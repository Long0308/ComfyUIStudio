"""T-E15g critic fix round: regression tests written RED first (probes A-D plus plan binding,
native sizes and the custom-node allowlist)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from engine.comfy import dispatch as dsp
from engine.comfy import guards
from engine.comfy.client import ComfyClient
from engine.comfy.settings import ComfySettings
from engine.config import loader
from engine.core.errors import Refused, Uncertain
from engine.core.io import canonical_sha256
from engine.media.probe import VideoInfo
from engine.seedvr2 import plan as plan_mod
from fractions import Fraction
from exec_fixtures import SHOT, fake_probe, make_rig, media_bytes
from fake_comfy import FakeComfy

GRAPH = {"1": {"class_type": "LocalNode", "inputs": {"x": 1}}}


@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


def crash_after_post(rig) -> None:
    executor = rig.executor()

    def die(*args, **kwargs):
        raise KeyboardInterrupt("simulated crash after POST")

    executor.materialize = die  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        executor.run(rig.tasks(max_chunks=1))
    assert rig.job(0)["status"] == "SUBMITTED"


def job_bytes(rig) -> bytes:
    return (rig.chunk_dir(0) / "job.json").read_bytes()


# ---- Probe A: no second POST for a chunk with ANY post evidence --------------------------
@pytest.mark.parametrize("delete", [["dispatch-intent.json"],
                                    ["dispatch-intent.json", "submitted.json"],
                                    ["dispatch-intent.json", "submitted.json", "job.json"]])
def test_A_a_deleted_intent_never_leads_to_a_second_post(fake, tmp_path, delete) -> None:
    rig = make_rig(tmp_path, fake)
    crash_after_post(rig)
    for name in delete:
        (rig.chunk_dir(0) / name).unlink()
    survivors = {p.name for p in rig.chunk_dir(0).iterdir()}
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert len(fake.posts_made()) == 1, "never a second POST"
    assert result["exit_code"] == 2 and result["stopped"]["stage"] in {"intent_missing", "post_evidence"}
    if "job.json" in survivors:
        assert rig.job(0)["prompt_id"] == "pid-0001", "the prompt_id is not replaced"


def test_A_unknown_receipt_alone_blocks_a_new_post(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    fake.post_mode = "drop"
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 2
    (rig.chunk_dir(0) / "dispatch-intent.json").unlink()
    (rig.chunk_dir(0) / "job.json").unlink()
    fake.post_mode = "normal"
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1


@pytest.mark.parametrize("name", ["dispatch-intent.json", "submitted.json", "submit-unknown.json",
                                  "reconciled.json"])
def test_A_dispatch_itself_refuses_when_any_post_evidence_exists(fake, tmp_path, name) -> None:
    settings = ComfySettings(base_url=fake.url, lock_path=tmp_path / "gpu.lock", input_dir=tmp_path / "in",
                             output_dir=tmp_path / "out", container="c", lock_timeout_seconds=0.2)
    (tmp_path / "rc").mkdir()
    (tmp_path / "rc" / name).write_text("{}")
    with pytest.raises(Refused, match="already holds"):
        dsp.dispatch(ComfyClient(fake.url, timeout_seconds=5), settings, graph=GRAPH,
                     receipt_dir=tmp_path / "rc", identity={"kind": "t"})
    assert fake.requests == []


# ---- Probe B: state refusals never rewrite job.json; "posted" comes from disk -------------
def test_B_rerun_without_resume_after_a_crashed_post_keeps_job_json_and_is_exit_two(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    crash_after_post(rig)
    before = job_bytes(rig)
    result = rig.executor().run(rig.tasks(max_chunks=1))
    assert result["exit_code"] == 2, "a POST happened earlier: never 1"
    assert job_bytes(rig) == before and rig.job(0)["status"] == "SUBMITTED"
    note = json.loads((rig.chunk_dir(0) / "job-check-failure.json").read_text())
    assert note["posted"] is True and note["stage"] == "existing_state"
    assert len(fake.posts_made()) == 1


def test_B_posted_is_derived_from_disk_not_from_this_attempt(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    result = rig.executor().run(rig.tasks(max_chunks=1))  # fresh executor, nothing posted by it
    assert result["exit_code"] == 2 and result["stopped"]["posted"] is True


# ---- Probe C: an unreadable or foreign job.json is never overwritten ----------------------
def test_C_unreadable_job_json_is_preserved_and_stops_with_exit_two(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    (rig.chunk_dir(0) / "job.json").write_text("{garbage", encoding="ascii")
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and len(fake.posts_made()) == 1
    assert (rig.chunk_dir(0) / "job.json").read_text(encoding="ascii") == "{garbage"
    assert (rig.chunk_dir(0) / "job-check-failure.json").is_file()


def test_C_identity_mismatched_job_json_is_preserved(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    assert rig.executor().run(rig.tasks(max_chunks=1))["exit_code"] == 0
    job = rig.job(0)
    job["segment_sha256"] = "0" * 64
    (rig.chunk_dir(0) / "job.json").write_text(json.dumps(job))
    before = job_bytes(rig)
    result = rig.executor().run(rig.tasks(max_chunks=1), resume=True)
    assert result["exit_code"] == 2 and job_bytes(rig) == before and len(fake.posts_made()) == 1


# ---- Probe D: ClaudeNode is refused under ANY policy -------------------------------------
@pytest.mark.parametrize("policy", [guards.ClassPolicy(frozenset(), False),
                                    guards.ClassPolicy(frozenset({"other"}), True)])
def test_D_claudenode_is_refused_under_any_policy(policy) -> None:
    graph = {"1": {"class_type": "ClaudeNode", "inputs": {}}}
    with pytest.raises(Refused, match="ClaudeNode"):
        guards.check_graph(None, graph, policy)
    assert guards.static_refusals(["claudenode"], policy)


def test_D_claudenode_is_refused_before_any_network_even_with_a_client(fake) -> None:
    with pytest.raises(Refused):
        guards.check_graph(ComfyClient(fake.url, timeout_seconds=5),
                           {"1": {"class_type": "ClaudeNode", "inputs": {}}},
                           guards.ClassPolicy(frozenset(), False))
    assert fake.requests == []


# ---- custom-node allowlist (domain allowed_custom_nodes) ---------------------------------
def test_custom_node_packs_must_be_on_the_domain_allowlist(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    policy = guards.ClassPolicy.from_domain({"forbidden_node_classes": [], "forbid_partner_nodes": True,
                                             "allowed_custom_nodes": ["Comfyui-Krea2Edit"]})
    fake.object_info["Mine"] = {"python_module": "custom_nodes.comfyui-krea2edit", "category": "x"}
    fake.object_info["Evil"] = {"python_module": "custom_nodes.evilpack.nodes", "category": "x"}
    fake.object_info["Core"] = {"python_module": "comfy_extras.nodes_seedvr", "category": "x"}
    for ok in ("Mine", "Core", "LocalNode"):
        guards.check_graph(client, {"1": {"class_type": ok, "inputs": {}}}, policy)
    with pytest.raises(Refused, match="evilpack"):
        guards.check_graph(client, {"1": {"class_type": "Evil", "inputs": {}}}, policy)


def test_a_policy_without_an_allowlist_refuses_every_custom_node(fake) -> None:
    client = ComfyClient(fake.url, timeout_seconds=5)
    fake.object_info["Mine"] = {"python_module": "custom_nodes.comfyui-krea2edit"}
    with pytest.raises(Refused, match="custom node"):
        guards.check_graph(client, {"1": {"class_type": "Mine", "inputs": {}}},
                           guards.ClassPolicy(frozenset(), True))


# ---- plan binding: machine + domain, with a clear re-plan message --------------------------
def test_plan_is_bound_to_the_machine_config(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    for key, value in (("gpu_lock_path", str(tmp_path / "other.lock")),
                       ("comfy", {**rig.config.machine["comfy"], "url": "http://127.0.0.1:1"}),
                       ("comfy", {**rig.config.machine["comfy"], "container": "elsewhere"}),
                       ("comfy", {**rig.config.machine["comfy"], "output_dir": str(tmp_path / "o2")})):
        moved = dataclasses.replace(rig.config, machine={**rig.config.machine, key: value})
        with pytest.raises(Refused, match="re-plan"):
            loader_load(rig, moved)


def test_plan_is_bound_to_the_domain_config(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    tightened = dataclasses.replace(rig.config, domain={
        **rig.config.domain, "forbidden_node_classes": [*rig.config.domain["forbidden_node_classes"], "X"]})
    with pytest.raises(Refused, match="re-plan"):
        loader_load(rig, tightened)


def test_a_plan_without_the_bindings_is_refused(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    plan = json.loads(rig.plan.path.read_text())
    plan.pop("machine_sha256")
    rig.plan.path.write_text(json.dumps(plan))
    with pytest.raises(Refused, match="re-plan"):
        rig.reload_plan()


def loader_load(rig, config):
    from engine.seedvr2.execplan import load_exec_plan
    return load_exec_plan(rig.plan.path, config, rig.recipe)


# ---- sizes come from the recipe ------------------------------------------------------------
def test_a_source_that_is_not_the_recipe_native_size_is_refused_at_plan_time(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)

    def half(path, *, count_packets=False):
        info = fake_probe(path, count_packets=count_packets)
        return VideoInfo(frames=info.frames, width=432, height=240, fps=Fraction(24))  # same aspect

    with pytest.raises(Refused, match="native"):
        plan_mod.build_plan(rig.config, repo_root=loader.REPO_ROOT, segments_root=rig.plan.segments_root,
                            probe=half)


def test_plan_source_video_must_match_the_recipe_native_size(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    plan = json.loads(rig.plan.path.read_text())
    plan["shots"][0]["source_video"]["width"] = 432
    rig.plan.path.write_text(json.dumps(plan))
    with pytest.raises(Refused, match="native"):
        rig.reload_plan()


def test_the_executor_checks_segments_against_the_recipe_native_size_not_the_plan(fake, tmp_path) -> None:
    rig = make_rig(tmp_path, fake)
    native = dict(rig.recipe["native"])
    assert native == {"width": 864, "height": 480}
    executor = rig.executor()
    seen: list = []
    real = executor.probe

    def spy(path, **kw):
        info = real(path, **kw)
        seen.append((info.width, info.height))
        return info

    executor.probe = spy
    executor.dry_run(rig.tasks(max_chunks=1))
    assert seen == [(864, 480)]
    # a tampered plan size cannot widen the check: the segment is verified against recipe.native
    segment = rig.plan.segments_root / SHOT / "chunks" / "chunk-0000" / "source-segment.mp4"
    segment.write_bytes(media_bytes(17, 432, 240, "seg0"))
    with pytest.raises(Refused, match="hash mismatch"):
        executor.dry_run(rig.tasks(max_chunks=1))
