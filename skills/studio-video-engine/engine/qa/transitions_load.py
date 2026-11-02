"""Inputs of ``jjv qa transitions``: the boundary rows and the measured first spoken frame of every line.

* ``--boundaries`` is either an editorial ``boundaries.json`` (``jjv/boundaries/v1``, rows resolved through the
  preset catalog, so the window is the preset's own) or a review config with ``motion.transitions`` (the rows the
  render actually used: ``start`` / ``end_exclusive`` as written).
* The first spoken frame of a line comes from the word timing (``--timing``: first word ``start_frame``, else the
  line start + ``start_s``); a review config's own ``dialogue[].words[].startF`` is the fallback.  A line that
  has no words is recorded as silent (frame ``None``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.errors import Refused
from ..editorial import presets, transitions
from .review_model import Transition, _transitions
from .review_recipe import effective_recipe, normalise_type

BOUNDARIES_SCHEMA = "jjv/boundaries/v1"


@dataclass(frozen=True)
class Row:
    """One boundary: the review-model transition plus the catalog preset it resolves to and its declared framing."""
    t: Transition
    preset: str | None
    framing: str | None
    params: dict


def is_graphic(name: str, q4: dict) -> bool:
    return name in q4["graphic_ids"] or any(name.startswith(prefix) for prefix in q4["graphic_prefixes"])


def _from_boundaries(doc: dict, recipe: dict) -> tuple[Row, ...]:
    rows = doc.get("boundaries")
    if not isinstance(rows, list) or not rows:
        raise Refused("boundaries document has no boundaries list")
    out = []
    for raw in rows:
        if not isinstance(raw, dict) or not isinstance(raw.get("frame"), int) or isinstance(raw.get("frame"), bool):
            raise Refused("a boundaries row needs an integer 'frame' (the start of to_shot); "
                          "pass the review config instead when the table leaves it out")
        row = transitions.resolve_row(raw)
        start, end = transitions.window(row)
        layout = row.get("framing")
        t = Transition(id=f"T{row['frame']}", boundary=row["frame"], type=normalise_type(row["type"], recipe),
                       raw_type=str(row["type"]), frames=row["frames"], start=start, end_exclusive=end,
                       from_id=row["from_shot"], to_id=row["to_shot"], continuity=row.get("continuity"),
                       layout_change=False if layout == "same_framing" else None)
        out.append(Row(t, row["preset"], layout, row["params"]))
    return tuple(sorted(out, key=lambda r: r.t.boundary))


def _from_config(doc: dict, recipe: dict) -> tuple[Row, ...]:
    motion = doc.get("motion") or {}
    raw = {int(r.get("boundary", r.get("frame", -1))): r for r in motion.get("transitions", doc.get("transitions")) or []
           if isinstance(r, dict)}
    out = []
    for t in _transitions(doc, recipe):
        name = presets.resolve_name(t.type, t.frames)
        source = raw.get(t.boundary, {})
        params = source.get("params") if isinstance(source.get("params"), dict) else {}
        out.append(Row(t, name if name in presets.catalog()["presets"] else None, source.get("framing"), params))
    return tuple(out)


def load_rows(doc: object, recipe: dict) -> tuple[tuple[Row, ...], str, dict]:
    """(rows, source kind, recipe in force).  A review config may only tighten the recipe (like ``qa review``)."""
    if not isinstance(doc, dict):
        raise Refused("--boundaries must be a JSON object")
    if doc.get("schema") == BOUNDARIES_SCHEMA:
        return _from_boundaries(doc, recipe), "boundaries", recipe
    if "motion" in doc or "transitions" in doc:
        merged, _sources = effective_recipe(recipe, doc)
        return _from_config(doc, merged), "review-config", merged
    raise Refused(f"--boundaries is neither a {BOUNDARIES_SCHEMA} document nor a review config with motion.transitions")


def _first_of(words: list, line_start: object, fps: float) -> tuple[int, str] | None:
    found = []
    for word in words:
        if isinstance(word.get("start_frame"), int):
            found.append((word["start_frame"], word))
        elif isinstance(word.get("startF"), int):
            found.append((word["startF"], word))
        elif isinstance(line_start, int) and isinstance(word.get("start_s"), (int, float)):
            found.append((line_start + round(word["start_s"] * fps), word))  # start_s is relative to the line start
    if not found:
        return None
    frame, word = min(found, key=lambda pair: pair[0])
    return frame, str(word.get("text") or word.get("raw_text") or word.get("w") or "")


def spoken_index(timing: dict | None, config: dict | None, fps: float) -> dict[str, dict]:
    """``{line id: {"frame": first spoken frame | None (silent), "source", "word"}}``; the timing wins over the config."""
    index: dict[str, dict] = {}
    if config:
        for entry in config.get("dialogue") or []:
            found = _first_of(entry.get("words") or [], entry.get("start_frame"), fps)
            index[str(entry.get("id"))] = {"frame": found[0] if found else None, "word": found[1] if found else None,
                                           "source": "config.dialogue.words.startF"}
    if timing:
        stated = timing.get("fps")
        if isinstance(stated, (int, float)) and abs(stated - fps) > 1e-6:
            raise Refused(f"word timing is at {stated} fps but the episode delivers {fps} fps")
        for entry in timing.get("entries") or []:
            found = _first_of(entry.get("words") or [], entry.get("start_frame"), fps)
            index[str(entry.get("id"))] = {"frame": found[0] if found else None, "word": found[1] if found else None,
                                           "source": "word timing"}
    return index
