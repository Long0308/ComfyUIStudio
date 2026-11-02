"""T-E42: the ending as parameters + the derived editorial timeline (ending.derive_timeline).

Real ep04 inputs mutated in tmp.  Without ``derive_timeline`` nothing changes (the parity tests prove it);
with it the card lengths come from the card WAVs, ``logo_hold_frames`` is the still logo hold between the
dialogue end and card 1, the end plate follows the last card window (or the measured speech end), the end
card (EndLogo) length is ``end_card_frames`` and the logo disc layout follows the outro start.
"""

from __future__ import annotations

import json
import math
import wave
import pytest

from editorial_fixtures import REAL_ROOT, Inputs
from engine.core.errors import Refused
from engine.editorial import end_card

FPS = 30
DIALOGUE_END = 2160   # intro 3 s + dialogue 69 s at 30 fps on ep04
HOLD = 60             # default logo hold: card 1 starts at DIALOGUE_END + HOLD
OUTRO = DIALOGUE_END + HOLD
V013 = REAL_ROOT / "editorial" / "review-hd-v013" / "config" / "review-config-v013.json"


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


def _derive(inputs: Inputs, **ending) -> Inputs:
    """Switch the ep04 table to the derived timeline: no card frames, no plate start, no boundary frames
    and no iris/disc numbers that the timeline now decides."""
    doc = inputs.boundaries
    doc["ending"].update({"derive_timeline": True, **ending})
    del doc["ending"]["end_plate"]["start"]
    del doc["ending"]["logo_disc"]["fade_start"]
    for card in doc["cards"]:
        del card["start_frame"], card["duration_frames"]
    for row in doc["boundaries"]:
        if row["to_shot"].startswith("CARD_") or row["to_shot"] in ("END_PLATE", "ENDLOGO"):
            del row["frame"]
        if row["type"] == "iris":
            del row["params"]["disc_fade_start_f"]
    return inputs


def _wav_seconds(card: dict) -> float:
    with wave.open(str(REAL_ROOT / card["audio"]["path"])) as stream:
        return stream.getnframes() / stream.getframerate()


def _iris(built) -> dict:
    return next(t for t in built.events["transitions"] if t["type"] == "iris")


# ---- derived timeline arithmetic -------------------------------------------------------------------
def test_card_lengths_are_the_longer_of_the_minimum_and_the_wav(inputs: Inputs) -> None:
    built = _derive(inputs).build()
    cards = built.config["outro_cards"]
    assert len(cards) == 12
    expected = [max(90, math.ceil(_wav_seconds(c) * FPS)) for c in inputs.boundaries["cards"]]
    assert [c["duration_frames"] for c in cards] == expected == [90] * 12   # every ep04 card WAV is under 3 s
    assert [c["start_frame"] for c in cards] == [OUTRO + 90 * i for i in range(12)]


def test_logo_hold_is_the_still_logo_between_the_dialogue_end_and_card_one(inputs: Inputs) -> None:
    default = _derive(inputs).build().config["outro_cards"][0]["start_frame"]
    assert default == DIALOGUE_END + 60
    held = _derive(Inputs(inputs.tmp), logo_hold_frames=70).build()
    assert held.config["outro_cards"][0]["start_frame"] == 2230 == DIALOGUE_END + 70
    assert held.events["ending"]["derived_timeline"]["outro_start_frame"] == 2230


def test_main_film_and_end_card_are_derived_not_squeezed(inputs: Inputs) -> None:
    built = _derive(inputs).build()
    config = built.config
    cards_end = OUTRO + 12 * 90
    assert config["main_frames"] == cards_end + 4 == 3304      # the plate follows the last card window
    assert config["end_hold_frames"] == 60 and config["total_frames"] == 3364
    assert config["qa"]["av"]["reference_seconds"] == 3304 / FPS
    logo = built.events["ending"]["end_logo"]
    assert (logo["frames"], logo["from_frame"], logo["total_frames"]) == (60, 3304, 3364)
    assert built.events["transitions"][-1]["boundary"] == 3304      # END_PLATE -> ENDLOGO


