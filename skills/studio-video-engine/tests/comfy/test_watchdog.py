"""CPU-only behavioral tests; isolated import also works with python -I."""
import json
import sys
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Lock

import pytest

sys.dont_write_bytecode = True
from engine.comfy import run_watchdog as watchdog
Caps, Pollers, Watchdog = watchdog.Caps, watchdog.Pollers, watchdog.Watchdog


@pytest.fixture
def tmp_path(request):
    # Windows Python 3.14's mode=0700 pytest temp ACL is inaccessible in this
    # sandbox. Default inherited ACLs work; retain artifacts (user: no delete).
    base = Path(request.config.getoption("basetemp"))
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True)
    return path


class Fake:
    def __init__(self, tmp_path, **caps):
        self.now, self.ram, self.vram, self.epoch = 0.0, 1024, 100, "epoch-1"
        self.running, self.pending = ["ours"], ["later", "foreign"]
        self.calls, self.reads = [], 0
        self.path = tmp_path / "terminal.json"
        self.latch_path = tmp_path / "terminal-latch.json"
        self.lock = Lock()
        self.errors = set()
        self.caps = replace(Caps(), **caps)

    def poll(self, name, value):
        if name in self.errors:
            raise OSError(name + " unavailable")
        return value

    def queue(self):
        self.reads += 1
        return self.poll("queue", {"queue_running": [[0, p] for p in self.running],
                                   "queue_pending": [[0, p] for p in self.pending]})

    def action(self, name, ids=()):
        # Observable ordering: terminal latch is already persisted before action.
        assert self.w.status == "FAIL"
        assert json.loads(self.path.read_text())["execution_status"] == "FAIL"
        assert watchdog.read_latch(self.latch_path, run_id="test-run")["execution_status"] == "FAIL"
        self.calls.append((name, list(ids)))
        if name == "interrupt":
            self.running = []
        else:
            self.pending = [p for p in self.pending if p not in ids]

    def sleep(self, seconds):
        self.now += seconds

    def build(self, **kwargs):
        self.w = Watchdog(
            pollers=Pollers(lambda: self.poll("ram", self.ram),
                            lambda: self.poll("vram", self.vram), self.queue,
                            lambda: self.poll("epoch", self.epoch)),
            interrupt=lambda: self.action("interrupt"),
            delete_pending=lambda ids: self.action("delete", ids), receipt_path=self.path,
            latch_path=self.latch_path, container_id="container-1", gate=lambda: self.lock,
            run_id="test-run", prompt_ids={"ours", "later"}, expected_started_at="epoch-1",
            caps=self.caps, clock=lambda: self.now, sleep=self.sleep,
            utc=lambda: "2026-10-31T00:00:00+00:00", **kwargs)
        return self.w


def assert_failure(fake, result, reason, measured, cap):
    assert result["execution_status"] == "FAIL"
    event = next(e for e in result["events"] if e["reason"] == reason)
    assert (event["measured"], event["cap"]) == (measured, cap)
    assert result["timestamp"] == "2026-10-31T00:00:00+00:00"
    assert result["dispatch_allowed"] is False
    assert result["cleanup_status"] == "CONFIRMED"
    assert fake.calls == [("interrupt", []), ("delete", ["later"])]
    assert fake.pending == ["foreign"]
    assert json.loads(fake.path.read_text()) == result
    assert not list(fake.path.parent.glob("*.tmp"))


def test_ram_breach_interrupts_deletes_and_writes_fail_receipt(tmp_path):
    f = Fake(tmp_path)
    f.ram = 25_769_803_776  # Independent literal protects exact GiB boundary.
    result = f.build().run(lambda: True)
    assert_failure(f, result, "ram_bytes", 25_769_803_776, 25_769_803_776)
    assert f.w.run(lambda: True) is result  # Terminal reentry cannot act again.
    assert len(f.calls) == 2


def test_vram_breach_interrupts_deletes_and_writes_fail_receipt(tmp_path):
    f = Fake(tmp_path)
    f.vram = 14501
    assert_failure(f, f.build().run(lambda: False), "vram_mib", 14501, 14500)


@pytest.mark.parametrize("seconds", [300, 900])
def test_model_deadline_interrupts_deletes_and_writes_fail_receipt(tmp_path, seconds):
    f = Fake(tmp_path, deadline_seconds=seconds)
    w = f.build()
    f.now = seconds
    assert_failure(f, w.run(lambda: True), "deadline", seconds, seconds)


