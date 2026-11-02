"""Bảng domain của ``jjv video`` (dữ liệu: ``recipes/video/routes-v001.json``).

Code ở đây không nêu tên domain nào: domain được phép, template H3 theo domain, port graph, lưới frame, seed
gốc và chính sách upscale đều đọc từ file routes.  Domain không có trong bảng bị từ chối trước khi ghi file.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path
from ..layout.context import REPO_ROOT, SKILL_ROOT, Context

ROUTES_SCHEMA = "jjv/video-routes/v1"
ROUTES = SKILL_ROOT / "recipes" / "video" / "routes-v001.json"
TOP_KEYS = ("allowed_domains", "domains", "stages", "max_lanes", "shotlist_schemas")
PORT_KEYS = ("face", "anchor", "wav", "prompt", "length", "seed", "editorial_node", "output_ports")
LIST_PORTS = ("face", "anchor", "wav", "output_ports")
DOTTED_PORTS = ("prompt", "length", "seed")
STAGE_COUNT = 5


def load_routes(path: Path | None = None) -> dict[str, Any]:
    """Đọc + kiểm tra hình dạng tối thiểu; trả về bản sao kèm ``_path``/``_sha256`` (để ghi vào receipt)."""
    file = Path(path) if path else ROUTES
    routes = read_json(file)
    if not isinstance(routes, dict) or routes.get("schema") != ROUTES_SCHEMA:
        raise Refused(f"{file}: not a {ROUTES_SCHEMA} document")
    missing = [key for key in TOP_KEYS if key not in routes]
    if missing:
        raise Refused(f"{file}: video routes missing {missing}")
    if not isinstance(routes["allowed_domains"], list) or not isinstance(routes["domains"], dict):
        raise Refused(f"{file}: allowed_domains must be a list and domains an object")
    if not isinstance(routes["stages"], list) or len(routes["stages"]) != STAGE_COUNT:
        raise Refused(f"{file}: stages must name the {STAGE_COUNT} ComfyUI groups in order")
    lanes = routes["max_lanes"]
    if not isinstance(lanes, int) or isinstance(lanes, bool) or lanes < 1:
        raise Refused(f"{file}: max_lanes must be a positive integer")
    return {**routes, "_path": str(file), "_sha256": sha256_file(file)}


def _check_ports(domain_id: str, ports: Any) -> None:
    if not isinstance(ports, dict) or any(key not in ports for key in PORT_KEYS):
        raise Refused(f"video routes: domain {domain_id!r} ports must hold {list(PORT_KEYS)}")
    for key in LIST_PORTS:
        rows = ports[key]
        if not isinstance(rows, list) or not rows or not all(isinstance(p, list) and len(p) == 2 for p in rows):
            raise Refused(f"video routes: domain {domain_id!r} ports.{key} must be a non-empty list of [node, input]")
    for key in DOTTED_PORTS:
        if not isinstance(ports[key], str) or len(ports[key].split(".")) != 2 or not all(ports[key].split(".")):
            raise Refused(f"video routes: domain {domain_id!r} ports.{key} must be 'NODE.input'")
    if not isinstance(ports["editorial_node"], str) or not ports["editorial_node"]:
        raise Refused(f"video routes: domain {domain_id!r} ports.editorial_node must name a node")


def domain_route(ctx: Context, routes: dict[str, Any]) -> dict[str, Any]:
    """Hàng routes của domain episode; domain không được phép ⇒ Refused trước mọi I/O ghi (A2)."""
    if ctx.domain_id not in routes["allowed_domains"]:
        raise Refused(f"VIDEO_DOMAIN_REFUSED: domain {ctx.domain_id!r} is not allowed for `jjv video` "
                      f"(allowed: {routes['allowed_domains']}); nothing was written")
    row = routes["domains"].get(ctx.domain_id)
    if not isinstance(row, dict):
        raise Refused(f"video routes: domain {ctx.domain_id!r} is allowed but has no row")
    _check_ports(ctx.domain_id, row.get("ports"))
    template = row.get("template")
    if not isinstance(template, dict) or not isinstance(template.get("path"), str) \
            or not isinstance(template.get("sha256"), str):
        raise Refused(f"video routes: domain {ctx.domain_id!r} template needs path + sha256")
    grid = row.get("frame_grid")
    if not isinstance(grid, dict) or not isinstance(grid.get("step"), int) or not isinstance(grid.get("offset"), int) \
            or grid["step"] < 1 or grid["offset"] < 0:
        raise Refused(f"video routes: domain {ctx.domain_id!r} frame_grid needs integer step >= 1 and offset >= 0")
    if not isinstance(row.get("seed_base"), int) or isinstance(row.get("seed_base"), bool):
        raise Refused(f"video routes: domain {ctx.domain_id!r} seed_base must be an integer")
    upscale = row.get("upscale")
    if not isinstance(upscale, dict) or not isinstance(upscale.get("backends"), list) \
            or upscale.get("default_backend") not in upscale["backends"] \
            or not isinstance(upscale.get("qualified"), dict) or not isinstance(upscale.get("target"), str):
        raise Refused(f"video routes: domain {ctx.domain_id!r} upscale needs backends, default_backend in backends, "
                      "qualified object and target")
    return row


def template_for(route: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Template API graph của domain: đường dẫn tuyệt đối + sha256 đã kiểm (đổi byte ⇒ Refused)."""
    declared = route["template"]
    given = Path(declared["path"])
    path = resolve_data_path(given if given.is_absolute() else repo_root / given)
    require_hash(path, declared["sha256"], "video template graph")
    return {"path": str(Path(path).resolve()), "sha256": declared["sha256"]}


