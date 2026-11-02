"""Captions (G-CAP) and icons (G-ICON): real ep04 word timing, mutated once each."""

from __future__ import annotations

import copy

import pytest

from editorial_fixtures import Inputs
from engine.core.errors import Refused, Uncertain
from engine.editorial import captions


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- captions (G-CAP) -------------------------------------------------------------------------------
def test_captions_require_timing_for_every_dialogue_entry(inputs: Inputs) -> None:
    inputs.timing["entries"] = [e for e in inputs.timing["entries"] if e["id"] != "S03_A"]
    with pytest.raises(Refused, match="no word timing entry for dialogue 'S03_A'"):
        inputs.build()


def test_an_entry_without_words_is_refused(inputs: Inputs) -> None:
    inputs.entry("S02_B")["words"] = []
    with pytest.raises(Refused, match="G-CAP: no word timing for S02_B"):
        inputs.build()


def test_words_must_spell_the_script(inputs: Inputs) -> None:
    inputs.entry("S01_A")["words"][1]["raw_text"] = "see!"
    with pytest.raises(Refused, match="words != speech_text"):
        inputs.build()


def test_a_word_outside_its_window_is_refused(inputs: Inputs) -> None:
    entry = inputs.entry("S01_A")
    entry["words"][-1]["start_frame"] = entry["end_frame_exclusive"] + 5
    entry["words"][-1]["end_frame_exclusive"] = entry["end_frame_exclusive"] + 9
    with pytest.raises(Refused, match="outside its window"):
        inputs.build()


def test_non_monotonic_words_are_refused(inputs: Inputs) -> None:
    words = inputs.entry("S01_A")["words"]
    words[2]["start_frame"] = words[1]["start_frame"] - 3
    with pytest.raises(Refused, match="non-monotonic"):
        inputs.build()


def test_the_dialogue_windows_must_follow_the_episode_timeline(inputs: Inputs) -> None:
    inputs.entry("S01_B")["start_frame"] = 245
    with pytest.raises(Refused, match="timeline puts it at f240"):
        inputs.build()


def test_word_timing_measured_on_another_wav_is_refused(inputs: Inputs) -> None:
    inputs.entry("S01_A")["audio"]["sha256"] = "0" * 64
    with pytest.raises(Refused, match="word timing was measured on WAV"):
        inputs.build()


def test_word_timing_fps_must_match_the_domain(inputs: Inputs) -> None:
    inputs.timing["fps"] = 24
    with pytest.raises(Refused, match="word timing fps"):
        inputs.build()


# ---- icons (G-ICON) ------------------------------------------------------------------------------------
def test_a_term_without_an_anchor_word_fails_hard(inputs: Inputs) -> None:
    for entry in inputs.timing["entries"]:
        for word in entry["words"]:
            if word["vocab_icon"] == "yogurt.png":
                word["vocab_anchor"] = False
    with pytest.raises(Refused, match=r"declared terms without an icon event: \['yogurt.png'\]"):
        inputs.build()


def test_an_anchor_icon_outside_the_declared_terms_fails(inputs: Inputs) -> None:
    inputs.boundaries["icons"]["terms"] = [t for t in inputs.boundaries["icons"]["terms"] if t["icon"] != "bones.png"]
    inputs.timing["vocabulary_icons"] = [t for t in inputs.timing["vocabulary_icons"] if t["icon"] != "bones.png"]
    with pytest.raises(Refused, match="not in the declared term list"):
        inputs.build()


def test_the_timing_vocabulary_list_may_not_drift_from_the_declared_terms(inputs: Inputs) -> None:
    inputs.timing["vocabulary_icons"].pop()
    with pytest.raises(Refused, match="vocabulary_icons differ"):
        inputs.build()


def test_a_missing_icon_file_is_an_unreadable_input(inputs: Inputs) -> None:
    inputs.boundaries["icons"]["dir"] = "assets3d"
    with pytest.raises(Uncertain, match="icon missing on disk"):
        inputs.build()


