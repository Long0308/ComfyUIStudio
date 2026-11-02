"""Onset rules on synthetic sounds: rule A, rule B, the 'liquid' stop closure, caps, shift limit, line-first rule."""

from __future__ import annotations

import pytest
from test_timing_support import ALL, FIRST, FPS, sound, word

from engine.core.errors import Refused, Uncertain
from engine.timing.firstword import calibrate_first_word, measure_line_onset, rms_runs
from engine.timing.onset import correct_word
from engine.timing.words import correct_entry, integrity_errors


def fix(snd, w, entry_start=0):
    return correct_word(snd, w, entry_start, ALL, FPS)


def test_rule_a_start_in_silence_moves_to_the_rising_edge_and_keeps_the_end() -> None:
    row = fix(sound(("sil", 0.5), ("tone", 0.8)), word(1, "Where", 0.1, 1.0))
    assert row["moved"] and row["rule"] == "rule A"
    assert abs(row["new_start_s"] - 0.50) <= 0.011 and row["new_start_frame"] == 15
    assert row["end_s"] == 1.0 and row["end_frame_exclusive"] == 30  # ends kept


def test_start_already_on_sound_without_a_pause_is_unchanged() -> None:
    row = fix(sound(("tone", 1.2)), word(1, "is", 0.2, 1.0))
    assert not row["moved"] and row["new_start_frame"] == row["old_start_frame"] == 6
    assert row["rule"].startswith("unchanged: start already on sound")


def test_rule_b_pause_inside_the_word_start_moves_to_the_edge_after_the_pause() -> None:
    # the lit start sits in the tail of the previous word: voiced 0-0.3 s, pause 0.15 s, the word at 0.45 s
    row = fix(sound(("tone", 0.3), ("sil", 0.15), ("tone", 0.8)), word(1, "look", 0.1, 1.2))
    assert row["moved"] and row["rule"] == "rule B"
    assert 0.45 <= row["new_start_s"] <= 0.47 and row["steps"][0]["pause_offset_in_word_s"] == 0.2


def test_stop_closure_inside_a_word_must_not_move_the_start() -> None:
    """'liquid': a 0.08 s closure at 0.25 s into the word is shorter than the 0.10 s the far window needs."""
    closure = sound(("tone", 0.35), ("sil", 0.08), ("tone", 0.8))
    assert not fix(closure, word(1, "liquid", 0.1, 1.2))["moved"]
    real_pause = sound(("tone", 0.35), ("sil", 0.12), ("tone", 0.8))  # same place, 0.12 s: a real gap
    assert fix(real_pause, word(1, "liquid", 0.1, 1.2))["moved"]


def test_pause_length_needed_depends_on_how_close_it_is_to_the_start() -> None:
    near_short = sound(("tone", 0.2), ("sil", 0.03), ("tone", 1.0))
    near_long = sound(("tone", 0.2), ("sil", 0.07), ("tone", 1.0))
    assert not fix(near_short, word(1, "a", 0.05, 1.1))["moved"]
    assert fix(near_long, word(1, "a", 0.05, 1.1))["moved"]
    beyond = sound(("tone", 0.6), ("sil", 0.3), ("tone", 0.8))  # pause starts 0.55 s after the start: outside the first 0.40 s
    assert not fix(beyond, word(1, "a", 0.05, 1.6))["moved"]


def test_shift_beyond_the_cap_is_refused_by_the_rule_not_applied() -> None:
    row = fix(sound(("tone", 0.2), ("sil", 0.8), ("tone", 0.6)), word(1, "x", 0.1, 1.6))
    assert not row["moved"] and row["new_start_frame"] == row["old_start_frame"]  # 0.9 s > max_shift_s 0.60


def test_start_is_capped_at_end_minus_two_frames_and_never_earlier_than_before() -> None:
    w = word(1, "x", 0.1, 0.55)
    w["end_frame_exclusive"] = 15  # a supplied end that rounds earlier than the onset (f14)
    row = fix(sound(("sil", 0.45), ("tone", 0.6)), w)
    assert row["new_start_frame"] == 13 and "capped at end-2f" in row["rule"] and row["new_start_frame"] >= row["old_start_frame"]


def test_a_start_is_never_moved_earlier_even_when_the_cap_is_below_the_old_frame() -> None:
    w = word(1, "x", 0.1, 0.9)
    w["end_frame_exclusive"] = 4  # a supplied end frame two frames after the start: cap f2 < old f3
    row = fix(sound(("sil", 0.5), ("tone", 0.6)), w)
    assert row["new_start_frame"] == row["old_start_frame"] == 3 and not row["moved"]


