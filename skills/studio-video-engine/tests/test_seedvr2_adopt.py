"""SV2-GAP2: ``seedvr2 adopt`` (scratch plan -> episode tree, hash-bound) and the precise protected-tree check."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pytest

from config_fixtures import make_live_action_world
from engine import cli_runtime
from engine.config import loader
from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.seedvr2 import adopt, plan as plan_mod
from engine.seedvr2.execplan import load_exec_plan
from engine.seedvr2.execute import Executor
from exec_fixtures import SHOT, FakeDocker, fake_probe, make_rig
from fake_comfy import FakeComfy

EPISODES_ROOT = loader.REPO_ROOT / plan_mod.EPISODES_DIR


# ---- precise protected-tree check (the 3 basetemp-sensitive CLI tests depend on this) ------
@pytest.fixture(scope="module")
def config():
    return loader.resolve_episode("04-milk-and-mom")


def _jjv_protected(config, segments=None) -> list:
    """Exactly the list bin/jjv.py run_seedvr2_plan passes."""
    return [Path(config.episode_root), Path(config.machine["comfy"]["root"]), segments,
            loader.REPO_ROOT / "production-local", loader.REPO_ROOT]


def test_scratch_under_the_episodes_root_engine_staging_is_accepted(config) -> None:
    scratch = EPISODES_ROOT / "engine" / "staging" / "SV2-GAP2" / "pt" / "test_x0" / "plan"
    assert plan_mod.refuse_output_inside(scratch, _jjv_protected(config)) == scratch.resolve()
    assert plan_mod.refuse_output_inside(loader.REPO_ROOT / "scratch-plan", _jjv_protected(config)) == (
        loader.REPO_ROOT / "scratch-plan").resolve()


def test_the_containers_themselves_and_anything_above_them_stay_refused(config) -> None:
    for bad in (loader.REPO_ROOT, EPISODES_ROOT, loader.REPO_ROOT.parent, EPISODES_ROOT.parent):
        with pytest.raises(Refused, match="protected tree"):
            plan_mod.refuse_output_inside(bad, _jjv_protected(config))


def test_the_precise_trees_inside_a_container_stay_refused(config) -> None:
    episode, comfy = Path(config.episode_root), Path(config.machine["comfy"]["root"])
    segments = episode / "seg"
    for bad in (episode / "x" / "plan", episode, episode.parent, comfy / "input" / "x", segments / "new"):
        with pytest.raises(Refused, match="protected tree"):
            plan_mod.refuse_output_inside(bad, _jjv_protected(config, segments))


def test_another_episode_tree_inside_a_container_is_refused_by_its_marker(tmp_path: Path) -> None:
    other = tmp_path / "prod" / "other-episode"
    (other / "engine").mkdir(parents=True)
    (other / "engine" / "episode.json").write_text("{}", encoding="utf-8")
    mine = tmp_path / "prod" / "mine"
    protected = [mine, tmp_path]
    with pytest.raises(Refused, match="an episode tree"):
        plan_mod.refuse_output_inside(other / "stage" / "plan", protected, containers=[tmp_path])
    with pytest.raises(Refused, match="protected tree"):
        plan_mod.refuse_output_inside(mine / "plan", protected, containers=[tmp_path])
    ok = tmp_path / "prod" / "scratch" / "plan"
    assert plan_mod.refuse_output_inside(ok, protected, containers=[tmp_path]) == ok.resolve()
    with pytest.raises(Refused, match="--into .* protected tree"):
        plan_mod.refuse_output_inside(ok, protected, containers=(), label="--into")  # no container: inside refused


# ---- adopt ------------------------------------------------------------------------------
@pytest.fixture()
def fake():
    with FakeComfy() as server:
        yield server


@pytest.fixture()
def rig(fake, tmp_path):
    """The rig's bound plan copied to a scratch folder OUTSIDE the episode (segments travel with it)."""
    rig = make_rig(tmp_path, fake)
    scratch = tmp_path / "scratch" / "seedvr2-plan"
    shutil.copytree(rig.plan.root, scratch)
    rig.scratch = scratch
    return rig