def test_the_hand_built_v013_numbers_come_from_parameters_alone(inputs: Inputs) -> None:
    built = _derive(inputs, logo_hold_frames=70, card_min_frames=90).build()
    config = built.config
    assert [c["start_frame"] for c in config["outro_cards"]] == [2230 + 90 * i for i in range(12)]
    assert built.events["ending"]["end_plate"]["start"] == 3310
    assert (config["main_frames"], config["end_hold_frames"], config["total_frames"]) == (3314, 60, 3374)
    assert next(t for t in built.events["transitions"] if t["to"] == "END_PLATE")["boundary"] == 3310


@pytest.mark.skipif(not V013.is_file(), reason="the hand-built v013 config is not on this machine")
def test_the_derived_numbers_equal_the_hand_built_v013_config(inputs: Inputs) -> None:
    old = json.loads(V013.read_text("utf-8"))
    built = _derive(inputs, logo_hold_frames=70).build()
    assert [c["start_frame"] for c in built.config["outro_cards"]] == [c["start_frame"] for c in old["outro_cards"]]
    assert built.config["main_frames"] == old["main_frames"]
    assert built.events["ending"]["end_plate"]["start"] == old["motion"]["ending"]["end_plate"]["start"]


def test_a_larger_card_minimum_is_used(inputs: Inputs) -> None:
    built = _derive(inputs, card_min_frames=100).build()
    assert [c["duration_frames"] for c in built.config["outro_cards"]] == [100] * 12
    assert built.config["main_frames"] == OUTRO + 1200 + 4


def test_end_card_frames_default_to_the_episode_and_can_be_declared(inputs: Inputs) -> None:
    assert _derive(inputs).build().config["end_hold_frames"] == 60
    built = _derive(Inputs(inputs.tmp), end_card_frames=75).build()
    assert built.config["end_hold_frames"] == 75
    assert built.config["total_frames"] == built.config["main_frames"] + 75
    assert built.events["ending"]["end_logo"]["frames"] == 75


def test_the_card_duration_rule_on_a_long_wav() -> None:
    from engine.editorial import derive
    assert derive.card_duration(samples=48000 * 4, rate=48000, fps=30, card_min=90) == 120     # 4 s > 3 s minimum
    assert derive.card_duration(samples=48000 * 1, rate=48000, fps=30, card_min=90) == 90
    assert derive.card_duration(samples=48000 * 3, rate=48000, fps=30, card_min=90) == 90      # exactly the minimum
    assert derive.card_duration(samples=48000 * 3 + 1, rate=48000, fps=30, card_min=90) == 91  # ceil, never round down


def test_every_boundary_into_a_card_or_the_ending_lands_on_the_derived_start(inputs: Inputs) -> None:
    built = _derive(inputs).build()
    starts = {t["to"]: t["boundary"] for t in built.events["transitions"]}
    assert starts["CARD_Smooth"] == OUTRO + 90 and starts["CARD_Ice Cream"] == OUTRO + 11 * 90
    assert starts["END_PLATE"] == OUTRO + 12 * 90 and starts["ENDLOGO"] == OUTRO + 12 * 90 + 4


