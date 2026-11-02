"""``jjv seedvr2 tails plan``: gaps -> sub-range sources -> a plan the existing execute path accepts."""

from __future__ import annotations

import copy
import json
from argparse import Namespace
from pathlib import Path

import pytest

from engine.config import loader
from engine.core.errors import Refused
from engine.seedvr2 import cli_cut, tails
from engine.seedvr2.coverage import Gap, Read
from engine.seedvr2.execplan import load_exec_plan
from test_seedvr2_segments_support import fake_probe, make_world, read_ids

GEOMETRY = {"core_frames": 13, "context_frames_each_side": 4}


@pytest.fixture()
def world(tmp_path: Path):
    return make_world(tmp_path)


def plan_it(world, out: Path, **kw):
    kw.setdefault("probe", fake_probe)
    kw.setdefault("runner", world.runner)
    return tails.plan_tails(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, out=out, **kw)


# ---- context rule ------------------------------------------------------------------------------
@pytest.mark.parametrize("gap,before,expected", [
    (3, 100, 4),    # ep04 S03_B / S04_B: 7 frames = 4 context + 3 tail
    (10, 92, 3),    # ep04 v005 S05_B: 10 tail frames leave room for 3, so it still plans as ONE chunk
    (7, 100, 4),    # ep04 v005 S03_B
    (13, 100, 4),   # a whole core: no cap, the recipe context
    (20, 100, 4),   # longer than a core: several chunks, recipe context
    (3, 2, 2),      # only 2 frames exist before the gap
    (3, 0, 0),      # the gap starts at frame 0
    (12, 100, 1),   # 12 + 1 == 13
])
def test_context_rule(gap, before, expected) -> None:
    assert tails.context_frames(gap, before, GEOMETRY) == expected


# ---- ranges per shot ---------------------------------------------------------------------------
def gap(shot, a, b, source=None, transition=None) -> Gap:
    return Gap(shot, a, b, (Read(shot, a, b, f"T{a}", source, transition),))


SRC = {"path": "n.mp4", "sha256": "ab" * 32, "frames": 50}


def test_two_gaps_of_a_shot_become_one_spanning_range() -> None:
    shots = tails.tail_shots([gap("A", 20, 22, SRC), gap("A", 30, 31, SRC)], GEOMETRY)
    assert [(s.shot_id, s.start, s.end, s.context) for s in shots] == [("A", 18, 31, 2)]  # 11 frames span: context capped to 2 so it is still ONE chunk
    assert len(shots[0].gaps) == 2


def test_a_gap_without_a_source_clip_is_refused() -> None:
    with pytest.raises(Refused, match="no source clip is declared"):
        tails.tail_shots([gap("A", 20, 22)], GEOMETRY)


def test_two_different_sources_for_one_shot_are_refused() -> None:
    with pytest.raises(Refused, match="2 different source clips"):
        tails.tail_shots([gap("A", 20, 22, SRC), gap("A", 30, 31, {**SRC, "path": "m.mp4"})], GEOMETRY)


def test_a_gap_past_the_source_clip_is_refused() -> None:
    with pytest.raises(Refused, match="source clip has 50 frames"):
        tails.tail_shots([gap("A", 48, 52, SRC)], GEOMETRY)


# ---- the plan ----------------------------------------------------------------------------------
def test_pending_tails_plan_names_ranges_and_closes_the_coverage(world) -> None:
    result = tails.build_tails_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, probe=fake_probe)
    plan = result.plan
    assert plan["kind"] == "tails" and plan["status"] == "PLANNED_SEGMENTS_PENDING"
    assert plan["tails"] == {"gap_count": 1, "gap_frames": 3, "shots": ["S01_A"], "extra_scope": []}
    shot = plan["shots"][0]
    assert shot["source_range"] == {"start_frame": 36, "end_frame_exclusive": 43, "source_frames_total": 47}
    assert shot["source_video"]["frames"] == 7 and shot["chunk_count"] == 1
    assert shot["tail"]["context_before_frames"] == 4 and shot["tail"]["restored_gap_frames"] == 3
    assert shot["tail"]["gaps"][0]["transitions"][0]["id"] == "T40"
    assert plan["coverage"]["ok"] and plan["coverage"]["scope"]["S01_A"] == [[0, 43]]
    assert plan["naming"]["output_prefix_template"].endswith("/tails/{shot}/{chunk}")
    assert plan["totals"]["total_source_frames"] == 7 and result.graphs == {}


def test_no_gap_means_no_plan(world) -> None:
    assert tails.build_tails_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads[:2],
                                  probe=fake_probe) is None
    summary = plan_it(world, world.tmp / "none")
    covered = tails.plan_tails(world.config, repo_root=loader.REPO_ROOT, reads=world.reads[:2],
                               out=world.tmp / "never", probe=fake_probe)
    assert covered["gaps"] == 0 and not (world.tmp / "never").exists() and summary["gaps"] == 1


