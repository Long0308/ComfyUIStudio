"""T-E30: single-executor guard (PID + start time + host run lock) and its use by the executor."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.cli_runtime import add_runtime_parsers
from engine.core.errors import Refused
from engine.core.runlock import process_info, run_pid_lock
from exec_fixtures import make_rig
from fake_comfy import FakeComfy

HOST = socket.gethostname()


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def write_lock(path: Path, **values) -> None:
    body = {"schema": "jjv/run-lock/v1", "pid": 1, "host": HOST, "process_start_time": None,
            "acquired_at": 1.0, "token": "other", **values}
    path.write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture()
def sleeper():
    """A genuinely live process on this host."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        yield child
    finally:
        child.kill()
        child.wait()


@pytest.fixture()
def dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


# ---- the lock itself ---------------------------------------------------------------------
def test_process_info_sees_this_process_and_a_dead_one(dead_pid) -> None:
    alive, start = process_info(os.getpid())
    assert alive and (start is None or abs(start - time.time()) < 86400)
    assert process_info(dead_pid)[0] is False


def test_lock_is_created_with_pid_start_time_and_host_and_removed_on_exit(tmp_path) -> None:
    path = tmp_path / "RUN-LOCK.json"
    with run_pid_lock(path) as body:
        on_disk = json.loads(path.read_text())
        assert on_disk["pid"] == os.getpid() and on_disk["host"] == HOST and on_disk["token"] == body["token"]
        assert "process_start_time" in on_disk and on_disk["acquired_at"] > 0
    assert not path.exists()


def test_lock_removed_even_when_the_body_raises(tmp_path) -> None:
    path = tmp_path / "RUN-LOCK.json"
    with pytest.raises(RuntimeError):
        with run_pid_lock(path):
            raise RuntimeError("boom")
    assert not path.exists()


def test_a_live_holder_is_refused_and_never_broken_even_with_break_stale(tmp_path, sleeper) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, pid=sleeper.pid, process_start_time=process_info(sleeper.pid)[1])
    for flag in (False, True):
        with pytest.raises(Refused, match="another executor is running"):
            with run_pid_lock(path, break_stale=flag):
                pytest.fail("a live holder must never be displaced")
    assert json.loads(path.read_text())["token"] == "other"


def test_a_stale_lock_is_reported_and_needs_the_flag(tmp_path, dead_pid) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, pid=dead_pid)
    with pytest.raises(Refused, match="STALE.*--break-stale-lock"):
        with run_pid_lock(path):
            pytest.fail("must not start on a stale lock without the flag")
    assert json.loads(path.read_text())["token"] == "other", "left in place"
    with run_pid_lock(path, break_stale=True) as body:
        assert json.loads(path.read_text())["token"] == body["token"]
    (report,) = tmp_path.glob("stale-lock-*.json")
    saved = json.loads(report.read_text())
    assert saved["lock"]["pid"] == dead_pid and saved["why"] == "pid is not running"
    assert not path.exists()


def test_a_reused_pid_with_a_different_start_time_counts_as_stale(tmp_path) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, pid=4242, process_start_time=1000.0)
    live_but_new = lambda pid: (True, 999999.0)  # noqa: E731 - same pid, a much later process
    with pytest.raises(Refused, match="STALE.*different process"):
        with run_pid_lock(path, info=live_but_new):
            pass
    with run_pid_lock(path, info=live_but_new, break_stale=True):
        pass


def test_other_host_and_unreadable_locks_are_never_broken(tmp_path) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, host="some-other-machine", pid=999999)
    with pytest.raises(Refused, match="another host"):
        with run_pid_lock(path, break_stale=True):
            pass
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(Refused, match="unreadable"):
        with run_pid_lock(path, break_stale=True):
            pass
    assert path.read_text() == "{not json"


def test_the_lock_is_not_removed_if_someone_else_replaced_it(tmp_path) -> None:
    path = tmp_path / "RUN-LOCK.json"
    with run_pid_lock(path):
        write_lock(path, token="intruder")
    assert json.loads(path.read_text())["token"] == "intruder"


# ---- the executor uses it ----------------------------------------------------------------
def test_a_second_executor_is_refused_before_anything_is_sent(fake, tmp_path, sleeper) -> None:
    rig = make_rig(tmp_path, fake)
    runs = rig.plan.root / "runs"
    runs.mkdir(parents=True)
    write_lock(runs / "RUN-LOCK.json", pid=sleeper.pid, process_start_time=process_info(sleeper.pid)[1])
    with pytest.raises(Refused, match="another executor is running"):
        rig.executor().run(rig.tasks(max_chunks=1), break_stale_lock=True)
    assert fake.requests == [] and not (runs / "run-state.json").exists()


def test_stale_lock_stops_the_executor_until_break_stale_lock(fake, tmp_path, dead_pid) -> None:
    rig = make_rig(tmp_path, fake)
    runs = rig.plan.root / "runs"
    runs.mkdir(parents=True)
    write_lock(runs / "RUN-LOCK.json", pid=dead_pid)
    with pytest.raises(Refused, match="STALE"):
        rig.executor().run(rig.tasks(max_chunks=1))
    assert fake.requests == []
    result = rig.executor().run(rig.tasks(max_chunks=1), break_stale_lock=True)
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1
    assert list(runs.glob("stale-lock-*.json")) and not (runs / "RUN-LOCK.json").exists()


def test_lock_is_held_during_the_run_and_released_after(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    lock = rig.plan.root / "runs" / "RUN-LOCK.json"
    seen: list[dict] = []
    previous = fake.on_post

    def watch(payload, prompt_id):
        seen.append(json.loads(lock.read_text()))
        return previous(payload, prompt_id)

    fake.on_post = watch
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    assert seen and seen[0]["pid"] == os.getpid() and seen[0]["host"] == HOST
    assert not lock.exists()


def test_dry_run_takes_no_lock(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    rig.executor().dry_run(rig.tasks(max_chunks=1))
    assert not (rig.plan.root / "runs").exists()


def test_cli_accepts_break_stale_lock() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    stages = parser.add_subparsers(dest="stage")
    seedvr2 = stages.add_parser("seedvr2")
    verbs = seedvr2.add_subparsers(dest="verb")
    add_runtime_parsers(stages, verbs)
    args = parser.parse_args(["seedvr2", "execute", "--episode", "e", "--plan", "p", "--break-stale-lock"])
    assert args.break_stale_lock is True
    assert parser.parse_args(["seedvr2", "execute", "--episode", "e", "--plan", "p"]).break_stale_lock is False
