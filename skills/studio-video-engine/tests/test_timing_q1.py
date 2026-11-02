"""Q1 gate on synthetic sounds: per-word verdicts, n/a words, the built-in negative control, UNTESTABLE."""

from __future__ import annotations

import pytest
from test_timing_support import FPS, Q1, sound, word

from engine.timing.gate import run_q1
from engine.timing.q1 import audible_onset, negative_control, q1_rows, summarize

LINE = sound(("tone", 0.5), ("sil", 0.3), ("tone", 0.7))  # word 1 0-0.5 s, a 0.3 s pause, word 2 at 0.8 s (frame 24)


def entry(second_lit_frame: int, base: int = 0) -> dict:
    second = word(2, "look", 0.8, 1.5, base)
    second["start_frame"] = base + second_lit_frame
    return {"id": "S01", "start_frame": base, "words": [word(1, "What", 0.0, 0.5, base), second]}


def rows_for(lit: int, base: int = 0, q: dict = Q1) -> list[dict]:
    return q1_rows([entry(lit, base)], lambda e: LINE, q, FPS)


def test_audible_onset_is_the_first_edge_after_the_pause_and_none_without_one() -> None:
    assert audible_onset(LINE, 0.5, 0.8, 1.5, Q1) == pytest.approx(0.8, abs=0.011)
    assert audible_onset(sound(("tone", 1.5)), 0.0, 0.5, 1.5, Q1) is None  # continuous speech: nothing to test


@pytest.mark.parametrize("lit, status", [(24, "PASS"), (26, "PASS"), (27, "LATE>2f"), (23, "FAIL-early"), (14, "FAIL-early")])
def test_limits_zero_frames_early_two_frames_late(lit: int, status: str) -> None:
    rows = rows_for(lit)
    assert rows[0]["status"].startswith("n/a") and rows[0]["delta_f"] is None
    assert rows[1]["status"] == status and rows[1]["delta_f"] == lit - 24


def test_entry_start_frame_is_part_of_the_onset_frame() -> None:
    row = rows_for(24, base=400)[1]
    assert row["onset_frame"] == 424 and row["delta_f"] == 0


def test_a_passing_document_passes_only_with_a_detected_negative_control() -> None:
    result = run_q1([entry(25)], lambda e: LINE, Q1, FPS)
    control = result["negative_control"]
    assert result["verdict"] == "PASS" and control["detected"] and control["status"] == "run"
    assert control["before"]["status"] == "PASS" and control["after"] == {
        "lit_frame": 20, "onset_frame": 24, "delta_f": -4, "status": "FAIL-early"}  # lit 25 shifted 5 f earlier


def test_one_early_word_fails_the_document_and_names_it() -> None:
    result = run_q1([entry(22)], lambda e: LINE, Q1, FPS)
    assert result["verdict"] == "FAIL" and result["summary"]["early_words"] == ["S01:look"]
    assert result["negative_control"]["status"] == "not_run"  # nothing passes, so nothing to shift


def test_one_late_word_fails_too() -> None:
    result = run_q1([entry(28)], lambda e: LINE, Q1, FPS)
    assert result["verdict"] == "FAIL" and result["summary"]["late_words"] == ["S01:look"]


def test_gate_that_cannot_see_an_early_word_is_not_a_pass() -> None:
    blind = {**Q1, "max_early_frames": 99}  # a gate that tolerates 99 early frames cannot catch the 5 f control
    result = run_q1([entry(24)], lambda e: LINE, blind, FPS)
    assert result["summary"]["early"] == 0 and not result["negative_control"]["detected"] and result["verdict"] == "FAIL"


def test_a_document_without_any_pause_is_untestable_not_a_pass() -> None:
    continuous = {"id": "S09", "start_frame": 0, "words": [word(1, "Milk", 0.0, 0.7), word(2, "is", 0.7, 1.4)]}
    result = run_q1([continuous], lambda e: sound(("tone", 1.5)), Q1, FPS)
    assert result["verdict"] == "UNTESTABLE" and result["summary"]["words_tested"] == 0


def test_summary_counts_and_orders_the_worst_words() -> None:
    rows = rows_for(30)
    summary = summarize(rows)
    assert (summary["words_total"], summary["words_tested"], summary["late"], summary["early"]) == (2, 1, 1, 0)
    assert summary["worst_10"][0]["delta_f"] == 6


def test_negative_control_flags_exactly_the_shifted_word() -> None:
    entries = [entry(24)]
    control = negative_control(entries, q1_rows(entries, lambda e: LINE, Q1, FPS), lambda e: LINE, Q1, FPS)
    assert control["detected"] and control["summary"]["early_words"] == ["S01:look"]
    assert entries[0]["words"][1]["start_frame"] == 24  # the document under test is not touched
