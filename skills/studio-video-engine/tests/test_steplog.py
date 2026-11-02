"""STEPLOG (BP-00A): per-step input/output log, verify, plan-resume and the two wired verbs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from engine.core import steplog
from engine.core.errors import Refused, Uncertain
from engine.core.io import canonical_json
from engine.images import cli as images_cli
from engine.video import cli as video_cli
from fake_comfy import FakeComfy
from test_images_local import Setup


@pytest.fixture
def fake():
    with FakeComfy() as server:
        yield server


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _lines(run: Path) -> list[bytes]:
    return (run / steplog.LOG_NAME).read_bytes().split(b"\n")[:-1]


def _step(run: Path, step_id: str, inputs: list[Path], output: Path, text: str) -> None:
    with steplog.logged_step(run, run_id="run-t", step_id=step_id, stage="test",
                             inputs=[("in", p) for p in inputs], settings={"seed": 7}, model={"name": "m"}) as step:
        _write(output, text)
        step.output(output, "out")


def _chain(run: Path) -> dict[str, Path]:
    """src -> s1 -> s2 -> s3: every step consumes the previous step's output."""
    src = _write(run / "inputs" / "src.txt", "source")
    s1, s2, s3 = run / "s1.txt", run / "s2.txt", run / "s3.txt"
    _step(run, "s1", [src], s1, "one")
    _step(run, "s2", [s1], s2, "two")
    _step(run, "s3", [s2], s3, "three")
    return {"src": src, "s1": s1, "s2": s2, "s3": s3}


def _decisions(run: Path) -> dict[str, str]:
    return {row["step_id"]: row["decision"] for row in steplog.plan_resume(run)["steps"]}


# --- one line per step, chain, verify ----------------------------------------------------

def test_one_line_per_step_has_all_fields_and_chains(tmp_path):
    run = tmp_path / "run"
    files = _chain(run)
    lines = _lines(run)
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert set(steplog.REQUIRED_KEYS) <= set(first)
    assert first["schema"] == steplog.SCHEMA and first["seq"] == 1 and first["prev_sha256"] == steplog.GENESIS
    assert first["status"] == "COMPLETE" and first["settings"]["seed"] == 7
    assert first["inputs"][0]["sha256"] == _sha(files["src"])
    assert first["outputs"][0]["sha256"] == _sha(files["s1"])
    assert json.loads(lines[1])["prev_sha256"] == hashlib.sha256(lines[0]).hexdigest()
    assert steplog.verify(run)["ok"] is True


def test_tampered_line_breaks_the_chain(tmp_path):
    run = tmp_path / "run"
    _chain(run)
    lines = _lines(run)
    record = json.loads(lines[0])
    record["stage"] = "edited"
    (run / steplog.LOG_NAME).write_bytes(b"\n".join([canonical_json(record, mode="utf8")] + lines[1:]) + b"\n")
    result = steplog.verify(run)
    assert result["ok"] is False
    assert any(error.startswith("line 2") and "chain" in error for error in result["errors"])


def test_reformatting_a_line_is_reported_as_not_canonical(tmp_path):
    run = tmp_path / "run"
    _chain(run)
    lines = _lines(run)
    edited = lines[0].replace(b'"stage":"test"', b'"stage": "test"')  # same value, different bytes
    (run / steplog.LOG_NAME).write_bytes(b"\n".join([edited] + lines[1:]) + b"\n")
    result = steplog.verify(run)
    assert result["ok"] is False and any("not canonical" in error for error in result["errors"])


def test_changing_a_value_in_canonical_form_is_caught_by_the_chain_not_the_format(tmp_path):
    run = tmp_path / "run"
    _chain(run)
    lines = _lines(run)
    edited = lines[0].replace(b'"stage":"test"', b'"stage":"tesT"')  # still canonical bytes
    (run / steplog.LOG_NAME).write_bytes(b"\n".join([edited] + lines[1:]) + b"\n")
    result = steplog.verify(run)
    assert result["ok"] is False
    assert not any("not canonical" in error for error in result["errors"])
    assert any(error.startswith("line 2") and "chain" in error for error in result["errors"])


def test_missing_output_is_reported(tmp_path):
    run = tmp_path / "run"
    files = _chain(run)
    files["s2"].unlink()
    result = steplog.verify(run)
    assert result["ok"] is False
    assert any("out" in e and "missing" in e and "s2.txt" in e for e in result["errors"])


def test_drifted_output_is_reported(tmp_path):
    run = tmp_path / "run"
    files = _chain(run)
    _write(files["s1"], "changed after the run")
    result = steplog.verify(run)
    assert result["ok"] is False and any("drift" in e and "s1.txt" in e for e in result["errors"])


def test_failed_step_records_fail_and_reraises(tmp_path):
    run = tmp_path / "run"
    src = _write(run / "src.txt", "x")
    with pytest.raises(RuntimeError, match="boom"):
        with steplog.logged_step(run, run_id="run-t", step_id="bad", stage="test", inputs=[("in", src)],
                                 settings={}, model={}):
            raise RuntimeError("boom")
    record = json.loads(_lines(run)[0])
    assert record["status"] == "FAIL" and record["error"].startswith("RuntimeError: boom")
    assert record["settings"]["seed"] is None
    assert steplog.verify(run)["ok"] is True


