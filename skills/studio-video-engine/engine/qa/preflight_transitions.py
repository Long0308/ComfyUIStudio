"""Preflight transitions: refuse a bad transition BEFORE the render, from the config and the SOURCE clips.

* A white flash / dip / bloom between two PICTURE shots that frame the same seat is refused (user rule: same
  seat, only props change -> hard cut + push-in).  Same framing is measured on two SOURCE clip frames (the one
  before the window and the first one after it, same NCC as Q3, ``q3_flash.ncc``), so no render is needed;
  a declared ``layout_change: false`` / ``framing: same_framing`` refuses it with no pixels at all.
* A type that shows both shots in one frame (dissolve, wipe, cloud, ...) next to a picture shot needs
  ``continuity: agree``; a config that does not state it is not ``agree``.
* An unknown transition type is refused (the build refuses it too).
* Boundaries that touch a graphic (intro, cards, end plate) are not framing questions and are listed as skipped.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..core.errors import Uncertain
from ..editorial import presets
from ..seedvr2.seam_media import ffmpeg_flags
from .gates import FAIL, PASS, UNCERTAIN, roll_up
from .gates.q3_flash import _small, ncc
from .preflight_segments import Piece, ending_at, native_index, starting_at
from .review_media import numpy_module
from .review_model import Model, Transition


def _preset(name: str) -> dict | None:
    return presets.catalog()["presets"].get(name)


def is_flash(t: Transition, preset: dict | None, q3: dict, block: dict) -> bool:
    """``block`` = the preflight recipe's ``transitions`` block."""
    return t.type in q3["needs_layout_change_types"] or bool(preset and preset["renders_as"] in block["flash_renders_as"])


def shows_both(t: Transition, preset: dict | None, q4: dict) -> bool:
    return bool(preset and preset["shows_both"]) or t.type in q4["both_shots_types"]


def _is_graphic(name: str, q4: dict) -> bool:
    return name in q4["graphic_ids"] or any(name.startswith(prefix) for prefix in q4["graphic_prefixes"])


def grab_gray(clip: Path, index: int, ffmpeg: str, width: int, height: int) -> Any:
    """One source frame as 8-bit gray, area-scaled like the Q3 analysis frames (decodes up to ``index`` only)."""
    np = numpy_module()
    if not clip.is_file():
        raise Uncertain(f"source clip not found: {clip}")
    vf = fr"select=eq(n\,{index}),scale={width}:{height}:flags=area,format=gray"
    try:
        result = subprocess.run([ffmpeg, "-v", "error", "-i", str(clip), "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-"],
                                capture_output=True, creationflags=ffmpeg_flags(), check=False)
    except OSError as error:
        raise Uncertain(f"cannot run ffmpeg: {error}") from error
    if result.returncode != 0 or len(result.stdout) != width * height:
        raise Uncertain(f"frame {index} of {clip.name} could not be decoded: {result.stderr.decode(errors='replace')[:160]}")
    return np.frombuffer(result.stdout, np.uint8).reshape(height, width)


def source_ncc(t: Transition, out: Piece, inc: Piece, ffmpeg: str, size: tuple[int, int]) -> tuple[float, dict]:
    before, after = min(t.start - 1, t.boundary - 1), max(t.end_exclusive, t.boundary)
    pair = (native_index(out, before), native_index(inc, after))
    a = grab_gray(out.path, pair[0], ffmpeg, *size) if out.path else _missing(out)
    b = grab_gray(inc.path, pair[1], ffmpeg, *size) if inc.path else _missing(inc)
    return ncc(_small(a), _small(b)), {"outgoing": [out.id, pair[0]], "incoming": [inc.id, pair[1]]}


def _missing(piece: Piece) -> Any:
    raise Uncertain(f"{piece.id}: the config names no source clip path")


def _row(t: Transition, preset: dict | None) -> dict:
    return {"id": t.id, "boundary": t.boundary, "type": t.type, "preset": t.type if preset else None,
            "status": PASS, "reasons": [], "checked": []}


