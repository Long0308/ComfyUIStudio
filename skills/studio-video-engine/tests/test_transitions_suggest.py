"""T-E42 follow-up: ``boundaries suggest`` on synthetic episodes (real mp4 clips) and on the real reference episode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.config import loader
from engine.editorial import boundaries_suggest as bs
from engine.editorial import transitions
from engine.editorial.boundaries_suggest_measure import find_ffmpeg, gray_frame, measure_pair, q3_numbers
from engine.qa.gates import q3_flash
from transitions_fixtures import (GRAD_MIX, GRAD_X, GRAD_Y, build, declared, needs_ffmpeg)

pytestmark = needs_ffmpeg


def one(tmp_path: Path, a_expr: str, b_expr: str, rows: list[dict] | None = None, tail: dict | None = None,
        kind: str = "cut", **kwargs) -> dict:
    """The suggestion item of the single boundary S01_A -> S01_B."""
    config, shots = build(tmp_path, [("S01_A", 24, "cut", a_expr), ("S01_B", 24, kind, b_expr)], tail)
    doc = bs.suggest(config, shots, declared(rows) if rows is not None else None, **kwargs)
    return next(it for it in doc["boundaries"] if it["kind"] == "picture")


def row(**extra) -> dict:
    return {"from_shot": "S01_A", "to_shot": "S01_B", **extra}


def types(item: dict) -> list[str]:
    return [o["type"] for o in item["alternatives"]]


# ---- the measure is the Q3 number --------------------------------------------------------------------------------
def test_the_measure_reproduces_q3_ncc_on_the_same_frames(tmp_path: Path) -> None:
    config, shots = build(tmp_path, [("S01_A", 24, "cut", GRAD_X), ("S01_B", 24, "cut", GRAD_MIX)])
    ffmpeg, analysis = find_ffmpeg(), q3_numbers()["analysis"]
    got = measure_pair(tmp_path, shots[0], shots[1], ffmpeg, analysis)
    a = gray_frame(tmp_path / "clips/S01_A-editorial.mp4", 23, ffmpeg, *analysis)
    b = gray_frame(tmp_path / "clips/S01_B-editorial.mp4", 0, ffmpeg, *analysis)
    assert got["ncc"] == round(q3_flash.ncc(q3_flash._small(a), q3_flash._small(b)), 3)
    assert got["from"]["frame_index"] == 23 and got["to"]["frame_index"] == 0
    assert 0.25 <= got["ncc"] < 0.35            # the near band (0.25 GRAD_X + 0.75 GRAD_Y against GRAD_X)


def test_a_missing_clip_is_unmeasured_not_a_crash(tmp_path: Path) -> None:
    config, shots = build(tmp_path, [("S01_A", 24, "cut", GRAD_X), ("S01_B", 24, "cut", GRAD_X)])
    (tmp_path / "clips/S01_B-editorial.mp4").unlink()
    item = next(it for it in bs.suggest(config, shots)["boundaries"] if it["kind"] == "picture")
    assert item["measured"]["ncc"] is None and "not found" in item["measured"]["why"]
    assert item["rule"] == "R6_unmeasured_safe_cut" and item["chosen"]["type"] == "cut" and item["alternatives"] == []


# ---- each zone ---------------------------------------------------------------------------------------------------
def test_same_framing_is_a_hard_cut_with_a_push_in_and_nothing_else_but_the_plain_cut(tmp_path: Path) -> None:
    item = one(tmp_path, GRAD_X, GRAD_X, [row(continuity="mismatch", motivation="props appear")])
    assert item["measured"]["ncc"] == 1.0 and item["framing"]["framing"] == "same_framing"
    assert (item["rule"], item["chosen"]["type"], item["chosen"]["frames"]) == ("R2_same_framing_push", "cut_push", 12)
    assert item["chosen"]["params"] == {"scale_from": 1.04, "ease": "out"}
    assert types(item) == ["cut"] and item["chosen"]["tail"]["needed"] is False


def test_near_same_is_treated_as_same_seat_and_never_suggests_a_flash(tmp_path: Path) -> None:
    item = one(tmp_path, GRAD_X, GRAD_MIX, [row(continuity="mismatch")])
    assert item["framing"]["framing"] == "near_same" and item["rule"] == "R3_near_same_push"
    assert item["chosen"]["type"] == "cut_push" and types(item) == ["cut"]


def test_new_framing_without_a_motivated_move_is_a_dip_to_white_that_needs_a_tail_frame(tmp_path: Path) -> None:
    item = one(tmp_path, GRAD_X, GRAD_Y, [row(continuity="mismatch", motivation="tree to bench")], tail={"S01_A": 13})
    assert item["framing"]["framing"] == "new_framing" and item["rule"] == "R5_new_framing_dip"
    chosen = item["chosen"]
    assert (chosen["type"], chosen["frames"]) == ("dip_white", 8)
    assert chosen["tail"]["needed"] is True and chosen["tail"]["native_frames_needed"] == 1
    assert chosen["tail"]["available"] is True and chosen["tail"]["have_native_frames"] == 13
    assert chosen["tail"]["native_index_range"] == [24, 24]       # the first native frame beyond the 24 editorial ones
    assert {"whip", "dip_black", "light_leak", "film_burn", "cut"} <= set(types(item))
    assert item["row"]["tail_clip"] == "clips/S01_A-native.mp4"


def test_a_dip_without_a_tail_handle_falls_back_to_a_whip_and_says_why(tmp_path: Path) -> None:
    item = one(tmp_path, GRAD_X, GRAD_Y, [row(motivation="tree to bench")])
    assert (item["chosen"]["type"], item["rule"]) == ("whip", "R4b_whip_no_tail")
    assert item["chosen"]["direction_source"] == "default" and item["chosen"]["tail"]["needed"] is False
    assert item["fallback_from"]["type"] == "dip_white" and "no GPU work is requested" in item["fallback_from"]["why"]
    dip = next(o for o in item["alternatives"] if o["type"] == "dip_white")
    assert dip["tail"]["available"] is False and dip["tail"]["needed"] is True


def test_a_new_framing_with_a_motivated_move_is_a_whip_in_the_declared_direction(tmp_path: Path) -> None:
    right = one(tmp_path / "r", GRAD_X, GRAD_Y, [row(motivation="Mother's pointing eyeline goes right")])
    assert (right["rule"], right["chosen"]["type"], right["chosen"]["direction"]) == ("R4_motivated_whip", "whip", 1)
    assert right["chosen"]["frames"] == 8 and right["chosen"]["tail"]["needed"] is False
    left = one(tmp_path / "l", GRAD_X, GRAD_Y, [row(motivation="follow-pan toward the door on the left")])
    assert left["chosen"]["direction"] == -1 and left["chosen"]["direction_source"] == "motivation"
    bridge = one(tmp_path / "b", GRAD_X, GRAD_Y, [row(motivation="x", g_bridge="declared")])
    assert bridge["chosen"]["type"] == "whip" and bridge["chosen"]["direction_source"] == "default"


def test_continuity_agree_adds_the_dissolve_family_only_on_a_measured_same_framing(tmp_path: Path) -> None:
    agree = one(tmp_path / "a", GRAD_X, GRAD_X, [row(continuity="agree")])
    assert {"crossfade", "blur_crossfade", "focus_pull", "cut"} <= set(types(agree))
    assert agree["chosen"]["type"] == "cut_push"        # allowed, never chosen
    assert "crossfade" not in types(one(tmp_path / "m", GRAD_X, GRAD_X, [row(continuity="mismatch")]))


def test_a_declared_framing_tightens_but_cannot_turn_a_measured_same_pair_into_a_change(tmp_path: Path) -> None:
    tight = one(tmp_path / "t", GRAD_X, GRAD_Y, [row(framing="same_framing")])
    assert tight["chosen"]["type"] == "cut_push" and any("declaration wins" in w for w in tight["warnings"])
    loose = one(tmp_path / "l", GRAD_X, GRAD_X, [row(framing="new_framing")])
    assert loose["chosen"]["type"] == "cut_push" and any("measurement wins" in w for w in loose["warnings"])


def test_a_carry_entry_takes_no_transition_and_a_pixel_mismatch_is_warned(tmp_path: Path) -> None:
    ok = one(tmp_path / "ok", GRAD_X, GRAD_X, kind="carry")
    assert (ok["rule"], ok["chosen"]["type"], ok["alternatives"], ok["warnings"]) == ("R1_carry", "none", [], [])
    assert ok["row"]["class"] == "carry" and ok["row"]["frames"] == 0
    bad = one(tmp_path / "bad", GRAD_X, GRAD_Y, kind="carry")
    assert bad["chosen"]["type"] == "none" and any("carry but the boundary frames differ" in w for w in bad["warnings"])


# ---- the document ------------------------------------------------------------------------------------------------
def test_every_suggested_row_passes_the_engines_row_rules_and_the_document_is_deterministic(tmp_path: Path) -> None:
    specs = [("S01_A", 24, "cut", GRAD_X), ("S01_B", 24, "carry", GRAD_X), ("S02_A", 24, "cut", GRAD_Y),
             ("S02_B", 24, "cut", GRAD_MIX), ("S03_A", 24, "cut", GRAD_X)]
    config, shots = build(tmp_path, specs, tail={"S01_B": 13})
    first = bs.suggest(config, shots)
    assert json.dumps(first, sort_keys=True) == json.dumps(bs.suggest(config, shots), sort_keys=True)
    pictures = frozenset(s["shot"] for s in shots)
    frames = [it["frame"] for it in first["boundaries"]]
    assert frames == sorted(frames) and frames[0] == 90          # intro 3 s at 30 fps; INTRO -> S01_A bloom
    for it in first["boundaries"]:
        if it["kind"] == "picture":
            transitions.check_row(transitions.resolve_row(it["row"]), pictures)
    assert [it["chosen"]["type"] for it in first["boundaries"]] == ["bloom", "none", "dip_white", "cut_push", "cut_push"]
    assert first["summary"]["tail_handle_needed"] == ["T150"]


def test_the_frame_of_a_boundary_is_where_the_incoming_shot_starts_on_the_delivery_timeline(tmp_path: Path) -> None:
    config, shots = build(tmp_path, [("S01_A", 24, "cut", GRAD_X), ("S01_B", 48, "cut", GRAD_Y), ("S02_A", 24, "cut", GRAD_X)])
    ids = [it["id"] for it in bs.suggest(config, shots)["boundaries"] if it["kind"] == "picture"]
    assert ids == ["T120", "T180"]          # 90 + 24 x 5/4, then + 48 x 5/4


def test_a_graphic_row_is_kept_as_declared_and_flagged_structural(tmp_path: Path) -> None:
    config, shots = build(tmp_path, [("S01_A", 24, "cut", GRAD_X), ("S01_B", 24, "cut", GRAD_X)])
    kept = {"from_shot": "S01_B", "to_shot": "OUTRO", "frame": 180, "type": "iris", "frames": 44,
            "params": {"disc_fade_frames": 6}}
    items = bs.suggest(config, shots, declared([row(), kept]))["boundaries"]
    graphic = next(it for it in items if it["id"] == "T180")
    assert graphic["rule"] == "R7_graphic_keep" and graphic["row"]["params"] == {"disc_fade_frames": 6}
    assert graphic["row"]["type"] == "iris"


# ---- the real reference episode ------------------------------------------------------------------------------------
EP = loader.REPO_ROOT / "production-local" / "JennieJoyKids-Story" / "04-milk-and-mom"
REAL = pytest.mark.skipif(not (EP / "clips" / "motion-v004" / "S04_B-editorial.mp4").is_file(), reason="episode clips absent")


@REAL
def test_the_reference_cut_is_reproduced_push_where_the_seat_is_the_same_and_never_a_flash_there() -> None:
    config = loader.resolve_episode("04-milk-and-mom")
    doc = bs.suggest(config, config.shots, json.loads((EP / "engine" / "boundaries.json").read_text("utf-8")))
    by = {it["id"]: it for it in doc["boundaries"]}
    for boundary in ("T1010", "T1310"):
        assert by[boundary]["chosen"]["type"] == "cut_push" and by[boundary]["chosen"]["frames"] == 12
        offered = {by[boundary]["chosen"]["type"], *types(by[boundary])}
        assert offered == {"cut_push", "cut"}, offered      # no dip_white / dip_black / light_leak / film_burn / whip
    assert by["T1310"]["measured"]["ncc"] < q3_numbers()["same_framing_ncc_min"]      # the near band
    assert by["T1610"]["chosen"]["type"] == "dip_white" and by["T1610"]["chosen"]["frames"] == 8
    assert {"dip_black", "light_leak", "film_burn"} <= set(types(by["T1610"]))
    assert [by[b]["chosen"]["type"] for b in ("T390", "T710", "T1495")] == ["whip"] * 3
    assert all(by[b]["chosen"]["direction"] == 1 for b in ("T390", "T710", "T1495"))
    assert doc["summary"]["tail_handle_needed"] == ["T1610"] and doc["summary"]["unmeasured"] == []
