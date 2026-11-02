"""Verify API links/types and canvas endpoint mapping without importing ComfyUI/CUDA."""
import ast
import json
from pathlib import Path

pack = Path(__file__).resolve().parents[1]
for source in pack.rglob("*.py"):
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
api = json.loads((pack / "examples/S02_A-panel.api.json").read_text(encoding="utf-8"))
gui = json.loads((pack / "examples/S02_A-panel.workflow.json").read_text(encoding="utf-8"))
nodes = {str(node["id"]): node for node in gui["nodes"]}
count = 0
for link_id, source, slot, target, input_slot, kind in gui["links"]:
    origin, destination = nodes[str(source)], nodes[str(target)]
    assert origin["outputs"][slot]["type"] == kind
    assert destination["inputs"][input_slot]["type"] == kind
    assert destination["inputs"][input_slot]["link"] == link_id
    assert link_id in origin["outputs"][slot]["links"]
    name = destination["inputs"][input_slot]["name"]
    assert api[str(target)]["inputs"][name] == [str(source), slot]
    count += 1
assert api["6"]["inputs"]["width"] == ["100", 3]
assert api["6"]["inputs"]["length"] == ["100", 6]
assert api["18"]["inputs"]["receipt_json"] == ["100", 7]
assert api["8"]["inputs"]["ref_image_paths_json"] == ["100", 10]
assert not any("Claude" in node["class_type"] for node in api.values())
print(f"PASS: Python AST, {len(nodes)} example nodes, {count} typed API/canvas links; no GPU/import/queue.")
