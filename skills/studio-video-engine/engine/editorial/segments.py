"""``segments.json`` (``jjv/segments/v1``): the cut list of a film (T-E45 P2, engine side).

An additive output of ``jjv editorial build-config``.  The film is cut into segments that are rendered
independently (silent video, closed GOP, see the kit) and joined by stream copy, so a one-boundary change
re-renders only the segments around it.

Rules (all enforced, never guessed):

* the segments cover ``[0, total_frames)`` exactly: no gap, no overlap, every segment has >= 1 frame;
* an effect window is the ``start .. end_exclusive`` of a transition record (the catalog ``window`` mode,
  computed by :func:`engine.editorial.presets.window`; the kit's tail windows follow the same numbers).  A cut
  is NEVER inside a window (the edges are fine): one effect belongs to exactly one segment.  Windows that
  overlap are merged into one ``transition`` segment that lists every id;
* a hard cut or a carry (empty window) makes no transition segment; the clip boundary is still a cut;
* with an iris ending the vector-only part starts at ``join_frame`` = the first frame in which no shot
  video is drawn (``logo_disc.in`` + 3: the disc is opaque from its third frame).  This is the very frame
  the kit cuts ``main`` / ``ending`` at, and the iris window is cut short there.

The output is canonical (sorted by frame, fixed key order) so a rebuild is byte-identical.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..core.errors import Refused
from ..core.io import pretty_json
from .timeline import END_PLATE, Timeline

SCHEMA = "jjv/segments/v1"
DISC_OPAQUE_FRAMES = 3     # the logo disc fades in over 3 frames; from the 3rd the iris shows no picture
JSON_MODE = "utf8"
KINDS = ("intro", "shot_span", "transition", "card", "plate", "ending", "logo_hold")


def canonical_bytes(document: dict) -> bytes:
    return pretty_json(document, mode=JSON_MODE)


def join_frame_of(records: Sequence[dict], ending: dict | None) -> int | None:
    """First frame without shot video for an iris ending (the kit's main/ending cut), else None."""
    disc = ((ending or {}).get("logo_disc") or {}).get("in")
    has_iris = any(r.get("renders_as") == "iris" for r in records)
    return disc + DISC_OPAQUE_FRAMES if has_iris and isinstance(disc, int) and not isinstance(disc, bool) else None


def _windows(transitions: Iterable[dict], join: int | None, total: int) -> list[dict]:
    """Merged effect windows ``{start, end, ids, records}`` (empty windows dropped, iris cut short at the join)."""
    raw = []
    for rec in transitions:
        start, end = rec["start"], rec["end_exclusive"]
        if rec.get("renders_as") == "iris" and join is not None:
            end = min(end, join)
        start, end = max(0, start), min(total, end)
        if end > start:
            raw.append({"start": start, "end": end, "ids": [rec["id"]], "records": [rec]})
    raw.sort(key=lambda w: (w["start"], w["end"], w["ids"][0]))
    merged: list[dict] = []
    for window in raw:
        if merged and window["start"] < merged[-1]["end"]:
            last = merged[-1]
            merged[-1] = {"start": last["start"], "end": max(last["end"], window["end"]),
                          "ids": last["ids"] + window["ids"], "records": last["records"] + window["records"]}
        else:
            merged.append(window)
    return merged


def _inside(cut: int, windows: Sequence[dict]) -> dict | None:
    return next((w for w in windows if w["start"] < cut < w["end"]), None)


def _overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _kind_of(start: int, *, main: int, plate: int | None, cards: Sequence[dict], join: int | None,
             dialogue_end: int, intro_end: int) -> str:
    if start >= main:
        return "ending"
    if plate is not None and start >= plate:
        return "plate"
    if cards and start >= cards[0]["start"]:
        return "card"
    if start >= (join if join is not None else dialogue_end):
        return "logo_hold"
    if start >= intro_end:
        return "shot_span"
    return "intro"


def _shot_at(frame: int, shots: Sequence[dict]) -> dict | None:
    return next((s for s in shots if s["start"] <= frame < s["end"]), None)


def _card_at(frame: int, cards: Sequence[dict]) -> int:
    index = 0
    for i, card in enumerate(cards):
        if card["start"] <= frame:
            index = i
    return index


def plan_segments(*, fps: int, total_frames: int, main_frames: int, intro_end: int, dialogue_end: int,
                  shots: Sequence[dict], transitions: Sequence[dict], cards: Sequence[dict],
                  plate_start: int | None, join_frame: int | None, icons: Sequence[dict] = (),
                  episode_id: str | None = None, extra_cuts: Sequence[int] = ()) -> dict:
    """The segment document for plain data (see :func:`from_build` for the build wiring).

    ``shots``: ``{id, start, end}``; ``transitions``: records with ``id, boundary, from, to, start,
    end_exclusive`` (+ ``renders_as``, ``outgoing_tail``); ``cards``: ``{term, start, frames}``.
    ``extra_cuts`` are cuts a caller insists on: one inside an effect window is ``Refused``."""
    windows = _windows(transitions, join_frame, total_frames)
    if join_frame is not None and _inside(join_frame, windows):
        w = _inside(join_frame, windows)
        raise Refused(f"the join frame f{join_frame} falls inside the effect window of {', '.join(w['ids'])} "
                      f"(f{w['start']}..f{w['end'] - 1})")
    for cut in extra_cuts:
        if not 0 < cut < total_frames:
            raise Refused(f"cut f{cut} is outside the film (f1..f{total_frames - 1})")
        w = _inside(cut, windows)
        if w is not None:
            raise Refused(f"cut at f{cut} falls inside the effect window of {', '.join(w['ids'])} "
                          f"(f{w['start']}..f{w['end'] - 1}): one effect must belong to one segment")
    candidates = {0, total_frames, main_frames, *extra_cuts}
    if intro_end > 0:
        candidates.add(intro_end)
    candidates.update(s["start"] for s in shots)
    if join_frame is None or join_frame >= dialogue_end:
        candidates.add(dialogue_end)      # with an iris the join frame replaces it: nothing changes at the last clip end
    candidates.update(c["start"] for c in cards)
    if plate_start is not None:
        candidates.add(plate_start)
    if join_frame is not None:
        candidates.add(join_frame)
    for w in windows:
        candidates.update((w["start"], w["end"]))
    cuts = sorted(c for c in candidates if 0 <= c <= total_frames and (_inside(c, windows) is None
                                                                          or c in extra_cuts))
    shot_ids = {s["id"] for s in shots}
    rows: list[dict] = []
    for a, b in zip(cuts, cuts[1:]):
        window = next((w for w in windows if (w["start"], w["end"]) == (a, b)), None)
        rows.append(_row(a, b, window, shots=shots, shot_ids=shot_ids, cards=cards, join=join_frame,
                         main=main_frames, plate=plate_start, dialogue_end=dialogue_end, intro_end=intro_end))
    rows = _name(rows)
    for row in rows:
        row["inputs_slice_hint"] = _hint(row, shots, transitions, icons, cards)
    document: dict[str, Any] = {"schema": SCHEMA}
    if episode_id is not None:
        document["episode_id"] = episode_id
    document.update({"fps": fps, "total_frames": total_frames, "main_frames": main_frames,
                     "join_frame": join_frame, "cut_points": cuts, "segments": [_ordered(r) for r in rows]})
    check(document)
    return document


def _row(a: int, b: int, window: dict | None, *, shots, shot_ids, cards, join, main, plate, dialogue_end,
         intro_end) -> dict:
    if window is not None:
        records = window["records"]
        visible = []
        for shot in shots:
            tail = any(r.get("outgoing_tail") and r["from"] == shot["id"] for r in records)
            if shot["id"] in {r[k] for r in records for k in ("from", "to")} or tail:
                if _overlap(a, b, shot["start"], shot["end"]) or tail:
                    visible.append(shot["id"])
        if join is not None and a >= join:
            visible = []
        ids = sorted(window["ids"], key=lambda i: (next(r["boundary"] for r in records if r["id"] == i), i))
        return {"kind": "transition", "start": a, "end_exclusive": b, "shots_visible": visible,
                "transition_ids": ids}
    kind = _kind_of(a, main=main, plate=plate, cards=cards, join=join, dialogue_end=dialogue_end,
                    intro_end=intro_end)
    row: dict[str, Any] = {"kind": kind, "start": a, "end_exclusive": b, "shots_visible": []}
    if kind == "shot_span":
        shot = _shot_at(a, shots)
        if shot is None:
            row["kind"] = "logo_hold"
        else:
            row["shots_visible"] = [shot["id"]]
            row["shot"] = shot["id"]
    elif kind == "card":
        row["card_index"] = _card_at(a, cards)
        row["card_term"] = cards[row["card_index"]]["term"]
    return row


def _name(rows: list[dict]) -> list[dict]:
    """Stable, readable ids: ``intro``, ``shot-<id>-<n>``, ``tr-<id>``, ``card-NN``, ``logo-hold``, ``plate``, ``ending``."""
    base: list[str] = []
    for row in rows:
        kind = row["kind"]
        if kind == "shot_span":
            base.append(f"shot-{row['shot']}")
        elif kind == "transition":
            base.append("tr-" + "+".join(row["transition_ids"]))
        elif kind == "card":
            base.append(f"card-{row['card_index'] + 1:02d}")
        else:
            base.append({"logo_hold": "logo-hold"}.get(kind, kind))
    seen: dict[str, int] = {}
    totals = {b: base.count(b) for b in base}
    for row, name in zip(rows, base):
        seen[name] = seen.get(name, 0) + 1
        suffix = row["kind"] == "shot_span" or totals[name] > 1
        row["id"] = f"{name}-{seen[name]}" if suffix else name
    return rows


def _hint(row: dict, shots, transitions, icons, cards) -> dict:
    a, b = row["start"], row["end_exclusive"]
    return {
        "shots": [s["id"] for s in shots if _overlap(a, b, s["start"], s["end"])],
        "transitions": [t["id"] for t in transitions
                        if _overlap(a, b, t["start"], t["end_exclusive"]) or a <= t["boundary"] < b],
        "icons": [i["id"] for i in icons if _overlap(a, b, i["frame"], i["frame"] + i["total_frames"])],
        "cards": [c["term"] for c in cards if _overlap(a, b, c["start"], c["start"] + c["frames"])],
    }


def _ordered(row: dict) -> dict:
    out: dict[str, Any] = {"id": row["id"], "kind": row["kind"], "start": row["start"],
                           "end_exclusive": row["end_exclusive"], "frames": row["end_exclusive"] - row["start"],
                           "shots_visible": row["shots_visible"]}
    if row["kind"] == "transition":
        out["transition_id"] = row["transition_ids"][0]
        out["transition_ids"] = row["transition_ids"]
    if row["kind"] == "card":
        out["card_term"] = row["card_term"]
    out["inputs_slice_hint"] = row["inputs_slice_hint"]
    return out


def check(document: dict) -> None:
    """The structural gate: exact cover, no overlap, frames >= 1, unique ids, consistent cut points."""
    rows = document["segments"]
    total = document["total_frames"]
    if not rows or rows[0]["start"] != 0:
        raise Refused("segments must start at f0")
    at = 0
    seen: set[str] = set()
    for row in rows:
        if row["start"] != at:
            raise Refused(f"segment {row['id']} starts at f{row['start']} but the previous one ends at f{at}")
        if row["end_exclusive"] - row["start"] < 1:
            raise Refused(f"segment {row['id']} has no frames")
        if row["id"] in seen:
            raise Refused(f"duplicate segment id {row['id']}")
        seen.add(row["id"])
        at = row["end_exclusive"]
    if at != total:
        raise Refused(f"segments end at f{at}, the film has {total} frames")
    if document["cut_points"] != [0, *[r["start"] for r in rows[1:]], total]:
        raise Refused("cut_points disagree with the segments")


def from_build(*, episode_id: str, timeline: Timeline, records: Sequence[dict], cards: Sequence[dict],
               ending: dict | None, icons: Sequence[dict]) -> dict:
    """The segment document of a validated build (timeline + transition records + cards + ending + icons)."""
    total = timeline.main_frames + timeline.end_card_frames
    return plan_segments(
        fps=timeline.fps, total_frames=total, main_frames=timeline.main_frames, intro_end=timeline.intro_end,
        dialogue_end=timeline.dialogue_end,
        shots=[{"id": s.shot, "start": s.start, "end": s.end} for s in timeline.shots],
        transitions=list(records),
        cards=[{"term": c["term"], "start": c["start_frame"], "frames": c["duration_frames"]} for c in cards],
        plate_start=timeline.starts.get(END_PLATE), join_frame=join_frame_of(records, ending),
        icons=list(icons), episode_id=episode_id)
