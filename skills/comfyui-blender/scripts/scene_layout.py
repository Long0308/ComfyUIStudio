#!/usr/bin/env python3
"""Spatial structure API: validate a 3D scene-layout brief and emit a bpy blockout script.

Shared infrastructure for three separate domains (jenniejoy_cartoon_3d, newtecons_live_action,
aec). The brief's `domain` field selects the domain rules; nothing here ever mixes cast,
prompts, workflows, recipes, anchors or acceptance between domains.

    python scene_layout.py validate  <brief.json> [--json]
    python scene_layout.py emit-bpy  <brief.json> <out.py> [--force]
    python scene_layout.py continuity <briefA.json> <briefB.json> [--transition T] [--json]
    python scene_layout.py placement-text <brief.json> [--ids A,B] [--include-set] [--json]

`validate` is pure standard-library Python (never imports bpy). `emit-bpy` writes a
self-contained script that builds the blockout + camera and, run by
`blender --background --python out.py -- [options]`, saves a .blend, a Workbench guide PNG and
a JSON of world-space positions. The emitted script only ever uses the Workbench engine
(no Cycles, no Eevee, so no heavy GPU work).

World axes: +X right, +Y into the scene, +Z up, metres. facing_deg is counter-clockwise from +X
in plan (0 = +X, 90 = +Y, -90 = towards a camera at -Y). Proxies are modelled looking toward
-Y at yaw 0, so the Z rotation applied to a proxy is facing_deg + 90.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # sibling modules import `scene_layout` by name: reuse this module, do not load a second copy
    sys.modules.setdefault("scene_layout", sys.modules[__name__])
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:  # python -I does not put the script directory on sys.path
    sys.path.insert(0, _HERE)

from scene_common import SCHEMA_PATH, SKILL_DIR, Finding, schema_errors  # noqa: E402,F401
from scene_set import resolve_set  # noqa: E402

TEMPLATE_PATH = Path(__file__).with_name("bpy_layout_template.py")
BRIEF_PLACEHOLDER = '"__BRIEF_JSON_PLACEHOLDER__"'

Point = tuple[float, float]

# POLICY/GUESS, NOT MEASURED: default footprints/heights. The cow numbers are read off the
# episode-04 v012 placeholder ellipsoids (body +-0.88 x, head to -1.54 y, rump +1.24 y, highest
# point 1.89 m at scale 1); they describe a graybox proxy, not a cow asset. Other species must
# declare footprint and height_m.
SPECIES_DEFAULTS: dict[str, dict[str, Any]] = {
    "cow": {"half": (0.88, 1.39), "offset": (0.0, -0.15), "height_m": 1.9},
}
# POLICY/GUESS, NOT MEASURED: default actor footprint half-sizes by pose.
POSE_FOOTPRINT: dict[str, tuple[float, float]] = {
    "standing": (0.25, 0.20), "seated": (0.40, 0.45), "kneeling": (0.35, 0.40)}
# POLICY/GUESS, NOT MEASURED: allowed head-top height ABOVE the supporting plane (standing: above
# the ground), fitted loosely around the v012 seated/kneeling proxies; v012 itself asserts none.
POSE_PLANE: dict[str, tuple[float, float]] = {
    "standing": (0.7, 2.3), "seated": (0.55, 1.45), "kneeling": (0.6, 1.45)}
FENCE_DEFAULTS: dict[str, Any] = {
    "height_m": 1.44, "thickness_m": 0.2, "post_spacing_m": 2.0, "rail_heights_m": [0.38, 0.91, 1.31]}
# front_edge = the fence side facing the audience/camera: (axis, index into the [min,max] range, outward sign).
FRONT_EDGES: dict[str, tuple[str, int, int]] = {
    "min_y": ("y", 0, -1), "max_y": ("y", 1, 1), "min_x": ("x", 0, -1), "max_x": ("x", 1, 1)}
MAX_POST_SPACING_M = 2.5
SUPPORT_TOP_TOLERANCE_M = 0.02
NEAR_CLIP_M = 0.1

_CARTOON_ONLY = r"newtecons|char_0\d|live[ _-]?action|bfs_(?:head|body)_swap"
_LIVE_ONLY = r"jennie|(?<![a-z0-9])alice(?![a-z0-9])|milkmaid|cartoon|milk[ _-]and[ _-]mom|04-milk"
FORBIDDEN_TOKENS = {
    "jenniejoy_cartoon_3d": re.compile(_CARTOON_ONLY, re.IGNORECASE),
    "newtecons_live_action": re.compile(_LIVE_ONLY, re.IGNORECASE),
    "aec": re.compile(f"{_CARTOON_ONLY}|{_LIVE_ONLY}", re.IGNORECASE),
}



@dataclass(frozen=True)
class Entity:
    id: str
    kind: str  # "actor" | "animal"
    species: str | None
    zone: str
    polygon: tuple[Point, ...]
    height: float




# --------------------------------------------------------------------------- geometry

def _rotate(point: Point, degrees: float) -> Point:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return (point[0] * c - point[1] * s, point[0] * s + point[1] * c)


def footprint_polygon(position: Point, facing_deg: float, half: Point, offset: Point, scale: float) -> tuple[Point, ...]:
    """Oriented footprint rectangle in world plan; proxy local frame looks toward -Y at yaw 0."""
    corners = [(offset[0] + sx * half[0], offset[1] + sy * half[1]) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    out = []
    for local in corners:
        rx, ry = _rotate((local[0] * scale, local[1] * scale), facing_deg + 90.0)
        out.append((position[0] + rx, position[1] + ry))
    return tuple(out)


def _bounds(points: tuple[Point, ...]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def _inside(points: tuple[Point, ...], x: tuple[float, float], y: tuple[float, float]) -> bool:
    x0, x1, y0, y1 = _bounds(points)
    return x0 >= x[0] and x1 <= x[1] and y0 >= y[0] and y1 <= y[1]


def _vsub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(p - q for p, q in zip(a, b))


def _dot(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum(p * q for p, q in zip(a, b))


def _cross(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: tuple[float, ...]) -> tuple[float, ...]:
    n = math.sqrt(_dot(a, a))
    return tuple(p / n for p in a)


def camera_ndc(camera: dict[str, Any], width: int, height: int, point: tuple[float, float, float]) -> tuple[float, float, float] | None:
    """Project a world point to (ndc_x, ndc_y, depth); None when it is not in front of the camera.

    Matches Blender's world_to_camera_view with zero roll and sensor_fit AUTO (the sensor width
    applies to the larger render dimension). ndc is -1..1 across the frame.
    """
    pos = (camera["position_xy"][0], camera["position_xy"][1], camera["height_m"])
    forward = _unit(_vsub(tuple(camera["target"]), pos))
    right = _unit(_cross(forward, (0.0, 0.0, 1.0)))
    up = _cross(right, forward)
    delta = _vsub(point, pos)
    depth = _dot(delta, forward)
    if depth <= NEAR_CLIP_M:
        return None
    sensor = camera.get("sensor_width_mm", 36.0)
    sx, sy = (sensor, sensor * height / width) if width >= height else (sensor * width / height, sensor)
    lens = camera["lens_mm"]
    return (2 * lens * _dot(delta, right) / (depth * sx), 2 * lens * _dot(delta, up) / (depth * sy), depth)


def entity_corners(entity: Entity) -> list[tuple[float, float, float]]:
    return [(p[0], p[1], z) for p in entity.polygon for z in (0.0, entity.height)]


def framing(camera: dict[str, Any], width: int, height: int, entity: Entity) -> dict[str, Any]:
    """NDC extent of an entity's 8 box corners, plus whether all are in front of the camera."""
    projected = [camera_ndc(camera, width, height, c) for c in entity_corners(entity)]
    if any(p is None for p in projected):
        return {"id": entity.id, "in_front": False, "x": None, "y": None}
    xs, ys = [p[0] for p in projected], [p[1] for p in projected]
    return {"id": entity.id, "in_front": True, "x": (min(xs), max(xs)), "y": (min(ys), max(ys))}


