"""T-E42: the transition preset library, part 1: defaults, frames, params, direction, shows_both, tail.
Every expectation is derived from the catalog JSON (see preset_fixtures.py), on real ep04 inputs.
"""

from __future__ import annotations

import pytest

from editorial_fixtures import Inputs, probe_override
from engine.core.errors import Refused
from preset_fixtures import (FIXED_FRAMES, FREE_FRAMES, GENEROUS, NEW_PRESETS, NO_TAIL_PRESETS, PRESETS, TAIL_PRESETS,
                             WITH_PARAMS, default_frames, default_params, record_at, tail_count, use, window_of)


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- accepted defaults + record fields -----------------------------------------------------------
@pytest.mark.parametrize("name", NEW_PRESETS)
def test_a_preset_with_no_frames_takes_its_defaults_and_records_them(inputs: Inputs, name: str) -> None:
    p = PRESETS[name]
    use(inputs, name)
    record = record_at(inputs.build(probe=GENEROUS))
    frames = default_frames(p)
    assert (record["type"], record["preset"], record["renders_as"]) == (name, name, p["renders_as"])
    assert record["frames"] == frames and record["shows_both"] is p["shows_both"]
    assert record["params"] == default_params(p)
    assert (record["start"], record["end_exclusive"]) == window_of(p, 1010, frames)
    assert record["continuity"] == ("agree" if p["shows_both"] else "mismatch")
    tail = tail_count(p, frames)
    if tail:
        assert record["outgoing_tail"]["tail_output_frames"] == tail
        assert record["outgoing_tail"]["tail_frames_needed"] == -(-tail * 4 // 5)
    else:
        assert "outgoing_tail" not in record


@pytest.mark.parametrize("name", NEW_PRESETS)
def test_the_record_is_the_same_in_events_and_config(inputs: Inputs, name: str) -> None:
    use(inputs, name)
    built = inputs.build(probe=GENEROUS)
    assert record_at(built) == next(t for t in built.config["motion"]["transitions"] if t["boundary"] == 1010)


@pytest.mark.parametrize("name", [n for n in NEW_PRESETS if "schedule" in PRESETS[n]])
def test_the_dip_family_records_its_schedule_and_overlay(inputs: Inputs, name: str) -> None:
    p = PRESETS[name]
    use(inputs, name)
    record = record_at(inputs.build(probe=GENEROUS))
    assert record["schedule"] == p["schedule"] and record["overlay"] == p["overlay"]
    assert record["frames"] == len(p["schedule"])
    assert sum(1 for e in record["schedule"] if e["white"] == 1.0) == 1  # exactly one pure-colour frame
    hidden = sum(1 for e in p["schedule"] if e["t"] >= 0 and e["shot"] != "in")
    assert record["incoming_hidden_frames"] == hidden
    if p["overlay"]["kind"] == "colour":
        assert record["white_colour"] == p["overlay"]["colour"]


def test_the_approved_dip_white_keeps_the_warm_white_colour(inputs: Inputs) -> None:
    use(inputs, "dip_white")
    record = record_at(inputs.build(probe=GENEROUS))
    assert record["white_colour"] == "#FFF8EC" and record["incoming_hidden_frames"] == 2
    assert record["outgoing_tail"]["tail_output_frames"] == 1 and len(record["schedule"]) == 8
    assert "pure white f1011" in record["placement"]


# ---- frames rules -------------------------------------------------------------------------------
@pytest.mark.parametrize("name", FREE_FRAMES)
def test_frames_must_stay_inside_the_preset_bounds(inputs: Inputs, name: str) -> None:
    rule = PRESETS[name]["frames"]
    step = 2 if rule.get("even") else 1
    for bad in (rule["min"] - step, rule["max"] + step):
        use(inputs, name, frames=bad)
        with pytest.raises(Refused, match="frames"):
            inputs.build(probe=GENEROUS)
    for good in (rule["min"], rule["max"]):
        use(inputs, name, frames=good)
        assert record_at(inputs.build(probe=GENEROUS))["frames"] == good


@pytest.mark.parametrize("name", [n for n in FREE_FRAMES if PRESETS[n]["frames"].get("even")])
def test_an_even_preset_refuses_an_odd_frame_count(inputs: Inputs, name: str) -> None:
    use(inputs, name, frames=PRESETS[name]["frames"]["min"] + 1)
    with pytest.raises(Refused, match="even"):
        inputs.build(probe=GENEROUS)


@pytest.mark.parametrize("name", FIXED_FRAMES)
def test_a_fixed_preset_takes_exactly_its_frame_count(inputs: Inputs, name: str) -> None:
    fixed = PRESETS[name]["frames"]["fixed"]
    use(inputs, name, frames=fixed)
    assert record_at(inputs.build(probe=GENEROUS))["frames"] == fixed
    use(inputs, name, frames=fixed + 3)
    with pytest.raises(Refused, match=f"{fixed} frames|frames must be {fixed}"):
        inputs.build(probe=GENEROUS)


# ---- params ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", NEW_PRESETS)
def test_an_unknown_param_is_refused(inputs: Inputs, name: str) -> None:
    use(inputs, name, params={"no_such_param": 1})
    with pytest.raises(Refused, match="unknown param 'no_such_param'"):
        inputs.build(probe=GENEROUS)


def _bad_values(spec: dict) -> list:
    if spec["type"] == "enum":
        return ["bogus"]
    if spec["type"] == "boolean":
        return ["yes", 1]
    out: list = ["text", True]
    if "max" in spec:
        out.append(spec["max"] + 1)
    if "min" in spec:
        out.append(spec["min"] - 1)
    if spec["type"] == "integer":
        out.append(spec["default"] + 0.5)
    return out


def _good_values(spec: dict) -> list:
    if spec["type"] == "enum":
        return list(spec["values"])
    if spec["type"] == "boolean":
        return [True, False]
    return [spec["min"], spec["max"]]


@pytest.mark.parametrize("name", WITH_PARAMS)
def test_params_are_type_and_range_checked(inputs: Inputs, name: str) -> None:
    for key, spec in PRESETS[name]["params"].items():
        for bad in _bad_values(spec):
            use(inputs, name, params={key: bad})
            with pytest.raises(Refused, match=key):
                inputs.build(probe=GENEROUS)
        for good in _good_values(spec):
            use(inputs, name, params={key: good})
            assert record_at(inputs.build(probe=GENEROUS))["params"][key] == good


# ---- direction ------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", [n for n in NEW_PRESETS if PRESETS[n]["direction"] == "required"])
def test_a_directional_preset_needs_minus_one_or_plus_one(inputs: Inputs, name: str) -> None:
    for direction in (-1, 1):
        use(inputs, name, direction=direction)
        assert record_at(inputs.build(probe=GENEROUS))["direction"] == direction
    use(inputs, name, direction=0)
    with pytest.raises(Refused, match="direction"):
        inputs.build(probe=GENEROUS)
    row = use(inputs, name)
    del row["direction"]
    with pytest.raises(Refused, match="direction"):
        inputs.build(probe=GENEROUS)


@pytest.mark.parametrize("name", [n for n in NEW_PRESETS if PRESETS[n]["direction"] != "required"])
def test_a_non_directional_preset_builds_without_a_direction(inputs: Inputs, name: str) -> None:
    row = use(inputs, name)
    del row["direction"]
    assert record_at(inputs.build(probe=GENEROUS))["direction"] == 0


# ---- shows_both vs continuity -----------------------------------------------------------------------
@pytest.mark.parametrize("name", [n for n in NEW_PRESETS if PRESETS[n]["shows_both"]])
@pytest.mark.parametrize("continuity", ["mismatch", "unknown"])
def test_a_shows_both_preset_is_refused_between_pictures_unless_they_agree(inputs: Inputs, name: str,
                                                                          continuity: str) -> None:
    use(inputs, name, continuity=continuity)
    with pytest.raises(Refused, match="both sides in one frame"):
        inputs.build(probe=GENEROUS)


@pytest.mark.parametrize("name", [n for n in NEW_PRESETS if not PRESETS[n]["shows_both"]])
@pytest.mark.parametrize("continuity", ["mismatch", "unknown", "agree"])
def test_a_one_shot_preset_is_allowed_whatever_the_continuity(inputs: Inputs, name: str, continuity: str) -> None:
    use(inputs, name, continuity=continuity)
    assert record_at(inputs.build(probe=GENEROUS))["preset"] == name


# ---- tail rule: never a silent GPU request ------------------------------------------------------------
@pytest.mark.parametrize("name", TAIL_PRESETS)
def test_a_missing_handle_is_refused_naming_the_boundary_and_asking_for_no_gpu(inputs: Inputs, name: str) -> None:
    use(inputs, name)
    with pytest.raises(Refused) as caught:
        inputs.build(probe=probe_override("S03_B-native.mp4", 100))   # no tail frame beyond the 100 the cut uses
    text = str(caught.value)
    assert "boundary f1010 S03_B -> S04_A" in text and "tail handle too short" in text
    assert text.endswith("no GPU work is requested; choose a preset without a tail or restore the tail separately")


@pytest.mark.parametrize("name", TAIL_PRESETS)
def test_a_tail_preset_without_a_tail_clip_is_refused_with_the_same_message(inputs: Inputs, name: str) -> None:
    row = use(inputs, name)
    del row["tail_clip"]
    with pytest.raises(Refused, match="tail_clip is required.*no GPU work is requested"):
        inputs.build(probe=GENEROUS)


@pytest.mark.parametrize("name", NO_TAIL_PRESETS)
def test_a_preset_without_a_tail_needs_no_handle(inputs: Inputs, name: str) -> None:
    row = use(inputs, name)
    del row["tail_clip"]
    record = record_at(inputs.build(probe=probe_override("S03_B-native.mp4", 100)))   # S03_B has no spare frame
    assert "outgoing_tail" not in record and record["preset"] == name


def test_only_the_frames_beyond_the_cut_count_for_a_half_tail_preset(inputs: Inputs) -> None:
    # card_flip_3d at 18 frames takes ceil(18/2) = 9 tail frames -> needs ceil(0.8 x 9) = 8 native tail frames
    use(inputs, "card_flip_3d", frames=18)
    with pytest.raises(Refused, match="7 native tail frame.*8 needed"):
        inputs.build()                           # S03_B has 7 tail frames
    use(inputs, "card_flip_3d", frames=16)      # 8 tail frames -> needs 7
    assert record_at(inputs.build())["outgoing_tail"]["tail_output_frames"] == 8


# ---- cut / none / carry rules -------------------------------------------------------------------------
def test_cut_is_a_designed_hard_cut_with_no_frames(inputs: Inputs) -> None:
    use(inputs, "cut")
    record = record_at(inputs.build(probe=GENEROUS))
    assert (record["frames"], record["start"], record["end_exclusive"]) == (0, 1010, 1010)
    assert record["placement"] == "hard cut"


def test_a_carry_still_requires_none_and_a_cut_still_refuses_none(inputs: Inputs) -> None:
    inputs.row(240).update({"type": "cut", "frames": 0})
    with pytest.raises(Refused, match="carry is pixel-continuous"):
        inputs.build()
    inputs2 = Inputs(inputs.tmp)
    inputs2.row(390).update({"type": "none", "frames": 0, "direction": 0})
    with pytest.raises(Refused, match="hard cut must have a designed transition"):
        inputs2.build()


