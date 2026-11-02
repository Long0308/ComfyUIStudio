"""Blockout builder emitted by scene_layout.py (do not edit the emitted copy; edit the brief).

DOMAIN: __DOMAIN__    BRIEF: __BRIEF_ID__
Layout guide only: geometry, camera and contact guide. The proxies are gray/colored blockouts,
never character, cow or set art. Workbench engine only: no Cycles, no Eevee, no GPU compute.

Run:  blender --background --python <this file> --python-exit-code 1 -- --out-dir <dir>
      [--width W --height H] [--no-render] [--force]
Writes <out-dir>/<basename>.blend, <basename>-guide.png and <basename>-positions.json.
Exit code 3 = a world-space assertion failed (the JSON is still written for inspection).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

BRIEF = json.loads("__BRIEF_JSON_PLACEHOLDER__")
ENGINE = "BLENDER_WORKBENCH"
ZONE_COLORS = {"garden": (0.30, 0.46, 0.20), "pen": (0.39, 0.57, 0.24), "pasture": (0.39, 0.57, 0.24),
               "floor": (0.62, 0.60, 0.56), "interior": (0.70, 0.68, 0.64), "road": (0.35, 0.35, 0.37),
               "yard": (0.55, 0.52, 0.45), "other": (0.50, 0.50, 0.50)}
FRONT_EDGES = {"min_y": ("y", 0, -1), "max_y": ("y", 1, 1), "min_x": ("x", 0, -1), "max_x": ("x", 1, 1)}
FENCE_COLOR = (0.55, 0.32, 0.15)
PROXY_GRAY = (0.55, 0.55, 0.58)
MARKER_COLOR = (0.95, 0.95, 0.95)
COW_WHITE, COW_BLACK, COW_HOOF = (0.88, 0.87, 0.80), (0.05, 0.06, 0.07), (0.11, 0.09, 0.08)

_MATERIALS: dict[tuple, object] = {}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    try:
        default_dir = Path(__file__).resolve().parent / f"{BRIEF['brief_id']}_out"
    except NameError:  # __file__ missing in some launch modes
        default_dir = Path.cwd() / f"{BRIEF['brief_id']}_out"
    p.add_argument("--out-dir", type=Path, default=default_dir)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--no-render", action="store_true", help="build, save .blend and measure; no render (no GPU use at all)")
    p.add_argument("--force", action="store_true")
    return p.parse_args(argv)


def material(rgb) -> object:
    key = tuple(round(c, 4) for c in rgb)
    if key not in _MATERIALS:
        mat = bpy.data.materials.new(f"guide_{len(_MATERIALS):03d}")
        mat.diffuse_color = (*key, 1.0)  # Workbench color_type MATERIAL reads the viewport color
        _MATERIALS[key] = mat
    return _MATERIALS[key]


def add_part(entity_id: str, kind: str, name: str, shape: str, base: Matrix, center, dims, rgb, **props) -> None:
    """One primitive; dims are full sizes for cube, radii for sphere, (diameter, diameter, height) for cylinder."""
    if shape == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1)
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=1)
    else:
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.5, depth=1)
    obj = bpy.context.object
    obj.name = f"{entity_id}__{name}"
    obj.matrix_world = base @ Matrix.Translation(center) @ Matrix.Diagonal((*dims, 1.0))
    obj.data.materials.append(material(rgb))
    obj["entity_id"], obj["entity_kind"] = entity_id, kind
    for key, value in props.items():
        obj[key] = value


def base_matrix(x: float, y: float, facing_deg: float, scale: float = 1.0) -> Matrix:
    """Proxy local frame looks toward -Y at yaw 0, so yaw = facing_deg + 90."""
    return Matrix.Translation((x, y, 0.0)) @ Matrix.Rotation(math.radians(facing_deg + 90.0), 4, "Z") @ Matrix.Scale(scale, 4)


def build_zones() -> None:
    for zone in BRIEF["ground"]["zones"]:
        (x0, x1), (y0, y1) = zone["x"], zone["y"]
        rgb = zone.get("color") or ZONE_COLORS[zone["kind"]]
        add_part(zone["id"], "zone", "slab", "cube", Matrix.Identity(4), ((x0 + x1) / 2, (y0 + y1) / 2, -0.1),
                 (x1 - x0, y1 - y0, 0.2), rgb)


def build_fence(fence: dict) -> None:
    (x0, x1), (y0, y1) = fence["x"], fence["y"]
    t, h, rgb = fence["thickness_m"], fence["height_m"], fence.get("color") or FENCE_COLOR
    spacing, ident = fence["post_spacing_m"], fence["id"]
    xs = [x0 + i * spacing for i in range(int((x1 - x0) / spacing) + 1)]
    ys = [y0 + i * spacing for i in range(int((y1 - y0) / spacing) + 1)]
    if xs[-1] < x1 - 1e-6:
        xs.append(x1)
    if ys[-1] < y1 - 1e-6:
        ys.append(y1)
    posts = {(x, y0) for x in xs} | {(x, y1) for x in xs} | {(x0, y) for y in ys} | {(x1, y) for y in ys}
    for px, py in sorted(posts):
        add_part(ident, "fence", f"post_{px:+.2f}_{py:+.2f}", "cube", Matrix.Identity(4), (px, py, h / 2), (t, t, h), rgb)
    rail_t = t * 0.65
    for z in fence["rail_heights_m"]:
        for ry in (y0, y1):
            add_part(ident, "fence", f"rail_x_{ry:+.2f}_{z:.2f}", "cube", Matrix.Identity(4),
                     ((x0 + x1) / 2, ry, z), (x1 - x0 + t, rail_t, 0.13), rgb)
        for rx in (x0, x1):
            add_part(ident, "fence", f"rail_y_{rx:+.2f}_{z:.2f}", "cube", Matrix.Identity(4),
                     (rx, (y0 + y1) / 2, z), (rail_t, y1 - y0 + t, 0.13), rgb)


def build_prop(prop: dict) -> None:
    shape = {"box": "cube", "cylinder": "cylinder", "ellipsoid": "sphere"}[prop["kind"]]
    dims = [s / 2 for s in prop["size"]] if shape == "sphere" else prop["size"]
    base = Matrix.Translation(prop["position"]) @ Matrix.Rotation(math.radians(prop.get("yaw_deg", 0.0)), 4, "Z")
    add_part(prop["id"], "prop", "body", shape, base, (0, 0, 0), dims, prop.get("color") or (0.6, 0.5, 0.4))


def build_actor(a: dict) -> None:
    """Blocking proxy: head + torso + legs, with a white facing marker. Not a character."""
    ident, pose = a["id"], a["pose"]
    top = a["head_top_z"]
    floor = a["support"]["top_z"] if a.get("support") else 0.0
    h = top - floor
    rgb = a.get("color") or PROXY_GRAY
    base = base_matrix(a["position"][0], a["position"][1], a["facing_deg"])
    hr = (0.11 if pose == "standing" else 0.15) * h
    head_z = top - hr * 1.15
    torso_bottom = floor + (0.45 if pose == "standing" else 0.10) * h
    torso_top = head_z - hr * 1.0
    torso_z = (torso_bottom + torso_top) / 2
    add_part(ident, "actor", "head", "sphere", base, (0, 0, head_z), (hr, hr, hr * 1.15), rgb, pose=pose)
    add_part(ident, "actor", "marker", "cube", base, (0, -hr * 1.05, head_z), (hr * 0.3, hr * 0.5, hr * 0.3), MARKER_COLOR)
    add_part(ident, "actor", "torso", "sphere", base, (0, 0, torso_z),
             (0.15 * h, 0.11 * h, max((torso_top - torso_bottom) / 2, 0.05)), rgb)
    if pose == "standing":
        for side in (-1, 1):
            add_part(ident, "actor", f"leg_{side}", "cylinder", base, (side * 0.05 * h, 0, torso_bottom / 2),
                     (0.07 * h, 0.07 * h, torso_bottom), rgb)
    elif pose == "seated":
        for side in (-1, 1):
            add_part(ident, "actor", f"thigh_{side}", "cube", base, (side * 0.07 * h, -0.15 * h, floor + 0.06 * h),
                     (0.10 * h, 0.30 * h, 0.09 * h), rgb)
    else:  # kneeling: shins folded behind
        for side in (-1, 1):
            add_part(ident, "actor", f"shin_{side}", "cube", base, (side * 0.07 * h, 0.12 * h, floor + 0.04 * h),
                     (0.09 * h, 0.30 * h, 0.07 * h), rgb)


def build_animal(species: str, m: dict) -> None:
    ident = m["id"]
    s = m["scale"]
    base = base_matrix(m["position"][0], m["position"][1], m["facing_deg"], s)
    rgb = m.get("color") or COW_WHITE
    kw = {"species": species}
    if species != "cow":  # generic box-ish proxy sized from the declared footprint/height
        fp = m["footprint"]
        add_part(ident, "animal", "body", "sphere", base, (fp["offset"][0], fp["offset"][1], m["height_m"] / 2),
                 (fp["half"][0], fp["half"][1], m["height_m"] / 2), rgb, **kw)
        return
    add_part(ident, "animal", "body", "sphere", base, (0, 0, 1.12), (0.88, 1.24, 0.58), rgb, **kw)
    add_part(ident, "animal", "head", "sphere", base, (0, -1.10, 1.47), (0.43, 0.44, 0.42), rgb, **kw)
    for side in (-1, 1):
        for fore_aft in (-0.72, 0.68):
            add_part(ident, "animal", f"leg_{side}_{fore_aft}", "cube", base, (side * 0.51, fore_aft, 0.43), (0.22, 0.22, 0.86), rgb, **kw)
            add_part(ident, "animal", f"hoof_{side}_{fore_aft}", "cube", base, (side * 0.51, fore_aft, 0.05), (0.24, 0.31, 0.11), COW_HOOF, **kw)
    add_part(ident, "animal", "patch_l", "sphere", base, (-0.64, -0.17, 1.22), (0.18, 0.46, 0.30), COW_BLACK, **kw)
    add_part(ident, "animal", "patch_r", "sphere", base, (0.64, 0.45, 1.25), (0.18, 0.34, 0.29), COW_BLACK, **kw)
    add_part(ident, "animal", "udder", "sphere", base, (0, 0, 0.66), (0.30, 0.37, 0.19), rgb, **kw)


def build_camera() -> object:
    cam = BRIEF["camera"]
    pos = Vector((cam["position_xy"][0], cam["position_xy"][1], cam["height_m"]))
    bpy.ops.object.camera_add(location=pos)
    obj = bpy.context.object
    obj.name = "CAMERA"
    obj.rotation_euler = (Vector(cam["target"]) - pos).to_track_quat("-Z", "Y").to_euler()
    obj.data.type = "PERSP"
    obj.data.lens = cam["lens_mm"]
    obj.data.sensor_width = cam["sensor_width_mm"]
    obj.data.sensor_fit = "AUTO"
    obj.data.clip_start, obj.data.clip_end = 0.1, 500.0
    bpy.context.scene.camera = obj
    return obj


def configure_scene(width: int, height: int, png: Path) -> None:
    scene = bpy.context.scene
    scene.unit_settings.system, scene.unit_settings.scale_length = "METRIC", 1.0
    scene.render.engine = ENGINE
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = width, height, 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(png)
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.color = (0.62, 0.73, 0.83)
    shading = scene.display.shading
    shading.light, shading.color_type, shading.show_shadows = "STUDIO", "MATERIAL", True
    try:
        scene.view_settings.view_transform = "Standard"
    except TypeError as exc:  # enum names differ between Blender versions; keep the default
        print(f"view_transform left at default: {exc}")


def entity_bounds(entity_id: str) -> tuple[Vector, Vector]:
    corners = [obj.matrix_world @ Vector(c) for obj in bpy.data.objects if obj.get("entity_id") == entity_id for c in obj.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return lo, hi


def ndc_extent(scene, cam_obj, lo: Vector, hi: Vector) -> dict:
    pts = [world_to_camera_view(scene, cam_obj, Vector((x, y, z))) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    xs, ys = [p.x * 2 - 1 for p in pts], [p.y * 2 - 1 for p in pts]
    return {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)], "min_depth": min(p.z for p in pts)}


def select(selectors, kinds: dict, species: dict) -> list[str]:
    out: list[str] = []
    for sel in selectors:
        if sel in ("actors", "animals"):
            out += [i for i, k in kinds.items() if k == sel[:-1]]
        elif sel.startswith("species:"):
            out += [i for i, sp in species.items() if sp == sel.split(":", 1)[1]]
        else:
            out.append(sel)
    return list(dict.fromkeys(out))


def run_assertions(bounds: dict, ndc: dict, kinds: dict, species: dict) -> list[dict]:
    """Re-check the brief's rules against the geometry actually built in Blender (world space)."""
    fences = {f["id"]: f for f in BRIEF.get("fences", [])}
    results: list[dict] = []

    def record(rule_id: str, kind: str, ok: bool, detail: str) -> None:
        results.append({"rule": rule_id, "type": kind, "passed": ok, "detail": detail})

    rules = list(BRIEF.get("rules", [])) + [{"id": "implicit_camera_frames_actors", "type": "camera_frames", "subjects": ["actors"], "margin": 0.0}]
    for r in rules:
        if r["type"] == "exact_count":
            have = sum(1 for sp in species.values() if sp == r["species"])
            record(r["id"], r["type"], have == r["count"], f"{have} x {r['species']} built, expected {r['count']}")
            continue
        for ident in select(r.get("subjects", []), kinds, species):
            lo, hi = bounds[ident]
            if r["type"] in ("wholly_inside_fence", "outside_fence"):
                f = fences[r["fence"]]
                inset = f["thickness_m"] / 2 + r.get("clearance_m", 0.0)
                if r["type"] == "wholly_inside_fence":
                    slack = min(lo.x - (f["x"][0] + inset), (f["x"][1] - inset) - hi.x, lo.y - (f["y"][0] + inset), (f["y"][1] - inset) - hi.y)
                    record(r["id"], r["type"], slack >= 0, f"{ident}: world slack inside fence {slack:+.3f} m")
                else:
                    hit = hi.x > f["x"][0] - inset and lo.x < f["x"][1] + inset and hi.y > f["y"][0] - inset and lo.y < f["y"][1] + inset
                    record(r["id"], r["type"], not hit, f"{ident}: {'overlaps' if hit else 'clear of'} fence {f['id']}")
                    if r.get("side") == "front":
                        axis, index, sign = FRONT_EDGES[f["front_edge"]]
                        lo_c, hi_c = (lo.x, hi.x) if axis == "x" else (lo.y, hi.y)
                        edge = f[axis][index]
                        slack = (edge - inset) - hi_c if sign < 0 else lo_c - (edge + inset)
                        record(r["id"], "outside_fence.side_front", slack >= 0, f"{ident}: world slack on front side {slack:+.3f} m")
            elif r["type"] == "inside_zone":
                z = next(z for z in BRIEF["ground"]["zones"] if z["id"] == r["zone"])
                ok = lo.x >= z["x"][0] and hi.x <= z["x"][1] and lo.y >= z["y"][0] and hi.y <= z["y"][1]
                record(r["id"], r["type"], ok, f"{ident}: world bbox vs zone {z['id']}")
            elif r["type"] == "camera_frames":
                lim = 1.0 - r.get("margin", 0.0)
                e = ndc[ident]
                ok = e["min_depth"] > 0.1 and min(e["x"][0], e["y"][0]) >= -lim and max(e["x"][1], e["y"][1]) <= lim
                record(r["id"], r["type"], ok, f"{ident}: blender ndc x{[round(v, 3) for v in e['x']]} y{[round(v, 3) for v in e['y']]}")
    return results


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    args = parse_args()
    base = BRIEF["output"].get("basename") or BRIEF["brief_id"]
    out = args.out_dir
    blend, png, positions = out / f"{base}.blend", out / f"{base}-guide.png", out / f"{base}-positions.json"
    if not args.force and any(p.exists() for p in (blend, png, positions)):
        raise FileExistsError(f"outputs exist in {out}; save a new version or pass --force")
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    width, height = args.width or BRIEF["output"]["width"], args.height or BRIEF["output"]["height"]
    configure_scene(width, height, png)

    build_zones()
    for fence in BRIEF.get("fences", []):
        build_fence(fence)
    for prop in BRIEF.get("props", []):
        build_prop(prop)
    kinds: dict[str, str] = {}
    species: dict[str, str] = {}
    for actor in BRIEF.get("actors", []):
        build_actor(actor)
        kinds[actor["id"]] = "actor"
    for group in BRIEF.get("animals", []):
        for member in group["members"]:
            build_animal(group["species"], member)
            kinds[member["id"]] = "animal"
            species[member["id"]] = group["species"]
    cam_obj = build_camera()
    bpy.context.view_layer.update()

    scene = bpy.context.scene
    ids = {o["entity_id"]: o["entity_kind"] for o in bpy.data.objects if "entity_id" in o}
    bounds = {i: entity_bounds(i) for i in ids}
    ndc = {i: ndc_extent(scene, cam_obj, *bounds[i]) for i in ids}
    assertions = run_assertions(bounds, ndc, kinds, species)

    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    rendered = not args.no_render
    if rendered:
        bpy.ops.render.render(write_still=True)
    doc = {
        "schema": "scene-layout-positions/1", "brief_id": BRIEF["brief_id"], "domain": BRIEF["domain"],
        "status": BRIEF["status"], "units": "meters", "blender_version": bpy.app.version_string,
        "render": {"engine": scene.render.engine, "width": width, "height": height, "rendered": rendered},
        "blend": str(blend), "blend_sha256": sha256(blend),
        "png": str(png) if rendered else None, "png_sha256": sha256(png) if rendered else None,
        "camera": {"location": list(cam_obj.location), "lens_mm": cam_obj.data.lens, "sensor_width_mm": cam_obj.data.sensor_width},
        "entities": [{"id": i, "kind": ids[i], "species": species.get(i),
                      "world_bbox_min": list(bounds[i][0]), "world_bbox_max": list(bounds[i][1]),
                      "world_center": list((bounds[i][0] + bounds[i][1]) / 2), "ndc": ndc[i]} for i in sorted(ids)],
        "assertions": assertions,
        "note": "Guide only. Proxies are not character/cow/set art; this is not an accepted storyboard frame.",
    }
    positions.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    failed = [a for a in assertions if not a["passed"]]
    print(json.dumps({"positions": str(positions), "assertions": len(assertions), "failed": len(failed)}))
    if failed:
        for a in failed:
            print("ASSERTION FAILED:", a)
        sys.exit(3)


if __name__ == "__main__":
    main()