# --------------------------------------------------------------------------- normalize

def normalize(brief: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy with every default resolved (the emitted bpy script consumes only this)."""
    out = copy.deepcopy(brief)
    for fence in out.get("fences", []):
        for key, value in FENCE_DEFAULTS.items():
            fence.setdefault(key, copy.deepcopy(value))
    out["camera"].setdefault("sensor_width_mm", 36.0)
    for actor in out.get("actors", []):
        half = POSE_FOOTPRINT[actor["pose"]]
        actor.setdefault("footprint", {"half": list(half), "offset": [0.0, 0.0]})
        actor["footprint"].setdefault("offset", [0.0, 0.0])
        actor.setdefault("proxy", "blocking_proxy")
    for group in out.get("animals", []):
        defaults = SPECIES_DEFAULTS.get(group["species"])
        for member in group["members"]:
            member.setdefault("scale", 1.0)
            if defaults:
                member.setdefault("footprint", {"half": list(defaults["half"]), "offset": list(defaults["offset"])})
                member.setdefault("height_m", defaults["height_m"])
            if "footprint" in member:
                member["footprint"].setdefault("offset", [0.0, 0.0])
    return out


def entities_of(brief: dict[str, Any]) -> list[Entity]:
    """Actors and animals as footprint entities; `brief` must be normalized."""
    out: list[Entity] = []
    for actor in brief.get("actors", []):
        fp = actor["footprint"]
        out.append(Entity(actor["id"], "actor", None, actor["zone"], footprint_polygon(
            tuple(actor["position"]), actor["facing_deg"], tuple(fp["half"]), tuple(fp["offset"]), 1.0),
            actor["head_top_z"]))
    for group in brief.get("animals", []):
        for m in group["members"]:
            if "footprint" not in m or "height_m" not in m:
                continue  # reported as SPECIES_UNKNOWN by _check_structure
            fp = m["footprint"]
            out.append(Entity(m["id"], "animal", group["species"], m["zone"], footprint_polygon(
                tuple(m["position"]), m["facing_deg"], tuple(fp["half"]), tuple(fp["offset"]), m["scale"]),
                m["height_m"] * m["scale"]))
    return out


def resolve_subjects(selectors: list[str], entities: list[Entity]) -> tuple[list[Entity], list[str]]:
    chosen: dict[str, Entity] = {}
    unknown: list[str] = []
    for sel in selectors:
        if sel == "actors":
            matches = [e for e in entities if e.kind == "actor"]
        elif sel == "animals":
            matches = [e for e in entities if e.kind == "animal"]
        elif sel.startswith("species:"):
            matches = [e for e in entities if e.species == sel.split(":", 1)[1]]
        else:
            matches = [e for e in entities if e.id == sel]
        if not matches:
            unknown.append(sel)
        for e in matches:
            chosen[e.id] = e
    return list(chosen.values()), unknown


# --------------------------------------------------------------------------- validation

def _ranges_ok(r: list[float]) -> bool:
    return r[0] < r[1]


def _check_structure(b: dict[str, Any], add) -> dict[str, list[float]]:
    zones = {z["id"]: z for z in b["ground"]["zones"]}
    ids: dict[str, str] = {}

    def claim(identifier: str, where: str) -> None:
        if identifier in ids:
            add("error", "DUP_ID", where, f"id '{identifier}' already used at {ids[identifier]}")
        ids[identifier] = where

    for i, z in enumerate(b["ground"]["zones"]):
        claim(z["id"], f"ground.zones[{i}]")
        if not (_ranges_ok(z["x"]) and _ranges_ok(z["y"])):
            add("error", "RANGE_ORDER", f"ground.zones[{i}]", "x/y ranges must be [min, max] with min < max")
    for i, f in enumerate(b.get("fences", [])):
        claim(f["id"], f"fences[{i}]")
        if not (_ranges_ok(f["x"]) and _ranges_ok(f["y"])):
            add("error", "RANGE_ORDER", f"fences[{i}]", "x/y ranges must be [min, max] with min < max")
        if f["post_spacing_m"] > MAX_POST_SPACING_M:
            add("warning", "FENCE_GAP", f"fences[{i}]", f"post spacing {f['post_spacing_m']} m > {MAX_POST_SPACING_M} m: not clearly closed")
    for i, p in enumerate(b.get("props", [])):
        claim(p["id"], f"props[{i}]")
    for i, a in enumerate(b.get("actors", [])):
        claim(a["id"], f"actors[{i}]")
    for gi, g in enumerate(b.get("animals", [])):
        if len(g["members"]) != g["count"]:
            add("error", "COUNT_MISMATCH", f"animals[{gi}]", f"{g['species']}: count={g['count']} but {len(g['members'])} member(s) listed")
        for mi, m in enumerate(g["members"]):
            claim(m["id"], f"animals[{gi}].members[{mi}]")
            if "footprint" not in m or "height_m" not in m:
                add("error", "SPECIES_UNKNOWN", f"animals[{gi}].members[{mi}]",
                    f"species '{g['species']}' has no built-in defaults: give footprint and height_m")
    names = list(zones)
    for i, n1 in enumerate(names):
        for n2 in names[i + 1:]:
            a, c = zones[n1], zones[n2]
            ox = min(a["x"][1], c["x"][1]) - max(a["x"][0], c["x"][0])
            oy = min(a["y"][1], c["y"][1]) - max(a["y"][0], c["y"][0])
            if ox > 1e-9 and oy > 1e-9:
                add("warning", "ZONE_OVERLAP", "ground.zones", f"zones '{n1}' and '{n2}' overlap by {ox:.2f} x {oy:.2f} m")
    return {k: z for k, z in zones.items()}


def _check_entities(b: dict[str, Any], entities: list[Entity], zones: dict[str, Any], add) -> None:
    for e in entities:
        zone = zones.get(e.zone)
        if zone is None:
            add("error", "ZONE_UNKNOWN", e.id, f"zone '{e.zone}' is not declared in ground.zones")
        elif not _inside(e.polygon, tuple(zone["x"]), tuple(zone["y"])):
            x0, x1, y0, y1 = _bounds(e.polygon)
            add("error", "NOT_IN_ZONE", e.id,
                f"footprint x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] is not inside zone '{e.zone}' x{zone['x']} y{zone['y']}")
    props = {p["id"]: p for p in b.get("props", [])}
    for a in b.get("actors", []):
        low, high = POSE_PLANE[a["pose"]]
        support = a.get("support")
        base = support["top_z"] if support else 0.0
        rise = a["head_top_z"] - base
        if not low <= rise <= high:
            add("error", "POSE_PLANE", a["id"], f"{a['pose']}: head_top_z {a['head_top_z']} is {rise:.2f} m above its plane z={base}; allowed {low}-{high} m")
        if a["pose"] == "seated" and (not support or support["kind"] not in ("stool", "bench", "chair")):
            add("error", "SEATED_NO_SUPPORT", a["id"], "a seated actor needs support.kind stool|bench|chair with top_z")
        if a["pose"] == "standing" and support and support["top_z"] > 0.05:
            add("warning", "STANDING_ON_SUPPORT", a["id"], "standing actor has a raised support plane")
        if support and support.get("prop_id"):
            prop = props.get(support["prop_id"])
            if prop is None:
                add("error", "SUPPORT_PROP", a["id"], f"support.prop_id '{support['prop_id']}' is not a declared prop")
                continue
            top = prop["position"][2] + prop["size"][2] / 2
            if abs(top - support["top_z"]) > SUPPORT_TOP_TOLERANCE_M:
                add("error", "SUPPORT_TOP", a["id"], f"support.top_z {support['top_z']} != top of prop '{prop['id']}' ({top:.3f})")
            local = _rotate((a["position"][0] - prop["position"][0], a["position"][1] - prop["position"][1]), -prop.get("yaw_deg", 0.0))
            if abs(local[0]) > prop["size"][0] / 2 or abs(local[1]) > prop["size"][1] / 2:
                add("error", "SUPPORT_XY", a["id"], f"actor position is not over prop '{prop['id']}'")


def _fence_inset(fence: dict[str, Any], clearance: float) -> float:
    return fence["thickness_m"] / 2 + clearance


def _front_slack(fence: dict[str, Any], bounds: tuple[float, float, float, float], inset: float) -> float:
    """Metres an entity lies on the front side beyond the fence's front_edge outer face (negative = not in front)."""
    axis, index, sign = FRONT_EDGES[fence["front_edge"]]
    lo, hi = (bounds[0], bounds[1]) if axis == "x" else (bounds[2], bounds[3])
    edge = fence[axis][index]
    return (edge - inset) - hi if sign < 0 else lo - (edge + inset)


def _behind_gap(fence: dict[str, Any], bounds: tuple[float, float, float, float], inset: float) -> float:
    """Metres between the entity's NEAREST point to the front_edge and that edge's inner face (negative = in front of it)."""
    axis, index, sign = FRONT_EDGES[fence["front_edge"]]
    lo, hi = (bounds[0], bounds[1]) if axis == "x" else (bounds[2], bounds[3])
    edge = fence[axis][index]
    return lo - (edge + inset) if sign < 0 else (edge - inset) - hi


def _camera_front_slack(fence: dict[str, Any], camera: dict[str, Any]) -> float:
    axis, index, sign = FRONT_EDGES[fence["front_edge"]]
    coord = camera["position_xy"][0 if axis == "x" else 1]
    return sign * (coord - fence[axis][index])


def _check_rules(b: dict[str, Any], entities: list[Entity], add) -> None:
    fences = {f["id"]: f for f in b.get("fences", [])}
    zones = {z["id"]: z for z in b["ground"]["zones"]}
    width, height = b["output"]["width"], b["output"]["height"]
    for i, rule in enumerate(b.get("rules", [])):
        where, kind = f"rules[{i}]({rule['id']})", rule["type"]
        if kind == "exact_count":
            if "species" not in rule or "count" not in rule:
                add("error", "RULE_ARGS", where, "exact_count needs species and count")
                continue
            have = sum(1 for e in entities if e.species == rule["species"])
            if have != rule["count"]:
                add("error", "RULE_COUNT", where, f"expected exactly {rule['count']} '{rule['species']}', found {have}")
            continue
        subjects, unknown = resolve_subjects(rule.get("subjects", []), entities)
        for sel in unknown:
            add("error", "RULE_SUBJECT", where, f"selector '{sel}' matches nothing")
        if not rule.get("subjects"):
            add("error", "RULE_ARGS", where, f"{kind} needs subjects")
        if kind in ("wholly_inside_fence", "outside_fence"):
            fence = fences.get(rule.get("fence", ""))
            if fence is None:
                add("error", "RULE_ARGS", where, f"unknown fence '{rule.get('fence')}'")
                continue
            inset = _fence_inset(fence, rule.get("clearance_m", 0.0))
            if kind == "wholly_inside_fence" and _camera_front_slack(fence, b["camera"]) <= 0:
                add("error", "FRONT_EDGE_CAMERA", where,
                    f"camera is not on the front side of fence '{fence['id']}' (front_edge={fence['front_edge']}): "
                    "subjects 'behind the front fence' would be seen from the wrong side")
            for e in subjects:
                x0, x1, y0, y1 = _bounds(e.polygon)
                behind = _behind_gap(fence, (x0, x1, y0, y1), inset)
                in_front = _front_slack(fence, (x0, x1, y0, y1), inset)
                if kind == "outside_fence" and rule.get("side") == "front" and in_front < 0:
                    add("error", "OUTSIDE_NOT_FRONT", e.id,
                        f"not wholly on the front side of fence '{fence['id']}' (front_edge={fence['front_edge']}), short by {-in_front:.2f} m")
                if kind == "wholly_inside_fence":
                    slack = min(x0 - (fence["x"][0] + inset), (fence["x"][1] - inset) - x1,
                                y0 - (fence["y"][0] + inset), (fence["y"][1] - inset) - y1)
                    if slack < 0:
                        add("error", "NOT_BEHIND_FENCE", e.id,
                            f"crosses/escapes fence '{fence['id']}' by {-slack:.2f} m (inset {inset:.3f}); footprint x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}]; "
                            f"nearest point is {abs(behind):.2f} m {'behind' if behind >= 0 else 'IN FRONT OF'} the inner face of front_edge={fence['front_edge']}")
                else:
                    hit = (x1 > fence["x"][0] - inset and x0 < fence["x"][1] + inset
                           and y1 > fence["y"][0] - inset and y0 < fence["y"][1] + inset)
                    if hit:
                        add("error", "INSIDE_FENCE", e.id, f"footprint overlaps fence '{fence['id']}' (inset {inset:.3f}); it must stay outside")
        elif kind == "inside_zone":
            zone = zones.get(rule.get("zone", ""))
            if zone is None:
                add("error", "RULE_ARGS", where, f"unknown zone '{rule.get('zone')}'")
                continue
            for e in subjects:
                if not _inside(e.polygon, tuple(zone["x"]), tuple(zone["y"])):
                    add("error", "NOT_IN_ZONE", e.id, f"not wholly inside zone '{zone['id']}'")
        elif kind == "camera_frames":
            _frame_errors(b["camera"], width, height, subjects, rule.get("margin", 0.0), where, add)


def _frame_errors(camera: dict[str, Any], width: int, height: int, subjects: list[Entity], margin: float, where: str, add) -> None:
    limit = 1.0 - margin
    for e in subjects:
        f = framing(camera, width, height, e)
        if not f["in_front"]:
            add("error", "CAMERA_BEHIND", where, f"{e.id}: part of it is behind the camera/near clip")
            continue
        (x0, x1), (y0, y1) = f["x"], f["y"]
        if x0 < -limit or x1 > limit or y0 < -limit or y1 > limit:
            add("error", "CAMERA_CROP", where,
                f"{e.id}: ndc x[{x0:.3f},{x1:.3f}] y[{y0:.3f},{y1:.3f}] leaves the +-{limit:.2f} frame")


def _walk_text(node: Any, path: str):
    """Yield (path, text, is_key) for every string value and every dict key below `node`."""
    if isinstance(node, str):
        yield path, node, False
    elif isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}", str(k), True
            yield from _walk_text(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_text(v, f"{path}[{i}]")


def _check_domain(b: dict[str, Any], add) -> None:
    domain = b["domain"]
    pattern = FORBIDDEN_TOKENS[domain]
    for key, value in b.items():
        if key == "domain":
            continue
        for path, text, is_key in _walk_text(value, key):
            hit = pattern.search(text)
            if hit:
                add("error", "DOMAIN_LEAK", path,
                    f"'{hit.group(0)}' in a {'key' if is_key else 'value'} belongs to another domain; brief domain is {domain}")
    if domain == "newtecons_live_action" and b["status"] != "previz_only":
        add("error", "DOMAIN_STATUS", "status", "newtecons_live_action briefs are previz_only (blocking proxies, never character generation)")
    if domain == "jenniejoy_cartoon_3d" and b["status"] == "previz_only":
        add("error", "DOMAIN_STATUS", "status", "jenniejoy_cartoon_3d briefs are layout_guide_only (or draft)")
    for i, a in enumerate(b.get("actors", [])):
        where = f"actors[{i}]"
        if a.get("proxy", "blocking_proxy") != "blocking_proxy":
            add("error", "DOMAIN_PROXY", where, "actors are blocking proxies only")
        if domain != "jenniejoy_cartoon_3d" and a.get("cast_ref"):
            add("error", "DOMAIN_CAST", where, f"cast_ref is only allowed in jenniejoy_cartoon_3d; {domain} previz binds no characters")
        if domain == "newtecons_live_action" and a["role"] != "proxy":
            add("error", "DOMAIN_ROLE", where, "live-action previz actors must have role 'proxy'")
        if domain == "aec" and a["role"] != "scale_figure":
            add("error", "DOMAIN_ROLE", where, "aec actors must have role 'scale_figure'")
    if domain in ("aec", "newtecons_live_action") and b.get("animals"):
        add("error", "DOMAIN_ANIMALS", "animals", f"{domain} layouts carry no animal proxies (blocking proxies for people/set only)")


def validate(brief: dict[str, Any], base_dir: Path | None = None) -> tuple[list[Finding], dict[str, Any]]:
    """Return (findings, info). info carries per-entity framing numbers for the report.

    `base_dir` is where a `set` reference is looked up (the brief file's folder; default: cwd).
    """
    findings: list[Finding] = []

    def add(level: str, code: str, where: str, message: str) -> None:
        findings.append(Finding(level, code, where, message))

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for message in schema_errors(brief, schema, schema):
        add("error", "SCHEMA", message.split(":", 1)[0], message.split(":", 1)[1].strip())
    if findings:
        return findings, {}
    resolution = resolve_set(brief, base_dir)
    findings.extend(resolution.findings)
    if any(f.level == "error" for f in findings):
        return findings, {}
    b = normalize(resolution.brief)
    cam = b["camera"]
    if (cam["position_xy"][0], cam["position_xy"][1], cam["height_m"]) == tuple(cam["target"]):
        add("error", "CAMERA_DEGENERATE", "camera", "camera position equals target")
    elif cam["position_xy"] == cam["target"][:2]:
        add("error", "CAMERA_DEGENERATE", "camera", "camera looks straight up/down: roll is undefined")
    if findings:
        return findings, {}
    zones = _check_structure(b, add)
    entities = entities_of(b)
    _check_entities(b, entities, zones, add)
    _check_rules(b, entities, add)
    actors = [e for e in entities if e.kind == "actor"]
    _frame_errors(cam, b["output"]["width"], b["output"]["height"], actors, 0.0, "camera(actors)", add)
    _check_domain(b, add)
    info: dict[str, Any] = {"framing": [framing(b["camera"], b["output"]["width"], b["output"]["height"], e) for e in entities]}
    if resolution.set_id:
        info["set_id"] = resolution.set_id
    return findings, info


# --------------------------------------------------------------------------- emit

def emit_bpy(brief: dict[str, Any], base_dir: Path | None = None) -> str:
    """Return the text of a self-contained bpy script for a VALID brief (a referenced set is merged in)."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if BRIEF_PLACEHOLDER not in template:
        raise ValueError(f"template placeholder missing in {TEMPLATE_PATH}")
    literal = repr(json.dumps(normalize(resolve_set(brief, base_dir).brief), ensure_ascii=True, sort_keys=True))
    return (template.replace(BRIEF_PLACEHOLDER, literal)
            .replace("__DOMAIN__", brief["domain"]).replace("__BRIEF_ID__", brief["brief_id"]))


# --------------------------------------------------------------------------- CLI

def load_brief(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _cmd_validate(args: argparse.Namespace) -> int:
    findings, info = validate(load_brief(args.brief), args.brief.parent)
    errors = [f for f in findings if f.level == "error"]
    if args.json:
        print(json.dumps({"valid": not errors, "findings": [f.__dict__ for f in findings], **info}, indent=2))
    else:
        for f in findings:
            print(f.line())
        for row in info.get("framing", []):
            if row["in_front"]:
                print(f"INFO    framing {row['id']}: ndc x[{row['x'][0]:.3f},{row['x'][1]:.3f}] y[{row['y'][0]:.3f},{row['y'][1]:.3f}]")
        warnings = len(findings) - len(errors)
        print(f"{'INVALID' if errors else 'VALID'}: {len(errors)} error(s), {warnings} warning(s) in {args.brief.name}")
    return 1 if errors else 0


def _cmd_emit(args: argparse.Namespace) -> int:
    brief = load_brief(args.brief)
    findings, _ = validate(brief, args.brief.parent)
    errors = [f for f in findings if f.level == "error"]
    if errors:
        for f in errors:
            print(f.line(), file=sys.stderr)
        print(f"refusing to emit: {len(errors)} validation error(s)", file=sys.stderr)
        return 1
    if args.out.exists() and not args.force:
        print(f"refusing to overwrite {args.out} (save a new version or pass --force)", file=sys.stderr)
        return 2
    text = emit_bpy(brief, args.brief.parent)
    compile(text, str(args.out), "exec")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.out} ({len(text.splitlines())} lines); run: blender --background --python \"{args.out}\" --python-exit-code 1 -- --out-dir <dir>")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="pure-Python brief validation (schema, counts, zones, fences, camera framing, domain)")
    v.add_argument("brief", type=Path)
    v.add_argument("--json", action="store_true", help="machine-readable report")
    v.set_defaults(func=_cmd_validate)
    e = sub.add_parser("emit-bpy", help="write a bpy script that builds the blockout (Workbench only)")
    e.add_argument("brief", type=Path)
    e.add_argument("out", type=Path)
    e.add_argument("--force", action="store_true", help="overwrite an existing output script")
    e.set_defaults(func=_cmd_emit)
    import scene_continuity  # after this module is fully defined: it imports scene_layout back
    scene_continuity.add_parsers(sub)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"scene_layout: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
