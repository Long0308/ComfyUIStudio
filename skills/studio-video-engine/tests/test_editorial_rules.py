"""Editorial rules (transitions, coverage, shows_both): real ep04 inputs, mutated once each."""

from __future__ import annotations

import copy

import pytest

from editorial_fixtures import Inputs, fake_probe, probe_override, probe_returning
from engine.core.errors import Refused, Uncertain
from engine.editorial import captions, end_card, transitions

BOTH_SHOTS = ("dissolve", "cloud", "bubble", "wipe")


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


def _retype(inputs: Inputs, frame: int, kind: str, frames: int, continuity: str, **extra) -> None:
    row = inputs.row(frame)
    row.update({"type": kind, "frames": frames, "continuity": continuity, **extra})


# ---- both shots in one frame -------------------------------------------------------------
@pytest.mark.parametrize("kind", BOTH_SHOTS)
@pytest.mark.parametrize("continuity", ["mismatch", "unknown"])
def test_both_shots_types_are_refused_unless_continuity_agrees(inputs: Inputs, kind: str, continuity: str) -> None:
    _retype(inputs, 1010, kind, 6, continuity)
    with pytest.raises(Refused, match="both sides in one frame"):
        inputs.build()


@pytest.mark.parametrize("kind", BOTH_SHOTS)
def test_both_shots_types_are_allowed_when_continuity_agrees_and_the_tail_fits(inputs: Inputs, kind: str) -> None:
    # T-E42: cloud and wipe are directional presets in the catalog, so the row now names a direction
    _retype(inputs, 1010, kind, 5, "agree", direction=1)
    record = next(t for t in inputs.build().events["transitions"] if t["boundary"] == 1010)
    assert record["type"] == kind and (record["start"], record["end_exclusive"]) == (1010, 1015)
    assert record["outgoing_tail"]["tail_frames_needed"] == 4  # ceil(0.8 * 5)


def test_safe_types_are_allowed_on_a_mismatch(inputs: Inputs) -> None:
    for kind, frames in (("whip", 8), ("dip_white", 9), ("bloom", 6)):
        _retype(inputs, 1010, kind, frames, "mismatch", direction=1 if kind == "whip" else 0)
        inputs.build()


# ---- tail handles ----------------------------------------------------------------------------
def test_tail_only_type_needs_ceil_point_eight_times_n_native_tail_frames(inputs: Inputs) -> None:
    # S03_B: 107 native, 100 used -> 7 tail frames. N=8 needs ceil(6.4)=7 (ok), N=9 needs 8 (refused).
    _retype(inputs, 1010, "dissolve", 8, "agree")
    assert inputs.build().events["transitions"][6]["outgoing_tail"]["tail_frames_needed"] == 7
    _retype(inputs, 1010, "dissolve", 9, "agree")
    with pytest.raises(Refused, match="tail handle too short.*7 native tail frame.*8 needed"):
        inputs.build()


def test_dip_white_counts_only_its_outgoing_tail_frames(inputs: Inputs) -> None:
    built = inputs.build()  # real data: 3 tail output frames, 3 needed
    tail = next(t for t in built.events["transitions"] if t["boundary"] == 1010)["outgoing_tail"]
    assert (tail["tail_output_frames"], tail["tail_frames_needed"], tail["last_native_index_used"]) == (3, 3, 102)


def test_a_clip_with_too_few_tail_frames_is_refused(inputs: Inputs) -> None:
    with pytest.raises(Refused, match="tail handle too short"):
        inputs.build(probe=probe_returning(102))  # S03_B: 100 used -> 2 tail frames < 3


def test_the_last_native_index_must_exist(inputs: Inputs) -> None:
    # N=5 needs 4 tail frames and uses native index ceil((125 + 5 - 1) * 0.8) = 104.
    # 104 native frames give exactly 4 tail frames (enough) but only index 103 exists.
    _retype(inputs, 1010, "dissolve", 5, "agree")
    with pytest.raises(Refused, match="last native index used 104/103"):
        inputs.build(probe=probe_override("S03_B-native.mp4", 104))
    inputs.build(probe=probe_override("S03_B-native.mp4", 105))  # index 104 exists


def test_a_tail_type_without_a_tail_clip_is_refused(inputs: Inputs) -> None:
    del inputs.row(1010)["tail_clip"]
    with pytest.raises(Refused, match="tail_clip is required"):
        inputs.build()


