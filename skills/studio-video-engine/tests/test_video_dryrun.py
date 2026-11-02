"""VENG-1: ``jjv video run --dry-run`` trên episode NEWTECONS thật (chỉ đọc production-local; --out ở tmp):
đúng 6 shot của script-v003 với prompt/refs/seed/length/WAV, không gửi gì, không ghi gì ngoài plan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from video_fixtures import LIVE, VideoWorld, run_video

from engine.layout.context import REPO_ROOT

EPISODE = REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "Newtecons-TienDo-KichTinh-30s" / "engine" / "episode.json"
SCRIPT = REPO_ROOT / "production-local" / "engine" / "staging" / "newtecons-30s" / "script-v003.json"
SCRIPT_SHA = "2059dce6b083048af87d534b2e83d6374deba73df8427e88bbe53d3f2db18cd0"
GRID = 17


def _machine(tmp_path: Path) -> Path:
    """machine.json tạm: khoá GPU ở tmp (không bao giờ là khoá thật), ComfyUI không có thật (dry-run không gọi)."""
    comfy = tmp_path / "comfy"
    (comfy / "input").mkdir(parents=True)
    path = tmp_path / "machine.json"
    path.write_text(json.dumps({"comfy": {"url": "http://127.0.0.1:1", "root": str(comfy), "container": "none"},
                                "gpu_lock_path": str(tmp_path / "gpu.lock")}), encoding="utf-8")
    return path


@pytest.fixture()
def real_plan(tmp_path):
    if not EPISODE.is_file() or not SCRIPT.is_file():
        pytest.skip("NEWTECONS episode/script not present on this machine")
    out = tmp_path / "video-v001"
    base = ["--episode", str(EPISODE), "--out", str(out), "--machine", str(_machine(tmp_path))]
    code, result = run_video(["plan", *base, "--shotlist", str(SCRIPT)])
    assert code == 0, result
    return out, base, result


def test_dry_run_emits_the_graph_inputs_of_all_six_shots(real_plan) -> None:
    out, base, planned = real_plan
    assert [s["shot"] for s in planned["shots"]] == ["S02_A", "S03_A", "S04_A", "S05_A", "S06_A", "S07_A"]
    assert planned["shotlist_sha256"] == SCRIPT_SHA and planned["upscale"]["backend"] == "none"
    before = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    code, result = run_video(["run", *base, "--completion", "--lanes", "3", "--dry-run"])
    assert code == 0 and result["dry_run"] is True and result["domain"] == LIVE
    after = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert before == after  # dry-run ghi gì cũng không
    script = json.loads(SCRIPT.read_text("utf-8"))
    payloads = result["payloads"]
    assert [p["shot"] for p in payloads] == [s["id"] for s in script["shots"]]
    for index, (payload, row) in enumerate(zip(payloads, script["shots"])):
        assert payload["submit"] is False and payload["route"] == "h3-ref2va"
        assert row["speech_text"] in payload["prompt"]["text"] and row["source"]["prompt_as_code"]["subject"] in payload["prompt"]["text"]
        assert payload["prompt"]["port"] == "19.value" and len(payload["prompt"]["sha256"]) == 64
        assert payload["seed"] == {"port": "11.noise_seed", "value": 20261030 + index}
        frames = payload["length"]["frames"]
        assert payload["length"]["port"] == "6.length" and (frames - 5) % GRID == 0 and frames >= round(row["duration_s"] * 24)
        face = script["character_references"][row["speaker"]]
        bound = [r for r in payload["refs"] if r["bound"]]
        assert len(bound) == 1 and bound[0]["sha256"] == face["canonical_sha256"] and bound[0]["ports"] == ["5", "image"]
        assert payload["graph_inputs"]["5.image"] == f"h3-{face['canonical_sha256']}.png"
        assert payload["wav"]["status"] == "pending" and "NO_H3_INPUTS" in payload["wav"]["reason"]
        assert payload["anchor"]["status"] == "pending"
        assert payload["graph_inputs"]["7.audio"] == "<pending: wav>" and payload["graph_inputs"]["8.image"] == "<pending: anchor>"
        assert payload["geometry"] == {"width": 1280, "height": 704, "fps": 24.0}  # routes geometry (C2 -> 1440, user 31/10)
        assert payload["output_prefix_template"] == "NEWTECONS/H3/Shot"
    listeners = {p["shot"]: [r["role"] for r in p["refs"] if not r["bound"]] for p in payloads}
    assert listeners["S03_A"] == ["CHAR_GDDA"] and listeners["S05_A"] == ["CHAR_KYSU_TRE_NU"]
    preview = result["gates_preview"]
    assert preview["gpu_approval"] is False and preview["would_stop_at"] == "gpu-approval"
    assert preview["h3_qualification"] == "qualified" and preview["h3_inputs"] == "missing"
    assert preview["upscale_backend"] == "none" and preview["upscale_qualified"] is False
    assert sorted(r["lane"] for r in result["prompts"]) == [1, 1, 2, 2, 3, 3]


def test_dry_run_with_a_token_still_sends_nothing_and_names_the_pilot_gate(real_plan) -> None:
    out, base, _ = real_plan
    code, result = run_video(["run", *base, "--dry-run", "--gpu-approved", "token:user-token"])
    # H3 is qualified now, so the pilot gate is passed; the first real stop is the missing H3 inputs (technical).
    assert code == 0 and result["gates_preview"]["h3_qualification"] == "qualified"
    assert result["gates_preview"]["would_stop_at"] == "blocked_technical"
    assert result["gpu_approval"] == {"kind": "token", "value": "user-token"}
    assert not (out / "runs").exists() and not (out / "h3-r001").exists()
    code, status = run_video(["status", *base])
    assert code == 0 and status["counts"]["planned"] == 6 and status["chain_ok"] and status["current_shot"] == "S02_A"
    assert status["shots"][0]["next_stage"] == "02 VIẾT PROMPT"


def test_fixture_world_dry_run_matches_the_frozen_prompt_after_a_real_prompt_stage(tmp_path) -> None:
    world = VideoWorld(tmp_path)
    world.plan()
    dry = world.run_direct(dry_run=True)
    assert dry["payloads"][0]["prompt"]["sha256"] == dry["prompts"][0]["prompt_sha256"] and dry["prompts"][0]["written"] is False
    world.run()
    frozen = world.run_direct(dry_run=True)
    assert frozen["payloads"][0]["prompt"]["text"] == world.prompt_text()
    assert frozen["payloads"][0]["graph_inputs"]["31.image"].startswith("h3-")
