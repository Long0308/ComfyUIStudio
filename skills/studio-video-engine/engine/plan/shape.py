"""Accessors for the review-config data shape (``jjv/review-config/v1`` and the legacy review-hd configs) and the cut list.

The cut list is ``engine.editorial.segments.plan_segments`` (read-only import: one source of truth for the cut rules);
an existing ``segments.json`` (``jjv/segments/v1``) in the inputs wins over a recomputation.
"""

from __future__ import annotations

from typing import Any

from ..core.errors import Refused
from ..editorial import segments as engine_segments
from .load import PlanInputs


def fps(c: dict) -> int:
    return c["fps"]


def main_frames(c: dict) -> int:
    return c["main_frames"]


def total_frames(c: dict) -> int:
    """main + end hold (a legacy config's ``total_frames`` is the main film only; its ``total_frames_with_endlogo`` is the whole)."""
    return c["main_frames"] + c.get("end_hold_frames", 0)


def shots(c: dict) -> list[dict]:
    """``{id, start, end, native_frames, words, clips[], wav_sha256}`` per dialogue entry, timeline order."""
    out = []
    for d in c.get("dialogue", []):
        segs = d.get("segments") or []
        out.append({"id": d["id"], "start": d["start_frame"], "end": d["end_frame_exclusive"],
                    "native_frames": sum(s.get("native_frames") or 0 for s in segs) or None,
                    "words": d.get("words") or [], "clips": [s.get("sha256") for s in segs],
                    "wav_sha256": (d.get("audio") or {}).get("sha256"),
                    "wav_offset_frames": (d.get("audio") or {}).get("offset_frames")})
    return sorted(out, key=lambda s: s["start"])


def transitions(c: dict) -> list[dict]:
    return (c.get("motion") or {}).get("transitions") or []


def icons(c: dict) -> list[dict]:
    return (c.get("motion") or {}).get("icons") or []


def ending(c: dict) -> dict:
    return (c.get("motion") or {}).get("ending") or {}


def cards(c: dict) -> list[dict]:
    return c.get("outro_cards") or []


def _records(c: dict) -> list[dict]:
    """Transition records as ``plan_segments`` expects them (``renders_as`` falls back to the legacy ``type``)."""
    return [dict(r, renders_as=r.get("renders_as") or r.get("type")) for r in transitions(c)]


def join_frame(c: dict) -> int | None:
    """First frame without shot video for an iris ending (the kit cuts main / ending there), else None."""
    return engine_segments.join_frame_of(_records(c), ending(c))


def shot_window(c: dict, shot: dict) -> tuple[int, int]:
    """The frames a shot's picture can be drawn on: its window, cut at the join frame of an iris ending."""
    join = join_frame(c)
    return shot["start"], (min(shot["end"], join) if join is not None else shot["end"])


def _check_cover(doc: dict, total: int) -> None:
    at = 0
    for row in doc.get("segments") or []:
        if row["start"] != at or row["end_exclusive"] <= row["start"]:
            raise Refused(f"segments.json: segment {row.get('id')} breaks the cover at f{at}")
        at = row["end_exclusive"]
    if at != total:
        raise Refused(f"segments.json covers f0..f{at} but the film has {total} frames")


def cut_list(inputs: PlanInputs) -> list[dict]:
    """Segments ``{id, kind, start, end_exclusive, frames, shots_visible, transition_ids?}`` covering the whole film."""
    c = inputs.config
    total = total_frames(c)
    if inputs.segments_doc is not None:
        _check_cover(inputs.segments_doc, total)
        return [dict(r) for r in inputs.segments_doc["segments"]]
    sh = shots(c)
    if not sh:
        raise Refused(f"{inputs.label}: the config has no dialogue shots")
    end = ending(c)
    plate = (end.get("end_plate") or {}).get("start")
    recs = _records(c)
    doc = engine_segments.plan_segments(
        fps=fps(c), total_frames=total, main_frames=main_frames(c), intro_end=sh[0]["start"],
        dialogue_end=max(s["end"] for s in sh),
        shots=[{"id": s["id"], "start": s["start"], "end": s["end"]} for s in sh],
        transitions=recs,
        cards=[{"term": x["term"], "start": x["start_frame"], "frames": x["duration_frames"]} for x in cards(c)],
        plate_start=plate, join_frame=engine_segments.join_frame_of(recs, end),
        icons=[{"id": i["id"], "frame": i["frame"], "total_frames": i["total_frames"]} for i in icons(c)],
        episode_id=c.get("episode_id"))
    return doc["segments"]


def overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def card_of(c: dict, segment: dict) -> list[int]:
    """Indexes of the outro cards whose window (plus a 1 f lead / hand-over frame) touches the segment."""
    return [i for i, x in enumerate(cards(c))
            if overlap(x["start_frame"] - 1, x["start_frame"] + x["duration_frames"] + 1, segment["start"],
                       segment["end_exclusive"])]


def value(c: dict, *path: str, default: Any = None) -> Any:
    cur: Any = c
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur
