"""T-E30 units: the LOST proof (every condition on its own), docker probe parsing, stall watchdog, settings."""

from __future__ import annotations

import json
import subprocess

import pytest

from engine.comfy.client import ComfyClient
from engine.comfy.docker_probe import DockerProbe, parse_started_at
from engine.comfy.lost import LOST, NOT_LOST, UNCERTAIN, Classification, LostPrompt, classify_lost
from engine.comfy.settings import settings_from_machine
from engine.comfy.watchdog import FALLBACK_EXPECTED_SECONDS, StallWatchdog, expected_seconds, gpu_bucket
from engine.config import loader, schema
from exec_fixtures import FakeDocker
from fake_comfy import FakeComfy

PREFIX = "episodes/x/S01_A/chunk-0000"
DISPATCH = 1000.0


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def classify(fake, tmp_path, docker=None, **kw):
    docker = docker or FakeDocker()
    docker.restarted = kw.pop("restarted", True)
    args = dict(client=ComfyClient(fake.url, timeout_seconds=5), probe=docker, container="c",
                dispatch_time=time_ago(), dispatch_instance={"started_at_text": FakeDocker.BEFORE},
                output_dir=tmp_path, output_prefix=PREFIX, prompt_id="p1",
                recheck_seconds=0.0, sleep=lambda s: None)
    return classify_lost(**{**args, **kw})


def time_ago() -> float:
    import time
    return time.time() - 100  # FakeDocker.restart() reports now + 1: always later


def test_all_three_conditions_hold_is_lost_with_evidence(fake, tmp_path) -> None:
    docker = FakeDocker(faults=["CUDA error: an illegal instruction was encountered"])
    result = classify(fake, tmp_path, docker)
    assert result.verdict == LOST and result.lost
    assert len(result.evidence["snapshots"]) == 2
    assert result.evidence["gpu_fault"]["matched_lines"] == ["CUDA error: an illegal instruction was encountered"]
    assert result.evidence["container_started_at_text"] != result.evidence["dispatch_container_started_at_text"]


def test_two_checks_are_spaced_by_the_recheck_delay(fake, tmp_path) -> None:
    sleeps: list[float] = []
    classify(fake, tmp_path, recheck_seconds=7.5, sleep=sleeps.append)
    assert sleeps == [7.5]


def test_container_not_restarted_is_not_lost_and_never_reads_comfy(fake, tmp_path) -> None:
    result = classify(fake, tmp_path, restarted=False)
    assert result.verdict == NOT_LOST and "not restarted" in result.reasons[0]
    assert fake.requests == []


def test_prompt_still_in_history_is_not_lost(fake, tmp_path) -> None:
    fake.add_history("p1", {"1": {}}, "jjv-x")
    result = classify(fake, tmp_path)
    assert result.verdict == NOT_LOST and "history" in result.reasons[0]


def test_prompt_still_in_queue_is_not_lost(fake, tmp_path) -> None:
    fake.queue["queue_pending"] = [[1, "p1", {"1": {}}, {"client_id": "jjv-x"}, []]]
    assert classify(fake, tmp_path).verdict == NOT_LOST


def test_prompt_appearing_at_the_second_check_is_not_lost(fake, tmp_path) -> None:
    result = classify(fake, tmp_path, sleep=lambda s: fake.add_history("p1", {"1": {}}, "jjv-x"))
    assert result.verdict == NOT_LOST and "check 2" in result.reasons[0]


def test_output_file_with_the_prefix_is_not_lost(fake, tmp_path) -> None:
    partial = tmp_path / PREFIX.rsplit("/", 1)[0] / "chunk-0000_00001_.mp4"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"x")
    (partial.parent / "chunk-0001_00001_.mp4").write_bytes(b"other chunk")  # a different chunk does not count
    result = classify(fake, tmp_path)
    assert result.verdict == NOT_LOST and result.evidence["outputs_with_prefix"][0]["name"] == "chunk-0000_00001_.mp4"


