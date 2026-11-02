"""Deterministic English placement sentences for H3 prompts.

    python scene_layout.py placement-text <brief.json> [--ids A,B] [--include-set] [--json]

One short sentence per entity, built only from the brief's numbers and the shot camera, so two shots
that share a layout can repeat identical words, e.g.
    "sealed bottle on the table top, centre-left"
    "Mother seated on the mother bench seat, centre-right, facing screen left"
Order is actors, animals, props, each sorted by id. Screen words are camera-relative (what the
audience sees), never world axes. Pure standard library; the sentence describes the PLANNED layout.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import scene_layout as sl
from scene_set import resolve_set
from scene_track import Tracked, box_centre, box_visible, collect, ndc_box

RESTING_TOLERANCE_M = 0.03   # POLICY/GUESS: a prop whose bottom is within 3 cm of another prop's top rests on it
GROUND_CLEARANCE_M = 0.05    # props whose bottom is lower than this stand on the ground, not "on" another prop
_FACING = ("the camera", "screen right, towards the camera", "screen right", "screen right, away from the camera",
           "away from the camera", "screen left, away from the camera", "screen left", "screen left, towards the camera")


def display_name(item: Tracked) -> str:
    """Label without any parenthesised note, else the id as words; props are lower-case, people/animals keep their case."""
    text = re.sub(r"\s*\(.*?\)", "", item.label or "").strip()
    if item.kind == "prop":
        return (text or re.sub(r"[_-]+", " ", item.id).strip()).lower()
    return text or re.sub(r"[_-]+", " ", item.id).strip().title()


def h_band(x: float) -> str:
    if x < -0.6:
        return "far left"
    if x < -0.15:
        return "centre-left"
    if x <= 0.15:
        return "centre"
    return "centre-right" if x <= 0.6 else "far right"


def v_band(y: float) -> str | None:
    return "upper" if y > 0.4 else "lower" if y < -0.4 else None


def screen_place(brief: dict[str, Any], item: Tracked) -> str:
    box = ndc_box(brief, item.corners)
    if not box_visible(box):
        return "out of frame"
    x, y = box_centre(box)
    vertical = v_band(y)
    return f"{vertical} {h_band(x)}" if vertical else h_band(x)


def facing_phrase(camera: dict[str, Any], facing_deg: float) -> str:
    """Facing direction relative to the camera: 0 = towards it, +90 = screen right."""
    pos = (camera["position_xy"][0], camera["position_xy"][1], camera["height_m"])
    forward = sl._unit(sl._vsub(tuple(camera["target"]), pos))
    right = sl._unit(sl._cross(forward, (0.0, 0.0, 1.0)))
    d = (math.cos(math.radians(facing_deg)), math.sin(math.radians(facing_deg)), 0.0)
    angle = math.degrees(math.atan2(sl._dot(d, right), -sl._dot(d, forward)))
    return _FACING[int(((angle % 360.0) + 22.5) // 45) % 8]


def _resting_on(prop: dict[str, Any], props: list[dict[str, Any]]) -> dict[str, Any] | None:
    bottom = prop["position"][2] - prop["size"][2] / 2
    if bottom <= GROUND_CLEARANCE_M:
        return None
    best = None
    for other in props:
        if other["id"] == prop["id"]:
            continue
        top = other["position"][2] + other["size"][2] / 2
        local = sl._rotate((prop["position"][0] - other["position"][0], prop["position"][1] - other["position"][1]), -other.get("yaw_deg", 0.0))
        if (abs(top - bottom) <= RESTING_TOLERANCE_M and abs(local[0]) <= other["size"][0] / 2
                and abs(local[1]) <= other["size"][1] / 2 and (best is None or other["id"] < best["id"])):
            best = other
    return best


def _name_of_prop(prop: dict[str, Any]) -> str:
    return display_name(Tracked(prop["id"], prop["id"], "prop", (), None, None, (), False, prop.get("label"), None))


def placement_lines(brief: dict[str, Any], base_dir: Path | None = None, ids: list[str] | None = None,
                    include_set: bool = False) -> list[str]:
    """Placement sentences for a VALID brief (a referenced set is merged in first)."""
    resolution = resolve_set(brief, base_dir)
    nb = sl.normalize(resolution.brief)
    props = {p["id"]: p for p in nb.get("props", [])}
    camera = nb["camera"]
    order = {"actor": 0, "animal": 1, "prop": 2}
    lines: list[str] = []
    for item in sorted(collect(resolution, nb), key=lambda t: (order[t.kind], t.id)):
        if ids is not None and item.id not in ids:
            continue
        if ids is None and item.from_set and not include_set:
            continue
        place = screen_place(nb, item)
        if item.kind == "prop":
            support = _resting_on(props[item.id], list(props.values()))
            head = f"{display_name(item)} on the {_name_of_prop(support)}" if support else display_name(item)
            lines.append(f"{head}, {place}")
            continue
        head = display_name(item)
        if item.pose:
            head += f" {item.pose}"
            if item.support_prop_id:
                head += f" on the {_name_of_prop(props[item.support_prop_id])}"
        lines.append(f"{head}, {place}, facing {facing_phrase(camera, item.facing_deg)}")
    return lines
