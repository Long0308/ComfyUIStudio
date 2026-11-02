"""M9b-4: ``plan explain`` consumes Studio feedback notes (annotation only; tmp_path fixtures, no process, no network).

Notes NEVER change rows / actions / costs and never edit inputs.  Absent feedback -> output identical to before.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import test_plan_support as S
from engine.core.errors import Refused
from engine.plan import cli
from engine.plan.api import plan_explain
from test_plan_support import base_config, mix_plan, mutate, record, shot_of, write_version

SKILL = Path(__file__).resolve().parents[1]
ART = "b" * 64
DOMAIN = "test_domain"
EPISODE = "synthetic"
RECEIPT_NEW = "evidence/h3-new.json"
RECEIPT_OLD = "evidence/h3-old.json"
RECEIPT_FREE = "evidence/free.json"
IDS = ["3c361f57-8485-4e9a-b58a-9fd25f4f765f", "7f0e6c5a-0b1d-4f6e-8a1b-2c3d4e5f6a7b",
       "11111111-2222-4333-8444-555555555555", "22222222-3333-4444-8555-666666666666"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _world(tmp_path: Path) -> dict:
    root = tmp_path / "ep"
    (root / "engine").mkdir(parents=True)
    (root / "engine" / "episode.json").write_text(json.dumps({"episode_id": EPISODE, "domain": DOMAIN}), encoding="utf-8")
    for rel, doc in ((RECEIPT_NEW, {"frame_count": 100, "media": {"sha256": ART}}),
                     (RECEIPT_OLD, {"frame_count": 100, "media": {"sha256": "c" * 64}}),
                     (RECEIPT_FREE, {"stage": "timing"})):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(doc), encoding="utf-8")
    shas = {r: _sha(root / r) for r in (RECEIPT_NEW, RECEIPT_OLD, RECEIPT_FREE)}

    def ev(rel: str, art: str | None, shot: str | None = "S01_B", stage: str = "h3") -> dict:
        return {"receipt": rel, "receipt_sha256": shas[rel], "stage": stage, "shot": shot, "artifact_sha256": art}

    def core(config: dict) -> None:
        shot_of(config, "S01_B")["segments"][0]["sha256"] = S.sha("clip-v2")

    old = write_version(root / "versions", "old", base_config(), plan=mix_plan(), record=record(),
                        descriptor={"review_evidence": [ev(RECEIPT_OLD, "c" * 64)]})
    new = write_version(root / "versions", "new", mutate(base_config(), core), plan=mix_plan(), record=record(),
                        descriptor={"review_evidence": [ev(RECEIPT_NEW, ART), ev(RECEIPT_FREE, None, None, "timing")]})
    return {"root": root, "old": old, "new": new, "shas": shas}


def _note(world: dict, nid: str, rel: str, **over) -> dict:
    rec = {"schema": "jjv/studio-feedback/v1", "id": nid, "domain": DOMAIN, "episode": EPISODE, "shot": "S01_B",
           "stage": "h3", "verdict": "changes", "note": "mouth", "author": "Dir", "ts": "2026-10-28T14:00:00.000Z",
           "receipt": rel, "receipt_sha256": world["shas"][rel], "artifact_sha256": ART, "frame": 3, "supersedes": None}
    rec.update(over)
    return rec


def _put(world: dict, *records: dict, name: str = "feedback-v1.jsonl", canonical: bool = True) -> Path:
    path = (world["root"] / "editorial" / "review-feedback" / name) if canonical else world["root"] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join((json.dumps(r, separators=(",", ":")) + "\n").encode() for r in records))
    return path


def _explain(world: dict, **kw) -> dict:
    return plan_explain(world["old"], world["new"], **kw)


def test_no_feedback_arguments_leave_the_document_without_a_feedback_key(tmp_path: Path) -> None:
    world = _world(tmp_path)
    assert "feedback" not in _explain(world)


def test_cli_without_episode_is_byte_identical_to_the_pre_feedback_output(tmp_path: Path, capsys) -> None:
    world = _world(tmp_path)
    cli.main(["explain", "--old", str(world["old"]), "--new", str(world["new"]), "--no-table"])
    out = capsys.readouterr().out
    assert out == json.dumps(_explain(world), indent=2, ensure_ascii=True) + "\n"
    assert '"feedback"' not in out


def test_feedback_requires_episode(tmp_path: Path, capsys) -> None:
    world = _world(tmp_path)
    path = _put(world, _note(world, IDS[0], RECEIPT_NEW))
    code = cli.main(["explain", "--old", str(world["old"]), "--new", str(world["new"]), "--feedback", str(path)])
    assert code == 1 and "--feedback requires --episode" in capsys.readouterr().out


def test_episode_alone_with_no_default_file_reports_present_false(tmp_path: Path) -> None:
    world = _world(tmp_path)
    doc = _explain(world, episode=world["root"])
    fb = doc["feedback"]
    assert fb["present"] is False and fb["notes"] == [] and fb["sha256"] is None and fb["line_count"] == 0
    base = {k: v for k, v in doc.items() if k != "feedback"}
    assert base == _explain(world)


def test_default_path_notes_are_annotated_with_binding_and_related_nodes(tmp_path: Path) -> None:
    world = _world(tmp_path)
    path = _put(world, _note(world, IDS[0], RECEIPT_NEW),
                _note(world, IDS[1], RECEIPT_OLD, artifact_sha256="c" * 64),
                _note(world, IDS[2], RECEIPT_FREE, stage="timing", shot=None, artifact_sha256=None, frame=None,
                      verdict="comment"),
                _note(world, IDS[3], RECEIPT_NEW, stage="script", shot=None, verdict="comment", artifact_sha256=None,
                      frame=None))
    doc = _explain(world, episode=world["root"])
    fb = doc["feedback"]
    assert fb["sha256"] == _sha(path) and fb["bytes"] == path.stat().st_size and fb["line_count"] == 4 and fb["present"]
    by = {n["id"]: n for n in fb["notes"]}
    assert by[IDS[0]]["binding"] == "new" and by[IDS[0]]["line"] == 1
    assert by[IDS[0]]["related_nodes"] == ["motion.h3[S01_B]"]
    assert by[IDS[0]]["related_changed"] == [{"node": "motion.h3[S01_B]", "status": "CHANGED",
                                              "action_code": next(r for r in doc["rows"] if r["node"] == "motion.h3[S01_B]")["action_code"]}]
    assert by[IDS[1]]["binding"] == "old"
    assert by[IDS[2]]["binding"] == "new" and "timing.words" in by[IDS[2]]["related_nodes"]
    assert by[IDS[3]]["binding"] == "unbound" and by[IDS[3]]["related_nodes"] == []
    assert IDS[3] in fb["unmapped"]
    assert fb["by_node"]["motion.h3[S01_B]"] == [IDS[0], IDS[1]]   # an old-cut note stays an old-cut note
    assert fb["unresolved_changes"] == [IDS[0], IDS[1]]


def test_notes_never_change_rows_actions_costs_or_gpu_gate(tmp_path: Path) -> None:
    world = _world(tmp_path)
    plain = _explain(world)
    _put(world, _note(world, IDS[0], RECEIPT_NEW), _note(world, IDS[1], RECEIPT_OLD, artifact_sha256="c" * 64))
    annotated = _explain(world, episode=world["root"])
    for key in ("rows", "summary", "headline", "pins", "old", "new", "costs", "policy", "warnings", "target"):
        assert annotated[key] == plain[key], key
    assert annotated["summary"]["gpu_jobs_need_approval"] == ["motion.h3[S01_B]"]


def test_a_note_on_a_receipt_not_in_the_version_evidence_is_unbound(tmp_path: Path) -> None:
    world = _world(tmp_path)
    for side in ("old", "new"):                       # drop all evidence from both versions
        (world[side] / "plan-inputs.json").write_text(json.dumps({"schema": "jjv/plan-inputs/v1"}), encoding="utf-8")
    _put(world, _note(world, IDS[0], RECEIPT_NEW))
    note = _explain(world, episode=world["root"])["feedback"]["notes"][0]
    assert note["binding"] == "unbound"


def test_evidence_whose_receipt_bytes_changed_is_not_trusted(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _put(world, _note(world, IDS[0], RECEIPT_NEW))
    doc = _explain(world, episode=world["root"])
    assert doc["feedback"]["notes"][0]["binding"] == "new"
    # the receipt on disk is edited after the descriptor recorded its SHA: association no longer verified
    (world["root"] / RECEIPT_NEW).write_text(json.dumps({"frame_count": 100, "media": {"sha256": ART}, "x": 1}), encoding="utf-8")
    doc = _explain(world, episode=world["root"])
    note = doc["feedback"]["notes"][0]
    assert note["binding"] == "stale" and doc["feedback"]["stale"] == [IDS[0]]
    assert any("review_evidence" in w and RECEIPT_NEW in w for w in doc["warnings"])


def test_stale_note_is_listed_separately_and_does_not_count_as_unresolved(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _put(world, _note(world, IDS[0], RECEIPT_NEW, receipt_sha256="0" * 64))
    fb = _explain(world, episode=world["root"])["feedback"]
    assert fb["stale"] == [IDS[0]] and fb["notes"][0]["binding"] == "stale"
    assert fb["unresolved_changes"] == [] and fb["notes"][0]["related_nodes"] == []


def test_malformed_line_is_refused_with_its_line_number(tmp_path: Path) -> None:
    world = _world(tmp_path)
    path = _put(world, _note(world, IDS[0], RECEIPT_NEW))
    path.write_bytes(path.read_bytes() + b"{not json}\n")
    with pytest.raises(Refused, match="line 2"):
        _explain(world, episode=world["root"])


def test_explicit_missing_file_wrong_episode_and_escape_are_refused(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with pytest.raises(Refused, match="not found"):
        _explain(world, episode=world["root"], feedback=world["root"] / "nope.jsonl")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    with pytest.raises(Refused, match="inside"):
        _explain(world, episode=world["root"], feedback=outside)
    _put(world, _note(world, IDS[0], RECEIPT_NEW, episode="99-other"))
    with pytest.raises(Refused, match="episode"):
        _explain(world, episode=world["root"])


def test_explicit_feedback_file_is_used(tmp_path: Path) -> None:
    world = _world(tmp_path)
    path = _put(world, _note(world, IDS[0], RECEIPT_NEW), name="custom.jsonl", canonical=False)
    fb = _explain(world, episode=world["root"], feedback=path)["feedback"]
    assert fb["path"].endswith("custom.jsonl") and [n["id"] for n in fb["notes"]] == [IDS[0]]


def test_explain_never_modifies_the_feedback_or_inputs(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _put(world, _note(world, IDS[0], RECEIPT_NEW))

    def snap() -> dict:
        return {str(p): (p.stat().st_size, _sha(p)) for p in world["root"].rglob("*") if p.is_file()}

    before = snap()
    _explain(world, episode=world["root"])
    assert snap() == before


def test_table_lists_notes_and_stale_separately_on_stderr(tmp_path: Path, capsys) -> None:
    world = _world(tmp_path)
    _put(world, _note(world, IDS[0], RECEIPT_NEW), _note(world, IDS[1], RECEIPT_NEW, receipt_sha256="0" * 64))
    assert cli.main(["explain", "--old", str(world["old"]), "--new", str(world["new"]),
                     "--episode", str(world["root"])]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["feedback"]["line_count"] == 2
    assert "FEEDBACK" in err and "motion.h3[S01_B]" in err and "STALE" in err and "mouth" in err
    assert err.index("TOTAL") < err.index("FEEDBACK")


def test_real_subprocess_cli_with_feedback_and_without(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _put(world, _note(world, IDS[0], RECEIPT_NEW))
    base = [sys.executable, "-B", str(SKILL / "bin" / "jjv.py"), "plan", "explain", "--old", str(world["old"]),
            "--new", str(world["new"]), "--no-table"]
    with_fb = subprocess.run([*base, "--episode", str(world["root"])], capture_output=True, text=True, env=dict(os.environ))
    without = subprocess.run(base, capture_output=True, text=True, env=dict(os.environ))
    assert with_fb.returncode == 0 and without.returncode == 0
    assert json.loads(with_fb.stdout)["feedback"]["notes"][0]["binding"] == "new"
    assert "feedback" not in json.loads(without.stdout)
    bad = subprocess.run([*base, "--feedback", "x.jsonl"], capture_output=True, text=True)
    assert bad.returncode == 1
