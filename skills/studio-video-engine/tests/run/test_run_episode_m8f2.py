"""M8-f2: the SeedVR2 stage of the episode DAG runs through ``jjv seedvr2 adopt`` (SV2-GAP2 closed).

The stage is ``segments`` (cut into scratch) -> ``plan`` (bound to those segments, into scratch) -> ``adopt`` (hash-bound
copy INTO the stage folder) -> ``execute --execute`` (GPU, on the ADOPTED plan).  Its receipts live beside the adopted
plan, never in scratch, and the old "move the plan folder by hand" work-around is gone.

Every verb is the recording fake (run_fixtures.FakeRunner): no ffmpeg cut, no ComfyUI, nothing submitted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from run_fixtures import FakeRunner, jjv_module, make_run_world, run_cli, write

from engine.run import dag as dag_mod
from engine.seedvr2.adopt import ADOPT_FILE
from engine.seedvr2.plan import PLAN_FILE

DAG = dag_mod.load_dag()
STEP_IDS = ["segments", "plan", "adopt", "execute"]
SEGMENTS = "{scratch}/seedvr2-segments"
SCRATCH_PLAN = "{scratch}/seedvr2-plan"
ADOPTED = "{stage:seedvr2}/plan"
_PLACEHOLDER = re.compile(r"\{[a-z_]+(?::[A-Za-z0-9_.-]+)?\}")


def stage(receipt: dict, stage_id: str) -> dict:
    return next(s for s in receipt["stages"] if s["id"] == stage_id)


def _flag(argv, name: str) -> str:
    assert name in argv, f"{name} missing in {list(argv)}"
    return argv[list(argv).index(name) + 1]


# ---- the recipe: four steps in order, execute on the adopted plan, receipts beside it ------------------
def test_seedvr2_stage_cuts_plans_adopts_then_executes_the_adopted_plan() -> None:
    sv = DAG.stage("seedvr2")
    assert [s.id for s in sv.steps] == STEP_IDS
    segments, plan, adopt, execute = sv.steps
    assert segments.argv[:2] == ("seedvr2", "segments") and _flag(segments.argv, "--out") == SEGMENTS
    assert plan.argv[:2] == ("seedvr2", "plan") and _flag(plan.argv, "--out") == SCRATCH_PLAN
    assert _flag(plan.argv, "--segments-root") == SEGMENTS, \
        "a plan without bound segments is PLANNED_SEGMENTS_PENDING: adopt and execute both refuse it"
    assert _flag(plan.argv, "--reads") == "{stage:editorial}/review-config.json"
    assert adopt.argv[:2] == ("seedvr2", "adopt") and _flag(adopt.argv, "--plan") == SCRATCH_PLAN
    assert _flag(adopt.argv, "--segments-root") == SEGMENTS and _flag(adopt.argv, "--into") == ADOPTED
    assert execute.argv[:2] == ("seedvr2", "execute") and execute.gpu and "--execute" in execute.argv
    assert _flag(execute.argv, "--plan") == f"{ADOPTED}/{PLAN_FILE}", "execute targets the ADOPTED plan, never scratch"
    assert "--segments-root" not in execute.argv, "adopt copies the segments beside the plan (execute's default root)"
    assert not any(s.gpu or s.human for s in (segments, plan, adopt))
    assert sv.receipts == (f"{ADOPTED}/{ADOPT_FILE}", f"{ADOPTED}/runs/run-state.json")
    assert sv.known_gap is None, "SV2-GAP2 is closed by adopt: no work-around to declare"
    assert "move the plan folder by hand" not in DAG.path.read_text("utf-8")


def test_seedvr2_steps_use_only_flags_the_real_verbs_advertise() -> None:
    """Every argv parses with the real ``bin/jjv.py`` parser once its placeholders are filled (no invented flag)."""
    parser = jjv_module().build_parser()
    for step in DAG.stage("seedvr2").steps:
        argv = [_PLACEHOLDER.sub("X", token) for token in step.argv]
        try:
            parsed = parser.parse_args(argv)
        except SystemExit as error:  # argparse reports an unknown or missing flag by exiting 2
            pytest.fail(f"step {step.id!r} argv is not accepted by the real parser (exit {error.code}): {argv}")
        assert (parsed.stage, parsed.verb) == ("seedvr2", step.id)


# ---- the walk: cut, plan, adopt run in order; the GPU step stops before anything is submitted -----------
def test_seedvr2_run_cuts_plans_and_adopts_then_stops_at_the_gpu_step(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    write(world.stage("editorial") / "review-config.json", {"schema": "fixture"})
    fake = FakeRunner()
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "seedvr2", "--to", "seedvr2"))
    assert code == 1 and receipt["first_stop"]["kind"] == "gpu-approval" and receipt["first_stop"]["step"] == "execute"
    assert [c[:2] for c in fake.calls] == [("seedvr2", "segments"), ("seedvr2", "plan"), ("seedvr2", "adopt")]
    assert fake.touched_gpu() == []
    scratch = world.root.parent / "scratch"
    segments_call, plan_call, adopt_call = fake.calls
    assert Path(_flag(segments_call, "--out")) == scratch / "seedvr2-segments"
    assert Path(_flag(plan_call, "--segments-root")) == scratch / "seedvr2-segments"
    assert Path(_flag(plan_call, "--out")) == scratch / "seedvr2-plan"
    assert Path(_flag(adopt_call, "--plan")) == scratch / "seedvr2-plan"
    assert Path(_flag(adopt_call, "--segments-root")) == scratch / "seedvr2-segments"
    assert Path(_flag(adopt_call, "--into")) == world.stage("seedvr2") / "plan"
    rows = {s["id"]: s for s in stage(receipt, "seedvr2")["steps"]}
    assert {k: v["status"] for k, v in rows.items()} == {"segments": "ok", "plan": "ok", "adopt": "ok", "execute": "stop"}
    assert Path(_flag(rows["execute"]["argv"], "--plan")) == world.stage("seedvr2") / "plan" / PLAN_FILE


def test_seedvr2_dry_run_names_the_four_steps_and_the_adopted_receipts(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner()
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "seedvr2", "--to", "seedvr2", dry_run=True))
    assert code == 0 and fake.calls == []
    row = stage(plan, "seedvr2")
    assert row["status"] == "planned" and row["would_stop"]["kind"] == "gpu-approval" and row["would_stop"]["step"] == "execute"
    assert [s["id"] for s in row["steps"]] == STEP_IDS and row["known_gap"] is None
    declared = {Path(p) for p in row["receipts"]["found"]}
    adopted = world.stage("seedvr2") / "plan"
    assert declared == {adopted / ADOPT_FILE, adopted / "runs" / "run-state.json"}
