"""Editable GUI workflow and the review GUI that pins the produced image (derived from the saved API graph).

Reuses the audio lane's ``api_to_gui`` (the GUI follows the published workflow shape, version 0.4). Best effort:
a missing ComfyUI is recorded as an error in the receipt, never a failure of the run (the API graph + receipt
are the evidence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..audio.gui import api_to_gui
from ..comfy.gui_inputs import flat_input_name, stage_graph_inputs
from ..comfy.staging import stage_input
from ..core.io import write_json_once

ObjectInfo = Callable[[str], dict]


def attach_image_result(gui: dict, *, input_name: str, status: str, prompt_id: str, image_sha256: str) -> dict:
    """A copy of ``gui`` plus a ``LoadImage`` node pinning the produced file ("KET QUA" review graph)."""
    out = json.loads(json.dumps(gui))
    node_id = out["last_node_id"] + 1
    right = max((float(n["pos"][0]) for n in out["nodes"]), default=0.0)
    title = f"KET QUA {status.upper()} | job {str(prompt_id)[:8]} | SHA {image_sha256[:12]}"
    out["nodes"].append({
        "id": node_id, "type": "LoadImage", "pos": [right + 520, 40], "size": [430, 320], "flags": {},
        "order": len(out["nodes"]), "mode": 0,
        "inputs": [{"localized_name": "image", "name": "image", "type": "COMBO", "widget": {"name": "image"}, "link": None},
                   {"localized_name": "upload", "name": "upload", "type": "IMAGEUPLOAD", "widget": {"name": "upload"}, "link": None}],
        "outputs": [{"localized_name": "IMAGE", "name": "IMAGE", "type": "IMAGE", "links": []},
                    {"localized_name": "MASK", "name": "MASK", "type": "MASK", "links": []}],
        "title": title, "properties": {"Node name for S&R": "LoadImage"}, "widgets_values": [input_name, "image"],
        "widgets_values_named": {"image": input_name, "upload": "image"}, "color": "#114f5a", "bgcolor": "#09292f"})
    out["last_node_id"] = node_id
    out["extra"].update(review_only=True, result_sha256=image_sha256, prompt_id=prompt_id, status=status)
    return out


def write_guis(folder: Path, api_graph: dict, object_info: ObjectInfo | None, input_dir: Path | None, *, title: str,
               graph_sha256: str, produced: dict[str, Any] | None, domain: str, shot: str,
               expected_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    """``graph.gui.json`` always (when ComfyUI answered), ``graph.review.gui.json`` once a result exists."""
    if object_info is None:
        return {"skipped": "no ComfyUI object_info available"}
    rows: dict[str, Any] = {}
    try:
        staged = stage_graph_inputs(api_graph, input_dir, domain=domain, shot=shot, expected_hashes=expected_hashes)
        editable = api_to_gui(staged, object_info, title=title, extra={"graph_sha256": graph_sha256})
        rows["gui"] = "graph.gui.json"
        rows["gui_sha256"] = write_json_once(Path(folder) / "graph.gui.json", editable, mode="ascii")
        if produced and input_dir is not None:
            name = flat_input_name(domain, shot, produced["sha256"], Path(produced["path"]).name)
            stage_input(Path(produced["path"]), Path(input_dir), name, produced["sha256"])
            review = attach_image_result(editable, input_name=name, status="completed",
                                         prompt_id=produced["prompt_id"], image_sha256=produced["sha256"])
            rows["review_gui"] = "graph.review.gui.json"
            rows["review_gui_sha256"] = write_json_once(Path(folder) / "graph.review.gui.json", review, mode="ascii")
            rows["pinned_input"] = name
    except Exception as error:  # noqa: BLE001 - see module docstring
        rows["error"] = repr(error)
    return rows
