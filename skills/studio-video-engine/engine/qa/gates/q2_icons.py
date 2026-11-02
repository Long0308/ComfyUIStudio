"""Q2 icons: coverage, hash binding, and opposite pairs that really look opposite.

* Coverage: every dialogue word flagged ``anchor`` has an icon event of the same shot within
  ``frame_tolerance`` frames of the word start, and every outro-card vocabulary term (``A and B`` = two parts)
  is covered by some event's word.
* Hash binding: the icon file on disk hashes to the event's ``icon_sha256``.
* Opposite pairs (recipe + ``qa.review.opposite_pairs``, e.g. warm/cold): the two icon FILES must not be the same
  image, must differ in mean colour (CIE76 delta E) and, when both are coloured, in hue; and the tile actually
  rendered at ``pop + onscreen_offset_frames`` must differ in colour too (the icon overlay is found as the
  densest changed ``tile_frac_of_width`` square against the frame before the pop inside ``roi``; an event whose
  predecessor icon is still on screen is skipped there, the baseline would hold the old icon).
"""

from __future__ import annotations

import colorsys
import re
import subprocess
from pathlib import Path
from typing import Any

from ...core.errors import Uncertain
from ...core.io import sha256_file
from ...core.paths import resolve_data_path
from ..review_media import extract_frames, numpy_module
from ...seedvr2.seam_media import ffmpeg_flags
from ..review_model import Model
from . import FAIL, PASS, UNCERTAIN

ICON_SIDE = 128


def stem(text: Any) -> str:
    word = re.sub(r"[^a-z]", "", str(text or "").lower())
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def tokens(text: Any) -> set[str]:
    return {stem(t) for t in re.split(r"[^A-Za-z]+", str(text or "")) if t}


def rgb_to_lab(rgb: Any) -> Any:
    np = numpy_module()
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]) @ c
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def delta_e(rgb_a: Any, rgb_b: Any) -> float:
    return float(numpy_module().linalg.norm(rgb_to_lab(rgb_a) - rgb_to_lab(rgb_b)))


def hue_sat(rgb: Any) -> tuple[float, float]:
    h, s, _ = colorsys.rgb_to_hsv(*(float(v) / 255.0 for v in rgb))
    return h * 360.0, s


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def icon_colour(path: Path, ffmpeg: str, alpha_min: int) -> list[float]:
    """Mean RGB of the opaque pixels of an icon PNG (decoded and area-scaled by ffmpeg)."""
    np = numpy_module()
    result = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-vf", f"scale={ICON_SIDE}:{ICON_SIDE}:flags=area",
                             "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, creationflags=ffmpeg_flags())
    if result.returncode != 0 or len(result.stdout) != ICON_SIDE * ICON_SIDE * 4:
        raise Uncertain(f"cannot decode icon {path.name}: {result.stderr.decode(errors='replace')[:160]}")
    px = np.frombuffer(result.stdout, np.uint8).reshape(-1, 4)
    opaque = px[px[:, 3] >= alpha_min]
    return [float(v) for v in (opaque if len(opaque) else px)[:, :3].mean(axis=0)]


def _resolve(raw: Any, root: Path) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    return resolve_data_path(path if path.is_absolute() else root / path)   # a retired absolute root is remapped


def coverage(model: Model, tolerance: int) -> tuple[list[str], list[dict], list[str]]:
    """(failures, per-anchor rows, orphan event ids)."""
    failures, rows, used = [], [], set()
    for word in (w for w in model.words if w["anchor"]):
        cands = [e for e in model.icons if e.get("shot") == word["shot"] and stem(e.get("word")) == stem(word["text"])]
        best = min(cands, key=lambda e: abs(e["frame"] - word["startF"]), default=None)
        off = None if best is None else best["frame"] - word["startF"]
        ok = best is not None and abs(off) <= tolerance
        if best is not None:
            used.add(best.get("id"))
        rows.append({"shot": word["shot"], "word": word["text"], "start_frame": word["startF"],
                     "event": best.get("id") if best else None, "offset_frames": off, "ok": ok})
        if not ok:
            failures.append(f"anchor word {word['text']!r} ({word['shot']} f{word['startF']}): "
                            + ("no icon event" if best is None else f"icon event {best.get('id')} is {off:+d} f away "
                               f"(tolerance {tolerance})"))
    covered = {stem(e.get("word")) for e in model.icons}
    for card in model.cards:
        for part in re.split(r"\band\b|[/&,]", str(card.get("term", "")), flags=re.I):
            if part.strip() and not (tokens(part) & covered):
                failures.append(f"vocabulary term {part.strip()!r} (outro card) has no icon event")
    return failures, rows, [str(e.get("id")) for e in model.icons if e.get("id") not in used]