def _judge_flash(row: dict, t: Transition, pcs: tuple[Piece, ...], declared: frozenset[int], ffmpeg: str,
                 recipe: dict, pre: dict, raw: dict | None) -> None:
    if t.layout_change is False or t.boundary in declared or (raw or {}).get("framing") == "same_framing":
        row["status"] = FAIL
        row["reasons"].append(f"'{t.type}' flash at a boundary declared as the same framing (no layout change): "
                              "use hard cut + push-in")
        row["checked"].append("declared")
        return
    out, inc = ending_at(pcs, t.boundary), starting_at(pcs, t.boundary)
    if out is None or inc is None:
        row["status"] = UNCERTAIN
        row["reasons"].append("both sides are pictures but the config has no source clip piece ending/starting at "
                              "this boundary: the framing cannot be measured")
        return
    p = recipe["q3_flash"]
    value, used = source_ncc(t, out, inc, ffmpeg, (p["analysis_width"], p["analysis_height"]))
    limit = pre["transitions"]["same_framing_ncc_min_source"]
    row.update(source_ncc=round(value, 3), source_frames=used, source_ncc_limit=limit)
    row["checked"].append("source_ncc")
    if value >= limit:
        row["status"] = FAIL
        row["reasons"].append(f"'{t.type}' (white flash) between same-framing shots: source ncc {value:.2f} >= {limit} "
                              f"({used['outgoing'][0]}#{used['outgoing'][1]} vs {used['incoming'][0]}#{used['incoming'][1]}): "
                              "use hard cut + push-in, flash only when the angle/scene changes")


def run(config: dict, model: Model, recipe: dict, pre: dict, pcs: tuple[Piece, ...], ffmpeg: str,
        declared_same: frozenset[int] = frozenset()) -> dict:
    q3, q4 = recipe["q3_flash"], recipe["q4_ghost"]
    raw_rows = {int(r.get("boundary", r.get("frame", -1))): r for r in
                ((config.get("motion") or {}).get("transitions", config.get("transitions")) or []) if isinstance(r, dict)}
    pictures = {p.id for p in pcs} | {p.logical for p in pcs} | set(model.picture_ids)
    rows = []
    for t in model.transitions:
        preset = _preset(t.type)
        row = _row(t, preset)
        side = [name in pictures and not _is_graphic(name, q4) for name in (t.from_id, t.to_id)]
        if preset is None and t.type not in q3["needs_layout_change_types"] + q3["spike_allowed_types"]:
            row["status"] = FAIL
            row["reasons"].append(f"unknown transition type {t.raw_type!r}")
        if shows_both(t, preset, q4) and any(side) and t.continuity != "agree":
            row["status"] = FAIL
            row["reasons"].append(f"'{t.type}' shows both shots in one frame next to a picture shot but continuity is "
                                  f"{t.continuity!r} (only 'agree' allows it): use dip_white on a real angle change, "
                                  "whip, cut_push or card_flip_3d")
            row["checked"].append("continuity")
        if all(side) and is_flash(t, preset, q3, pre["transitions"]):
            _guarded_flash(row, t, pcs, declared_same, ffmpeg, recipe, pre, raw_rows.get(t.boundary))
        elif not any(side) and not row["reasons"]:
            row["skipped"] = "graphic boundary (intro, card, plate): not a same-framing question"
        rows.append(row)
    failures = [f"{r['id']}: {reason}" for r in rows if r["status"] != PASS for reason in r["reasons"]]
    return {"gate": "TRANSITIONS", "status": roll_up(r["status"] for r in rows), "failures": failures,
            "transitions": len(rows), "flash_boundaries_measured": sum("source_ncc" in r for r in rows), "rows": rows,
            "params": {"same_framing_ncc_min_source": pre["transitions"]["same_framing_ncc_min_source"]}}


def _guarded_flash(row: dict, t: Transition, pcs: tuple[Piece, ...], declared: frozenset[int], ffmpeg: str,
                   recipe: dict, pre: dict, raw: dict | None) -> None:
    """An unreadable clip makes THIS boundary UNCERTAIN (a FAIL already found stays a FAIL)."""
    try:
        _judge_flash(row, t, pcs, declared, ffmpeg, recipe, pre, raw)
    except Uncertain as error:
        if row["status"] != FAIL:
            row["status"] = UNCERTAIN
        row["reasons"].append(f"unreadable input: {error}")
