"""T-E30 round 2: one test per critic finding (F1-F7).  Fakes only: no docker, no real ComfyUI, no GPU.

F1 missing output ROOT is UNCERTAIN, not proof of absence     F5 break-stale race (judged one lock, removed another)
F2 restart = StartedAt CHANGED since the intent, no clock math F6 machine-level run lock across plans
F3 retry budget survives deleting an archive (append-only ledger)  F7 lost_redispatches survive an executor restart
F4 docker log lines are redacted before they reach a receipt
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.comfy.client import ComfyClient
from engine.comfy.docker_probe import ContainerState, DockerProbe
from engine.comfy.lost import (LOST, NOT_LOST, UNCERTAIN, Classification, archive_lost_attempt, classify_lost,
                               lost_receipt, outputs_with_prefix)
from engine.core.errors import Refused
from engine.core.runlock import process_info, run_pid_lock
from exec_fixtures import FakeDocker, make_rig
from fake_comfy import FakeComfy

PREFIX = "episodes/x/S01_A/chunk-0000"
HOST = socket.gethostname()
MACHINE_LOCK = "EXECUTOR-RUN-LOCK.json"


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def fast(rig, **overrides):
    values = {"stall_factor": 1.0, "expected_chunk_seconds": 0.06, "lost_recheck_seconds": 0.01,
              "poll_seconds": 0.01, **overrides}
    rig.settings = rig.settings.with_overrides(**values)
    rig.settings.output_dir.mkdir(parents=True, exist_ok=True)  # a real ComfyUI has its output root
    return rig


def archives(rig, index=0):
    return sorted(p for p in rig.chunk_dir(index).glob("abandoned-lost-*") if p.is_dir())


def classify(fake, output_dir, docker, *, dispatch_instance=..., **kw):
    args = dict(client=ComfyClient(fake.url, timeout_seconds=5), probe=docker, container="c",
                dispatch_time=time.time() - 100, output_dir=output_dir, output_prefix=PREFIX, prompt_id="p1",
                recheck_seconds=0.0, sleep=lambda s: None)
    if dispatch_instance is not ...:
        args["dispatch_instance"] = dispatch_instance
    else:
        args["dispatch_instance"] = {"started_at_text": FakeDocker.BEFORE}
    return classify_lost(**{**args, **kw})


def write_lock(path: Path, **values) -> None:
    body = {"schema": "jjv/run-lock/v1", "pid": 1, "host": HOST, "process_start_time": None,
            "acquired_at": 1.0, "token": "other", **values}
    path.write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture()
def sleeper():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        yield child
    finally:
        child.kill()
        child.wait()


# ---- F1: a missing output ROOT is not proof that no output exists ------------------------
def test_f1_missing_output_root_is_uncertain_not_lost(fake, tmp_path) -> None:
    docker = FakeDocker()
    docker.restart()
    result = classify(fake, tmp_path / "unmounted-output-root", docker)
    assert result.verdict == UNCERTAIN, result.reasons
    assert "output" in result.reasons[0].lower()


def test_f1_output_root_that_is_a_file_is_uncertain(fake, tmp_path) -> None:
    docker = FakeDocker()
    docker.restart()
    not_a_dir = tmp_path / "output"
    not_a_dir.write_text("x")
    assert classify(fake, not_a_dir, docker).verdict == UNCERTAIN


def test_f1_existing_root_without_the_prefix_folder_is_still_lost(fake, tmp_path) -> None:
    """The root is readable and has no folder for this chunk yet: that IS absence."""
    docker = FakeDocker()
    docker.restart()
    assert classify(fake, tmp_path, docker).verdict == LOST


def test_f1_outputs_with_prefix_raises_for_a_missing_root(tmp_path) -> None:
    with pytest.raises(OSError):
        outputs_with_prefix(tmp_path / "nope", PREFIX)
    assert outputs_with_prefix(tmp_path, PREFIX) == []


# ---- F2: restart = the container instance changed, never host clock vs VM clock ---------
def test_f2_changed_started_at_since_the_intent_is_lost(fake, tmp_path) -> None:
    docker = FakeDocker()
    docker.restart()
    result = classify(fake, tmp_path, docker, dispatch_instance={"started_at_text": FakeDocker.BEFORE})
    assert result.verdict == LOST
    assert result.evidence["dispatch_container_started_at_text"] == FakeDocker.BEFORE


def test_f2_vm_clock_30s_ahead_without_a_restart_is_not_lost(fake, tmp_path) -> None:
    class SkewDocker(FakeDocker):
        def state(self, container):  # same instance as at dispatch; the VM clock reads 30 s ahead
            return ContainerState(started_at=time.time() + 30.0, started_at_text=FakeDocker.BEFORE,
                                  running=True, restart_count=0)
    result = classify(fake, tmp_path, SkewDocker(), dispatch_time=time.time() - 40)
    assert result.verdict == NOT_LOST and "not restarted" in result.reasons[0]


def test_f2_missing_pre_dispatch_value_is_uncertain(fake, tmp_path) -> None:
    docker = FakeDocker()
    docker.restart()
    for missing in (None, {}, {"started_at_text": ""}):
        result = classify(fake, tmp_path, docker, dispatch_instance=missing)
        assert result.verdict == UNCERTAIN, missing
        assert "StartedAt" in result.reasons[0]
    assert fake.requests == [], "no ComfyUI read is needed to decide that"


def test_f2_executor_with_a_skewed_vm_clock_never_redispatches(fake, tmp_path) -> None:
    """Whole executor: the prompt vanishes, the VM clock is ahead, the container never restarted."""
    class SkewDocker(FakeDocker):
        def state(self, container):
            return ContainerState(started_at=time.time() + 30.0, started_at_text="same-instance",
                                  running=True, restart_count=0)
    fake.lose_next_posts = 1
    rig = fast(make_rig(tmp_path, fake, history_timeout=0.4))
    result = rig.executor(container_probe=SkewDocker()).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 3 and len(fake.posts_made()) == 1 and archives(rig) == []
    assert result["stopped"]["evidence"]["lost_classification"]["verdict"] == "NOT_LOST"


def test_f2_the_container_instance_is_recorded_in_the_intent_before_the_post(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    seen: list[dict] = []
    previous = fake.on_post

    def watch(payload, prompt_id):
        seen.append(json.loads((rig.chunk_dir(0) / "dispatch-intent.json").read_text()))
        return previous(payload, prompt_id)

    fake.on_post = watch
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    assert seen[0]["container_instance"]["started_at_text"] == FakeDocker.BEFORE
    assert seen[0]["container_instance"]["container"] == "test-container"


def test_f2_docker_unreadable_at_dispatch_refuses_the_dispatch(fake, tmp_path) -> None:
    """Round 3: no StartedAt, no dispatch (a prompt that can never be proven lost can only hang)."""
    docker = FakeDocker()
    docker.unreadable = True
    fake.lose_next_posts = 1
    rig = fast(make_rig(tmp_path, fake, history_timeout=0.4))
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and result["stopped"]["stage"] == "container_instance_unavailable"
    assert fake.posts_made() == [] and not (rig.chunk_dir(0) / "dispatch-intent.json").exists()


# ---- F3: the retry budget cannot be reset by deleting an archive -------------------------
def test_f3_deleting_an_archive_does_not_reset_the_retry_budget(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = 2, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 2
    assert len(fake.posts_made()) == 2
    (archive,) = archives(rig)
    import shutil
    shutil.rmtree(archive)  # somebody "cleans up" the evidence
    fake.lose_next_posts = 1
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2, result
    assert result["stopped"]["stage"] == "lost_ledger_mismatch"
    assert "ledger" in result["stopped"]["message"].lower()
    assert len(fake.posts_made()) == 2, "no third POST"
    assert archives(rig) == []


def test_f3_every_archive_is_written_to_the_append_only_ledger(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = 1, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 0
    ledger = rig.plan.root / "runs" / "LOST-LEDGER.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["shot_id"] == "S01_A" and rows[0]["chunk"] == "chunk-0000"
    assert rows[0]["archive"] == archives(rig)[0].name


def test_f3_legacy_archives_without_a_ledger_still_count(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = 2, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 2
    (rig.plan.root / "runs" / "LOST-LEDGER.jsonl").unlink()  # pre-ledger state: dirs alone
    fake.lose_next_posts = 1
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and result["stopped"]["stage"] == "lost_retries_exhausted"
    assert len(fake.posts_made()) == 2


# ---- F4: nothing token-like reaches LOST.json / INCIDENT.json ----------------------------
SECRET_LOG = "\n".join([
    "Authorization: Bearer sk-live-AAAA1111BBBB2222 CUDA error: an illegal instruction was encountered",
    "CUDA error while calling with api_key=hunter2hunter2 and token=abc123def456 password=correcthorse",
    "Fatal Python error: Aborted OPENAI=sk-proj-Zm9vYmFyYmF6cXV4MTIzNDU2 ok",
    "out of memory 3f2a9c4b7e1d8a6f5c0b9e8d7a6f5c4b3e2d1c0b9a8f7e6d5c4b3a291807f6e5",
    "CUDA error blob " + "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789+/abcdefghij==",
    "CUDA error " + "x " * 600,
    "unrelated line with token=shouldnotmatter",
])
SECRETS = ["sk-live-AAAA1111BBBB2222", "hunter2hunter2", "abc123def456", "correcthorse",
           "Zm9vYmFyYmF6cXV4MTIzNDU2", "3f2a9c4b7e1d8a6f5c0b9e8d7a6f5c4b3e2d1c0b9a8f7e6d5c4b3a291807f6e5",
           "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789"]


def test_f4_fault_lines_redact_tokens_and_cap_length() -> None:
    probe = DockerProbe(lambda c: subprocess.CompletedProcess(c, 0, "", SECRET_LOG))
    fault = probe.fault_lines("c", 1.0)
    dumped = json.dumps(fault)
    for secret in SECRETS:
        assert secret not in dumped, secret
    assert fault["matched_total"] == 6 and all(len(line) <= 400 for line in fault["matched_lines"])
    assert any(line.startswith("Authorization") and "CUDA error" in line for line in fault["matched_lines"]), \
        "the fault text itself stays readable"
    assert "[REDACTED" in dumped
    assert fault["patterns"] == ["cuda error", "fatal python error", "out of memory"]


def test_f4_archive_files_carry_no_secret(tmp_path) -> None:
    probe = DockerProbe(lambda c: subprocess.CompletedProcess(c, 0, "", SECRET_LOG))
    verdict = Classification(LOST, ("proof",), {"gpu_fault": probe.fault_lines("c", 1.0)})
    chunk = tmp_path / "chunk-0000"
    chunk.mkdir()
    (chunk / "job.json").write_text("{}")
    receipt = lost_receipt(verdict, identity={}, retries_before=0, max_lost_retries=1, decision="REDISPATCH",
                           clock=lambda: 1.0)
    target = archive_lost_attempt(chunk, receipt, lambda: 1.0)
    text = (target / "LOST.json").read_text() + (target / "INCIDENT.json").read_text()
    for secret in SECRETS:
        assert secret not in text, secret


# ---- F5: break-stale must remove the lock it JUDGED, not one that replaced it ------------
def test_f5_break_stale_does_not_remove_a_lock_that_replaced_the_judged_one(tmp_path, sleeper) -> None:
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, pid=424242, token="stale-token", process_start_time=None)
    fresh = {"pid": sleeper.pid, "token": "fresh-live-token", "process_start_time": process_info(sleeper.pid)[1]}
    real_info = process_info
    swapped = {"done": False}

    def racing_info(pid):
        if pid == 424242 and not swapped["done"]:
            swapped["done"] = True
            write_lock(path, **fresh)  # a live executor took over between our read and our removal
            return False, None
        return real_info(pid)

    with pytest.raises(Refused, match="changed while"):
        with run_pid_lock(path, break_stale=True, info=racing_info):
            pytest.fail("must not take the lock")
    assert json.loads(path.read_text())["token"] == "fresh-live-token", "the live holder's lock is intact"
    assert not list(tmp_path.glob("*.aside")), "nothing left behind"
    assert not list(tmp_path.glob("stale-lock-*.json")), "no break report for a lock that was not broken"


def test_f5_a_genuinely_stale_lock_is_still_broken_and_reported(tmp_path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    path = tmp_path / "RUN-LOCK.json"
    write_lock(path, pid=child.pid, token="stale-token")
    with run_pid_lock(path, break_stale=True) as body:
        assert json.loads(path.read_text())["token"] == body["token"]
    (report,) = tmp_path.glob("stale-lock-*.json")
    assert json.loads(report.read_text())["lock"]["token"] == "stale-token"
    assert not list(tmp_path.glob("*.aside")) and not path.exists()


# ---- F6: a machine-level lock excludes executors of OTHER plans --------------------------
def machine_lock(rig) -> Path:
    return rig.settings.lock_path.parent / MACHINE_LOCK


def test_f6_a_live_executor_on_another_plan_refuses_this_one_naming_the_holder(fake, tmp_path, sleeper) -> None:
    rig = make_rig(tmp_path, fake)
    write_lock(machine_lock(rig), pid=sleeper.pid, process_start_time=process_info(sleeper.pid)[1],
               plan="D:/other/plan-v004")
    with pytest.raises(Refused) as caught:
        rig.executor().run(rig.tasks(max_chunks=1), break_stale_lock=True)
    message = str(caught.value)
    assert str(sleeper.pid) in message and HOST in message and "other/plan-v004" in message
    assert "machine" in message.lower()
    assert fake.requests == [] and not (rig.plan.root / "runs" / "run-state.json").exists()
    assert not (rig.plan.root / "runs" / "RUN-LOCK.json").exists(), "the plan lock was released"


def test_f6_the_machine_lock_is_held_for_the_run_names_the_plan_and_is_released(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    seen: list[dict] = []
    previous = fake.on_post

    def watch(payload, prompt_id):
        seen.append(json.loads(machine_lock(rig).read_text()))
        return previous(payload, prompt_id)

    fake.on_post = watch
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    assert seen[0]["pid"] == os.getpid() and seen[0]["host"] == HOST
    assert seen[0]["plan"] == str(rig.plan.root) and seen[0]["plan_sha256"] == rig.plan.sha256
    assert not machine_lock(rig).exists()


def test_f6_two_plans_one_machine_second_executor_is_refused_while_first_runs(fake, tmp_path) -> None:
    rig_a = make_rig(tmp_path / "a", fake)
    with FakeComfy() as fake_b:
        rig_b = make_rig(tmp_path / "b", fake_b)
        rig_b.settings = rig_b.settings.with_overrides(lock_path=rig_a.settings.lock_path)
        outcome: dict = {}
        previous = fake.on_post

        def second_executor_starts_mid_run(payload, prompt_id):
            try:
                rig_b.executor().run(rig_b.tasks(max_chunks=1))
                outcome["error"] = None
            except Refused as error:
                outcome["error"] = error
            return previous(payload, prompt_id)

        fake.on_post = second_executor_starts_mid_run
        assert rig_a.executor().run(rig_a.tasks(max_chunks=1))["exit_code"] == 0
        assert isinstance(outcome.get("error"), Refused), outcome
        assert str(os.getpid()) in str(outcome["error"]) and fake_b.requests == []


def test_f6_dry_run_takes_neither_lock(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    rig.executor().dry_run(rig.tasks(max_chunks=1))
    assert not machine_lock(rig).exists() and not (rig.plan.root / "runs").exists()


def test_f6_a_stale_machine_lock_needs_the_flag(fake, tmp_path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    rig = make_rig(tmp_path, fake)
    write_lock(machine_lock(rig), pid=child.pid, plan="old")
    with pytest.raises(Refused, match="STALE"):
        rig.executor().run(rig.tasks(max_chunks=1))
    assert fake.requests == []
    assert rig.executor().run(rig.tasks(max_chunks=1), break_stale_lock=True)["exit_code"] == 0
    assert not machine_lock(rig).exists()


# ---- F7: lost_redispatches are carried across an executor restart ------------------------
def test_f7_run_state_keeps_earlier_redispatches_after_a_restart(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = 1, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    assert len(rig.tasks()) >= 2, "this test needs a second chunk"
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 0
    state = json.loads((rig.plan.root / "runs" / "run-state.json").read_text())
    assert [r["chunk"] for r in state["lost_redispatches"]] == ["chunk-0000"]
    again = rig.executor(container_probe=FakeDocker()).run(rig.tasks(), resume=True)
    assert again["exit_code"] == 0
    state = json.loads((rig.plan.root / "runs" / "run-state.json").read_text())
    assert [r["chunk"] for r in state["lost_redispatches"]] == ["chunk-0000"], state
    assert state["automatic_retry"] is True
