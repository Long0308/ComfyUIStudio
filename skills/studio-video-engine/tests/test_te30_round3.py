"""T-E30 round 3: one test per re-critic finding (F-A .. F-E).  Fakes only: no docker, no real ComfyUI, no GPU.

F-A an UNREADABLE output root / prefix folder is not "no output"      F-D lock-break OS errors become Refused; contention
F-B UNCERTAIN must stop (no dispatch without a StartedAt; K stalls)   F-E the ledger check must not block COMPLETED resume
F-C redaction: JSON/quoted keys, URL userinfo, Basic auth, file names stay readable
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

import engine.core.runlock as runlock_mod
from engine.comfy.client import ComfyClient
from engine.comfy.docker_probe import DockerProbe, redact_line
from engine.comfy.lost import LOST, UNCERTAIN, Classification, classify_lost, outputs_with_prefix
from engine.comfy.watchdog import MAX_CONSECUTIVE_UNCERTAIN, StallWatchdog, UncertainStall
from engine.core.errors import Refused
from engine.core.runlock import run_pid_lock
from exec_fixtures import FakeDocker, make_rig
from fake_comfy import FakeComfy

PREFIX = "episodes/x/S01_A/chunk-0000"
SUB = PREFIX.rsplit("/", 1)[0]
HOST = socket.gethostname()


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def fast(rig, **overrides):
    values = {"stall_factor": 1.0, "expected_chunk_seconds": 0.06, "lost_recheck_seconds": 0.01,
              "poll_seconds": 0.01, **overrides}
    rig.settings = rig.settings.with_overrides(**values)
    rig.settings.output_dir.mkdir(parents=True, exist_ok=True)
    return rig


def archives(rig, index=0):
    return sorted(p for p in rig.chunk_dir(index).glob("abandoned-lost-*") if p.is_dir())


def classify(fake, output_dir):
    docker = FakeDocker()
    docker.restart()
    return classify_lost(client=ComfyClient(fake.url, timeout_seconds=5), probe=docker, container="c",
                         dispatch_time=1.0, output_dir=output_dir, output_prefix=PREFIX,
                         dispatch_instance={"started_at_text": FakeDocker.BEFORE}, prompt_id="p1",
                         recheck_seconds=0.0, sleep=lambda s: None)


# ---- F-A: only FileNotFoundError means "absent" -------------------------------------------
def deny_stat(monkeypatch, denied: Path) -> None:
    real = os.stat

    def stat(path, *args, **kwargs):
        if Path(os.fspath(path)) == denied:
            raise PermissionError(13, "Access is denied (simulated)", os.fspath(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)


def test_fa_unreadable_output_root_is_uncertain(fake, tmp_path, monkeypatch) -> None:
    root = tmp_path / "out"
    root.mkdir()
    deny_stat(monkeypatch, root)
    result = classify(fake, root)
    assert result.verdict == UNCERTAIN, result.reasons
    with pytest.raises(PermissionError):
        outputs_with_prefix(root, PREFIX)


def test_fa_unreadable_prefix_folder_is_uncertain(fake, tmp_path, monkeypatch) -> None:
    root = tmp_path / "out"
    (root / SUB).mkdir(parents=True)
    deny_stat(monkeypatch, root / SUB)
    result = classify(fake, root)
    assert result.verdict == UNCERTAIN, result.reasons
    with pytest.raises(PermissionError):
        outputs_with_prefix(root, PREFIX)


def test_fa_absent_prefix_folder_is_still_absence(fake, tmp_path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    assert outputs_with_prefix(root, PREFIX) == []
    assert classify(fake, root).verdict == LOST


# ---- F-B: UNCERTAIN stops --------------------------------------------------------------------
def test_fb_no_dispatch_without_a_container_startedat(fake, tmp_path) -> None:
    docker = FakeDocker()
    docker.unreadable = True  # docker unreadable when the intent would be written
    rig = fast(make_rig(tmp_path, fake))
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2, result
    assert result["stopped"]["stage"] == "container_instance_unavailable"
    assert fake.posts_made() == [], "nothing was sent"
    assert not (rig.chunk_dir(0) / "dispatch-intent.json").exists(), "no intent either"


def test_fb_watchdog_stops_after_k_consecutive_uncertain_classifications() -> None:
    clock = {"t": 0.0}
    alerts: list[dict] = []
    stops: list[dict] = []
    unsure = Classification(UNCERTAIN, ("docker unreadable",))
    dog = StallWatchdog(stall_seconds=10, fingerprint=lambda: "same", on_alert=alerts.append,
                        classify=lambda: unsure, clock=lambda: clock["t"], on_stop=stops.append)
    clock["t"] = 0.0
    dog.check()  # baseline
    for _ in range(MAX_CONSECUTIVE_UNCERTAIN - 1):
        clock["t"] += 11
        dog.check()
    assert len(alerts) == MAX_CONSECUTIVE_UNCERTAIN - 1 and stops == []
    clock["t"] += 11
    with pytest.raises(UncertainStall) as caught:
        dog.check()
    assert caught.value.exit_code == 2 and caught.value.evidence["stage"] == "stall_uncertain"
    assert len(stops) == 1 and stops[0]["consecutive_uncertain"] == MAX_CONSECUTIVE_UNCERTAIN


def test_fb_a_readable_verdict_resets_the_uncertain_count() -> None:
    clock = {"t": 0.0}
    verdicts = [UNCERTAIN, UNCERTAIN, "NOT_LOST", UNCERTAIN, UNCERTAIN]
    dog = StallWatchdog(stall_seconds=10, fingerprint=lambda: "same", on_alert=lambda body: None,
                        classify=lambda: Classification(verdicts.pop(0), ("x",)), clock=lambda: clock["t"])
    dog.check()
    for _ in range(5):
        clock["t"] += 11
        dog.check()  # never 3 UNCERTAIN in a row -> never raises


def test_fb_executor_stops_early_on_uncertain_stalls_instead_of_waiting_for_the_hard_timeout(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts = 1
    fake.on_lose = lambda: setattr(docker, "unreadable", True)  # the container goes dark after the POST
    rig = fast(make_rig(tmp_path, fake, history_timeout=60.0))
    started = time.monotonic()
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    elapsed = time.monotonic() - started
    assert result["exit_code"] == 2 and result["stopped"]["stage"] == "stall_uncertain", result.get("stopped")
    assert elapsed < 20 and len(fake.posts_made()) == 1 and archives(rig) == []
    incident = json.loads((rig.chunk_dir(0) / "INCIDENT-stall-uncertain.json").read_text())
    assert incident["kind"] == "stall_uncertain" and incident["consecutive_uncertain"] == MAX_CONSECUTIVE_UNCERTAIN
    assert incident["classification"]["verdict"] == "UNCERTAIN" and incident["automatic_resubmit"] is False


# ---- F-D: lock break OS errors, failed restore, contention --------------------------------------
def write_lock(path: Path, **values) -> None:
    body = {"schema": "jjv/run-lock/v1", "pid": 99999, "host": HOST, "process_start_time": None,
            "acquired_at": 1.0, "token": "stale", **values}
    path.write_text(json.dumps(body), encoding="utf-8")


def test_fd_oserror_while_removing_the_stale_lock_is_refused_not_raised(tmp_path, monkeypatch) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path)
    real = Path.unlink

    def unlink(self, *args, **kwargs):
        if self.name == "RUN-LOCK.json":
            raise PermissionError(32, "being used by another process (simulated)")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(Refused, match="could not be removed"):
        with run_pid_lock(path, break_stale=True, info=lambda pid: (False, None), host=HOST):
            pytest.fail("must not take the lock")
    assert json.loads(path.read_text())["token"] == "stale", "the lock is exactly where it was"


def test_fd_a_second_breaker_waits_then_refuses_naming_the_guard(tmp_path, monkeypatch) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path)
    guard = tmp_path / "RUN-LOCK.json.break"
    guard.write_text("someone else is breaking")
    monkeypatch.setattr(runlock_mod, "BREAK_GUARD_SECONDS", 0.1)
    with pytest.raises(Refused, match="breaking run lock") as caught:
        with run_pid_lock(path, break_stale=True, info=lambda pid: (False, None), host=HOST):
            pytest.fail("must not take the lock")
    assert str(guard) in str(caught.value)
    assert json.loads(path.read_text())["token"] == "stale" and guard.exists(), "nothing touched"


def test_fd_a_live_lock_is_never_missing_while_a_break_is_judged(tmp_path) -> None:
    """The break re-reads the lock in place: at no instant is the (replacement) lock file absent."""
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path)
    seen: list[bool] = []
    swapped = {"done": False}

    def racing_info(pid):
        if pid == 99999 and not swapped["done"]:
            swapped["done"] = True
            write_lock(path, pid=os.getpid(), token="fresh-live-token")  # replaced after it was judged
        return False, None

    real_read = runlock_mod._read

    def read(p):
        seen.append(Path(p).exists())
        return real_read(p)

    runlock_mod._read, original = read, runlock_mod._read
    try:
        with pytest.raises(Refused, match="changed while"):
            with run_pid_lock(path, break_stale=True, info=racing_info, host=HOST):
                pytest.fail("must not take the lock")
    finally:
        runlock_mod._read = original
    assert all(seen) and json.loads(path.read_text())["token"] == "fresh-live-token"


def test_fd_six_threads_contend_for_a_stale_lock_without_a_raw_oserror(tmp_path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    path = runs / "RUN-LOCK.json"

    def info(pid):
        return (False, None) if pid == 99999 else (True, 1000.0 + pid)

    bad: list[str] = []
    gate = threading.Lock()
    inside, peak = [0], [0]
    for round_no in range(30):
        write_lock(path, token=f"dead{round_no}")
        barrier = threading.Barrier(6)
        won = []

        def worker(i: int) -> None:
            barrier.wait()
            try:
                with run_pid_lock(path, break_stale=True, info=info, pid=2000 + i, report_dir=runs, host=HOST):
                    with gate:
                        inside[0] += 1
                        peak[0] = max(peak[0], inside[0])
                    time.sleep(0.004)
                    with gate:
                        inside[0] -= 1
                    won.append(i)
            except Refused:
                pass
            except Exception as error:  # noqa: BLE001 - this is the finding: nothing but Refused may escape
                bad.append(f"{type(error).__name__}: {error}"[:200])

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert won, f"round {round_no}: nobody acquired the lock"
    assert not bad, bad[:3]
    assert peak[0] <= 1, "two holders at once"
    assert inside[0] == 0 and not list(runs.glob("*.aside")) and not list(runs.glob("*.break"))
    assert not path.exists(), "the last holder released its lock"


# ---- F-E: the ledger check does not block verifying a COMPLETED chunk --------------------------
def test_fe_resume_still_verifies_a_completed_chunk_after_its_archive_was_deleted(fake, tmp_path) -> None:
    import shutil
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = 1, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 0
    for archive in archives(rig):
        shutil.rmtree(archive)
    posts = len(fake.posts_made())
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 0, result.get("stopped")
    assert len(fake.posts_made()) == posts, "verification only, no POST"


# ---- F-C: redaction ----------------------------------------------------------------------------
@pytest.mark.parametrize("line, secret", [
    ('{"api_key": "hunter2-ABCDEF"} CUDA error: illegal instruction', "hunter2-ABCDEF"),
    ("{'password': 'hunter3 SECRET with spaces'} CUDA error", "hunter3 SECRET"),
    ("GET /x?token=abc123SECRET&x=1 CUDA error", "abc123SECRET"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA== CUDA error", "dXNlcjpwYXNzd29yZA=="),
    ("authorization: Digest username=bob,response=abcdef0123456789abcdef CUDA error", "abcdef0123456789abcdef"),
    ("https://user:pa55w0rdXYZ@host/x CUDA error", "pa55w0rdXYZ"),
    ("https://TOKENONLYabc123@host/x CUDA error", "TOKENONLYabc123"),
    ("password='hunter3SECRET' CUDA error", "hunter3SECRET"),
    ("sk-proj-AAAA1111BBBB2222CCCC CUDA error", "AAAA1111BBBB2222CCCC"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123456789 CUDA error", "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("X-Api-Key: zzz9SECRETvalue CUDA error", "zzz9SECRETvalue"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r CUDA error",
     "eyJzdWIiOiIxMjM0NTY3ODkwIn0"),
    ("blob QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789+/abcdefghij== CUDA error",
     "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789"),
])
def test_fc_secret_shapes_are_redacted(line: str, secret: str) -> None:
    assert secret not in redact_line(line), redact_line(line)


def test_fc_file_names_and_paths_stay_readable() -> None:
    name = "seedvr2-prod-v004-ef75780775f4f9e1-S02_B-chunk-0007-f000087-000108-08f5fbd9a11b.mp4"
    out = redact_line(f"CUDA error while writing D:/out/{name}")
    assert name in out, out
    path = "/app/ComfyUI/custom_nodes/ComfyUI-SeedVR2_VideoUpscaler/src/core/generation_phases.py"
    assert path in redact_line(f'File "{path}", line 12, CUDA error'), "unix path with dots"
    win = r"C:\Users\Admin\ComfyUI\custom_nodes\ComfyUI-SeedVR2_VideoUpscaler\src\core\generation_phases.py"
    assert win in redact_line(f"{win}: CUDA error")
    assert "ok" in redact_line("auth: ok, CUDA error"), "a plain word after 'auth:' is not a secret"


def test_fc_fault_text_survives_redaction() -> None:
    log = '{"api_key": "hunter2-ABCDEF"} CUDA error: an illegal instruction was encountered\n'
    out = DockerProbe(lambda c: subprocess.CompletedProcess(c, 0, "", log)).fault_lines("c", 1.0)
    assert out["patterns"] == ["cuda error"] and "hunter2-ABCDEF" not in json.dumps(out)
    assert out["matched_lines"] == ['{"api_key": [REDACTED]} CUDA error: an illegal instruction was encountered']
