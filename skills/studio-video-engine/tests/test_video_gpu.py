"""VENG-1: mọi bước chạm GPU từ chối khi thiếu ``--gpu-approved``; render thật đi qua H3 trên FakeComfy; khoá GPU
toàn cục; resume không POST lại; backend 1080p chưa qualify bị từ chối.  Không GPU, không mạng ngoài 127.0.0.1."""

from __future__ import annotations

import json

import pytest
from video_fixtures import (LIVE, SHOT, TOKEN, TOKEN_TEXT, FakeProbe, VideoWorld, fake_with_video, hold_executor_lock,
                            ok_ps, watch_lock_at_post)
from fake_comfy import FakeComfy

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused
from engine.h3 import submit as h3_submit
from engine.video import routes as routes_mod
from engine.video import upscale as upscale_mod


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def planned_world(tmp_path, fake, **kw) -> VideoWorld:
    world = VideoWorld(tmp_path, comfy_url=fake.url, **kw)
    code, _ = world.plan()
    assert code == 0
    return world


# ---- cổng --gpu-approved ---------------------------------------------------------------------------------
def test_run_without_gpu_approval_stops_at_the_gpu_gate_and_posts_nothing(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    code, result = world.run("--completion", "--lanes", "3")
    assert code == 0 and result["ok"] is False  # cổng người dùng: exit 0, ok false
    assert result["gate"]["kind"] == "gpu-approval" and result["gate"]["user_gate"] is True
    assert "GPU_APPROVAL_MISSING" in result["gate"]["detail"]
    assert fake.posts == [] and fake.posts_made() == []
    assert world.state()["state"] == "prompted"  # prompt (CPU) đã chạy, render chưa
    assert world.state()["gate"]["kind"] == "gpu-approval"
    assert (world.out / SHOT / "prompt" / "r001" / "prompt-receipt.json").is_file()
    assert not (world.out / "h3-r001").exists()


def test_empty_gpu_token_is_refused_before_anything(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    code, result = world.run("--completion", "--gpu-approved", "   ")
    assert code == 1 and "non-empty" in result["error"]
    assert fake.posts == []


def test_gpu_approval_receipt_path_is_hash_bound(tmp_path, fake) -> None:
    from engine.video.run import gpu_approval_from

    receipt = tmp_path / "user-approval.json"
    receipt.write_text('{"approved": true}', encoding="utf-8")
    bound = gpu_approval_from(str(receipt))
    assert bound["kind"] == "receipt" and len(bound["sha256"]) == 64
    assert gpu_approval_from("token:token-text") == {"kind": "token", "value": "token-text"}
    with pytest.raises(Refused, match="token:<text>"):  # CR-VENG: chữ trần không phải phê duyệt
        gpu_approval_from("token-text")


def test_live_domain_with_approval_stops_at_the_h3_pilot_gate_and_posts_nothing(tmp_path, fake, monkeypatch) -> None:
    """Domain được phép trong routes video nhưng H3 (recipes/h3/routes-v001.json) chưa qualified.

    newtecons_live_action đã qualified (2026-11-01), nên H3 routes được trỏ về bản trước qualification (không có
    receipt cho domain này) để kiểm tra đúng nhánh chưa qualified."""
    from engine.h3 import prepare

    unqualified = tmp_path / "h3-routes-unqualified.json"
    unqualified.write_text(json.dumps({"allowed_domains": ["jenniejoy_cartoon_3d"], "qualification_required": {},
                                       "legacy_voice_episodes": []}), encoding="utf-8")
    monkeypatch.setattr(prepare, "ROUTES", unqualified)
    world = planned_world(tmp_path, fake, domain=LIVE)
    world.run("--lanes", "2")  # prompts
    world.write_h3_inputs()
    result = world.run_direct(gpu_token=TOKEN, fake=fake)
    assert result["ok"] is False and result["gate"]["kind"] == "needs-gpu-pilot-approval"
    assert "not qualified" in result["gate"]["detail"]
    assert fake.posts == []
    assert world.state()["state"] == "prompted"


# ---- render thật qua H3 trên FakeComfy, rồi 1080p 'none' dừng ở cổng pilot, resume không POST lại -----------
def test_render_through_h3_then_upscale_none_gate_and_resume_never_reposts(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    fake_with_video(world.h3, fake)
    first = world.run("--completion")  # prompts + cổng gpu
    assert first[1]["gate"]["kind"] == "gpu-approval"
    world.write_h3_inputs()
    lock = world.h3.settings().executor_lock_path
    seen = watch_lock_at_post(fake, lock)
    result = world.run_direct(gpu_token=TOKEN, fake=fake)
    assert [p for p in fake.posts_made()] == [("POST", "/prompt")]  # đúng MỘT POST
    assert seen[0]["exists"] is True and seen[0]["body"]["stage"] == "video-render"  # khoá máy giữ lúc POST
    assert seen[0]["body"]["video_out"] == str(world.out.resolve()) and not lock.exists()  # và thả sau job
    assert result["ok"] is False and result["gate"]["kind"] == "needs-gpu-pilot-approval"
    assert "upscale_pending" in result["gate"]["detail"]
    state = world.state()
    assert state["state"] == "rendered" and set(state["receipts"]) == {"plan", "prompt", "render"}
    render = json.loads((world.out / SHOT / "render" / "r001" / "render-receipt.json").read_text("utf-8"))
    adopt = json.loads((world.out / "h3-r001" / SHOT / "adopt.json").read_text("utf-8"))
    editorial = next(r for r in adopt["outputs"] if r["role"] == "editorial")
    assert render["native"]["sha256"] == editorial["sha256"] and render["prompt_id"] == adopt["prompt_id"]
    assert render["gpu_approval"] == {"kind": "token", "value": TOKEN_TEXT}
    assert render["gpu_lock"]["path"] == str(lock) and render["gpu_lock"]["scope"] == "machine"
    preparation = json.loads((world.out / "h3-r001" / SHOT / "preparation.json").read_text("utf-8"))
    assert render["preparation"]["wav_sha256"] == preparation["wav"]["sha256"]  # WAV = receipt WAV
    assert preparation["mouth"]["19.value"] == world.prompt_text()  # prompt đóng băng đi thẳng vào graph
    pending = world.out / SHOT / "upscale" / "r001" / "upscale-pending.json"
    assert json.loads(pending.read_text("utf-8"))["status"] == "upscale_pending"
    steps = [(s["step"], s["status"]) for s in result["steps"]]
    assert steps == [("render", "ok"), ("upscale", "pending")]
    # resume: cùng lệnh lần hai -> không POST thêm, cùng cổng, state không đổi
    again = world.run_direct(gpu_token=TOKEN, fake=fake)
    assert len(fake.posts_made()) == 1
    assert again["gate"]["kind"] == "needs-gpu-pilot-approval" and world.state()["state"] == "rendered"
    assert [(s["step"], s["status"]) for s in again["steps"]] == [("upscale", "pending")]
    assert (world.out / "runs" / "run-001.json").is_file() and (world.out / "runs" / "run-002.json").is_file()


def test_unqualified_1080p_backend_is_refused_even_with_gpu_approval(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    fake_with_video(world.h3, fake)
    world.run()
    world.write_h3_inputs()
    world.run_direct(gpu_token=TOKEN, fake=fake)  # rendered
    result = world.run_direct(gpu_token=TOKEN, fake=fake, backend="seedvr2-7b")
    assert result["gate"]["kind"] == "needs-gpu-pilot-approval"
    assert "UPSCALE_UNQUALIFIED" in result["gate"]["detail"] and "seedvr2-7b" in result["gate"]["detail"]
    assert world.state()["state"] == "rendered"
    assert not (world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").exists()
    unknown = world.run_direct(gpu_token=TOKEN, fake=fake, backend="magic-upscaler")
    assert unknown["gate"]["kind"] == "blocked_technical" and "not one of" in unknown["gate"]["detail"]
    with pytest.raises(Refused, match="not one of"):  # cùng luật ở tầng backend
        upscale_mod.select_backend(world.ctx(), routes_mod.domain_route(world.ctx(), routes_mod.load_routes(world.routes)),
                                   "magic-upscaler")


def test_prompt_drift_in_h3_inputs_is_blocked_before_any_post(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    world.run()
    world.write_h3_inputs(**{"19.value": "someone edited the prompt by hand"})
    result = world.run_direct(gpu_token=TOKEN, fake=fake)
    assert result["gate"]["kind"] == "blocked_technical" and "PROMPT_DRIFT" in result["gate"]["detail"]
    assert fake.posts == []
    code, cli_result = world.run("--completion", "--gpu-approved", TOKEN)
    assert code == 1  # blocked_technical qua CLI là exit 1 (không phải cổng người dùng)


def test_missing_h3_inputs_is_a_technical_stop_with_the_exact_next_command(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    world.run()
    result = world.run_direct(gpu_token=TOKEN, fake=fake)
    gate = result["gate"]
    assert gate["kind"] == "blocked_technical" and "H3_INPUTS_MISSING" in gate["detail"]
    assert "jjv h3 inputs" in gate["detail"] and fake.posts == []


# ---- một khoá GPU toàn cục -------------------------------------------------------------------------------
def test_machine_executor_lock_held_by_a_live_process_blocks_the_gpu_step(tmp_path, fake) -> None:
    world = planned_world(tmp_path, fake)
    world.run()
    world.write_h3_inputs()
    lock = hold_executor_lock(world, "seedvr2-execute-of-another-plan")
    result = world.run_direct(gpu_token=TOKEN, fake=fake)
    assert result["gate"]["kind"] == "blocked_technical"
    assert "another executor is running" in result["gate"]["detail"]
    assert fake.posts == [] and lock.is_file()  # khoá của người khác không bao giờ bị xoá
    assert world.state()["state"] == "prompted"


def _h3_submit(world: VideoWorld, fake: FakeComfy, out, **kw):
    return h3_submit.submit(world.ctx(), out, None, world.h3.settings(), ComfyClient(fake.url, timeout_seconds=5),
                            approve_gpu=True, probe=FakeProbe(), ps=ok_ps, wait_timeout=5, **kw)


def test_plain_h3_submit_holds_the_same_machine_lock_for_post_and_wait_and_is_blocked_when_held(tmp_path, fake) -> None:
    """CR-VENG-RULES: `jjv h3 submit` (không qua video) cũng giữ EXECUTOR-RUN-LOCK suốt POST + wait."""
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    fake_with_video(world.h3, fake)
    world.h3.prepare()  # h3out/S02_A/preparation.json (cartoon domain: H3 qualified in recipes/h3/routes)
    lock = world.h3.settings().executor_lock_path
    seen = watch_lock_at_post(fake, lock)
    result = _h3_submit(world, fake, world.h3.out)
    assert [r["status"] for r in result["submitted"]] == ["COMPLETED"] and len(fake.posts_made()) == 1
    assert seen == [{"exists": True, "body": seen[0]["body"]}] and seen[0]["body"]["stage"] == "h3"
    assert seen[0]["body"]["shots"] == [SHOT] and seen[0]["body"]["out"] == str(world.h3.out.resolve())
    assert not lock.exists()  # thả sau khi job xong
    # một executor khác đang sống giữ khoá -> submit thứ hai (folder mới) bị từ chối, không POST
    second = tmp_path / "h3out-2"
    world.h3.prepare(out=second)
    hold_executor_lock(world, "seedvr2-execute")
    with pytest.raises(Refused, match="another executor is running"):
        _h3_submit(world, fake, second)
    assert len(fake.posts_made()) == 1 and not (second / SHOT / "comfy").exists()
    # resume của shot đã POST không cần khoá (không gửi gì) và vẫn báo ALREADY_SUBMITTED
    again = _h3_submit(world, fake, world.h3.out)
    assert [r["shot"] for r in again["already_submitted"]] == [SHOT] and len(fake.posts_made()) == 1


def test_lanes_only_parallelise_prompts_and_are_bounded(tmp_path, fake) -> None:
    from video_fixtures import shot_row

    shots = [shot_row("S01_A"), shot_row("S02_A"), shot_row("S03_A"), shot_row("S04_A")]
    world = VideoWorld(tmp_path, comfy_url=fake.url, shots=shots)
    assert world.plan()[0] == 0
    code, result = world.run("--lanes", "3")
    assert code == 0 and sorted(r["lane"] for r in result["prompts"]) == [1, 1, 2, 3]
    assert all(world.state(s["id"])["state"] == "prompted" for s in shots)
    assert fake.posts == []
    for bad in ("0", "11"):
        code, result = world.run("--lanes", bad)
        assert code == 1 and "--lanes" in result["error"]
    assert "one job" in result["error"]