def _adopt(rig, **kw):
    kw.setdefault("plan_path", rig.scratch / rig.plan.path.name)
    return adopt.adopt_plan(rig.config, rig.recipe, **kw)


def test_adopt_copies_plan_graphs_and_segments_hash_bound_with_a_receipt(rig) -> None:
    out = _adopt(rig)
    into = Path(out["adopted_dir"])
    assert into == Path(rig.config.episode_root) / "engine" / "stages" / "seedvr2" / f"seedvr2-plan-v2-{rig.plan.sha256[:12]}"
    assert out["ok"] and out["already_adopted"] is False and out["plan_sha256"] == rig.plan.sha256
    assert out["graphs"] == len(rig.plan.tasks) == out["segments"] and out["files"] == 1 + 2 * len(rig.plan.tasks)
    receipt = json.loads((into / adopt.ADOPT_FILE).read_text("utf-8"))
    assert receipt["schema"] == adopt.ADOPT_SCHEMA and receipt["plan_sha256"] == rig.plan.sha256
    assert receipt["source_dir"] == str(rig.scratch) and "adopted_at" not in receipt
    for entry in receipt["files"]:
        assert sha256_file(into / entry["path"]) == entry["sha256"] and (into / entry["path"]).stat().st_size == entry["bytes"]
    assert sha256_file(into / "seedvr2-plan-v2.json") == rig.plan.sha256
    assert sorted(p.name for p in rig.scratch.iterdir()) == sorted(p.name for p in rig.plan.root.iterdir())  # untouched


def test_adopted_plan_loads_dry_runs_and_executes_with_receipts_beside_it(rig, fake) -> None:
    adopted = Path(_adopt(rig)["plan_path"])
    plan = load_exec_plan(adopted, rig.config, rig.recipe)
    assert plan.root == adopted.parent and plan.segments_root == adopted.parent and plan.sha256 == rig.plan.sha256
    executor = Executor(config=rig.config, recipe=rig.recipe, plan=plan, settings=rig.settings,
                        repo_root=loader.REPO_ROOT, probe=fake_probe, runner=rig.ffmpeg,
                        emit=lambda m: None, container_probe=FakeDocker())
    assert len(executor.dry_run(list(plan.tasks))) == len(plan.tasks) and fake.requests == []
    result = executor.run(plan.tasks[:1])
    assert result["exit_code"] == 0 and [c["status"] for c in result["completed"]] == ["COMPLETED"]
    assert (adopted.parent / "runs" / SHOT / "chunk-0000" / "job.json").is_file()
    assert not (rig.scratch / "runs").exists() and len(fake.posts_made()) == 1


def test_re_adopting_identical_bytes_is_a_no_op_and_drift_is_refused(rig) -> None:
    first = _adopt(rig)
    again = _adopt(rig)
    assert again["already_adopted"] is True and again["receipt_sha256"] == first["receipt_sha256"]
    into = Path(first["adopted_dir"])
    graph = next((into / "workflows").rglob("*.api.json"))
    graph.write_text(graph.read_text("utf-8") + "\n", encoding="utf-8")  # same canonical content, other bytes
    with pytest.raises(Refused, match="refusing to overwrite"):
        _adopt(rig)


def test_a_tampered_scratch_graph_or_segment_is_refused_before_anything_is_written(rig) -> None:
    graph = next((rig.scratch / "workflows").rglob("*.api.json"))
    data = json.loads(graph.read_text("utf-8"))
    data["10"]["inputs"]["seed"] = 12345
    graph.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="canonical API graph hash changed"):
        _adopt(rig, into=Path(rig.config.episode_root) / "adopted")
    assert not (Path(rig.config.episode_root) / "adopted").exists()
    shutil.copyfile(rig.plan.root / graph.relative_to(rig.scratch), graph)
    segment = rig.scratch / SHOT / "chunks" / "chunk-0001" / "source-segment.mp4"
    segment.write_bytes(segment.read_bytes() + b"x")
    with pytest.raises(Refused, match="chunk-0001 segment hash mismatch"):
        _adopt(rig, into=Path(rig.config.episode_root) / "adopted")
    assert not (Path(rig.config.episode_root) / "adopted").exists()


