"""T-E39 call sites: images local submit, audio run_job and the SeedVR2 executor refuse BEFORE any intent/POST
when the health preflight fails.  The test-harness default (tests/conftest.py) answers any container as healthy
and never runs the real docker CLI; a test that wants a sick container monkeypatches the health runner."""

from __future__ import annotations

import pytest

from engine.audio import jobs
from engine.comfy.client import ComfyClient
from engine.comfy.guards import ClassPolicy
from engine.comfy.settings import ComfySettings
from engine.core.errors import Refused
from engine.health import docker_facts, fixture
from exec_fixtures import make_rig
from fake_comfy import FakeComfy
from test_images_local import Setup


def bad_container_runner(container_args=("main.py",)):
    """A docker runner whose container (any name asked) was launched WITHOUT --disable-partner-nodes."""
    def run(command):
        return fixture.fixture_runner(fixture.healthy_fixture(command[-1], args=container_args))(command)
    return run


def docker_missing(command):
    raise FileNotFoundError("docker")


@pytest.fixture
def fake():
    with FakeComfy() as server:
        yield server


def test_the_harness_default_answers_any_container_as_healthy_and_never_runs_the_real_cli():
    facts = docker_facts.collect_docker_facts("any-name-at-all")
    assert facts.engine_reachable and facts.container.name == "any-name-at-all"
    assert "--disable-partner-nodes" in facts.container.args and facts.container.restart_policy == "unless-stopped"
    with pytest.raises(FileNotFoundError, match="never run by tests"):
        docker_facts._real_default_runner(["docker", "version"])


def test_images_local_submit_refuses_a_container_without_the_flag_and_stages_nothing(tmp_path, fake, monkeypatch):
    setup = Setup(tmp_path, fake)
    monkeypatch.setattr(docker_facts, "default_runner", bad_container_runner())
    with pytest.raises(Refused, match="launched without --disable-partner-nodes") as caught:
        setup.submit(pilot=True)
    assert caught.value.evidence["stage"] == "health_preflight" and fake.posts == []
    assert not list(setup.settings.input_dir.iterdir())  # refused before staging and before any intent
    assert not (setup.out / "S01_A" / "local" / "t001" / "comfy").exists()


def test_images_local_submit_refuses_when_docker_is_unreachable(tmp_path, fake, monkeypatch):
    setup = Setup(tmp_path, fake)
    monkeypatch.setattr(docker_facts, "default_runner", docker_missing)
    with pytest.raises(Refused, match="docker engine unreachable"):
        setup.submit(pilot=True)
    assert fake.posts == []


def test_images_local_dry_run_never_reaches_the_preflight(tmp_path, fake, monkeypatch):
    setup = Setup(tmp_path, fake)
    monkeypatch.setattr(docker_facts, "default_runner", docker_missing)
    assert setup.submit(dry_run=True)["dry_run"] is True and fake.posts == []


def _audio_context(tmp_path, fake):
    settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                             output_dir=tmp_path / "out", container="render-box")
    return jobs.RunContext(client=ComfyClient(fake.url, timeout_seconds=5), settings=settings,
                           policy=ClassPolicy(frozenset(), True, frozenset()), out=tmp_path / "audio", timeout_seconds=5.0)


def test_audio_run_job_refuses_a_container_without_the_flag_before_any_post(tmp_path, fake, monkeypatch):
    ctx = _audio_context(tmp_path, fake)
    graph = {"1": {"class_type": "SaveAudio", "inputs": {"filename_prefix": "x"}}}
    job = {"job_id": "j1", "receipt_dir": "jobs/j1", **jobs.write_workflow(ctx.out, "j1", graph)}
    monkeypatch.setattr(docker_facts, "default_runner", bad_container_runner())
    with pytest.raises(Refused, match="launched without --disable-partner-nodes"):
        jobs.run_job(ctx, job, models_checked=lambda: None)
    assert fake.posts == [] and not (ctx.out / "jobs" / "j1" / "dispatch-intent.json").exists()
    assert jobs.job_state(ctx.out, job) == "READY"  # no post evidence: the job can be run once docker is fixed


def test_seedvr2_executor_refuses_before_the_intent_when_the_container_lacks_the_flag(tmp_path, fake, monkeypatch):
    rig = make_rig(tmp_path, fake)
    monkeypatch.setattr(docker_facts, "default_runner", bad_container_runner())
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 1 and fake.posts_made() == []
    assert result["stopped"]["stage"] == "health_preflight" and "--disable-partner-nodes" in result["stopped"]["message"]
    assert not (rig.chunk_dir(0) / "dispatch-intent.json").exists()
    job = rig.job(0)
    assert job["status"] == "FAILED" and job["prior_status"] == "PREPARED" and job["failure"]["posted"] is False
    monkeypatch.setattr(docker_facts, "default_runner", bad_container_runner(("main.py", "--disable-partner-nodes")))
    again = rig.executor().run(rig.tasks(max_chunks=1), resume=True)  # the operator fixed the container: resume dispatches once
    assert again["exit_code"] == 0 and len(fake.posts_made()) == 1 and rig.job(0)["status"] == "COMPLETED"


def test_seedvr2_executor_still_dispatches_with_the_harness_default(tmp_path, fake):
    rig = make_rig(tmp_path, fake)
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 0 and len(fake.posts_made()) == 1 and rig.job(0)["status"] == "COMPLETED"
