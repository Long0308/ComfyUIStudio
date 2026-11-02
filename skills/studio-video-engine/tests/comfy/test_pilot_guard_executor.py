"""Executor opt-in `terminal_guard: true`: marker trước POST đầu, guard trên mọi dispatch, latch dừng chunk kế."""
from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import pytest

from engine.comfy import dispatch as dsp
from engine.comfy import run_watchdog as wd
from engine.comfy.pilot_guard import PilotGuard, PilotGuardStartError
from engine.core.errors import Refused
from engine.seedvr2 import execute as ex
from engine.seedvr2.execplan import load_exec_plan
from exec_fixtures import FakeDocker, make_rig
from fake_comfy import FakeComfy


@pytest.fixture
def tmp_path(request):  # ACL 0700 của pytest bị chặn trên host này (xem test_watchdog.py)
    path = Path(request.config.getoption("basetemp")) / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def opted(rig):
    body = json.loads(rig.plan.path.read_text("utf-8"))
    body["terminal_guard"] = True
    rig.plan.path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return dataclasses.replace(rig, plan=load_exec_plan(rig.plan.path, rig.config, rig.recipe))


def good_pollers(**over):
    base = dict(ram_bytes=lambda: 1024, vram_mib=lambda: 100.0,
                queue=lambda: {"queue_running": [], "queue_pending": []}, started_at=lambda: FakeDocker.BEFORE)
    return wd.Pollers(**{**base, **over})


def factory(pollers=None):
    def build(executor):
        return PilotGuard(run_dir=executor.plan.root / "runs", run_id="run-exec", pollers=pollers or good_pollers(),
                          container_id="test-container", interrupt=lambda: None, delete_pending=lambda ids: None)
    return build


def spy(monkeypatch, after_first=None):
    calls = []
    real = ex.dispatch

    def wrapper(*args, **kwargs):
        marker = wd.guard_required_marker(kwargs["receipt_dir"])
        calls.append({"guard": kwargs.get("guard"), "marker_before": marker is not None})
        result = real(*args, **kwargs)
        if len(calls) == 1 and after_first:
            after_first()
        return result
    monkeypatch.setattr(ex, "dispatch", wrapper)
    return calls


def test_opted_plan_declares_marker_passes_guard_and_latch_stops_the_next_chunk(fake, tmp_path, monkeypatch) -> None:
    rig = opted(make_rig(tmp_path, fake))
    marker_at_first_post = {}
    render = fake.on_post

    def at_post(payload, prompt_id):
        marker_at_first_post.setdefault("exists", (rig.plan.root / "runs" / wd.GUARD_REQUIRED_MARKER).exists())
        return render(payload, prompt_id)
    fake.on_post = at_post
    latch = rig.plan.root / "runs" / "terminal-latch.json"

    def set_latch():
        with wd.file_gate(latch.with_name("terminal-latch.gate"), timeout=2.0):
            wd.latch_terminal(latch, run_id="run-exec", execution_status="FAIL", reason="vram_mib",
                              timestamp="t", monotonic=1.0, container_epoch="e", container_id="c", evidence={})
    calls = spy(monkeypatch, after_first=set_latch)
    result = rig.executor(pilot_guard_factory=factory()).run(rig.tasks())
    assert marker_at_first_post == {"exists": True}
    assert len(fake.posts_made()) == 1 and len(calls) == 1
    assert all(c["guard"] is not None and c["marker_before"] for c in calls)
    assert result["exit_code"] != 0 and result["stopped"]["stage"] == "terminal_latch"
    stop = json.loads((rig.plan.root / "runs" / "terminal-guard-stop.json").read_text())
    assert stop["run_id"] == "run-exec" and stop["latch_status"] == "FAIL" and stop["next_chunk"]
    state = json.loads((rig.plan.root / "runs" / "run-state.json").read_text())
    assert state["status"] == "STOPPED"


def test_opted_plan_full_run_passes_guard_on_every_dispatch(fake, tmp_path, monkeypatch) -> None:
    rig = opted(make_rig(tmp_path, fake))
    calls = spy(monkeypatch)
    result = rig.executor(pilot_guard_factory=factory()).run(rig.tasks())
    assert result["exit_code"] == 0, result
    assert len(calls) == len(fake.posts_made()) == 4
    assert all(c["guard"] is not None for c in calls)


def test_poller_init_failure_refuses_before_any_post(fake, tmp_path) -> None:
    rig = opted(make_rig(tmp_path, fake))

    def broken():
        raise OSError("nvidia-smi missing")
    with pytest.raises(PilotGuardStartError) as info:
        rig.executor(pilot_guard_factory=factory(good_pollers(vram_mib=broken))).run(rig.tasks())
    assert isinstance(info.value, Refused) and fake.posts_made() == []


def test_non_opted_plan_keeps_old_behaviour(fake, tmp_path, monkeypatch) -> None:
    rig = make_rig(tmp_path, fake)

    def must_not_build(executor):
        raise AssertionError("guard factory must not run for a non-opted plan")
    calls = spy(monkeypatch)
    result = rig.executor(pilot_guard_factory=must_not_build).run(rig.tasks())
    assert result["exit_code"] == 0 and len(calls) == 4 and all(c["guard"] is None for c in calls)
    assert not (rig.plan.root / "runs" / wd.GUARD_REQUIRED_MARKER).exists()
