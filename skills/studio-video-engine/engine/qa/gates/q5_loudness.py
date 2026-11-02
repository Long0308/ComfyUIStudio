"""Q5 loudness: per-section ebur128 of the finished audio against the film-mix standard.

Sections come from the review config (no section list is hard-coded per episode): ``intro`` (before the first
dialogue, informational), ``dialogue`` (first dialogue start .. last dialogue end), ``logo_hold`` (until the
first outro card), ``cards`` (first card start .. last card end), ``plate_endlogo`` (to the end of the file) and
``whole``.  Gated sections (recipe) must sit at ``target_lufs`` +- ``tolerance_lu`` with true peak <=
``true_peak_max_dbtp``; neighbouring gated sections may not differ by more than ``max_section_jump_lu``.
"""

from __future__ import annotations

from pathlib import Path

from ...core.errors import Uncertain
from ..review_media import ebur128
from ..review_model import Model
from . import FAIL, PASS, UNCERTAIN

ORDER = ("intro", "dialogue", "logo_hold", "cards", "plate_endlogo")


def section_frames(model: Model, total: int) -> dict[str, tuple[int, int]]:
    """``{name: (first frame, end frame exclusive)}`` derived from the config; empty sections are dropped."""
    starts = [d["start_frame"] for d in model.dialogue if isinstance(d.get("start_frame"), int)]
    ends = [d["end_frame_exclusive"] for d in model.dialogue if isinstance(d.get("end_frame_exclusive"), int)]
    if not starts or not ends or not model.cards:
        raise Uncertain("loudness sections need dialogue windows and outro cards in the config")
    first, last = model.cards[0], model.cards[-1]
    cards_start, cards_end = first["start_frame"], last["start_frame"] + last["duration_frames"]
    bounds = [0, min(starts), max(ends), cards_start, cards_end, total]
    sections = {name: (bounds[i], bounds[i + 1]) for i, name in enumerate(ORDER)}
    sections["whole"] = (0, total)
    return {k: v for k, v in sections.items() if v[1] > v[0]}


def run(model: Model, recipe: dict, source: Path, ffmpeg: str, total: int | None, audio_origin_s: float = 0.0) -> dict:
    p = recipe["q5_pacing"]
    if total is None:
        return {"status": UNCERTAIN, "failures": [], "note": "the config states no total frame count"}
    rows, failures = [], []
    sections = section_frames(model, total)
    for name, (a, b) in sections.items():
        start, dur = a / model.fps - audio_origin_s, (b - a) / model.fps
        if start < 0 or dur <= 0:
            continue
        got = ebur128(source, ffmpeg, start, dur)
        gated = name in p["gated_sections"]
        row = {"section": name, "frames": [a, b], "seconds": [round(a / model.fps, 3), round(b / model.fps, 3)],
               "lufs": got["lufs"], "true_peak_dbtp": got["true_peak_dbtp"], "gated": gated, "ok": True}
        if gated and abs(got["lufs"] - p["target_lufs"]) > p["tolerance_lu"]:
            row["ok"] = False
            failures.append(f"section {name}: {got['lufs']} LUFS is outside {p['target_lufs']} +- {p['tolerance_lu']}")
        if gated and got["true_peak_dbtp"] > p["true_peak_max_dbtp"]:
            row["ok"] = False
            failures.append(f"section {name}: true peak {got['true_peak_dbtp']} dBTP above {p['true_peak_max_dbtp']}")
        rows.append(row)
    chain = [r for r in rows if r["gated"] and r["section"] != "whole"]
    for left, right in zip(chain, chain[1:]):
        jump = round(abs(right["lufs"] - left["lufs"]), 2)
        if jump > p["max_section_jump_lu"]:
            failures.append(f"loudness jump {jump} LU between {left['section']} and {right['section']} "
                            f"(max {p['max_section_jump_lu']})")
    return {"status": FAIL if failures else PASS, "sections": rows, "failures": failures,
            "params": {k: p[k] for k in ("target_lufs", "tolerance_lu", "true_peak_max_dbtp", "max_section_jump_lu")}}
