"""Load and check the declarative boundary table against the episode timeline."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..qa.scope import require_scoped
from . import boundaries_current, end_card, presets, transitions
from .timeline import CARD_PREFIX, END_LOGO, END_PLATE, Timeline, required_pairs

Rel = Callable[[Path], str]


def load_document(path: Path, schema_path: Path, episode_id: str, domain: dict) -> dict:
    boundaries_current.verify(path)
    document = read_json(path)
    _refuse_planned_presets(document)
    errors = validate(document, read_json(schema_path), label="boundaries")
    if errors:
        raise Refused("boundaries.json is invalid: " + "; ".join(errors))
    seen: set[str] = set()
    for window in document.get("expect_silent", []):
        if window["shot"] in seen:
            raise Refused(f"expect_silent for {window['shot']!r} is declared twice")
        seen.add(window["shot"])
        if not math.isfinite(window["max_rms"]):
            raise Refused(f"expect_silent for {window['shot']!r}: max_rms must be finite, got {window['max_rms']!r}")
    if document["episode_id"] != episode_id:
        raise Refused(f"boundaries.json episode_id {document['episode_id']!r} != {episode_id!r}")
    end_card.check_params(document.get("ending"), domain)
    _check_cards_declared(document)
    return document


def _refuse_planned_presets(document: Any) -> None:
    """A planned preset is in the catalog but not built: say so instead of a generic schema error."""
    rows = document.get("boundaries") if isinstance(document, dict) else None
    for row in rows if isinstance(rows, list) else []:
        name = row.get("type") if isinstance(row, dict) else None
        if isinstance(name, str) and name in presets.catalog()["presets"]:
            presets.get(name, label=f"boundary f{row.get('frame', '?')} {row.get('from_shot')} -> {row.get('to_shot')}")


def _check_cards_declared(document: dict) -> None:
    """Card frames and the plate start may be left out only when the timeline is derived."""
    ending = document.get("ending") or {}
    if ending.get("derive_timeline"):
        return
    for card in document.get("cards", []):
        if "start_frame" not in card or "duration_frames" not in card:
            raise Refused(f"card {card['term']!r} needs start_frame and duration_frames "
                          "(only ending.derive_timeline may derive them from the card WAVs)")
    plate = ending.get("end_plate")
    if plate is not None and "start" not in plate:
        raise Refused("ending.end_plate.start is required (only ending.derive_timeline derives it from the "
                      "measured speech end)")


def _allowed_pairs(timeline: Timeline, cards: list[dict], has_plate: bool) -> set[tuple[str, str]]:
    allowed = set(required_pairs(timeline, cards))
    if has_plate:
        last = CARD_PREFIX + cards[-1]["term"] if cards else None
        if last:
            allowed.add((last, END_PLATE))
        allowed.add((END_PLATE, END_LOGO))
    return allowed


def _check_position(row: dict, timeline: Timeline, allowed: set, shots: dict) -> None:
    label = f"boundary f{row['frame']} {row['from_shot']} -> {row['to_shot']}"
    pair = (row["from_shot"], row["to_shot"])
    for name in pair:
        if name not in timeline.starts:
            raise Refused(f"{label}: unknown name {name!r} (not a shot, card, INTRO, OUTRO, END_PLATE or ENDLOGO "
                          "of this episode)")
    if pair not in allowed:
        raise Refused(f"{label}: not an adjacency of this timeline")
    if row["frame"] != timeline.starts[row["to_shot"]]:
        raise Refused(f"{label}: frame is {row['frame']} but {row['to_shot']!r} starts at "
                      f"f{timeline.starts[row['to_shot']]}")
    incoming = shots.get(row["to_shot"])
    if incoming is not None and pair[0] in shots:
        if row["class"] != incoming.entry_kind:
            raise Refused(f"{label}: class {row['class']!r} contradicts shots.json entry kind {incoming.entry_kind!r}")
        if incoming.entry_kind == "carry" and incoming.entry_from != row["from_shot"]:
            raise Refused(f"{label}: shots.json says the carry comes from {incoming.entry_from!r}")


def _unknown_name(row: dict, name: str) -> Refused:
    label = f"boundary f{row.get('frame', '?')} {row['from_shot']} -> {row['to_shot']}"
    return Refused(f"{label}: unknown name {name!r} (not a shot, card, INTRO, OUTRO, END_PLATE or ENDLOGO "
                   "of this episode)")


def _with_frame(row: dict, timeline: Timeline) -> dict:
    """``frame`` may be left out: it is where the incoming side starts on the timeline."""
    if "frame" in row:
        return row
    start = timeline.starts.get(row["to_shot"])
    if start is None:
        raise _unknown_name(row, row["to_shot"])
    return {**row, "frame": start}


def check_table(document: dict, timeline: Timeline, cards: list[dict], has_plate: bool,
                warnings: list | None = None) -> list[dict]:
    """Resolved rows (preset, frames, direction, params filled in) sorted by frame after every
    position/coverage rule; raises ``Refused``.  Build warnings are appended to ``warnings``."""
    shots = {s.shot: s for s in timeline.shots}
    allowed = _allowed_pairs(timeline, cards, has_plate)
    seen_frames: set[int] = set()
    seen_pairs: set[tuple[str, str]] = set()
    picture_shots = frozenset(shots)
    resolved: list[dict] = []
    for raw in document["boundaries"]:
        row = transitions.resolve_row(_with_frame(raw, timeline))
        transitions.check_row(row, picture_shots)
        _check_position(row, timeline, allowed, shots)
        if warnings is not None:
            warnings.extend(transitions.row_warnings(row, picture_shots))
        pair = (row["from_shot"], row["to_shot"])
        if row["frame"] in seen_frames or pair in seen_pairs:
            raise Refused(f"boundary f{row['frame']} {pair[0]} -> {pair[1]} is declared twice")
        seen_frames.add(row["frame"])
        seen_pairs.add(pair)
        resolved.append(row)
    missing = [pair for pair in required_pairs(timeline, cards) if pair not in seen_pairs]
    if missing:
        raise Refused("boundary table does not cover every cut/carry: missing "
                      + ", ".join(f"{a} -> {b}" for a, b in missing))
    return sorted(resolved, key=lambda row: row["frame"])


def outgoing_of(row: dict, timeline: Timeline) -> transitions.OutgoingShot | None:
    for shot in timeline.shots:
        if shot.shot == row["from_shot"]:
            return transitions.OutgoingShot(shot.shot, shot.editorial_frames, shot.delivery_frames)
    return None


def build_transitions(rows: list[dict], timeline: Timeline, root: Path, rel: Rel,
                      probe: transitions.Probe, allow=()) -> list[dict]:
    """Validate every tail handle (probing the native clip) and build the transition records."""
    transitions.audit_dip_schedule()
    records = []
    for row in rows:
        clip_name = row.get("tail_clip")
        clip = require_scoped(root / clip_name, root, allow, "tail_clip") if clip_name else None
        tail = transitions.check_tail(row, outgoing_of(row, timeline), clip, probe,
                                      timeline.fps, timeline.native_fps)
        clip_info = ({"native_path": rel(clip), "native_sha256": sha256_file(clip)}
                     if tail is not None and clip is not None else None)
        records.append(transitions.build_transition(row, tail, clip_info))
    return records


def _memo(probe: transitions.Probe) -> transitions.Probe:
    seen: dict[Path, int] = {}

    def probed(clip: Path) -> int:
        if clip not in seen:
            seen[clip] = probe(clip)
        return seen[clip]
    return probed


def _select(rows: list[dict], only: str | None) -> list[dict]:
    if only is None:
        return rows
    text = str(only).strip()
    chosen = [row for row in rows if text in (str(row["frame"]), f"T{row['frame']}")]
    if not chosen:
        raise Refused(f"no boundary {only!r} in this table (use a frame number or an id such as T1010)")
    return chosen


def feasibility_table(rows: list[dict], timeline: Timeline, root: Path, rel: Rel, probe: transitions.Probe,
                      allow=(), only: str | None = None) -> list[dict]:
    """Per boundary: its tail handle and, for every ready preset, availability + eligibility.

    Reads native clips (frame counts only); nothing is rendered or requested."""
    probe = _memo(probe)
    picture_shots = frozenset(s.shot for s in timeline.shots)
    table = []
    for row in _select(rows, only):
        clip_name = row.get("tail_clip")
        clip = require_scoped(root / clip_name, root, allow, "tail_clip") if clip_name else None
        outgoing = outgoing_of(row, timeline)
        found = transitions.feasibility(row, outgoing, clip, probe, timeline.fps, timeline.native_fps)
        handle = None
        if outgoing is not None and clip is not None and clip.is_file():
            native = probe(clip)
            handle = {"clip": rel(clip), "shot": outgoing.shot, "native_frames": native,
                      "editorial_frames": outgoing.editorial_frames,
                      "tail_frames_available": native - outgoing.editorial_frames}
        entries = {}
        for name, entry in found.items():
            why = transitions.eligibility(row, name, picture_shots)
            entries[name] = {**entry, "eligible": why is None, "eligible_reason": why}
        item = {"id": f"T{row['frame']}", "boundary": row["frame"], "from": row["from_shot"], "to": row["to_shot"],
                "class": row["class"], "continuity": row["continuity"], "current": row["preset"],
                "frames": row["frames"], "tail_handle": handle, "presets": entries}
        if "framing" in row:
            item["framing"] = row["framing"]
        table.append(item)
    return table
