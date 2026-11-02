"""``engine.video.ui_state``: JSON ``jjv/video-ui-state/v1`` cho panel ComfyUI — status chỉ đọc từ receipt THẬT.

Ba layout receipt thật được mô phỏng: engine (``<out>/<shot>/preparation.json`` + ``comfy/job.json`` + ``adopt.json``
+ ``acceptance/``), legacy ep04 (``technical/motion-vNNN/<shot>/{preparation,job}.json`` + ``engine/shots.json``),
pilot (``pilot-preparation.json`` / ``dispatch/submitted.json``), cộng state ``jjv video``.  Không GPU, không mạng.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from engine.core.errors import Refused  # noqa: E402
from engine.layout.context import load_context  # noqa: E402
from engine.video import state as state_mod  # noqa: E402
from engine.video import ui_state  # noqa: E402

EP = "t-ep"
CARTOON = "jenniejoy_cartoon_3d"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def blob(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class World:
    """Episode tối thiểu + machine.json trỏ tới ComfyUI giả (input/output dưới tmp)."""

    def __init__(self, tmp: Path, domain: str = CARTOON) -> None:
        self.tmp, self.domain = Path(tmp), domain
        self.root = self.tmp / "ep"
        dump(self.root / "engine" / "episode.json", {"episode_id": EP, "domain": domain, "files": {"shots": "shots.json"}})
        self.comfy = self.tmp / "comfy"
        self.input, self.output = self.comfy / "input", self.comfy / "output"
        self.input.mkdir(parents=True)
        self.output.mkdir(parents=True)
        self.machine = dump(self.tmp / "machine.json", {
            "comfy": {"url": "http://127.0.0.1:1", "root": str(self.comfy), "output_dir": str(self.output), "container": "x"},
            "gpu_lock_path": str(self.tmp / "gpu.lock")})

    def ctx(self):
        return load_context(str(self.root), self.machine)

    def draft(self, rows: list[dict], episode: str = EP) -> Path:
        return dump(self.tmp / "shotlist-draft.json", {"schema": "jjv/shotlist-draft/v1", "episode": episode, "fps": 24,
                                                       "rows": rows})

    def graph(self, path: Path, prompt: str, image: str = "anchor.png") -> Path:
        return dump(path, {
            "19": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": prompt}},
            "30": {"class_type": "LoadImage", "inputs": {"image": image}, "_meta": {"title": "Ảnh cảnh đã duyệt"}},
            "6": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["19", 0], "width": 864, "height": 480,
                                                                        "length": 124, "ref_images.ref_image_0": ["30", 0]}},
            "63": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "x", "video": ["6", 0]}}})

    def legacy_shot(self, version: str, shot: str, *, completed: bool, output_exists: bool = True,
                    where: str = "history") -> Path:
        """Layout ep04 thật: v002–v005 giữ output trong ``history.json`` (bản ghi /history), v006 thêm ``response.outputs``."""
        folder = self.root / "technical" / version / shot
        api = self.graph(self.root / "workflows" / version / f"{shot}.api.json", f"prompt of {shot}")
        dump(folder / "preparation.json", {"film_id": EP, "shot_id": shot, "status": "PREPARED_NOT_SUBMITTED",
                                           "version": version, "api": {"path": str(api), "sha256": sha(api)},
                                           "image": {"path": str(self.input / "anchor.png"), "sha256": "a" * 64},
                                           "sinks": {"native": "18", "editorial": "63", "carry": "55"}})
        if completed:
            sub = f"episodes/{EP}/shots/{shot}"
            if output_exists:
                blob(self.output / sub / f"{version}_editorial_00001_.mp4", f"video-{shot}".encode())
                blob(self.output / sub / f"{version}_frame119_00001_.png", b"png")
            outputs = {"18": {"images": [{"filename": f"{version}_native_00001_.mp4", "subfolder": sub, "type": "output"}]},
                       "63": {"images": [{"filename": f"{version}_editorial_00001_.mp4", "subfolder": sub, "type": "output",
                                          "metadata": {"kind": "video", "width": 864, "height": 480, "fps": 24.0,
                                                       "frame_count": 128}}]},
                       "55": {"images": [{"filename": f"{version}_frame119_00001_.png", "subfolder": sub, "type": "output"}]}}
            job = {"film_id": EP, "shot_id": shot, "status": "COMPLETED", "prompt_id": f"p-{shot}", "workflow_sha256": sha(api),
                   "outputs": {"editorial": {"path": "D:\\retired\\clips\\x.mp4", "sha256": "f" * 64}}}
            if where == "response":
                job["response"] = {"outputs": outputs}
            else:
                dump(folder / "history.json", {f"p-{shot}": {"outputs": outputs, "status": {"completed": True}}})
            dump(folder / "job.json", job)
        return folder


ROWS = [{"id": "SCENE_01", "kind": "non_dialogue", "scene": "SCENE_01", "speaker": None, "size": "Đặc tả", "angle": None,
         "move": None, "seconds": 3, "frames": 72, "refs": []},
        {"id": "S02_A", "kind": "dialogue", "scene": "SCENE_02", "speaker": "alice", "size": "Trung cảnh", "angle": "Góc thấp",
         "move": None, "seconds": 4, "frames": 96, "refs": ["alice"]},
        {"id": "S03_A", "kind": "dialogue", "scene": "SCENE_03", "speaker": "mother", "size": None, "angle": None,
         "move": None, "seconds": 4, "frames": 96, "refs": ["mother", "alice"]}]


def test_planned_only_from_shotlist_draft_and_atomic_write(tmp_path) -> None:
    world = World(tmp_path)
    document = ui_state.build(world.ctx(), shotlist=world.draft(ROWS))
    assert document["schema"] == ui_state.SCHEMA and document["episode"] == EP and document["domain"] == CARTOON
    assert document["fps"] == 24 and document["export"] == {"w": 3840, "h": 2160} and document["native"] is None
    assert [s["id"] for s in document["shots"]] == ["SCENE_01", "S02_A", "S03_A"]
    first = document["shots"][0]
    assert first["status"] == "planned" and first["size"] == "Đặc tả" and first["angle"] is None and first["move"] is None
    assert first["seconds"] == 3 and first["prompt"] is None and first["native_url"] is None and first["hd_url"] is None
    assert document["shots"][2]["cast"] == ["mother", "alice"] and document["shots"][2]["refs"] == []  # refs chỉ từ pack đã kiểm
    assert document["shots"][2]["legacy_refs"] == [] and any(p.startswith("ANCHOR_PACK_MISSING") for p in document["shots"][2]["problems"])
    assert document["counts"] == {"planned": 3, "prompted": 0, "rendered": 0, "upscaled_1080": 0, "accepted": 0, "unknown": 0}
    out = tmp_path / "data" / "video" / f"{EP}.json"
    digest = ui_state.write(document, out)
    assert out.is_file() and sha(out) == digest and json.loads(out.read_text("utf-8"))["episode"] == EP
    assert not [p for p in out.parent.iterdir() if p.suffix == ".tmp"]  # temp + os.replace, không để rác


def test_script_v1_shotlist_adds_intro_outro_and_character_refs(tmp_path) -> None:
    world = World(tmp_path)
    face = blob(tmp_path / "face.png", b"face")
    staged = blob(world.input / f"h3-{sha(face)}.png", b"face")  # ảnh ref đã stage vào ComfyUI/input ⇒ có URL
    script = dump(tmp_path / "script.json", {
        "schema": "jjv/script/v1", "film_id": EP, "domain": CARTOON, "fps": 24,
        "character_references": {"alice": {"character_id": "alice", "bible_name": "Alice", "canonical_path": str(face),
                                           "canonical_sha256": sha(face)},
                                 "mother": {"character_id": "mom", "bible_name": "Mom", "canonical_path": "missing.png",
                                            "canonical_sha256": "b" * 64}},
        "structure": {"intro": {"source_scene_id": "SCENE_01", "duration_s": 3.0},
                      "outro": {"source_scene_id": "SCENE_08", "duration_s": 2.0}},
        "shots": [{"id": "S02_A", "speaker": "alice", "listener": "mother", "duration_s": 4.0,
                   "source": {"scene_id": "SCENE_02"}, "continuity": {"camera_id": "CAM_LOW"}}]})
    shots = ui_state.build(world.ctx(), shotlist=script)["shots"]
    assert [s["id"] for s in shots] == ["SCENE_01", "S02_A", "SCENE_08"]
    assert shots[0]["seconds"] == 3.0 and shots[0]["scene"] == "SCENE_01" and shots[2]["seconds"] == 2.0
    assert shots[1]["scene"] == "SCENE_02" and shots[1]["size"] is None and shots[1]["camera_id"] == "CAM_LOW"
    assert shots[1]["cast"] == ["Alice", "Mom"] and shots[1]["refs"] == []  # ảnh stage h3-<sha> không phải tham chiếu đã duyệt
    assert shots[1]["legacy_refs"] == [{"name": "Alice", "url": f"/view?filename={staged.name}&type=input",
                                        "blocked": ui_state.LEGACY_BLOCK}]
    with pytest.raises(Refused, match="episode"):
        ui_state.build(world.ctx(), shotlist=world.draft(ROWS, episode="other-ep"))


def test_legacy_receipts_prompted_rendered_accepted_from_real_files(tmp_path) -> None:
    world = World(tmp_path)
    blob(world.input / "anchor.png", b"anchor")
    done = world.legacy_shot("motion-v004", "S02_A", completed=True)
    world.legacy_shot("motion-v004", "S03_A", completed=False)
    world.legacy_shot("motion-v005", "SCENE_01", completed=True, output_exists=False, where="response")
    clip = blob(world.root / "clips" / "S02_A-editorial.mp4", b"video-S02_A")
    dump(world.root / "engine" / "shots.json", {"schema": "jjv/shots/v1", "episode_id": EP, "shots": [
        {"shot": "S02_A", "receipt_dir": "technical/motion-v004/S02_A",
         "clip": {"path": "clips/S02_A-editorial.mp4", "sha256": sha(clip), "frames": 128}}]})
    document = ui_state.build(world.ctx(), shotlist=world.draft(ROWS), h3_dirs=[world.root / "technical" / "motion-v005",
                                                                                world.root / "technical" / "motion-v004"])
    by_id = {s["id"]: s for s in document["shots"]}
    assert by_id["S02_A"]["status"] == "accepted" and by_id["S02_A"]["status_source"].startswith("shots doc")
    assert by_id["S02_A"]["prompt"] == "prompt of S02_A"
    assert by_id["S02_A"]["native_url"] == ("/view?filename=motion-v004_editorial_00001_.mp4"
                                            f"&subfolder=episodes/{EP}/shots/S02_A&type=output")
    assert by_id["S02_A"]["thumb_url"].endswith("frame119_00001_.png&subfolder=episodes/t-ep/shots/S02_A&type=output")
    assert by_id["S02_A"]["refs"] == [] and by_id["S02_A"]["legacy_refs"][0] == {  # graph pilot: chỉ legacy, bị chặn
        "name": "Ảnh cảnh đã duyệt", "url": "/view?filename=anchor.png&type=input", "blocked": ui_state.LEGACY_BLOCK}
    assert by_id["S02_A"]["evidence"]["receipt_dir"].endswith("S02_A") and by_id["S02_A"]["evidence"]["job"]["prompt_id"] == "p-S02_A"
    assert by_id["S03_A"]["status"] == "prompted" and by_id["S03_A"]["native_url"] is None
    assert by_id["SCENE_01"]["status"] == "prompted" and any("missing" in p for p in by_id["SCENE_01"]["problems"])
    assert document["native"] == {"w": 864, "h": 480}
    assert document["counts"]["accepted"] == 1 and document["counts"]["prompted"] == 2
    assert done.name == "S02_A"


def test_engine_pilot_and_guarded_layouts(tmp_path) -> None:
    world = World(tmp_path)
    h3, pilot, guarded = tmp_path / "h3-r001", tmp_path / "pilot", tmp_path / "scene01-video"
    graph = world.graph(h3 / "S02_A" / "graph.api.json", "engine prompt")
    native = blob(world.output / "h3" / EP / "S02_A" / "o.mp4", b"native")
    dump(h3 / "S02_A" / "preparation.json", {"schema": "jjv/h3-preparation/v1", "episode_id": EP, "domain": CARTOON,
                                             "shot": "S02_A", "status": "PREPARED_NOT_SUBMITTED",
                                             "graph_sha256": sha(graph), "api": {"path": "graph.api.json"},
                                             "anchor": {"path": "a.png", "sha256": "a" * 64, "input_name": "h3-a.png"},
                                             "wav": {"path": "w.wav", "sha256": "c" * 64},
                                             "faces": [{"path": "f.png", "sha256": "d" * 64, "input_name": "h3-d.png"}],
                                             "editorial_node": "63", "sinks": {}})
    dump(h3 / "S02_A" / "comfy" / "job.json", {"status": "COMPLETED", "prompt_id": "p-5", "graph_sha256": sha(graph),
                                              "outputs": [{"node_id": "63", "filename": "o.mp4", "subfolder": f"h3/{EP}/S02_A",
                                                           "type": "output", "path": str(native), "exists": True,
                                                           "sha256": sha(native), "bytes": 6}]})
    dump(h3 / "S02_A" / "adopt.json", {"schema": "jjv/h3-adopt/v1", "episode_id": EP, "shot": "S02_A", "prompt_id": "p-5",
                                       "outputs": [{"role": "editorial", "node_id": "63", "path": str(native), "name": "o.mp4",
                                                    "sha256": sha(native)}]})
    dump(h3 / "S02_A" / "acceptance" / "001-pick.json", {"decision": "pick", "decided_by": "Kim",
                                                         "subject": {"sha256": sha(native)}})
    world.graph(pilot / "S03_A" / "graph.api.json", "pilot prompt")
    dump(pilot / "S03_A" / "pilot-preparation.json", {"schema": "jjv/h3-pilot-preparation/v0-draft", "episode_id": EP,
                                                      "shot": "S03_A", "status": "PREPARED_NOT_SUBMITTED"})
    world.graph(guarded / "workflow.api.json", "guarded prompt")
    dump(guarded / "dispatch" / "submitted.json", {"prompt_id": "p-g", "graph_sha256": "e" * 64})
    document = ui_state.build(world.ctx(), shotlist=world.draft(ROWS), h3_dirs=[h3, pilot], receipts={"SCENE_01": guarded})
    by_id = {s["id"]: s for s in document["shots"]}
    assert by_id["S02_A"]["status"] == "accepted" and "pick" in by_id["S02_A"]["status_source"]
    assert by_id["S02_A"]["native_url"] == f"/view?filename=o.mp4&subfolder=h3/{EP}/S02_A&type=output"
    assert by_id["S02_A"]["evidence"]["native"]["sha256"] == sha(native)
    assert by_id["S03_A"]["status"] == "prompted" and by_id["S03_A"]["prompt"] == "pilot prompt"
    assert by_id["SCENE_01"]["status"] == "prompted" and by_id["SCENE_01"]["evidence"]["job"] == {"status": "SUBMITTED",
                                                                                                   "prompt_id": "p-g"}
    assert document["counts"] == {"planned": 0, "prompted": 2, "rendered": 0, "upscaled_1080": 0, "accepted": 1, "unknown": 0}


def test_video_state_wins_and_a_broken_chain_never_invents_a_status(tmp_path) -> None:
    world = World(tmp_path)
    vout = tmp_path / "video-v001"
    dump(vout / "plan.json", {"schema": "jjv/video-plan/v1", "episode_id": EP, "domain": CARTOON,
                              "shots": [{"shot": "S02_A", "order": 1}]})
    native = blob(world.output / "h3" / EP / "S02_A" / "n.mp4", b"n")
    hd = blob(world.output / "up" / "S02_A-1080p.mp4", b"hd")
    render = dump(vout / "S02_A" / "render" / "r001" / "render-receipt.json",
                  {"schema": "jjv/video-render-receipt/v1", "native": {"path": str(native), "sha256": sha(native), "name": "n.mp4"}})
    upscale = dump(vout / "S02_A" / "upscale" / "r001" / "upscale-receipt.json",
                   {"schema": "jjv/video-upscale-receipt/v1", "output": {"path": str(hd), "sha256": sha(hd)}})
    prompt = blob(vout / "S02_A" / "prompt" / "r001" / "prompt.txt", b"frozen prompt\n")
    receipt = dump(vout / "S02_A" / "prompt" / "r001" / "prompt-receipt.json", {"prompt": {"path": "prompt.txt", "sha256": sha(prompt)}})
    state = {"schema": "jjv/video-shot-state/v1", "episode_id": EP, "domain": CARTOON, "shot": "S02_A", "order": 1,
             "state": "upscaled_1080", "revision": 1, "gate": None, "rejected": [], "history": [],
             "receipts": {"prompt": state_mod.ref(vout, receipt), "render": state_mod.ref(vout, render),
                          "upscale": state_mod.ref(vout, upscale)}}
    dump(vout / "S02_A" / "state.json", state)
    shot = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), video_out=vout)["shots"]}["S02_A"]
    assert shot["status"] == "upscaled_1080" and shot["status_source"] == "jjv video state.json"
    assert shot["prompt"] == "frozen prompt" and shot["native_url"].endswith("n.mp4&subfolder=h3/t-ep/S02_A&type=output")
    assert shot["hd_url"] == "/view?filename=S02_A-1080p.mp4&subfolder=up&type=output"
    render.write_text("{}", encoding="utf-8")  # receipt đổi byte sau khi state ghi ⇒ không tin, không bịa
    shot = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), video_out=vout)["shots"]}["S02_A"]
    assert shot["status"] is None and any("RECONCILE" in p for p in shot["problems"]) and shot["hd_url"] is None


def test_foreign_episode_receipts_are_ignored_not_mixed(tmp_path) -> None:
    world = World(tmp_path)
    folder = world.legacy_shot("motion-v004", "S02_A", completed=True)
    receipt = json.loads((folder / "preparation.json").read_text("utf-8"))
    dump(folder / "preparation.json", {**receipt, "film_id": "another-episode"})
    shot = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS),
                                               h3_dirs=[world.root / "technical" / "motion-v004"])["shots"]}["S02_A"]
    assert shot["status"] == "planned" and any("another-episode" in p for p in shot["problems"])


def test_index_upsert_keeps_episodes_apart(tmp_path) -> None:
    index = tmp_path / "data" / "video" / "index.json"
    first = ui_state.upsert_index(index, episode="ep-b", domain="d1", file="ep-b.json")
    second = ui_state.upsert_index(index, episode="ep-a", domain="d2", file="ep-a.json")
    third = ui_state.upsert_index(index, episode="ep-b", domain="d1", file="ep-b.json")
    assert first["episodes"] == [{"episode": "ep-b", "domain": "d1", "file": "ep-b.json"}]
    assert [e["episode"] for e in second["episodes"]] == ["ep-a", "ep-b"] and len(third["episodes"]) == 2
    assert json.loads(index.read_text("utf-8"))["schema"] == ui_state.INDEX_SCHEMA


def test_cli_writes_file_and_index(tmp_path, capsys) -> None:
    world = World(tmp_path)
    out, index = tmp_path / "data" / "video" / f"{EP}.json", tmp_path / "data" / "video" / "index.json"
    code = ui_state.main(["--episode", str(world.root), "--machine", str(world.machine), "--shotlist", str(world.draft(ROWS)),
                          "--out", str(out), "--index", str(index)])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["counts"]["planned"] == 3 and printed["out"] == str(out)
    assert out.is_file() and json.loads(index.read_text("utf-8"))["episodes"][0]["episode"] == EP
