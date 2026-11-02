"""M4: staging, guards, wait, client, outputs, telemetry, run lock, atomic writes, comfy verbs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from engine.comfy import commands, guards, staging
from engine.comfy.client import ComfyClient, ComfyError
from engine.comfy.dispatch import dispatch
from engine.comfy.outputs import collect_outputs, node_output_entries, resolve_output
from engine.comfy.settings import ComfySettings, settings_from_machine
from engine.comfy.telemetry import TelemetrySampler
from engine.comfy.wait import wait_for_history
from engine.core import io
from engine.core.errors import Failed, Refused, Uncertain, WaitTimeout
from engine.core.filelock import run_lock
from fake_comfy import FakeComfy

GRAPH = {"1": {"class_type": "LocalNode", "inputs": {"x": 1}},
         "2": {"class_type": "SaveVideo", "inputs": {"video": ["1", 0]}}}
POLICY = guards.ClassPolicy(frozenset({"claudenode", "badnode"}), True)


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def settings_for(fake, tmp_path, **kw) -> ComfySettings:
    return ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                         output_dir=tmp_path / "out", container="Comfyui-Studio", lock_timeout_seconds=0.2,
                         poll_seconds=0.01, **kw)


# ---- staging (I8) ------------------------------------------------------------------------
def test_stage_copies_verifies_links_and_leaves_no_temp(tmp_path) -> None:
    source = tmp_path / "seg.mp4"
    source.write_bytes(b"segment")
    target = staging.stage_input(source, tmp_path / "in", "x.mp4", sha(b"segment"))
    assert target.read_bytes() == b"segment" and [p.name for p in (tmp_path / "in").iterdir()] == ["x.mp4"]
    assert staging.stage_input(source, tmp_path / "in", "x.mp4", sha(b"segment")) == target  # idempotent


def test_stage_refuses_a_foreign_existing_file_and_keeps_it(tmp_path) -> None:
    source = tmp_path / "seg.mp4"
    source.write_bytes(b"segment")
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "x.mp4").write_bytes(b"foreign")
    with pytest.raises(Refused, match="hash mismatch"):
        staging.stage_input(source, tmp_path / "in", "x.mp4", sha(b"segment"))
    assert (tmp_path / "in" / "x.mp4").read_bytes() == b"foreign"


def test_stage_refuses_when_the_source_does_not_match_its_pin(tmp_path) -> None:
    source = tmp_path / "seg.mp4"
    source.write_bytes(b"segment")
    with pytest.raises(Refused, match="source for staging"):
        staging.stage_input(source, tmp_path / "in", "x.mp4", sha(b"other"))
    assert not (tmp_path / "in" / "x.mp4").exists()


def test_stage_collision_during_link_is_verified_not_overwritten(tmp_path, monkeypatch) -> None:
    source = tmp_path / "seg.mp4"
    source.write_bytes(b"segment")
    real_link = os.link

    def racing_link(src, dst, *a, **k):  # a foreign writer wins the race
        Path(dst).write_bytes(b"foreign")
        return real_link(src, dst, *a, **k)

    monkeypatch.setattr(staging.os, "link", racing_link)
    with pytest.raises(Refused, match="concurrent"):
        staging.stage_input(source, tmp_path / "in", "x.mp4", sha(b"segment"))
    assert (tmp_path / "in" / "x.mp4").read_bytes() == b"foreign"
    assert [p.name for p in (tmp_path / "in").iterdir()] == ["x.mp4"]


@pytest.mark.parametrize("name", ["../x.mp4", "a/b.mp4", "", "..", "C:\\x.mp4"])
def test_unsafe_input_names_are_refused(tmp_path, name) -> None:
    with pytest.raises(Refused):
        staging.input_target(tmp_path, name)


def test_input_state_reports_present_missing_and_checks_the_hash(tmp_path) -> None:
    assert staging.input_state(tmp_path, "x.mp4", sha(b"a"))[1] == "missing"
    (tmp_path / "x.mp4").write_bytes(b"a")
    assert staging.input_state(tmp_path, "x.mp4", sha(b"a"))[1] == "present"
    with pytest.raises(Refused):
        staging.input_state(tmp_path, "x.mp4", sha(b"b"))


# ---- guards (I12) ------------------------------------------------------------------------
def test_sha_mismatch_refuses() -> None:
    guards.require_sha("a" * 64, None, "graph")
    guards.require_sha("a" * 64, "A" * 64, "graph")
    with pytest.raises(Refused, match="sha256 mismatch"):
        guards.require_sha("a" * 64, "b" * 64, "graph")


def test_claudenode_is_refused_statically_without_any_network() -> None:
    graph = {**GRAPH, "3": {"class_type": "ClaudeNode", "inputs": {}}}
    with pytest.raises(Refused, match="forbidden by policy"):
        guards.check_graph(None, graph, POLICY)
    # ...and under a policy that lists nothing and allows partners (the old tautology hid this)
    with pytest.raises(Refused, match="ClaudeNode"):
        guards.check_graph(None, graph, guards.ClassPolicy.from_domain(
            {"forbidden_node_classes": [], "forbid_partner_nodes": False}))


def test_domain_forbidden_class_is_refused_case_insensitively() -> None:
    with pytest.raises(Refused, match="BadNode"):
        guards.check_graph(None, {"1": {"class_type": "BadNode", "inputs": {}}}, POLICY)


def test_partner_and_unknown_classes_are_refused_via_object_info(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.object_info["CloudThing"] = {"python_module": "comfy_api_nodes.x", "category": "api node/x"}
    fake.object_info["FlagThing"] = {"api_node": True}
    fake.unknown.add("Nope")
    for name, text in (("CloudThing", "partner"), ("FlagThing", "partner"), ("Nope", "unknown")):
        with pytest.raises(Refused, match=text):
            guards.check_graph(client, {"1": {"class_type": name, "inputs": {}}}, POLICY)
    assert guards.check_graph(client, GRAPH, POLICY) == ["LocalNode", "SaveVideo"]


def test_partner_is_allowed_only_when_the_domain_allows_it_unknown_never(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.object_info["CloudThing"] = {"python_module": "comfy_api_nodes.x"}
    fake.unknown.add("Nope")
    lax = guards.ClassPolicy(frozenset({"claudenode"}), False)
    guards.check_graph(client, {"1": {"class_type": "CloudThing", "inputs": {}}}, lax)
    with pytest.raises(Refused, match="unknown"):
        guards.check_graph(client, {"1": {"class_type": "Nope", "inputs": {}}}, lax)


def test_object_info_failure_refuses_and_verdicts_are_cached(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    cache: dict = {}
    guards.check_graph(client, GRAPH, POLICY, cache=cache)
    guards.check_graph(client, GRAPH, POLICY, cache=cache)
    assert len([r for r in fake.requests if r[1].startswith("/object_info/")]) == 2
    dead = ComfyClient("http://127.0.0.1:9", timeout_seconds=1)  # discard port: nothing listens
    with pytest.raises(Refused, match="cannot verify"):
        guards.check_graph(dead, GRAPH, POLICY)


@pytest.mark.parametrize("graph,text", [({}, "non-empty"), ([], "non-empty"),
                                        ({"nodes": [], "links": []}, "UI export"),
                                        ({"1": {"inputs": {}}}, "no class_type")])
def test_graph_shape_is_validated(graph, text) -> None:
    with pytest.raises(Refused, match=text):
        guards.graph_class_types(graph)


# ---- client ------------------------------------------------------------------------------
def test_client_has_explicit_timeouts_and_wraps_every_failure(fake) -> None:
    with pytest.raises(ValueError):
        ComfyClient(fake.url, timeout_seconds=0)
    fake.get_delay = 1.0
    with pytest.raises(ComfyError, match="failed"):
        ComfyClient(fake.url, timeout_seconds=0.2).get("/queue")
    fake.get_delay = 0
    fake.queue_mode = "incomplete"
    with pytest.raises(ComfyError, match="IncompleteRead"):
        ComfyClient(fake.url, timeout_seconds=5).get("/queue")
    fake.queue_mode = "status:500"
    with pytest.raises(ComfyError) as error:
        ComfyClient(fake.url, timeout_seconds=5).get("/queue")
    assert error.value.http_status == 500 and isinstance(error.value, Uncertain)
    with pytest.raises(ValueError):
        ComfyClient(fake.url).get("queue")


# ---- wait --------------------------------------------------------------------------------
def test_wait_returns_the_entry_and_tolerates_flaky_reads(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.add_history("p1", GRAPH, "c")
    fake.history_fail_count = 2
    assert wait_for_history(client, "p1", timeout_seconds=5, poll_seconds=0.01)["status"]["completed"]


def test_wait_timeout_is_exit_three_with_evidence_and_never_posts(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.history_mode = "incomplete"
    with pytest.raises(WaitTimeout) as error:
        wait_for_history(client, "p-x", timeout_seconds=0.2, poll_seconds=0.01)
    assert error.value.exit_code == 3 and error.value.evidence["poll_error_count"] >= 1
    assert "IncompleteRead" in error.value.evidence["poll_error_tail"][-1]
    assert fake.posts_made() == []
    with pytest.raises(ValueError):
        wait_for_history(client, "", timeout_seconds=1, poll_seconds=0.1)


# ---- outputs -----------------------------------------------------------------------------
def test_outputs_resolve_inside_the_root_and_hash(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.mp4").write_bytes(b"video")
    entry = {"outputs": {"15": {"images": [{"filename": "a.mp4", "subfolder": "sub", "type": "output"}],
                                "animated": [True]}}}
    assert len(node_output_entries(entry, "15")) == 1 and node_output_entries(entry, "9") == []
    (record,) = collect_outputs(entry, tmp_path)
    assert record["sha256"] == sha(b"video") and record["exists"] is True
    with pytest.raises(Refused):
        resolve_output(tmp_path, {"filename": "../../x.mp4", "subfolder": "sub"})
    with pytest.raises(Failed, match="missing"):
        resolve_output(tmp_path, {"filename": "none.mp4", "subfolder": ""})
    with pytest.raises(Failed, match="type"):
        resolve_output(tmp_path, {"filename": "a.mp4", "subfolder": "sub", "type": "temp"})


# ---- telemetry (optional) ----------------------------------------------------------------
def test_telemetry_uses_the_injected_runner_and_survives_failures(tmp_path) -> None:
    calls: list = []

    def runner(command):
        calls.append(command[0])
        if command[0] == "docker":
            return subprocess.CompletedProcess(command, 0, "x 1.5GiB / 31.2GiB y", "")
        raise OSError("no nvidia-smi")

    with TelemetrySampler(container="c", samples_path=tmp_path / "t.json", runner=runner,
                          interval_seconds=0.05) as sampler:
        pass
    summary = sampler.summary()
    assert summary["container_memory_peak_bytes"] == int(1.5 * 1024 ** 3)
    assert summary["gpu_memory_peak_mib"] is None and summary["sample_count"] >= 2
    assert json.loads((tmp_path / "t.json").read_text())[0]["container_memory_limit_bytes"]
    assert "docker" in calls and "nvidia-smi" in calls
