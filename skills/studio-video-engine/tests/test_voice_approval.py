"""voice approve: listen approval bound to the WAV sha256, enforced by finalize, checkable by H3 prepare."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest
from config_fixtures import make_world
from test_voice_finalize import FFMPEG, make
from test_voice_plan import cast_doc, dialogue_doc

from engine.config import loader
from engine.config.loader import resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.voice import approval, finalize, receipts

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "bin"))
import jjv  # noqa: E402

pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not available")
JOB = "dialogue:S01_A"


def job_of(context: finalize.FinalizeContext, request_id: str = JOB) -> dict:
    return next(j for j in context.plan["jobs"] if j["request_id"] == request_id)


def approve(context: finalize.FinalizeContext, job: dict, **kwargs) -> dict:
    options = {"by": "Ken", "note": "ok", "sha256": None, "episode_root": context.episode_root, **kwargs}
    return approval.approve(context.out, job, **options)


def test_the_real_domains_require_listen_approval() -> None:
    for name in ("jenniejoy_cartoon_3d", "newtecons_live_action"):
        data = json.loads((SKILL_ROOT / "domains" / f"{name}.json").read_text(encoding="utf-8"))
        assert data["voice"]["require_listen_approval"] is True, name


def test_unapproved_wavs_are_refused_before_anything_is_written(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    assert context.settings.require_listen_approval is True
    with pytest.raises(Refused, match="E_LISTEN_APPROVAL.*dialogue:S01_A.*not approved"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists() and not (context.out / receipts.FINALIZE_FILE).exists()
    report = finalize.dry_run(context)
    assert report["listen_approval"]["required"] and len(report["listen_approval"]["blocked"]) == 3


def test_approval_is_bound_to_the_native_sha_and_recorded_in_the_receipt(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    job = job_of(context)
    native_sha = read_json(receipts.job_dir(context.out, JOB) / receipts.TAKE)["native"]["sha256"]
    result = approve(context, job, note="clear, warm", sha256=native_sha.upper(), now=1.0)
    assert result["status"] == "APPROVED" and result["subject_sha256"] == native_sha
    record = read_json(approval.approval_path(context.out, JOB))
    assert record["subject"]["sha256"] == native_sha and record["approved_by"] == "Ken"
    assert record["request_sha256"] == job["request_sha256"]
    assert approve(context, job, note="again")["status"] == "ALREADY_APPROVED"
    for other in context.plan["jobs"][1:]:
        approve(context, other)
    receipt = finalize.run_finalize(context)
    bound = receipt["entries"][0]["listen_approval"]
    assert bound["required"] is True and bound["subject_sha256"] == native_sha and bound["approved_by"] == "Ken"
    assert bound["record_sha256"] == sha256_file(approval.approval_path(context.out, JOB))
    assert receipt["listen_approval"] == {"required": True}
    assert finalize.run_finalize(context) == receipt  # the binding has no timestamp: the receipt stays idempotent


def test_an_approval_of_another_wav_does_not_count(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    for job in context.plan["jobs"]:
        approve(context, job)
    path = approval.approval_path(context.out, JOB)
    record = read_json(path)
    record["subject"]["sha256"] = "0" * 64
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(Refused, match="approval is bound to another WAV"):
        finalize.run_finalize(context)
    assert not (context.out / "finalize").exists()


def test_who_can_approve_and_what_is_checked(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    job = job_of(context)
    for by in ("", "  ", "claude", "Opus 5.5", "auto-approver agent"):
        with pytest.raises(Refused, match="E_APPROVAL_BY"):
            approve(context, job, by=by)
    with pytest.raises(Refused, match="E_APPROVAL_NOTE"):
        approve(context, job, note=" ")
    with pytest.raises(Refused, match="not the bound native take"):
        approve(context, job, sha256="a" * 64)
    (receipts.job_dir(context.out, JOB) / receipts.TAKE).unlink()
    with pytest.raises(Refused, match="no bound take"):
        approve(context, job)
    assert not approval.approval_path(context.out, JOB).exists()


def test_a_domain_without_the_requirement_finalizes_unapproved_and_stays_stable(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    relaxed = dataclasses.replace(context, settings=dataclasses.replace(context.settings, require_listen_approval=False))
    receipt = finalize.run_finalize(relaxed)
    assert receipt["listen_approval"] == {"required": False}
    assert all(e["listen_approval"] == {"required": False} for e in receipt["entries"])


def test_h3_prepare_check_resolves_any_derived_wav_back_to_the_approved_take(tmp_path: Path) -> None:
    context = make(tmp_path, approved=False)
    for job in context.plan["jobs"]:
        approve(context, job)
    receipt = finalize.run_finalize(context)
    segment_sha = receipt["entries"][1]["split"]["segments"][0]["sha256"]
    for sha in (receipt["entries"][0]["receipt_wav"]["sha256"], receipt["entries"][0]["editorial"]["sha256"], segment_sha):
        got = approval.require_wav_approved(context.out, context.plan, sha, context.episode_root)
        assert got["approval"]["approved_by"] == "Ken"
    with pytest.raises(Refused, match="not in voice-finalize.json"):
        approval.require_wav_approved(context.out, context.plan, "f" * 64, context.episode_root)
    approval.approval_path(context.out, JOB).unlink()
    with pytest.raises(Refused, match="no listen approval"):
        approval.require_wav_approved(context.out, context.plan, receipt["entries"][0]["receipt_wav"]["sha256"],
                                      context.episode_root)


def test_cli_approve_list_and_refusals(tmp_path: Path, capsys, monkeypatch) -> None:
    world = make_world(tmp_path)
    monkeypatch.setattr(loader, "DEFAULT_MACHINE_PATH", world.machine_path)
    config = resolve_episode(str(world.episode_file), skill_root=world.skill_root, machine_path=world.machine_path)
    eid = config.episode["episode_id"]
    (tmp_path / "d.json").write_text(json.dumps(dialogue_doc(eid)), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps(cast_doc(eid)), encoding="utf-8")
    out = tmp_path / "voice-v001"
    ep = ["--episode", str(world.episode_file), "--out", str(out)]
    assert jjv.main(["voice", "plan", *ep, "--dialogue", str(tmp_path / "d.json"), "--cast", str(tmp_path / "c.json")]) == 0
    capsys.readouterr()
    assert jjv.main(["voice", "approve", *ep, "--list"]) == 0
    rows = json.loads(capsys.readouterr().out)["jobs"]
    assert [r["approved"] for r in rows] == [False] * 3 and rows[0]["reason"].startswith("no bound take")
    assert jjv.main(["voice", "approve", *ep, "--job", JOB, "--by", "Ken", "--note", "x"]) == 1
    assert "no bound take" in json.loads(capsys.readouterr().out)["error"]
    assert jjv.main(["voice", "approve", *ep, "--job", "dialogue:S99_Z", "--by", "Ken", "--note", "x"]) == 1
    assert "planned request ids" in json.loads(capsys.readouterr().out)["error"]
    assert jjv.main(["voice", "approve", *ep, "--job", JOB, "--by", "claude", "--note", "x"]) == 1
    assert "E_APPROVAL_BY" in json.loads(capsys.readouterr().out)["error"]
