"""Explicit resample-lineage finalize integration; every WAV is a generated tone."""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.voice import approval, cli, finalize, receipts
from test_voice_passthrough import build, needs_ffmpeg


def converted(tmp_path: Path, **kwargs):
    context, native = build(tmp_path, rate=24000, channels=1, **kwargs)
    return replace(context, resample_lineage=True), native


@needs_ffmpeg
def test_conversion_receipt_carries_source_approval_and_numeric_checks(tmp_path: Path) -> None:
    context, native = converted(tmp_path)
    source_bytes = native.read_bytes()
    source_sha = sha256_file(native)
    receipt = finalize.run_finalize(context)
    entry = receipt["entries"][0]
    lineage = entry["lineage"]
    assert receipt["mode"] == "resample_lineage" and receipt["trim"] is None
    assert lineage["schema"] == "jjv/voice-resample-lineage/v1"
    assert lineage["source_sha256"] == source_sha == entry["receipt_wav"]["source_sha256"]
    assert lineage["derived_sha256"] == entry["receipt_wav"]["sha256"] != source_sha
    assert lineage["approval_record_sha256"] == sha256_file(approval.approval_path(context.out, entry["request_id"]))
    assert lineage["converter_version"].startswith("ffmpeg version")
    assert "resampler=soxr" in lineage["converter_command_line"]
    assert "precision=28" in lineage["converter_command_line"]
    assert abs(lineage["source_duration_s"] - lineage["derived_duration_s"]) <= 0.001
    assert lineage["checks"]
    assert native.read_bytes() == source_bytes
    assert entry["trim"] is None and entry["split"] is None
    assert entry["listen_approval"]["subject_sha256"] == source_sha
    print("finalize lineage checks:", lineage["checks"])


