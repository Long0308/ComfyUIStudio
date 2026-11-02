"""Recipe timing/words-onset-v003 (root decision 2026-10-27): onset at -42 dBFS, 1 f early tolerance, two negative controls."""

from __future__ import annotations

import json
from pathlib import Path

from test_timing_parity_ep04 import needs_wavs, produce
from test_timing_q1 import LINE, entry
from test_timing_support import FPS
from test_timing_v002 import V2

from engine.timing.gate import run_q1
from engine.timing.q1 import q1_rows
from engine.timing.recipe import load_timing_recipe

V3 = load_timing_recipe("timing/words-onset-v003")
Q3 = V3.block("q1")


def test_v003_differs_from_v002_in_exactly_the_decided_q1_values() -> None:
    for block in ("first_word", "all_words", "recognition", "language", "document_schema"):
        assert V3.data[block] == V2.data[block]
    q2 = V2.block("q1")
    changed = {k for k in set(q2) | set(Q3) if q2.get(k) != Q3.get(k)}
    assert changed == {"onset_voiced_dbfs", "max_early_frames", "extra_control_shift_frames"}
    assert (Q3["onset_voiced_dbfs"], Q3["max_early_frames"], Q3["extra_control_shift_frames"]) == (-42.0, 1, [2])
    assert (Q3["max_late_frames"], Q3["warn_late_frames"], Q3["pause_min_s"], Q3["control_shift_frames"]) == (2, 6, 0.10, 5)
    assert V3.data["default_for_domain"] is True


def test_one_frame_early_is_inside_the_tolerance_two_frames_early_fails() -> None:
    status = {lit: q1_rows([entry(lit)], lambda e: LINE, Q3, FPS)[1]["status"] for lit in (24, 23, 22, 14)}
    assert status == {24: "PASS", 23: "PASS", 22: "FAIL-early", 14: "FAIL-early"}


def test_both_negative_controls_run_and_are_flagged() -> None:
    result = run_q1([entry(24)], lambda e: LINE, Q3, FPS)
    control = result["negative_control"]
    assert result["verdict"] == "PASS" and control["status"] == "run" and control["detected"]
    assert [(c["shift_frames"], c["detected"]) for c in control["controls"]] == [(5, True), (2, True)]


def test_a_tolerance_that_hides_the_two_frame_control_makes_the_gate_a_fail() -> None:
    lax = {**Q3, "max_early_frames": 2}  # a word 2 f early would now pass: the 2 f control cannot be flagged
    result = run_q1([entry(24)], lambda e: LINE, lax, FPS)
    assert result["negative_control"]["status"] == "not_run" and not result["negative_control"]["detected"]
    assert result["verdict"] == "FAIL"


@needs_wavs
def test_v003_on_the_hand_run_v004_reference_is_pinned(tmp_path: Path) -> None:
    """Measured 2026-10-27: 33 tested, 30 pass, 3 WARN, 0 early, 0 late FAIL, both controls flagged: verdict PASS."""
    summary, _ = produce(tmp_path, recipe=V3)
    qa = json.loads((tmp_path / "out" / "WORD-TIMING-QA.json").read_text(encoding="utf-8"))["q1"]
    stats = qa["summary"]
    assert (stats["words_tested"], stats["pass"], stats["warn"], stats["late"], stats["early"]) == (33, 30, 3, 0, 0)
    assert stats["warn_words"] == ["S01_B:and(+3f)", "S06_B:and(+3f)", "S06_B:and(+4f)"]
    assert summary["verdict"] == "PASS" and qa["negative_control"]["detected"] is True
    assert [c["shift_frames"] for c in qa["negative_control"]["controls"]] == [5, 2]
