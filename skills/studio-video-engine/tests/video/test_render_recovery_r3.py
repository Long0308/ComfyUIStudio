"""Crash recovery contracts, using local fakes only (no HTTP, Docker, or GPU)."""

import json
import socket
import time
from pathlib import Path

import pytest

from engine.comfy.docker_probe import ContainerState
from engine.core.errors import Refused, Uncertain
from engine.core.runlock import rename_stale_lock
from engine.h3.submit import _recover_lost
from engine.comfy.settings import ComfySettings


def _lock(path: Path, *, age: float = 1) -> None:
    path.write_text(json.dumps({"schema": "jjv/run-lock/v1", "pid": 424242, "host": socket.gethostname(),
                                "process_start_time": 100.0, "acquired_at": time.time() - age,
                                "token": "dead-token"}), encoding="utf-8")


def test_dead_lock_is_renamed_and_reported(tmp_path):
    path = tmp_path / "EXECUTOR-RUN-LOCK.json"
    _lock(path)
    archived = rename_stale_lock(path, queue_idle=lambda: True, report_dir=tmp_path / "runs",
                                 info=lambda _pid: (False, None))
    assert archived is not None and archived.name.startswith(path.name + ".stale-")
    assert not path.exists() and json.loads(archived.read_text())["token"] == "dead-token"
    report = next((tmp_path / "runs").glob("stale-lock-machine-*.json"))
    assert json.loads(report.read_text())["archive"] == str(archived)


def test_live_or_busy_lock_stays_put(tmp_path):
    path = tmp_path / "EXECUTOR-RUN-LOCK.json"
    _lock(path)
    with pytest.raises(Refused, match="another executor"):
        rename_stale_lock(path, queue_idle=lambda: True, report_dir=tmp_path,
                          info=lambda _pid: (True, 100.0))
    with pytest.raises(Refused, match="queue is busy"):
        rename_stale_lock(path, queue_idle=lambda: False, report_dir=tmp_path,
                          info=lambda _pid: (False, None))
    assert path.is_file() and not list(tmp_path.glob("*.stale-*"))


def test_old_lock_with_idle_queue_is_renamed(tmp_path):
    path = tmp_path / "EXECUTOR-RUN-LOCK.json"
    _lock(path, age=3600)
    archived = rename_stale_lock(path, queue_idle=lambda: True, report_dir=tmp_path,
                                 info=lambda _pid: (True, 100.0), max_age_seconds=1800)
    assert archived is not None and archived.exists()


class FakeProbe:
    def __init__(self, started="new"):
        self.started = started

    def state(self, _container):
        return ContainerState(started_at=2.0, started_at_text=self.started, running=True, restart_count=1)

    def fault_lines(self, _container, _since):
        return {}


class FakeClient:
    def __init__(self, present=False):
        self.present = present

    def get(self, path):
        if path == "/queue":
            return {"queue_running": [], "queue_pending": []}
        if path == "/history/p-old":
            return {"p-old": {}} if self.present else {}
        raise AssertionError(f"unexpected fake GET {path}")


def _attempt(tmp_path):
    folder = tmp_path / "h3-r001" / "S02_A"
    receipts = folder / "comfy"
    receipts.mkdir(parents=True)
    (receipts / "dispatch-intent.json").write_text(json.dumps({
        "graph_sha256": "a" * 64, "created_at": 1.0,
        "container_instance": {"started_at_text": "old"}}), encoding="utf-8")
    (receipts / "submitted.json").write_text(json.dumps({"prompt_id": "p-old"}), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    settings = ComfySettings(base_url="http://fake.invalid", lock_path=tmp_path / "gpu.lock",
                             input_dir=tmp_path / "input", output_dir=output, container="fake",
                             lost_recheck_seconds=0, max_lost_retries=1)
    receipt = {"shot": "S02_A", "graph_sha256": "a" * 64}
    graph = {"1": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "h3/S02_A/attempt"}}}
    return folder, settings, receipt, graph


def test_orphan_is_archived_then_fresh_receipt_dir_is_available(tmp_path):
    folder, settings, receipt, graph = _attempt(tmp_path)
    _recover_lost(folder, receipt, graph, settings, FakeClient(), FakeProbe())
    archives = list((folder / "comfy").glob("abandoned-lost-*"))
    assert len(archives) == 1
    assert (archives[0] / "submitted.json").is_file()
    assert json.loads((archives[0] / "LOST.json").read_text())["status"] == "LOST"
    assert not (folder / "comfy" / "submitted.json").exists()
    assert len((folder.parent / "LOST-LEDGER.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("probe,client", [(FakeProbe("old"), FakeClient()),
                                          (FakeProbe(), FakeClient(present=True))])
def test_prompt_without_loss_proof_is_not_archived(tmp_path, probe, client):
    folder, settings, receipt, graph = _attempt(tmp_path)
    _recover_lost(folder, receipt, graph, settings, client, probe)
    assert (folder / "comfy" / "submitted.json").is_file()
    assert not list((folder / "comfy").glob("abandoned-lost-*"))


def test_output_prevents_orphan_resubmit(tmp_path):
    folder, settings, receipt, graph = _attempt(tmp_path)
    output = settings.output_dir / "h3" / "S02_A"
    output.mkdir(parents=True)
    (output / "attempt_00001_.mp4").write_bytes(b"fake-output")
    _recover_lost(folder, receipt, graph, settings, FakeClient(), FakeProbe())
    assert (folder / "comfy" / "submitted.json").is_file()


def test_lost_retry_budget_is_enforced(tmp_path):
    folder, settings, receipt, graph = _attempt(tmp_path)
    settings = settings.with_overrides(max_lost_retries=0)
    with pytest.raises(Uncertain, match="retry budget exhausted"):
        _recover_lost(folder, receipt, graph, settings, FakeClient(), FakeProbe())
    assert (folder / "comfy" / "submitted.json").is_file()
