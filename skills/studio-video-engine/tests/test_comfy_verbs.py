"""M4: atomic writes, run lock, settings and the four comfy verbs (part 2 of test_comfy_support.py)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from engine.comfy import commands, guards, staging
from engine.comfy.client import ComfyClient, ComfyError
from engine.comfy.dispatch import dispatch
from engine.comfy.outputs import collect_outputs, node_output_entries, resolve_output
from engine.comfy.settings import ComfySettings, settings_from_machine
from engine.comfy.telemetry import TelemetrySampler
from engine.comfy.wait import wait_for_history
from engine.core import io
from engine.core.errors import Failed, Refused, Uncertain, WaitTimeout
from engine.core.filelock import run_lock
from fake_comfy import FakeComfy

GRAPH = {"1": {"class_type": "LocalNode", "inputs": {"x": 1}},
         "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
POLICY = guards.ClassPolicy(frozenset({"claudenode", "badnode"}), True)


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def settings_for(fake, tmp_path, **kw) -> ComfySettings:
    return ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                         output_dir=tmp_path / "out", container="Comfyui-Studio", lock_timeout_seconds=0.2,
                         poll_seconds=0.01, **kw)


# ---- atomic writes and the run lock ------------------------------------------------------
def test_write_once_never_exposes_a_partial_file_and_cleans_its_temp(tmp_path, monkeypatch) -> None:
    target = tmp_path / "r.json"
    seen = []
    real_link = os.link

    def spy(src, dst, *a, **k):
        seen.append((Path(src).read_bytes(), Path(dst).exists()))  # complete bytes, target still absent
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(io.os, "link", spy)
    io.write_once(target, b"payload")
    assert seen == [(b"payload", False)] and [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_write_once_failure_between_temp_and_link_leaves_no_target_and_no_temp(tmp_path, monkeypatch) -> None:
    def failing(*a, **k):
        raise OSError("link failed")

    monkeypatch.setattr(io.os, "link", failing)
    with pytest.raises(OSError):
        io.write_once(tmp_path / "r.json", b"x")
    assert list(tmp_path.iterdir()) == []


def test_write_once_race_with_a_different_payload_refuses_and_keeps_the_winner(tmp_path) -> None:
    target = tmp_path / "r.json"
    barrier = threading.Barrier(2)
    outcomes: list = []

    def writer(payload: bytes) -> None:
        barrier.wait()
        try:
            outcomes.append(io.write_once(target, payload))
        except Refused as error:
            outcomes.append(error)

    threads = [threading.Thread(target=writer, args=(p,)) for p in (b"one", b"two")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(isinstance(o, Refused) for o in outcomes) == 1
    assert target.read_bytes() in (b"one", b"two") and [p.name for p in tmp_path.iterdir()] == ["r.json"]


def test_write_atomic_replaces_and_returns_the_sha(tmp_path) -> None:
    target = tmp_path / "job.json"
    io.write_atomic(target, b"one")
    assert io.write_atomic(target, b"two") == sha(b"two") and target.read_bytes() == b"two"
    assert [p.name for p in tmp_path.iterdir()] == ["job.json"]


def test_run_lock_excludes_a_second_holder_and_is_reusable(tmp_path) -> None:
    path = tmp_path / ".executor.lock"
    with run_lock(path, timeout_seconds=0):
        with pytest.raises(Refused, match="run lock"):
            with run_lock(path, timeout_seconds=0.1):
                pytest.fail("must not acquire")
    with run_lock(path, timeout_seconds=0):
        pass
    assert path.exists(), "the lock file itself is never deleted"
    with pytest.raises(ValueError):
        with run_lock(path, timeout_seconds=-1):
            pass


# ---- settings and the four comfy verbs ---------------------------------------------------
def test_settings_come_from_machine_config_only() -> None:
    machine = {"comfy": {"url": "http://127.0.0.1:1/", "root": "R", "container": "C"}, "gpu_lock_path": "L"}
    s = settings_from_machine(machine)
    assert (s.base_url, s.lock_path, s.input_dir, s.output_dir) == (
        "http://127.0.0.1:1", Path("L"), Path("R/input"), Path("R/output"))
    assert s.with_overrides(poll_seconds=None, lock_timeout_seconds=5).lock_timeout_seconds == 5


def test_check_reports_ready_busy_unhealthy_and_lock(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    ok_ps = lambda name: f"{name}|running|Up 2 hours (healthy)\n"  # noqa: E731
    report, ready = commands.cmd_check(client, settings, ps=ok_ps)
    assert ready and report["lock"]["exists"] is False and report["vram"][0]["vram_free_mib"] == 8192
    fake.queue["queue_pending"] = [[1, "p", {}, {}, []]]
    assert not commands.cmd_check(client, settings, ps=ok_ps)[1]
    fake.queue["queue_pending"] = []
    assert not commands.cmd_check(client, settings, ps=lambda n: f"{n}|exited|Exited (1)\n")[1]
    assert not commands.cmd_check(client, settings, ps=lambda n: f"{n}|running|Up (unhealthy)\n")[1]
    assert not commands.cmd_check(client, settings, ps=ok_ps, min_vram_free_mib=99999)[1]
    (tmp_path / "gpu.lock").write_text("pid=1 token=ab\n")
    report, ready = commands.cmd_check(client, settings, ps=ok_ps)
    assert not ready and any("lock" in p for p in report["problems"])
    assert fake.posts_made() == []


def _graph_file(tmp_path, graph=GRAPH) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph), encoding="utf-8")
    return path


def test_submit_wait_reconcile_round_trip(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    graph = _graph_file(tmp_path)
    fake.auto_complete = True
    out = tmp_path / "out" / "sub"
    out.mkdir(parents=True)
    (out / "clip.mp4").write_bytes(b"video-bytes")
    fake.on_post = lambda payload, pid: {"2": {"images": [{"filename": "clip.mp4", "subfolder": "sub",
                                                           "type": "output"}]}}
    summary = commands.cmd_submit(client, settings, POLICY, graph_path=graph, receipt_dir=tmp_path / "rc",
                                  expect_sha=sha(graph.read_bytes()))
    assert summary["prompt_id"] == "pid-0001" and len(fake.posts_made()) == 1
    waited = commands.cmd_wait(client, settings, receipt_dir=tmp_path / "rc", timeout_seconds=2)
    job = json.loads((tmp_path / "rc" / "job.json").read_text())
    assert waited["status"] == job["status"] == "COMPLETED"
    assert job["outputs"][0]["sha256"] == sha(b"video-bytes")
    report, code = commands.cmd_reconcile(client, settings, receipt_dir=tmp_path / "rc")
    assert code == 0 and report["prompt_id"] == "pid-0001" and len(fake.posts_made()) == 1


def test_submit_refuses_on_sha_partner_and_claudenode_without_posting(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    graph = _graph_file(tmp_path)
    with pytest.raises(Refused, match="sha256 mismatch"):
        commands.cmd_submit(client, settings, POLICY, graph_path=graph, receipt_dir=tmp_path / "rc",
                            expect_sha="0" * 64)
    claude = _graph_file(tmp_path, {**GRAPH, "3": {"class_type": "ClaudeNode", "inputs": {}}})
    with pytest.raises(Refused, match="forbidden"):
        commands.cmd_submit(client, settings, POLICY, graph_path=claude, receipt_dir=tmp_path / "rc2")
    assert fake.posts_made() == [] and not (tmp_path / "rc").exists() and not (tmp_path / "gpu.lock").exists()


def test_wait_failed_and_timeout_write_a_job_receipt(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    graph = _graph_file(tmp_path)
    fake.auto_complete = True
    fake.complete_status = {"status_str": "error", "completed": False}
    commands.cmd_submit(client, settings, POLICY, graph_path=graph, receipt_dir=tmp_path / "rc")
    with pytest.raises(Failed):
        commands.cmd_wait(client, settings, receipt_dir=tmp_path / "rc", timeout_seconds=2)
    assert json.loads((tmp_path / "rc" / "job.json").read_text())["status"] == "FAILED"
    fake.history.clear()
    with pytest.raises(WaitTimeout):
        commands.cmd_wait(client, settings, receipt_dir=tmp_path / "rc", timeout_seconds=0.1)
    assert json.loads((tmp_path / "rc" / "job.json").read_text())["status"] == "WAIT_TIMEOUT"
    assert len(fake.posts_made()) == 1


def test_reconcile_none_is_exit_two_and_bad_intents_are_errors(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    rc = tmp_path / "rc"
    rc.mkdir()
    with pytest.raises(Refused, match="nothing to reconcile"):
        commands.cmd_reconcile(client, settings, receipt_dir=rc)
    for content in ('{"nope": 1}', '{"client_id": 5, "graph_sha256": "x"}'):
        (rc / "dispatch-intent.json").write_text(content)
        with pytest.raises(Uncertain, match="client_id"):
            commands.cmd_reconcile(client, settings, receipt_dir=rc)
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "jjv-x", "graph_sha256": "a" * 64}))
    report, code = commands.cmd_reconcile(client, settings, receipt_dir=rc)
    assert code == 2 and report["status"] == "none" and "never resubmit" in report["next_action"]
    assert not (rc / "reconciled.json").exists() and fake.posts_made() == []


def test_wait_without_a_prompt_id_receipt_refuses(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    rc = tmp_path / "rc"
    rc.mkdir()
    (rc / "dispatch-intent.json").write_text(json.dumps({"client_id": "jjv-x", "graph_sha256": "a" * 64}))
    with pytest.raises(Refused, match="reconcile"):
        commands.cmd_wait(client, settings, receipt_dir=rc, timeout_seconds=0.1)


def test_dispatch_through_submit_uses_the_lock_path_from_settings_only(fake, tmp_path) -> None:
    client, settings = ComfyClient(fake.url, timeout_seconds=5), settings_for(fake, tmp_path)
    fake.auto_complete = True
    dispatch(client, settings, graph=GRAPH, receipt_dir=tmp_path / "rc", identity={"kind": "t"})
    assert not settings.lock_path.exists() and settings.lock_path.parent == tmp_path