def test_complete_step_refuses_an_output_that_is_not_on_disk(tmp_path):
    run = tmp_path / "run"
    src = _write(run / "src.txt", "x")
    with pytest.raises(Refused):
        with steplog.logged_step(run, run_id="run-t", step_id="s", stage="test", inputs=[("in", src)],
                                 settings={}, model={}) as step:
            step.output(run / "never.txt", "out")
    assert not (run / steplog.LOG_NAME).exists()


def test_skipped_step_keeps_its_note(tmp_path):
    run = tmp_path / "run"
    with steplog.logged_step(run, run_id="run-t", step_id="s", stage="test", inputs=[], settings={}, model={}) as step:
        step.skip("dry-run: nothing sent")
    record = json.loads(_lines(run)[0])
    assert record["status"] == "SKIPPED" and record["note"] == "dry-run: nothing sent"


def test_input_key_moves_with_inputs_seed_and_model():
    base = dict(step_id="s", input_shas=["a" * 64], settings={"seed": 1}, model={"name": "m", "sha256": None})
    key = steplog.input_key(**base)
    assert steplog.input_key(**{**base, "input_shas": ["b" * 64]}) != key
    assert steplog.input_key(**{**base, "settings": {"seed": 2}}) != key
    assert steplog.input_key(**{**base, "model": {"name": "n", "sha256": None}}) != key


# --- plan-resume --------------------------------------------------------------------------

def test_resume_unchanged_chain_reuses_every_step(tmp_path):
    run = tmp_path / "run"
    _chain(run)
    assert _decisions(run) == {"s1": "reuse", "s2": "reuse", "s3": "reuse"}


def test_resume_tampered_middle_output_reruns_it_and_downstream(tmp_path):
    run = tmp_path / "run"
    files = _chain(run)
    _write(files["s2"], "tampered")
    assert _decisions(run) == {"s1": "reuse", "s2": "rerun", "s3": "downstream-rerun"}


def test_resume_failed_step_reruns(tmp_path):
    run = tmp_path / "run"
    src = _write(run / "inputs" / "src.txt", "source")
    _step(run, "s1", [src], run / "s1.txt", "one")
    with pytest.raises(RuntimeError):
        with steplog.logged_step(run, run_id="run-t", step_id="s2", stage="test", inputs=[("in", run / "s1.txt")],
                                 settings={}, model={}):
            raise RuntimeError("render failed")
    assert _decisions(run) == {"s1": "reuse", "s2": "rerun"}


def test_resume_from_step_forces_it_and_dependency_descendants(tmp_path):
    run = tmp_path / "run"
    _chain(run)
    assert {row["step_id"]: row["decision"] for row in steplog.plan_resume(run, from_step="s2")["steps"]} == {
        "s1": "reuse", "s2": "rerun", "s3": "downstream-rerun"}


def _cli(*argv: str) -> int:
    parser = argparse.ArgumentParser()
    stages = parser.add_subparsers(dest="stage", required=True)
    steplog.register_cli(stages)
    return steplog.run_cli(parser.parse_args(list(argv)))


def test_cli_plan_resume_prints_table_and_verify_sets_exit_code(tmp_path, capsys):
    run = tmp_path / "run"
    _chain(run)
    assert _cli("steplog", "plan-resume", "--run", str(run)) == 0
    table = capsys.readouterr().out
    assert "s3" in table and "reuse" in table
    assert _cli("steplog", "verify", "--run", str(run)) == 0
    _write(run / "s1.txt", "changed")
    assert _cli("steplog", "verify", "--run", str(run)) == 1


# --- the two wired verbs ------------------------------------------------------------------

def _images_args(setup: Setup) -> argparse.Namespace:
    return argparse.Namespace(provider="comfyui-local", shot="S01_A", prompt_file=str(setup.prompt), prompt_batch=None,
                              library_out=None, n=1, take=None, seed=None, task=None, pilot=False, dry_run=True)


def test_images_submit_dry_run_appends_one_skipped_line(tmp_path, fake):
    setup = Setup(tmp_path, fake)
    result = images_cli._submit(setup.world.ctx(), setup.out, _images_args(setup))
    assert result["dry_run"] is True and fake.posts == []
    records = [json.loads(line) for line in _lines(setup.out)]
    assert len(records) == 1 and records[0]["status"] == "SKIPPED"
    assert records[0]["step_id"].startswith("images.submit.comfyui-local.S01_A.")
    assert records[0]["inputs"][0]["sha256"] == _sha(setup.prompt)
    graph = next(item for item in records[0]["outputs"] if item["role"] == "graph")
    assert graph["sha256"] == _sha(Path(result["graph"]))
    assert records[0]["settings"]["seed"] == result["seed"]
    assert steplog.verify(setup.out)["ok"] is True


