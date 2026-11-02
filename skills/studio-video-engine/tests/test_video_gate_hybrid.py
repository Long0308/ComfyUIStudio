"""GATE-HYBRID (user chốt 31/10 "Duyệt shot đầu rồi tự chạy"): chính sách ``take_gate`` của ``jjv video run``.

``every`` (mặc định, như cũ): dừng ở take-acceptance của MỌI shot.  ``first``: chỉ shot đầu dừng; khi shot đầu ĐÃ
``accepted`` bởi người, các shot sau chạy render -> upscale tự động và nằm ở ``upscaled_1080`` (đã sản xuất, chờ duyệt);
cuối lượt dừng một lần ở cổng ``review-pending``.  Không bao giờ tự đặt ``accepted``.  Không GPU: ``_render`` /
``_upscale`` được thay bằng bản giả ghi receipt thật; ``h3 accept`` (cần adopt.json) được thay bằng bản giả có ghi lại."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from video_fixtures import CARTOON, VideoWorld, shot_row

from engine.core.errors import Refused
from engine.core.io import sha256_file, write_json_once
from engine.video import accept as accept_mod
from engine.video import run as run_mod
from engine.video import state as state_mod

SHOTS = ["S01", "S02", "S03"]
BY = ("--by", "Kim")


def _receipt(out: Path, shot: str, state: dict, key: str, body: dict) -> Path:
    folder = out / shot / key / state_mod.rev(state["revision"])
    path = folder / f"{key}-receipt.json"
    write_json_once(path, body, mode="utf8")
    return path


@pytest.fixture(autouse=True)
def fake_pipeline(monkeypatch):
    """03/04 giả (CPU): receipt thật, file thật, hash theo shot+revision; h3 accept giả chỉ ghi lại lời gọi."""
    calls: list[str] = []

    def render(self, state, receipt):
        shot = state["shot"]
        calls.append(f"render:{shot}")
        native = self.out / shot / f"native-{state['revision']}.mp4"
        native.write_bytes(f"native {shot} {state['revision']}".encode())
        path = _receipt(self.out, shot, state, "render", {"native": {"path": str(native), "sha256": sha256_file(native)}})
        state_mod.advance(self.out, state, "rendered", receipt_key="render", receipt_path=path)
        return None

    def upscale(self, state, render_receipt=None):
        shot = state["shot"]
        calls.append(f"upscale:{shot}")
        output = self.out / shot / f"p1080-{state['revision']}.mp4"
        output.write_bytes(f"1080 {shot} {state['revision']}".encode())
        path = _receipt(self.out, shot, state, "upscale", {"output": {"path": str(output), "sha256": sha256_file(output)}})
        state_mod.advance(self.out, state, "upscaled_1080", receipt_key="upscale", receipt_path=path)
        return None

    monkeypatch.setattr(run_mod.Scheduler, "_render", render)
    monkeypatch.setattr(run_mod.Scheduler, "_upscale", upscale)
    monkeypatch.setattr(accept_mod.h3_accept, "decide",
                        lambda *a, **kw: {"record": "fake-ledger", "sha256": kw["sha256"]})
    return calls


def make_world(tmp_path, *, take_gate: str | None = "first", shots: list[str] = SHOTS) -> VideoWorld:
    world = VideoWorld(tmp_path, domain=CARTOON, shots=[shot_row(s) for s in shots])
    if take_gate is not None:
        routes = json.loads(world.routes.read_text("utf-8"))
        routes["take_gate"] = take_gate
        world.routes.write_text(json.dumps(routes), encoding="utf-8")
    assert world.plan()[0] == 0
    return world


def run(world: VideoWorld, *, completion: bool, **extra) -> dict:
    return run_mod.run(world.ctx(), world.out, completion=completion, gpu_token="token:user-ok",
                       routes_path=world.routes, wait_timeout=5, **extra)


def states(world: VideoWorld) -> list[str]:
    return [world.state(s)["state"] for s in SHOTS]


def pick(world: VideoWorld, shot: str) -> tuple[int, dict]:
    up = json.loads((world.out / shot / "upscale" / f"r{world.state(shot)['revision']:03d}" / "upscale-receipt.json")
                    .read_text("utf-8"))
    return world.accept("--shot", shot, "--pick", "--sha256", up["output"]["sha256"], *BY, "--reason", "watched, ok")


def reject(world: VideoWorld, shot: str) -> tuple[int, dict]:
    up = json.loads((world.out / shot / "upscale" / f"r{world.state(shot)['revision']:03d}" / "upscale-receipt.json")
                    .read_text("utf-8"))
    return world.accept("--shot", shot, "--reject", "--sha256", up["output"]["sha256"], *BY, "--reason", "lips late")


# (a) shot 1 vẫn dừng ở cổng acceptance ----------------------------------------------------------------------
def test_a_first_shot_stops_at_take_acceptance_and_nothing_after_it_runs(tmp_path, fake_pipeline) -> None:
    world = make_world(tmp_path)
    result = run(world, completion=True)
    assert result["ok"] is False and result["gate"]["kind"] == "take-acceptance" and result["gate"]["shot"] == "S01"
    assert result["gate"]["user_gate"] is True
    assert states(world) == ["upscaled_1080", "prompted", "prompted"]
    assert fake_pipeline == ["render:S01", "upscale:S01"]


# (b) shot 1 đã duyệt -> shot 2..M tự chạy, KHÔNG accepted -----------------------------------------------------
def test_b_after_first_accept_the_rest_run_through_and_stay_upscaled_not_accepted(tmp_path, fake_pipeline) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    assert pick(world, "S01")[0] == 0
    fake_pipeline.clear()
    result = run(world, completion=True)
    assert fake_pipeline == ["render:S02", "upscale:S02", "render:S03", "upscale:S03"]
    assert states(world) == ["accepted", "upscaled_1080", "upscaled_1080"]  # không bao giờ tự accepted
    assert result["gate"]["kind"] != "take-acceptance"
    assert not any(world.state(s)["receipts"].get("acceptance") for s in ("S02", "S03"))


# (c) cuối lượt dừng một lần ở cổng review-pending, liệt kê shot chờ duyệt ----------------------------------------
def test_c_end_of_run_stops_once_at_review_pending_listing_the_pending_shots(tmp_path) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    pick(world, "S01")
    result = run(world, completion=True)
    gate = result["gate"]
    assert gate["kind"] == "review-pending" and gate["user_gate"] is True and gate["shot"] is None
    assert gate["pending"] == ["S02", "S03"] and "S02" in gate["detail"] and "S03" in gate["detail"]
    assert result["ok"] is False and result["complete"] is False
    again = run(world, completion=True)  # chạy lại: không render/upscale lại, vẫn đúng cổng đó
    assert again["gate"]["kind"] == "review-pending" and again["gate"]["pending"] == ["S02", "S03"]


# (d) duyệt cuối vẫn cần MỌI shot accepted (accept.py không đổi) ----------------------------------------------
def test_d_final_review_still_needs_every_shot_accepted(tmp_path) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    pick(world, "S01")
    run(world, completion=True)
    code, bad = world.accept("--final", *BY, "--note", "watched all")
    assert code == 1 and "still pending" in bad["error"] and "S02" in bad["error"]
    assert pick(world, "S02")[0] == 0 and pick(world, "S03")[0] == 0
    result = run(world, completion=True)
    assert result["gate"]["kind"] == "final-review"  # hết shot chờ -> mới tới duyệt cuối
    code, final = world.accept("--final", *BY, "--note", "watched all")
    assert code == 0 and final["shots"] == SHOTS


def test_d_pick_still_needs_the_watched_sha_and_a_named_person(tmp_path) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    code, bad = world.accept("--shot", "S01", "--pick", "--sha256", "0" * 64, *BY, "--reason", "x")
    assert code == 1 and "1080p take" in bad["error"]
    code, bad = pick_as(world, "claude")
    assert code == 1 and "E_APPROVAL_BY" in bad["error"]
    assert world.state("S01")["state"] == "upscaled_1080"


def pick_as(world: VideoWorld, who: str) -> tuple[int, dict]:
    up = json.loads((world.out / "S01" / "upscale" / "r001" / "upscale-receipt.json").read_text("utf-8"))
    return world.accept("--shot", "S01", "--pick", "--sha256", up["output"]["sha256"], "--by", who, "--reason", "x")


# (e) shot 1 bị reject thì KHÔNG mở chế độ tự chạy ------------------------------------------------------------
def test_e_a_rejected_first_shot_does_not_unlock_auto_mode(tmp_path, fake_pipeline) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    code, rejected = reject(world, "S01")
    assert code == 0 and rejected["state"] == "planned" and rejected["revision"] == 2
    fake_pipeline.clear()
    result = run(world, completion=True)
    assert result["gate"]["kind"] == "take-acceptance" and result["gate"]["shot"] == "S01"
    assert fake_pipeline == ["render:S01", "upscale:S01"]  # S02/S03 không được chạm
    assert states(world) == ["upscaled_1080", "prompted", "prompted"]


# (f) reject muộn của shot sau -> revision mới như cũ (A9 không đổi) --------------------------------------------
def test_f_a_later_reject_creates_a_new_revision_and_is_redone_without_a_stop(tmp_path, fake_pipeline) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    pick(world, "S01")
    run(world, completion=True)
    first_sha = json.loads((world.out / "S02" / "upscale" / "r001" / "upscale-receipt.json")
                           .read_text("utf-8"))["output"]["sha256"]
    code, rejected = reject(world, "S02")
    assert code == 0 and rejected["state"] == "planned" and rejected["revision"] == 2
    state = world.state("S02")
    assert state["rejected"][0]["output_1080_sha256"] == first_sha and list(state["receipts"]) == ["plan"]
    assert (world.out / "S02" / "acceptance" / "001-reject.json").is_file()
    fake_pipeline.clear()
    result = run(world, completion=True)
    assert fake_pipeline == ["render:S02", "upscale:S02"]  # chỉ shot bị loại làm lại, revision 2
    assert world.state("S02")["revision"] == 2 and world.state("S02")["state"] == "upscaled_1080"
    assert result["gate"]["kind"] == "review-pending" and result["gate"]["pending"] == ["S02", "S03"]


# (g) status: N đã sản xuất / K đã duyệt / M ---------------------------------------------------------------------
def test_g_status_reports_produced_accepted_and_total(tmp_path) -> None:
    world = make_world(tmp_path)
    code, status = world.status()
    assert code == 0 and status["progress"] == {"produced": 0, "accepted": 0, "total": 3, "pending_review": []}
    run(world, completion=True)
    assert world.status()[1]["progress"] == {"produced": 1, "accepted": 0, "total": 3, "pending_review": ["S01"]}
    pick(world, "S01")
    run(world, completion=True)
    progress = world.status()[1]["progress"]
    assert progress == {"produced": 3, "accepted": 1, "total": 3, "pending_review": ["S02", "S03"]}
    pick(world, "S02")
    assert world.status()[1]["progress"]["accepted"] == 2


# mặc định 'every' giữ nguyên hành vi cũ + giá trị lạ bị từ chối ---------------------------------------------------
def test_default_policy_is_every_and_keeps_the_old_per_shot_stop(tmp_path, fake_pipeline) -> None:
    world = make_world(tmp_path, take_gate=None)
    run(world, completion=True)
    pick(world, "S01")
    fake_pipeline.clear()
    result = run(world, completion=True)
    assert result["gate"]["kind"] == "take-acceptance" and result["gate"]["shot"] == "S02"
    assert fake_pipeline == ["render:S02", "upscale:S02"]
    assert states(world) == ["accepted", "upscaled_1080", "prompted"]


def test_run_option_overrides_routes_and_an_unknown_policy_is_refused(tmp_path) -> None:
    world = make_world(tmp_path, take_gate="every")
    run(world, completion=True)
    pick(world, "S01")
    result = run(world, completion=True, take_gate="first")
    assert result["gate"]["kind"] == "review-pending" and states(world)[1:] == ["upscaled_1080", "upscaled_1080"]
    with pytest.raises(Refused, match="take_gate"):
        run(world, completion=True, take_gate="never")


def test_single_step_without_completion_never_enters_auto_mode(tmp_path) -> None:
    world = make_world(tmp_path)
    run(world, completion=True)
    pick(world, "S01")
    result = run(world, completion=False)  # một bước mỗi lượt như cũ
    assert states(world)[1] == "rendered" and result["gate"]["kind"] == "blocked_technical"
