"""T-E30: the executor survives a ComfyUI crash mid-chunk (fake ComfyUI + fake docker, no real POST).

Incident 2026-10-27: CUDA illegal instruction -> container restarted -> the awaited prompt vanished and
the executor hung ~50 min.  Here the fake server "loses" a POST (answers a prompt_id, queues nothing) and
the fake docker reports a restart; the executor must PROVE the loss, archive, re-dispatch at most
``max_lost_retries`` times, and otherwise stop loudly.  It must never resubmit on any doubt.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from exec_fixtures import FakeDocker, make_rig
from fake_comfy import FakeComfy


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def fast(rig, **overrides):
    """Tiny stall window: stall after ~0.06 s without progress, two LOST checks 0.01 s apart."""
    values = {"stall_factor": 1.0, "expected_chunk_seconds": 0.06, "lost_recheck_seconds": 0.01,
              "poll_seconds": 0.01, **overrides}
    rig.settings = rig.settings.with_overrides(**values)
    rig.settings.output_dir.mkdir(parents=True, exist_ok=True)  # a real ComfyUI has its output root; absence of it is UNCERTAIN
    return rig


def crash_rig(tmp_path, fake, *, losses=1, **overrides):
    docker = FakeDocker()
    fake.lose_next_posts, fake.on_lose = losses, docker.restart
    return fast(make_rig(tmp_path, fake, **overrides)), docker


def archives(rig, index=0):
    return sorted(p for p in rig.chunk_dir(index).glob("abandoned-lost-*") if p.is_dir())


def test_container_restart_mid_chunk_is_lost_then_one_redispatch_then_completed(fake, tmp_path) -> None:
    docker = FakeDocker(faults=["CUDA error: an illegal instruction was encountered", "Fatal Python error: Aborted"])
    fake.lose_next_posts, fake.on_lose = 1, docker.restart
    rig = fast(make_rig(tmp_path, fake))
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 0, result
    assert len(fake.posts_made()) == 2, "exactly one automatic re-dispatch"
    job = rig.job(0)
    assert job["status"] == "COMPLETED" and job["prompt_id"] == "pid-0002" and job["lost_redispatches"] == 1
    (archive,) = archives(rig)
    assert {p.name for p in archive.iterdir()} >= {"INCIDENT.json", "LOST.json", "job.json", "dispatch-intent.json",
                                                   "submitted.json"}
    lost = json.loads((archive / "LOST.json").read_text())
    c = lost["classification"]
    assert lost["status"] == "LOST" and lost["decision"] == "REDISPATCH" and lost["retries_before"] == 0
    assert c["verdict"] == "LOST" and c["prompt_id"] == "pid-0001"
    assert c["container_started_at"] > c["dispatch_time"], "StartedAt later than the dispatch"
    assert len(c["snapshots"]) == 2 and not any(s["in_history"] or s["in_queue"] for s in c["snapshots"])
    assert c["outputs_with_prefix"] == []
    assert c["gpu_fault"]["matched_lines"][0].startswith("CUDA error")
    incident = json.loads((archive / "INCIDENT.json").read_text())
    assert incident["kind"] == "lost_prompt" and any(a["name"] == "job.json" and a["sha256"] for a in incident["archived"])
    state = json.loads((rig.plan.root / "runs" / "run-state.json").read_text())
    assert state["lost_redispatches"][0]["chunk"] == "chunk-0000"


def test_second_loss_stops_loudly_without_a_third_post(fake, tmp_path) -> None:
    rig, docker = crash_rig(tmp_path, fake, losses=2)
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and result["stopped"]["stage"] == "lost_retries_exhausted"
    assert "max_lost_retries=1" in result["stopped"]["message"]
    assert len(fake.posts_made()) == 2
    assert len(archives(rig)) == 1
    receipt = json.loads((rig.chunk_dir(0) / "LOST-retries-exhausted.json").read_text())
    assert receipt["decision"] == "STOP" and receipt["retries_before"] == 1
    assert rig.job(0)["status"] == "FAILED"


def test_max_lost_retries_zero_never_redispatches(fake, tmp_path) -> None:
    rig, docker = crash_rig(tmp_path, fake)
    rig.settings = rig.settings.with_overrides(max_lost_retries=0)
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1 and archives(rig) == []


def test_two_retries_allowed_by_config_survive_two_losses(fake, tmp_path) -> None:
    rig, docker = crash_rig(tmp_path, fake, losses=2)
    rig.settings = rig.settings.with_overrides(max_lost_retries=2)
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 3 and len(archives(rig)) == 2


def test_lost_limit_survives_an_executor_restart(fake, tmp_path) -> None:
    """The retry count is read from the abandoned-lost-* folders, not from memory."""
    rig, docker = crash_rig(tmp_path, fake, losses=2)
    assert rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))["exit_code"] == 2
    again = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert again["exit_code"] == 2 and len(fake.posts_made()) == 2, "still no third POST"
    rig.settings = rig.settings.with_overrides(max_lost_retries=2)
    fake.lose_next_posts = 0
    ok = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert ok["exit_code"] == 0 and len(fake.posts_made()) == 3 and len(archives(rig)) == 2


def test_container_not_restarted_is_never_lost_the_hard_timeout_stays_exit_3(fake, tmp_path) -> None:
    fake.lose_next_posts = 1  # prompt vanishes but docker says the container never restarted
    rig = fast(make_rig(tmp_path, fake, history_timeout=0.4))
    result = rig.executor(container_probe=FakeDocker()).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 3 and len(fake.posts_made()) == 1 and archives(rig) == []
    verdict = result["stopped"]["evidence"]["lost_classification"]
    assert verdict["verdict"] == "NOT_LOST" and "not restarted" in verdict["reasons"][0]
    assert (rig.chunk_dir(0) / "stall-alerts.json").is_file(), "stalled while waiting: alerted, not resubmitted"


def test_docker_unreadable_is_uncertain_never_resubmits(fake, tmp_path) -> None:
    docker = FakeDocker()
    fake.lose_next_posts = 1
    fake.on_lose = lambda: setattr(docker, "unreadable", True)  # readable at dispatch, dark after the loss
    rig = fast(make_rig(tmp_path, fake, history_timeout=30.0))
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1 and archives(rig) == []
    assert result["stopped"]["stage"] == "stall_uncertain"
    assert result["stopped"]["evidence"]["classification"]["verdict"] == "UNCERTAIN"


def test_stall_alerts_and_keeps_waiting_until_the_prompt_finishes(fake, tmp_path) -> None:
    rig = fast(make_rig(tmp_path, fake, auto_complete=False, history_timeout=5.0))
    original = fake.on_post

    def slow(payload, prompt_id):
        outputs = original(payload, prompt_id)

        def finish():
            time.sleep(0.5)
            fake.queue["queue_running"] = []
            fake.add_history(prompt_id, payload["prompt"], payload["client_id"], outputs)
        threading.Thread(target=finish, daemon=True).start()
        return outputs

    fake.on_post = slow
    # the output file appears at POST time in this fake: hide it from the watchdog's progress view by
    # asserting only what matters here (an alert was written, the run still completed, no resubmit)
    result = rig.executor(container_probe=FakeDocker()).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1 and archives(rig) == []
    alerts = json.loads((rig.chunk_dir(0) / "stall-alerts.json").read_text())
    assert alerts and alerts[0]["kind"] == "stall" and alerts[0]["classification"]["verdict"] == "NOT_LOST"
    assert alerts[0]["stall_seconds"] == pytest.approx(0.06) and alerts[0]["prompt_id"] == "pid-0001"
    assert rig.job(0)["stall_alerts"]["count"] == len(alerts)


def test_resume_after_a_dead_executor_and_a_lost_prompt_redispatches_once(fake, tmp_path) -> None:
    """The incident replay: the executor died waiting; `--resume` finds an intent whose prompt is gone."""
    rig, docker = crash_rig(tmp_path, fake)
    executor = rig.executor(container_probe=docker)
    original = executor.materialize
    executor.materialize = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt("killed while waiting"))
    with pytest.raises(KeyboardInterrupt):
        executor.run(rig.tasks(max_chunks=1))
    assert rig.job(0)["status"] == "SUBMITTED" and (rig.chunk_dir(0) / "dispatch-intent.json").is_file()
    executor.materialize = original
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 2 and len(archives(rig)) == 1
    assert rig.job(0)["status"] == "COMPLETED" and rig.job(0)["prompt_id"] == "pid-0002"


def test_resume_with_a_vanished_prompt_but_no_restart_still_stops(fake, tmp_path) -> None:
    rig, docker = crash_rig(tmp_path, fake)
    executor = rig.executor(container_probe=docker)
    executor.materialize = lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt("killed"))
    with pytest.raises(KeyboardInterrupt):
        executor.run(rig.tasks(max_chunks=1))
    docker.restarted = False  # docker says: never restarted
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1 and archives(rig) == []
    assert result["stopped"]["evidence"]["lost_classification"]["verdict"] == "NOT_LOST"


def test_partial_output_with_the_chunk_prefix_blocks_the_redispatch(fake, tmp_path) -> None:
    rig, docker = crash_rig(tmp_path, fake, history_timeout=0.5)
    prefix = rig.plan.plan["naming"]["output_prefix_template"].format(shot="S01_A", chunk="chunk-0000")
    partial = rig.settings.output_dir / f"{prefix}_00001_.mp4"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"half")
    result = rig.executor(container_probe=docker).run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 3 and len(fake.posts_made()) == 1 and archives(rig) == []
    assert "output file" in result["stopped"]["evidence"]["lost_classification"]["reasons"][0]
