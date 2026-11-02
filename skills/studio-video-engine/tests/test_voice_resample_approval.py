"""H3 approval inheritance is bound to generated tones, files, request and source approval."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from wav_fixtures import tone_wav_bytes

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.h3.prepare import voice_proof
from engine.voice import approval, receipts, resample_lineage
from engine.seedvr2.seam_media import find_ffmpeg


def write_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def setup_lineage(tmp_path: Path):
    out = tmp_path / "voice"
    out.mkdir()
    source, derived = out / "source.wav", out / "derived.wav"
    source.write_bytes(tone_wav_bytes(seconds=0.5, rate=24000, channels=1))
    lineage = resample_lineage.convert(find_ffmpeg(None), source, derived)
    job = {"request_id": "dialogue:S01_A", "request_sha256": "a" * 64}
    plan = {"episode_id": "tone-test", "jobs": [job]}
    native = {"path": "source.wav", "sha256": sha256_file(source)}
    output = {"path": "derived.wav", "sha256": sha256_file(derived)}
    take = {"request_sha256": job["request_sha256"], "audio_id": "tone", "native": native}
    write_json(receipts.job_dir(out, job["request_id"]) / receipts.TAKE, take)
    approval.approve(out, job, by="Test Listener", note="generated test tone", sha256=None,
                     episode_root=tmp_path, now=1)
    lineage["approval_record_sha256"] = sha256_file(approval.approval_path(out, job["request_id"]))
    entry = {"request_id": job["request_id"], "category": "dialogue", "native": native,
             "base": output, "editorial": output, "receipt_wav": output, "split": None,
             "transform": {"mode": "resample_lineage"}, "lineage": lineage}
    receipt = {"mode": "resample_lineage", "entries": [entry]}
    write_json(out / receipts.FINALIZE_FILE, receipt)
    write_json(out / receipts.PLAN_FILE, plan)
    write_json(out / receipts.BINDINGS_FILE, {"episode_id": "tone-test", "dialogue": [
        {"id": "S01_A", "request_id": job["request_id"], "audio": output}]})
    return out, plan, receipt, source, derived


def check(out, plan, receipt, tmp_path):
    write_json(out / receipts.FINALIZE_FILE, receipt)
    return approval.require_wav_approved(out, plan, receipt["entries"][0]["receipt_wav"]["sha256"], tmp_path)


def test_source_approval_carries_to_derived_and_h3_voice_proof(tmp_path: Path):
    out, plan, receipt, _, _ = setup_lineage(tmp_path)
    proof = check(out, plan, receipt, tmp_path)
    assert proof["approval"]["subject_sha256"] == receipt["entries"][0]["lineage"]["source_sha256"]
    assert proof["approval"]["approved_by"] == "Test Listener"
    ctx = SimpleNamespace(episode_id="tone-test", root=tmp_path)
    assert voice_proof(ctx, out, receipt["entries"][0]["receipt_wav"], "S01_A") == proof


@pytest.mark.parametrize("mutation,code", [
    ("approval_missing", "APPROVAL"), ("approval_request_changed", "APPROVAL"),
    ("approval_record_changed", "APPROVAL"), ("source_sha_changed", "SOURCE"),
    ("approval_malformed_json", "APPROVAL"),
    ("source_file_changed", "SOURCE"), ("derived_file_changed", "DERIVED"),
    ("derived_sha_changed", "DERIVED"), ("unknown_job", "JOB"),
    ("lineage_deleted", "MISSING"), ("top_mode_deleted_lineage_deleted", "MISSING"),
    ("transform_deleted_lineage_deleted", "MISSING"), ("lineage_not_dict", "INVALID"),
    ("duration_changed", "DURATION"),
])
def test_invalid_lineage_is_refused_with_named_error(tmp_path: Path, mutation: str, code: str):
    out, plan, receipt, source, derived = setup_lineage(tmp_path)
    entry = receipt["entries"][0]
    record_path = approval.approval_path(out, plan["jobs"][0]["request_id"])
    if mutation == "approval_missing":
        record_path.unlink()
    elif mutation == "approval_malformed_json":
        record_path.write_text("{malformed", encoding="utf-8")
    elif mutation.startswith("approval_"):
        record = json.loads(record_path.read_text())
        record["request_sha256" if mutation == "approval_request_changed" else "note"] = "changed"
        write_json(record_path, record)
    elif mutation == "source_sha_changed":
        entry["lineage"]["source_sha256"] = "f" * 64
    elif mutation == "source_file_changed":
        source.write_bytes(tone_wav_bytes(seconds=0.7, rate=24000, channels=1))
    elif mutation == "derived_file_changed":
        derived.write_bytes(tone_wav_bytes(seconds=0.7, rate=48000, channels=2))
    elif mutation == "derived_sha_changed":
        entry["lineage"]["derived_sha256"] = "f" * 64
    elif mutation == "unknown_job":
        entry["request_id"] = "dialogue:unknown"
    elif mutation.endswith("lineage_deleted") or mutation == "lineage_deleted":
        del entry["lineage"]
        if mutation.startswith("top_mode"):
            del receipt["mode"]
        if mutation.startswith("transform"):
            del entry["transform"]
    elif mutation == "lineage_not_dict":
        entry["lineage"] = []
    elif mutation == "duration_changed":
        entry["lineage"]["derived_duration_s"] += 0.002
    with pytest.raises(Refused, match=f"E_VOICE_LINEAGE_{code}"):
        check(out, plan, receipt, tmp_path)


def test_missing_source_approval_refused_through_h3_boundary(tmp_path: Path):
    out, plan, receipt, _, _ = setup_lineage(tmp_path)
    approval.approval_path(out, plan["jobs"][0]["request_id"]).unlink()
    ctx = SimpleNamespace(episode_id="tone-test", root=tmp_path)
    with pytest.raises(Refused, match="E_VOICE_LINEAGE_APPROVAL"):
        voice_proof(ctx, out, receipt["entries"][0]["receipt_wav"], "S01_A")