def test_unreadable_docker_stopped_container_and_dead_comfy_are_uncertain(fake, tmp_path) -> None:
    unreadable = FakeDocker()
    unreadable.unreadable = True
    assert classify(fake, tmp_path, unreadable).verdict == UNCERTAIN
    assert classify(fake, tmp_path, FakeDocker(running=False)).verdict == UNCERTAIN
    fake.queue_mode = "status:500"
    result = classify(fake, tmp_path)
    assert result.verdict == UNCERTAIN and "ComfyUI unreadable" in result.reasons[0]


def test_without_a_prompt_id_the_intent_graph_and_client_stand_in(fake, tmp_path) -> None:
    kw = dict(prompt_id=None, graph_sha256="a" * 64, client_id="jjv-x")
    assert classify(fake, tmp_path, **kw).verdict == LOST
    from engine.core.io import canonical_sha256
    graph = {"1": {"class_type": "X"}}
    fake.add_history("p9", graph, "jjv-x")
    assert classify(fake, tmp_path, prompt_id=None, graph_sha256=canonical_sha256(graph, mode="ascii"),
                    client_id="jjv-x").verdict == NOT_LOST
    with pytest.raises(ValueError):
        classify(fake, tmp_path, prompt_id=None)


# ---- docker probe ------------------------------------------------------------------------
def test_parse_started_at_handles_docker_nanoseconds() -> None:
    assert parse_started_at("2026-10-27T07:02:57.123456789Z") == pytest.approx(1793084577.123456)
    assert parse_started_at("2026-10-27T07:02:57Z") == 1793084577.0
    assert parse_started_at("garbage") is None


def test_docker_probe_state_and_fault_signature_through_an_injected_runner() -> None:
    calls: list[list[str]] = []
    log = ("loading model\nCUDA error: an illegal instruction was encountered\nFatal Python error: Aborted\n"
           "nothing here\nCUDA out of memory\n")

    def runner(command):
        calls.append(command)
        if command[1] == "inspect":
            return subprocess.CompletedProcess(command, 0, "2026-10-27T07:02:57.5Z|true|1\n", "")
        return subprocess.CompletedProcess(command, 0, "", log)  # ComfyUI logs to stderr

    probe = DockerProbe(runner)
    state = probe.state("Comfyui-Studio")
    assert state and state.running and state.restart_count == 1 and state.started_at == pytest.approx(1793084577.5)
    fault = probe.fault_lines("Comfyui-Studio", 1793000000.25)
    assert fault["patterns"] == ["cuda error", "fatal python error", "out of memory"]
    assert fault["matched_total"] == 3 and fault["line_count"] == 5
    assert calls[1][:4] == ["docker", "logs", "--since", "1793000000.250"]


def test_docker_probe_failures_are_unknown_not_an_error() -> None:
    def broken(command):
        raise FileNotFoundError("docker")
    assert DockerProbe(broken).state("c") is None
    assert DockerProbe(lambda c: subprocess.CompletedProcess(c, 1, "", "no such")).state("c") is None
    assert DockerProbe(broken).fault_lines("c", 1.0)["available"] is False


# ---- watchdog ----------------------------------------------------------------------------
def make_dog(states, verdicts):
    clock = {"t": 0.0}
    alerts: list[dict] = []
    seq = iter(states)
    dog = StallWatchdog(stall_seconds=10, fingerprint=lambda: next(seq), on_alert=alerts.append,
                        classify=lambda: verdicts.pop(0), clock=lambda: clock["t"])
    return dog, clock, alerts


def tick(dog, clock, seconds):
    clock["t"] += seconds
    dog.check()


def test_watchdog_progress_resets_the_stall_clock() -> None:
    dog, clock, alerts = make_dog(["a", "b", "b", "c", "c"], [])
    for _ in range(5):
        tick(dog, clock, 9)  # 9 s each: every change resets, no 10 s quiet period ever builds up
    assert alerts == []


