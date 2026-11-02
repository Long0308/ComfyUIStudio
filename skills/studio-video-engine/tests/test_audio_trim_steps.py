"""The cinema solver: speech by class buses (not the bed), bed-only band, bed never raised, steps, ramp (T-E43)."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from audio_fixtures import RATE, tone
from test_audio_mixgate import CFG, _bundle, _sections, ffmpeg

from engine.audio import bedsolve, dsp, mixgate

PUMP = {"max_swing_db": 3.0}
SOLVE = {"*": {"mode": "solve", "min_db": -3.0, "max_db": 3.0}}


def run_solver(layout, schedule, buses_cfg=SOLVE, music_amplitude=0.09):
    """``layout``: [(seconds, class or None, speech amplitude)] per section; one speech class per speech section."""
    lengths = [row[0] for row in layout]
    sections = _sections(*lengths)
    total = int(sum(lengths) * RATE)
    stems: dict[str, np.ndarray] = {}
    at = 0
    for seconds, name, amplitude in layout:
        if name:
            stem = stems.setdefault(name, np.zeros((total, 2), dtype=np.float32))
            stem[at:at + int(seconds * RATE)] = tone(seconds, amplitude, 330.0)
        at += int(seconds * RATE)
    int_stems = {k: dsp.to_pcm16(v) for k, v in stems.items()}
    music = tone(sum(lengths), music_amplitude, 180.0).astype(np.float32)
    roles = ["speech" if name else "bed_only" for _, name, _ in layout]
    classes = [{name} if name else set() for _, name, _ in layout]
    compose = _bundle(int_stems, music, sections)
    gains, buses, history, bundle = bedsolve.target_gains(compose, sections, roles, list(schedule), CFG, RATE, ffmpeg(),
                                                          subprocess.run, section_classes=classes, buses_cfg=buses_cfg)
    rows = bedsolve.measure_sections(bundle["final"], sections, CFG, RATE, ffmpeg(), subprocess.run, roles)
    for row, role, group in zip(rows, roles, classes):
        row["role"], row["classes"] = role, sorted(group)
    return gains, buses, rows, history, roles


def verdict(gains, buses, rows, schedule, buses_cfg=SOLVE):
    rows_buses = {name: {"gain_db": value, "mode": buses_cfg.get(name, buses_cfg["*"])["mode"],
                         **{k: v for k, v in buses_cfg.get(name, buses_cfg["*"]).items() if k in ("min_db", "max_db")}}
                  for name, value in buses.items()}
    return mixgate.evaluate("cinema", CFG, PUMP, {"integrated_lufs": -17.0, "true_peak_dbtp": -3.0}, rows,
                            {"max_swing_db": 0.0, "worst_pair": None}, True, gains, rows_buses, list(schedule))


LAYOUT = [(4.0, None, 0), (6.0, "dialogue", 0.20), (4.0, None, 0)]
ZERO = (0.0, 0.0, 0.0)


def test_speech_above_the_band_is_brought_in_by_its_bus_and_the_bed_is_not_touched() -> None:
    gains, buses, rows, history, roles = run_solver(LAYOUT, ZERO)
    assert -3.0 <= buses["dialogue"] < 0.0 and gains == [0.0, 0.0, 0.0]               # the bed stays at the recipe gain
    by_name = {r["name"]: r["integrated_lufs"] for r in rows}
    assert abs(by_name["s1"] + 17.0) <= 1.0 and -25.0 <= by_name["s0"] <= -20.0 and -25.0 <= by_name["s2"] <= -20.0, by_name
    assert verdict(gains, buses, rows, ZERO)["verdict"] == "PASS"


def test_each_speech_class_gets_its_own_bus_inside_plus_minus_3_db_and_a_pinned_class_does_not_move() -> None:
    layout = [(4.0, None, 0), (6.0, "dialogue", 0.20), (4.0, None, 0), (6.0, "vocabulary", 0.10), (4.0, None, 0)]
    schedule = (0.0,) * 5
    gains, buses, rows, history, roles = run_solver(layout, schedule)
    assert buses["dialogue"] < 0.0 < buses["vocabulary"] <= 3.0 and gains == [0.0] * 5   # one loud, one quiet: opposite buses
    assert all(abs(r["integrated_lufs"] + 17.0) <= 1.0 for r in rows if r["role"] == "speech"), [r["integrated_lufs"] for r in rows]
    pinned = {"dialogue": {"mode": "fixed", "gain_db": -1.5}, "vocabulary": {"mode": "fixed", "gain_db": 2.7}, "*": {"mode": "fixed", "gain_db": 0.0}}
    _, fixed, rows2, _, _ = run_solver(layout, schedule, pinned)
    assert fixed == {"dialogue": -1.5, "vocabulary": 2.7}                                # taken as given, never solved
    assert verdict([0.0] * 5, fixed, rows2, schedule, pinned)["verdict"] in ("PASS", "FAIL")


def test_a_bed_only_section_louder_than_its_limit_is_lowered_never_raised_and_steps_stay_within_3_db() -> None:
    gains, buses, rows, history, roles = run_solver([(4.0, None, 0), (6.0, "dialogue", 0.17), (4.0, None, 0)], ZERO, music_amplitude=0.30)
    assert gains[0] < 0 and gains[2] < 0 and all(g <= 0.0 for g in gains)
    assert max(abs(a - b) for a, b in zip(gains, gains[1:])) <= 3.0 + 1e-6
    upper = bedsolve.bed_only_upper(0, rows, roles, CFG)
    assert rows[0]["integrated_lufs"] <= upper + 0.2 and upper <= -19.0


def test_a_bed_that_is_too_quiet_is_never_raised_and_the_gate_says_so() -> None:
    gains, buses, rows, history, roles = run_solver([(4.0, None, 0), (6.0, "dialogue", 0.17), (4.0, None, 0)], ZERO, music_amplitude=0.01)
    assert gains == [0.0, 0.0, 0.0]
    result = verdict(gains, buses, rows, ZERO)
    assert result["verdict"] == "FAIL" and any("bed-only section s0" in f for f in result["failures"])


def test_a_section_gain_is_never_above_the_recipe_schedule_and_the_gate_catches_a_raise() -> None:
    schedule = (0.0, 0.0, 1.5)
    gains, buses, rows, history, roles = run_solver(LAYOUT, schedule)
    assert all(g <= cap + 1e-9 for g, cap in zip(gains, schedule))
    raised = mixgate.evaluate("cinema", CFG, PUMP, {"integrated_lufs": -17.0, "true_peak_dbtp": -3.0}, rows,
                              {"max_swing_db": 0.0, "worst_pair": None}, True, [0.0, 0.0, 2.5], {}, list(schedule))
    assert any("above its recipe gain" in f for f in raised["failures"])


def test_a_short_unmeasured_section_keeps_its_recipe_gain() -> None:
    layout = [(4.0, None, 0), (6.0, "dialogue", 0.17), (2.0, None, 0)]                  # the last bed-only section is under 3 s
    schedule = (0.0, 0.0, 2.5)
    gains, buses, rows, history, roles = run_solver(layout, schedule)
    assert rows[2]["measurable"] is False and gains[2] == 2.5                           # not copied from the neighbour


def test_speech_that_needs_more_than_the_bus_range_keeps_the_gate_failing_and_names_the_bus() -> None:
    gains, buses, rows, history, roles = run_solver([(4.0, None, 0), (6.0, "dialogue", 0.45), (4.0, None, 0)], ZERO)  # about -7 LUFS
    assert buses["dialogue"] == -3.0
    result = verdict(gains, buses, rows, ZERO)
    assert result["verdict"] == "FAIL" and any("dialogue bus already at its floor -3.0 dB" in f for f in result["failures"])


def test_a_pinned_bus_is_named_in_the_failure() -> None:
    pinned = {"*": {"mode": "fixed", "gain_db": 0.0}}
    gains, buses, rows, history, roles = run_solver(LAYOUT, ZERO, pinned)               # speech about -15 LUFS, nobody may move it
    result = verdict(gains, buses, rows, ZERO, pinned)
    assert result["verdict"] == "FAIL" and any("dialogue bus pinned at 0.0 dB" in f for f in result["failures"])


def test_choose_gain_puts_the_most_levels_in_the_band_then_the_smaller_miss_then_the_target() -> None:
    levels = [-15.9, -20.7, -13.4]                                                      # no single scalar fits all three
    gain = bedsolve.choose_gain(levels, 0.0, CFG, -3.0, 3.0)
    assert sum(-18.0 <= v + gain <= -16.0 for v in levels) == 1 and -3.0 <= gain <= 3.0
    assert bedsolve.choose_gain([-16.5, -17.5], 0.0, CFG, -3.0, 3.0) == 0.0             # already in band, nearest to the target
    assert bedsolve.choose_gain([-14.0, -14.5], 0.0, CFG, -3.0, 3.0) == -2.5            # both in band for [-3, -2]; the miss ties, so the smaller gain wins
    assert bedsolve.choose_gain([-20.0], 0.0, CFG, -3.0, 3.0) == 3.0                    # positive buses are allowed (capped at +3)
    assert bedsolve.choose_gain([-15.0], -1.0, CFG, -3.0, 3.0) == pytest.approx(-3.0)   # measured at -1 dB: -14 at 0, -17 at -3


def test_limit_steps_lowers_the_higher_neighbour_and_never_raises() -> None:
    gains = [0.0, -10.0, 0.0]
    assert bedsolve.limit_steps(gains, 3.0) is True
    assert gains == [-7.0, -10.0, -7.0] and max(gains) <= 0.0
    steady = [0.0, -1.5, -3.0]
    assert bedsolve.limit_steps(steady, 3.0) is False and steady == [0.0, -1.5, -3.0]


def test_roles_and_the_bed_only_limit_follow_the_neighbouring_speech() -> None:
    sections = _sections(4.0, 6.0, 4.0)
    windows = [{"start_sample": 5 * RATE, "end_sample": 6 * RATE}]
    assert bedsolve.roles_of(sections, windows) == ["bed_only", "speech", "bed_only"]
    named = [{**sections[0], "name": "brand_voice"}, *sections[1:]]
    assert bedsolve.roles_of(named, windows)[0] == "brand_voice"
    roles = ["bed_only", "speech", "bed_only"]
    rows = [{"integrated_lufs": -30.0, "measurable": False}, {"integrated_lufs": -20.0, "measurable": True},
            {"integrated_lufs": -30.0, "measurable": False}]
    assert bedsolve.bed_only_upper(0, rows, roles, CFG) == -23.0                      # quietest speech neighbour -20 minus 3 LU
    rows[1]["integrated_lufs"] = -16.0
    assert bedsolve.bed_only_upper(2, rows, roles, CFG) == -19.0                      # the -22 + 3 limit binds


def test_the_bed_gain_ramp_is_one_second_and_never_reaches_into_the_next_seam() -> None:
    sections = [{"start_sample": 0, "end_sample": 3 * RATE}, {"start_sample": 3 * RATE, "end_sample": 3 * RATE + RATE // 2},
                {"start_sample": 3 * RATE + RATE // 2, "end_sample": 8 * RATE}]
    env = dsp.section_gain_envelope(8 * RATE, sections, [0.0, 3.0, 0.0], CFG["ramp_s"], RATE)[:, 0]
    assert np.all(np.isfinite(env)) and env.min() >= 1.0 - 1e-6
    wide = [{"start_sample": 0, "end_sample": 4 * RATE}, {"start_sample": 4 * RATE, "end_sample": 8 * RATE}]
    ramp = dsp.section_gain_envelope(8 * RATE, wide, [0.0, 3.0], 1.0, RATE)[:, 0]
    moving = np.nonzero((ramp > ramp[0] + 1e-6) & (ramp < ramp[-1] - 1e-6))[0]
    assert (moving[-1] - moving[0]) / RATE == pytest.approx(1.0, abs=0.01)             # the 3 dB change takes one second


def test_evaluate_bands_by_role_and_judges_jumps_only_between_speech_sections() -> None:
    rows = [{"name": "brand_voice", "role": "brand_voice", "measurable": True, "integrated_lufs": -13.0},
            {"name": "intro", "role": "bed_only", "measurable": True, "integrated_lufs": -30.0},
            {"name": "dialogue", "role": "speech", "measurable": True, "integrated_lufs": -17.0},
            {"name": "logo_hold", "role": "bed_only", "measurable": True, "integrated_lufs": -21.0},
            {"name": "outro_cards", "role": "speech", "measurable": True, "integrated_lufs": -17.4}]
    whole = {"integrated_lufs": -17.0, "true_peak_dbtp": -3.0}
    quiet = {"max_swing_db": 0.0, "worst_pair": None}
    text = " | ".join(mixgate.evaluate("cinema", CFG, PUMP, whole, rows, quiet, True)["failures"])
    assert "brand voice -13.0" in text and "bed-only section intro -30.0" in text
    assert "logo_hold" not in text and "jump" not in text                              # -21 is inside [-25, -20] (speech -17.0 minus 3 = -20)
    rows[3]["integrated_lufs"] = -19.5
    assert "bed-only section logo_hold" in " | ".join(mixgate.evaluate("cinema", CFG, PUMP, whole, rows, quiet, True)["failures"])
    rows[4]["integrated_lufs"] = -20.5
    assert any("jump" not in f and "outro_cards" in f for f in mixgate.evaluate("cinema", CFG, PUMP, whole, rows, quiet, True)["failures"])
