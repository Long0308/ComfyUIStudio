"""M8-f1: tonight's verbs wired into the DAG (h3 inputs / publish-shots, boundaries write, qa transitions, deliver init,
health preflight before every GPU step) + the CR-M8 MAJORs (sha-bound approvals, fresh receipts, override after the limit).

Every verb is the recording fake (run_fixtures.FakeRunner); the declared checks (``pre`` / ``post`` / ``write_once`` /
``argv_if_exists``) are evaluated by the real orchestrator on files the tests write.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from run_fixtures import FakeRunner, make_run_world, run_cli, write

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.run import checks, dag as dag_mod, gates
from engine.run.context import load_run_context
from engine.run.gates import record_approval

DAG = dag_mod.load_dag()
GPU_VERBS = {("voice", "synth"), ("layout", "render"), ("images", "submit"), ("h3", "submit"), ("seedvr2", "execute")}


def stage(receipt: dict, stage_id: str) -> dict:
    return next(s for s in receipt["stages"] if s["id"] == stage_id)


def _argv_text(step) -> str:
    return " ".join(step.argv)


# ---- the recipe: tonight's verbs are wired -------------------------------------------------------------
def test_h3_stage_builds_its_manifest_and_publishes_shots_after_acceptance() -> None:
    h3 = DAG.stage("h3")
    assert [s.id for s in h3.steps] == ["inputs", "prepare", "submit", "adopt", "publish-shots"]
    inputs, prepare, submit, _adopt, publish = h3.steps
    assert inputs.argv[:2] == ("h3", "inputs") and "{file:h3_spec}" in inputs.argv and "--carry-from" in inputs.argv
    manifest = inputs.argv[inputs.argv.index("--out") + 1]
    assert prepare.argv[prepare.argv.index("--inputs") + 1] == manifest, "prepare reads the manifest inputs wrote"
    assert submit.gpu and publish.argv[:2] == ("h3", "publish-shots") and publish.human == "h3-acceptance"
    assert [p["kind"] for p in h3.post] == ["unmet-gap", "shots-not-adopted"]
    recipe_text = DAG.path.read_text("utf-8")
    assert "{file:h3_inputs}" not in recipe_text, "the manifest is built by the engine, not declared by hand"


def test_editorial_writes_boundaries_before_build_config_and_every_render_reads_them() -> None:
    editorial = DAG.stage("editorial")
    assert [s.id for s in editorial.steps] == ["boundaries-write", "build-config"]
    bw, bc = editorial.steps
    assert bw.argv[:3] == ("editorial", "boundaries", "write") and "storyboard" in editorial.needs
    out = bw.argv[bw.argv.index("--out") + 1]
    assert bc.argv[bc.argv.index("--boundaries") + 1] == f"{out}/boundaries.json"
    assert bc.pre and bc.pre["kind"] == "boundaries-draft" and bc.pre["list"] == "pending"
    assert {f for f, _ in bw.argv_if_exists} == {"{stage_dir}/boundaries-media.json", "{stage_dir}/boundaries-suggested.json"}
    for sid, step_id in (("edit", "review-render"), ("master", "master-render")):
        step = next(s for s in DAG.stage(sid).steps if s.id == step_id)
        assert step.argv[step.argv.index("--boundaries") + 1] == "{stage:editorial}/boundaries/boundaries.json"
    assert "{engine_dir}/boundaries.json" not in DAG.path.read_text("utf-8")


def test_qa_transitions_deliver_init_and_marker_checks_are_declared() -> None:
    assert [s.id for s in DAG.stage("qa").steps] == ["gate", "transitions"]
    transitions = DAG.stage("qa").steps[1]
    assert transitions.argv[:2] == ("qa", "transitions") and "--json" in transitions.argv
    deliver = DAG.stage("deliver")
    assert [s.id for s in deliver.steps] == ["init", "film-2k"]
    assert deliver.steps[0].write_once == "{engine_dir}/delivery.json"
    assert deliver.steps[1].pre["kind"] == "unresolved-marker" and deliver.steps[1].pre["section"] == "film_2k"
    brand_title, brand_join = DAG.stage("brand").steps
    assert brand_title.pre["section"] == "brand" and set(brand_title.pre["ignore"]) == {"film", "title"}
    assert "--film" in brand_join.argv and "--title" in brand_join.argv
    assert DAG.stage("publish").steps[0].pre["section"] == "publish"


def test_health_preflight_runs_from_the_orchestrator_before_every_gpu_step(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    fake = FakeRunner()
    marked = {tuple(step.argv[:2]) for s in DAG.stages for step in s.steps if step.gpu}
    assert GPU_VERBS <= marked
    monkeypatch.setattr("engine.run.orchestrator.health_gate_status", lambda dag: "available")
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "voice", "--to", "voice", approve_gpu=True))
    assert code == 1 and receipt["health_gate"] == "available"
    verbs = [c[:2] for c in fake.calls]
    assert verbs == [("voice", "plan"), ("health", "preflight"), ("voice", "synth")], "the gate runs right before the GPU verb"
    synth = next(s for s in stage(receipt, "voice")["steps"] if s["id"] == "synth")
    assert synth["health_result"]["exit"] == 0 and "--episode" in fake.calls[1]
    fake.fail[("health", "preflight")] = 1
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "voice", "--to", "voice", approve_gpu=True))
    assert code == 1 and receipt["first_stop"]["kind"] == "health-gate" and fake.calls[-1][:2] == ("health", "preflight")


def test_recipe_refuses_malformed_checks(tmp_path: Path) -> None:
    raw = json.loads(DAG.path.read_text("utf-8"))
    bad_step = {**raw["stages"][1]["steps"][0], "pre": {"kind": "x"}}
    with pytest.raises(Refused, match="pre"):
        dag_mod.load_dag(write(tmp_path / "bad.json", {**raw, "stages": [{**raw["stages"][1], "needs": [], "steps": [bad_step]}]}))
    with pytest.raises(Refused, match="post"):
        dag_mod.load_dag(write(tmp_path / "bad2.json", {**raw, "stages": [{**raw["stages"][1], "needs": [], "post": [{"kind": "x"}]}]}))


# ---- declared checks: named STOPs, never a crash --------------------------------------------------------
def _delivery(world, brand: dict | None = None, publish: dict | None = None) -> Path:
    doc = {"schema": "jjv/delivery-config/v1", "episode_id": "ep-fixture", "domain": "jenniejoy_cartoon_3d",
           "film_2k": {"out": "../delivery/v001/2k"},
           "brand": brand if brand is not None else {"kit": "/kit", "film": {"missing": "MISSING_EPISODE_KEY:brand.film"},
                                                     "title": {"missing": "MISSING_EPISODE_KEY:brand.title"}},
           "publish": publish if publish is not None else {"artifacts": {"missing": "MISSING_EPISODE_KEY:publish.artifacts"}}}
    return write(world.engine_dir / "delivery.json", doc)


def test_deliver_init_is_skipped_when_delivery_json_exists_and_film_2k_runs(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    _delivery(world)
    write(world.stage("master") / "master.mp4", "fake-master")
    fake = FakeRunner(receipts={("deliver", "film-2k"): "receipt.json"})   # --out is already the film-2k folder
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "deliver", "--to", "deliver"))
    assert code == 0 and [c[:2] for c in fake.calls] == [("deliver", "film-2k")]
    rows = {s["id"]: s for s in stage(receipt, "deliver")["steps"]}
    assert rows["init"]["status"] == "exists" and "delivery.json" in rows["init"]["reason"]
    assert rows["film-2k"]["status"] == "ok" and rows["film-2k"]["pre"]["ok"] is True


def test_an_unresolved_marker_in_delivery_json_is_a_named_stop_with_the_key(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    _delivery(world, brand={"kit": {"missing": "MISSING_MACHINE_KEY:brand.kit"}, "props": {"titleEn": "x"},
                            "film": {"missing": "MISSING_EPISODE_KEY:brand.film"}})
    write(world.stage("deliver") / "film-2k" / "receipt.json", {"schema": "fixture"})
    fake = FakeRunner()
    for extra in ([], ["--dry-run"]):
        code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "brand", "--to", "brand", *extra))
        stop = receipt["first_stop"]
        assert stop["stage"] == "brand" and stop["step"] == "title" and stop["kind"] == "unresolved-marker"
        assert "brand.kit = MISSING_MACHINE_KEY:brand.kit" in stop["reason"] and "brand.film" not in stop["reason"]
        assert "machine.json" in stop["next_step"] and "delivery.json" in stop["next_step"]
    assert fake.calls == [], "nothing ran: the marker is read before the verb"
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "deliver", "--to", "deliver", dry_run=True))
    rows = {s["id"]: s for s in stage(plan, "deliver")["steps"]}
    assert rows["init"]["status"] == "exists" and rows["film-2k"]["status"] == "planned"
    world.engine_dir.joinpath("delivery.json").unlink()
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "deliver", "--to", "deliver", dry_run=True))
    rows = {s["id"]: s for s in stage(plan, "deliver")["steps"]}
    assert rows["init"]["status"] == "planned" and rows["film-2k"]["pre"]["pending"] is True
    assert "would_stop" not in stage(plan, "deliver"), "a file the previous step will write is not a would-stop"


def test_h3_post_checks_surface_mouth_boxes_gap_and_unadopted_shots(tmp_path) -> None:
    world = make_run_world(tmp_path)
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root, stages_root=world.stages_root)
    gap, adopted = DAG.stage("h3").post
    gap_rows = [{"code": "MOUTH_BOXES_NOT_DERIVABLE", "file": "mouth-boxes", "why": "no receipt carries mouth tracks"}]
    verdict = checks.evaluate(gap, ctx, "h3")
    assert verdict.ok is False and verdict.pending is True, "nothing published yet is pending, not a crash"
    write(world.engine_dir / "shots-h3-v001.publication.json", {"schema": "jjv/h3-shots-publication/v1", "unmet": gap_rows})
    published = write(world.engine_dir / "shots-h3-v001.json", {"schema": "jjv/shots/v1", "shots": [{"shot": "S01_A"}]})
    verdict = checks.evaluate(gap, ctx, "h3")
    assert verdict.ok is False and verdict.kind == "unmet-gap" and "MOUTH_BOXES_NOT_DERIVABLE" in verdict.detail
    assert "re-run --from h3" in verdict.next_step
    write(world.engine_dir / "shots-h3-v002.publication.json", {"schema": "jjv/h3-shots-publication/v1", "unmet": []})
    assert checks.evaluate(gap, ctx, "h3").ok is True, "the latest publication wins"
    verdict = checks.evaluate(adopted, ctx, "h3")
    assert verdict.ok is False and verdict.kind == "shots-not-adopted" and "shots-h3-v001.json" in verdict.next_step
    assert "files.shots" in verdict.next_step and str(world.episode_file) in verdict.next_step
    world.engine_dir.joinpath("shots.json").write_bytes(published.read_bytes())
    assert checks.evaluate(adopted, ctx, "h3").ok is True


def test_a_boundaries_draft_stops_before_build_config_and_media_is_passed_when_present(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    for name in ("storyboard-check.json",):
        write(world.stage("storyboard") / name, {"schema": "fixture"})
    write(world.stage("script") / "boundaries-input.json", {"schema": "fixture"})
    write(world.stage("timing") / "WORD-TIMING.json", {"schema": "fixture"})
    pending = ["cards audio missing for: Creamy", "icons missing (pass --media ...)"]
    fake = FakeRunner(receipts={("editorial", "boundaries", "write"): ("versions/boundaries-draft-v001.json", {"pending": pending})})
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "editorial", "--to", "editorial"))
    stop = receipt["first_stop"]
    assert code == 1 and stop["kind"] == "boundaries-draft" and stop["step"] == "build-config"
    assert "cards audio missing for: Creamy" in stop["reason"] and "boundaries-media.json" in stop["next_step"]
    assert [c[:3] for c in fake.calls] == [("editorial", "boundaries", "write")] and "--media" not in fake.calls[0]
    write(world.stage("editorial") / "boundaries-media.json", {"cards_audio": {}})
    code, plan = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "editorial", "--to", "editorial", dry_run=True))
    argv = stage(plan, "editorial")["steps"][0]["argv"]
    assert argv[argv.index("--media") + 1].endswith("boundaries-media.json") and "--suggested" not in argv


def test_post_checks_are_re_evaluated_on_reuse_without_re_running_the_steps(tmp_path, capsys, monkeypatch) -> None:
    raw = json.loads(DAG.path.read_text("utf-8"))
    custom = {**raw, "stages": [{
        "id": "pub", "s": "X", "label": "custom", "needs": [], "inputs": ["{file:script}"], "gates": [],
        "steps": [{"id": "publish", "argv": ["fake", "publish", "--out", "{stage_dir}"]}],
        "post": [{"kind": "shots-not-adopted", "latest": "{stage_dir}/shots-h3-v[0-9][0-9][0-9].json", "equals": "{file:shots}",
                  "next": "set episode.files.shots = {latest}, then re-run --from pub"}],
        "receipts": ["{stage_dir}/shots-h3-v001.json"]}]}
    world = make_run_world(tmp_path)
    dag_file = write(tmp_path / "custom-dag.json", custom)
    fake = FakeRunner(receipts={("fake", "publish"): "shots-h3-v001.json"})
    argv = world.base_argv("--dag", str(dag_file))
    code, first = run_cli(capsys, monkeypatch, fake, argv)
    assert code == 1 and first["first_stop"]["kind"] == "shots-not-adopted" and "shots-h3-v001.json" in first["first_stop"]["next_step"]
    assert stage(first, "pub")["status"] == "stopped" and (world.runs_root / "ledger" / "pub.json").is_file()
    assert json.loads((world.runs_root / "ledger" / "pub.json").read_text())["status"] == "steps-done"
    code, second = run_cli(capsys, monkeypatch, fake, argv)
    assert code == 1 and len(fake.calls) == 1, "reused: the step did not run again, the check still holds the run"
    world.engine_dir.joinpath("shots.json").write_bytes((world.stage("pub") / "shots-h3-v001.json").read_bytes())
    code, third = run_cli(capsys, monkeypatch, fake, argv)
    assert code == 0 and stage(third, "pub")["status"] == "reused" and len(fake.calls) == 1
    assert json.loads((world.runs_root / "ledger" / "pub.json").read_text())["status"] == "complete"


# ---- CR-M8 MAJOR 1: approvals are bound to the subject's sha ------------------------------------------
def test_accept_and_change_records_must_carry_the_subject_sha(tmp_path) -> None:
    world = make_run_world(tmp_path)
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root)
    for gate in ("music-approval", "publish-approval", "user-review"):
        with pytest.raises(Refused, match="--sha256"):
            record_approval(ctx, gate, by="Ken", note="x", verdict="accept", sha256=None)
    with pytest.raises(Refused, match="--sha256"):
        record_approval(ctx, "user-review", by="Ken", note="x", verdict="change", sha256=None)


def test_a_music_approval_of_an_older_pick_does_not_pass_the_gate_for_the_new_one(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    pick = write(world.stage("music") / "music-pick.json", {"schema": "fixture", "bed": "NHAC-1"})
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root)
    record_approval(ctx, "music-approval", by="Ken", note="bed ok", verdict="accept", sha256=sha256_file(pick))
    bounds = ["--from", "mix", "--to", "mix"]
    write(world.stage("editorial") / "review-config.json", {"schema": "fixture"})
    code, ok = run_cli(capsys, monkeypatch, FakeRunner(receipts={("audio", "mix"): "mix-receipt.json"}), world.base_argv(*bounds))
    assert code == 0 and stage(ok, "mix")["steps"][0]["human_state"]["ok"] is True
    write(pick, {"schema": "fixture", "bed": "NHAC-2"})
    fake = FakeRunner()
    code, changed = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 1 and changed["first_stop"]["kind"] == "human-gate" and fake.calls == []
    assert "no accept record for" in changed["first_stop"]["reason"] and sha256_file(pick) in changed["first_stop"]["next_step"]
    # a hand-written record without a sha never satisfies the gate
    write(ctx.approvals_dir / "music-approval-002.json", {"schema": gates.APPROVAL_SCHEMA, "gate": "music-approval",
                                                           "episode_id": "ep-fixture", "by": "Ken", "note": "x",
                                                           "verdict": "accept", "sha256": None})
    code, still = run_cli(capsys, monkeypatch, fake, world.base_argv(*bounds))
    assert code == 1 and still["first_stop"]["kind"] == "human-gate"


# ---- CR-M8 MAJOR 2: a receipt counts only when THIS run wrote or named it ------------------------------
def test_a_stale_receipt_from_an_earlier_run_does_not_prove_this_run(tmp_path, capsys, monkeypatch) -> None:
    world = make_run_world(tmp_path)
    stale = write(world.stage("script") / "ingest-receipt.json", {"schema": "stale"})
    old = time.time() - 3600
    os.utime(stale, (old, old))
    fake = FakeRunner()   # the ingest verb exits 0 but writes nothing this time
    code, receipt = run_cli(capsys, monkeypatch, fake, world.base_argv("--from", "script", "--to", "script"))
    assert code == 2 and receipt["first_stop"]["kind"] == "receipt-missing"
    assert "stale" in receipt["first_stop"]["reason"] and "ingest-receipt.json" in receipt["first_stop"]["reason"]
    assert not (world.runs_root / "ledger" / "script.json").exists()
    # the same old file counts when the step's own output names it (a verb that reused an identical version)
    named = FakeRunner(stdout={("script", "ingest"): {"ok": True, "receipt": str(stale)}})
    code, receipt = run_cli(capsys, monkeypatch, named, world.base_argv("--from", "script", "--to", "script"))
    assert code == 0 and stage(receipt, "script")["status"] == "ran"
    # ... or binds it by sha256
    os.utime(stale, (old, old))
    (world.runs_root / "ledger" / "script.json").unlink()
    bound = FakeRunner(stdout={("script", "ingest"): {"ok": True, "sha256": sha256_file(stale)}})
    code, receipt = run_cli(capsys, monkeypatch, bound, world.base_argv("--from", "script", "--to", "script"))
    assert code == 0 and stage(receipt, "script")["status"] == "ran"


# ---- CR-M8 MAJOR 3: override only after the limit ------------------------------------------------------
def test_override_is_refused_until_the_user_review_limit_is_reached(tmp_path) -> None:
    world = make_run_world(tmp_path)
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root)
    with pytest.raises(Refused, match="limit"):
        record_approval(ctx, "user-review", by="Ken", note="skip it", verdict="override", sha256=None)
    record_approval(ctx, "user-review", by="Ken", note="v1 bad", verdict="change", sha256="11" * 32)
    with pytest.raises(Refused, match="limit"):
        record_approval(ctx, "user-review", by="Ken", note="skip it", verdict="override", sha256=None)
    record_approval(ctx, "user-review", by="Ken", note="v2 bad", verdict="change", sha256="22" * 32)
    record_approval(ctx, "user-review", by="Ken", note="one more, my call", verdict="override", sha256=None)
    with pytest.raises(Refused, match="limit"):   # the override reset the count: a second one needs two more changes
        record_approval(ctx, "user-review", by="Ken", note="again", verdict="override", sha256=None)
    with pytest.raises(Refused, match="user-review"):
        record_approval(ctx, "music-approval", by="Ken", note="x", verdict="override", sha256=None)


# ---- the h3 acceptance gate reads the episode context (M7-f1 changed the accept API) -------------------
def test_h3_acceptance_gate_evaluates_without_a_type_error(tmp_path) -> None:
    world = make_run_world(tmp_path)
    world.stage("h3").mkdir(parents=True)
    ctx = load_run_context(str(world.episode_file), runs_root=world.runs_root, stages_root=world.stages_root)
    state = gates.check(ctx, "h3", DAG.stage("h3").human_gates, "h3-acceptance")
    assert state.ok is False and "2/2 shots not picked" in state.detail and "jjv h3 accept" in state.next_step
