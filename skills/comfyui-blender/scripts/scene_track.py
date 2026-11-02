"""Entity tracking helpers shared by `continuity` and `placement-text`.

`collect` turns a resolved + normalized brief into `Tracked` records (actors, animal members and
props) with world position, facing, pose and 8 world-space box corners. `ndc_box` projects those
corners with the shot's own camera, exactly like `scene_layout.framing` (same projection code).
Pure standard library.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import scene_layout as sl
from scene_set import SetResolution

Corner = tuple[float, float, float]
Box = tuple[float, float, float, float]  # x0, x1, y0, y1 in NDC (-1..1 across the frame)


@dataclass(frozen=True)
class Tracked:
    key: str          # match key across shots: track_as, else id
    id: str
    kind: str         # "actor" | "animal" | "prop"
    position: tuple[float, ...]   # actors/animals: (x, y); props: (x, y, z)
    facing_deg: float | None      # actors/animals: facing_deg; props: yaw_deg
    pose: str | None
    corners: tuple[Corner, ...]
    from_set: bool
    label: str | None
    support_prop_id: str | None


def prop_corners(prop: dict[str, Any]) -> tuple[Corner, ...]:
    """Bounding-box corners of a prop (cylinders/ellipsoids use their size box: conservative)."""
    px, py, pz = prop["position"]
    sx, sy, sz = prop["size"]
    yaw = prop.get("yaw_deg", 0.0)
    out: list[Corner] = []
    for dx in (-0.5, 0.5):
        for dy in (-0.5, 0.5):
            rx, ry = sl._rotate((dx * sx, dy * sy), yaw)
            for dz in (-0.5, 0.5):
                out.append((px + rx, py + ry, pz + dz * sz))
    return tuple(out)


def collect(resolution: SetResolution, brief: dict[str, Any]) -> list[Tracked]:
    """`brief` must be the normalized, resolved brief (sl.normalize(resolution.brief)); order is actors, animals, props."""
    entities = {e.id: e for e in sl.entities_of(brief)}
    out: list[Tracked] = []
    for a in brief.get("actors", []):
        out.append(Tracked(a.get("track_as", a["id"]), a["id"], "actor", tuple(a["position"]), a["facing_deg"], a["pose"],
                           tuple(sl.entity_corners(entities[a["id"]])), False, a.get("label"),
                           (a.get("support") or {}).get("prop_id")))
    for group in brief.get("animals", []):
        for m in group["members"]:
            out.append(Tracked(m.get("track_as", m["id"]), m["id"], "animal", tuple(m["position"]), m["facing_deg"], None,
                               tuple(sl.entity_corners(entities[m["id"]])), False, m.get("label"), None))
    for p in brief.get("props", []):
        out.append(Tracked(p.get("track_as", p["id"]), p["id"], "prop", tuple(p["position"]), p.get("yaw_deg", 0.0), None,
                           prop_corners(p), p["id"] in resolution.set_prop_ids, p.get("label"), None))
    return out


def ndc_box(brief: dict[str, Any], corners: tuple[Corner, ...]) -> Box | None:
    """NDC extent of the corners in the brief's camera; None when any corner is behind the camera/near clip."""
    out = brief["output"]
    pts = [sl.camera_ndc(brief["camera"], out["width"], out["height"], c) for c in corners]
    if any(p is None for p in pts):
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), max(xs), min(ys), max(ys))


def box_visible(box: Box | None) -> bool:
    return box is not None and box[1] >= -1.0 and box[0] <= 1.0 and box[3] >= -1.0 and box[2] <= 1.0


def box_centre(box: Box) -> tuple[float, float]:
    return ((box[0] + box[1]) / 2, (box[2] + box[3]) / 2)


def box_iou(a: Box, b: Box) -> float:
    iw = min(a[1], b[1]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[2], b[2])
    inter = iw * ih if iw > 0 and ih > 0 else 0.0
    union = (a[1] - a[0]) * (a[3] - a[2]) + (b[1] - b[0]) * (b[3] - b[2]) - inter
    return inter / union if union > 0 else 0.0