def test_a_missing_tail_clip_file_is_an_unreadable_input(inputs: Inputs) -> None:
    inputs.row(1010)["tail_clip"] = "clips/nope.mp4"
    with pytest.raises(Uncertain, match="tail_clip not found"):
        inputs.build()


def test_a_tail_type_whose_outgoing_side_is_not_a_shot_is_refused(inputs: Inputs) -> None:
    # T-E42: a dissolve between two cards is now refused earlier (picture-only preset on graphics), so the
    # outgoing side that is not a shot is the INTRO card of INTRO -> S01_A
    _retype(inputs, 90, "dissolve", 4, "agree", tail_clip="clips/motion-v005/S03_B-native.mp4")
    with pytest.raises(Refused, match="is not a shot"):
        inputs.build()


def test_tail_frames_needed_is_integer_ceil_of_point_eight() -> None:
    assert [transitions.tail_frames_needed(n) for n in (1, 3, 5, 8, 9, 10)] == [1, 3, 4, 7, 8, 8]


# ---- hard cuts / carries / frames / motivation ---------------------------------------------------
def test_a_hard_cut_must_have_a_designed_type(inputs: Inputs) -> None:
    _retype(inputs, 390, "none", 0, "mismatch", direction=0)
    with pytest.raises(Refused, match="hard cut must have a designed transition"):
        inputs.build()


def test_a_carry_takes_no_transition(inputs: Inputs) -> None:
    _retype(inputs, 240, "whip", 8, "agree", direction=1)
    with pytest.raises(Refused, match="carry is pixel-continuous"):
        inputs.build()


def test_frames_are_zero_exactly_when_the_type_is_none(inputs: Inputs) -> None:
    inputs.row(240)["frames"] = 4
    with pytest.raises(Refused, match="frames must be 0"):
        inputs.build()


@pytest.mark.parametrize("change", [{"direction": 0}, {"frames": 7}])
def test_a_whip_needs_a_direction_and_an_even_frame_count(inputs: Inputs, change: dict) -> None:
    inputs.row(390).update(change)
    with pytest.raises(Refused, match="whip needs direction"):
        inputs.build()


def test_a_bloom_needs_an_even_frame_count(inputs: Inputs) -> None:
    inputs.row(90)["frames"] = 5
    with pytest.raises(Refused, match="bloom"):
        inputs.build()


def test_a_card_slide_needs_a_direction(inputs: Inputs) -> None:
    inputs.row(2190)["direction"] = 0
    with pytest.raises(Refused, match="card slide needs direction"):
        inputs.build()


def test_dip_white_has_a_fixed_nine_frame_schedule(inputs: Inputs) -> None:
    inputs.row(1010)["frames"] = 7
    with pytest.raises(Refused, match="9 frames"):
        inputs.build()


def test_an_iris_needs_its_fade_parameter(inputs: Inputs) -> None:
    del inputs.row(2160)["params"]["disc_fade_frames"]
    with pytest.raises(Refused, match="disc_fade_frames"):
        inputs.build()


def test_every_row_needs_a_written_motivation(inputs: Inputs) -> None:
    inputs.row(240)["motivation"] = "   "
    with pytest.raises(Refused, match="motivation"):
        inputs.build()


def test_dip_white_never_shows_two_shots_in_one_frame() -> None:
    schedule = transitions.DIP_WHITE_SCHEDULE
    assert all(not (e["shot"] in ("out", "out_tail") and e["shot"] == "in") for e in schedule)
    visible = [{"out": "A", "out_tail": "A", "in": "B", "none": None}[e["shot"]] for e in schedule]
    assert len(visible) == len(schedule)  # exactly one source (or none) per frame by construction
    assert [e["t"] for e in schedule if e["white"] == 1.0 and e["shot"] == "none"] == [3]
    transitions.audit_dip_schedule()


# ---- coverage, positions, classes ----------------------------------------------------------------
def test_every_shot_pair_needs_a_row(inputs: Inputs) -> None:
    inputs.boundaries["boundaries"].remove(inputs.row(1150))
    with pytest.raises(Refused, match="does not cover every cut/carry: missing S04_A -> S04_B"):
        inputs.build()


def test_the_boundary_frame_must_be_where_the_incoming_shot_starts(inputs: Inputs) -> None:
    inputs.row(390)["frame"] = 392
    with pytest.raises(Refused, match="starts at f390"):
        inputs.build()


