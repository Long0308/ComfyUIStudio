"""``jjv qa transitions``: full-resolution frames across every transition window, a contact sheet per boundary and
four recorded checks.

1. **Ghost / double exposure** (picture <-> picture, window > 0 frames): the Q4 edge-correlation proxy
   (``q4_ghost._proxy``) on analysis-scale frames made from the FULL-resolution ones.  A preset that shows both
   shots by design (``shows_both``) may blend only when the boundary says continuity ``agree``; every other
   preset FAILS at ``ghost_fail`` (measured clean 0.00-0.02, double exposure 0.21-0.35).  Consecutive window
   frames that are (near) identical are recorded as ``duplicate_pairs``.
2. **Dip peak vs speech** (dip / flash family): the peak is the scheduled full-white frame(s) AND the measured
   extreme-luma frame; the next line's first spoken frame (word timing) must come AFTER the last peak frame.
   ``bright_reach`` records how long the overlay (sparkles included) stays above the incoming picture.
3. **Same seat = cut or cut_push**: same seat = declared (``framing: same_framing`` / ``layout_change: false`` /
   ``--layout-same-framing``) or measured (NCC of the last clean frame before and the first after >=
   ``q3_flash.same_framing_ncc_min``); any other visible type there FAILS.  A declaration can never turn a
   measured same-seat pair into a layout change.
4. **Luma step at a non-flash boundary** (a flash hiding in a cut): step above ``q3_flash.step_max_at_cut`` FAILS.

A boundary whose frames are not in the file is SKIPPED (a clip run); all skipped = UNCERTAIN.  Evidence that is
incomplete is never a silent PASS: a window with missing frames records a ghost check UNCERTAIN (listing them), a
luma step is only taken between adjacent frames (gaps are listed, UNCERTAIN), a dip with no readable window frame is
UNCERTAIN, and a same-seat NCC in the grey band ``[same_seat_grey_ncc_min, same_framing_ncc_min)`` of
``recipes/qa/transitions-gates-v001.json`` is UNCERTAIN.  Long windows are read in chunks (analysis size only).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file
from ..editorial import presets
from .gates import FAIL, PASS, UNCERTAIN, roll_up
from .gates import q4_ghost
from .gates.q3_flash import _small, ncc
from .review_media import extract_frames, numpy_module, write_png
from .transitions_load import Row, is_graphic

SKIPPED = "SKIPPED"
SAME_SEAT_OK_TYPES = ("cut", "cut_push", "none")
# Recorded-check constants of this gate (the shared thresholds stay in recipes/qa/review-gates-v001.json).
PARAMS = {"duplicate_mad_max": 0.25, "bright_reach_tol": 3.0, "cut_context_frames": 2}
GATE_RECIPE = SKILL_ROOT / "recipes" / "qa" / "transitions-gates-v001.json"
GATE_RECIPE_SCHEMA = "jjv/qa-transitions-recipe/v1"
SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def load_gate_recipe(path: Path | None = None) -> dict:
    """The thresholds of this gate that are not in the shared review recipe (grey band, chunk size)."""
    target = Path(path) if path else GATE_RECIPE
    doc = read_json(target)
    if not isinstance(doc, dict) or doc.get("schema") != GATE_RECIPE_SCHEMA:
        raise Uncertain(f"{target.name}: not a {GATE_RECIPE_SCHEMA} document")
    grey, chunk = doc.get("same_seat_grey_ncc_min"), doc.get("extract_chunk_frames")
    if not isinstance(grey, (int, float)) or isinstance(grey, bool) or not 0.0 <= grey <= 1.0:
        raise Refused(f"{target.name}: same_seat_grey_ncc_min must be a number in [0, 1]")
    if not isinstance(chunk, int) or isinstance(chunk, bool) or chunk < 1:
        raise Refused(f"{target.name}: extract_chunk_frames must be a positive integer")
    return {**doc, "sha256": sha256_file(target)}


def _gate(recipe: dict) -> dict:
    return recipe.get("transitions") or load_gate_recipe()


def analysis_gray(rgb: Any, width: int, height: int) -> Any:
    """BT.601 luma of a full-resolution RGB frame, area-averaged to the Q3/Q4 analysis size (nearest when not integral)."""
    np = numpy_module()
    gray = rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114
    h, w = gray.shape
    if h % height == 0 and w % width == 0:
        gray = gray.reshape(height, h // height, width, w // width).mean((1, 3))
    else:
        gray = gray[np.ix_(np.arange(height) * h // height, np.arange(width) * w // width)]
    return np.clip(np.rint(gray), 0, 255).astype(np.uint8)


def _bounds(row: Row) -> tuple[int, int, list[int]]:
    """(frame before the window, frame after it, frames to extract)."""
    t = row.t
    if t.frames > 0:
        before, after = t.start - 1, t.end_exclusive
        return before, after, list(range(before, after + 1))
    c = PARAMS["cut_context_frames"]
    return t.boundary - 1, t.boundary, list(range(t.boundary - c, t.boundary + c))


def _is_picture(row: Row, q4: dict) -> bool:
    return not is_graphic(row.t.from_id, q4) and not is_graphic(row.t.to_id, q4)


def _preset(row: Row) -> dict:
    return presets.catalog()["presets"].get(row.preset or "") or {}


def _sheet(got: dict, tiles: list[int], native: tuple[int, int], columns: int, out: Path, ffmpeg: str) -> dict:
    np = numpy_module()
    width, height = native
    rows = -(-len(tiles) // columns)
    canvas = np.zeros((rows * height, columns * width, 3), dtype=np.uint8)
    for k, frame in enumerate(tiles):
        r, c = divmod(k, columns)
        canvas[r * height:(r + 1) * height, c * width:(c + 1) * width] = got[frame]
    write_png(out, canvas, ffmpeg)
    return {"file": f"sheets/{out.name}", "sha256": sha256_file(out), "tiles": tiles, "tile_size": [width, height],
            "columns": columns}


def _ghost_incomplete(out: dict, missing: list[int]) -> None:
    out["ghost"] = {"status": UNCERTAIN, "missing_frames": missing, "reasons": [
        f"{len(missing)} window frame(s) missing from the file {missing[:12]}: double exposure was NOT measured, "
        "a critic must look at the sheet"]}


def _ghost(out: dict, row: Row, gray: dict, before: int, after: int, recipe: dict) -> None:
    p, t, np = recipe["q4_ghost"], row.t, numpy_module()
    stack = np.stack([gray[f] for f in range(before, after + 1)])
    proxy = q4_ghost._proxy(t, stack, before, p)
    shows_both = bool(_preset(row).get("shows_both")) or t.type in p["both_shots_types"]
    pairs = [[a, a + 1] for a in range(before, after) if float(np.abs(gray[a].astype(float) - gray[a + 1]).mean()) < PARAMS["duplicate_mad_max"]]
    check = {**(proxy or {}), "shows_both_by_design": shows_both, "duplicate_pairs": pairs,
             "ghost_fail": p["ghost_fail"], "ghost_warn": p["ghost_warn"], "status": PASS, "reasons": []}
    if proxy is None:
        check.update(status=UNCERTAIN, reasons=["frames before/after the window are not in the file"])
    elif shows_both and t.continuity != "agree":
        check.update(status=FAIL, reasons=[f"'{t.type}' shows both shots in one frame but continuity is {t.continuity!r} "
                                           "(only 'agree' allows a blend): use dip_white on a real angle change, whip or cut_push"])
        if proxy["ghost_excess"] >= p["ghost_fail"]:
            check["reasons"].append(f"double exposure measured: ghost excess {proxy['ghost_excess']} >= {p['ghost_fail']}")
    elif not shows_both and proxy["ghost_excess"] >= p["ghost_fail"]:
        check.update(status=FAIL, reasons=[f"double exposure: ghost excess {proxy['ghost_excess']} >= {p['ghost_fail']} "
                                           f"at a '{t.type}' boundary that must show one shot per frame"])
    elif not shows_both and proxy["ghost_excess"] >= p["ghost_warn"]:
        check.update(status=UNCERTAIN, reasons=[f"ghost excess {proxy['ghost_excess']} in the grey zone: a critic must look at the sheet"])
    out["ghost"] = check


def _same_seat(out: dict, row: Row, gray: dict, before: int, after: int, recipe: dict, declared: frozenset[int]) -> None:
    t, limit, grey = row.t, recipe["q3_flash"]["same_framing_ncc_min"], _gate(recipe)["same_seat_grey_ncc_min"]
    if grey >= limit:
        raise Refused(f"transitions recipe: same_seat_grey_ncc_min {grey} must be below same_framing_ncc_min {limit}")
    measured = ncc(_small(gray[before]), _small(gray[after]))
    why = [w for w, hit in (("framing: same_framing", row.framing == "same_framing"), ("layout_change: false", t.layout_change is False),
                            ("--layout-same-framing", t.boundary in declared)) if hit]
    same = bool(why) or measured >= limit
    check = {"ncc": round(measured, 3), "ncc_limit": limit, "ncc_grey_min": grey, "declared": why, "same_seat": same, "status": PASS, "reasons": []}
    if same and t.type not in SAME_SEAT_OK_TYPES:
        how = "declared " + "/".join(why) if why else f"measured ncc {measured:.2f} >= {limit}"
        check.update(status=FAIL, reasons=[f"same seat ({how}) but the boundary is '{t.type}': use cut or cut_push, "
                                           "flash/dissolve/whip only when angle or scene changes"])
    elif t.type not in SAME_SEAT_OK_TYPES and measured >= grey:
        check.update(status=UNCERTAIN, reasons=[f"near same-seat: ncc {measured:.3f} is in the grey band [{grey}, {limit}) at a "
                                                f"'{t.type}' boundary: review the sheet (is the angle really different?)"])
    out["same_seat"] = check


def _luma(gray: dict) -> dict:
    return {f: float(g.mean(dtype="float64")) for f, g in gray.items()}


def _is_dip(row: Row, recipe: dict) -> bool:
    return "schedule" in _preset(row) or row.t.type in recipe["q3_flash"]["needs_layout_change_types"]


def _peak_frames(row: Row) -> list[int]:
    return [row.t.boundary + s["t"] for s in _preset(row).get("schedule", []) if s["white"] >= 1.0]


def _dip(out: dict, row: Row, luma: dict, before: int, after: int, spoken: dict, q4: dict) -> None:
    t = row.t
    base = (luma[before] + luma[after]) / 2
    window = [f for f in range(t.start, t.end_exclusive) if f in luma]
    measured = max(window, key=lambda f: abs(luma[f] - base)) if window else None
    scheduled = _peak_frames(row)
    peak = max(scheduled + ([measured] if measured is not None else []), default=None)
    reach = [f for f in range(peak if peak is not None else t.boundary, t.end_exclusive) if f in luma and abs(luma[f] - luma[after]) > PARAMS["bright_reach_tol"]]
    check = {"scheduled_peak_frames": scheduled, "measured_peak_frame": measured,
             "measured_peak_excess": None if measured is None else round(abs(luma[measured] - base), 1),
             "peak_frame_checked": peak, "bright_reach_last_frame": max(reach, default=None),
             "sparkles": row.params.get("sparkles"), "status": PASS, "reasons": []}
    if measured is None:
        check.update(status=UNCERTAIN, reasons=[f"no window frame ({t.start}..{t.end_exclusive - 1}) is readable"
                                                + (": the dip peak is unverified" if peak is None else ": only the scheduled peak is known, not measured")])
    info = spoken.get(t.to_id)
    if info is None:
        if is_graphic(t.to_id, q4):
            check["note"] = "incoming side is a graphic: no spoken line to protect"
        else:
            check.update(status=UNCERTAIN, reasons=check["reasons"] + [f"no word timing for line {t.to_id!r} (--timing): the first spoken frame is unknown"])
    elif info["frame"] is None:
        check["note"] = f"line {t.to_id} has no spoken words"
    else:
        check.update(first_spoken_frame=info["frame"], first_spoken_word=info["word"], first_spoken_source=info["source"],
                     margin_frames=None if peak is None else info["frame"] - peak)
        if peak is not None and info["frame"] <= peak:
            check.update(status=FAIL, reasons=[f"dip peak (frame {peak}) overlaps the first spoken frame {info['frame']} "
                                               f"of {t.to_id} ({info['word']!r}, {info['source']}): the first word is lost in the white"])
    out["dip"] = check


def _step(out: dict, row: Row, luma: dict, expected: list[int], recipe: dict) -> None:
    """Luma step between ADJACENT frames only; a missing frame leaves a gap that is listed, never bridged."""
    p, frames = recipe["q3_flash"], sorted(luma)
    steps = [abs(luma[b] - luma[a]) for a, b in zip(frames, frames[1:]) if b == a + 1]
    gaps = [[a, b] for a, b in zip(frames, frames[1:]) if b != a + 1 and a >= min(expected) - 1 and b <= max(expected) + 1]
    missing = [f for f in expected if f not in luma]
    worst = round(max(steps, default=0.0), 1)
    check = {"max_step": worst, "step_max_at_cut": p["step_max_at_cut"], "gaps": gaps, "status": PASS, "reasons": []}
    if row.t.type not in p["spike_allowed_types"] and worst > p["step_max_at_cut"]:
        check.update(status=FAIL, reasons=[f"luma step {worst} at a '{row.t.type}' boundary exceeds {p['step_max_at_cut']}"])
    elif missing or not steps:
        check.update(status=UNCERTAIN, reasons=[f"luma step not measured across missing frame(s) {missing[:12]}"
                                                if missing else "no two adjacent frames to measure a luma step"])
    out["luma_step"] = check


def judge_row(row: Row, got: dict, native: tuple[int, int], recipe: dict, spoken: dict, declared: frozenset[int],
              out_dir: Path, ffmpeg: str, extra_gray: dict | None = None) -> dict:
    """``got`` = full-resolution frames (sheet tiles); ``extra_gray`` = analysis-size gray of the other window frames."""
    t, q3, q4 = row.t, recipe["q3_flash"], recipe["q4_ghost"]
    before, after, wanted = _bounds(row)
    picture = _is_picture(row, q4)
    result: dict = {"id": t.id, "boundary": t.boundary, "type": t.type, "preset": row.preset, "from": t.from_id, "to": t.to_id,
                    "kind": "picture" if picture else "graphic/mixed", "window": [t.start, t.end_exclusive],
                    "frames": t.frames, "continuity": t.continuity, "status": PASS, "reasons": [], "checks": {}}
    if before < 0:
        result.update(status=UNCERTAIN, reasons=[f"the window starts at frame {t.start}: there is no frame before it, so the "
                                                 "boundary cannot be measured (shift the cut or judge it by eye)"])
        return result
    if before not in got or after not in got:
        result.update(status=SKIPPED, reasons=["the frames before/after the window are not in the file"])
        return result
    tiles = q4_ghost.sheet_frames(before, t.start, t.end_exclusive, after, q4["sheet_max_tiles"]) if t.frames > 0 else wanted
    tiles = [f for f in tiles if f in got]
    result["sheet"] = _sheet(got, tiles, native, q4["sheet_columns"], out_dir / "sheets" / f"tr-{SAFE.sub('_', t.id)}-f{t.start}-f{t.end_exclusive}.png", ffmpeg)
    gray = {f: analysis_gray(got[f], q3["analysis_width"], q3["analysis_height"]) for f in got}
    gray.update(extra_gray or {})
    result["frames_measured"] = sorted(gray)
    checks = result["checks"]
    missing = [f for f in range(before, after + 1) if f not in gray] if t.frames > 0 else []
    if picture and t.frames > 0:
        _ghost_incomplete(checks, missing) if missing else _ghost(checks, row, gray, before, after, recipe)
    if picture:
        _same_seat(checks, row, gray, before, after, recipe, declared)
        _step(checks, row, _luma(gray), wanted, recipe)
    if t.frames > 0 and _is_dip(row, recipe):
        _dip(checks, row, _luma(gray), before, after, spoken, q4)
    result["status"] = roll_up(c["status"] for c in checks.values())
    result["reasons"] = [f"{name}: {reason}" for name, c in checks.items() for reason in c["reasons"]]
    return result


def _read_window(video: Path, ffmpeg: str, row: Row, recipe: dict, native: tuple[int, int], origin: int) -> tuple[dict, dict]:
    """(full-resolution sheet tiles, analysis gray of every other window frame read in small chunks)."""
    before, after, wanted = _bounds(row)
    q3, q4, t = recipe["q3_flash"], recipe["q4_ghost"], row.t
    tiles = wanted if t.frames == 0 else q4_ghost.sheet_frames(before, t.start, t.end_exclusive, after, q4["sheet_max_tiles"])
    got = extract_frames(video, ffmpeg, tiles, native[0], native[1], origin=origin, native=native)
    extra: dict = {}
    if t.frames > 0 and _is_picture(row, q4) and before in got and after in got:
        rest, size = [f for f in wanted if f not in got], _gate(recipe)["extract_chunk_frames"]
        for k in range(0, len(rest), size):
            for f, rgb in extract_frames(video, ffmpeg, rest[k:k + size], native[0], native[1], origin=origin, native=native).items():
                extra[f] = analysis_gray(rgb, q3["analysis_width"], q3["analysis_height"])
    return got, extra


def run_transitions(*, rows: tuple[Row, ...], recipe: dict, video: Path, ffmpeg: str, native: tuple[int, int],
                    origin: int, spoken: dict, declared: frozenset[int], out_dir: Path) -> dict:
    """Judge every boundary; ``gate`` block of the receipt (the caller adds provenance)."""
    gate_recipe = _gate(recipe)
    recipe = {**recipe, "transitions": gate_recipe}
    results = []
    for row in rows:
        got, extra = _read_window(video, ffmpeg, row, recipe, native, origin)
        results.append(judge_row(row, got, native, recipe, spoken, declared, out_dir, ffmpeg, extra))
    judged = [r for r in results if r["status"] != SKIPPED]
    if not judged:
        raise Uncertain("no transition window lies inside the file: nothing could be measured (use --frame-origin for a clip)")
    status = roll_up(r["status"] for r in judged)
    return {"gate": "TRANSITIONS_FULLRES", "status": status, "rows": results,
            "counts": {"boundaries": len(results), "judged": len(judged), "skipped": len(results) - len(judged),
                       "fail": sum(r["status"] == FAIL for r in judged), "uncertain": sum(r["status"] == UNCERTAIN for r in judged)},
            "failures": [f"{r['id']}: {x}" for r in judged if r["status"] != PASS for x in r["reasons"]],
            "sheets": [r["sheet"]["file"] for r in results if r.get("sheet")],
            "params": {**PARAMS, **{k: recipe["q4_ghost"][k] for k in ("ghost_fail", "ghost_warn")},
                       "same_framing_ncc_min": recipe["q3_flash"]["same_framing_ncc_min"],
                       "same_seat_grey_ncc_min": gate_recipe["same_seat_grey_ncc_min"],
                       "extract_chunk_frames": gate_recipe["extract_chunk_frames"],
                       "transitions_recipe": {"id": gate_recipe.get("id"), "sha256": gate_recipe["sha256"]},
                       "step_max_at_cut": recipe["q3_flash"]["step_max_at_cut"]}}
