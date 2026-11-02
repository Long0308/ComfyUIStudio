"""Q1b caption gate: does the RENDERED karaoke caption light each word at its ``startF``?

Q1 (``engine/timing/q1.py``) checks timing DATA against the audio.  Nothing proved that the picture follows the data;
this gate reads the picture.  For every word (or ``sample_every``-th word plus every word after a pause):

1. the caption strip is cropped from the export (layout = remotion-kit constants in the recipe, scaled by
   video height / reference height);
2. the word boxes of the shot are located on one fully-lit reference frame (colour clusters left to right, per EN line);
   a box count different from the word count makes the shot UNCERTAIN, never a guess;
3. in a window ``[startF - window_before, startF + allowed_late + extra]`` (clipped to the frames where the caption panel
   is fully opaque) each frame is classified lit/unlit by COLOUR inside the word box: plain word = mint background or ink
   text, keyword = pink fill (the fill ramps over ``keyword_ramp_frames``);
4. PASS when ``first lit frame - startF`` is in ``[-early_max, allowed_late]`` (``allowed_late`` = ``plain_late_max_frames``
   or ``keyword_ramp_frames``) and no word lights before the word before it.

The report carries a NEGATIVE CONTROL: every passing word is judged again against an expected start shifted
``shift_frames`` (5) later and earlier; each shifted judgement must FAIL, otherwise the tolerance is too wide to prove
anything and the gate is UNCERTAIN.  The expected timing is the config's: to check an export against corrected timing,
pass the corrected config (the picture of an older cut then fails on every word that moved).

Exit code of the stand-alone entry: 0 PASS, 1 FAIL, 2 UNCERTAIN.  CPU only (ffmpeg + numpy), no network.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from engine.config.loader import SKILL_ROOT  # noqa: E402
from engine.core.errors import EngineError, Refused, Uncertain, exit_code_for  # noqa: E402
from engine.core.provenance import stamp  # noqa: E402
from engine.core.io import read_json, sha256_file, write_json_atomic  # noqa: E402
from engine.qa.gates import FAIL, PASS, UNCERTAIN, roll_up  # noqa: E402
from engine.qa.review_media import find_ffprobe, numpy_module, probe  # noqa: E402
from engine.seedvr2.seam_media import ffmpeg_flags, find_ffmpeg  # noqa: E402

RECIPE_SCHEMA = "jjv/qa-q1b-recipe/v1"
DEFAULT_RECIPE = SKILL_ROOT / "recipes" / "qa" / "q1b-caption-v001.json"
EXIT = {PASS: 0, FAIL: 1, UNCERTAIN: 2}
MAX_RANGES_PER_CALL = 300


def load_recipe(path: Path | None = None) -> tuple[dict, str]:
    target = Path(path) if path else DEFAULT_RECIPE
    recipe = read_json(target)
    if not isinstance(recipe, dict) or recipe.get("schema") != RECIPE_SCHEMA:
        raise Uncertain(f"{target.name}: not a {RECIPE_SCHEMA} document")
    for key in ("layout", "timing", "segment", "classify", "control"):
        if not isinstance(recipe.get(key), dict):
            raise Uncertain(f"{target.name}: block {key!r} is missing")
    return recipe, sha256_file(target)


# ----------------------------------------------------------------------------------------------- the plan (pure)
def judge(first_lit: int | None, start: int, allowed_late: int, early_max: int) -> tuple[str, int | None]:
    """(status, first_lit - start); ``first_lit`` None = never lit inside the window."""
    if first_lit is None:
        return "FAIL-late", None
    delta = first_lit - start
    if delta < -early_max:
        return "FAIL-early", delta
    return ("FAIL-late" if delta > allowed_late else PASS), delta


def shots_of(config: dict, fps: float, t: dict, every: int) -> list[dict]:
    """Per dialogue shot: its words (startF/keyword/after_pause/sampled) and the frame range where the panel is opaque."""
    shots = []
    for entry in config.get("dialogue") or []:
        words, start = entry.get("words") or [], entry.get("start_frame")
        if not words or not isinstance(start, int):
            continue
        duration = entry.get("duration_frames", entry.get("end_frame_exclusive", start) - start)
        speech_end = entry.get("speech_end_in_window_s")
        hide = min(duration, math.ceil((speech_end + t["hide_after_speech_s"]) * fps)) if speech_end is not None else duration
        rows, prev_end = [], None
        for i, word in enumerate(words):
            start_f = word.get("startF")
            if isinstance(start_f, bool) or not isinstance(start_f, int):
                raise Refused(f"{entry.get('id')}: word {i} has no integer startF")
            pause = prev_end is None or start_f - prev_end >= t["pause_min_frames"]
            rows.append({"index": i, "word": str(word.get("w", "")), "startF": start_f, "keyword": bool(word.get("keyword")),
                         "after_pause": pause, "sampled": every <= 1 or i % every == 0 or pause})
            prev_end = word.get("endF", start_f)
        shots.append({"id": str(entry.get("id")), "start": start, "words": rows,
                      "open_lo": start + t["panel_fade_in_frames"], "open_hi": start + hide - t["panel_fade_out_frames"] - 1})
    return shots


def window_of(word: dict, shot: dict, t: dict) -> tuple[int, int] | None:
    """Inclusive global frame window to classify, or None when it cannot test the word (reason in ``why``)."""
    late = t["keyword_ramp_frames"] if word["keyword"] else t["plain_late_max_frames"]
    lo, hi = max(word["startF"] - t["window_before_frames"], shot["open_lo"]), min(word["startF"] + late + t["window_after_extra_frames"], shot["open_hi"])
    if lo > word["startF"] - 1:
        word["why"] = "no fully opaque frame before startF (caption panel is still fading in)"
    elif hi < word["startF"] + late:
        word["why"] = "caption panel is fading out before the end of the tolerance window"
    else:
        return lo, hi
    return None


# --------------------------------------------------------------------------------------------- picture reading
def geometry(r: dict, width: int, height: int) -> dict:
    """Crop rectangle of the EN lines and the row span of each EN line (line 0 = bottom), in native pixels."""
    s, L = height / r["layout"]["reference_height"], r["layout"]
    en_bottom = L["reference_height"] - L["panel_bottom"] - L["panel_pad_bottom"] - L["vi_line_px"] - L["vi_gap_px"]
    top = en_bottom - L["en_lines_max"] * L["en_line_px"]
    y0, y1 = int(math.floor(top * s)), int(math.ceil(en_bottom * s))
    x0 = int(round((L["panel_left"] + L["panel_pad_x"]) * s))
    x1 = width - int(round((L["panel_right"] + L["panel_pad_x"]) * s))
    if x1 <= x0 or y0 < 0:
        raise Uncertain(f"video {width}x{height} is too small for the caption layout")
    spans = [(int(round((en_bottom - (k + 1) * L["en_line_px"]) * s)) - y0, int(round((en_bottom - k * L["en_line_px"]) * s)) - y0)
             for k in range(L["en_lines_max"])]
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "spans": spans, "scale": s}


def stream_band(video: Path, ffmpeg: str, frames: list[int], geo: dict, origin: int) -> Iterator[tuple[int, Any]]:
    """Yield ``(global frame, RGB band (h, w, 3))`` for the wanted frames in ascending order (frames past EOF are absent)."""
    np = numpy_module()
    wanted = sorted({f - origin for f in frames if f - origin >= 0})
    ranges: list[list[int]] = []
    for n in wanted:
        if ranges and n == ranges[-1][1] + 1:
            ranges[-1][1] = n
        else:
            ranges.append([n, n])
    size = geo["w"] * geo["h"] * 3
    for part in (ranges[i:i + MAX_RANGES_PER_CALL] for i in range(0, len(ranges), MAX_RANGES_PER_CALL)):
        select = "+".join(f"between(n,{a},{b})" for a, b in part)
        order = iter(n for a, b in part for n in range(a, b + 1))
        command = [ffmpeg, "-v", "error", "-i", str(video), "-an", "-vf", f"select='{select}',crop={geo['w']}:{geo['h']}:{geo['x']}:{geo['y']}",
                   "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        with tempfile.TemporaryFile() as errors:
            try:
                proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, creationflags=ffmpeg_flags())
            except OSError as error:
                raise Uncertain(f"cannot run ffmpeg: {error}") from error
            got = 0
            while True:
                chunk = proc.stdout.read(size)
                if len(chunk) < size:
                    break
                got += 1
                yield next(order) + origin, np.frombuffer(chunk, np.uint8).reshape(geo["h"], geo["w"], 3)
            proc.stdout.close()
            code = proc.wait()
            errors.seek(0)
            if (code != 0 and got == 0) or (chunk and len(chunk) < size):
                raise Uncertain(f"ffmpeg could not decode {video.name}: {errors.read().decode(errors='replace')[-200:]}")


def _clusters(columns: Any, gap: int, minimum: int) -> list[tuple[int, int]]:
    np = numpy_module()
    index = np.flatnonzero(columns)
    if index.size == 0:
        return []
    cut = np.flatnonzero(np.diff(index) > gap)
    first, last = np.r_[index[0], index[cut + 1]], np.r_[index[cut], index[-1]]
    return [(int(a), int(b) + 1) for a, b in zip(first, last) if b + 1 - a >= minimum]


def _boxes_for(ref: Any, spans: list[tuple[int, int]], geo: dict, seg: dict) -> list[list[tuple[int, int, int, int]]]:
    """Word boxes ``(x0, y0, x1, y1)`` per EN line (top line first) when the caption has ``len(spans)`` lines."""
    np = numpy_module()
    top, bottom = max(spans[-1][0], 0), min(spans[0][1], ref.shape[0])
    pixels = ref.astype(np.int32)
    paper = np.median(pixels[top:bottom].reshape(-1, 3), axis=0)  # only rows inside the panel for this line count
    mask = np.sqrt(((pixels - paper) ** 2).sum(axis=2)) > seg["ink_dist_min"]
    gap = max(1, int(round(seg["min_gap_px"] * geo["scale"])))
    lines = []
    for lo, hi in reversed(spans):
        lo, hi = max(lo, 0), min(hi, ref.shape[0])
        boxes = []
        for a, b in _clusters(mask[lo:hi].any(axis=0), gap, max(1, int(seg["min_word_px"] * geo["scale"]))):
            rows = np.flatnonzero(mask[lo:hi, a:b].any(axis=1))
            boxes.append((a, lo + int(rows[0]), b, lo + int(rows[-1]) + 1))
        lines.append(boxes)
    return lines


def locate_boxes(ref: Any, count: int, geo: dict, seg: dict) -> list[tuple[int, int, int, int]]:
    """Word boxes of a fully-lit reference band in reading order.  The line count is not known, so 1..max lines are tried;
    the layout is accepted only when exactly ``count`` boxes are found and every line holds one; else ``Uncertain``."""
    tried = []
    for n in range(1, len(geo["spans"]) + 1):
        lines = _boxes_for(ref, geo["spans"][:n], geo, seg)
        found = [box for line in lines for box in line]
        tried.append(f"{len(found)} boxes with {n} line(s)")
        if len(found) == count and all(lines):
            return found
    raise Uncertain(f"layout not recognised for {count} words: " + ", ".join(tried))


def is_lit(region: Any, keyword: bool, c: dict) -> bool:
    """Colour test inside one word box (see module doc)."""
    np = numpy_module()
    r, g, b = (region[..., i].astype(np.int32) for i in range(3))
    if keyword:
        return float(((r - g >= c["pink_rg_min"]) & (r >= c["pink_r_min"])).mean()) >= c["pink_frac_min"]
    mint = ((g - (r + b) // 2 >= c["mint_chroma_min"]) & (r >= c["mint_r_min"])).mean()
    dark = ((299 * r + 587 * g + 114 * b) // 1000 <= c["dark_luma_max"]).mean()
    return bool(mint >= c["mint_frac_min"] or dark >= c["dark_frac_min"])


# ------------------------------------------------------------------------------------------------- the gate
def _measure_shot(shot: dict, frames: dict[int, Any], ref_frame: int, geo: dict, r: dict) -> None:
    """Fill ``first_lit`` / ``status`` of every testable word of ``shot`` from the buffered ``frames`` (in place)."""
    t, early = r["timing"], r["timing"]["early_max_frames"]
    try:
        if ref_frame not in frames:
            raise Uncertain(f"reference frame {ref_frame} is not in the file")
        boxes = locate_boxes(frames[ref_frame], len(shot["words"]), geo, r["segment"])
    except Uncertain as error:
        for word in shot["words"]:
            word.update(status=UNCERTAIN, why=str(error))
        return
    for word, box in zip(shot["words"], boxes):
        win = word.get("window")
        word["box"] = list(box)
        if win is None:
            continue
        lo, hi = win
        if lo not in frames:
            word.update(status="n/a", why=f"frame {lo} is not in the file")
            continue
        late = t["keyword_ramp_frames"] if word["keyword"] else t["plain_late_max_frames"]
        lit = [f for f in range(lo, hi + 1) if f in frames and is_lit(frames[f][box[1]:box[3], box[0]:box[2]], word["keyword"], r["classify"])]
        word["first_lit"] = lit[0] if lit else None
        word["status"], word["delta_f"] = judge(word["first_lit"], word["startF"], late, early)
        word["lit_at_window_start"] = bool(lit) and lit[0] == lo
    measured = [w for w in shot["words"] if w.get("first_lit") is not None]
    for before, after in zip(measured, measured[1:]):  # a word must not light before the word spoken before it
        if after["first_lit"] < before["first_lit"] and before["status"] == PASS:
            before.update(status="FAIL-order", why=f"lit at f{before['first_lit']}, after the next word (f{after['first_lit']})")


def _control(words: list[dict], r: dict) -> dict:
    """Judge every passing word again against an expected start shifted by +-shift: every judgement must FAIL."""
    t, shift = r["timing"], r["control"]["shift_frames"]
    passing = [w for w in words if w.get("status") == PASS]
    missed = []
    for w in passing:
        late = t["keyword_ramp_frames"] if w["keyword"] else t["plain_late_max_frames"]
        for s in (shift, -shift):
            if judge(w["first_lit"], w["startF"] + s, late, t["early_max_frames"])[0] == PASS:
                missed.append(f"{w['shot']}:{w['word']} (shift {s:+d})")
    return {"shift_frames": shift, "status": "run" if passing else "not_run", "words_checked": len(passing),
            "detected": bool(passing) and not missed, "missed": missed[:12],
            "what": f"each passing word judged against startF +{shift} and -{shift}; every judgement must FAIL"}


def run_q1b(config: dict, video: Path, *, ffmpeg: str | None = None, recipe: dict | None = None, recipe_sha256: str | None = None,
            origin: int = 0) -> dict:
    """Gate dict (``gate``/``status``/``failures``/``words``/``control``/``timing_s``) for ``video`` against ``config`` timing."""
    started = time.perf_counter()
    if recipe is None:
        recipe, recipe_sha256 = load_recipe()
    ffmpeg = ffmpeg or find_ffmpeg()
    if not Path(video).is_file():
        raise Uncertain(f"video not found: {video}")
    fps = config.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise Refused(f"config: fps must be a positive number, got {fps!r}")
    info = probe(Path(video), find_ffprobe(ffmpeg))
    geo = geometry(recipe, info.width, info.height)
    t = recipe["timing"]
    shots = shots_of(config, float(fps), t, int(recipe.get("sample_every", 1)))
    plan: dict[int, set[int]] = {}
    refs: dict[int, int] = {}
    end = origin + info.frames if info.frames else None
    for n, shot in enumerate(shots):
        if shot["open_hi"] < origin or (end is not None and shot["open_lo"] >= end):  # a clip holds only part of the film
            for word in shot["words"]:
                word.update(status="n/a", why="shot is not in this file")
            continue
        wanted = set()
        for word in shot["words"]:
            if word["sampled"]:
                window = window_of(word, shot, t)
                if window:
                    word["window"] = window
                    wanted.update(range(window[0], window[1] + 1))
            else:
                word["why"] = "not sampled (sample_every)"
        refs[n] = min(shot["words"][-1]["startF"] + t["ref_after_last_start_frames"], shot["open_hi"])
        plan[n] = wanted | {refs[n]}
    last_of = {n: max(f) for n, f in plan.items()}
    owners: dict[int, list[int]] = {}
    for n, frames in plan.items():
        for f in frames:
            owners.setdefault(f, []).append(n)
    buffers: dict[int, dict[int, Any]] = {n: {} for n in plan}
    done: set[int] = set()
    decode_s = 0.0
    mark = time.perf_counter()
    for frame, band in stream_band(Path(video), ffmpeg, sorted(owners), geo, origin):
        for n in owners.get(frame, ()):
            buffers[n][frame] = band
            if frame == last_of[n]:
                decode_s += time.perf_counter() - mark
                _measure_shot(shots[n], buffers.pop(n), refs[n], geo, recipe)
                done.add(n)
                mark = time.perf_counter()
    for n in set(plan) - done:  # the file ended before this shot's last wanted frame
        _measure_shot(shots[n], buffers.pop(n), refs[n], geo, recipe)
    words = [{"shot": s["id"], **{k: v for k, v in w.items() if k != "sampled"}} for s in shots for w in s["words"]]
    for w in words:
        w.setdefault("status", "n/a")
        if w["status"] == "n/a":
            w.setdefault("why", "not tested")
    control = _control(words, recipe)
    failures = [f"{w['shot']}:{w['word']}: {w['status']} (startF {w['startF']}, first lit {w.get('first_lit')})" + (f" - {w['why']}" if w.get("why") else "")
                for w in words if w["status"].startswith("FAIL")]
    failures += [f"{w['shot']}:{w['word']}: {w['why']}" for w in words if w["status"] == UNCERTAIN]
    tested = [w for w in words if w["status"] not in ("n/a", UNCERTAIN)]
    parts = [FAIL if any(w["status"].startswith("FAIL") for w in words) else PASS]
    control_bad = control["status"] == "run" and not control["detected"]
    if any(w["status"] == UNCERTAIN for w in words) or not tested or control_bad:
        parts.append(UNCERTAIN)
    if not tested:
        failures.append("no word could be tested")
    if control_bad:
        failures.append(f"negative control: a {control['shift_frames']} f shift was NOT flagged for {control['missed']}")
    return {"gate": "Q1b", "status": roll_up(parts), "failures": failures, "recipe": {"id": recipe["id"], "sha256": recipe_sha256},
            "summary": {"words": len(words), "tested": len(tested), "pass": sum(w["status"] == PASS for w in words),
                        "fail": sum(w["status"].startswith("FAIL") for w in words), "n/a": sum(w["status"] == "n/a" for w in words),
                        "uncertain": sum(w["status"] == UNCERTAIN for w in words),
                        "early": [f"{w['shot']}:{w['word']}" for w in words if w["status"] == "FAIL-early"]},
            "control": control, "words": words, "origin_frame": origin, "video": Path(video).name,
            "timing_s": {"decode": round(decode_s, 2), "total": round(time.perf_counter() - started, 2)}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="q1b-caption", description=__doc__.split("\n", 1)[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--recipe", default=None)
    parser.add_argument("--frame-origin", type=int, default=0, help="global frame number of the file's first frame (clips)")
    parser.add_argument("--out", default=None)
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args(argv)
    try:
        recipe, sha = load_recipe(Path(args.recipe) if args.recipe else None)
        report = run_q1b(read_json(Path(args.config)), Path(args.video), ffmpeg=args.ffmpeg, recipe=recipe, recipe_sha256=sha,
                         origin=args.frame_origin)
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    report = stamp(report)
    if args.out:
        write_json_atomic(Path(args.out), report, mode="ascii")
    print(f"Q1b {report['status']}  {report['summary']}  control detected={report['control']['detected']}  {report['timing_s']['total']} s",
          file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return EXIT[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
