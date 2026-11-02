"""Read-only view of a review config for the Q-gates (engine-built or hand-built, same field names).

The config is the producer's statement; the gates only read it.  Anything a gate cannot derive from it is
reported as ``None`` (-> the gate says UNCERTAIN), never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..core.errors import Refused, Uncertain
from .review_recipe import normalise_type

_RANGE = re.compile(r"f?(\d+)\s*-\s*f?(\d+)")


@dataclass(frozen=True)
class Transition:
    id: str
    boundary: int
    type: str
    raw_type: str
    frames: int
    start: int
    end_exclusive: int
    from_id: str
    to_id: str
    continuity: str | None
    layout_change: bool | None


@dataclass(frozen=True)
class Model:
    fps: float
    width: int | None
    height: int | None
    transitions: tuple[Transition, ...]
    icons: tuple[dict, ...]
    words: tuple[dict, ...]
    cards: tuple[dict, ...]
    dialogue: tuple[dict, ...]
    picture_ids: frozenset[str]
    main_frames: int | None
    end_frames: int
    total_frames: int | None
    ending: dict


def _int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise Refused(f"review config: {label} must be an integer, got {value!r}")
    return int(value)


def _transitions(config: dict, recipe: dict) -> tuple[Transition, ...]:
    motion = config.get("motion") or {}
    rows = motion.get("transitions", config.get("transitions"))
    if not isinstance(rows, list) or not rows:
        raise Uncertain("review config has no transitions list (motion.transitions)")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise Refused("review config: a transition row is not an object")
        boundary = _int(row.get("boundary", row.get("frame")), "transition boundary")
        frames = _int(row.get("frames", 0), f"transition f{boundary} frames")
        start = _int(row.get("start", boundary), f"transition f{boundary} start")
        end = _int(row.get("end_exclusive", start + frames), f"transition f{boundary} end_exclusive")
        layout = row.get("layout_change")
        out.append(Transition(
            id=str(row.get("id", f"T{boundary}")), boundary=boundary, raw_type=str(row.get("type", "none")),
            type=normalise_type(row.get("type"), recipe), frames=frames, start=start, end_exclusive=end,
            from_id=str(row.get("from", row.get("from_shot", ""))), to_id=str(row.get("to", row.get("to_shot", ""))),
            continuity=row.get("continuity"), layout_change=layout if isinstance(layout, bool) else None))
    return tuple(sorted(out, key=lambda t: t.boundary))


def _icons(config: dict, events: dict | None) -> tuple[dict, ...]:
    if events and isinstance(events.get("icon_events"), list):
        return tuple(events["icon_events"])
    motion = config.get("motion") or {}
    rows = motion.get("icons", config.get("icons"))
    return tuple(rows) if isinstance(rows, list) else ()


def _words(config: dict) -> tuple[dict, ...]:
    out = []
    for entry in config.get("dialogue") or []:
        for word in entry.get("words") or []:
            out.append({"shot": entry.get("id"), "text": str(word.get("w", "")), "startF": word.get("startF"),
                        "anchor": bool(word.get("anchor")), "icon": word.get("icon")})
    return tuple(out)


def build_model(config: dict, recipe: dict, events: dict | None = None) -> Model:
    """Parse ``config`` (+ optional engine ``events.json``); ``Refused`` for a malformed value."""
    if not isinstance(config, dict):
        raise Refused("review config must be a JSON object")
    fps = config.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
        raise Refused(f"review config: fps must be a positive number, got {fps!r}")
    dialogue = tuple({"id": str(d.get("id")), "start_frame": d.get("start_frame"),
                      "end_frame_exclusive": d.get("end_frame_exclusive")} for d in config.get("dialogue") or [])
    pictures = {d["id"] for d in dialogue}
    for entry in config.get("dialogue") or []:
        pictures |= {str(s.get("source_id")) for s in entry.get("segments") or [] if s.get("source_id")}
    ending = ((config.get("motion") or {}).get("ending")) or config.get("ending") or {}
    end_frames = config.get("end_hold_frames", (ending.get("end_logo") or {}).get("frames", 0))
    main, total = config.get("main_frames"), config.get("total_frames")
    return Model(
        fps=float(fps), width=config.get("width"), height=config.get("height"),
        transitions=_transitions(config, recipe), icons=_icons(config, events), words=_words(config),
        cards=tuple(config.get("outro_cards") or []), dialogue=dialogue, picture_ids=frozenset(pictures),
        main_frames=main if isinstance(main, int) else None, end_frames=end_frames if isinstance(end_frames, int) else 0,
        total_frames=total if isinstance(total, int) else None, ending=ending if isinstance(ending, dict) else {})


def contract_frames(config: dict, model: Model) -> tuple[int | None, str]:
    """The frame count the finished file must have, and where it came from.

    ``total_frames_with_endlogo`` when the config states it, else ``main_frames + end_hold_frames``, else
    ``total_frames + end_hold_frames`` (a config whose ``total_frames`` is the main film only)."""
    stated = config.get("total_frames_with_endlogo")
    if isinstance(stated, int):
        return stated, "total_frames_with_endlogo"
    if model.main_frames is not None:
        return model.main_frames + model.end_frames, "main_frames + end_hold_frames"
    if model.total_frames is not None:
        return model.total_frames + model.end_frames, "total_frames + end_hold_frames"
    return None, "none"


def logo_still_frames(model: Model) -> tuple[int | None, tuple[int, int] | None, str]:
    """(still frame count, (first, last) frame range when stated, source key).

    Order: numeric ``ending.logo_still_frames`` (engine style), a ``still_hold`` range text such as
    ``"f2156-f2221 (66 f)"``, then the ``full_logo_frames`` range text."""
    disc = model.ending.get("logo_disc") or {}
    value = model.ending.get("logo_still_frames", disc.get("still_frames"))
    if isinstance(value, int):
        return value, None, "logo_still_frames"
    for key in ("still_hold", "full_logo_frames"):
        text = disc.get(key)
        match = _RANGE.search(text) if isinstance(text, str) else None
        if match:
            first, last = int(match.group(1)), int(match.group(2))
            return last - first + 1, (first, last), f"logo_disc.{key}"
    return None, None, "none"