def test_total_deadline_includes_prior_models(tmp_path):
    f = Fake(tmp_path, deadline_seconds=900)
    f.now = 2099.5
    w = f.build(started_monotonic=2099.5, total_started_monotonic=0)
    result = w.run(lambda: False)
    assert f.now == 2100
    assert_failure(f, result, "total_deadline", 2100, 2100)
    assert [e["reason"] for e in result["events"]] == ["total_deadline"]
    assert f.now - w.start == 0.5 < w.caps.deadline_seconds


@pytest.mark.parametrize("source", ["ram", "vram", "queue", "epoch"])
def test_telemetry_loss_fails_closed(tmp_path, source):
    f = Fake(tmp_path, telemetry_loss_polls=3)
    f.errors = {source}
    result = f.build().run(lambda: True)
    assert f.now == 1.0
    assert result["execution_status"] == "FAIL"
    assert result["events"][0] == {"reason": "telemetry_loss", "measured": 3, "cap": 3, "unit": "polls"}
    if source in {"queue", "epoch"}:
        assert f.calls == []
        assert result["cleanup_status"] == "UNCONFIRMED"
    else:
        assert result["cleanup_status"] == "CONFIRMED"


def test_container_restart_writes_lost_even_with_simultaneous_ram_breach(tmp_path):
    f = Fake(tmp_path)
    w = f.build()
    f.epoch, f.ram = "epoch-2", 25_769_803_776
    result = w.run(lambda: True)
    assert result["execution_status"] == "LOST"
    assert result["qualification_status"] == "NOT_QUALIFIED"
    assert result["expected_started_at"] == "epoch-1"
    assert result["samples"]["started_at"] == "epoch-2"
    assert [e["reason"] for e in result["events"]] == ["container_restart", "ram_bytes"]
    assert f.calls == []
    assert json.loads(f.path.read_text()) == result


def test_normal_completion_at_safe_boundaries_no_action(tmp_path):
    f = Fake(tmp_path)
    f.ram, f.vram = 25_769_803_775, 14500
    result = f.build().run(lambda: f.now >= 1)
    assert f.now == 1
    assert result["execution_status"] == "COMPLETED"
    assert f.calls == []
    assert not f.path.exists()


def test_empty_queue_does_not_complete_stitch_deadline_still_applies(tmp_path):
    f = Fake(tmp_path, deadline_seconds=1)
    f.running, f.pending = [], []
    result = f.build().run(lambda: False)
    assert result["execution_status"] == "FAIL"
    assert result["events"][0]["reason"] == "deadline"
    assert f.now == 1


def test_foreign_or_changed_running_prompt_never_interrupts(tmp_path):
    f = Fake(tmp_path)
    w = f.build()
    f.ram, f.running = 25_769_803_776, ["foreign"]
    result = w.run(lambda: False)
    assert f.calls == [("delete", ["later"])]
    assert result["cleanup_status"] == "CONFIRMED"


def test_restart_during_cleanup_never_interrupts_new_instance(tmp_path):
    f = Fake(tmp_path)
    w = f.build()
    original = f.queue

    def racing_queue():
        if f.reads == 1:
            f.epoch = "epoch-2"
        return original()

    w.pollers = replace(w.pollers, queue=racing_queue)
    f.ram = 25_769_803_776
    result = w.run(lambda: False)
    assert result["cleanup_status"] == "UNCONFIRMED"
    assert result["execution_status"] == "LOST"
    assert result["cleanup_observed_started_at"] == "epoch-2"
    assert result["events"][-1]["reason"] == "container_restart"
    assert f.calls == []


def test_cleanup_exception_still_deletes_owned_pending_and_remains_fail(tmp_path):
    f = Fake(tmp_path)
    w = f.build()
    w.interrupt = lambda: (_ for _ in ()).throw(OSError("interrupt failed"))
    f.ram = 25_769_803_776
    result = w.run(lambda: False)
    assert result["execution_status"] == "FAIL"
    assert result["cleanup_status"] == "UNCONFIRMED"
    assert result["cleanup_errors"]
    assert f.calls == [("delete", ["later"])]


@pytest.mark.parametrize("metric", [float("nan"), float("inf"), -1, True, "24 GiB"])
def test_invalid_metric_is_telemetry_loss(tmp_path, metric):
    f = Fake(tmp_path, telemetry_loss_polls=1)
    f.ram = metric
    result = f.build().run(lambda: True)
    assert result["events"][0]["reason"] == "telemetry_loss"


