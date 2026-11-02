"""Audio binding, silence, scope and the ending: real ep04 inputs, mutated once each."""

from __future__ import annotations

import copy

import pytest

from editorial_fixtures import Inputs, fake_probe
from engine.core.errors import Refused, Uncertain
from engine.editorial import end_card


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- end card, label, cards -----------------------------------------------------------------------------
def test_end_logo_frames_come_from_the_engine_timeline(inputs: Inputs) -> None:
    config = inputs.build().config
    assert config["end_hold_frames"] == 60 and config["main_frames"] == 2520 and config["total_frames"] == 2580
    assert config["motion"]["ending"]["end_logo"]["from_frame"] == 2520
    assert config["motion"]["ending"]["end_logo"]["total_frames"] == 2580


def test_end_logo_may_not_declare_its_own_length(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["end_logo"]["frames"] = 45
    with pytest.raises(Refused, match="come from timeline.end_card_frames"):
        inputs.build()


def test_an_end_logo_without_an_end_card_in_the_timeline_is_refused(inputs: Inputs) -> None:
    inputs.timeline_change(end_card_s=0, end_card_frames=0)
    with pytest.raises(Refused):
        inputs.build()


def test_the_end_card_length_follows_a_shorter_timeline_end_card(inputs: Inputs) -> None:
    inputs.timeline_change(end_card_s=1.0, end_card_frames=30)
    inputs.boundaries["boundaries"] = [r for r in inputs.boundaries["boundaries"] if r["frame"] != 2520]
    config = inputs.build().config
    assert config["end_hold_frames"] == 30 and config["motion"]["ending"]["end_logo"]["total_frames"] == 2550


def test_the_end_plate_must_start_after_the_measured_end_of_the_last_word(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["end_plate"]["start"] = 2517
    inputs.row(2516)["frame"] = 2517
    with pytest.raises(Refused, match="plate must start at f2516"):
        inputs.build()


def test_the_measured_plate_start_is_recorded(inputs: Inputs) -> None:
    plate = inputs.build().config["motion"]["ending"]["end_plate"]
    assert plate["start"] == 2516 and plate["speech_end_frame"] == 2515.3 and plate["speech_end_s"] == 1.01


def test_speech_end_of_a_silent_wav_is_uncertain(tmp_path) -> None:
    import wave
    path = tmp_path / "s.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\x00\x00" * 8000)
    from engine.core.errors import Uncertain
    with pytest.raises(Uncertain):
        end_card.speech_end_seconds(path)


def test_the_label_comes_from_the_domain_review_block(inputs: Inputs) -> None:
    assert inputs.build().config["label"] == inputs.config.domain["delivery"]["review"]["label"]
    domain = copy.deepcopy(inputs.config.domain)
    domain["delivery"]["review"]["label"] = "OTHER LABEL"
    assert inputs.with_config(domain=domain).build().config["label"] == "OTHER LABEL"
    del domain["delivery"]["review"]["label"]
    with pytest.raises(Refused, match="no delivery.review.label"):
        inputs.with_config(domain=domain).build()


def test_cards_must_tile_the_outro(inputs: Inputs) -> None:
    inputs.boundaries["cards"][3]["start_frame"] += 1
    with pytest.raises(Refused, match="cards tile the outro"):
        inputs.build()


def test_a_card_wav_with_a_different_hash_is_refused(inputs: Inputs) -> None:
    inputs.boundaries["cards"][0]["audio"]["sha256"] = "0" * 64
    with pytest.raises(Refused, match="WAV sha256 differs"):
        inputs.build()


def test_the_declared_logo_hash_is_checked(inputs: Inputs) -> None:
    inputs.boundaries["ending"]["logo"]["sha256"] = "0" * 64
    with pytest.raises(Refused, match="ending.logo"):
        inputs.build()



# ---- M2: silent WAVs -------------------------------------------------------------------------------------------
def test_the_real_silent_wav_is_declared_and_carried_into_the_binding(inputs: Inputs) -> None:
    bindings = {b["name"]: b for b in inputs.build().config["wav_bindings"]}
    assert bindings["dlg S06_B3"]["expect_silent"] == {"start_frame": 2110, "end_frame_exclusive": 2160,
                                                       "max_rms": 0.04}
    assert all("expect_silent" not in b for n, b in bindings.items() if n != "dlg S06_B3")


def test_a_silent_wav_without_a_declared_window_is_refused(inputs: Inputs) -> None:
    inputs.boundaries["expect_silent"] = []
    with pytest.raises(Refused, match="silent but no expect_silent window"):
        inputs.build()


def test_the_declared_silent_window_must_be_the_shots_window(inputs: Inputs) -> None:
    inputs.boundaries["expect_silent"][0]["start_frame"] = 2111
    with pytest.raises(Refused, match="is not the shot's window"):
        inputs.build()


def test_expect_silent_on_an_audible_wav_is_refused(inputs: Inputs) -> None:
    inputs.boundaries["expect_silent"].append({"shot": "S06_B2", "start_frame": 1935, "end_frame_exclusive": 2110,
                                               "max_rms": 0.04})
    with pytest.raises(Refused, match="carries signal"):
        inputs.build()


def test_expect_silent_for_a_shot_that_does_not_exist_is_refused(inputs: Inputs) -> None:
    inputs.boundaries["expect_silent"].append({"shot": "S99_Z", "start_frame": 0, "end_frame_exclusive": 5,
                                               "max_rms": 0.04})
    with pytest.raises(Refused, match="not in the timeline"):
        inputs.build()


def test_a_silent_wav_with_words_timed_inside_its_window_is_refused(inputs: Inputs) -> None:
    words = inputs.entry("S06_B")["words"]
    words[-1].update({"start_frame": 2120, "end_frame_exclusive": 2130})
    with pytest.raises(Refused, match="inside its window"):
        inputs.build()


def test_an_audible_wav_with_no_word_in_its_window_is_refused(inputs: Inputs) -> None:
    entry = inputs.entry("S06_B")
    entry["words"] = [w for w in entry["words"] if w["start_frame"] >= 1935]  # nothing timed in S06_B1
    entry["speech_text"] = " ".join(w["raw_text"] for w in entry["words"])
    with pytest.raises(Refused, match="audible but the word timing has no word"):
        inputs.build()


# ---- M4: multi-segment dialogue --------------------------------------------------------------------------------
def test_the_multi_segment_timing_wav_must_be_the_concatenation_of_the_bound_segments(inputs: Inputs) -> None:
    assert inputs.build().config["dialogue"][-1]["timing_audio"]["sha256"] == inputs.entry("S06_B")["audio"]["sha256"]
    inputs.entry("S06_B")["audio"]["sha256"] = "0" * 64
    with pytest.raises(Refused, match="does not hash to its declared sha256"):
        inputs.build()


def test_a_timing_wav_that_is_not_the_concatenation_is_refused(inputs: Inputs) -> None:
    import hashlib
    from editorial_fixtures import REAL_ROOT
    entry = inputs.entry("S06_B")
    entry["audio"]["path"] = "audio/dialogue-trim-v002/dialogue-S06_B-trim-v002-48k.wav"  # a different WAV
    entry["audio"]["sha256"] = hashlib.sha256((REAL_ROOT / entry["audio"]["path"]).read_bytes()).hexdigest()
    with pytest.raises(Refused, match="not the concatenation of its bound segment WAVs"):
        inputs.build()


def test_a_multi_segment_dialogue_needs_its_timing_audio_declared(inputs: Inputs) -> None:
    del inputs.entry("S06_B")["audio"]
    with pytest.raises(Refused, match="needs audio.path and audio.sha256"):
        inputs.build()


# ---- M5 / L2: exit classes and scope ----------------------------------------------------------------------------
def test_a_missing_wav_is_an_unreadable_input(inputs: Inputs) -> None:
    inputs.boundaries["cards"][0]["audio"]["path"] = "audio/nope.wav"
    with pytest.raises(Uncertain, match="not found"):
        inputs.build()


def test_the_logo_outside_the_episode_root_needs_the_allow_list(inputs: Inputs) -> None:
    import json
    from engine.editorial import build
    boundaries = inputs.tmp / "b.json"
    timing = inputs.tmp / "t.json"
    boundaries.write_text(json.dumps(inputs.boundaries), encoding="utf-8")
    timing.write_text(json.dumps(inputs.timing), encoding="utf-8")
    with pytest.raises(Refused, match="outside the episode root and not allow-listed"):
        build.build_review_config(inputs.config, boundaries, timing, probe=fake_probe)


@pytest.mark.parametrize("path", ["../../../../../../Windows/win.ini", "../outside.mp4"])
def test_a_tail_clip_cannot_escape_the_episode_root(inputs: Inputs, path: str) -> None:
    inputs.row(1010)["tail_clip"] = path
    with pytest.raises(Refused, match="outside the episode root"):
        inputs.build()


def test_the_icons_dir_and_card_wavs_cannot_escape_the_root(inputs: Inputs) -> None:
    inputs.boundaries["icons"]["dir"] = "../../studio-app"
    with pytest.raises(Refused, match="outside the episode root"):
        inputs.build()
    inputs2 = Inputs(inputs.tmp)
    inputs2.boundaries["cards"][0]["audio"]["path"] = "../../engine/machine.json"
    with pytest.raises(Refused, match="outside the episode root"):
        inputs2.build()


def test_the_config_echoes_no_absolute_path(inputs: Inputs) -> None:
    import json
    config = inputs.build().config
    text = json.dumps(config)
    assert "D:\\\\" not in text and "C:\\\\" not in text and "D:/" not in text and "C:/" not in text
    assert config["word_timing"]["path"] == "word-timing.json"  # outside the root: file name only