def test_the_icon_pop_follows_the_declared_lead_and_the_word_start(inputs: Inputs) -> None:
    base = {e["id"]: e for e in inputs.build().config["motion"]["icons"]}
    inputs.boundaries["icons"]["lead_frames"] = 2
    lead = {e["id"]: e for e in inputs.build().config["motion"]["icons"]}
    assert all(lead[k]["frame"] == base[k]["frame"] + 2 for k in base)
    assert all(e["frame"] == e["word_start_frame"] for e in base.values())


def test_raw_whisper_start_wins_only_when_it_differs_by_more_than_0_3_s() -> None:
    entry = {"start_frame": 100}
    word = {"start_s": 1.0, "start_frame": 130, "raw_whisper_start_s": 1.25}
    assert captions.pop_frame(entry, word, 30) == (130, "start_frame")        # 0.25 s: calibrated start
    word["raw_whisper_start_s"] = 1.4                                          # 0.4 s: audible syllable
    assert captions.pop_frame(entry, word, 30) == (100 + 42, "raw_whisper_start_s")
    word["raw_whisper_start_s"] = None
    assert captions.pop_frame(entry, word, 30) == (130, "start_frame")



# ---- L3 / L4 / L5 -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["whole-line-fallback", "manual", "", "Whisper-small"])
def test_word_methods_other_than_whisper_or_estimated_are_refused(inputs: Inputs, method: str) -> None:
    for word in inputs.entry("S01_B")["words"]:
        word["method"] = method
    with pytest.raises(Refused, match="timing method"):
        inputs.build()


def test_estimated_words_are_accepted_but_marked_on_their_icon_events(inputs: Inputs) -> None:
    for word in inputs.entry("S01_B")["words"]:
        word["method"] = "estimated"
    built = inputs.build()
    events = [e for e in built.events["icon_events"] if e["shot"] == "S01_B"]
    assert events and all(e["estimated"] and e["word_method"] == "estimated" for e in events)
    assert any("ESTIMATED" in w for w in built.warnings)
    assert not any(e["estimated"] for e in built.events["icon_events"] if e["shot"] != "S01_B")


def test_a_word_end_beyond_the_window_is_refused(inputs: Inputs) -> None:
    entry = inputs.entry("S01_A")
    entry["words"][-1]["end_frame_exclusive"] = entry["end_frame_exclusive"] + 1
    with pytest.raises(Refused, match="outside its window"):
        inputs.build()


def test_pop_frame_adds_the_audio_offset_for_both_start_sources() -> None:
    entry = {"start_frame": 100, "audio": {"offset_frames": 2}}
    word = {"start_s": 1.0, "start_frame": 130, "raw_whisper_start_s": None}
    assert captions.pop_frame(entry, word, 30) == (132, "start_frame")
    word["raw_whisper_start_s"] = 1.5
    assert captions.pop_frame(entry, word, 30) == (100 + 45 + 2, "raw_whisper_start_s")
    assert captions.pop_frame({"start_frame": 100}, word, 30) == (145, "raw_whisper_start_s")


def test_the_icon_offset_flows_into_the_built_events(inputs: Inputs) -> None:
    base = {e["id"]: e["frame"] for e in inputs.build().events["icon_events"] if e["shot"] == "S01_B"}
    shots = copy.deepcopy(inputs.config.shots)  # shots.json is the source of truth for the offset (T-E28a r3)
    next(s for s in shots if s["shot"] == "S01_B")["wav_binding"]["offset_s"] = 2 / 30
    inputs.with_config(shots=shots)
    inputs.entry("S01_B")["audio"]["offset_frames"] = 2
    shifted = {e["id"]: e["frame"] for e in inputs.build().events["icon_events"] if e["shot"] == "S01_B"}
    assert shifted == {k: v + 2 for k, v in base.items()}
