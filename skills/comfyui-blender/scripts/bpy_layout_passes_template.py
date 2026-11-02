"""Control-pass code APPENDED to an emitted scene_layout.py blockout script (do not run on its own).

Written for `jjv layout render` (studio-video-engine, Q-2). `bpy_layout_template.py` is untouched: the engine
emits the base script with `scene_layout.py emit-bpy`, replaces the placeholder below with a JSON config and
appends this file. The base `main()` has already built the scene, saved the .blend and (unless --no-render)
rendered the Workbench beauty guide; this code then writes the CONTROL PASSES from the same camera:

  <base>-depth.png       16-bit gray, value 65535 = nearest hit ... 1 = farthest hit, 0 = no hit (near/far in -passes.json)
  <base>-depth-raw.npy   float32 linear z-depth in metres (0.0 = no hit)
  <base>-mask-id.png     8-bit RGB entity index map (index = R + 256 * G, 0 = background); legend in -mask-legend.json
  <base>-mask-<id>.png   8-bit gray 255/0 binary mask per actor and animal
  <base>-passes.json     what was written, sizes, hit counts, sha256 of every file

Method: one CPU ray per pixel centre with scene.ray_cast. No render engine, no GPU, no compositor, so the passes
do not depend on Workbench/Eevee pass support and the result is deterministic. Guide geometry only: proxies are
blockouts, not character art (see comfyui-blender SKILL, Spatial structure API).
"""
import hashlib
import json
import struct
import sys
import time
import zlib
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

PASS_CONFIG = json.loads("__PASS_CONFIG_JSON_PLACEHOLDER__")
MASKED_KINDS = ("actor", "animal")


def _argv() -> list:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _option(name: str, default):
    argv = _argv()
    return type(default)(argv[argv.index(name) + 1]) if name in argv else default


def png_bytes(array: "np.ndarray", bit_depth: int) -> bytes:
    """Minimal PNG encoder: gray (H, W) or RGB (H, W, 3), 8 or 16 bit."""
    height, width = array.shape[:2]
    color_type = 2 if array.ndim == 3 else 0
    raw = (array.astype(">u2") if bit_depth == 16 else array.astype(np.uint8)).tobytes()
    rows = np.frombuffer(raw, dtype=np.uint8).reshape(height, -1)
    body = np.concatenate([np.zeros((height, 1), dtype=np.uint8), rows], axis=1).tobytes()

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(body, 6)) + chunk(b"IEND", b"")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def camera_rays(scene, cam, width: int, height: int):
    """Origin, forward axis and the per-pixel world directions (row-major, top row first)."""
    corners = [Vector(v) for v in cam.data.view_frame(scene=scene)]
    xs, ys = [c.x for c in corners], [c.y for c in corners]
    z = corners[0].z
    u = (np.arange(width) + 0.5) / width
    v = (np.arange(height) + 0.5) / height
    local_x = min(xs) + u * (max(xs) - min(xs))
    local_y = max(ys) - v * (max(ys) - min(ys))
    grid_x, grid_y = np.meshgrid(local_x, local_y)
    local = np.stack([grid_x, grid_y, np.full_like(grid_x, z)], axis=-1).reshape(-1, 3)
    rotation = np.array(cam.matrix_world.to_3x3())
    world = local @ rotation.T
    world /= np.linalg.norm(world, axis=1, keepdims=True)
    forward = np.array(cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0)))
    return np.array(cam.matrix_world.translation), forward, world


def cast_all(scene, depsgraph, origin, forward, directions, far: float):
    """Per-pixel (entity id or None, z-depth); ray_cast returns the nearest hit object."""
    start = Vector(origin.tolist())
    count = len(directions)
    depth = np.zeros(count, dtype=np.float32)
    owners = [None] * count
    for i in range(count):
        d = directions[i]
        hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, start, Vector((d[0], d[1], d[2])), distance=far)
        if hit:
            owners[i] = obj.get("entity_id") if obj is not None else None
            depth[i] = float(np.dot(np.array(location) - origin, forward))
    return owners, depth


def entity_table(owners) -> tuple:
    kinds = {}
    for obj in bpy.data.objects:
        if "entity_id" in obj:
            kinds[obj["entity_id"]] = (obj.get("entity_kind"), obj.get("species"))
    ids = sorted(kinds)
    return ids, {ident: index + 1 for index, ident in enumerate(ids)}, kinds


def passes_main() -> None:
    started = time.monotonic()
    scene = bpy.context.scene
    cam = scene.camera
    base = PASS_CONFIG["basename"]
    out = Path(_option("--out-dir", Path(PASS_CONFIG["out_dir"])))
    width = _option("--width", scene.render.resolution_x)
    height = _option("--height", scene.render.resolution_y)
    wanted = set(PASS_CONFIG["passes"])
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin, forward, directions = camera_rays(scene, cam, width, height)
    owners, depth = cast_all(scene, depsgraph, origin, forward, directions, float(PASS_CONFIG["far_m"]))
    ids, index_of, kinds = entity_table(owners)
    index = np.array([index_of.get(o, 0) if o else 0 for o in owners], dtype=np.int32).reshape(height, width)
    z = depth.reshape(height, width)
    hit = z > 0
    files, info = {}, {"width": width, "height": height, "hit_pixels": int(hit.sum()), "total_pixels": width * height}
    if "depth" in wanted:
        near, far = (float(z[hit].min()), float(z[hit].max())) if hit.any() else (0.0, 0.0)
        span = (far - near) or 1.0
        encoded = np.where(hit, 1 + np.round(65534 * (1.0 - (z - near) / span)), 0).astype(np.uint16)
        files[f"{base}-depth.png"] = png_bytes(encoded, 16)
        np.save(out / f"{base}-depth-raw.npy", z.astype(np.float32))
        info["depth"] = {"near_m": near, "far_m": far, "encoding": "uint16: 65535 near .. 1 far, 0 no hit",
                         "raw": f"{base}-depth-raw.npy"}
    if "mask" in wanted:
        rgb = np.stack([index & 255, (index >> 8) & 255, np.zeros_like(index)], axis=-1).astype(np.uint8)
        files[f"{base}-mask-id.png"] = png_bytes(rgb, 8)
        legend = {ident: {"index": index_of[ident], "kind": kinds[ident][0], "species": kinds[ident][1],
                          "pixels": int((index == index_of[ident]).sum())} for ident in ids}
        for ident in ids:
            if kinds[ident][0] in MASKED_KINDS:
                files[f"{base}-mask-{ident}.png"] = png_bytes(((index == index_of[ident]) * 255).astype(np.uint8), 8)
        info["mask"] = {"encoding": "index = R + 256 * G, 0 background", "legend": legend}
    written = {}
    for name, payload in files.items():
        (out / name).write_bytes(payload)
    for name in list(files) + ([f"{base}-depth-raw.npy"] if "depth" in wanted else []):
        written[name] = {"sha256": sha256(out / name), "bytes": (out / name).stat().st_size}
    info.update(schema="scene-layout-passes/1", passes=sorted(wanted), files=written, elapsed_s=round(time.monotonic() - started, 3),
                blender_version=bpy.app.version_string, method="scene.ray_cast per pixel centre (CPU)")
    (out / f"{base}-passes.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passes": str(out / f"{base}-passes.json"), "hit_pixels": info["hit_pixels"], "elapsed_s": info["elapsed_s"]}))


if __name__ == "__main__":
    passes_main()