def geometry_for(route: dict[str, Any]) -> dict[str, Any] | None:
    """Cỡ render H3 khai trong hàng routes (``geometry.width/height`` + ``width_port/height_port``).

    Không khai số ⇒ ``None`` (graph giữ nguyên cỡ của template).  Số khai phải là số nguyên dương và là bội của
    ``multiple_of`` (mặc định 32; VAE/H3 làm tròn cạnh theo bội này).  Cỡ sai ⇒ Refused, không đoán."""
    geometry = route.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("width") is None or geometry.get("height") is None:
        return None
    step = geometry.get("multiple_of", 32)
    values = {key: geometry[key] for key in ("width", "height")}
    if not isinstance(step, int) or isinstance(step, bool) or step < 1             or any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in values.values()):
        raise Refused("video routes: geometry width/height/multiple_of must be positive integers")
    bad = sorted(key for key, value in values.items() if value % step)
    if bad:
        raise Refused(f"video routes: geometry {bad} must be a multiple of {step} (got "
                      f"{values['width']}x{values['height']})")
    ports = {key: geometry.get(f"{key}_port") for key in ("width", "height")}
    if any(not isinstance(v, str) or len(v.split(".")) != 2 for v in ports.values()):
        raise Refused("video routes: geometry needs width_port and height_port as 'NODE.input'")
    return {**values, "ports": ports}


def frame_length(duration_s: float, fps: float, grid: dict[str, Any]) -> dict[str, Any]:
    """Số frame nhỏ nhất trên lưới ``step*k + offset`` không ngắn hơn ``round(duration_s * fps)``."""
    wanted = int(round(float(duration_s) * float(fps)))
    step, offset = int(grid["step"]), int(grid["offset"])
    k = max(0, math.ceil((wanted - offset) / step))
    frames = step * k + offset
    return {"frames": frames, "wanted_frames": wanted, "grid": f"{step}k+{offset}", "k": k,
            "seconds": round(frames / float(fps), 4), "source": grid.get("source")}


def port_pair(dotted: str) -> tuple[str, str]:
    node, key = dotted.split(".", 1)
    return node, key


__all__ = ["ROUTES", "ROUTES_SCHEMA", "load_routes", "domain_route", "template_for", "frame_length", "geometry_for", "port_pair"]