def test_slow_telemetry_fails_stale_cap(tmp_path):
    f = Fake(tmp_path)
    w = f.build()

    def slow_ram():
        f.now += 1.1
        return 1024

    w.pollers = replace(w.pollers, ram_bytes=slow_ram)
    result = w.run(lambda: True)
    assert "freshness" in result["telemetry_errors"]


@pytest.mark.parametrize("failed_target", ["latch", "receipt"])
def test_persistence_write_failure_stops_runner_before_cleanup(tmp_path, monkeypatch, failed_target):
    f = Fake(tmp_path)
    w = f.build()
    w.interrupt = lambda: f.calls.append(("interrupt", []))
    w.delete_pending = lambda ids: f.calls.append(("delete", ids))

    original = watchdog.write_receipt_atomic

    def fail_write(path, body):
        if path == (f.latch_path if failed_target == "latch" else f.path):
            raise OSError("disk full")
        return original(path, body)

    monkeypatch.setattr(watchdog, "write_receipt_atomic", fail_write)
    f.ram = 25_769_803_776
    with pytest.raises(watchdog.PersistenceError, match="runner stopped") as caught:
        w.run(lambda: False)
    assert isinstance(caught.value.__cause__, OSError)
    assert w.status == "FAIL"
    assert len(w.receipt["receipt_errors"]) == 1
    assert f.calls == []
    assert w.receipt["cleanup_status"] == "UNCONFIRMED"
    assert not f.path.exists()
    assert f.latch_path.exists() is (failed_target == "receipt")
    with pytest.raises(watchdog.PersistenceError):
        w.run(lambda: True)
    assert f.calls == []


def test_existing_receipt_is_preserved(tmp_path):
    f = Fake(tmp_path)
    f.path.write_text('{"execution_status":"LOST"}')
    with pytest.raises(FileExistsError):
        f.build()
    assert json.loads(f.path.read_text())["execution_status"] == "LOST"


def test_completion_callback_failure_fails_closed(tmp_path):
    f = Fake(tmp_path)

    def unavailable():
        raise OSError("history unavailable")

    result = f.build().run(unavailable)
    assert_failure(f, result, "telemetry_loss", 2, 2)
    assert "completion" in result["telemetry_errors"]


def write_test_latch(f, status="FAIL"):
    return watchdog.latch_terminal(f.latch_path, run_id="test-run",
        execution_status=status, reason="ram_bytes", timestamp="2026-10-31T00:00:00+00:00",
        monotonic=f.now, container_epoch=f.epoch, container_id="container-1",
        evidence={"ram_bytes": f.ram})


def test_latch_written_under_gate_before_interrupt_and_delete(tmp_path, monkeypatch):
    f = Fake(tmp_path)
    order = []

    @contextmanager
    def gate():
        with f.lock:
            order.append("gate-enter")
            try:
                yield
            finally:
                order.append("gate-exit")

    w = f.build()
    w.gate = gate
    original = watchdog.write_receipt_atomic

    def observe_write(path, body):
        if path == f.latch_path:
            assert f.lock.locked()
        original(path, body)
        order.append("latch" if path == f.latch_path else "receipt")

    monkeypatch.setattr(watchdog, "write_receipt_atomic", observe_write)
    action = f.action

    def observe_action(name, ids=()):
        # Do not rely only on assertions in callbacks (cleanup catches errors).
        order.append(name)
        action(name, ids)

    w.interrupt = lambda: observe_action("interrupt")
    w.delete_pending = lambda ids: observe_action("delete", ids)
    f.ram = 25_769_803_776
    result = w.run(lambda: False)
    assert result["cleanup_status"] == "CONFIRMED"
    assert order == ["gate-enter", "latch", "gate-exit", "receipt",
                     "interrupt", "delete", "gate-enter", "latch", "gate-exit", "receipt"]


