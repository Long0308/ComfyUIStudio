"""``engine.video.ui_refresh`` (làm mới panel tự động, opt-in theo episode) + ``ui_pipeline`` (10 bước mỗi shot)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from test_ui_state import CARTOON, EP, World, dump, sha  # noqa: E402

from engine.video import ui_refresh  # noqa: E402

ASSET = "pending-assets"


def _script(tmp: Path, status: str = "approved") -> Path:
    return dump(tmp / "script.json", {
        "schema": "jjv/script/v1", "film_id": EP, "domain": CARTOON, "fps": 24, "status": status,
        "character_references": {},
        "shots": [{"id": "S02_A", "speaker": "alice", "duration_s": 4.0, "speech_text": "Tien do dang gap",
                   "source": {"scene_id": "SCENE_02"}}]})


def _target(world: World, script: Path, out: Path, **extra) -> Path:
    return dump(world.root / "engine" / ui_refresh.TARGET_FILE, {
        "schema": ui_refresh.TARGET_SCHEMA, "enabled": True, "episode_id": EP, "out": str(out), "shotlist": str(script), **extra})


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_episode_without_a_target_is_untouched(tmp_path) -> None:
    world = World(tmp_path)
    before = _files(tmp_path)
    assert ui_refresh.refresh(world.ctx()) == {"refreshed": False, "reason": "no enabled ui-state target for this episode"}
    assert ui_refresh.refresh_after("video", "run", str(world.root), str(world.machine)) == {
        "refreshed": False, "reason": "no enabled ui-state target for this episode"}
    assert _files(tmp_path) == before


def test_refresh_writes_atomically_and_failure_keeps_the_old_bytes(tmp_path) -> None:
    world = World(tmp_path)
    out = tmp_path / "data" / "video" / f"{EP}.json"
    _target(world, _script(tmp_path), out)
    result = ui_refresh.refresh(world.ctx())
    assert result["refreshed"] is True and sha(out) == result["sha256"]
    assert not [p for p in out.parent.iterdir() if p.suffix == ".tmp"]
    old = out.read_bytes()
    (tmp_path / "script.json").write_text("{not json", encoding="utf-8")  # nguồn hỏng giữa chừng
    failed = ui_refresh.refresh_after("h3", "submit", str(world.root), str(world.machine))
    assert failed["refreshed"] is False and "error" in failed
    assert out.read_bytes() == old and not [p for p in out.parent.iterdir() if p.suffix == ".tmp"]


@pytest.mark.parametrize("stage,verb,dry", [("images", "approve", False), ("video", "ui-state", False), ("video", "run", True)])
def test_refresh_only_after_receipt_writing_stage_verbs(tmp_path, stage, verb, dry) -> None:
    world = World(tmp_path)
    out = tmp_path / "ui.json"
    _target(world, _script(tmp_path), out)
    assert ui_refresh.refresh_after(stage, verb, str(world.root), str(world.machine), dry) is None
    assert not out.exists()


def test_target_of_another_episode_is_refused_not_applied(tmp_path) -> None:
    world = World(tmp_path)
    dump(world.root / "engine" / ui_refresh.TARGET_FILE, {"schema": ui_refresh.TARGET_SCHEMA, "enabled": True,
                                                          "episode_id": "other", "out": "x", "shotlist": "y"})
    result = ui_refresh.refresh_after("video", "run", str(world.root), str(world.machine))
    assert result["refreshed"] is False and "other" in result["error"]


def test_pipeline_has_ten_stages_and_review_boxes_carry_both_commands(tmp_path) -> None:
    world = World(tmp_path)
    wav = tmp_path / "line.wav"
    wav.write_bytes(b"RIFFxxxx")
    dialogue = dump(tmp_path / "dialogue.json", {"dialogue": [{"id": "S02_A_L1", "speaker": "alice", "start_frame": 0,
                                                              "end_frame_exclusive": 95, "speech_text": "Tien do dang gap",
                                                              "audio": {"path": str(wav), "sha256": sha(wav), "duration_seconds": 3.96}}]})
    out = tmp_path / "ui.json"
    _target(world, _script(tmp_path), out, video_out=str(tmp_path / "vout"), pipeline={
        "voice_out": str(tmp_path / "voice"), "images_out": str(tmp_path / "images"),
        "evidence": [{"stage": "voice", "shot": "S02_A", "kind": "dialogue-doc", "path": str(dialogue)}]})
    # video_out phải là plan thật; không có plan ⇒ để target không khai video_out cho test này
    target = json.loads((world.root / "engine" / ui_refresh.TARGET_FILE).read_text("utf-8"))
    target.pop("video_out")
    dump(world.root / "engine" / ui_refresh.TARGET_FILE, target)
    assert ui_refresh.refresh(world.ctx())["refreshed"] is True
    shot = json.loads(out.read_text("utf-8"))["shots"][0]
    stages = shot["pipeline"]["stages"]
    assert [s["code"] for s in stages] == [f"{i:02d}" for i in range(1, 11)]
    by = {s["key"]: s for s in stages}
    voice = by["voice"]  # tạo ra nhưng chưa duyệt ⇒ ô CHỜ DUYỆT: có lệnh duyệt + lệnh chạy tiếp, đều do engine dựng
    assert voice["status"] == "pending-review" and voice["out"][0]["sha256"] == sha(wav)
    assert "voice approve" in voice["approval"]["text"] and "dialogue:S02_A_L1" in voice["approval"]["text"]
    assert sha(wav) in voice["approval"]["text"] and "<tên-người-duyệt>" in voice["approval"]["placeholders"]
    assert voice["next"]["text"].split("jjv.py ")[1].startswith("h3 inputs") and voice["next"]["gpu"] is False
    shotlist = by["shotlist"]  # đã duyệt ⇒ không có ô chờ duyệt
    assert shotlist["status"] == "approved" and shotlist["approval"] is None and shotlist["next"] is None
    assert by["h3"]["status"] == "missing" and by["h3"]["approval"] is None and by["h3"]["next"]["gpu"] is True
    # CARTOON nay có route qualified seedvr2-7b (stage C, NOTES: "Qualification status: `PASS`") ⇒ cổng mở, bước 06 chờ chạy
    assert by["upscale"]["status"] == "missing" and by["upscale"].get("reason") is None
    assert by["captions"]["status"] == "missing" and by["captions"]["next"]["text"].find("captions build") > 0
    assert by["audio"]["detail"]["sfx_enabled"] is None


def test_without_pipeline_config_no_pipeline_key_is_written(tmp_path) -> None:
    world = World(tmp_path)
    out = tmp_path / "ui.json"
    _target(world, _script(tmp_path), out)
    ui_refresh.refresh(world.ctx())
    assert all("pipeline" not in s for s in json.loads(out.read_text("utf-8"))["shots"])


def test_upscale_chunk_receipt_may_be_a_dict_with_chunks(tmp_path) -> None:
    """Receipt SeedVR2 theo shot là dict {status, chunks:[...]}; list trần (cũ) vẫn đọc được."""
    world = World(tmp_path)
    as_dict = dump(tmp_path / "r1.json", {"status": "DONE", "chunks": [{"chunk": 0, "out_sha256": "aa", "out_frames": 17}]})
    as_list = dump(tmp_path / "r2.json", [{"chunk": 1, "out_sha256": "bb", "out_frames": 17}])
    out = tmp_path / "ui.json"
    _target(world, _script(tmp_path), out, pipeline={"evidence": [
        {"stage": "upscale", "shot": "S02_A", "kind": "chunk-receipts", "path": str(as_dict)},
        {"stage": "upscale", "shot": "S02_A", "kind": "chunk-receipts", "path": str(as_list)}]})
    assert ui_refresh.refresh(world.ctx())["refreshed"] is True
    by = {st["key"]: st for st in json.loads(out.read_text("utf-8"))["shots"][0]["pipeline"]["stages"]}
    assert [c["chunk"] for c in by["upscale"]["detail"]["pilot_chunks"]] == [0, 1]
