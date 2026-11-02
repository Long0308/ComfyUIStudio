"""Payload ``--dry-run``: đúng các ô input ComfyUI mà bước ``03 AI QUAY VIDEO`` sẽ gửi cho một shot.

Không gửi gì.  Anchor và WAV chỉ được điền khi ``<out>/h3-inputs.json`` (do ``jjv h3 inputs`` dựng từ
receipt) đã có hàng của shot; nếu chưa, chúng được in là ``pending`` kèm lý do, không bịa.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..core.io import canonical_sha256, sha256_file
from ..h3.prepare import set_port
from . import routes as routes_mod


def _media_name(path: str, sha: str) -> str:
    return f"h3-{sha}{Path(path).suffix.lower()}"


def _widget(graph: dict[str, Any], dotted: str | None) -> Any:
    if not dotted:
        return None
    node, key = routes_mod.port_pair(dotted)
    return ((graph.get(node) or {}).get("inputs") or {}).get(key)


def _manifest_media(row: dict[str, Any] | None, key: str, pending_reason: str) -> dict[str, Any]:
    item = (row or {}).get(key)
    if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
        return {"status": "pending", "reason": pending_reason}
    path = Path(item["path"])
    on_disk = path.is_file() and sha256_file(path) == item["sha256"]
    return {"status": "bound" if on_disk else "hash-mismatch", "path": str(path), "sha256": item["sha256"],
            "file": _media_name(item["path"], item["sha256"]), "ports": item.get("ports")}


def shot_payload(route: dict[str, Any], template_graph: dict[str, Any], receipt: dict[str, Any], prompt_text: str,
                 prompt_sha256: str, state: dict[str, Any], manifest_row: dict[str, Any] | None,
                 stages: list[str]) -> dict[str, Any]:
    ports = route["ports"]
    graph = copy.deepcopy(template_graph)
    set_port(graph, routes_mod.port_pair(ports["prompt"]), prompt_text)
    set_port(graph, routes_mod.port_pair(ports["length"]), receipt["length"]["frames"])
    set_port(graph, routes_mod.port_pair(ports["seed"]), receipt["seed"])
    frozen = receipt.get("geometry")
    if frozen:  # cỡ đã đóng băng trong plan receipt (đọc từ routes lúc plan), không hardcode ở đây
        for axis in ("width", "height"):
            set_port(graph, routes_mod.port_pair(frozen["ports"][axis]), frozen[axis])
    inputs: dict[str, Any] = {ports["prompt"]: f"<prompt sha256 {prompt_sha256}>",
                              ports["length"]: receipt["length"]["frames"], ports["seed"]: receipt["seed"]}
    refs = []
    for item in receipt["refs"]:
        if item.get("bound"):
            name = _media_name(item["path"], item["sha256"])
            set_port(graph, item["ports"], name)
            inputs[f"{item['ports'][0]}.{item['ports'][1]}"] = name
        refs.append({k: item.get(k) for k in ("picture", "role", "character_id", "path", "sha256", "bound", "ports")})
    anchor = _manifest_media(manifest_row, "anchor", "NO_H3_INPUTS: approved native anchor is bound by `jjv h3 inputs`")
    wav = _manifest_media(manifest_row, "wav", "NO_H3_INPUTS: the listen-approved WAV (preparation.json -> wav.sha256) "
                                               "is bound by `jjv h3 inputs` / `jjv h3 prepare`")
    for media, key in ((anchor, "anchor"), (wav, "wav")):
        if media["status"] == "bound":
            for port in media.get("ports") or ports[key]:
                set_port(graph, port, media["file"])
                inputs[f"{port[0]}.{port[1]}"] = media["file"]
        else:
            for port in ports[key]:
                inputs[f"{port[0]}.{port[1]}"] = f"<pending: {key}>"
    geometry = {**(route.get("geometry") or {}), **({"width_port": frozen["ports"]["width"],
                                                       "height_port": frozen["ports"]["height"]} if frozen else {})}
    if frozen:
        inputs.update({frozen["ports"][axis]: frozen[axis] for axis in ("width", "height")})
    out_node, out_key = ports["output_ports"][0]
    return {"shot": receipt["shot"], "order": receipt["order"], "revision": state["revision"], "state": state["state"],
            "tier": receipt["tier"], "resolution": receipt["resolution"],
            "stage": stages[2], "submit": False, "route": route.get("h3_route"),
            "template": receipt["template"],
            "prompt": {"port": ports["prompt"], "sha256": prompt_sha256, "chars": len(prompt_text), "text": prompt_text},
            "refs": refs, "anchor": anchor, "wav": wav,
            "seed": {"port": ports["seed"], "value": receipt["seed"]},
            "length": {"port": ports["length"], **receipt["length"]},
            "duration_s": receipt["duration_s"], "fps": receipt["fps"],
            "geometry": {"width": _widget(graph, geometry.get("width_port")),
                         "height": _widget(graph, geometry.get("height_port")),
                         "fps": _widget(graph, geometry.get("fps_port")) if geometry.get("fps_port") else receipt["fps"]},
            "output_prefix_template": ((graph.get(out_node) or {}).get("inputs") or {}).get(out_key),
            "graph_inputs": inputs,
            "graph_preview_sha256": canonical_sha256(graph, mode="ascii"),
            "note": "preview only: the prepared graph (anchor/WAV bound, output prefix per shot) and its sha256 are "
                    "written by `jjv h3 prepare` into preparation.json; nothing was sent"}


__all__ = ["shot_payload"]
