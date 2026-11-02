"""T-E42 follow-up: the RULE layer of ``boundaries suggest`` (pure functions) against the user rule."""

from __future__ import annotations

import json

import pytest

from engine.editorial import boundaries_suggest_rules as rules
from engine.editorial import presets
from engine.editorial.boundaries_suggest_measure import QA_RECIPE, q3_numbers

PICTURES = frozenset({"S01_A", "S01_B"})
DIP_FAMILY = {"dip_white", "dip_black", "light_leak", "film_burn"}
SAME_MIN = q3_numbers()["same_framing_ncc_min"]


def allowed(framing: str, continuity: str = "mismatch") -> list[str]:
    return rules.allowed(framing, continuity, PICTURES, "S01_A", "S01_B")


# ---- the thresholds are the Q3 number plus one calibrated gap --------------------------------------------------
def test_the_same_framing_number_is_the_q3_recipe_value_not_a_copy() -> None:
    recipe = json.loads(QA_RECIPE.read_text("utf-8"))
    assert SAME_MIN == recipe["q3_flash"]["same_framing_ncc_min"] == 0.35
    assert 0 < rules.LAYOUT_CHANGE_NCC_MAX < SAME_MIN


@pytest.mark.parametrize("ncc, expected", [
    (0.540, rules.SAME_FRAMING), (0.35, rules.SAME_FRAMING), (0.334, rules.NEAR_SAME), (0.25, rules.NEAR_SAME),
    (0.136, rules.NEW_FRAMING), (0.018, rules.NEW_FRAMING), (-0.2, rules.NEW_FRAMING)])
def test_three_zones_by_measured_ncc(ncc: float, expected: str) -> None:
    got = rules.classify(ncc, None, SAME_MIN)
    assert (got["framing"], got["source"], got["conflict"]) == (expected, "measured", None)


def test_the_first_user_approved_cut_lands_in_the_expected_zones() -> None:
    """The six measured values of the approved reference cut (push 0.540 / 0.334, whip / dip 0.018 .. 0.136)."""
    zones = [rules.classify(n, None, SAME_MIN)["framing"] for n in (0.540, 0.334, 0.105, 0.018, 0.136, 0.045)]
    assert zones == ["same_framing", "near_same", "new_framing", "new_framing", "new_framing", "new_framing"]


def test_a_declared_same_framing_can_tighten_but_a_declared_change_cannot_loosen() -> None:
    tight = rules.classify(0.10, "same_framing", SAME_MIN)
    assert tight["framing"] == rules.SAME_FRAMING and tight["source"] == "declared" and "declaration wins" in tight["conflict"]
    loose = rules.classify(0.60, "new_framing", SAME_MIN)
    assert loose["framing"] == rules.SAME_FRAMING and loose["source"] == "measured" and "measurement wins" in loose["conflict"]
    assert rules.classify(0.30, "new_framing", SAME_MIN)["framing"] == rules.NEW_FRAMING   # near band: declaration is used


def test_an_unmeasured_boundary_trusts_only_what_is_declared() -> None:
    assert rules.classify(None, None, SAME_MIN)["framing"] == rules.UNMEASURED
    assert rules.classify(None, "same_framing", SAME_MIN)["framing"] == rules.SAME_FRAMING


# ---- what each zone may use ------------------------------------------------------------------------------------
@pytest.mark.parametrize("framing", [rules.SAME_FRAMING, rules.NEAR_SAME])
def test_same_seat_allows_only_a_cut_with_or_without_the_push_never_a_flash_or_pan(framing: str) -> None:
    names = allowed(framing)
    assert sorted(names) == ["cut", "cut_push"]
    assert not DIP_FAMILY & set(names) and "whip" not in names and "pan_motivated" not in names


