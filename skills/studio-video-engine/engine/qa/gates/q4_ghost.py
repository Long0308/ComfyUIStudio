"""Q4 transition ghost check.

For EVERY transition window (frames > 0) a full-resolution contact sheet PNG is written for a human/critic:
tile order = frame before the window, up to ``sheet_max_tiles - 2`` evenly spaced window frames, frame after.
For picture <-> picture windows two numeric proxies of a duplicated character are added:

* ghost excess = max over window frames of min(ncc(edges(f), edges(before)), ncc(edges(f), edges(after)))
  minus ncc(edges(before), edges(after)).  A cross-dissolve / mask wipe shows BOTH shots in one frame, so the
  frame correlates with both ends clearly above what the two ends share (measured clean 0.00-0.02, double
  exposure 0.21-0.35).  >= ``ghost_fail`` FAILS, >= ``ghost_warn`` is UNCERTAIN (a critic must look).
* mirror correlation rise = how much more left/right-symmetric the window frame's edge map is than the
  two ends (reported; >= ``mirror_rise_warn`` is UNCERTAIN).

Config rule on top: a both-shots type between two pictures needs continuity ``agree``; with no declared
continuity the measured same-framing correlation (Q3 value) stands in.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...core.io import sha256_file
from ..review_media import extract_frames, numpy_module, write_png
from ..review_model import Model, Transition
from . import FAIL, PASS, UNCERTAIN, roll_up
from .q3_flash import _small, ncc


def edge_map(frame: Any, cell: int) -> Any:
    """Gradient magnitude of an 8-bit gray frame, block-averaged ``cell`` x ``cell``."""
    np = numpy_module()
    g = frame.astype(np.float64)
    e = np.abs(np.diff(g, axis=1))[:-1, :] + np.abs(np.diff(g, axis=0))[:, :-1]
    h, w = e.shape
    return e[: h // cell * cell, : w // cell * cell].reshape(h // cell, cell, w // cell, cell).mean((1, 3))


def mirror_ncc(edges: Any) -> float:
    return ncc(edges, edges[:, ::-1])


def sheet_frames(before: int, start: int, end_excl: int, after: int, max_tiles: int) -> list[int]:
    """Row-major tile frames: before, evenly spaced window frames, after (at most ``max_tiles``)."""
    inner = list(range(start, end_excl))
    room = max(max_tiles - 2, 1)
    if len(inner) > room:
        step = (len(inner) - 1) / (room - 1) if room > 1 else 0
        inner = [inner[round(i * step)] for i in range(room)]
    return sorted({before, *inner, after})


def build_sheet(video: Path, ffmpeg: str, frames: list[int], native: tuple[int, int], columns: int, origin: int,
                out: Path) -> dict | None:
    """Native-resolution contact sheet; None when the file holds none of the frames."""
    np = numpy_module()
    width, height = native
    got = extract_frames(video, ffmpeg, frames, width, height, origin=origin, native=native)
    tiles = [f for f in frames if f in got]
    if not tiles:
        return None
    rows = -(-len(tiles) // columns)
    canvas = np.zeros((rows * height, columns * width, 3), dtype=np.uint8)
    for k, f in enumerate(tiles):
        r, c = divmod(k, columns)
        canvas[r * height:(r + 1) * height, c * width:(c + 1) * width] = got[f]
    write_png(out, canvas, ffmpeg)
    return {"path": str(out), "sha256": sha256_file(out), "tiles": tiles, "tile_size": [width, height],
            "columns": columns}


def _is_picture(t: Transition, model: Model) -> bool:
    return t.from_id in model.picture_ids and t.to_id in model.picture_ids


def _proxy(t: Transition, gray: Any, origin: int, p: dict) -> dict | None:
    before, after = t.start - 1, t.end_exclusive
    n = gray.shape[0]
    if not (0 <= before - origin < n and 0 <= after - origin < n):
        return None
    cell = p["edge_cell"]
    ea, eb = edge_map(gray[before - origin], cell), edge_map(gray[after - origin], cell)
    base, both, mirror = ncc(ea, eb), 0.0, 0.0
    for f in range(t.start, t.end_exclusive):
        if 0 <= f - origin < n:
            ef = edge_map(gray[f - origin], cell)
            both = max(both, min(ncc(ef, ea), ncc(ef, eb)))
            mirror = max(mirror, mirror_ncc(ef))
    return {"ncc_before_after": round(base, 3), "ghost_excess": round(both - base, 3),
            "mirror_rise": round(mirror - max(mirror_ncc(ea), mirror_ncc(eb)), 3)}


def _judge(row: dict, t: Transition, gray: Any, origin: int, recipe: dict) -> None:
    p, q3 = recipe["q4_ghost"], recipe["q3_flash"]
    proxy = _proxy(t, gray, origin, p)
    if proxy is None:
        row.update(status=UNCERTAIN, reasons=["frames before/after the window are not in the file"])
        return
    row.update(proxy)
    if t.type in p["both_shots_types"] and t.continuity != "agree":
        framing = ncc(_small(gray[t.start - 1 - origin]), _small(gray[t.end_exclusive - origin]))
        row["same_framing_ncc"] = round(framing, 3)
        if t.continuity is not None or framing < q3["same_framing_ncc_min"]:
            row["status"] = FAIL
            row["reasons"].append(f"two-shot type '{t.type}' between pictures that are not the same framing "
                                  f"(continuity {t.continuity!r}, ncc {framing:.2f}): shows both characters at once")
    if proxy["ghost_excess"] >= p["ghost_fail"]:
        row["status"] = FAIL
        row["reasons"].append(f"double exposure: ghost excess {proxy['ghost_excess']} >= {p['ghost_fail']}")
    elif proxy["ghost_excess"] >= p["ghost_warn"] or proxy["mirror_rise"] >= p["mirror_rise_warn"]:
        if row["status"] == PASS:
            row["status"] = UNCERTAIN
        row["reasons"].append(f"ghost excess {proxy['ghost_excess']} / mirror rise {proxy['mirror_rise']} in the "
                              "grey zone: a critic must look at the sheet")


def run(model: Model, gray: Any, video: Path, ffmpeg: str, recipe: dict, sheets_dir: Path,
        native: tuple[int, int], origin: int = 0) -> dict:
    p = recipe["q4_ghost"]
    n = gray.shape[0]
    rows, safe = [], re.compile(r"[^A-Za-z0-9_.-]+")
    for t in model.transitions:
        if t.frames <= 0:
            continue
        before, after = t.start - 1, t.end_exclusive
        if after - origin < 0 or before - origin >= n:
            continue  # window not in this file
        row: dict = {"id": t.id, "boundary": t.boundary, "type": t.type, "window": [t.start, t.end_exclusive],
                     "kind": "picture" if _is_picture(t, model) else "graphic", "status": PASS, "reasons": []}
        frames = sheet_frames(before, t.start, t.end_exclusive, after, p["sheet_max_tiles"])
        name = f"q4-{safe.sub('_', t.id)}-f{t.start}-f{t.end_exclusive}.png"
        row["sheet"] = build_sheet(video, ffmpeg, frames, native, p["sheet_columns"], origin, sheets_dir / name)
        if row["kind"] == "picture":
            _judge(row, t, gray, origin, recipe)
        rows.append(row)
    return {"gate": "Q4", "status": roll_up(r["status"] for r in rows), "windows": rows,
            "sheets": [r["sheet"]["path"] for r in rows if r.get("sheet")],
            "params": {k: p[k] for k in ("ghost_fail", "ghost_warn", "mirror_rise_warn")},
            "failures": [f"{r['id']}: {x}" for r in rows if r["status"] != PASS for x in r["reasons"]]}