def test_dispatch_gate_read_sees_shared_terminal_latch(tmp_path):
    f = Fake(tmp_path)
    f.ram = 25_769_803_776
    f.build().run(lambda: False)
    with f.lock:  # Same gate that the dispatcher integration must hold over POST.
        body = watchdog.read_latch(f.latch_path, run_id="test-run")
        assert watchdog.is_latched(f.latch_path, run_id="test-run") is True
    assert body["schema"] == "jjv/comfy-terminal-latch/v1"
    assert body["version"] == 1
    assert body["execution_status"] == "FAIL"
    assert body["qualification_status"] == "NOT_QUALIFIED"
    assert body["container_id"] == "container-1"
    assert body["container_epoch"] == "epoch-1"
    assert body["reason"] == "ram_bytes"
    assert body["evidence"]["events"][0]["measured"] == 25_769_803_776


def test_absent_latch_is_not_an_active_guard(tmp_path):
    f = Fake(tmp_path)
    assert watchdog.read_latch(f.latch_path, run_id="test-run") is None
    assert watchdog.is_latched(f.latch_path, run_id="test-run") is False


@pytest.mark.parametrize("data", ["{", "{}", '{"execution_status":"ACTIVE"}'])
def test_corrupt_latch_refuses_read_and_runner_start(tmp_path, data):
    f = Fake(tmp_path)
    f.latch_path.write_text(data)
    with pytest.raises(watchdog.LatchReadError):
        watchdog.is_latched(f.latch_path, run_id="test-run")
    with pytest.raises(watchdog.LatchReadError):
        f.build()
    assert f.latch_path.read_text() == data


def test_existing_latch_refuses_start_without_clearing(tmp_path):
    f = Fake(tmp_path)
    with f.lock:
        write_test_latch(f)
    original = f.latch_path.read_bytes()
    with pytest.raises(watchdog.TerminalLatchRefused):
        f.build()
    assert f.latch_path.read_bytes() == original


def test_terminal_is_monotonic_and_keeps_both_evidence_sets(tmp_path):
    f = Fake(tmp_path)
    with f.lock:
        write_test_latch(f)
        f.epoch = "epoch-2"
        write_test_latch(f, "LOST")
        write_test_latch(f, "FAIL")
    body = watchdog.read_latch(f.latch_path, run_id="test-run")
    assert body["execution_status"] == "LOST"
    assert body["previous"]["execution_status"] == "LOST"
    assert body["previous"]["previous"]["execution_status"] == "FAIL"
    original = f.latch_path.read_bytes()
    with pytest.raises(watchdog.LatchReadError):
        write_test_latch(f, "ACTIVE")
    assert f.latch_path.read_bytes() == original
    with pytest.raises(watchdog.LatchReadError):
        watchdog.read_latch(f.latch_path, run_id="another-run")


def test_latch_write_uses_fsync_before_replace(tmp_path, monkeypatch):
    f = Fake(tmp_path)
    order = []
    original_sync, original_replace = watchdog.os.fsync, watchdog.os.replace

    def sync(fd):
        order.append("fsync")
        original_sync(fd)

    def replace_file(src, dst):
        assert src.parent == dst.parent == f.latch_path.parent
        assert src != dst
        assert json.loads(src.read_text())["execution_status"] == "FAIL"
        order.append("replace")
        original_replace(src, dst)

    monkeypatch.setattr(watchdog.os, "fsync", sync)
    monkeypatch.setattr(watchdog.os, "replace", replace_file)
    with f.lock:
        write_test_latch(f)
    assert order[:2] == ["fsync", "replace"]


def test_latch_replace_failure_keeps_previous_terminal(tmp_path, monkeypatch):
    f = Fake(tmp_path)
    with f.lock:
        write_test_latch(f)
    original = f.latch_path.read_bytes()

    def fail_replace(*args):
        raise OSError("replace failed")

    monkeypatch.setattr(watchdog.os, "replace", fail_replace)
    with f.lock, pytest.raises(OSError, match="replace failed"):
        write_test_latch(f, "LOST")
    assert f.latch_path.read_bytes() == original


def test_cleanup_persistence_failure_is_not_swallowed(tmp_path, monkeypatch):
    f = Fake(tmp_path)
    w = f.build()
    original_queue, original_write = f.queue, watchdog.write_receipt_atomic

    def racing_queue():
        if f.reads == 1:
            f.epoch = "epoch-2"
        return original_queue()

    def fail_lost(path, body):
        if body["execution_status"] == "LOST":
            raise OSError("disk full after restart")
        original_write(path, body)

    w.pollers = replace(w.pollers, queue=racing_queue)
    monkeypatch.setattr(watchdog, "write_receipt_atomic", fail_lost)
    f.ram = 25_769_803_776
    with pytest.raises(watchdog.PersistenceError):
        w.run(lambda: False)
    assert w.status == "LOST"
    assert f.calls == []