def test_watchdog_alerts_when_quiet_and_not_lost_then_rearms() -> None:
    quiet = Classification(NOT_LOST, ("container has not restarted",))
    dog, clock, alerts = make_dog(["a"] * 5, [quiet, quiet])
    tick(dog, clock, 0)   # baseline
    tick(dog, clock, 9)
    assert alerts == []
    tick(dog, clock, 2)   # 11 s quiet
    assert len(alerts) == 1 and alerts[0]["kind"] == "stall" and alerts[0]["classification"]["verdict"] == NOT_LOST
    tick(dog, clock, 5)
    assert len(alerts) == 1, "re-armed: needs another stall period"
    tick(dog, clock, 6)
    assert len(alerts) == 2


def test_watchdog_raises_lost_prompt_when_the_reclassification_says_lost() -> None:
    lost = Classification(LOST, ("proof",), {"x": 1})
    dog, clock, alerts = make_dog(["a"] * 3, [lost])
    tick(dog, clock, 0)
    with pytest.raises(LostPrompt) as caught:
        tick(dog, clock, 11)
    assert caught.value.classification is lost and alerts == []


def test_watchdog_unreadable_probe_is_one_constant_state_not_progress() -> None:
    def boom():
        raise OSError("down")
    clock = {"t": 0.0}
    alerts: list[dict] = []
    dog = StallWatchdog(stall_seconds=10, fingerprint=boom, on_alert=alerts.append,
                        classify=lambda: Classification(UNCERTAIN, ("?",)), clock=lambda: clock["t"])
    for step in (0, 6, 6):
        tick(dog, clock, step)
    assert len(alerts) == 1


def test_expected_seconds_prefers_config_then_plan_estimate_then_fallback() -> None:
    chunk = {"estimate": {"gpu_seconds_linear_by_padded_frames": 80.5, "gpu_seconds_conservative": 175.15}}
    assert expected_seconds(30, chunk) == 30.0
    assert expected_seconds(None, chunk) == 80.5
    assert expected_seconds(None, {"estimate": {"gpu_seconds_conservative": 175.15}}) == 175.15
    assert expected_seconds(None, {}) == FALLBACK_EXPECTED_SECONDS


def test_gpu_bucket_ignores_idle_jitter() -> None:
    assert gpu_bucket([{"gpu_memory_used_mib": 1000}]) == gpu_bucket([{"gpu_memory_used_mib": 1020}])
    assert gpu_bucket([{"gpu_memory_used_mib": 1000}]) != gpu_bucket([{"gpu_memory_used_mib": 9000}])
    assert gpu_bucket(None) is None and gpu_bucket([]) is None


# ---- config keys -------------------------------------------------------------------------
def test_resilience_keys_are_optional_validated_and_default_in_code() -> None:
    machine = loader.resolve_episode("04-milk-and-mom").machine
    assert "resilience" not in machine, "the real machine.json is untouched (plans hash it)"
    base = settings_from_machine(machine)
    assert (base.max_lost_retries, base.stall_factor, base.lost_recheck_seconds, base.expected_chunk_seconds) == (
        1, 3.0, 5.0, None)
    tuned = settings_from_machine({**machine, "resilience": {"max_lost_retries": 2, "stall_factor": 4}})
    assert tuned.max_lost_retries == 2 and tuned.stall_factor == 4 and tuned.lost_recheck_seconds == 5.0
    doc = json.loads((loader.SKILL_ROOT / "schemas" / "machine.schema.json").read_text("utf-8"))
    ok = {**machine, "resilience": {"max_lost_retries": 0, "stall_factor": 1.5}}
    assert schema.validate(ok, doc) == []
    for bad in ({"stall_factor": 0.5}, {"max_lost_retries": -1}, {"max_lost_retries": 9}, {"nope": 1}):
        assert schema.validate({**machine, "resilience": bad}, doc), bad
