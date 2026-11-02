"""``jjv layout plan`` and ``jjv layout check`` (CPU only; the shared scene_layout.py runs as a subprocess)."""

from __future__ import annotations

import json
import shutil

import pytest

from engine.core.errors import Refused
from engine.layout import check as layout_check
from engine.layout.cast import load_cast
from images_fixtures import EXAMPLES, LIVE, World, make_png, run_layout


def test_plan_writes_set_one_brief_per_cut_shot_and_binds_cast_by_sha(tmp_path):
    world = World(tmp_path)
    out = tmp_path / "layout"
    code, summary = run_layout(["plan", "--episode", str(world.root), "--out", str(out), "--cast", str(world.cast),
                                "--map", "mother=mom-alice", "--machine", str(world.machine_path)])
    assert code == 0
    assert summary["briefs"] == ["briefs/S01_A.brief.json", "briefs/S02_A.brief.json", "briefs/S03_A.brief.json"]
    assert summary["carry"] == {"S01_B": "S01_A"}
    plan = json.loads((out / "layout-plan.json").read_text("utf-8"))
    s01 = plan["shots"][0]
    assert {c["role"]: c["character_id"] for c in s01["cast"]} == {"mother": "mom-alice", "alice": "alice"}
    assert all(len(c["sha256"]) == 64 for c in s01["cast"])
    assert set(plan["tool"]) == {"scene_layout.py", "scene-layout.schema.json", "bpy_layout_template.py",
                                 "bpy_layout_passes_template.py"}
    brief = json.loads((out / "briefs" / "S01_A.brief.json").read_text("utf-8"))
    assert brief["status"] == "draft" and brief["provenance"]["jjv_scaffold"]["filled"] is False
    assert all(a["cast_ref"] for a in brief["actors"])


def test_plan_refuses_unbound_roles_and_a_cast_file_that_does_not_match_its_sha(tmp_path):
    world = World(tmp_path)
    code, _ = run_layout(["plan", "--episode", str(world.root), "--out", str(tmp_path / "a"), "--cast", str(world.cast),
                          "--machine", str(world.machine_path)])   # `mother` has no cast id of that name
    assert code == 1 and not (tmp_path / "a" / "layout-plan.json").exists()
    world.mom.write_bytes(world.mom.read_bytes() + b"x")             # now the sha in the manifest is stale
    with pytest.raises(Refused, match="hash mismatch"):
        load_cast(world.cast)


def test_live_action_domain_gets_previz_status_and_no_cast_in_the_brief(tmp_path):
    world = World(tmp_path, domain=LIVE)
    out = tmp_path / "layout"
    world.plan_layout(out)
    brief = json.loads((out / "briefs" / "S01_A.brief.json").read_text("utf-8"))
    assert brief["status"] == "previz_only"
    assert all("cast_ref" not in a for a in brief["actors"])


def test_check_refuses_a_scaffold_then_passes_once_the_geometry_is_filled(tmp_path):
    world = World(tmp_path)
    out = tmp_path / "layout"
    world.plan_layout(out)
    code, report = run_layout(["check", "--layout", str(out)])
    assert code == 1 and not report["ok"]
    assert any("SCAFFOLD_UNFILLED" in p for p in report["briefs"]["S01_A"]["problems"])
    world.fill_briefs(out)
    code, report = run_layout(["check", "--layout", str(out)])
    assert code == 0 and report["ok"], report
    assert [(p["from"], p["to"]) for p in report["pairs"]] == [("S01_A", "S01_B"), ("S01_B", "S02_A"), ("S02_A", "S03_A")]
    assert report["pairs"][0]["same_layout"] is True          # a carry shares its cut's layout
    assert (out / "placement" / "S01_A.txt").read_text("utf-8").strip()
    assert (out / "storyboard-check.json").is_file() and (out / "continuity-plan.json").is_file()


def test_check_reports_a_continuity_mismatch_and_the_transitions_it_allows(tmp_path):
    world = World(tmp_path)
    out = tmp_path / "layout"
    world.plan_layout(out)
    world.fill_briefs(out)
    for name in ("scene-layout.example.ep04-S03_B.cartoon.json", "scene-layout.example.ep04-S04_A-mismatch.cartoon.json",
                 "scene-set.example.ep04-garden.json"):
        shutil.copy(EXAMPLES / name, out / "briefs" / name)
    (out / "briefs" / "S02_A.brief.json").write_text(
        (EXAMPLES / "scene-layout.example.ep04-S03_B.cartoon.json").read_text("utf-8"), encoding="utf-8")
    (out / "briefs" / "S03_A.brief.json").write_text(
        (EXAMPLES / "scene-layout.example.ep04-S04_A-mismatch.cartoon.json").read_text("utf-8"), encoding="utf-8")
    code, report = run_layout(["check", "--layout", str(out)])
    pair = next(p for p in report["pairs"] if (p["from"], p["to"]) == ("S02_A", "S03_A"))
    assert pair["classification"] == "MISMATCH" and pair["allowed_transitions"] == ["bloom", "whip", "cut"]
    assert report["continuity_mismatches"] == ["S02_A->S03_A"]
    assert code == 0, report   # a mismatch restricts the transition type; it is not a failure


def test_check_refuses_when_the_shared_tool_changed_since_the_plan(tmp_path):
    world = World(tmp_path)
    out = tmp_path / "layout"
    world.plan_layout(out)
    plan = json.loads((out / "layout-plan.json").read_text("utf-8"))
    plan["tool"]["scene_layout.py"] = "0" * 64
    (out / "layout-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(Refused, match="tool changed"):
        layout_check.check_layout(out)


def test_an_invalid_brief_is_reported_not_crashed(tmp_path):
    world = World(tmp_path)
    out = tmp_path / "layout"
    world.plan_layout(out)
    world.fill_briefs(out)
    broken = json.loads((out / "briefs" / "S01_A.brief.json").read_text("utf-8"))
    broken["camera"]["lens_mm"] = -1
    (out / "briefs" / "S01_A.brief.json").write_text(json.dumps(broken), encoding="utf-8")
    code, report = run_layout(["check", "--layout", str(out)])
    assert code == 1 and any("SCHEMA" in p for p in report["briefs"]["S01_A"]["problems"])
    make_png(tmp_path / "unused.png")
