"""M8 / Q-6 ``jjv run episode``: dry-run plan, GPU stop, reuse, --from/--to, human gates, domain refusal.

Every verb is the recording fake (run_fixtures.FakeRunner): no ComfyUI, no TTS, no render, no publish.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from run_fixtures import SHOTS, FakeRunner, make_run_world, run_cli, write

from engine.core.errors import Refused
from engine.run import dag as dag_mod
from engine.run.context import load_run_context
from engine.run.gates import record_approval

DAG = dag_mod.load_dag()
GPU_VERBS = {("voice", "synth"), ("layout", "render"), ("images", "submit"), ("h3", "submit"), ("seedvr2", "execute")}


def stage(receipt: dict, stage_id: str) -> dict:
    return next(s for s in receipt["stages"] if s["id"] == stage_id)


# ---- the recipe itself ---------------------------------------------------------------------------------
def test_recipe_declares_every_gpu_verb_as_gpu_and_the_health_todo() -> None:
    marked = {tuple(step.argv[:2]) for s in DAG.stages for step in s.steps if step.gpu}
    assert GPU_VERBS <= marked
    assert DAG.domains == ("jenniejoy_cartoon_3d",) and "T-E39" in DAG.health_gate["todo"]
    assert all(step.human or s.human for s in DAG.stages for step in s.steps if step.argv[:2] == ("publish", "studio")
               and "--publish" in step.argv)


def test_recipe_shape_errors_are_refused(tmp_path: Path) -> None:
    raw = json.loads(DAG.path.read_text("utf-8"))
    bad = {**raw, "stages": [{**raw["stages"][1], "needs": ["nope"]}]}
    with pytest.raises(Refused, match="not an earlier stage"):
        dag_mod.load_dag(write(tmp_path / "bad.json", bad))
    with pytest.raises(Refused, match="unknown human gate"):
        dag_mod.load_dag(write(tmp_path / "bad2.json", {**raw, "stages": [{**raw["stages"][0], "human": "x",
                                                                            "human_gates": {"x": {}}}]}))


# ---- dry run -------------------------------------------------------------------------------------------
def test_dry_run_lists_every_stage_and_gate_and_runs_nothing(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner()
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv(dry_run=True))
    assert code == 0 and plan["dry_run"] and plan["ran_nothing"] and fake.calls == []
    assert [s["id"] for s in plan["stages"]] == list(DAG.ids)
    for declared in DAG.stages:
        row = stage(plan, declared.id)
        assert [g["id"] for g in row["gates"]] == [g.id for g in declared.gates]
        assert all(g["status"] == "planned" and g["argv"] for g in row["gates"])
        assert "reuse" in row or row["status"] == "blocked"
    assert plan["first_stop"]["stage"] == "voice" and plan["first_stop"]["kind"] == "gpu-approval"
    assert stage(plan, "layout")["would_stop"]["kind"] == "gpu-approval"
    assert stage(plan, "review")["would_stop"]["kind"] == "human-gate"
    assert stage(plan, "h3")["status"] == "blocked" or stage(plan, "h3")["would_stop"]["kind"] in ("blocked", "gpu-approval")
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
                     and "runs" in p.parts)
    assert written == [f"runs/{plan['run_id']}/plan.json"] and not world.stages_root.exists()
    render_rows = [s for s in stage(plan, "layout")["steps"] if s["id"] == "render"]
    assert [s["shot"] for s in render_rows] == SHOTS, "per_shot steps expand once per shot of shots.json"


# ---- GPU stop ------------------------------------------------------------------------------------------
def test_gpu_step_without_approve_gpu_stops_with_nothing_submitted(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner()
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "voice", "--to", "voice"))
    assert code == 1 and receipt["ok"] is False
    assert receipt["first_stop"]["stage"] == "voice" and receipt["first_stop"]["kind"] == "gpu-approval"
    assert "--approve-gpu" in receipt["first_stop"]["next_step"]
    assert fake.verbs() == ["voice plan --episode"] and fake.touched_gpu() == []
    steps = {s["id"]: s["status"] for s in stage(receipt, "voice")["steps"]}
    assert steps == {"plan": "ok", "synth": "stop", "finalize": "after-stop"}
    assert (Path(receipt["run_dir"]) / "run.json").is_file() and (Path(receipt["run_dir"]) / "stage-times.jsonl").is_file()
    rows = [json.loads(line) for line in (Path(receipt["run_dir"]) / "stage-times.jsonl").read_text().splitlines()]
    assert rows[0]["stage"] == "voice" and rows[0]["step"] == "plan" and rows[0]["exit"] == 0 and rows[0]["seconds"] >= 0


def test_with_approve_gpu_the_gpu_step_runs_and_the_listen_approval_stops_next(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner()
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "voice", "--to", "voice", approve_gpu=True))
    assert code == 1 and receipt["first_stop"]["kind"] == "human-gate"
    assert receipt["first_stop"]["step"] == "finalize" and "voice plan" in receipt["first_stop"]["next_step"]
    assert [c[:2] for c in fake.calls if c[:2] != ("health", "preflight")] == [("voice", "plan"), ("voice", "synth")]
    assert "voice finalize" not in fake.verbs()


# ---- reuse ---------------------------------------------------------------------------------------------
def test_a_stage_with_matching_receipts_is_reused_until_an_input_changes(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner(receipts={("script", "ingest"): "ingest-receipt.json"})
    bounds = ["--from", "script", "--to", "script"]
    code, first = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 0 and first["ok"] and stage(first, "script")["status"] == "ran" and len(fake.calls) == 1
    assert (world.runs_root / "ledger" / "script.json").is_file()
    code, second = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 0 and stage(second, "script")["status"] == "reused" and len(fake.calls) == 1
    assert "unchanged since run" in stage(second, "script")["reuse"]["reason"]
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds, dry_run=True))
    assert stage(plan, "script")["status"] == "reuse" and len(fake.calls) == 1
    write(world.root / "script" / "script.json", {"schema": "jjv/script/v1", "status": "LOCKED", "lines": ["b"]})
    code, third = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 0 and stage(third, "script")["status"] == "ran" and len(fake.calls) == 2
    assert stage(third, "script")["reuse"]["reason"].startswith("inputs changed since run")


def test_hand_made_receipts_without_a_ledger_are_not_reused(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    write(world.stage("script") / "ingest-receipt.json", {"schema": "hand-made"})
    code, plan = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv("--from", "script", "--to", "script", dry_run=True))
    assert code == 0 and stage(plan, "script")["status"] == "planned"
    assert "not proven" in stage(plan, "script")["reuse"]["reason"]


def test_a_stage_whose_steps_pass_but_leave_no_receipt_stops(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    code, receipt = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv("--from", "script", "--to", "script"))
    assert code == 2 and receipt["first_stop"]["kind"] == "receipt-missing"
    assert not (world.runs_root / "ledger" / "script.json").exists()


# ---- --from / --to -------------------------------------------------------------------------------------
def test_from_and_to_bound_the_walk(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    code, plan = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv("--from", "editorial", "--to", "qa", dry_run=True))
    assert code == 0
    status = {s["id"]: s["status"] for s in plan["stages"]}
    ids = list(DAG.ids)
    for sid in ids[:ids.index("editorial")]:
        assert status[sid] == "skipped-range" and stage(plan, sid)["reason"] == "before --from editorial"
    for sid in ids[ids.index("qa") + 1:]:
        assert status[sid] == "skipped-range" and stage(plan, sid)["reason"] == "after --to qa"
    assert status["editorial"] == "planned" and status["mix"] == "planned" and status["qa"] == "planned"
    code, out = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv("--from", "qa", "--to", "editorial", dry_run=True))
    assert code == 1 and "comes after" in out["error"]
    code, out = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv("--from", "nope", dry_run=True))
    assert code == 1 and "unknown stage" in out["error"]


# ---- human gates ---------------------------------------------------------------------------------------
def test_missing_music_approval_stops_before_the_mix_runs(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    write(world.stage("music") / "music-pick.json", {"schema": "fixture", "bed": "x"})
    fake = FakeRunner()
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "mix", "--to", "mix"))
    assert code == 1 and receipt["first_stop"] == {**receipt["first_stop"], "stage": "mix", "step": "mix", "kind": "human-gate"}
    assert "music-approval" in receipt["first_stop"]["next_step"] and fake.calls == []


def test_user_review_limit_two_then_override_then_accept(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    film = world.stage("edit") / "review.mp4"
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root)
    bounds = ["--from", "review", "--to", "review"]

    def verdict() -> dict:
        _code, receipt = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv(*bounds))
        return receipt["first_stop"] or {"kind": "none", "reason": "", "next_step": ""}

    assert "no review film yet" in verdict()["reason"]
    write(film, "version-1")
    assert "waiting for the user's review of version 1" in verdict()["reason"]
    record_approval(ctx, "user-review", by="Ken", note="captions late", verdict="change", sha256=_sha(film))
    assert "change requested" in verdict()["reason"]
    write(film, "version-2")
    assert "review of version 2" in verdict()["reason"]
    record_approval(ctx, "user-review", by="Ken", note="icon wrong", verdict="change", sha256=_sha(film))
    write(film, "version-3")
    limit = verdict()
    assert "limit 2 reached" in limit["reason"] and "--verdict override" in limit["next_step"]
    record_approval(ctx, "user-review", by="Ken", note="one more, my call", verdict="override", sha256=None)
    assert "review of version 1" in verdict()["reason"], "override resets the count"
    record_approval(ctx, "user-review", by="Ken", note="good", verdict="accept", sha256=_sha(film))
    code, receipt = run_cli(capsys, monkeypatch, FakeRunner(), world.base_argv(*bounds))
    assert code == 0 and receipt["ok"] and stage(receipt, "review")["human"]["ok"]
    with pytest.raises(Refused, match="--by must name the person"):
        record_approval(ctx, "user-review", by="claude", note="x", verdict="accept", sha256=None)


def test_run_approve_verb_writes_a_numbered_record(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    argv = ["run", "approve", "--episode", str(world.episode_file), "--runs-root", str(world.runs_root), "--gate",
            "music-approval", "--by", "Ken", "--note", "bed ok", "--sha256", "ab" * 32]
    code, out = run_cli(capsys, monkeypatch, FakeRunner(), argv)
    assert code == 0 and out["record"].endswith("music-approval-001.json")
    code, out = run_cli(capsys, monkeypatch, FakeRunner(), argv)
    assert code == 0 and out["record"].endswith("music-approval-002.json")


# ---- domains -------------------------------------------------------------------------------------------
def test_a_domain_without_a_run_recipe_is_refused_before_anything_is_written(tmp_path, capsys, monkeypatch) -> None:
    # B01: live action now HAS its own recipe (test_run_episode_live_dag.py); a domain with none is still refused
    world = make_run_world(tmp_path, domain="no_such_domain", episode_id="live-fixture")
    fake = FakeRunner()
    for extra in ([], ["--dry-run"], ["--approve-gpu"]):
        code, out = run_cli(capsys, monkeypatch, fake, world.base_argv(*extra))
        assert code == 1 and "cross-domain" in out["error"] and "no_such_domain" in out["error"]
    assert fake.calls == [] and not world.runs_root.exists() and not world.stages_root.exists()


def _sha(path: Path) -> str:
    from engine.core.io import sha256_file
    return sha256_file(path)


# ---- plan explain before a re-run ----------------------------------------------------------------------
def test_plan_explain_runs_before_a_re_run_of_a_render_stage(tmp_path, capsys, monkeypatch) -> None:
    from engine.plan.load import load_inputs
    world = make_run_world(tmp_path)
    config = write(world.stage("editorial") / "review-config.json", {"schema": "fixture", "version": 1})
    write(world.stage("editorial") / "events.json", {"schema": "fixture"})
    write(world.stage("mix") / "mix-receipt.json", {"schema": "fixture"})
    fake = FakeRunner(receipts={("edit", "review-render"): "review.mp4"})
    bounds = ["--from", "edit", "--to", "edit"]
    code, first = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 0 and stage(first, "edit")["explain"]["status"] == "first-run"
    assert [c[:2] for c in fake.calls] == [("qa", "preflight"), ("edit", "review-render")], "gate first, then the step"
    snapshot = world.runs_root / "ledger" / "edit" / "explain"
    assert (snapshot / "plan-inputs.json").is_file() and (snapshot / "review-config.json").is_file()
    assert load_inputs(snapshot, pin_keys=[]).config_sha256 == _sha(config), "the ledger snapshot is a plan-explain version"
    write(config, {"schema": "fixture", "version": 2})
    code, second = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 0 and stage(second, "edit")["reuse"]["reason"].startswith("inputs changed")
    verbs = [c[:2] for c in fake.calls[2:]]
    assert verbs == [("qa", "preflight"), ("plan", "explain"), ("edit", "review-render")]
    explain_argv = fake.calls[3]
    old, new = explain_argv[explain_argv.index("--old") + 1], explain_argv[explain_argv.index("--new") + 1]
    assert Path(old) == snapshot and (Path(new) / "plan-inputs.json").is_file()
    assert load_inputs(new, pin_keys=[]).config_sha256 == _sha(config)
    assert stage(second, "edit")["explain"]["status"] == "ok" and stage(second, "edit")["status"] == "ran"
    fake.fail[("plan", "explain")] = 1
    write(config, {"schema": "fixture", "version": 3})
    code, third = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 1 and third["first_stop"]["kind"] == "explain-failed"
    assert fake.calls[-1][:2] == ("plan", "explain"), "a failed explain stops the stage before the render"