def test_a_pending_or_foreign_plan_is_refused_like_execute_would(rig, tmp_path: Path) -> None:
    pending = tmp_path / "pending"
    pending.mkdir()
    text = (rig.scratch / rig.plan.path.name).read_text("utf-8").replace('"PLANNED_NOT_RENDERED"', '"PLANNED_SEGMENTS_PENDING"')
    (pending / rig.plan.path.name).write_text(text, encoding="utf-8")
    with pytest.raises(Refused, match="PLANNED_NOT_RENDERED"):
        _adopt(rig, plan_path=pending / rig.plan.path.name)
    foreign = tmp_path / "foreign"
    shutil.copytree(rig.scratch, foreign)
    data = json.loads((foreign / rig.plan.path.name).read_text("utf-8"))
    data["episode_id"] = "someone-else"
    (foreign / rig.plan.path.name).write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refused, match="episode_id"):
        _adopt(rig, plan_path=foreign / rig.plan.path.name)


@pytest.mark.parametrize("where,text", [
    ("outside", "escaped"), ("comfy", "escaped"), ("root", "episode root or its engine"),
    ("engine", "episode root or its engine"), ("scratch", "--into .* protected tree"), ("segments", "--into .* protected tree"),
])
def test_destinations_that_are_not_a_fresh_sub_folder_of_the_episode_are_refused(rig, tmp_path: Path, where, text) -> None:
    """Scratch plan and segments root sit INSIDE the episode here, so their refusal is the protected-tree one."""
    episode = Path(rig.config.episode_root)
    scratch = episode / "scratch-plan"
    shutil.copytree(rig.scratch, scratch)
    segments = episode / "segments"
    shutil.copytree(scratch / SHOT, segments / SHOT)
    into = {"outside": tmp_path / "elsewhere", "comfy": Path(rig.config.machine["comfy"]["root"]) / "input" / "x",
            "root": episode, "engine": episode / "engine", "scratch": scratch / "sub", "segments": segments / "x"}[where]
    with pytest.raises(Refused, match=text):
        _adopt(rig, plan_path=scratch / rig.plan.path.name, segments_root=segments, into=into)
    used = episode / "used"
    used.mkdir()
    (used / "old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Refused, match="not empty"):
        _adopt(rig, into=used)


def test_segments_may_come_from_another_root_and_the_adopted_folder_is_self_contained(rig, tmp_path: Path) -> None:
    elsewhere = tmp_path / "segments-elsewhere"
    shutil.copytree(rig.scratch / SHOT, elsewhere / SHOT)
    shutil.rmtree(rig.scratch / SHOT)
    with pytest.raises(Refused, match="segment is missing"):
        _adopt(rig)
    out = _adopt(rig, segments_root=elsewhere)
    into = Path(out["adopted_dir"])
    assert out["segments"] == len(rig.plan.tasks) and (into / SHOT / "chunks" / "chunk-0000" / "source-segment.mp4").is_file()
    assert load_exec_plan(Path(out["plan_path"]), rig.config, rig.recipe).segments_root == into


def test_a_scratch_tails_plan_adopts_the_same_way(tmp_path: Path) -> None:
    from engine.seedvr2 import tails
    from test_seedvr2_segments_support import fake_probe as support_probe, make_world as make_support_world
    world = make_support_world(tmp_path)
    scratch = tmp_path / "tails-scratch"  # what `tails plan --scratch` writes (outside the episode)
    planned = tails.plan_tails(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, out=scratch,
                               probe=support_probe, runner=world.runner)
    assert planned["status"] == "PLANNED_NOT_RENDERED"
    out = adopt.adopt_plan(world.config, world.recipe, plan_path=adopt.resolve_plan_file(scratch))
    assert Path(out["adopted_dir"]).name.startswith("seedvr2-tails-plan-v2-") and out["segments"] == planned["segments_cut"]
    adopted = load_exec_plan(Path(out["plan_path"]), world.config, world.recipe)
    assert adopted.plan["kind"] == "tails" and adopted.root == Path(world.config.episode_root) / "engine" / "stages" / "seedvr2" / Path(out["adopted_dir"]).name
    assert json.loads((Path(out["adopted_dir"]) / adopt.ADOPT_FILE).read_text("utf-8"))["plan_kind"] == "tails"


# ---- CLI handler (the parser bin/jjv.py wires through CLI-PATCH-adopt.md) ------------------
def _parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="jjv")
    verbs = top.add_subparsers(dest="stage", required=True).add_parser("seedvr2").add_subparsers(dest="verb", required=True)
    adopt.register_cli(verbs)
    return top


