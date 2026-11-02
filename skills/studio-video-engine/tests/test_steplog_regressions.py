"""Regression coverage for STEPLOG findings #03, #04, #05, #07 and #10."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.core import steplog
from engine.core.errors import Refused, Uncertain
from engine.core.io import canonical_json
from engine.video import cli as video_cli
from test_steplog import (
    _chain, _decisions, _fake_render_result, _lines, _sha, _step, _successful_render,
    _video_args, _video_inputs_setup, _write, _json,
)


def test_complete_refuses_empty_outputs(tmp_path):
    with pytest.raises(Refused, match="outputs are empty"):
        with steplog.logged_step(tmp_path, run_id="r", step_id="s", stage="test"):
            pass
    assert not (tmp_path / steplog.LOG_NAME).exists()


def test_verify_refuses_historical_complete_with_empty_outputs(tmp_path):
    _step(tmp_path, "s", [], tmp_path / "out", "value")
    record = json.loads(_lines(tmp_path)[0])
    record["outputs"] = []
    (tmp_path / steplog.LOG_NAME).write_bytes(canonical_json(record, mode="utf8") + b"\n")
    assert any("COMPLETE has no outputs" in e for e in steplog.verify(tmp_path)["errors"])
    assert _decisions(tmp_path) == {"s": "rerun"}


def test_render_registers_all_mp4_paths_and_hashes(tmp_path, monkeypatch):
    _, out, _ = _successful_render(tmp_path, monkeypatch)
    record = json.loads(_lines(out)[0])
    assert record["status"] == "COMPLETE"
    videos = [item for item in record["outputs"] if item["path"].endswith(".mp4")]
    assert {item["path"] for item in videos} == {"native.mp4", "raw.mp4"}
    assert all(item["sha256"] == _sha(out / item["path"]) for item in videos)
    assert steplog.verify(out)["ok"]


@pytest.mark.parametrize("filename", ["native.mp4", "raw.mp4"])
@pytest.mark.parametrize("damage", ["delete", "modify"])
def test_render_missing_or_changed_mp4_cannot_be_reused(tmp_path, monkeypatch, filename, damage):
    _, out, _ = _successful_render(tmp_path, monkeypatch)
    path = out / filename
    if damage == "delete":
        path.unlink()
    else:
        path.write_bytes(b"damaged")
    assert not steplog.verify(out)["ok"]
    assert _decisions(out) == {"video.render.S01_A.r001": "rerun"}


@pytest.mark.parametrize("role", ["template", "anchor", "wav", "refs_0", "faces_0"])
def test_render_hashes_actual_inputs_and_detects_media_changes(tmp_path, monkeypatch, role):
    ctx, out, media = _successful_render(tmp_path, monkeypatch)
    record = json.loads(_lines(out)[0])
    inputs = {item["role"]: item for item in record["inputs"]}
    assert inputs[role]["sha256"] == _sha(media[role])
    assert Path(inputs[role]["path"]) == media[role].resolve()
    _write(media[role], "changed media")
    assert _decisions(out) == {"video.render.S01_A.r001": "rerun"}
    # A fresh snapshot/input_key differs without editing any receipt bytes.
    fresh = [steplog.file_ref(out, path, r)["sha256"] for r, path in video_cli._render_inputs(ctx, out, "S01_A")]
    assert steplog.input_key(record["step_id"], fresh, record["settings"], record["model"]) != record["input_key"]


def test_render_missing_state_raises_uncertain_and_never_calls_verb(tmp_path, monkeypatch):
    from types import SimpleNamespace
    def unexpected(*a, **kw):
        pytest.fail("missing state must stop before render")
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", unexpected)
    with pytest.raises(Uncertain, match="state.json is missing"):
        video_cli._render_logged(SimpleNamespace(root=tmp_path), tmp_path, _video_args(), None, None)
    record = json.loads(_lines(tmp_path)[0])
    assert record["status"] == "FAIL" and "Uncertain" in record["error"]


def test_gate_without_manifest_logs_known_inputs_and_missing_manifest(tmp_path, monkeypatch):
    from types import SimpleNamespace
    ctx = SimpleNamespace(root=tmp_path / "episode")
    out = tmp_path / "video"
    _video_inputs_setup(ctx, out)
    video_cli.render_mod.manifest_path(out).unlink()
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", lambda *a, **kw: {"gate": {"user_gate": True}})
    video_cli._render_logged(ctx, out, _video_args(), None, None)
    record = json.loads(_lines(out)[0])
    assert record["status"] == "SKIPPED"
    assert {i["role"] for i in record["inputs"]} >= {"plan", "prompt", "plan_template", "h3_inputs"}
    assert next(i for i in record["inputs"] if i["role"] == "h3_inputs")["sha256"] is None


def test_success_cannot_log_complete_with_missing_manifest(tmp_path, monkeypatch):
    from types import SimpleNamespace
    ctx = SimpleNamespace(root=tmp_path / "episode")
    out = tmp_path / "video"
    _video_inputs_setup(ctx, out)
    video_cli.render_mod.manifest_path(out).unlink()
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", lambda *a, **kw: _fake_render_result(out))
    with pytest.raises(Uncertain, match="missing input files"):
        video_cli._render_logged(ctx, out, _video_args(), None, None)
    assert json.loads(_lines(out)[0])["status"] == "FAIL"


def test_rerun_uses_latest_complete_outputs_and_splices_downstream(tmp_path):
    files = _chain(tmp_path)
    _step(tmp_path, "s2", [files["s1"]], files["s2"], "new two")
    assert _decisions(tmp_path) == {"s1": "reuse", "s2": "reuse", "s3": "downstream-rerun"}
    # Updating the consumer finishes the splice without invalidating the producer again.
    _step(tmp_path, "s3", [files["s2"]], files["s3"], "new three")
    assert set(_decisions(tmp_path).values()) == {"reuse"}
    assert len(_lines(tmp_path)) == 5  # old evidence is preserved, including historical drift
    assert not steplog.verify(tmp_path)["ok"]


def test_failed_partial_output_lineage_survives_successful_retry(tmp_path):
    src = _write(tmp_path / "source", "source")
    partial = tmp_path / "partial"
    with pytest.raises(RuntimeError):
        with steplog.logged_step(tmp_path, run_id="run-t", step_id="s2", stage="test", inputs=[("in", src)]) as step:
            step.output(_write(partial, "old partial"), "out")
            raise RuntimeError("failed after output")
    _step(tmp_path, "s3", [partial], tmp_path / "s3", "consumer")
    _step(tmp_path, "s2", [src], partial, "successful replacement")
    assert _decisions(tmp_path) == {"s2": "reuse", "s3": "downstream-rerun"}


def test_from_follows_dependencies_in_reverse_log_order_and_ignores_other_branch(tmp_path):
    src = _write(tmp_path / "src", "source")
    produced = _write(tmp_path / "p", "p")
    consumed = tmp_path / "c"
    _step(tmp_path, "consumer", [produced], consumed, "c")
    _step(tmp_path, "grandchild", [consumed], tmp_path / "g", "g")
    _step(tmp_path, "producer", [src], produced, "p")
    _step(tmp_path, "independent", [src], tmp_path / "i", "i")
    result = {r["step_id"]: r["decision"] for r in steplog.plan_resume(tmp_path, "producer")["steps"]}
    assert result == {"consumer": "downstream-rerun", "grandchild": "downstream-rerun",
                      "producer": "rerun", "independent": "reuse"}
    # Natural invalidation propagates through the same graph, also independent of log order.
    _write(src, "changed source")
    assert _decisions(tmp_path)["grandchild"] == "downstream-rerun"


def test_identical_bytes_at_unrelated_paths_are_not_dependencies(tmp_path):
    a = _write(tmp_path / "a", "same")
    b = _write(tmp_path / "b", "same")
    _step(tmp_path, "consumer", [b], tmp_path / "c", "consumer")
    _step(tmp_path, "producer", [], a, "same")
    result = {r["step_id"]: r["decision"] for r in steplog.plan_resume(tmp_path, "producer")["steps"]}
    assert result == {"consumer": "reuse", "producer": "rerun"}


def test_failed_latest_attempt_never_reuses_an_older_complete(tmp_path):
    _step(tmp_path, "s", [], tmp_path / "out", "good")
    with pytest.raises(RuntimeError):
        with steplog.logged_step(tmp_path, run_id="run-t", step_id="s", stage="test"):
            raise RuntimeError("retry failed")
    assert _decisions(tmp_path) == {"s": "rerun"}


def test_append_still_refuses_corrupt_chain_when_allowing_historical_file_drift(tmp_path):
    files = _chain(tmp_path)
    lines = _lines(tmp_path)
    lines[0] = lines[0].replace(b'"stage":"test"', b'"stage":"evil"')
    (tmp_path / steplog.LOG_NAME).write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(Refused, match="chain broken"):
        _step(tmp_path, "s2", [files["s1"]], files["s2"], "new")



def test_relative_video_out_and_legacy_cwd_relative_media_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.chdir(tmp_path)
    ctx = SimpleNamespace(root=tmp_path / "episode")
    out = Path("video")
    _video_inputs_setup(ctx, out)
    def render(*args, **kwargs):
        assert args[1].is_absolute()
        _fake_render_result(args[1])
        # Existing receipts may hold h3.adopt's old CWD-relative filesystem paths.
        receipt = json.loads((out / "render.json").read_text("utf-8"))
        receipt["native"]["path"] = "video/native.mp4"
        adopted = json.loads((out / "adopt.json").read_text("utf-8"))
        for item in adopted["outputs"]:
            item["path"] = "video/" + Path(item["path"]).name
        _json(out / "adopt.json", adopted)
        receipt["adopt"] = video_cli.state_mod.ref(out, out / "adopt.json")
        _json(out / "render.json", receipt)
        state = video_cli.state_mod.read_state(out, "S01_A")
        state["receipts"]["render"] = video_cli.state_mod.ref(out, out / "render.json")
        video_cli.state_mod.write_state(out, state)
        return {"ok": True}
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", render)
    video_cli._render_logged(ctx, out, _video_args(), None, None)
    assert steplog.verify(out)["ok"]
    outputs = json.loads(_lines(out)[0])["outputs"]
    assert {i["path"] for i in outputs if i["path"].endswith(".mp4")} == {"native.mp4", "raw.mp4"}


@pytest.mark.parametrize("role", ["template", "anchor", "wav", "faces_0", "refs_0", "h3_inputs"])
def test_resume_never_rebinds_old_mp4_to_changed_inputs(tmp_path, monkeypatch, role):
    ctx, out, media = _successful_render(tmp_path, monkeypatch)
    original = json.loads(_lines(out)[0])
    path = video_cli.render_mod.manifest_path(out) if role == "h3_inputs" else media[role]
    path.write_bytes(path.read_bytes() + b" ")
    def must_not_render(*args, **kwargs):
        pytest.fail("resume with drift must fail before the render verb")
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", must_not_render)
    args = _video_args()
    args.resume = True
    with pytest.raises(Uncertain):
        video_cli._render_logged(ctx, out, args, None, None)
    records = [json.loads(line) for line in _lines(out)]
    assert [record["status"] for record in records] == ["COMPLETE", "FAIL"]
    assert records[0] == original
    assert _decisions(out) == {"video.render.S01_A.r001": "rerun"}


def test_resume_with_original_preparation_keeps_old_mp4_and_succeeds(tmp_path, monkeypatch):
    ctx, out, _ = _successful_render(tmp_path, monkeypatch)
    before = _sha(out / "native.mp4")
    monkeypatch.setattr(video_cli.verbs_mod, "render_shot", lambda *a, **kw: {"ok": True})
    args = _video_args()
    args.resume = True
    video_cli._render_logged(ctx, out, args, None, None)
    assert [json.loads(line)["status"] for line in _lines(out)] == ["COMPLETE", "COMPLETE"]
    assert _sha(out / "native.mp4") == before
    assert steplog.verify(out)["ok"]