def test_an_existing_tail_scope_removes_the_gap(world) -> None:
    assert tails.build_tails_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads,
                                  extra_scope=[("S01_A", 36, 43)], probe=fake_probe) is None


def test_native_source_that_changed_is_refused(world) -> None:
    from test_seedvr2_segments_support import write_media
    write_media(world.native, [f"X:{i}" for i in range(47)], 864, 480)
    with pytest.raises(Refused, match="source sha256"):
        tails.build_tails_plan(world.config, repo_root=loader.REPO_ROOT, reads=world.reads, probe=fake_probe)


def test_plan_tails_cuts_sub_range_sources_and_the_plan_loads_in_the_existing_execute_path(world) -> None:
    out = world.root / "tails-run"
    dry = plan_it(world, out, dry_run=True)
    assert dry["dry_run"] and not out.exists() and world.runner.commands == []
    summary = plan_it(world, out)
    assert summary["status"] == "PLANNED_NOT_RENDERED" and summary["segments_cut"] == 1
    segment = out / "S01_A/chunks/chunk-0000/source-segment.mp4"
    assert read_ids(segment) == [f"S01_A:{i}" for i in range(36, 43)], "frames 36..42 of the NATIVE clip"
    assert (out / tails.TAILS_PLAN_FILE).is_file() and (out / "segments-receipt.json").is_file()
    plan = load_exec_plan(out / tails.TAILS_PLAN_FILE, world.config, world.recipe)
    assert [t.shot_id for t in plan.tasks] == ["S01_A"] and plan.plan["kind"] == "tails"
    assert plan.tasks[0].chunk["core_frames"] == 7 and plan.tasks[0].chunk["segment_frames"] == 7


# ---- the execute loader treats a tails plan as a tails plan only -----------------------------------
def planned(world) -> dict:
    out = world.root / "tails-run"
    plan_it(world, out)
    return json.loads((out / tails.TAILS_PLAN_FILE).read_text())


def reload(world, plan: dict, tmp: Path):
    path = tmp / "p.json"
    path.write_text(json.dumps(plan))
    return load_exec_plan(path, world.config, world.recipe)


@pytest.mark.parametrize("edit,match", [
    (lambda p: p.update(kind="weird"), "kind"),
    (lambda p: p.pop("kind"), "plan shots differ from the episode shots"),
    (lambda p: p["shots"][0].pop("source_range"), "needs a source_range"),
    (lambda p: p["shots"][0]["source_range"].update(end_frame_exclusive=50), "not inside the source|planned frames"),
    (lambda p: p["shots"][0].update(source_sha256="nothex"), "not a sha256"),
    (lambda p: p["shots"].append(copy.deepcopy(p["shots"][0])), "duplicate-free subset"),
    (lambda p: p["shots"][0].update(shot_id="S09_Z"), "subset|unsafe"),
    (lambda p: p["shots"][0]["chunks"][0].update(core_frames=6), "recipe-derived"),
])
def test_tampered_tails_plans_are_refused(world, tmp_path: Path, edit, match) -> None:
    plan = planned(world)
    edit(plan)
    with pytest.raises(Refused, match=match):
        reload(world, plan, tmp_path)


def test_a_normal_plan_cannot_carry_a_source_range(world, tmp_path: Path) -> None:
    from engine.seedvr2.plan import build_plan, write_plan
    from test_seedvr2_segments_support import write_media
    from engine.seedvr2.segments import run_segments
    out = tmp_path / "main"
    run_segments(world.config, repo_root=loader.REPO_ROOT, out_root=out, probe=fake_probe, runner=world.runner)
    result = build_plan(world.config, repo_root=loader.REPO_ROOT, segments_root=out, probe=fake_probe)
    plan = copy.deepcopy(result.plan)
    plan["shots"][0]["source_range"] = {"start_frame": 0, "end_frame_exclusive": 40, "source_frames_total": 40}
    write_plan(out, result)
    with pytest.raises(Refused, match="only valid in a tails plan"):
        reload(world, plan, out)


# ---- CLI output rules ----------------------------------------------------------------------------
def test_cli_out_must_be_fresh_inside_the_episode_and_not_in_its_config(world) -> None:
    cfg = world.config
    cli_cut._check_out(world.root / "tails-run", cfg, inside_episode=True)
    for bad, match in ((world.tmp / "elsewhere", "outside the episode tree"), (world.root, "episode folder"),
                       (world.tmp, "episode folder or above"), (world.comfy_root / "x", "ComfyUI"),
                       (world.root / "engine" / "x", "config folder")):
        with pytest.raises(Refused, match=match):
            cli_cut._check_out(bad, cfg, inside_episode=True)
    cli_cut._check_out(world.tmp / "elsewhere", cfg, inside_episode=False)
