"""Film sections the loudness standard is judged on, derived from the timeline of the review config.

``intro`` (before the first dialogue), ``dialogue``, ``logo_hold`` (after the last line until the first
vocabulary card), ``outro_cards``, ``end_plate`` (``motion.ending.end_plate.start`` when the config declares
it) and ``ending`` (frames after the last line when there are no cards).  They tile ``[0, total_frames)``.
An explicit ``--sections`` file (``[{name, start_frame, end_frame_exclusive}]``) replaces the derivation.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import Refused
from ..core.io import read_json
from .timeline import samples_for_frames


def _starts(review_config: dict, total: int, brand_voice_end_frame: int | None = None) -> list[tuple[str, int]]:
    rows = [r for r in review_config.get("dialogue", []) if isinstance(r, dict) and "start_frame" in r]
    cards = [c for c in review_config.get("outro_cards", []) if isinstance(c, dict) and "start_frame" in c]
    if not rows:
        raise Refused("review config has no dialogue[] rows: cannot derive sections (pass --sections)")
    first = min(int(r["start_frame"]) for r in rows)
    last = max(int(r.get("end_frame_exclusive", int(r["start_frame"]) + int(r.get("duration_frames", 0)))) for r in rows)
    plate = ((review_config.get("motion") or {}).get("ending") or {}).get("end_plate") or {}
    named = [("intro", 0), ("dialogue", first)]
    if brand_voice_end_frame:  # the brand voice plays alone first; the music (intro) starts when it has ended
        if not 0 < brand_voice_end_frame <= first:
            raise Refused(f"the brand voice ends at frame {brand_voice_end_frame}, after the first line (frame {first})")
        named = [("brand_voice", 0), ("intro", brand_voice_end_frame), ("dialogue", first)]
    if cards:
        card0 = min(int(c["start_frame"]) for c in cards)
        if card0 > last:
            named.append(("logo_hold", last))
        named.append(("outro_cards", card0))
    elif last < total:
        named.append(("ending", last))
    if isinstance(plate.get("start"), int) and plate["start"] > named[-1][1]:
        named.append(("end_plate", plate["start"]))
    return named


def derive_sections(review_config: dict, timeline: dict, brand_voice_end_frame: int | None = None) -> list[dict]:
    total, fps, rate = timeline["total_frames"], timeline["fps"], timeline["sample_rate"]
    named = [(n, f) for n, f in _starts(review_config, total, brand_voice_end_frame) if 0 <= f < total]
    return _rows(named, total, fps, rate)


def _rows(starts: list[tuple[str, int]], total: int, fps: int, rate: int) -> list[dict]:
    rows = []
    for (name, start), end in zip(starts, [f for _, f in starts[1:]] + [total]):
        if end <= start:
            continue
        rows.append({"name": name, "start_frame": start, "end_frame_exclusive": end,
                     "start_sample": samples_for_frames(start, fps, rate), "end_sample": samples_for_frames(end, fps, rate)})
    return rows


def load_sections(path: str | Path, timeline: dict) -> list[dict]:
    document = read_json(Path(path))
    if not isinstance(document, list) or not document:
        raise Refused(f"{path}: sections must be a non-empty JSON list")
    expected, rows = 0, []
    for item in document:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise Refused(f"{path}: every section needs a name")
        start, end = item.get("start_frame"), item.get("end_frame_exclusive")
        if not isinstance(start, int) or not isinstance(end, int) or start != expected or end <= start:
            raise Refused(f"{path}: section {item.get('name')!r} must start at frame {expected} and end after it")
        expected = end
        rows.append(item)
    if expected != timeline["total_frames"]:
        raise Refused(f"{path}: sections end at frame {expected}, the film has {timeline['total_frames']}")
    return _rows([(r["name"], r["start_frame"]) for r in rows], timeline["total_frames"], timeline["fps"], timeline["sample_rate"])