def test_video_render_gate_appends_a_second_line_after_the_image_line(tmp_path, fake, monkeypatch):
    setup = Setup(tmp_path, fake)
    images_cli._submit(setup.world.ctx(), setup.out, _images_args(setup))

    def gate_only(ctx, out, shot, revision, route, **kwargs):
        return {"ok": False, "gate": {"user_gate": True, "reason": "needs --gpu-approved"}}

    media = _video_inputs_setup(setup.world.ctx(), setup.out)
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", gate_only)
    args = argparse.Namespace(shot="S01_A", revision=1, route="h3-ref2va", gpu_approved=None, resume=False,
                              timeout=1.0)
    result = video_cli._render_logged(setup.world.ctx(), setup.out, args, None, None)
    assert result["gate"]["user_gate"] is True
    records = [json.loads(line) for line in _lines(setup.out)]
    assert [r["stage"] for r in records] == ["images.submit", "video.render"]
    assert records[1]["status"] == "SKIPPED" and records[1]["step_id"] == "video.render.S01_A.r001"
    inputs = {item["role"]: item for item in records[1]["inputs"]}
    assert {"plan", "prompt", "h3_inputs", "template", "anchor", "wav", "refs_0"} <= inputs.keys()
    assert inputs["wav"]["sha256"] == _sha(media["wav"])
    assert all(item["sha256"] for item in inputs.values())
    assert records[1]["prev_sha256"] == hashlib.sha256(_lines(setup.out)[0]).hexdigest()
    assert steplog.verify(setup.out)["ok"] is True


# --- regressions #03/#04/#05/#07/#10 ------------------------------------------------------


def _json(path, value):
    return _write(path, json.dumps(value))


def _video_inputs_setup(ctx, out):
    # H3 asset paths are relative to ctx.root, receipt paths to video out.
    media = {role: _write(ctx.root / "steplog-media" / name, role)
             for role, name in (("template", "workflow.json"), ("anchor", "guide.png"),
                                ("wav", "dialogue.wav"), ("refs_0", "body.png"),
                                ("faces_0", "face.png"))}
    def ref(role):
        path = media[role]
        return {"path": path.relative_to(ctx.root).as_posix(), "sha256": _sha(path)}
    plan = _json(out / "plan-receipt.json", {"template": ref("template"), "refs": []})
    prompt = _json(out / "prompt-receipt.json", {"text": "test prompt"})
    receipts = {role: video_cli.state_mod.ref(out, path) for role, path in (("plan", plan), ("prompt", prompt))}
    state = {"schema": video_cli.state_mod.STATE_SCHEMA, "state": "prompted", "shot": "S01_A", "receipts": receipts}
    video_cli.state_mod.write_state(out, state)
    _json(video_cli.render_mod.manifest_path(out), {"shots": [
        {"shot": "OTHER", "template": {"path": "must-not-be-read.json"}},
        {"shot": "S01_A", "template": ref("template"), "anchor": ref("anchor"), "wav": ref("wav"),
         "faces": [ref("faces_0")], "refs": [ref("refs_0")]}]})
    return media


def _video_args():
    return argparse.Namespace(shot="S01_A", revision=1, route="test-route", gpu_approved=None,
                              resume=False, timeout=1.0)


def _fake_render_result(out, media=None):
    native = _write(out / "native.mp4", "native video bytes")
    raw = _write(out / "raw.mp4", "raw video bytes")
    adopted = _json(out / "adopt.json", {"outputs": [
        {"role": "editorial", "path": str(native.resolve()), "sha256": _sha(native)},
        {"role": "raw", "path": str(raw.resolve()), "sha256": _sha(raw)}]})
    receipt = _json(out / "render.json", {"native": {"path": str(native.resolve()), "sha256": _sha(native)},
                                          "adopt": video_cli.state_mod.ref(out, adopted)})
    if media:
        preparation = _json(out / "preparation.json", {
            **{role: {"path": str(media[role].resolve()), "sha256": _sha(media[role])}
               for role in ("template", "anchor", "wav")},
            "faces": [{"path": str(media["faces_0"].resolve()), "sha256": _sha(media["faces_0"])}],
            "refs": [{"path": str(media["refs_0"].resolve()), "sha256": _sha(media["refs_0"])}]})
        body = json.loads(receipt.read_text("utf-8"))
        body["preparation"] = video_cli.state_mod.ref(out, preparation)
        body["h3_inputs"] = video_cli.state_mod.ref(out, video_cli.render_mod.manifest_path(out))
        _json(receipt, body)
    state = video_cli.state_mod.read_state(out, "S01_A")
    state["receipts"]["render"] = video_cli.state_mod.ref(out, receipt)
    video_cli.state_mod.write_state(out, state)
    return {"ok": True}


def _successful_render(tmp_path, monkeypatch):
    from types import SimpleNamespace
    ctx = SimpleNamespace(root=tmp_path / "episode")
    out = tmp_path / "video"
    media = _video_inputs_setup(ctx, out)
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", lambda *a, **kw: _fake_render_result(out, media))
    video_cli._render_logged(ctx, out, _video_args(), None, None)
    return ctx, out, media
