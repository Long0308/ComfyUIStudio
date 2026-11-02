"""VENG-1: máy trạng thái theo shot — plan write-once, prompt idempotent (A3), resume theo hash (A7), receipt đổi
byte ⇒ RECONCILE, acceptance/reject với ledger H3 (A8/A9), final review (A10).  Không GPU."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from video_fixtures import (CARTOON, SHOT, TOKEN, VideoWorld, fake_with_video, hold_executor_lock, sha_file,
                            write_routes)
from fake_comfy import FakeComfy

from engine.core.errors import Refused, Uncertain
from engine.video import routes as routes_mod
from engine.video import state as state_mod
from engine.video import upscale as upscale_mod


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def test_plan_writes_planned_states_and_is_write_once(tmp_path) -> None:
    world = VideoWorld(tmp_path)
    code, result = world.plan()
    assert code == 0 and result["shots"][0]["state"] == "planned"
    receipt = json.loads((world.out / SHOT / "plan-receipt.json").read_text("utf-8"))
    assert receipt["length"] == {"frames": 107, "wanted_frames": 96, "grid": "17k+5", "k": 6, "seconds": 4.4583,
                                 "source": "fixture"}
    assert receipt["seed"] == 1000 and receipt["refs"][0]["sha256"] == sha_file(world.h3.face)
    assert receipt["wav"]["status"] == "pending" and receipt["anchor"]["status"] == "pending"
    assert receipt["upscale"] == {"backend": "none", "target": "1920x1080", "qualified": False}
    state = world.state()
    assert state["state"] == "planned" and state["revision"] == 1 and list(state["receipts"]) == ["plan"]
    code, again = world.plan()
    assert code == 1 and "write-once" in again["error"]
    code, status = world.status()
    assert code == 0 and status["counts"]["planned"] == 1 and status["chain_ok"] and status["current_shot"] == SHOT


def test_prompt_is_idempotent_and_a_changed_prompt_needs_a_new_revision(tmp_path) -> None:
    from engine.video import prompt as prompt_mod

    world = VideoWorld(tmp_path)
    world.plan()
    first = world.run("--lanes", "2")[1]["prompts"][0]
    second = world.run("--lanes", "2")[1]["prompts"][0]
    assert first["written"] is True and second["written"] is False and second["reused"] is True
    assert first["prompt_sha256"] == second["prompt_sha256"]
    text = world.prompt_text()
    assert "Hello from S02_A" in text and "<Picture 1> = Alice (alice, alice)." in text and text.startswith("template prompt")
    with pytest.raises(Refused, match="NEW revision"):
        prompt_mod.write_prompt(world.out, SHOT, 1, text + "edited\n", body={})
    assert world.prompt_text() == text  # không ghi đè


def test_tampered_receipt_stops_with_reconcile_and_skips_nothing(tmp_path, fake) -> None:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    world.plan()
    world.run()
    receipt = world.out / SHOT / "prompt" / "r001" / "prompt-receipt.json"
    body = json.loads(receipt.read_text("utf-8"))
    body["lane"] = 99
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(Uncertain, match="RECONCILE"):
        world.run_direct(gpu_token=TOKEN, fake=fake)
    assert fake.posts == [] and world.state()["state"] == "prompted"
    code, status = world.status()
    assert code == 0 and status["chain_ok"] is False and "RECONCILE" in status["shots"][0]["problems"][0]


def test_illegal_transition_and_foreign_plan_are_refused(tmp_path) -> None:
    world = VideoWorld(tmp_path)
    world.plan()
    state = world.state()
    with pytest.raises(Refused, match="illegal transition"):
        state_mod.advance(world.out, state, "rendered")
    with pytest.raises(Refused, match="needs the prompt receipt"):
        state_mod.advance(world.out, state, "prompted", receipt_key="prompt")
    other = VideoWorld(tmp_path / "other", domain=CARTOON)
    plan = json.loads((world.out / "plan.json").read_text("utf-8"))
    plan["episode_id"] = "another-ep"
    (other.out).mkdir(parents=True)
    (other.out / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    code, result = other.status()
    assert code == 1 and "belongs to episode" in result["error"]


class FakeLanczos:
    """Adapter upscale giả (CPU) cho backend 'lanczos' sau khi domain có receipt qualification."""

    name, gpu = "lanczos", False

    def __init__(self, entry: dict) -> None:
        self.entry = entry

    def run(self, ctx, *, source, target, out_dir, shot, revision, gpu_approval):
        out_dir.mkdir(parents=True, exist_ok=True)
        output = out_dir / f"{shot}-{revision}-1080p.mp4"
        output.write_bytes(b"1080p:" + Path(source["path"]).read_bytes())
        return {"backend": self.name, "source": source, "output": {"path": str(output), "sha256": sha_file(output)},
                "geometry": {"in": "864x480", "out": target}, "qualification": self.entry}


def qualified_world(tmp_path, fake, monkeypatch) -> VideoWorld:
    world = VideoWorld(tmp_path, comfy_url=fake.url)
    qualification = tmp_path / "upscale-qualification.json"
    qualification.write_text('{"schema": "test/qualification", "status": "PASS"}', encoding="utf-8")
    write_routes(world.routes, {CARTOON: world.h3.template},
                 qualified={CARTOON: {"lanczos": {"path": str(qualification), "sha256": sha_file(qualification)}}})
    monkeypatch.setitem(upscale_mod.REGISTRY, "lanczos", FakeLanczos)
    fake_with_video(world.h3, fake)
    assert world.plan()[0] == 0
    world.run()
    world.write_h3_inputs()
    return world


class FakeGpuUpscaler(FakeLanczos):
    """Backend GPU giả: tự kiểm rằng khoá EXECUTOR máy đang được giữ (thân khoá stage video-upscale) khi chạy."""

    gpu = True
    lock = None  # được test gán

    def run(self, ctx, **kw):
        body = json.loads(self.lock.read_text("utf-8"))
        assert body["stage"] == "video-upscale" and body["backend"] == "lanczos" and body["shot"] == kw["shot"]
        return super().run(ctx, **kw)


def test_gpu_upscale_backend_runs_under_the_machine_lock_and_is_blocked_when_held(tmp_path, fake, monkeypatch) -> None:
    world = qualified_world(tmp_path, fake, monkeypatch)
    FakeGpuUpscaler.lock = world.h3.settings().executor_lock_path
    monkeypatch.setitem(upscale_mod.REGISTRY, "lanczos", FakeGpuUpscaler)
    no_token = world.run_direct(fake=fake, backend="lanczos")  # render cần token trước
    assert no_token["gate"]["kind"] == "gpu-approval"
    rendered = world.run_direct(gpu_token=TOKEN, fake=fake, backend="lanczos")
    assert rendered["gate"]["kind"] == "take-acceptance" and world.state()["state"] == "upscaled_1080"
    assert not FakeGpuUpscaler.lock.exists()  # thả sau job
    # world thứ hai trên một FakeComfy RIÊNG (cùng graph trên cùng server sẽ bị dispatch chặn là "twin": đúng luật)
    with FakeComfy() as fake2:
        other = VideoWorld(tmp_path / "other", comfy_url=fake2.url)
        write_routes(other.routes, {CARTOON: other.h3.template},
                     qualified={CARTOON: {"lanczos": {"path": str(tmp_path / "upscale-qualification.json"),
                                                       "sha256": sha_file(tmp_path / "upscale-qualification.json")}}})
        fake_with_video(other.h3, fake2)
        other.plan()
        other.run()
        other.write_h3_inputs()
        other.run_direct(gpu_token=TOKEN, fake=fake2)  # rendered (backend none -> pending)
        hold_executor_lock(other, "seedvr2-execute")
        FakeGpuUpscaler.lock = other.h3.settings().executor_lock_path
        blocked = other.run_direct(gpu_token=TOKEN, fake=fake2, backend="lanczos")
        assert blocked["gate"]["kind"] == "blocked_technical" and "another executor is running" in blocked["gate"]["detail"]
        assert other.state()["state"] == "rendered"
        assert not (other.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").exists()
        with pytest.raises(Refused, match="GPU_LOCK_MISSING"):
            upscale_mod.upscale(other.ctx(), other.out, other.state(),
                                routes_mod.domain_route(other.ctx(), routes_mod.load_routes(other.routes)),
                                backend_name="lanczos", gpu_approval={"kind": "token", "value": TOKEN}, lock_path=None)


def test_qualified_backend_without_adapter_is_not_implemented(tmp_path, fake, monkeypatch) -> None:
    world = qualified_world(tmp_path, fake, monkeypatch)
    monkeypatch.delitem(upscale_mod.REGISTRY, "lanczos")
    result = world.run_direct(gpu_token=TOKEN, fake=fake, backend="lanczos")
    assert result["gate"]["kind"] == "blocked_technical" and "UPSCALE_NOT_IMPLEMENTED" in result["gate"]["detail"]
    assert world.state()["state"] == "rendered"


def test_reject_goes_back_to_a_new_revision_and_the_ledger_bans_the_take(tmp_path, fake, monkeypatch) -> None:
    from engine.h3 import ledger

    world = qualified_world(tmp_path, fake, monkeypatch)
    result = world.run_direct(gpu_token=TOKEN, fake=fake, backend="lanczos")
    assert result["gate"]["kind"] == "take-acceptance" and world.state()["state"] == "upscaled_1080"
    up = json.loads((world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").read_text("utf-8"))
    render = json.loads((world.out / SHOT / "render" / "r001" / "render-receipt.json").read_text("utf-8"))
    assert up["source"]["sha256"] == render["native"]["sha256"]  # A8: nguồn upscale là take native của chính shot
    code, bad = world.accept("--shot", SHOT, "--pick", "--sha256", render["native"]["sha256"], "--by", "Kim", "--reason", "x")
    assert code == 1 and "1080p take" in bad["error"]  # pick theo sha native bị từ chối
    code, bad = world.accept("--shot", SHOT, "--pick", "--sha256", up["output"]["sha256"], "--by", "claude", "--reason", "x")
    assert code == 1 and "E_APPROVAL_BY" in bad["error"]
    code, rejected = world.accept("--shot", SHOT, "--reject", "--sha256", up["output"]["sha256"], "--by", "Kim",
                                  "--reason", "lips late")
    assert code == 0 and rejected["state"] == "planned" and rejected["revision"] == 2
    assert render["native"]["sha256"] in ledger.rejected_shas(world.ctx())
    state = world.state()
    assert state["rejected"][0]["native_sha256"] == render["native"]["sha256"] and list(state["receipts"]) == ["plan"]
    code, again = world.accept("--shot", SHOT, "--pick", "--sha256", up["output"]["sha256"], "--by", "Kim", "--reason", "y")
    assert code == 1 and "upscaled_1080" in again["error"]  # A9: hash bị reject không thể pick lại
    assert (world.out / SHOT / "acceptance" / "001-reject.json").is_file()
    # revision mới: prompt r002 được đóng băng riêng, h3-spec-r002 cho `jjv h3 inputs`
    world.run()
    assert world.state()["state"] == "prompted" and world.state()["revision"] == 2
    assert (world.out / SHOT / "prompt" / "r002" / "prompt-receipt.json").is_file()
    assert (world.out / "h3-spec-r002.json").is_file()


def test_pick_then_final_review_completes_the_run(tmp_path, fake, monkeypatch) -> None:
    world = qualified_world(tmp_path, fake, monkeypatch)
    world.run_direct(gpu_token=TOKEN, fake=fake, backend="lanczos")
    up = json.loads((world.out / SHOT / "upscale" / "r001" / "upscale-receipt.json").read_text("utf-8"))
    code, picked = world.accept("--shot", SHOT, "--pick", "--sha256", up["output"]["sha256"], "--by", "Kim",
                                "--reason", "identity and lips ok")
    assert code == 0 and picked["state"] == "accepted"
    result = world.run_direct(fake=fake)  # không cần GPU nữa: mọi shot accepted -> cổng final review
    assert result["gate"]["kind"] == "final-review" and result["complete"] is False
    code, bad = world.accept("--final", "--by", "Kim", "--note", "")
    assert code == 1
    code, final = world.accept("--final", "--by", "Kim", "--note", "assembled candidate watched")
    assert code == 0 and final["shots"] == [SHOT]
    result = world.run_direct(fake=fake)
    assert result["ok"] is True and result["complete"] is True and result["gate"] is None
    code, status = world.status()
    assert status["complete"] is True and status["counts"]["accepted"] == 1
    assert len(fake.posts_made()) == 1  # toàn bộ vòng đời: đúng một POST


def test_h3_spec_carries_the_frozen_geometry_and_drops_unfilled_refs(tmp_path) -> None:
    """The spec written for `jjv h3 inputs` must already satisfy `render.require_manifest` (GEOMETRY_DRIFT) and bind a
    pack with fewer refs than the template has loaders (drop_unfilled_refs); no hand edit of the spec (ep05, 01/11)."""
    world = VideoWorld(tmp_path)
    routes = json.loads(Path(world.routes).read_text("utf-8"))
    routes["domains"][CARTOON]["geometry"] = {"width_port": "6.width", "height_port": "6.height", "fps_port": "17.fps",
                                              "width": 1280, "height": 704, "multiple_of": 32, "source": "test"}
    Path(world.routes).write_text(json.dumps(routes), encoding="utf-8")
    world.plan()
    world.run()
    spec = json.loads((world.out / "h3-spec-r001.json").read_text("utf-8"))
    plan = json.loads((world.out / SHOT / "plan-receipt.json").read_text("utf-8"))
    frozen = plan["geometry"]
    mouth = spec["shots"][0]["mouth"]
    assert mouth[frozen["ports"]["width"]] == frozen["width"] and mouth[frozen["ports"]["height"]] == frozen["height"]
    assert spec["defaults"]["drop_unfilled_refs"] is True