def test_cli_adopt_then_jjv_execute_accepts_the_adopted_plan_and_refuses_the_scratch_one(rig, fake, monkeypatch, capsys) -> None:
    monkeypatch.setattr(adopt, "resolve_episode", lambda ref: rig.config)
    code = adopt.run(_parser().parse_args(["seedvr2", "adopt", "--episode", "x", "--plan", str(rig.scratch)]))
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] and out["next"].startswith("jjv seedvr2 execute")
    monkeypatch.setattr(cli_runtime, "resolve_episode", lambda ref: rig.config)
    real = cli_runtime.Executor
    monkeypatch.setattr(cli_runtime, "Executor", lambda **kw: real(
        **kw, probe=fake_probe, runner=rig.ffmpeg, emit=lambda m: None, container_probe=FakeDocker()))
    argv = ["seedvr2", "execute", "--episode", "x", "--execute", "--no-telemetry", "--max-chunks", "1", "--plan"]
    code = _jjv().main([*argv, str(rig.scratch / rig.plan.path.name)])
    assert code == 1 and "escaped" in json.loads(capsys.readouterr().out)["error"] and fake.posts_made() == []
    code = _jjv().main([*argv, out["plan_path"]])
    summary = json.loads(capsys.readouterr().out)
    assert code == 0 and summary["ok"] and summary["plan_sha256"] == rig.plan.sha256 and len(fake.posts_made()) == 1


def test_cli_adopt_plan_folder_must_hold_exactly_one_plan_file(rig, tmp_path: Path) -> None:
    with pytest.raises(Refused, match="exactly one of"):
        adopt.resolve_plan_file(tmp_path)
    assert adopt.resolve_plan_file(rig.scratch) == (rig.scratch / "seedvr2-plan-v2.json").resolve()
    with pytest.raises(Refused, match="not found"):
        adopt.resolve_plan_file(tmp_path / "nope")


def test_cli_adopt_refuses_a_domain_without_a_qualified_recipe(tmp_path: Path, monkeypatch) -> None:
    world = make_live_action_world(tmp_path)
    live = loader.resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    monkeypatch.setattr(adopt, "resolve_episode", lambda ref: live)
    with pytest.raises(Refused, match="no qualified seedvr2 recipe"):
        adopt.run(_parser().parse_args(["seedvr2", "adopt", "--episode", "x", "--plan", str(tmp_path)]))


def _jjv():
    import importlib.util
    spec = importlib.util.spec_from_file_location("jjv_cli_adopt", loader.SKILL_ROOT / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- hygiene ----------------------------------------------------------------------------
def test_adopt_module_is_small_and_neutral() -> None:
    text = Path(adopt.__file__).read_text(encoding="utf-8")
    assert len(text.splitlines()) < 400
    for token in ("jenniejoy", "newtecons", "ep04", "04-milk", "8188"):
        assert token not in text.lower(), token