def test_a_short_click_in_silence_is_not_a_sustained_voiced_run() -> None:
    row = fix(sound(("sil", 0.3), ("tone", 0.03), ("sil", 0.47), ("tone", 0.7)), word(1, "x", 0.1, 1.5))
    assert row["moved"] and 0.79 <= row["new_start_s"] <= 0.81  # the 30 ms click at 0.3 s is skipped (needs 0.06 s)


def test_silence_start_with_only_soft_sound_finds_no_voiced_run_and_says_why() -> None:
    row = fix(sound(("sil", 0.4), ("soft", 0.8)), word(1, "x", 0.1, 1.0))
    assert not row["moved"] and "no sustained voiced run" in row["rule"]


def test_entry_start_frame_is_added_to_the_new_frame() -> None:
    row = fix(sound(("sil", 0.5), ("tone", 0.8)), word(1, "Where", 0.1, 1.0, entry_start=400), entry_start=400)
    assert row["new_start_frame"] == 415


# ---- line-first rule ------------------------------------------------------------------------------
def test_breath_burst_before_speech_is_skipped_for_the_first_word() -> None:
    snd = sound(("sil", 0.08), ("noise", 0.12), ("sil", 0.8), ("tone", 1.0))
    assert rms_runs(snd, FIRST)[0] == (0.08, 0.2)
    words, report = calibrate_first_word(snd, [word(1, "Good", 0.08, 0.9), word(2, "job", 0.9, 1.5)], 0, FIRST, FPS)
    assert report["moved"] and 0.99 <= words[0]["start_s"] <= 1.01 and words[0]["start_frame"] == 30
    assert report["decision_log"][0]["verdict"].startswith("isolated short burst")


def test_sustained_first_run_is_not_moved_and_short_run_in_a_cluster_counts() -> None:
    snd = sound(("sil", 0.3), ("tone", 1.0))
    _, report = calibrate_first_word(snd, [word(1, "Milk", 0.3, 1.0)], 0, FIRST, FPS)
    assert not report["moved"]
    cluster = sound(("sil", 0.2), ("tone", 0.1), ("sil", 0.3), ("tone", 1.4))  # short run, next one 0.3 s later
    assert measure_line_onset(cluster, FIRST)["onset_s"] == 0.2


def test_unvoiced_preroll_fused_with_speech_moves_to_the_first_voiced_window() -> None:
    snd = sound(("sil", 0.5), ("noise", 0.2), ("tone", 1.0))
    measured = measure_line_onset(snd, FIRST)
    assert measured["rms_onset_s"] == 0.5 and measured["step3_voiced_onset_applied"]
    assert 0.68 <= measured["onset_s"] <= 0.72


def test_a_line_with_words_but_no_speech_is_uncertain() -> None:
    with pytest.raises(Uncertain, match="no speech onset"):
        calibrate_first_word(sound(("sil", 1.0)), [word(1, "Hi", 0.1, 0.5)], 0, FIRST, FPS, label="S01")


def test_first_word_end_collapses_to_word_two_when_the_onset_passes_it() -> None:
    snd = sound(("sil", 1.0), ("tone", 1.0))
    words, report = calibrate_first_word(snd, [word(1, "It", 0.1, 0.4), word(2, "is", 0.4, 1.5)], 0, FIRST, FPS)
    assert report["end_collapsed_to_word2_start"] and words[0]["end_s"] == 0.4 and words[0]["start_s"] > 0.9


# ---- integrity contract of a whole entry ------------------------------------------------------------
def test_entry_integrity_rejects_non_monotonic_input_and_changed_fields() -> None:
    snd = sound(("tone", 1.5))
    backwards = [word(1, "a", 0.5, 0.9), word(2, "b", 0.2, 0.4)]
    with pytest.raises(Refused, match="non-monotonic at b"):
        correct_entry("S01", (0, 60), backwards, snd, {"all_words": ALL, "first_word": FIRST}, FPS, first_word=False)
    before, after = [word(1, "a", 0.2, 0.9)], [word(1, "a", 0.2, 0.9)]
    after[0].update(text="A", start_frame=1, end_frame_exclusive=1)
    errors = integrity_errors("S01", (0, 20), before, after, ("start_s", "start_frame"))
    assert any("field text changed" in e for e in errors) and any("moved earlier" in e for e in errors)
    assert any("start >= end" in e for e in errors)
    assert any("outside its window" in e for e in integrity_errors("S01", (0, 20), before, before, ("start_s",)) + integrity_errors(
        "S01", (0, 20), [word(1, "a", 1.0, 1.5)], [word(1, "a", 1.0, 1.5)], ("start_s",)))