def test_a_declared_boundary_frame_that_disagrees_with_the_derived_timeline_is_refused(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.row_by_to = next(r for r in inputs.boundaries["boundaries"] if r["to_shot"] == "CARD_Smooth")
    inputs.row_by_to["frame"] = 2190   # the old 30-frame card start
    with pytest.raises(Refused, match=f"starts at f{OUTRO + 90}"):
        inputs.build()


def test_a_declared_card_start_that_disagrees_with_the_derived_one_is_refused(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["cards"][1].update({"start_frame": 2190, "duration_frames": 30})
    with pytest.raises(Refused, match="Smooth.*derived"):
        inputs.build()


# ---- end plate ---------------------------------------------------------------------------------------
def test_the_plate_follows_the_last_card_window_by_default(inputs: Inputs) -> None:
    built = _derive(inputs).build()
    plate = built.events["ending"]["end_plate"]
    assert plate["start"] == OUTRO + 12 * 90 and plate["placement"] == "card_end"
    assert plate["speech_end_frame"] < plate["start"]      # the word is over before the plate appears
    assert next(t for t in built.events["transitions"] if t["to"] == "END_PLATE")["boundary"] == plate["start"]


def test_frames_after_the_card_window_are_a_parameter(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["ending"]["end_plate"]["frames_after_card_window"] = 6
    built = inputs.build()
    assert built.config["main_frames"] == OUTRO + 1080 + 6
    assert built.events["ending"]["end_plate"]["frames_after_card_window"] == 6


def test_the_plate_can_still_be_placed_at_the_measured_speech_end(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["ending"]["end_plate"]["placement"] = "speech_end"
    built = inputs.build()
    last_start = OUTRO + 11 * 90
    wav = REAL_ROOT / inputs.boundaries["cards"][-1]["audio"]["path"]
    expected = math.ceil(last_start + end_card.speech_end_seconds(wav) * FPS)
    plate = built.events["ending"]["end_plate"]
    assert plate["start"] == expected and expected > last_start
    assert built.config["main_frames"] == OUTRO + 1080          # the plate sits inside card 12
    assert next(t for t in built.events["transitions"] if t["to"] == "END_PLATE")["boundary"] == expected


def test_a_declared_plate_start_is_still_checked_against_the_placement(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["ending"]["end_plate"]["start"] = OUTRO + 11 * 90 + 1
    with pytest.raises(Refused, match=f"plate must start at f{OUTRO + 12 * 90}"):
        inputs.build()
    other = _derive(Inputs(inputs.tmp))
    other.boundaries["ending"]["end_plate"].update({"placement": "speech_end", "start": OUTRO + 11 * 90 + 1})
    with pytest.raises(Refused, match="plate must start at"):
        other.build()


def test_a_declared_plate_start_equal_to_the_derived_one_is_accepted(inputs: Inputs) -> None:
    derived = _derive(inputs).build().events["ending"]["end_plate"]["start"]
    inputs.boundaries["ending"]["end_plate"]["start"] = derived
    assert inputs.build().events["ending"]["end_plate"]["start"] == derived


def test_a_card_that_ends_before_its_word_does_is_refused_for_card_end(inputs: Inputs) -> None:
    wav = REAL_ROOT / inputs.boundaries["cards"][-1]["audio"]["path"]
    with pytest.raises(Refused, match="plate must start at"):
        end_card.check_end_plate(2001, 2000, wav, FPS, placement="card_end", last_card_end=2001)


# ---- logo disc layout and the iris row follow the outro start -----------------------------------------------
def test_the_logo_disc_layout_follows_the_outro_start(inputs: Inputs) -> None:
    _derive(inputs, logo_hold_frames=70)
    inputs.boundaries["ending"]["logo_disc_layout"] = {"slide_x": 520, "pill_left_x": 988}
    built = inputs.build()
    assert built.events["ending"]["logo_disc_layout"] == {"slide_x": 520, "pill_left_x": 988,
                                                          "slide_start": 2222, "slide_end": 2229}
    assert built.events["ending"]["logo_disc"]["fade_start"] == 2230
    disc = built.events["ending"]["derived_timeline"]["logo_disc"]
    assert (disc["slide_start"], disc["slide_end"], disc["fade_start"], disc["still_last_f"]) == (2222, 2229, 2230, 2221)


def test_a_declared_disc_layout_wins_but_must_stay_in_order(inputs: Inputs) -> None:
    _derive(inputs, logo_hold_frames=70)
    inputs.boundaries["ending"]["logo_disc_layout"] = {"slide_start": 2200, "slide_end": 2210, "slide_x": 520}
    assert inputs.build().events["ending"]["logo_disc_layout"]["slide_start"] == 2200
    inputs.boundaries["ending"]["logo_disc_layout"] = {"slide_start": 2210, "slide_end": 2200}
    with pytest.raises(Refused, match="slide_start .* slide_end"):
        inputs.build()
    inputs.boundaries["ending"]["logo_disc_layout"] = {"slide_start": 2200, "slide_end": 2231}
    with pytest.raises(Refused, match="slide_end .* fade_start"):
        inputs.build()


def test_the_iris_row_window_reaches_the_end_of_the_logo_disc_shrink(inputs: Inputs) -> None:
    built = _derive(inputs, logo_hold_frames=70).build()
    iris = _iris(built)
    assert iris["boundary"] == DIALOGUE_END and iris["frames"] == 44
    assert (iris["start"], iris["end_exclusive"]) == (2116, 2236)      # v013: iris f2116 .. shrink end f2235
    assert iris["hold_frames"] == 70 and iris["disc_fade_start_f"] == 2230 and iris["disc_fade_frames"] == 6
    assert iris["iris_close_f"] == 2140 and iris["logo_in_f"] == 2142


def test_a_declared_disc_fade_start_that_disagrees_with_the_outro_is_refused(inputs: Inputs) -> None:
    _derive(inputs, logo_hold_frames=70)
    next(r for r in inputs.boundaries["boundaries"] if r["type"] == "iris")["params"]["disc_fade_start_f"] = 2160
    with pytest.raises(Refused, match="disc_fade_start_f.*2230"):
        inputs.build()
    other = _derive(Inputs(inputs.tmp), logo_hold_frames=70)
    other.boundaries["ending"]["logo_disc"]["fade_start"] = 2160
    with pytest.raises(Refused, match="fade_start.*2230"):
        other.build()


def test_the_iris_window_without_a_hold_is_the_old_one(inputs: Inputs) -> None:
    iris = _iris(inputs.build())
    assert (iris["start"], iris["end_exclusive"]) == (2116, 2166) and "hold_frames" not in iris


# ---- warnings: the master contract is not touched --------------------------------------------------------
def test_a_derived_timeline_longer_than_the_domain_master_warns(inputs: Inputs) -> None:
    built = _derive(inputs).build()
    over = [w for w in built.warnings if "derived main film" in w]
    assert len(over) == 1 and "3304" in over[0] and "2520" in over[0] and "exceeds" in over[0]
    assert any("derived total" in w and "3364" in w and "2580" in w for w in built.warnings)


def test_an_end_card_beyond_the_domain_allowance_warns(inputs: Inputs) -> None:
    built = _derive(inputs, end_card_frames=75).build()
    assert any("end card" in w and "75" in w and "frames_max 60" in w for w in built.warnings)
    assert not any("frames_max" in w for w in _derive(Inputs(inputs.tmp)).build().warnings)
    assert not any("frames_max" in w for w in _derive(Inputs(inputs.tmp), logo_hold_frames=75).build().warnings)


def test_the_derived_timeline_is_recorded_in_the_ending(inputs: Inputs) -> None:
    built = _derive(inputs, logo_hold_frames=70).build()
    summary = built.events["ending"]["derived_timeline"]
    assert summary["main_frames"] == 3314 and summary["end_card_frames"] == 60 and summary["total_frames"] == 3374
    assert summary["card_min_frames"] == 90 and summary["logo_hold_frames"] == 70
    assert summary["dialogue_end_frame"] == 2160 and summary["outro_start_frame"] == 2230
    assert summary["cards_end_frame"] == 3310 and summary["plate_placement"] == "card_end"
    assert summary["plate_start"] == 3310 and summary["plate_frames_after_card_window"] == 4
    assert [c["term"] for c in summary["cards"]][:2] == ["Creamy", "Smooth"]
    assert built.config["motion"]["ending"] == built.events["ending"]


def test_without_derive_timeline_nothing_changes(inputs: Inputs) -> None:
    built = inputs.build()
    assert built.config["main_frames"] == 2520 and "derived_timeline" not in built.events["ending"]
    assert not any("derived" in w for w in built.warnings)
    inputs.boundaries["ending"]["derive_timeline"] = False
    inputs.boundaries["ending"]["card_min_frames"] = 120     # declared but not in force
    assert inputs.build().config["main_frames"] == 2520


def test_the_derive_timeline_flag_off_needs_the_card_frames_and_plate_start(inputs: Inputs) -> None:
    del inputs.boundaries["cards"][0]["start_frame"]
    with pytest.raises(Refused, match="card 'Creamy' needs start_frame and duration_frames"):
        inputs.build()
    inputs2 = Inputs(inputs.tmp)
    del inputs2.boundaries["ending"]["end_plate"]["start"]
    with pytest.raises(Refused, match="end_plate.start is required"):
        inputs2.build()


def test_derive_timeline_needs_cards(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["cards"] = []
    with pytest.raises(Refused, match="derive_timeline needs cards"):
        inputs.build()


# ---- parameter validation ---------------------------------------------------------------------------------
@pytest.mark.parametrize("change", [{"logo_hold_frames": 59}, {"card_min_frames": 89}, {"card_min_frames": 90.5},
                                    {"logo_hold_frames": "60"}, {"derive_timeline": "yes"},
                                    {"derive_timeline": 1}, {"end_card_frames": 59}, {"end_card_frames": "60"}])
def test_the_ending_numbers_are_validated(inputs: Inputs, change: dict) -> None:
    inputs.boundaries["ending"].update(change)
    # below-floor values are now refused by the DOMAIN floor (end_card.check_params), not by a schema literal (M8b c)
    with pytest.raises(Refused, match="boundaries.json is invalid|must be an integer >= "):
        inputs.build()


@pytest.mark.parametrize("change", [{"placement": "middle"}, {"frames_after_card_window": 0},
                                    {"frames_after_card_window": 2.5}])
def test_the_plate_parameters_are_validated(inputs: Inputs, change: dict) -> None:
    inputs.boundaries["ending"]["end_plate"].update(change)
    with pytest.raises(Refused, match="boundaries.json is invalid|end_plate"):
        inputs.build()


# ---- music bed policy ----------------------------------------------------------------------------------------
BED = {"extend": "loop_phrase_crossfade", "loop_start_s": 12.5, "loop_end_s": 20.0, "crossfade_frames": 12,
       "duck_db": 9.0, "duck_attack_frames": 3, "duck_release_frames": 9, "duck_under": "words"}


def test_a_valid_music_bed_is_passed_through_to_events_and_config(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["music_bed"] = dict(BED)
    built = inputs.build()
    assert built.events["ending"]["music_bed"] == BED
    assert built.config["motion"]["ending"]["music_bed"] == BED


def test_a_music_bed_that_does_not_extend_needs_no_loop(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["music_bed"] = {"extend": "none", "duck_db": 6, "duck_attack_frames": 2,
                                                "duck_release_frames": 6, "duck_under": "words"}
    assert inputs.build().events["ending"]["music_bed"]["extend"] == "none"


@pytest.mark.parametrize("change,message", [
    ({"extend": "bounce"}, "extend"),
    ({"duck_db": 0}, "duck_db"),
    ({"duck_db": -3}, "duck_db"),
    ({"duck_under": "music"}, "duck_under"),
    ({"crossfade_frames": -1}, "crossfade_frames"),
    ({"duck_attack_frames": 1.5}, "duck_attack_frames"),
    ({"loop_start_s": -1}, "loop_start_s"),
    ({"surprise": 1}, "surprise"),
])
def test_a_bad_music_bed_is_refused(inputs: Inputs, change: dict, message: str) -> None:
    inputs.boundaries["ending"]["music_bed"] = {**BED, **change}
    with pytest.raises(Refused, match=message):
        inputs.build()


def test_a_loop_must_end_after_it_starts_and_a_looping_bed_needs_both_ends(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["music_bed"] = {**BED, "loop_start_s": 20.0, "loop_end_s": 20.0}
    with pytest.raises(Refused, match="loop_end_s must be greater than loop_start_s"):
        inputs.build()
    bed = {k: v for k, v in BED.items() if k != "loop_end_s"}
    inputs.boundaries["ending"]["music_bed"] = bed
    with pytest.raises(Refused, match="loop_phrase_crossfade needs loop_start_s and loop_end_s"):
        inputs.build()


# ---- logo disc layout numbers ----------------------------------------------------------------------------------
def test_the_logo_disc_layout_is_passed_through_as_data(inputs: Inputs) -> None:
    layout = {"slide_start": 2152, "slide_end": 2159, "slide_x": 520, "pill_left_x": 380.5, "disc_in": 2142}
    inputs.boundaries["ending"]["logo_disc_layout"] = layout
    built = inputs.build()
    assert built.events["ending"]["logo_disc_layout"] == layout
    assert built.config["motion"]["ending"]["logo_disc_layout"] == layout


def test_the_logo_disc_layout_takes_numbers_only(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["logo_disc_layout"] = {"slide_x": "left"}
    with pytest.raises(Refused, match="boundaries.json is invalid"):
        inputs.build()


def test_end_logo_frames_are_still_not_declarable(inputs: Inputs) -> None:
    _derive(inputs)
    inputs.boundaries["ending"]["end_logo"]["frames"] = 90
    with pytest.raises(Refused, match="may not declare"):
        inputs.build()
