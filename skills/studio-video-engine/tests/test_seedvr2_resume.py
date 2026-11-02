"""M4: SeedVR2 executor resume/reconcile, plan validation (part 2 of test_seedvr2_execute.py).

Original docstring: SeedVR2 executor against a fake ComfyUI.  Ports the 16 v004 executor tests and adds the
helper-derived guarantees (dry run never POSTs; hash mismatch / busy queue / held lock refuse;
intent before POST; failure stops the run; resume skips and reconciles; short segments)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import canonical_sha256
from engine.comfy.settings import ComfySettings
from engine.seedvr2.execplan import select_tasks
from exec_fixtures import SHOT, make_rig, media_bytes
from fake_comfy import FakeComfy


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# ---- resume (I3, I9) ---------------------------------------------------------------------
def test_without_resume_existing_state_refuses(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    again = rig.executor().run(rig.tasks(max_chunks=1))
    assert again["exit_code"] == 2 and "--resume" in again["stopped"]["message"], "a POST happened earlier"
    assert len(fake.posts_made()) == 1
    assert rig.job(0)["status"] == "COMPLETED", "a refusal never demotes a verified COMPLETED job"
    assert (rig.chunk_dir(0) / "job-check-failure.json").is_file()


def test_resume_skips_verified_completed_chunks_without_any_network(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=2))["exit_code"] == 0
    requests = len(fake.requests)
    again = rig.executor().run(rig.tasks(max_chunks=2), resume=True)
    assert again["exit_code"] == 0 and len(fake.requests) == requests and len(fake.posts_made()) == 2


def test_resume_refuses_a_completed_chunk_whose_core_was_tampered(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    core = next((rig.chunk_dir(0) / "core").iterdir())
    core.write_bytes(b"tampered")
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and "hash mismatch" in result["stopped"]["message"]
    assert len(fake.posts_made()) == 1 and rig.job(0)["status"] == "COMPLETED"


def _crash_after_post(rig, fake) -> tuple[str, str]:
    """Run chunk 0 but make the executor die right after the POST (no job beyond PREPARED)."""
    executor = rig.executor()
    original = executor.materialize

    def die(*args, **kwargs):
        raise KeyboardInterrupt("simulated crash after POST")

    executor.materialize = die  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        executor.run(rig.tasks(max_chunks=1))
    assert rig.job(0)["status"] == "SUBMITTED"
    executor.materialize = original  # type: ignore[method-assign]
    return json.loads((rig.chunk_dir(0) / "dispatch-intent.json").read_text())["client_id"], "pid-0001"


def test_resume_after_a_crash_reconciles_the_known_prompt_and_never_reposts(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    _crash_after_post(rig, fake)
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1
    assert rig.job(0)["status"] == "COMPLETED" and rig.job(0)["prompt_id"] == "pid-0001"


def test_resume_reconciles_an_intent_without_a_job_by_exact_graph_and_client(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    _crash_after_post(rig, fake)
    chunk_dir = rig.chunk_dir(0)
    (chunk_dir / "job.json").unlink()  # lose the job AND submitted.json: only the intent survives
    (chunk_dir / "submitted.json").unlink()
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1
    job = rig.job(0)
    assert job["status"] == "COMPLETED" and job["prompt_id"] == "pid-0001" and job["reconciled_at"]


def test_resume_with_an_intent_and_no_trace_stops_and_never_reposts(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    _crash_after_post(rig, fake)
    chunk_dir = rig.chunk_dir(0)
    (chunk_dir / "job.json").unlink()
    (chunk_dir / "submitted.json").unlink()
    fake.history.clear()
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1
    assert result["stopped"]["stage"] == "reconciliation_no_match"


def test_resume_with_two_matching_prompts_is_ambiguous_and_stops(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    _crash_after_post(rig, fake)
    chunk_dir = rig.chunk_dir(0)
    (chunk_dir / "job.json").unlink()
    (chunk_dir / "submitted.json").unlink()
    entry = fake.history["pid-0001"]
    fake.add_history("pid-dup", entry["prompt"][2], entry["prompt"][3]["client_id"], entry["outputs"])
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and "multiple" in result["stopped"]["message"]
    assert len(fake.posts_made()) == 1


def test_resume_of_a_pre_post_failure_redispatches_cleanly(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    fake.queue["queue_pending"] = [[1, "foreign", {}, {}, []]]
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 1
    fake.queue["queue_pending"] = []
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1
    assert "failure" not in rig.job(0)


def test_the_run_lock_stops_two_executors_on_the_same_run(fake, tmp_path) -> None:
    from engine.core.filelock import run_lock
    rig = make_rig(tmp_path, fake)
    runs = rig.plan.root / "runs"
    runs.mkdir(parents=True)
    with run_lock(runs / ".executor.lock", timeout_seconds=0):
        with pytest.raises(Refused, match="run lock"):
            rig.executor().run(rig.tasks(max_chunks=1))
    assert fake.posts_made() == []


def test_telemetry_summary_lands_in_the_job_when_a_sampler_is_given(fake, tmp_path) -> None:
    from engine.comfy.telemetry import TelemetrySampler
    import subprocess as sp
    rig = make_rig(tmp_path, fake)
    runner = lambda cmd: sp.CompletedProcess(cmd, 0, "1 GiB / 2 GiB" if cmd[0] == "docker" else "4096", "")  # noqa: E731
    executor = rig.executor(sampler_factory=lambda path: TelemetrySampler(
        container="c", samples_path=path, runner=runner, interval_seconds=0.05))
    assert executor.run(rig.tasks(max_chunks=1))["exit_code"] == 0
    telemetry = rig.job(0)["telemetry"]
    assert telemetry["gpu_memory_peak_mib"] == 4096
    # the summary is taken after the sampler stopped, so its sha is the sha of the file that is on disk now
    from engine.core.io import sha256_file
    assert telemetry["samples_sha256"] == sha256_file(Path(telemetry["samples_path"]))


# ---- plan validation and domain rule ----------------------------------------------------
def test_tampered_plan_fields_are_refused(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    original = json.loads(rig.plan.path.read_text())

    def tamper(change) -> None:
        plan = json.loads(json.dumps(original))
        change(plan)
        rig.plan.path.write_text(json.dumps(plan))

    for change, text in (
            (lambda p: p["shots"][0]["chunks"][1].update(core_frames=12), "core_frames"),
            (lambda p: p["shots"][0]["chunks"][1].update(expected_raw_output_frames=24), "expected_raw_output_frames"),
            (lambda p: p["shots"][0]["chunks"][0].update(segment_sha256=None), "segment_sha256"),
            (lambda p: p["shots"][0]["chunks"][0].update(gpu_submitted=True), "prepare-only"),
            (lambda p: p.update(status="PLANNED_SEGMENTS_PENDING"), "PLANNED_NOT_RENDERED"),
            (lambda p: p.update(domain="newtecons_live_action"), "domain"),
            (lambda p: p.update(recipe_canonical_sha256="0" * 64), "recipe sha256"),
            (lambda p: p["recipe_geometry"].update(core_frames=17), "recipe_geometry"),
            (lambda p: p["target"].update(crop_left=0), "target"),
            (lambda p: p["shots"][0].update(source_sha256="0" * 64), "source sha256"),
            (lambda p: p["shots"].append(dict(p["shots"][0], shot_id="S99_X")), "shots differ")):
        tamper(change)
        with pytest.raises(Refused, match=text):
            rig.reload_plan()
    rig.plan.path.write_text(json.dumps(original))
    assert rig.reload_plan().shot_ids == [SHOT]


def test_a_graph_that_differs_from_the_pilot_beyond_the_two_ports_is_refused(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    task = rig.tasks()[0]
    graph_path = rig.plan.root / task.chunk["api_graph_path"]
    graph = json.loads(graph_path.read_text())
    graph["10"]["inputs"]["denoise"] = 0.5
    graph_path.write_text(json.dumps(graph))
    plan = json.loads(rig.plan.path.read_text())  # an attacker also "fixes" the plan hash
    plan["shots"][0]["chunks"][0]["api_graph_canonical_sha256"] = canonical_sha256(graph, mode="ascii")
    rig.plan.path.write_text(json.dumps(plan))
    forged = rig.reload_plan()
    executor = type(rig.executor())(config=rig.config, recipe=rig.recipe, plan=forged, settings=rig.settings,
                                    repo_root=__import__("engine.config.loader", fromlist=["x"]).REPO_ROOT,
                                    probe=rig.executor().probe, runner=rig.ffmpeg, emit=lambda m: None)
    with pytest.raises(Refused, match="differs from the pilot|differs from the qualified"):
        executor.dry_run(select_tasks(forged.tasks, only=f"{SHOT}:0"))


def test_plan_changes_between_chunks_are_detected(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    executor = rig.executor()
    rig.plan.path.write_text(rig.plan.path.read_text() + " ")
    result = executor.run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and "plan before chunk" in result["stopped"]["message"]
    assert fake.posts_made() == []


def test_selectors_follow_the_requested_order_and_reject_bad_input(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    picked = select_tasks(rig.plan.tasks, only=f"{SHOT}:2,{SHOT}:0,{SHOT}:1")
    assert [t.chunk["index"] for t in picked] == [2, 0, 1] and fake.requests == []
    assert [t.chunk["index"] for t in select_tasks(rig.plan.tasks, max_chunks=2)] == [0, 1]
    for only in ("", ",", f"{SHOT}:9", "S99", f"{SHOT}:x", f"{SHOT}:0,{SHOT}:0"):
        if only:
            with pytest.raises(Refused):
                select_tasks(rig.plan.tasks, only=only)
    with pytest.raises(Refused):
        select_tasks(rig.plan.tasks, max_chunks=0)


def test_history_timeout_below_the_minimum_is_refused(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    rig.settings = ComfySettings(**{**rig.settings.__dict__, "min_history_timeout_seconds": 900.0,
                                    "history_timeout_seconds": 10.0})
    with pytest.raises(Refused, match="at least 900"):
        rig.executor().run(rig.tasks(max_chunks=1))
    assert fake.requests == []
