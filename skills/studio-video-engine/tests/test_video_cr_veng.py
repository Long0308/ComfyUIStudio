"""CR-VENG (critic Gemini, FAIL) — vòng sửa: (1) ``jjv video render|upscale`` là verb mỏng trên đúng mã/cổng của
``run``; (2) ``--gpu-approved`` chỉ nhận ``token:<text>`` hoặc một receipt file CÓ THẬT (đường dẫn gõ nhầm không bao
giờ thành phê duyệt); (3) ``h3 submit(hold_executor_lock=False)`` đòi người gọi ĐANG giữ EXECUTOR-RUN-LOCK (pid trong
thân khoá là tiến trình này hoặc tiến trình cha).  Không GPU, không mạng ngoài 127.0.0.1 (FakeComfy)."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from fake_comfy import FakeComfy
from video_fixtures import (CARTOON, SHOT, TOKEN, TOKEN_TEXT, FakeProbe, VideoWorld, fake_with_video, ok_ps,
                            run_video, sha_file, write_routes)

from engine.comfy.client import ComfyClient
from engine.core.errors import Refused
from engine.core.runlock import run_pid_lock
from engine.h3 import submit as h3_submit
from engine.video import upscale as upscale_mod
from engine.video.run import gpu_approval_from


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def prompted_world(tmp_path, fake, *, h3_inputs: bool = True) -> VideoWorld:
    """Plan + prompt (CPU) + h3-inputs: shot ``prompted``, sẵn sàng cho 03."""
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    fake_with_video(world.h3, fake)
    assert world.plan()[0] == 0
    assert world.run()[1]["gate"]["kind"] == "gpu-approval"
    if h3_inputs:
        world.write_h3_inputs()
    return world


def render_args(world: VideoWorld, *more: str) -> list[str]:
    return world.base("render", "--shot", SHOT, "--revision", "1", "--route", "h3-ref2va", *more)


def upscale_args(world: VideoWorld, source: Path, *more: str) -> list[str]:
    return world.base("upscale", "--shot", SHOT, "--source", str(source), "--target", "1920x1080", *more)


def native_path(world: VideoWorld) -> Path:
    receipt = json.loads((world.out / SHOT / "render" / "r001" / "render-receipt.json").read_text("utf-8"))
    return Path(receipt["native"]["path"])


def why(result: dict) -> str:
    return json.dumps(result.get("gate") or result.get("error") or result)


def fake_cli_handles(monkeypatch, world: VideoWorld, fake: FakeComfy) -> None:
    """Dây CLI thật (argparse -> run_video -> render_shot/upscale_shot); chỉ handle docker/ComfyUI là FakeComfy +
    FakeProbe + ok_ps (đúng như ``run_direct``), vì conftest chặn docker CLI thật."""
    from engine.video import cli

    monkeypatch.setattr(cli, "_handles", lambda _ctx: world.handles(fake))


def rendered_world(tmp_path, fake, monkeypatch) -> VideoWorld:
    world = prompted_world(tmp_path, fake)
    fake_cli_handles(monkeypatch, world, fake)
    code, result = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 0 and result["ok"] is True, why(result)
    assert world.state()["state"] == "rendered"
    return world


# ---- (1) jjv video render ------------------------------------------------------------------------------------
def test_render_verb_stops_at_the_gpu_gate_without_approval_and_posts_nothing(tmp_path, fake) -> None:
    world = prompted_world(tmp_path, fake)
    code, result = run_video(render_args(world))
    assert code == 0 and result["ok"] is False, result
    assert result["verb"] == "render" and result["shot"] == SHOT
    assert result["gate"]["kind"] == "gpu-approval" and result["gate"]["user_gate"] is True
    assert fake.posts == [] and world.state()["state"] == "prompted"
    assert world.state()["gate"]["kind"] == "gpu-approval"


def test_render_verb_renders_once_through_h3_and_resume_never_reposts(tmp_path, fake, monkeypatch) -> None:
    world = prompted_world(tmp_path, fake)
    fake_cli_handles(monkeypatch, world, fake)
    lock = world.h3.settings().executor_lock_path
    code, result = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 0 and result["ok"] is True, why(result)
    assert result["verb"] == "render" and result["gate"] is None
    assert [(s["step"], s["status"]) for s in result["steps"]] == [("render", "ok")]
    assert fake.posts_made() == [("POST", "/prompt")]
    assert not lock.exists()  # khoá máy thả sau job
    state = world.state()
    assert state["state"] == "rendered" and set(state["receipts"]) == {"plan", "prompt", "render"}
    receipt = json.loads((world.out / SHOT / "render" / "r001" / "render-receipt.json").read_text("utf-8"))
    assert receipt["gpu_approval"] == {"kind": "token", "value": TOKEN_TEXT}
    assert receipt["route"] == "h3-ref2va"
    assert Path(result["run_receipt"]).is_file()
    # lần hai không --resume: từ chối, không POST
    code, again = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 1 and "already rendered" in again["error"]
    assert len(fake.posts_made()) == 1
    # --resume: đọc lại bằng chứng, không POST, state không đổi
    code, resumed = run_video(render_args(world, "--gpu-approved", TOKEN, "--resume"))
    assert code == 0 and resumed["ok"] is True and resumed["resumed"] is True
    assert [(s["step"], s["status"]) for s in resumed["steps"]] == [("render", "already")]
    assert len(fake.posts_made()) == 1 and world.state()["state"] == "rendered"


def test_render_verb_refuses_a_wrong_revision_route_or_shot(tmp_path, fake) -> None:
    world = prompted_world(tmp_path, fake)
    code, result = run_video(world.base("render", "--shot", SHOT, "--revision", "2", "--route", "h3-ref2va",
                                        "--gpu-approved", TOKEN))
    assert code == 1 and "revision" in result["error"]
    code, result = run_video(world.base("render", "--shot", SHOT, "--revision", "1", "--route", "pika-turbo",
                                        "--gpu-approved", TOKEN))
    assert code == 1 and "route" in result["error"]
    code, result = run_video(world.base("render", "--shot", "S99_Z", "--revision", "1", "--route", "h3-ref2va",
                                        "--gpu-approved", TOKEN))
    assert code == 1 and "S99_Z" in result["error"]
    assert fake.posts == [] and world.state()["state"] == "prompted"


def test_render_verb_technical_stop_is_exit_1_and_names_h3_inputs(tmp_path, fake) -> None:
    world = prompted_world(tmp_path, fake, h3_inputs=False)
    code, result = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 1 and result["ok"] is False
    assert result["gate"]["kind"] == "blocked_technical" and "H3_INPUTS_MISSING" in result["gate"]["detail"]
    assert fake.posts == [] and world.state()["state"] == "prompted"


def test_render_verb_refuses_a_planned_shot(tmp_path, fake) -> None:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    assert world.plan()[0] == 0
    code, result = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 1 and "planned" in result["error"] and fake.posts == []


# ---- (1) jjv video upscale -----------------------------------------------------------------------------------
def test_upscale_verb_none_backend_records_pending_and_stops_at_the_pilot_gate(tmp_path, fake, monkeypatch) -> None:
    world = rendered_world(tmp_path, fake, monkeypatch)
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "none"))
    assert code == 0 and result["ok"] is False, result
    assert result["verb"] == "upscale" and result["gate"]["kind"] == "needs-gpu-pilot-approval"
    assert result["gate"]["user_gate"] is True and "upscale_pending" in result["gate"]["detail"]
    pending = world.out / SHOT / "upscale" / "r001" / "upscale-pending.json"
    assert json.loads(pending.read_text("utf-8"))["backend"] == "none"
    assert world.state()["state"] == "rendered" and len(fake.posts_made()) == 1


def test_upscale_verb_source_and_target_must_match_the_render_receipt(tmp_path, fake, monkeypatch) -> None:
    world = rendered_world(tmp_path, fake, monkeypatch)
    code, result = run_video(upscale_args(world, world.h3.anchor, "--backend", "none"))
    assert code == 1 and "native take" in result["error"]
    code, result = run_video(world.base("upscale", "--shot", SHOT, "--source", str(native_path(world)),
                                        "--target", "1280x720", "--backend", "none"))
    assert code == 1 and "target" in result["error"]
    assert not (world.out / SHOT / "upscale").exists()


def test_upscale_verb_gpu_backend_needs_approval_then_the_domain_pilot(tmp_path, fake, monkeypatch) -> None:
    world = rendered_world(tmp_path, fake, monkeypatch)
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "seedvr2-7b"))
    assert code == 0 and result["gate"]["kind"] == "gpu-approval" and result["gate"]["user_gate"] is True
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "seedvr2-7b", "--gpu-approved", TOKEN))
    assert code == 0 and result["gate"]["kind"] == "needs-gpu-pilot-approval"
    assert "UPSCALE_UNQUALIFIED" in result["gate"]["detail"]
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "magic", "--gpu-approved", TOKEN))
    assert code == 1 and result["gate"]["kind"] == "blocked_technical"
    assert world.state()["state"] == "rendered"
    assert not (world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").exists()


def test_upscale_verb_requires_a_rendered_shot(tmp_path, fake) -> None:
    world = prompted_world(tmp_path, fake)
    code, result = run_video(upscale_args(world, world.h3.anchor, "--backend", "none"))
    assert code == 1 and "prompted" in result["error"]


class _FakeLanczos:
    name, gpu = "lanczos", False

    def __init__(self, entry: dict) -> None:
        self.entry = entry

    def run(self, ctx, *, source, target, out_dir, shot, revision, gpu_approval):
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{shot}-{revision}-1080p.mp4"
        output.write_bytes(b"1080p:" + Path(source["path"]).read_bytes())
        return {"backend": self.name, "source": source, "output": {"path": str(output), "sha256": sha_file(output)},
                "geometry": {"in": "864x480", "out": target}, "qualification": self.entry}


def test_upscale_verb_with_a_qualified_cpu_backend_advances_the_state_and_resume_is_a_no_op(tmp_path, fake,
                                                                                               monkeypatch) -> None:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    qualification = tmp_path / "upscale-qualification.json"
    qualification.write_text('{"schema": "test/qualification", "status": "PASS"}', encoding="utf-8")
    write_routes(world.routes, {CARTOON: world.h3.template},
                 qualified={CARTOON: {"lanczos": {"path": str(qualification), "sha256": sha_file(qualification)}}})
    monkeypatch.setitem(upscale_mod.REGISTRY, "lanczos", _FakeLanczos)
    fake_with_video(world.h3, fake)
    fake_cli_handles(monkeypatch, world, fake)
    assert world.plan()[0] == 0
    world.run()
    world.write_h3_inputs()
    code, result = run_video(render_args(world, "--gpu-approved", TOKEN))
    assert code == 0, why(result)
    code, result = run_video(upscale_args(world, native_path(world), "--backend", "lanczos"))
    assert code == 0 and result["ok"] is True and result["gate"] is None, why(result)
    assert [(s["step"], s["status"]) for s in result["steps"]] == [("upscale", "ok")]
    assert world.state()["state"] == "upscaled_1080"
    receipt = world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json"
    assert json.loads(receipt.read_text("utf-8"))["backend"] == "lanczos"
    code, again = run_video(upscale_args(world, native_path(world), "--backend", "lanczos"))
    assert code == 1 and "already upscaled_1080" in again["error"]
    code, resumed = run_video(upscale_args(world, native_path(world), "--backend", "lanczos", "--resume"))
    assert code == 0 and resumed["resumed"] is True and world.state()["state"] == "upscaled_1080"
    assert len(fake.posts_made()) == 1


# ---- (2) --gpu-approved: token:<text> hoặc receipt có thật ------------------------------------------------------
@pytest.mark.parametrize("value", ["yes", "true", "false", "1", "none", "approved", "receipts/approval.json"])
def test_bare_text_is_never_an_approval(value: str) -> None:
    with pytest.raises(Refused, match="token:<text>"):
        gpu_approval_from(value)


def test_a_mistyped_receipt_path_is_an_error_not_a_token(tmp_path) -> None:
    missing = tmp_path / "user-approval-typo.json"
    with pytest.raises(Refused, match="does not exist|neither an existing receipt file"):
        gpu_approval_from(str(missing))
    with pytest.raises(Refused, match="not a file"):
        gpu_approval_from(str(tmp_path))  # thư mục có thật cũng không phải receipt


def test_explicit_token_form_and_real_receipt_are_accepted(tmp_path) -> None:
    assert gpu_approval_from("token:user said yes") == {"kind": "token", "value": "user said yes"}
    receipt = tmp_path / "user-approval.json"
    receipt.write_text('{"approved": true}', encoding="utf-8")
    bound = gpu_approval_from(str(receipt))
    assert bound["kind"] == "receipt" and bound["sha256"] == sha_file(receipt) and bound["path"] == str(receipt.resolve())


@pytest.mark.parametrize("value", ["token:", "token:   ", "token:false", "token:no", "token:none", "token:0"])
def test_empty_or_negative_token_text_is_refused(value: str) -> None:
    with pytest.raises(Refused):
        gpu_approval_from(value)


def test_cli_run_with_a_mistyped_receipt_path_refuses_before_any_write_or_post(tmp_path, fake) -> None:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    assert world.plan()[0] == 0
    code, result = run_video(world.base("run", "--completion", "--gpu-approved", str(tmp_path / "typo.json")))
    assert code == 1 and "typo.json" in result["error"]
    assert fake.posts == [] and not (world.out / "runs").exists()
    assert world.state()["state"] == "planned"  # ngay cả prompt (CPU) cũng chưa chạy: từ chối trước mọi việc


# ---- (3) h3 submit(hold_executor_lock=False) đòi người gọi đang giữ khoá -------------------------------------------
def _submit(world: VideoWorld, fake: FakeComfy, **kw):
    return h3_submit.submit(world.ctx(), world.h3.out, None, world.h3.settings(), ComfyClient(fake.url, timeout_seconds=5),
                            approve_gpu=True, probe=FakeProbe(), ps=ok_ps, wait_timeout=5, **kw)


def _prepared(tmp_path, fake) -> VideoWorld:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    fake_with_video(world.h3, fake)
    world.h3.prepare()
    return world


def test_hold_false_without_any_lock_is_refused_before_the_post(tmp_path, fake) -> None:
    world = _prepared(tmp_path, fake)
    with pytest.raises(Refused, match="EXECUTOR_LOCK_NOT_HELD"):
        _submit(world, fake, hold_executor_lock=False)
    assert fake.posts == [] and not (world.h3.out / SHOT / "comfy").exists()


def test_hold_false_with_a_lock_of_a_foreign_pid_is_refused_and_the_lock_is_left_alone(tmp_path, fake) -> None:
    world = _prepared(tmp_path, fake)
    lock = world.h3.settings().executor_lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": "jjv/run-lock/v1", "pid": 999_999_001, "host": socket.gethostname(), "process_start_time": None,
            "token": "e" * 32, "plan": "someone-else"}
    lock.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(Refused, match="EXECUTOR_LOCK_NOT_HELD.*999999001"):
        _submit(world, fake, hold_executor_lock=False)
    assert fake.posts == [] and json.loads(lock.read_text("utf-8")) == body


def test_hold_false_proceeds_when_this_process_holds_the_lock(tmp_path, fake) -> None:
    world = _prepared(tmp_path, fake)
    lock = world.h3.settings().executor_lock_path
    with run_pid_lock(lock, scope="machine", extra={"stage": "test-caller"}) as held:
        result = _submit(world, fake, hold_executor_lock=False)
        assert [r["status"] for r in result["submitted"]] == ["COMPLETED"]
        assert json.loads(lock.read_text("utf-8"))["token"] == held["token"]  # submit không đụng khoá của caller
    assert len(fake.posts_made()) == 1 and not lock.exists()


def test_hold_false_accepts_the_parent_process_as_holder(tmp_path, fake) -> None:
    world = _prepared(tmp_path, fake)
    lock = world.h3.settings().executor_lock_path
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"schema": "jjv/run-lock/v1", "pid": os.getppid(), "host": socket.gethostname(),
                                "process_start_time": None, "token": "d" * 32, "plan": "parent-run"}), encoding="utf-8")
    result = _submit(world, fake, hold_executor_lock=False)
    assert [r["status"] for r in result["submitted"]] == ["COMPLETED"] and len(fake.posts_made()) == 1
    assert lock.is_file()  # khoá của tiến trình cha không bị thả bởi submit
