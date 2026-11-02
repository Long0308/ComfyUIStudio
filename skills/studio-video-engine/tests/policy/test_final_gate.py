"""Guard 1: FINAL gate (NO_FINAL_UNTIL_SHOTS_APPROVED). CPU only, no ffmpeg."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.assemble import cutkind, render
from engine.core.errors import Refused
from engine.policy import final_gate

GATED = {"final_gate": {"enabled": True, "rule": "NO_FINAL_UNTIL_SHOTS_APPROVED"}}
SHA_A, SHA_B = "a" * 64, "b" * 64


def write_pick(root: Path, shot: str, sha: str, decision: str = "pick", name: str = "001-pick.json") -> Path:
    path = root / shot / "acceptance" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "jjv/h3-acceptance/v1", "decision": decision,
                                "subject": {"sha256": sha}}), encoding="utf-8")
    return path


def test_unapproved_shots_are_named_and_refused(tmp_path):
    write_pick(tmp_path, "S01", SHA_A)
    with pytest.raises(Refused) as caught:
        final_gate.check_shots(GATED, [("S01", [SHA_A]), ("S02", [SHA_B])], [tmp_path], verb="edit assemble")
    text = str(caught.value)
    assert text.startswith("FINAL_GATE_UNAPPROVED") and "S02" in text and "S01 (" not in text


def test_all_approved_passes_and_returns_bound_rows(tmp_path):
    write_pick(tmp_path, "S01", SHA_A)
    write_pick(tmp_path, "S02", SHA_B)
    rows = final_gate.check_shots(GATED, [("S01", [SHA_A]), ("S02", [None, SHA_B])], [tmp_path], verb="x")
    assert [r["shot"] for r in rows] == ["S01", "S02"] and rows[0]["sha256"] == SHA_A


def test_approval_is_bound_to_the_exact_sha(tmp_path):
    write_pick(tmp_path, "S01", SHA_A)
    with pytest.raises(Refused):
        final_gate.check_shots(GATED, [("S01", [SHA_B])], [tmp_path], verb="x")


def test_a_rejected_sha_is_never_approved(tmp_path):
    write_pick(tmp_path, "S01", SHA_A)
    write_pick(tmp_path, "S01", SHA_A, "reject", "002-reject.json")
    with pytest.raises(Refused) as caught:
        final_gate.check_shots(GATED, [("S01", [SHA_A])], [tmp_path], verb="x")
    assert "rejected" in str(caught.value)


def test_domain_without_a_gate_is_untouched_jenniejoy_unchanged():
    assert final_gate.check_shots({"domain_id": "jenniejoy_cartoon_3d"}, [("S01", [SHA_A])], [], verb="x") == []
    assert final_gate.require_final_master({"domain_id": "jenniejoy_cartoon_3d"}, __file__, verb="x") is None
    assert cutkind.effective_tag(None, "final", "v1") == "v1"
    assert cutkind.effective_tag(None, "preview", "v1") == "v1"  # not gated: name and receipt unchanged
    real = json.loads((Path(__file__).resolve().parents[2] / "domains" / "jenniejoy_cartoon_3d.json").read_text("utf-8"))
    assert not final_gate.enabled(real)


def test_newtecons_domain_declares_the_gate():
    real = json.loads((Path(__file__).resolve().parents[2] / "domains" / "newtecons_live_action.json").read_text("utf-8"))
    assert final_gate.enabled(real) and real["final_gate"]["rule"] == "NO_FINAL_UNTIL_SHOTS_APPROVED"


def test_preview_is_labelled_and_final_is_not_relabelled():
    gate = GATED["final_gate"]
    assert cutkind.effective_tag(gate, "preview", "v4") == "preview-v4"
    assert cutkind.effective_tag(gate, "preview", "preview-v4") == "preview-v4"
    assert cutkind.effective_tag(gate, "final", "v4") == "v4"
    with pytest.raises(Refused):
        cutkind.effective_tag(gate, "draft", "v4")


def fake_validation(*pairs):
    return {"segments": [{"id": sid, "kind": "clip", "sha256": sha} for sid, sha in pairs]
            + [{"id": "card", "kind": "card"}]}


def test_assemble_gate_refuses_final_and_lets_preview_through(tmp_path):
    gate = GATED["final_gate"]
    validation = fake_validation(("S01", SHA_A), ("S02", SHA_B))
    with pytest.raises(Refused) as caught:
        cutkind.gate_cut(gate, validation, "final", [tmp_path])
    assert "S01" in str(caught.value) and "S02" in str(caught.value) and "card" not in str(caught.value)
    assert cutkind.gate_cut(gate, validation, "preview", [tmp_path]) == {"cut_kind": "preview", "approvals": []}
    write_pick(tmp_path, "S01", SHA_A)
    write_pick(tmp_path, "S02", SHA_B)
    done = cutkind.gate_cut(gate, validation, "final", [tmp_path])
    assert done["cut_kind"] == "final" and len(done["approvals"]) == 2


def test_clip_may_name_the_approved_take_it_was_derived_from(tmp_path):
    write_pick(tmp_path, "S01", SHA_A)
    validation = {"segments": [{"id": "S01", "kind": "clip", "sha256": SHA_B, "approved_sha256": SHA_A}]}
    assert cutkind.gate_cut(GATED["final_gate"], validation, "final", [tmp_path])["approvals"][0]["sha256"] == SHA_A


def test_policy_carries_the_gate_and_assemble_refuses_before_any_render(tmp_path, monkeypatch):
    tracks = [{"stem": s, "title": s, "codec": "flac", "language": "vie", "verify_exact": True}
              for s in ("final", "dialogue", "music", "sfx")]
    tracks[0]["default"] = True
    block = {"enabled": True, "edl_schema": "demo/film-edl/v1", "master": {"width": 2560, "height": 1440, "fps": 24},
             "review": {"width": 1920, "height": 1080}, "kinds": ["clip", "card", "slate"],
             "transitions": ["cut", "dissolve"], "fonts": {"regular": "C:/Windows/Fonts/arial.ttf"},
             "audio": {"sample_rate": 48000, "dialogue_ref_dbfs": -16.5, "tracks": tracks}}
    doc = {"domain_id": "demo", "delivery": {"assemble": block}, **GATED}
    built = render.AssemblePolicy.from_domain(doc)
    assert built.final_gate == GATED["final_gate"]
    edl = tmp_path / "edl.json"
    edl.write_text(json.dumps({"film_id": "f", "schema": "demo/film-edl/v1", "fps": 24, "segments": []}), "utf-8")
    monkeypatch.setattr(render, "validate_edl", lambda *a, **k: {**fake_validation(("S01", SHA_A)), "total_frames": 5, "shas": {}})
    with pytest.raises(Refused) as caught:
        render.assemble(edl, tmp_path / "out", "t1", built, base=tmp_path)
    assert str(caught.value).startswith("FINAL_GATE_UNAPPROVED") and not (tmp_path / "out" / "work-t1").exists()


def test_deliver_needs_a_final_master_receipt(tmp_path):
    master = tmp_path / "master.mp4"
    master.write_bytes(b"film")
    digest = final_gate.sha256_file(master)

    def receipt(kind):
        (tmp_path / "receipt-t.json").write_text(json.dumps(
            {"schema": "jjv/assemble-receipt/v1", "cut_kind": kind, "outputs": {"master": {"sha256": digest}}}), "utf-8")
    receipt("preview")
    with pytest.raises(Refused) as caught:
        final_gate.require_final_master(GATED, master, verb="deliver film-2k")
    assert "FINAL" in str(caught.value)
    receipt("final")
    assert final_gate.require_final_master(GATED, master, verb="deliver film-2k")["master_sha256"] == digest


def test_seedvr2_execute_gate_uses_each_plan_shot(tmp_path):
    from engine import cli_runtime
    executor = SimpleNamespace(config=SimpleNamespace(domain=GATED), tasks=None)
    tasks = [SimpleNamespace(shot={"shot_id": "S01", "source_sha256": SHA_A}),
             SimpleNamespace(shot={"shot_id": "S01", "source_sha256": SHA_A})]
    args = SimpleNamespace(approvals=[str(tmp_path)])
    with pytest.raises(Refused) as caught:
        cli_runtime.require_final_for_execute(executor, tasks, args)
    assert "S01" in str(caught.value)
    write_pick(tmp_path, "S01", SHA_A)
    cli_runtime.require_final_for_execute(executor, tasks, args)
    cli_runtime.require_final_for_execute(SimpleNamespace(config=SimpleNamespace(domain={})), tasks, SimpleNamespace(approvals=[]))


def test_master_config_final_needs_approved_cores_and_render_reads_the_stamp(tmp_path):
    from engine.edit import master_config_cli
    from engine.editorial import segments_edit_cli
    doc = {"build_mode": "master", "dialogue": [{"id": "d1", "segments": [{"shot": "S01", "final_sha256": SHA_A}]}]}
    with pytest.raises(Refused):
        master_config_cli.apply_final_gate(GATED, doc, [tmp_path])
    write_pick(tmp_path, "S01", SHA_A)
    stamped = master_config_cli.apply_final_gate(GATED, doc, [tmp_path])
    assert stamped["final_gate"]["status"] == "approved"
    assert master_config_cli.apply_final_gate({}, doc, [])  == doc
    path = tmp_path / "mc.json"
    path.write_text(json.dumps({**doc, "final_gate": {"status": "unapproved"}}), "utf-8")
    with pytest.raises(Refused):
        segments_edit_cli.require_approved_master_config(path)
    path.write_text(json.dumps(stamped), "utf-8")
    segments_edit_cli.require_approved_master_config(path)


def write_decisions(folder: Path, name: str, shots: list, **extra) -> Path:
    path = folder / name
    path.write_text(json.dumps({"schema": "newtecons/user-decisions/v1", "date": "2026-11-01",
                                "approved_shots": shots, **extra}), encoding="utf-8")
    return path


def test_user_decisions_review26_shape_approves_by_file_sha_and_by_prefix(tmp_path):
    clip = tmp_path / "S02_A_seedvr2.mp4"
    clip.write_bytes(b"s02 approved bytes")
    real = final_gate.sha256_file(clip)
    write_decisions(tmp_path, "USER-DECISIONS-2026-11-01-2125-REVIEW26.json", [
        {"id": "S02_A", "user": "S02_A DUYET", "file": str(clip), "sha256": real, "note": "primary"},
        {"id": "S05_SCREEN", "user": "earlier approval", "sha256_prefix": SHA_B[:8]}])
    rows = final_gate.check_shots(GATED, [("S02_A", [real]), ("S05_SCREEN", [SHA_B])], [tmp_path], verb="x")
    assert [r["shot"] for r in rows] == ["S02_A", "S05_SCREEN"] and rows[0]["record"].endswith("#S02_A")
    with pytest.raises(Refused):  # a different take of the same shot is not approved
        final_gate.check_shots(GATED, [("S02_A", [SHA_A])], [tmp_path], verb="x")


def test_user_decisions_are_read_from_every_file_and_a_changed_file_voids_its_row(tmp_path):
    clip = tmp_path / "S03.mp4"
    clip.write_bytes(b"v1")
    old = final_gate.sha256_file(clip)
    write_decisions(tmp_path, "USER-DECISIONS-2026-11-01-v003.json", [{"id": "S03_A", "file": str(clip), "sha256": old}])
    write_decisions(tmp_path, "USER-DECISIONS-2026-11-01-2125-REVIEW26.json", [{"id": "S01", "sha256": SHA_A}])
    assert len(final_gate.check_shots(GATED, [("S03_A", [old]), ("S01", [SHA_A])], [tmp_path], verb="x")) == 2
    clip.write_bytes(b"v2 re-rendered after approval")  # bytes no longer the ones the user approved
    with pytest.raises(Refused):
        final_gate.check_shots(GATED, [("S03_A", [old])], [tmp_path], verb="x")


def test_short_prefix_is_not_an_approval_and_gate_reads_declared_decision_roots(tmp_path, monkeypatch):
    write_decisions(tmp_path, "USER-DECISIONS-x.json", [{"id": "S09", "sha256_prefix": SHA_A[:4]}])
    with pytest.raises(Refused):
        final_gate.check_shots(GATED, [("S09", [SHA_A])], [tmp_path], verb="x")
    monkeypatch.setattr(final_gate, "REPO_ROOT", tmp_path)
    (tmp_path / "decisions").mkdir()
    write_decisions(tmp_path / "decisions", "USER-DECISIONS-y.json", [{"id": "S01", "sha256": SHA_A}])
    gate = {"enabled": True, "decision_roots": ["decisions"]}
    assert final_gate.check_shots({"final_gate": gate}, [("S01", [SHA_A])], [], verb="x")[0]["shot"] == "S01"