def test_the_class_may_not_contradict_shots_json(inputs: Inputs) -> None:
    row = inputs.row(240)  # shots.json: S01_B enters as a carry
    row.update({"class": "cut", "type": "whip", "frames": 8, "direction": 1})
    with pytest.raises(Refused, match="contradicts shots.json entry kind"):
        inputs.build()


def test_unknown_names_and_non_adjacent_pairs_are_refused(inputs: Inputs) -> None:
    inputs.row(240)["to_shot"] = "S99_Z"
    with pytest.raises(Refused, match="unknown name 'S99_Z'"):
        inputs.build()
    inputs2 = Inputs(inputs.tmp)
    row = inputs2.row(550)
    row["from_shot"] = "S01_A"
    with pytest.raises(Refused, match="not an adjacency"):
        inputs2.build()


def test_a_boundary_declared_twice_is_refused(inputs: Inputs) -> None:
    inputs.boundaries["boundaries"].append(copy.deepcopy(inputs.row(240)))
    with pytest.raises(Refused, match="declared twice"):
        inputs.build()


def test_boundaries_json_is_schema_checked(inputs: Inputs) -> None:
    inputs.row(240)["type"] = "sparkle"
    with pytest.raises(Refused, match="boundaries.json is invalid"):
        inputs.build()
    inputs2 = Inputs(inputs.tmp)
    inputs2.boundaries["episode_id"] = "other"
    with pytest.raises(Refused, match="episode_id"):
        inputs2.build()



# ---- M1: shows_both is explicit; graphics vs picture shots --------------------------------------------
def test_every_type_has_an_explicit_shows_both_property() -> None:
    assert set(transitions.TYPE_PROPERTIES) == set(transitions.TYPES)
    # T-E42: TYPE_PROPERTIES is derived from the preset catalog, so the shows_both set is the catalog's:
    # the six original names are still in it, now alongside the new presets
    both = {k for k, v in transitions.TYPE_PROPERTIES.items() if v["shows_both"]}
    assert {"dissolve", "cloud", "bubble", "wipe", "card_slide", "plate_in"} <= both
    assert both == transitions.BOTH_SHOTS_TYPES
    assert not any(transitions.TYPE_PROPERTIES[k]["shows_both"]
                   for k in ("none", "whip", "dip_white", "iris", "bloom", "cut", "cut_push"))


def test_the_transition_record_carries_shows_both(inputs: Inputs) -> None:
    by_type = {t["type"]: t for t in inputs.build().events["transitions"]}
    assert by_type["card_slide"]["shows_both"] is True and by_type["plate_in"]["shows_both"] is True
    assert all(by_type[k]["shows_both"] is False for k in ("whip", "dip_white", "iris", "bloom", "none"))


@pytest.mark.parametrize("kind", ["card_slide", "plate_in"])
@pytest.mark.parametrize("continuity", ["mismatch", "unknown"])
def test_card_slide_and_plate_in_between_picture_shots_are_refused(inputs: Inputs, kind: str, continuity: str) -> None:
    _retype(inputs, 390, kind, 6, continuity, direction=-1)
    with pytest.raises(Refused, match="both sides in one frame"):
        inputs.build()


@pytest.mark.parametrize("kind", ["card_slide", "plate_in"])
def test_card_slide_and_plate_in_between_picture_shots_are_graphic_only_even_when_they_agree(
        inputs: Inputs, kind: str) -> None:
    # T-E42: the catalog marks them safe_for graphic only, so agree no longer lets them between two pictures
    _retype(inputs, 390, kind, 6, "agree", direction=-1)
    with pytest.raises(Refused, match="graphic boundaries only"):
        inputs.build()


@pytest.mark.parametrize("continuity", ["mismatch", "unknown", "agree"])
def test_card_slide_between_two_graphics_is_allowed_whatever_the_continuity(inputs: Inputs, continuity: str) -> None:
    inputs.row(2190)["continuity"] = continuity
    assert inputs.build()


def test_card_slide_between_a_graphic_and_a_picture_shot_is_refused(inputs: Inputs) -> None:
    _retype(inputs, 90, "card_slide", 6, "unknown", direction=-1)  # INTRO -> S01_A
    with pytest.raises(Refused, match="both sides in one frame"):
        inputs.build()