def test_operator_clear_requires_stopped_reconciled_and_preserves_latch(tmp_path):
    f = Fake(tmp_path)
    with f.lock:
        write_test_latch(f)
    original = f.latch_path.read_bytes()
    args = dict(run_id="test-run", operator="test-operator", reason="queue reconciled",
                runner_stopped=True, watchdog_stopped=True, ownership_reconciled=True,
                gate=lambda: f.lock)
    for field in ("runner_stopped", "watchdog_stopped", "ownership_reconciled"):
        with pytest.raises(ValueError):
            watchdog._operator_clear_latch(f.latch_path, **{**args, field: False})
        assert f.latch_path.read_bytes() == original
    archive = watchdog._operator_clear_latch(f.latch_path, **args)
    assert not f.latch_path.exists()
    assert archive.read_bytes() == original
    audit = json.loads(archive.with_name(archive.name + ".operator.json").read_text())
    assert audit["operator"] == "test-operator"


# ---- operator clear: chỉ qua CLI, --confirm phải bằng --run-id -----------------------------------
def _latched_run(tmp_path):
    run_dir = tmp_path / "pilot-runs" / "run-9"
    run_dir.mkdir(parents=True)
    latch = run_dir / "terminal-latch.json"
    with watchdog.file_gate(run_dir / "terminal-latch.gate", timeout=1.0):
        watchdog.latch_terminal(latch, run_id="run-9", execution_status="FAIL", reason="ram_bytes",
                                timestamp="t", monotonic=1.0, container_epoch="e", container_id="c", evidence={})
    return run_dir, latch


def _clear(tmp_path, **over):
    from engine.comfy import run_watchdog as w
    args = dict(runs_root=tmp_path / "pilot-runs", run_id="run-9", confirm="run-9", reason="reconciled",
                runner_stopped=True, watchdog_stopped=True, ownership_reconciled=True, operator="tester")
    return w.cli_clear_latch(**{**args, **over})


def test_cli_clear_refuses_unless_confirm_equals_run_id(tmp_path):
    run_dir, latch = _latched_run(tmp_path)
    for bad in ("", "run-8", "RUN-9", " run-9"):
        with pytest.raises(watchdog.ClearRefused):
            _clear(tmp_path, confirm=bad)
    assert latch.exists(), "latch phải còn nguyên khi từ chối"
    assert not list(run_dir.glob("*.archived*"))


def test_cli_clear_archives_and_records_who_and_when(tmp_path):
    run_dir, latch = _latched_run(tmp_path)
    archive = _clear(tmp_path)
    assert not latch.exists() and archive.exists()
    receipt = json.loads(Path(str(archive) + ".operator.json").read_text())
    assert receipt["operator"] == "tester" and receipt["run_id"] == "run-9" and receipt["timestamp"]
    assert receipt["confirm"] == "run-9"


def test_cli_clear_defaults_operator_to_os_user_and_rejects_path_run_id(tmp_path):
    _latched_run(tmp_path)
    with pytest.raises(watchdog.ClearRefused):
        _clear(tmp_path, run_id="../run-9", confirm="../run-9")
    archive = _clear(tmp_path, operator=None)
    assert json.loads(Path(str(archive) + ".operator.json").read_text())["operator"].strip()


def test_public_api_does_not_expose_unguarded_clear():
    assert not hasattr(watchdog, "operator_clear_latch")


def test_jjv_cli_verb_refuses_bad_confirm_and_clears_with_good_one(tmp_path):
    import subprocess
    run_dir, latch = _latched_run(tmp_path)
    base = [sys.executable, "-I", str(Path(__file__).resolve().parents[2] / "bin" / "jjv.py"), "comfy", "watchdog",
            "clear", "--run-id", "run-9", "--reason", "r", "--runs-root", str(tmp_path / "pilot-runs"),
            "--runner-stopped", "--watchdog-stopped", "--ownership-reconciled", "--operator", "tester"]
    bad = subprocess.run(base + ["--confirm", "nope"], capture_output=True, text=True)
    assert bad.returncode == 1 and latch.exists() and "refused" in bad.stdout
    good = subprocess.run(base + ["--confirm", "run-9"], capture_output=True, text=True)
    assert good.returncode == 0, good.stdout + good.stderr
    assert not latch.exists()