@needs_ffmpeg
def test_explicit_conversion_requires_approval_even_when_domain_does_not(tmp_path: Path) -> None:
    context, _ = converted(tmp_path, approve=False)
    context = replace(context, settings=replace(context.settings, require_listen_approval=False))
    with pytest.raises(Refused, match="E_RESAMPLE_APPROVAL"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()
    assert not (context.out / receipts.FINALIZE_FILE).exists()


@needs_ffmpeg
def test_absent_flag_keeps_legacy_format_refusal(tmp_path: Path) -> None:
    context, _ = build(tmp_path, rate=24000, channels=1)
    with pytest.raises(Refused, match="E_PASSTHROUGH_FORMAT"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()


@needs_ffmpeg
def test_repeat_conversion_is_byte_identical(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    first = finalize.run_finalize(context)
    receipt_path = context.out / receipts.FINALIZE_FILE
    receipt_bytes = receipt_path.read_bytes()
    wav_path = receipts.resolve_described(first["entries"][0]["receipt_wav"]["path"], episode_root=context.episode_root,
                                         out=context.out)
    wav_bytes = wav_path.read_bytes()
    assert finalize.run_finalize(context) == first
    assert receipt_path.read_bytes() == receipt_bytes
    assert wav_path.read_bytes() == wav_bytes


@needs_ffmpeg
def test_existing_conversion_refuses_flag_removal(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    finalize.run_finalize(context)
    with pytest.raises(Refused, match="E_RESAMPLE_OPTIONS"):
        finalize.run_finalize(replace(context, resample_lineage=False))


@needs_ffmpeg
def test_existing_passthrough_refuses_flag_addition(tmp_path: Path) -> None:
    context, _ = build(tmp_path)
    finalize.run_finalize(context)
    with pytest.raises(Refused, match="E_RESAMPLE_OPTIONS"):
        finalize.run_finalize(replace(context, resample_lineage=True))


@needs_ffmpeg
def test_conversion_rejects_pitch_before_writing(tmp_path: Path) -> None:
    context, _ = converted(tmp_path, semitones=1)
    with pytest.raises(Refused, match="E_RESAMPLE_EDIT"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()


@needs_ffmpeg
def test_conversion_rejects_split_before_writing(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    context.plan["jobs"][0]["split"] = {"unexpected": True}
    with pytest.raises(Refused, match="E_RESAMPLE_EDIT"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()


@needs_ffmpeg
def test_conversion_rejects_non_native_source_format(tmp_path: Path) -> None:
    context, _ = build(tmp_path)
    with pytest.raises(Refused, match="E_RESAMPLE_FORMAT"):
        finalize.run_finalize(replace(context, resample_lineage=True))
    assert not (context.out / "finalize").exists()


@needs_ffmpeg
def test_conversion_dry_run_reports_requested_operation_without_writing(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    report = finalize.dry_run(context)
    assert report["mode"] == "resample_lineage"
    assert report["requested_conversion"]["precision"] == 28
    assert report["requested_conversion"]["trim"] is None
    assert report["listen_approval"]["required"] is True
    assert report["jobs"][0]["approved"] is True
    assert not (context.out / "finalize").exists()


def _legacy_module():
    """Read the original implementation as an oracle; all writes use the generated-tone test directory."""
    roots = [Path.cwd(), *Path(__file__).resolve().parents]
    original = next(root / ".agents/skills/studio-video-engine/engine/voice/finalize.py" for root in roots
                    if (root / ".agents/skills/studio-video-engine/engine/voice/finalize.py").is_file())
    name = "engine.voice._lineage_legacy_finalize"
    spec = importlib.util.spec_from_file_location(name, original)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@needs_ffmpeg
def test_passthrough_original_body_and_receipt_bytes_unchanged(tmp_path: Path) -> None:
    legacy = _legacy_module()
    assert inspect.getsource(finalize._passthrough_job) == inspect.getsource(legacy._passthrough_job)
    context, native = build(tmp_path)
    native_bytes = native.read_bytes()
    original_receipt = legacy.run_finalize(context)
    path = context.out / receipts.FINALIZE_FILE
    original_receipt_bytes = path.read_bytes()
    assert finalize.run_finalize(context) == original_receipt
    assert path.read_bytes() == original_receipt_bytes
    assert native.read_bytes() == native_bytes
    assert not (context.out / "finalize").exists()
    print("passthrough original/staged receipt identical bytes:", len(original_receipt_bytes))
    print("passthrough original/staged native identical bytes:", len(native_bytes))


def test_cli_flag_is_explicit_and_defaults_false() -> None:
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="stage"))
    base = ["voice", "finalize", "--episode", "generated", "--out", "generated"]
    assert parser.parse_args(base).resample_lineage is False
    assert parser.parse_args([*base, "--resample-lineage"]).resample_lineage is True


@needs_ffmpeg
def test_cli_prints_measured_lineage_checks(tmp_path: Path, monkeypatch, capsys) -> None:
    context, _ = converted(tmp_path)
    monkeypatch.setattr(cli, "_config", lambda ref: context.config)
    monkeypatch.setattr(cli, "_settings_for_plan", lambda *args: context.settings)
    args = argparse.Namespace(episode="generated-tone", out=str(context.out), ffmpeg=context.ffmpeg,
                              category="all", dry_run=False, resample_lineage=True)
    assert cli.run_finalize(args) == 0
    summary = json.loads(capsys.readouterr().out)
    checks = summary["entries"][0]["lineage_checks"]
    assert isinstance(checks["duration_delta_ms"], (int, float))
    assert isinstance(checks["correlation"], (int, float))
    assert isinstance(checks["residual_db"], (int, float))
    assert checks["delay_samples"] == 0
    assert checks["duration_delta_ms"] <= checks["thresholds"]["duration_delta_ms_max"]
    assert checks["correlation"] >= checks["thresholds"]["correlation_min"]
    assert checks["residual_db"] <= checks["thresholds"]["residual_db_max"]


@needs_ffmpeg
def test_conversion_requires_passthrough_recipe(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    recipe = replace(context.settings.recipe, data={**context.settings.recipe.data, "mode": "synth"})
    context = replace(context, settings=replace(context.settings, recipe=recipe))
    with pytest.raises(Refused, match="E_RESAMPLE_RECIPE"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()


@needs_ffmpeg
def test_conversion_requires_exact_target_format(tmp_path: Path) -> None:
    context, _ = converted(tmp_path)
    data = {**context.settings.recipe.data, "editorial": {"sample_rate": 24000, "channels": 1, "sample_width_bytes": 2}}
    context = replace(context, settings=replace(context.settings, recipe=replace(context.settings.recipe, data=data)))
    with pytest.raises(Refused, match="E_RESAMPLE_FORMAT"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()
