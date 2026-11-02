"""v004: terminal latch checked INSIDE the dispatch lock, right before the POST (hàm dispatch thật)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from engine.comfy import dispatch as dsp
from engine.comfy import run_watchdog as wd
from engine.comfy.client import ComfyClient
from engine.comfy.settings import ComfySettings
from engine.core.errors import Refused
from fake_comfy import FakeComfy

GRAPH = {"1": {"class_type": "LocalNode", "inputs": {"x": 1}},
         "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
RUN_ID = "run-v004"


@pytest.fixture
def tmp_path(request):  # cùng lý do với test_watchdog.py: ACL 0700 của pytest bị chặn trên host này
    base = Path(request.config.getoption("basetemp"))
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


class LatchingClient(ComfyClient):
    """Fake transport: sau khi trả history, gọi latch_terminal thật (watchdog ghi latch giữa precheck và POST)."""

    def __init__(self, url, *, on_history=None):
        super().__init__(url, timeout_seconds=5)
        self.on_history, self.paths = on_history, []

    def get(self, path, *, timeout=None):
        result = super().get(path, timeout=timeout)
        self.paths.append(path)
        if path.startswith("/history") and self.on_history:
            self.on_history()
        return result


def write_latch(latch: Path, gate_path: Path, status: str = "FAIL") -> None:
    with wd.file_gate(gate_path, timeout=2.0):
        wd.latch_terminal(latch, run_id=RUN_ID, execution_status=status, reason="vram_mib",
                          timestamp="2026-10-31T00:00:00+00:00", monotonic=1.0,
                          container_epoch="e1", container_id="c1", evidence={"x": 1})


def setup(fake, tmp_path, on_history=None):
    settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                             output_dir=tmp_path / "out", container="c", lock_timeout_seconds=1.0, poll_seconds=0.01)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    latch, gate_path = run_dir / "terminal-latch.json", run_dir / "terminal-latch.gate"
    guard = wd.TerminalGuard(run_id=RUN_ID, latch_path=latch, gate=lambda: wd.file_gate(gate_path, timeout=2.0))
    client = LatchingClient(fake.url, on_history=(lambda: write_latch(latch, gate_path)) if on_history else None)
    return client, settings, guard, latch, gate_path


def call(client, settings, guard, tmp_path):
    return dsp.dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "rc",
                        identity={"kind": "t"}, guard=guard,
                        container_instance=lambda: {"started_at_text": "2026-10-31T00:00:00Z"})


def test_terminal_latch_between_precheck_and_post_blocks_dispatch(fake, tmp_path) -> None:
    client, settings, guard, latch, _ = setup(fake, tmp_path, on_history=True)
    with pytest.raises(dsp.TerminalLatchRefused) as info:
        call(client, settings, guard, tmp_path)
    assert not isinstance(info.value, dsp.PostOutcomeUnknown) and isinstance(info.value, Refused)
    assert "/queue" in client.paths and any(p.startswith("/history") for p in client.paths)
    assert fake.posts_made() == [] and not any(p == "/prompt" for _, p in fake.requests)
    rc = tmp_path / "rc"
    refused = json.loads((rc / "dispatch-refused-terminal.json").read_text())
    assert refused["post_attempted"] is False and refused["run_id"] == RUN_ID
    assert refused["latch_path"] == str(latch) and refused["latch_status"] == "FAIL"
    assert len(refused["graph_sha256"]) == 64 and refused["client_id"].startswith("jjv-")
    assert (rc / "dispatch-intent.json").exists()
    assert not (rc / "submitted.json").exists() and not (rc / "submit-unknown.json").exists()
    assert not (tmp_path / "gpu.lock").exists(), "dispatch lock phải được nhả"
    with wd.file_gate(tmp_path / "run" / "terminal-latch.gate", timeout=0.5):
        pass  # gate cũng đã được nhả


def test_latch_present_before_call_blocks_post(fake, tmp_path) -> None:
    client, settings, guard, latch, gate_path = setup(fake, tmp_path)
    write_latch(latch, gate_path, "LOST")
    with pytest.raises(dsp.TerminalLatchRefused):
        call(client, settings, guard, tmp_path)
    assert fake.posts_made() == []


def test_unreadable_latch_blocks_post_with_guard_error(fake, tmp_path) -> None:
    client, settings, guard, latch, _ = setup(fake, tmp_path)
    latch.write_text("{not json")
    with pytest.raises(dsp.GuardRefused) as info:
        call(client, settings, guard, tmp_path)
    assert not isinstance(info.value, dsp.TerminalLatchRefused)
    assert fake.posts_made() == []
    assert json.loads((tmp_path / "rc" / "dispatch-refused-terminal.json").read_text())["post_attempted"] is False


def test_refusal_receipt_write_failure_still_blocks_post(fake, tmp_path, monkeypatch) -> None:
    client, settings, guard, latch, gate_path = setup(fake, tmp_path)
    write_latch(latch, gate_path)

    def boom(path, body):
        raise OSError("disk full")
    monkeypatch.setattr(wd, "write_receipt_atomic", boom)
    with pytest.raises(dsp.TerminalLatchRefused) as info:
        call(client, settings, guard, tmp_path)
    assert "disk full" in repr(info.value.evidence)
    assert fake.posts_made() == []
    assert not (tmp_path / "rc" / "dispatch-refused-terminal.json").exists()


def test_gate_unavailable_refuses_without_post(fake, tmp_path) -> None:
    client, settings, guard, _, gate_path = setup(fake, tmp_path)
    with wd.file_gate(gate_path, timeout=1.0):  # gate bị giữ ⇒ dispatcher hết hạn chờ ⇒ từ chối
        short = wd.TerminalGuard(run_id=RUN_ID, latch_path=guard.latch_path,
                                 gate=lambda: wd.file_gate(gate_path, timeout=0.2))
        with pytest.raises(dsp.GuardRefused):
            call(client, settings, short, tmp_path)
    assert fake.posts_made() == []


def test_no_latch_posts_normally(fake, tmp_path) -> None:
    client, settings, guard, _, _ = setup(fake, tmp_path)
    assert call(client, settings, guard, tmp_path).prompt_id == "pid-0001"


def test_transport_error_after_post_started_is_still_unknown(fake, tmp_path) -> None:
    client, settings, guard, _, _ = setup(fake, tmp_path)
    fake.post_mode = "drop"
    with pytest.raises(dsp.PostOutcomeUnknown):
        call(client, settings, guard, tmp_path)
    assert not (tmp_path / "rc" / "dispatch-refused-terminal.json").exists()


# ---- round 2: yêu cầu guard do RUN khai (marker), không do thiện chí của caller ---------------------
def _declare(tmp_path, where: Path | None = None) -> Path:
    return wd.declare_guard_required(where or tmp_path / "rc", run_id=RUN_ID)


def test_pilot_declared_run_without_guard_refuses_with_guard_required(fake, tmp_path) -> None:
    client, settings, _, _, _ = setup(fake, tmp_path)
    _declare(tmp_path)
    with pytest.raises(dsp.GuardRequired) as info:
        dsp.dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "rc", identity={"kind": "t"},
                     container_instance=lambda: {"started_at_text": "x"})
    assert isinstance(info.value, Refused) and not isinstance(info.value, dsp.PostOutcomeUnknown)
    assert fake.posts_made() == []
    assert not (tmp_path / "rc" / "dispatch-intent.json").exists()


def test_marker_in_parent_run_dir_also_requires_guard(fake, tmp_path) -> None:
    client, settings, _, _, _ = setup(fake, tmp_path)
    _declare(tmp_path, tmp_path / "runs")
    with pytest.raises(dsp.GuardRequired):
        dsp.dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "runs" / "shot" / "chunk",
                     identity={"kind": "t"})
    assert fake.posts_made() == []


def test_declared_run_with_guard_posts(fake, tmp_path) -> None:
    client, settings, guard, _, _ = setup(fake, tmp_path)
    _declare(tmp_path)
    assert call(client, settings, guard, tmp_path).prompt_id == "pid-0001"


def test_non_pilot_run_without_guard_keeps_old_behaviour(fake, tmp_path) -> None:
    client, settings, _, _, _ = setup(fake, tmp_path)
    result = dsp.dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "rc", identity={"kind": "t"})
    assert result.prompt_id == "pid-0001" and len(fake.posts_made()) == 1


def test_watchdog_startup_writes_the_marker(tmp_path) -> None:
    latch_dir = tmp_path / "run-x"
    wd.declare_guard_required(latch_dir, run_id="run-x")
    assert wd.guard_required_marker(latch_dir / "chunk") is not None
    assert wd.guard_required_marker(tmp_path / "other") is None
