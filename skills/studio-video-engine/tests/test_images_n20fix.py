"""N20-fix2: the images engine's locks are OS-level locks (no orphan to reclaim): real multi-process races give 0
overlaps, a hard-killed holder frees the lock at once, a stale holder note never blocks, refusals do not claim a live
process, cooling is re-read after the label lock, mark_good only after register. FAKE codex only."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from engine.core.errors import Refused, Uncertain
from engine.images import codex, pool
from engine.images.lease import lease, side_lock_path
from test_images_codex import Setup, no_auth_reads  # noqa: F401

SKILL = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).with_name("lease_worker.py")


def dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def write_stale_holder(lock: Path, pid: int) -> None:
    """What a killed process of the OLD lock left behind (lock body + holder note): must not matter any more."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": pid, "host": socket.gethostname(), "created_unix": time.time() - 5, "token": "orphan"})
    lock.write_text(body, encoding="ascii")
    lock.with_name(lock.name + ".holder").write_text(body, encoding="ascii")


def takes(setup: Setup) -> list[str]:
    folder = setup.out / "S01_A" / "codex-exec"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def race(tmp: Path, nproc: int, trials: int) -> tuple[int, int, list[str]]:
    overlaps, entered, errors = 0, 0, []
    for trial in range(trials):
        folder = tmp / f"race-{nproc}-{trial}"
        folder.mkdir(parents=True)
        lock, out = folder / "x.lock", folder / "out.jsonl"
        write_stale_holder(lock, dead_pid())  # the orphan the N56 experiment fought over
        start = time.time() + 2.5
        procs = [subprocess.Popen([sys.executable, str(WORKER), str(SKILL), "race", str(lock), str(out), str(start), "0.15"])
                 for _ in range(nproc)]
        for proc in procs:
            proc.wait()
        records = [json.loads(line) for line in out.read_text().splitlines()]
        errors += [r["err"] for r in records if "err" in r]
        ok = sorted((r for r in records if "enter" in r), key=lambda r: r["enter"])
        entered += len(ok)
        overlaps += sum(1 for a, b in zip(ok, ok[1:]) if b["enter"] < a["exit"])
    return overlaps, entered, errors


@pytest.mark.parametrize("nproc", [3, 6])
def test_real_processes_fighting_over_an_orphan_never_overlap(tmp_path, nproc):
    overlaps, entered, errors = race(tmp_path, nproc, 6)
    assert errors == [] and entered == nproc * 6 and overlaps == 0


def test_a_hard_killed_holder_frees_the_lock_at_once(tmp_path):
    lock, out = tmp_path / "k.lock", tmp_path / "out.jsonl"
    proc = subprocess.Popen([sys.executable, str(WORKER), str(SKILL), "hold", str(lock), str(out), "0", "0"])
    try:
        deadline = time.monotonic() + 20
        while not (out.exists() and out.read_text().strip()) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert out.read_text().strip(), "the holder process never took the lock"
        with pytest.raises(Refused, match="held by another process"):
            with lease(lock, timeout_seconds=0.3, what="probe"):
                pass
    finally:
        proc.kill()
        proc.wait()
    started = time.monotonic()
    with lease(lock, timeout_seconds=1.0, what="probe"):
        pass
    assert time.monotonic() - started < 1.0


def test_refusal_names_the_last_recorded_holder_without_claiming_it_is_live(tmp_path):
    lock = tmp_path / "r.lock"
    message = ""
    with lease(lock, timeout_seconds=1.0, what="demo lock") as mine:
        try:
            with lease(lock, timeout_seconds=0.2, what="demo lock"):
                pass
        except Refused as error:
            message = str(error)
    assert f"pid {mine['pid']}" in message and "last recorded holder" in message and "not verified live" in message
    assert "a live process" not in message and "ComfyUI" not in message


def test_a_stale_holder_note_and_lock_body_never_block(tmp_path):
    lock = tmp_path / "s.lock"
    write_stale_holder(lock, 1)
    started = time.monotonic()
    with lease(lock, timeout_seconds=1.0, what="stale"):
        pass
    assert time.monotonic() - started < 1.0


def test_label_lock_with_a_stale_orphan_is_taken_at_once(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    write_stale_holder(pool.label_lock_path(setup.state, "acct1"), dead_pid())
    started = time.monotonic()
    result = setup.run(account="acct1")
    assert time.monotonic() - started < 2.0 and result["account_label"] == "acct1"


def test_label_lock_held_by_a_live_lane_is_refused_without_an_empty_take(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    monkeypatch.setattr(codex, "LOCK_EXTRA_SECONDS", 0.0)
    with pool.locked(pool.label_lock_path(setup.state, "acct1"), timeout_seconds=1):
        with pytest.raises(Refused) as caught:
            setup.run(account="acct1", timeout=0.5)
    message = str(caught.value)
    assert "codex image label lock acct1 is held by another process" in message and "ComfyUI" not in message
    assert takes(setup) == [] and not setup.calls("acct1")


def test_orphan_state_lock_is_taken_at_once(tmp_path):
    setup = Setup(tmp_path)
    write_stale_holder(setup.state.with_suffix(".lock"), dead_pid())
    started = time.monotonic()
    pool.update_state(setup.state, lambda st: pool.mark_good(st, "acct1", 1.0))
    assert time.monotonic() - started < 2.0 and pool.load_state(setup.state)["last_good"] == "acct1"


def test_orphan_publish_lock_is_taken_at_once(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    write_stale_holder(side_lock_path(setup.world.root, "publish"), dead_pid())  # also: nothing is left in the episode tree
    before = sorted(p.name for p in setup.world.root.rglob("*"))
    started = time.monotonic()
    result = setup.run(account="acct1")
    assert time.monotonic() - started < 2.0 and Path(result["receipt"]).is_file()
    assert not any(".lock" in n or ".holder" in n for n in sorted(p.name for p in setup.world.root.rglob("*")) if n not in before)


def test_mark_good_only_after_register_succeeded(tmp_path, monkeypatch, no_auth_reads):
    setup = Setup(tmp_path)

    def refuse(*a, **k):
        raise Refused("register refused")

    monkeypatch.setattr(codex, "register", refuse)
    with pytest.raises(Refused, match="register refused"):
        setup.run(account="acct1")
    assert not setup.state.exists() or pool.load_state(setup.state)["last_good"] is None


def test_cooling_is_re_read_after_the_label_lock_so_a_queued_lane_does_not_hit_the_wall(tmp_path, no_auth_reads):
    setup = Setup(tmp_path)
    lock = pool.label_lock_path(setup.state, "acct1")
    outcome: dict = {}

    def queued():
        try:
            outcome["r"] = setup.run(account="acct1", timeout=30)
        except BaseException as error:  # reported to the main thread
            outcome["r"] = error

    with pool.locked(lock, timeout_seconds=5):  # lane A holds acct1
        thread = threading.Thread(target=queued)
        thread.start()
        time.sleep(0.6)  # lane B has computed its order (acct1 fine) and now waits for the lock
        pool.update_state(setup.state, lambda st: pool.mark_cooling(st, "acct1", setup.clock[0] + 9999, "quota", setup.clock[0]))
    thread.join(20)
    assert isinstance(outcome["r"], Uncertain), outcome
    assert not setup.calls("acct1"), "the queued lane must not run codex on a cooled account"
