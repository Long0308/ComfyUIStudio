"""Provider candidates publish editable ComfyUI review workflows and manifest entries."""

from __future__ import annotations

import json
from pathlib import Path

from images_fixtures import World, make_png, run_images, sha

ITEMS = ["identity", "headcount", "enclosure", "listener_mouth_closed", "no_text", "costume_print_side"]


class Flow:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.world = World(tmp)
        self.layout, self.out = tmp / "layout", tmp / "images"
        self.layout.mkdir(parents=True)
        (self.layout / "layout-plan.json").write_text(json.dumps({
            "schema": "jjv/layout-plan/v1",
            "episode_id": self.world.ctx().episode_id,
            "domain": self.world.domain,
            "shots": [{"shot": "S01_A", "kind": "cut", "layout_of": "S01_A",
                       "brief": "briefs/S01_A.brief.json", "cast": []}],
        }), encoding="utf-8")
        self.world.images_plan(self.out, self.layout, shots=("S01_A",))
        self.prompt = tmp / "brief.txt"
        self.prompt.write_text(
            "Warm garden frame.\nAuthorization: Bearer sk-or-SECRET-VALUE\naccess_token=DO-NOT-COPY\n",
            encoding="utf-8",
        )
        self.base = ["--episode", str(self.world.root), "--out", str(self.out), "--machine", str(self.world.machine_path)]

    def run(self, verb: str, *argv: str):
        return run_images([verb, *self.base, *argv])

    def adopt(self, name: str, color: tuple[int, int, int]):
        png = make_png(self.tmp / name, color, (1672, 941))
        code, summary = self.run(
            "adopt", "--shot", "S01_A", "--file", str(png), "--route", "codex-builtin",
            "--prompt-file", str(self.prompt), "--refs-from-plan",
            "--source-path", "C:/generated_images/01a17e00-3746-7862-a27d-b01bfd71673b/exec-1.png",
        )
        assert code == 0
        return summary, png

    def approve_and_native(self, candidate_sha: str):
        assert self.run("compare", "--shot", "S01_A")[0] == 0
        checklist_path = self.out / "S01_A" / "compare" / "checklist.json"
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        for item in ITEMS:
            checklist["candidates"][candidate_sha][item] = {"status": "pass", "note": "reviewed"}
        checklist_path.write_text(json.dumps(checklist), encoding="utf-8")
        assert self.run("approve", "--shot", "S01_A", "--sha", candidate_sha[:12],
                        "--reviewer", "root", "--scope", "still")[0] == 0
        return self.run("native", "--shot", "S01_A", "--sha", candidate_sha[:12])


def read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_adopt_writes_a_pinned_workflow_manifest_copy_and_no_credentials(tmp_path):
    flow = Flow(tmp_path)
    summary, _ = flow.adopt("first.png", (12, 90, 40))
    publication = summary["workflow"]
    workflow_path = Path(publication["workflow"])
    graph = read(str(workflow_path))

    assert workflow_path.parent == flow.world.root / "03_STORYBOARD_IMAGES"
    assert workflow_path.name == "S01_A-codex-builtin-review-v001.workflow.json"
    assert {node["type"] for node in graph["nodes"]} == {"LoadImage", "Note"}
    image_node = next(node for node in graph["nodes"] if node["type"] == "LoadImage")
    note_node = next(node for node in graph["nodes"] if node["type"] == "Note")
    input_name = image_node["widgets_values"][0]
    assert Path(input_name).name == input_name and input_name.startswith(flow.world.ctx().domain_id + "__")
    assert (flow.world.comfy_root / "input" / input_name).is_file()
    assert sha(flow.world.comfy_root / "input" / input_name) == summary["sha256"]
    note = note_node["widgets_values"][0]
    assert "Warm garden frame." in note and "reference_hashes:" in note and summary["sha256"] in note
    assert "account_label: not exposed" in note
    assert "codex_session_id: 01a17e00-3746-7862-a27d-b01bfd71673b" in note

    manifest = read(publication["manifest"])
    assert manifest["entry_count"] == 1
    entry = manifest["entries"][0]
    assert entry["path"] == "03_STORYBOARD_IMAGES/S01_A-codex-builtin-review-v001.workflow.json"
    assert entry["kind"] == "review" and entry["status"] == "candidate"
    assert entry["result_sha256"] == summary["sha256"] and entry["comfyui_input"] == input_name
    assert entry["result_pins"][0]["input_exists"] is True

    outputs = [workflow_path, Path(publication["manifest"]), flow.world.comfy_root / "input" / input_name]
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in outputs if path.suffix != ".png")
    for marker in ("sk-", "Bearer", "access_token"):
        assert marker not in text


def test_a_second_adopt_allocates_a_new_version_and_manifest_row(tmp_path):
    flow = Flow(tmp_path)
    first, _ = flow.adopt("first.png", (12, 90, 40))
    second, _ = flow.adopt("second.png", (90, 20, 40))

    first_path = Path(first["workflow"]["workflow"])
    second_path = Path(second["workflow"]["workflow"])
    assert first_path.name.endswith("-v001.workflow.json")
    assert second_path.name.endswith("-v002.workflow.json")
    assert first_path.read_bytes() != second_path.read_bytes()
    manifest = read(second["workflow"]["manifest"])
    assert manifest["entry_count"] == 2
    assert {entry["result_sha256"] for entry in manifest["entries"]} == {first["sha256"], second["sha256"]}


def test_native_anchor_publishes_its_own_workflow_with_source_provenance(tmp_path):
    flow = Flow(tmp_path)
    adopted, _ = flow.adopt("source.png", (45, 70, 95))
    code, native = flow.approve_and_native(adopted["sha256"])
    assert code == 0 and native["anchor_approved"] is True

    publication = native["workflow"]
    graph = read(publication["workflow"])
    note = next(node for node in graph["nodes"] if node["type"] == "Note")["widgets_values"][0]
    assert Path(publication["workflow"]).name == "S01_A-codex-builtin-native-review-v001.workflow.json"
    assert f"native_source_sha256: {adopted['sha256']}" in note
    assert f"native_sha256: {native['native']['sha256']}" in note
    assert f"output_sha256: {native['native']['sha256']}" in note
    entry = next(row for row in read(publication["manifest"])["entries"] if row["path"].endswith("native-review-v001.workflow.json"))
    assert entry["result_sha256"] == native["native"]["sha256"]
