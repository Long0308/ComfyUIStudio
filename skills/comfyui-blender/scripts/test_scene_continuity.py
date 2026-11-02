"""pytest for shot-to-shot continuity: shared SET resolution, `continuity` and `placement-text`.

Run (no GPU, no Blender needed):
    python -m pytest -p no:cacheprovider --basetemp <dir> test_scene_layout.py test_scene_continuity.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scene_continuity as sc  # noqa: E402
import scene_layout as sl  # noqa: E402
import scene_placement as sp  # noqa: E402
import scene_set  # noqa: E402

EXAMPLES = HERE.parent / "assets" / "examples"
SET_FILE = EXAMPLES / "scene-set.example.ep04-garden.json"
S03B = EXAMPLES / "scene-layout.example.ep04-S03_B.cartoon.json"
S04A_MISMATCH = EXAMPLES / "scene-layout.example.ep04-S04_A-mismatch.cartoon.json"
S04A_LOCKED = EXAMPLES / "scene-layout.example.ep04-S04_A-locked.cartoon.json"
LIVE = EXAMPLES / "scene-layout.example.live-action-previz.json"
ALL_FIVE = ["dissolve", "wipe", "bloom", "whip", "cut"]


def load(path: Path) -> dict:
    return copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))


def put(tmp_path: Path, name: str, doc: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def errs(brief: dict, base: Path = EXAMPLES) -> set[str]:
    findings, _ = sl.validate(brief, base)
    return {f.code for f in findings if f.level == "error"}


def find(brief: dict, section: str, ident: str) -> dict:
    return next(x for x in brief[section] if x["id"] == ident)


def pair(mutate_b=None, mutate_a=None) -> dict:
    a, b = load(S03B), load(S04A_LOCKED)
    if mutate_a:
        mutate_a(a)
    if mutate_b:
        mutate_b(b)
    return sc.compare(a, b, EXAMPLES, EXAMPLES)


def entity(report: dict, key: str) -> dict:
    return next(e for e in report["entities"] if e["id"] == key)


# ------------------------------------------------------------------ shared SET

def test_example_set_and_shots_validate_clean() -> None:
    for path in (S03B, S04A_MISMATCH, S04A_LOCKED):
        findings, info = sl.validate(load(path), EXAMPLES)
        assert [f.line() for f in findings] == [], path.name
        assert info["set_id"] == "ep04-garden-example"


def test_set_resolution_merges_set_and_shot_props() -> None:
    res = scene_set.resolve_set(load(S03B), EXAMPLES)
    assert [f.line() for f in res.findings] == []
    ids = {p["id"] for p in res.brief["props"]}
    assert {"TABLE_TOP", "MOTHER_BENCH_SEAT"} <= res.set_prop_ids
    assert {"SEALED_BOTTLE", "CUP_A"} <= ids and not ({"SEALED_BOTTLE", "CUP_A"} & res.set_prop_ids)
    assert res.set_prop_ids <= ids and res.set_id == "ep04-garden-example"
    assert [z["id"] for z in res.brief["ground"]["zones"]] == ["garden"]


def test_set_can_be_referenced_by_id(tmp_path: Path) -> None:
    put(tmp_path, "garden.json", load(SET_FILE))
    brief = load(S03B)
    brief["set"] = "ep04-garden-example"
    assert errs(brief, tmp_path) == set()
    brief["set"] = "no-such-set"
    assert "SET_NOT_FOUND" in errs(brief, tmp_path)
    put(tmp_path, "garden2.json", load(SET_FILE))  # two files claim the same id
    brief["set"] = "ep04-garden-example"
    assert "SET_AMBIGUOUS" in errs(brief, tmp_path)


def test_set_path_not_found() -> None:
    brief = load(S03B)
    brief["set"] = "missing-set.json"
    assert "SET_NOT_FOUND" in errs(brief)


def test_shot_redefining_a_set_prop_differently_is_set_mismatch() -> None:
    brief = load(S03B)
    table = copy.deepcopy(next(p for p in load(SET_FILE)["props"] if p["id"] == "TABLE_TOP"))
    brief["props"].append(table)
    assert errs(brief) == set()  # an identical redefinition is harmless
    table["position"][0] += 0.3
    findings, _ = sl.validate(brief, EXAMPLES)
    mismatch = [f for f in findings if f.code == "SET_MISMATCH"]
    assert mismatch and "TABLE_TOP" in mismatch[0].message and "position" in mismatch[0].message
    assert "DUP_ID" not in {f.code for f in findings}


def test_shot_zone_redefinition_is_set_mismatch() -> None:
    brief = load(S03B)
    brief["ground"] = {"zones": [{"id": "garden", "kind": "garden", "x": [-8, 9], "y": [-11, 4]}]}
    assert "SET_MISMATCH" in errs(brief)


def test_set_domain_must_match_shot_domain(tmp_path: Path) -> None:
    other = load(SET_FILE)
    other["domain"] = "newtecons_live_action"
    other["props"] = [p for p in other["props"] if p["id"].startswith("TABLE")]
    put(tmp_path, "other.json", other)
    brief = load(S03B)
    brief["set"] = "other.json"
    assert "SET_DOMAIN" in errs(brief, tmp_path)


def test_set_file_cannot_carry_actors_or_cast(tmp_path: Path) -> None:
    bad = load(SET_FILE)
    bad["actors"] = [{"id": "X", "role": "adult", "pose": "standing", "position": [0, 0], "facing_deg": 0, "head_top_z": 1.7, "zone": "garden"}]
    put(tmp_path, "bad.json", bad)
    brief = load(S03B)
    brief["set"] = "bad.json"
    assert "SET_INVALID" in errs(brief, tmp_path)
    notset = load(S03B)  # a brief is not a set
    put(tmp_path, "notset.json", notset)
    brief["set"] = "notset.json"
    assert "SET_INVALID" in errs(brief, tmp_path)


def test_set_content_goes_through_domain_leak_check(tmp_path: Path) -> None:
    leaky = load(SET_FILE)
    leaky["props"].append({"id": "NEWTECONS_LOGO", "kind": "box", "position": [0, 0, 1], "size": [1, 0.1, 1]})
    put(tmp_path, "leaky.json", leaky)
    brief = load(S03B)
    brief["set"] = "leaky.json"
    assert "DOMAIN_LEAK" in errs(brief, tmp_path)


def test_ground_is_required_when_no_set() -> None:
    brief = load(S03B)
    del brief["set"]
    assert "GROUND_MISSING" in errs(brief)


def test_schema_accepts_continuity_block_and_rejects_unknown_key() -> None:
    brief = load(S03B)
    brief["continuity"] = {"position_tol_m": 0.1, "facing_tol_deg": 10, "ndc_shift_tol": 0.03, "min_iou": 0.5, "include_set_props": False}
    assert errs(brief) == set()
    brief["continuity"]["surprise"] = 1
    assert "SCHEMA" in errs(brief)


def test_emit_bpy_resolves_the_set() -> None:
    text = sl.emit_bpy(load(S03B), EXAMPLES)
    compile(text, "emitted.py", "exec")
    assert "TABLE_TOP" in text and "SEALED_BOTTLE" in text


# ------------------------------------------------------------------ continuity classification

def test_mismatch_pair_lists_offenders_and_restricts_transitions() -> None:
    report = sc.compare(load(S03B), load(S04A_MISMATCH), EXAMPLES, EXAMPLES)
    assert report["classification"] == "MISMATCH"
    bad = {e["id"] for e in report["entities"] if not e["ok"]}
    assert {"MOTHER", "SEALED_BOTTLE", "CUP_B"} <= bad
    assert entity(report, "ALICE")["ok"] and entity(report, "CUP_A")["ok"]
    assert report["allowed_transitions"] == ["bloom", "whip", "cut"]
    assert any(line.startswith("MOTHER") for line in report["offenders"])
    mother = entity(report, "MOTHER")
    assert mother["displacement_m"] > 0.15 and mother["facing_change_deg"] > 15
    assert mother["iou"] is not None and mother["iou"] < 1.0 and mother["ndc_a"] and mother["ndc_b"]


def test_agree_pair_allows_every_transition() -> None:
    report = pair()
    assert report["classification"] == "AGREE" and report["offenders"] == []
    assert report["allowed_transitions"] == ALL_FIVE
    assert entity(report, "ALICE")["iou"] > 0.8 and entity(report, "SEALED_BOTTLE")["iou"] < 1.0


def test_static_set_props_are_skipped_by_default_but_can_be_included() -> None:
    report = pair()
    assert report["skipped_set_props"] >= 5
    assert "TABLE_TOP" not in {e["id"] for e in report["entities"]}
    def widen(b: dict) -> None:
        b["continuity"] = {"include_set_props": True}
    with_set = pair(mutate_b=widen)
    assert "TABLE_TOP" in {e["id"] for e in with_set["entities"]}
    assert with_set["skipped_set_props"] == 0


def test_pose_change_is_an_offender() -> None:
    def kneel(b: dict) -> None:
        a = find(b, "actors", "ALICE")
        a["pose"], a["head_top_z"], a["support"] = "standing", 1.2, {"kind": "floor", "top_z": 0.0}
    report = pair(mutate_b=kneel)
    assert report["classification"] == "MISMATCH"
    assert any("pose" in line for line in report["offenders"] if line.startswith("ALICE"))


def test_track_as_matches_entities_with_different_ids() -> None:
    def rename(b: dict) -> None:
        find(b, "props", "SEALED_BOTTLE")["id"] = "BOTTLE_LATE"
        find(b, "props", "BOTTLE_LATE")["track_as"] = "SEALED_BOTTLE"
    report = pair(mutate_b=rename)
    row = entity(report, "SEALED_BOTTLE")
    assert row["ids"] == ["SEALED_BOTTLE", "BOTTLE_LATE"] and row["ok"]
    assert "SEALED_BOTTLE" not in report["only_in_a"]


def test_entities_only_in_one_shot_are_reported_not_offenders() -> None:
    def drop(b: dict) -> None:
        b["props"] = [p for p in b["props"] if p["id"] != "CUP_B"]
    report = pair(mutate_b=drop)
    assert report["only_in_a"] == ["CUP_B"] and report["classification"] == "AGREE"


# ------------------------------------------------------------------ tolerance boundaries

def _mother_x(a_x: float, b_x: float, **rules):
    def set_a(a: dict) -> None:
        find(a, "actors", "MOTHER")["position"][0] = a_x
    def set_b(b: dict) -> None:
        find(b, "actors", "MOTHER")["position"][0] = b_x
        b["continuity"] = dict(rules)
    return pair(mutate_a=set_a, mutate_b=set_b)


def test_position_tolerance_boundary_passes_at_exactly_the_limit() -> None:
    rules = {"position_tol_m": 0.25, "ndc_shift_tol": 1.0}
    at_limit = _mother_x(2.0, 2.25, **rules)       # exactly 0.25 m (binary-exact numbers)
    over = _mother_x(2.0, 2.26, **rules)           # 0.26 m
    assert entity(at_limit, "MOTHER")["displacement_m"] == pytest.approx(0.25)
    assert entity(at_limit, "MOTHER")["ok"] and at_limit["classification"] == "AGREE"
    assert not entity(over, "MOTHER")["ok"] and over["classification"] == "MISMATCH"


def test_facing_tolerance_boundary_is_15_degrees_inclusive() -> None:
    def turn(deg: float):
        def f(b: dict) -> None:
            find(b, "actors", "MOTHER")["facing_deg"] = deg
        return f
    base_pose = lambda a: find(a, "actors", "MOTHER").update({"facing_deg": 180})  # noqa: E731
    at_limit = pair(mutate_a=base_pose, mutate_b=turn(165))
    over = pair(mutate_a=base_pose, mutate_b=turn(164))
    wrap = pair(mutate_a=lambda a: find(a, "actors", "MOTHER").update({"facing_deg": 175}), mutate_b=turn(-175))
    assert entity(at_limit, "MOTHER")["facing_change_deg"] == pytest.approx(15.0)
    assert entity(at_limit, "MOTHER")["ok"] and not entity(over, "MOTHER")["ok"]
    assert entity(wrap, "MOTHER")["facing_change_deg"] == pytest.approx(10.0)  # 175 -> -175 wraps through 180


def test_ndc_shift_tolerance_boundary_splits_at_the_measured_shift() -> None:
    probe = _mother_x(2.0, 2.5, position_tol_m=5.0, ndc_shift_tol=1.0)
    shift = entity(probe, "MOTHER")["ndc_centre_shift"]
    assert 0.0 < shift < 0.2
    at = _mother_x(2.0, 2.5, position_tol_m=5.0, ndc_shift_tol=shift)
    under = _mother_x(2.0, 2.5, position_tol_m=5.0, ndc_shift_tol=shift - 1e-6)
    assert entity(at, "MOTHER")["ok"] and not entity(under, "MOTHER")["ok"]
    assert any("screen" in line for line in under["offenders"])


def test_stricter_tolerance_of_the_two_briefs_wins() -> None:
    def tight(a: dict) -> None:
        a["continuity"] = {"position_tol_m": 0.01}
    def loose(b: dict) -> None:
        b["continuity"] = {"position_tol_m": 5.0}
    assert sc.compare(load(S03B), load(S04A_LOCKED), EXAMPLES, EXAMPLES)["tolerances"]["position_tol_m"] == 0.15
    report = pair(mutate_a=tight, mutate_b=loose)
    assert report["tolerances"]["position_tol_m"] == 0.01 and report["classification"] == "MISMATCH"


def test_camera_move_alone_breaks_agreement_on_screen() -> None:
    def sidestep(b: dict) -> None:
        b["camera"]["position_xy"][0] += 0.8  # same world layout, different screen place
        b["camera"]["target"][0] += 0.8
    report = pair(mutate_b=sidestep)
    assert report["classification"] == "MISMATCH"
    assert all(e["displacement_m"] < 0.15 for e in report["entities"])


# ------------------------------------------------------------------ transitions and CLI

def test_transition_not_allowed_on_mismatch_and_ok_on_agree(capsys: pytest.CaptureFixture[str]) -> None:
    mismatch = sc.compare(load(S03B), load(S04A_MISMATCH), EXAMPLES, EXAMPLES, transition="dissolve")
    assert [e["code"] for e in mismatch["errors"]] == ["TRANSITION_NOT_ALLOWED"]
    assert sc.compare(load(S03B), load(S04A_MISMATCH), EXAMPLES, EXAMPLES, transition="wipe")["errors"]
    for t in ("bloom", "whip", "cut"):
        assert sc.compare(load(S03B), load(S04A_MISMATCH), EXAMPLES, EXAMPLES, transition=t)["errors"] == []
    for t in ALL_FIVE:
        assert sc.compare(load(S03B), load(S04A_LOCKED), EXAMPLES, EXAMPLES, transition=t)["errors"] == []
    assert sl.main(["continuity", str(S03B), str(S04A_MISMATCH), "--transition", "dissolve"]) == 1
    out = capsys.readouterr().out
    assert "TRANSITION_NOT_ALLOWED" in out and "MISMATCH" in out


def test_cli_exit_codes_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert sl.main(["continuity", str(S03B), str(S04A_MISMATCH)]) == 1
    text = capsys.readouterr().out
    assert "MOTHER" in text and "allowed: bloom, whip, cut" in text
    assert sl.main(["continuity", str(S03B), str(S04A_LOCKED), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["classification"] == "AGREE" and doc["allowed_transitions"] == ALL_FIVE
    assert sl.main(["continuity", str(S03B), str(EXAMPLES / "nope.json")]) == 2
    with pytest.raises(SystemExit) as exc:
        sl.main(["continuity", str(S03B), str(S04A_LOCKED), "--transition", "spin"])
    assert exc.value.code == 2


def test_wipe_mask_origin_is_clear_of_shared_entities_when_agreeing() -> None:
    report = pair()
    origin = report["wipe_mask_origin"]
    assert origin["usable"] is True and origin["clearance_ndc"] > 0.0
    x, y = origin["ndc"]
    assert -1.0 <= x <= 1.0 and -1.0 <= y <= 1.0 and origin["region"]
    for e in report["entities"]:
        for box in (e["ndc_a"], e["ndc_b"]):
            if box:
                inside = box["x"][0] <= x <= box["x"][1] and box["y"][0] <= y <= box["y"][1]
                assert not inside, (e["id"], origin)
    mismatch = sc.compare(load(S03B), load(S04A_MISMATCH), EXAMPLES, EXAMPLES)
    assert mismatch["wipe_mask_origin"]["usable"] is False  # wipe is not an allowed transition here


def test_incomparable_inputs_are_refused_not_classified(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = load(S03B)
    find(bad, "actors", "MOTHER")["zone"] = "nowhere"
    with pytest.raises(sc.ContinuityError) as invalid:
        sc.compare(bad, load(S04A_LOCKED), EXAMPLES, EXAMPLES)
    assert invalid.value.code == "BRIEF_INVALID"
    wide = load(S04A_LOCKED)
    wide["output"] = {"width": 1000, "height": 1000}
    with pytest.raises(sc.ContinuityError) as aspect:
        sc.compare(load(S03B), wide, EXAMPLES, EXAMPLES)
    assert aspect.value.code == "ASPECT_MISMATCH"
    assert sl.main(["continuity", str(put(tmp_path, "bad.json", bad)), str(S04A_LOCKED)]) == 2


# ------------------------------------------------------------------ domain isolation

def test_continuity_across_domains_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(sc.ContinuityError) as exc:
        sc.compare(load(S03B), load(LIVE), EXAMPLES, EXAMPLES)
    assert exc.value.code == "DOMAIN_MISMATCH"
    assert sl.main(["continuity", str(S03B), str(LIVE)]) == 2
    assert "DOMAIN_MISMATCH" in capsys.readouterr().out


def test_live_action_previz_continuity_works_and_still_has_no_cast() -> None:
    a, b = load(LIVE), load(LIVE)
    b["actors"][0]["position"][0] += 0.05
    report = sc.compare(a, b, EXAMPLES, EXAMPLES)
    assert report["domain"] == "newtecons_live_action" and report["classification"] == "AGREE"
    assert all(e["kind"] in ("actor", "prop") for e in report["entities"])
    b["actors"][0]["cast_ref"] = "some/library/char.png"
    with pytest.raises(sc.ContinuityError) as exc:
        sc.compare(a, b, EXAMPLES, EXAMPLES)
    assert exc.value.code == "BRIEF_INVALID" and "DOMAIN_CAST" in str(exc.value)


# ------------------------------------------------------------------ placement-text

def test_placement_text_is_deterministic_and_order_independent() -> None:
    lines = sp.placement_lines(load(S03B), EXAMPLES)
    assert lines == sp.placement_lines(load(S03B), EXAMPLES)
    shuffled = load(S03B)
    shuffled["actors"].reverse()
    shuffled["props"].reverse()
    assert sp.placement_lines(shuffled, EXAMPLES) == lines
    rebuilt = json.loads(json.dumps(load(S03B), sort_keys=True))
    assert sp.placement_lines(rebuilt, EXAMPLES) == lines


def test_placement_text_content() -> None:
    lines = sp.placement_lines(load(S03B), EXAMPLES)
    joined = "\n".join(lines)
    assert any(l.startswith("Alice kneeling on the cushion, ") and l.endswith("facing screen right") for l in lines)
    assert any(l.startswith("Mother seated on the bench, ") and l.endswith("facing screen left") for l in lines)
    assert any(l.startswith("sealed milk bottle on the garden table, ") for l in lines)
    assert "TABLE_LEG" not in joined.upper().replace(" ", "_") and "table leg" not in joined  # set props are left out
    assert all(l[0].isalpha() and not l.endswith(".") for l in lines)


def test_placement_text_set_props_and_id_filter() -> None:
    all_lines = sp.placement_lines(load(S03B), EXAMPLES, include_set=True)
    default = sp.placement_lines(load(S03B), EXAMPLES)
    assert len(all_lines) > len(default)
    only = sp.placement_lines(load(S03B), EXAMPLES, ids=["SEALED_BOTTLE", "MOTHER"])
    assert len(only) == 2


def test_agree_pair_gives_identical_placement_text_for_unmoved_entities() -> None:
    a = {l.split(",")[0]: l for l in sp.placement_lines(load(S03B), EXAMPLES)}
    b = {l.split(",")[0]: l for l in sp.placement_lines(load(S04A_LOCKED), EXAMPLES)}
    assert a.keys() == b.keys() and a == b  # locked pair repeats the same words in both H3 prompts


def test_mismatch_pair_gives_different_placement_text() -> None:
    a = sp.placement_lines(load(S03B), EXAMPLES)
    b = sp.placement_lines(load(S04A_MISMATCH), EXAMPLES)
    assert a != b


def test_cli_placement_text(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert sl.main(["placement-text", str(S03B)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == sp.placement_lines(load(S03B), EXAMPLES)
    assert sl.main(["placement-text", str(S03B), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["lines"] == out
    bad = load(S03B)
    find(bad, "actors", "ALICE")["zone"] = "nowhere"
    assert sl.main(["placement-text", str(put(tmp_path, "bad.json", bad))]) == 1


# ------------------------------------------------------------------ housekeeping

def test_every_script_stays_under_800_lines() -> None:
    for path in HERE.glob("*.py"):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 800, path.name