def check_files(model: Model, root: Path, ffmpeg: str, p: dict) -> tuple[list[str], dict[str, dict]]:
    """Hash-bind every icon file and measure its colour; ``{icon path: info}``."""
    failures, info = [], {}
    for event in model.icons:
        path = _resolve(event.get("icon_path"), root)
        if path is None or not path.is_file():
            raise Uncertain(f"icon event {event.get('id')}: icon file {event.get('icon_path')!r} is not readable")
        key = str(path)
        if key not in info:
            sha = sha256_file(path)
            rgb = icon_colour(path, ffmpeg, p["alpha_min"])
            hue, sat = hue_sat(rgb)
            info[key] = {"name": path.name, "sha256": sha, "rgb": [round(v, 1) for v in rgb], "hue": round(hue, 1),
                         "saturation": round(sat, 3)}
        declared = event.get("icon_sha256")
        if declared and declared != info[key]["sha256"]:
            failures.append(f"icon {event.get('id')} ({path.name}): sha256 on disk differs from the event's")
        info[key].setdefault("events", []).append(event.get("id"))
    return failures, info


def find_tile(frame: Any, before: Any, p: dict) -> tuple[list[float], tuple[float, float], float]:
    """Mean RGB of the icon tile, its centre and the changed density of the densest tile-sized window."""
    np = numpy_module()
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = int(p["roi"][0] * w), int(p["roi"][1] * h), int(p["roi"][2] * w), int(p["roi"][3] * h)
    side = max(int(p["tile_frac_of_width"] * w), 4)
    a, b = frame[y0:y1, x0:x1].astype(np.int32), before[y0:y1, x0:x1].astype(np.int32)
    mask = (np.abs(a - b).max(axis=2) >= p["diff_threshold"]).astype(np.int64)
    ii = np.pad(mask.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    sums = ii[side:, side:] - ii[:-side, side:] - ii[side:, :-side] + ii[:-side, :-side]
    y, x = np.unravel_index(sums.argmax(), sums.shape)
    cy, cx = y + side / 2, x + side / 2
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
    disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= (side / 2 * p["disc_radius_frac"]) ** 2
    return [float(v) for v in a[disc].mean(axis=0)], (float(cx + x0), float(cy + y0)), float(sums.max() / (side * side))


def _active_before(event: dict, events: list[dict]) -> bool:
    return any(0 < event["frame"] - e["frame"] < e.get("total_frames", 32) for e in events if e is not event)


def screen_tiles(model: Model, video: Path, ffmpeg: str, native: tuple[int, int], origin: int, p: dict) -> dict[str, dict]:
    """``{event id: {rgb, centre, density} | {skipped: reason}}``."""
    wanted = {}
    for e in model.icons:
        wanted[e["id"]] = (e["frame"] - p["before_offset_frames"], e["frame"] + p["onscreen_offset_frames"])
    frames = extract_frames(video, ffmpeg, [i for pair in wanted.values() for i in pair], p["screen_width"],
                            p["screen_height"], origin=origin, native=native)
    out = {}
    for e in model.icons:
        pre, post = wanted[e["id"]]
        if _active_before(e, list(model.icons)):
            out[e["id"]] = {"skipped": "previous icon still on screen at the baseline frame"}
        elif pre not in frames or post not in frames:
            out[e["id"]] = {"skipped": "pop frames are not in the file"}
        else:
            rgb, centre, density = find_tile(frames[post], frames[pre], p)
            out[e["id"]] = {"rgb": [round(v, 1) for v in rgb], "centre": [round(c, 1) for c in centre],
                            "density": round(density, 2)}
    return out


def check_pairs(model: Model, files: dict[str, dict], tiles: dict[str, dict], p: dict) -> tuple[list[str], list[dict]]:
    failures, rows = [], []
    for a, b in p["opposite_pairs"]:
        ea = [e for e in model.icons if stem(e.get("word")) == stem(a)]
        eb = [e for e in model.icons if stem(e.get("word")) == stem(b)]
        if not ea or not eb:
            continue
        row: dict = {"pair": [a, b], "status": PASS, "reasons": []}
        info = lambda ev: next(v for v in files.values() if ev["id"] in v["events"])  # noqa: E731
        fa, fb = info(ea[0]), info(eb[0])
        row["files"] = {a: fa["name"], b: fb["name"]}
        row["delta_e_file"] = round(delta_e(fa["rgb"], fb["rgb"]), 1)
        if fa["sha256"] == fb["sha256"] or {i["sha256"] for i in map(info, ea)} & {i["sha256"] for i in map(info, eb)}:
            row["reasons"].append(f"'{a}' and '{b}' use the identical icon image ({fa['name']})")
        elif row["delta_e_file"] < p["min_delta_e_file"]:
            row["reasons"].append(f"icon colours too similar: delta E {row['delta_e_file']} < {p['min_delta_e_file']}")
        elif min(fa["saturation"], fb["saturation"]) >= p["hue_min_saturation"]:
            dist = hue_distance(fa["hue"], fb["hue"])
            row["hue_distance_deg"] = round(dist, 1)
            if dist < p["min_hue_distance_deg"]:
                row["reasons"].append(f"icon hues too close: {dist:.0f} deg < {p['min_hue_distance_deg']}")
        row["screen"] = _screen_pairs(ea, eb, tiles, p, row)
        if row["reasons"]:
            row["status"] = FAIL
            failures += [f"pair {a}/{b}: {r}" for r in row["reasons"]]
        rows.append(row)
    return failures, rows


def _screen_pairs(ea: list[dict], eb: list[dict], tiles: dict, p: dict, row: dict) -> list[dict]:
    out = []
    for x in ea:
        for y in eb:
            if x["shot"] != y["shot"]:
                continue
            tx, ty = tiles.get(x["id"], {}), tiles.get(y["id"], {})
            if "rgb" not in tx or "rgb" not in ty:
                out.append({"events": [x["id"], y["id"]], "skipped": tx.get("skipped") or ty.get("skipped")})
                continue
            de = round(delta_e(tx["rgb"], ty["rgb"]), 1)
            out.append({"events": [x["id"], y["id"]], "delta_e_screen": de})
            if de < p["min_delta_e_screen"]:
                row["reasons"].append(f"tiles on screen look the same: {x['id']}/{y['id']} delta E {de} < "
                                      f"{p['min_delta_e_screen']}")
    return out


def run(model: Model, recipe: dict, video: Path, ffmpeg: str, root: Path, native: tuple[int, int], origin: int = 0) -> dict:
    p = recipe["q2_icons"]
    if not model.icons or not model.words:
        return {"gate": "Q2", "status": UNCERTAIN, "failures": [],
                "note": "no icon events or no dialogue words in the config: nothing to check"}
    cover, anchors, orphans = coverage(model, p["frame_tolerance"])
    file_fail, files = check_files(model, root, ffmpeg, p)
    tiles = screen_tiles(model, video, ffmpeg, native, origin, p)
    pair_fail, pairs = check_pairs(model, files, tiles, p)
    hidden = [f"icon {k} not visible at pop+{p['onscreen_offset_frames']} (changed density {v['density']} < "
              f"{p['min_tile_density']})" for k, v in tiles.items() if "density" in v and v["density"] < p["min_tile_density"]]
    failures = cover + file_fail + pair_fail + hidden
    return {"gate": "Q2", "status": FAIL if failures else PASS, "failures": failures, "anchors_checked": len(anchors),
            "events": len(model.icons), "orphan_events": orphans, "pairs": pairs, "anchors": anchors,
            "icons": {v["name"]: {k: v[k] for k in ("sha256", "rgb", "hue", "saturation")} for v in files.values()},
            "on_screen": tiles,
            "params": {k: p[k] for k in ("frame_tolerance", "min_delta_e_file", "min_delta_e_screen", "min_hue_distance_deg")}}

