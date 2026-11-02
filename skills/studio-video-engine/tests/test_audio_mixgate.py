"""Ducking with hold, per-section bed gain, loudness targeting and the film-mix gate (synthetic stems, T-E43)."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from audio_fixtures import RATE, tone

from engine.audio import dsp, loudness, mixgate
from engine.seedvr2.seam_media import find_ffmpeg


CFG = {"enabled": True, "target_lufs": -17.0, "tolerance_lu": 1.0, "true_peak_max_dbtp": -1.0, "max_section_jump_lu": 2.0,
       "bed_gain_min_db": -24.0, "bed_gain_max_db": 0.0, "max_bed_step_db": 3.0,
       "max_iterations": 10, "ramp_s": 1.0, "min_measure_s": 0.5,
       "bed_only": {"target_lufs": -22.0, "tolerance_lu": 3.0, "below_speech_lu": 3.0, "min_s": 3.0},
       "brand_voice": {"target_lufs": -16.0, "tolerance_lu": 1.5}}
PUMP = {"enabled": True, "max_swing_db": 3.0, "min_window_s": 0.2}


def ffmpeg() -> str:
    try:
        return find_ffmpeg()
    except Exception:
        pytest.skip("ffmpeg not available")


def windows(*spans: tuple[float, float]) -> list[dict]:
    return [{"id": f"w{i}", "start_sample": int(a * RATE), "end_sample": int(b * RATE)} for i, (a, b) in enumerate(spans)]


def test_windows_closer_than_the_hold_are_merged_and_the_bed_stays_down_between_them() -> None:
    total = 12 * RATE
    spans = windows((2.0, 3.0), (4.0, 5.0), (9.0, 10.0))  # gap 1.0 s (< 1.5 s hold), then gap 4.0 s
    held, rows = dsp.duck_envelope(spans, total, depth_db=-7.0, attack_s=0.15, release_s=0.75, rate=RATE, merge_gap_s=1.5)
    plain, plain_rows = dsp.duck_envelope(spans, total, depth_db=-7.0, attack_s=0.15, release_s=0.75, rate=RATE)
    depth = dsp.db_to_gain(-7.0)
    assert [r["members"] for r in rows] == [["w0", "w1"], ["w2"]] and len(plain_rows) == 3
    assert held[int(3.5 * RATE), 0] == pytest.approx(depth)          # inside the gap: held down
    assert plain[int(3.5 * RATE), 0] > 0.9 * 0 + depth + 0.01        # without hold the bed has started to come back
    assert held[int(7.0 * RATE), 0] == 1.0                           # the long gap is open again
    assert np.all(held <= plain + 1e-6)                              # hold only ever lowers the bed further


def test_a_legacy_duck_without_hold_equals_the_first_episode_builder_sample_for_sample() -> None:
    """The reference below is the v003 ``duck_envelope`` loop (full-length ``local`` array per window)."""
    total, attack, release = 20 * RATE, int(round(0.14 * RATE)), int(round(0.28 * RATE))
    spans = windows((1.0, 2.2), (2.3, 3.0), (6.4, 7.9), (15.0, 19.99))
    duck = dsp.db_to_gain(-14.0)  # a Python float, as in the original builder
    reference = np.ones(total, dtype=np.float32)
    for w in spans:
        start, end = w["start_sample"], w["end_sample"]
        local = np.ones(total, dtype=np.float32)
        a0 = max(0, start - attack)
        if start > a0:
            local[a0:start] = np.linspace(1.0, duck, start - a0, dtype=np.float32)
        local[start:end] = duck
        r_end = min(total, end + release)
        if r_end > end:
            local[end:r_end] = np.linspace(duck, 1.0, r_end - end, dtype=np.float32)
        reference = np.minimum(reference, local)
    ours, _ = dsp.duck_envelope(spans, total, depth_db=-14.0, attack_s=0.14, release_s=0.28, rate=RATE)
    assert np.array_equal(ours[:, 0], reference)


def test_the_section_gain_envelope_holds_each_gain_and_ramps_across_the_seam() -> None:
    sections = [{"start_sample": 0, "end_sample": 4 * RATE}, {"start_sample": 4 * RATE, "end_sample": 8 * RATE}]
    env = dsp.section_gain_envelope(8 * RATE, sections, [6.0, -6.0], 0.3, RATE)
    assert env[RATE, 0] == pytest.approx(dsp.db_to_gain(6.0), rel=1e-5) and env[7 * RATE, 0] == pytest.approx(dsp.db_to_gain(-6.0), rel=1e-5)
    seam = env[int(4 * RATE - 0.15 * RATE):int(4 * RATE + 0.15 * RATE), 0]
    assert np.all(np.diff(seam) <= 1e-9) and seam[0] > seam[-1]


def _bundle(stems_by_class, music, sections, brand=None):
    """The synthetic twin of ``mix.compose``: ``compose(gains, buses)`` with per-class bus gains."""
    def compose(gains, buses):
        total = music.shape[0]
        env = dsp.section_gain_envelope(total, sections, gains, CFG["ramp_s"], RATE) if any(gains) else 1.0
        bed = dsp.to_pcm16(music * env)
        bus = np.zeros((total, 2), dtype=np.int32)
        for name, stem in stems_by_class.items():
            bus += np.rint(stem.astype(np.float64) * dsp.db_to_gain(buses.get(name, 0.0))).astype(np.int32)
        mixed = bus + bed.astype(np.int32) + (0 if brand is None else brand.astype(np.int32))
        return {"final": np.clip(mixed, -32768, 32767).astype("<i2"), "music_float": music * env, "music_pcm": bed,
                "speech_bus": np.clip(bus, -32768, 32767).astype("<i2"), "buses": dict(buses)}
    return compose


def _sections(*lengths: float) -> list[dict]:
    rows, at = [], 0
    for index, seconds in enumerate(lengths):
        end = at + int(seconds * RATE)
        rows.append({"name": f"s{index}", "start_frame": at // 1600, "end_frame_exclusive": end // 1600,
                     "start_sample": at, "end_sample": end})
        at = end
    return rows


def test_evaluate_names_every_way_a_mix_can_fail_and_a_legacy_recipe_is_never_judged() -> None:
    ok = {"integrated_lufs": -17.0, "true_peak_dbtp": -3.0}
    rows = [{"name": "a", "measurable": True, "integrated_lufs": -17.0, "classes": ["dialogue"]},
            {"name": "b", "measurable": True, "integrated_lufs": -14.5, "classes": ["dialogue"]},
            {"name": "c", "measurable": False, "integrated_lufs": None}]
    pump = {"max_swing_db": 4.2, "worst_pair": ["x", "y"]}
    verdict = mixgate.evaluate("cinema", CFG, PUMP, {"integrated_lufs": -14.0, "true_peak_dbtp": 0.5}, rows, pump, False,
                               gains_db=[0.0, 4.5, 4.5], buses={"dialogue": {"mode": "solve", "gain_db": -3.0, "min_db": -3.0}})
    text = " | ".join(verdict["failures"])
    for needle in ("dialogue samples", "whole film", "section b", "true peak", "jump a -> b", "pumping", "bed step a -> b",
                   "dialogue bus already at its floor"):
        assert needle in text
    assert verdict["unmeasured"] == ["c"]
    assert mixgate.evaluate("cinema", CFG, PUMP, ok, rows[:1], {"max_swing_db": 1.0, "worst_pair": None}, True)["verdict"] == "PASS"
    assert mixgate.evaluate("legacy", CFG, PUMP, {"integrated_lufs": -5.0, "true_peak_dbtp": 3.0}, rows, pump, True)["verdict"] == "UNGATED"


DUCK = {"attack_s": 0.15, "release_s": 0.75}
PUMP_CFG = {"enabled": True, "max_swing_db": 3.0, "min_window_s": 1.0, "gap_s": 0.5}


def _duck_rows(*spans: tuple[float, float]) -> list[dict]:
    return [{"id": f"w{i}", "start_sample": int(a * RATE), "end_sample_exclusive": int(b * RATE)} for i, (a, b) in enumerate(spans)]


def _music_with_ducks(total_s: float, level: float, spans, depth_db: float) -> np.ndarray:
    music = np.full((int(total_s * RATE), 2), level, dtype=np.float32)
    for a, b in spans:
        music[int(a * RATE):int(b * RATE)] *= dsp.db_to_gain(depth_db)
    return music


def test_pumping_is_the_swing_of_the_duck_depth_between_windows_not_the_bed_dynamics() -> None:
    sections = _sections(30.0)
    spans = [(5.0, 6.5), (12.0, 13.5), (20.0, 21.5)]
    rows = _duck_rows(*spans)
    even = mixgate.pumping(_music_with_ducks(30.0, 0.2, spans, -7.0), rows, PUMP_CFG, RATE, sections, DUCK)
    assert even["windows_measured"] == 3 and even["pairs_compared"] == 2 and even["max_swing_db"] < 0.1
    assert all(abs(d["depth_db"] - 7.0) < 0.1 for d in even["depths"])
    # a bed that is simply LOUDER in the second half (musical dynamics) is not pumping: depth is relative to the gaps around it
    music = _music_with_ducks(30.0, 0.2, spans, -7.0)
    music[int(10 * RATE):] *= 4.0
    assert mixgate.pumping(music, rows, PUMP_CFG, RATE, sections, DUCK)["max_swing_db"] < 0.1
    uneven = _music_with_ducks(30.0, 0.2, spans[:2], -7.0)
    uneven[int(20 * RATE):int(21.5 * RATE)] *= dsp.db_to_gain(-13.0)                  # the third window ducks 13 dB, not 7: 6 dB of pumping
    result = mixgate.pumping(uneven, rows, PUMP_CFG, RATE, sections, DUCK)
    assert result["max_swing_db"] == pytest.approx(6.0, abs=0.3) and result["worst_pair"] == ["w1", "w2"]


def test_pumping_ignores_windows_under_a_second_and_pairs_across_a_section_seam() -> None:
    sections = _sections(15.0, 15.0)
    spans = [(5.0, 5.8), (20.0, 21.5)]                                                  # the first window is shorter than 1 s
    rows = _duck_rows(*spans)
    result = mixgate.pumping(_music_with_ducks(30.0, 0.2, spans, -7.0), rows, PUMP_CFG, RATE, sections, DUCK)
    assert result["windows_measured"] == 1 and result["pairs_compared"] == 0 and result["max_swing_db"] == 0.0
    long = [(5.0, 6.5), (20.0, 21.5)]                                                   # two windows, one per section: not compared
    assert mixgate.pumping(_music_with_ducks(30.0, 0.2, long, -7.0), _duck_rows(*long), PUMP_CFG, RATE, sections, DUCK)["pairs_compared"] == 0


def test_loudness_is_not_measurable_below_one_gating_block() -> None:
    short = dsp.to_pcm16(tone(0.1, 0.3))
    assert not loudness.measure(short, RATE, ffmpeg()).measurable
    assert loudness.measure(dsp.to_pcm16(tone(2.0, 0.1)), RATE, ffmpeg()).integrated_lufs == pytest.approx(-20.9, abs=0.3)  # two identical channels add 3 dB


def test_physical_action_cues_move_off_speech_and_event_cues_stay_put() -> None:
    from engine.audio.sfxplace import avoid_speech
    spans = windows((1.0, 2.0), (2.1, 3.0))                                          # two lines with a 0.1 s gap
    rows = [{"cue_id": "A", "source": "keyword", "frame": 36}, {"cue_id": "B", "source": "icon", "frame": 36},
            {"cue_id": "C", "source": "manual", "frame": 6}]
    moved, moves = avoid_speech(rows, spans, 30, RATE, 10 * RATE, 0.1)
    assert [r["frame"] for r in moved] == [93, 36, 6]                                 # A: 1.2 s -> after both lines + pad (3.1 s)
    assert moves == [{"cue_id": "A", "from_frame": 36, "to_frame": 93, "speech": "w1"}]
    assert avoid_speech(rows, spans, 30, RATE, 10 * RATE, 0.0)[1] == []                # legacy: off
    from engine.core.errors import Refused
    with pytest.raises(Refused, match="cannot be placed"):
        avoid_speech(rows[:1], windows((0.5, 9.9)), 30, RATE, 10 * RATE, 0.1)