def test_a_dissolve_family_appears_only_for_measured_same_framing_with_continuity_agree() -> None:
    dissolves = {"crossfade", "blur_crossfade", "focus_pull"}
    assert dissolves <= set(allowed(rules.SAME_FRAMING, "agree"))
    assert not dissolves & set(allowed(rules.SAME_FRAMING, "mismatch"))
    assert not dissolves & set(allowed(rules.SAME_FRAMING, "unknown"))
    assert not dissolves & set(allowed(rules.NEAR_SAME, "agree"))
    assert "dissolve" not in allowed(rules.SAME_FRAMING, "agree")           # the alias name is never a separate choice


def test_a_new_framing_allows_dip_light_and_camera_moves_plus_the_safe_cut_but_no_two_shot_effect() -> None:
    names = set(allowed(rules.NEW_FRAMING, "agree"))      # even with agree: no both-shots effect on a changed layout
    assert names == DIP_FAMILY | {"whip", "pan_motivated", "cut"}
    shows_both = {n for n, p in presets.presets().items() if p.shows_both}
    assert not names & shows_both


def test_every_allowed_name_passes_the_engines_own_row_rules() -> None:
    from engine.editorial import transitions
    for framing in (rules.SAME_FRAMING, rules.NEAR_SAME, rules.NEW_FRAMING, rules.UNMEASURED):
        for name in allowed(framing, "agree"):
            probe = {"from_shot": "S01_A", "to_shot": "S01_B", "class": "cut", "continuity": "agree",
                     "motivation": "x", "frame": 0}
            assert transitions.eligibility(probe, name, PICTURES) is None, (framing, name)


def test_an_unmeasured_boundary_is_offered_nothing_but_the_designed_hard_cut() -> None:
    assert allowed(rules.UNMEASURED) == ["cut"]


# ---- choice order, motivation, direction -----------------------------------------------------------------------
def test_preference_order_by_zone_and_motivation() -> None:
    assert [n for n, _ in rules.preference(rules.SAME_FRAMING, False)] == ["cut_push", "cut"]
    assert [r for _, r in rules.preference(rules.NEAR_SAME, False)][0] == "R3_near_same_push"
    assert [n for n, _ in rules.preference(rules.NEW_FRAMING, True)] == ["whip", "dip_white", "cut"]
    assert [n for n, _ in rules.preference(rules.NEW_FRAMING, False)] == ["dip_white", "whip", "cut"]
    assert dict(rules.preference(rules.NEW_FRAMING, False))["whip"] == "R4b_whip_no_tail"
    assert [n for n, _ in rules.preference(rules.UNMEASURED, True)] == ["cut"]


@pytest.mark.parametrize("row, expected", [
    ({"motivation": "close-up -> wide two-shot; Mother's pointing eyeline in S02_A goes right"}, True),
    ({"motivation": "Mother moves left -> right between the shots"}, True),
    ({"motivation": "G-BRIDGE option A: motivated follow-pan toward the tree"}, True),
    ({"motivation": "x", "g_bridge": "satisfied by a declared transition"}, True),
    ({"motivation": "tree -> bench & book: dip to white; only one shot visible in any frame"}, False),
    ({"motivation": "the company panel opens"}, False),      # 'pan' must be a word, not a substring
    ({}, False)])
def test_a_motion_cue_is_a_declared_bridge_or_a_motion_word(row: dict, expected: bool) -> None:
    assert rules.motion_cue(row)[0] is expected


@pytest.mark.parametrize("text, expected", [
    ("Mother's pointing eyeline in S02_A goes right", (1, "motivation")),
    ("Mother moves left -> right between the shots", (1, "motivation")),     # the LAST side word wins
    ("follow-pan toward the door on the left", (-1, "motivation")),
    ("a motivated pan, no side named", (1, "default")),
    (None, (1, "default"))])
def test_whip_direction_comes_from_the_last_side_word_else_plus_one(text, expected) -> None:
    assert rules.infer_direction(text) == expected


def test_carry_check_flags_a_disagreement_between_entry_kind_and_pixels() -> None:
    assert rules.carry_check("carry", 1.0) is None and rules.carry_check("cut", 0.2) is None
    assert "differ" in rules.carry_check("carry", 0.5)
    assert "almost identical" in rules.carry_check("cut", 0.99)
    assert rules.carry_check("carry", None) is None
