"""Editable GUI graph (+ review GUI pinning the result) derived from an API graph and ``GET /object_info``.

Port of the first episode's audio lane (``comfy_audio_graphs.api_to_gui`` / ``attach_audio_result``): the GUI
workflow follows the shape of the published H3 workflows (version 0.4, links ``[id, from, slot, to, slot,
type]``).  ``object_info`` is injected (GET only, tests pass a fake); the review GUI adds a ``LoadAudio``
node that pins the produced file by sha256 (the audio file must already be in the ComfyUI input folder).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

WIDGET_PRIMS = {"STRING", "INT", "FLOAT", "BOOLEAN"}
EXTRA_WIDGETS = {
    "LoadAudio": [("audioUI", "AUDIO_UI", None), ("upload", "AUDIOUPLOAD", "")],
    "SaveAudio": [("audioUI", "AUDIO_UI", None)],
    "PreviewAudio": [("audioUI", "AUDIO_UI", None)],
}
BIG_NODES = ("KSampler", "YuE2GenerateMusic", "YuE2GenerateABC", "CLIPTextEncode")
ObjectInfo = Callable[[str], dict]


def _specs(info: dict) -> list[tuple[str, Any]]:
    order, inputs = info.get("input_order") or {}, info.get("input") or {}
    rows = []
    for section in ("required", "optional"):
        for name in order.get(section) or list((inputs.get(section) or {}).keys()):
            rows.append((name, inputs[section][name]))
    return rows


def _is_widget(spec: Any) -> bool:
    kind = spec[0]
    return isinstance(kind, list) or kind in WIDGET_PRIMS or kind == "COMBO"


def _wtype(spec: Any) -> str:
    return "COMBO" if isinstance(spec[0], list) else str(spec[0])


def _is_link(value: Any, api: dict) -> bool:
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in api


def api_to_gui(api: dict, object_info: ObjectInfo, *, title: str, extra: dict | None = None, columns: int = 4, node_infos: dict | None = None) -> dict:
    infos = node_infos if node_infos is not None else {nid: object_info(node["class_type"]) for nid, node in api.items()}
    ordered = sorted(api, key=int)
    links: list[list] = []
    out_links: dict[tuple[str, int], list[int]] = {}
    inputs_by_node: dict[str, list] = {}
    for nid in ordered:
        node, entries = api[nid], []
        for name, spec in _specs(infos[nid]):
            value = node["inputs"].get(name)
            link = _is_link(value, api)
            entry: dict[str, Any] = {"localized_name": name, "name": name, "link": None,
                                     "type": _wtype(spec) if _is_widget(spec) else str(spec[0])}
            if _is_widget(spec):
                entry["widget"] = {"name": name}
            if link:
                src, src_slot = value[0], int(value[1])
                # target slot = index of this entry in node.inputs (widget entries count), not a socket counter
                links.append([len(links) + 1, int(src), src_slot, int(nid), len(entries),
                              (infos[src].get("output") or [])[src_slot]])
                out_links.setdefault((src, src_slot), []).append(len(links))
                entry["link"] = len(links)
            entries.append(entry)
        for name, wtype, _ in EXTRA_WIDGETS.get(node["class_type"], []):
            entries.append({"localized_name": name, "name": name, "type": wtype, "widget": {"name": name}, "link": None})
        inputs_by_node[nid] = entries
    nodes = []
    for index, nid in enumerate(ordered):
        node, info, widgets, named = api[nid], infos[nid], [], {}
        for name, spec in _specs(info):
            if not _is_widget(spec):
                continue
            value = node["inputs"].get(name)
            if _is_link(value, api):
                value = spec[1].get("default") if len(spec) > 1 and isinstance(spec[1], dict) else None
            widgets.append(value)
            named[name] = value
            if len(spec) > 1 and isinstance(spec[1], dict) and spec[1].get("control_after_generate"):
                widgets.append("fixed")
        for name, _, default in EXTRA_WIDGETS.get(node["class_type"], []):
            if default is not None:
                widgets.append(default)
                named[name] = default
        outputs = [{"localized_name": oname, "name": oname, "type": otype, "links": out_links.get((nid, slot), [])}
                   for slot, (otype, oname) in enumerate(zip(info.get("output") or [], info.get("output_name") or []))]
        nodes.append({"id": int(nid), "type": node["class_type"], "pos": [40 + index % columns * 470, 40 + index // columns * 330],
                      "size": [430, 260 if node["class_type"] in BIG_NODES else 150], "flags": {}, "order": index,
                      "mode": 0, "inputs": inputs_by_node[nid], "outputs": outputs,
                      "title": node.get("_meta", {}).get("title", node["class_type"]),
                      "properties": {"Node name for S&R": node["class_type"]}, "widgets_values": widgets,
                      "widgets_values_named": named})
    digest = hashlib.sha256(json.dumps(api, sort_keys=True).encode()).hexdigest()
    return {"id": hashlib.sha256(title.encode()).hexdigest()[:8] + "-0000-4000-8000-" + digest[:12], "revision": 0,
            "last_node_id": max(int(k) for k in api), "last_link_id": len(links), "nodes": nodes, "links": links,
            "groups": [], "config": {}, "extra": {"title": title, **(extra or {})}, "version": 0.4}


def attach_audio_result(gui: dict, *, input_name: str, status: str, prompt_id: str, audio_sha256: str,
                        lufs: str | None = None) -> dict:
    """A copy of ``gui`` plus a ``LoadAudio`` node that pins the produced file ("KET QUA" review graph)."""
    out = json.loads(json.dumps(gui))
    node_id = out["last_node_id"] + 1
    right = max(float(n["pos"][0]) for n in out["nodes"])
    title = f"KET QUA {status.upper()} | job {str(prompt_id)[:8]} | SHA {audio_sha256[:12]}" + (f" | {lufs}" if lufs else "")
    out["nodes"].append({
        "id": node_id, "type": "LoadAudio", "pos": [right + 520, 40], "size": [430, 180], "flags": {},
        "order": len(out["nodes"]), "mode": 0,
        "inputs": [{"localized_name": "audio", "name": "audio", "type": "COMBO", "widget": {"name": "audio"}, "link": None},
                   {"localized_name": "audioUI", "name": "audioUI", "type": "AUDIO_UI", "widget": {"name": "audioUI"}, "link": None},
                   {"localized_name": "upload", "name": "upload", "type": "AUDIOUPLOAD", "widget": {"name": "upload"}, "link": None}],
        "outputs": [{"localized_name": "AUDIO", "name": "AUDIO", "type": "AUDIO", "links": []}],
        "title": title, "properties": {"Node name for S&R": "LoadAudio"}, "widgets_values": [input_name, ""],
        "widgets_values_named": {"audio": input_name, "upload": ""}, "color": "#114f5a", "bgcolor": "#09292f"})
    out["last_node_id"] = node_id
    out["extra"].update(review_only=True, result_sha256=audio_sha256, prompt_id=prompt_id, status=status)
    return out
