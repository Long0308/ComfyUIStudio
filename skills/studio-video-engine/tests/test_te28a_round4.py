"""T-E28a round 4: later-segment offsets, config may only tighten qa av, duplicates, strictness, v003 baseline."""

from __future__ import annotations

import copy
import json
import math

import pytest

from av_fixtures import FPS, SR, _noise, _run, _world, np
from editorial_fixtures import HISTORICAL_TIMING_V001, Inputs
from engine.core.errors import Refused, Uncertain
from engine.qa import av


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


def _with_offset_s(inputs: Inputs, shot_id: str, offset_s: float) -> None:
    shots = copy.deepcopy(inputs.config.shots)
    next(s for s in shots if s["shot"] == shot_id)["wav_binding"]["offset_s"] = offset_s
    inputs.with_config(shots=shots)


# ---- MED-1: offsets on non-first segments of a multi-segment dialogue -------------------------------
def test_med1_a_nonzero_offset_on_a_later_segment_is_refused(inputs: Inputs) -> None:
    _with_offset_s(inputs, "S06_B2", 0.1)  # critic P1: moved the WAV 3 frames, not its icons
    with pytest.raises(Refused, match="non-first segment"):
        inputs.build()


def test_med1_a_zero_offset_on_later_segments_and_a_first_segment_offset_still_build(inputs: Inputs) -> None:
    assert inputs.build().events["icon_events"]
    _with_offset_s(inputs, "S06_B1", 0.1)  # first segment: agrees with the timing entry's offset_frames
    inputs.entry("S06_B")["audio"]["offset_frames"] = 3
    moved = {e["word"]: e["frame"] for e in inputs.build().events["icon_events"] if e["shot"] == "S06_B"}
    (inputs.tmp / "b").mkdir()
    base = {e["word"]: e["frame"] for e in Inputs(inputs.tmp / "b").build().events["icon_events"]
            if e["shot"] == "S06_B"}
    assert moved == {k: v + 3 for k, v in base.items()}


# ---- MED-2: qa av config may only TIGHTEN the engine defaults ---------------------------------------
LOOSE = [
    ("tolerance_ms", 1e9), ("tolerance_ms", float("inf")), ("tolerance_ms", 20.0),
    ("ncc_min", 0), ("ncc_min", 0.29),
    ("silent_peak_max", 0.9), ("silent_peak_max", 0.002),
    ("pcm_max_abs", 0.5), ("slack_samples", 100000),
    ("tolerance_ms", float("nan")), ("search_s", float("inf")), ("reference_seconds", float("inf")),
]


@pytest.mark.parametrize("key,value", LOOSE)
def test_med2_a_loosening_or_non_finite_knob_is_refused(key: str, value: float) -> None:
    with pytest.raises(Refused, match=key):
        av.params_from_config({"qa": {"av": {key: value}}}, FPS)


@pytest.mark.parametrize("key,value", [("tolerance_ms", 10.0), ("tolerance_ms", 500 / 30), ("ncc_min", 0.3),
                                       ("ncc_min", 0.6), ("silent_peak_max", 1e-4), ("pcm_max_abs", 1e-4),
                                       ("slack_samples", 1024), ("search_s", 0.25)])
def test_med2_tightening_a_knob_is_accepted_and_recorded(key: str, value: float) -> None:
    params, sources = av.params_from_config({"qa": {"av": {key: value}}}, FPS)
    assert getattr(params, key) == value and sources[key] == "config"


def test_med2_a_late_wav_does_not_pass_with_a_declared_huge_tolerance(tmp_path) -> None:
    video, config, runner = _world(tmp_path, lag_samples=int(0.1 * SR))  # 100 ms late
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"
    config["qa"] = {"av": {"tolerance_ms": 1e9}}
    with pytest.raises(Refused, match="tolerance_ms"):
        _run(tmp_path, config, video, runner)


def test_med2_a_config_cannot_declare_its_way_to_a_pass_through_ncc_min_or_silent_peak(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    runner.table[str(video.resolve())] = _noise(6.0, 777, 0.01)  # the bound WAV is not in the export at all
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"
    for block in ({"ncc_min": 0}, {"silent_peak_max": 0.9}):
        config["qa"] = {"av": block}
        with pytest.raises(Refused, match=next(iter(block))):
            _run(tmp_path, config, video, runner)


# ---- LOW-1: duplicate expect_silent rows --------------------------------------------------------------
def test_low1_two_expect_silent_rows_for_one_shot_are_refused(inputs: Inputs) -> None:
    row = copy.deepcopy(inputs.boundaries["expect_silent"][0])
    row["max_rms"] = 0.05
    inputs.boundaries["expect_silent"].append(row)
    with pytest.raises(Refused, match="declared twice"):
        inputs.build()


# ---- LOW-2: offset_frames default only when absent, strict integer ----------------------------------
@pytest.mark.parametrize("bad", [0.0, False, None, -0.0, "0"])
def test_low2_a_present_offset_frames_must_be_a_real_integer(bad) -> None:
    cfg = {"dialogue": [{"id": "A", "start_frame": 10,
                         "audio": {"path": "a.wav", "sha256": "a" * 64, "offset_frames": bad}}]}
    with pytest.raises(Refused, match="offset_frames"):
        av.bindings_from_config(cfg)


def test_low2_an_absent_offset_frames_defaults_to_zero() -> None:
    cfg = {"dialogue": [{"id": "A", "start_frame": 10, "audio": {"path": "a.wav", "sha256": "a" * 64}}]}
    assert av.bindings_from_config(cfg)[0].start_frame == 10


# ---- LOW-3: non-finite max_rms ------------------------------------------------------------------------
def test_low3_a_nan_max_rms_is_refused_in_qa_av() -> None:
    spec = {"start_frame": 60, "end_frame_exclusive": 90, "max_rms": float("nan")}
    with pytest.raises(Refused, match="max_rms"):
        av.bindings_from_config({"wav_bindings": [{"name": "s", "path": "s.wav", "sha256": "a" * 64,
                                                   "start_frame": 60, "expect_silent": spec}]})


def test_low3_a_nan_max_rms_never_reaches_the_boundaries_check(inputs: Inputs) -> None:
    inputs.boundaries["expect_silent"][0]["max_rms"] = float("nan")
    with pytest.raises((Refused, Uncertain), match="max_rms|non-finite"):  # read_json rejects the constant first
        inputs.build()


# ---- LOW-4: sub-frame offsets -------------------------------------------------------------------------
@pytest.mark.parametrize("shot,offset_s", [("S01_B", 0.01), ("S04_B", 0.02), ("S06_B3", 0.02), ("S01_B", 0.0166)])
def test_low4_a_sub_frame_offset_is_refused(inputs: Inputs, shot: str, offset_s: float) -> None:
    _with_offset_s(inputs, shot, offset_s)
    with pytest.raises(Refused, match="whole number of frames"):
        inputs.build()


def test_low4_a_whole_frame_offset_given_in_seconds_is_accepted(inputs: Inputs) -> None:
    _with_offset_s(inputs, "S04_B", 2 / 30)
    inputs.entry("S04_B")["audio"]["offset_frames"] = 2
    assert inputs.build().config["wav_bindings"]


# ---- weak test hardening: the declared-silent run must exercise the bound ----------------------------
def test_the_declared_silent_run_depends_on_max_rms(tmp_path) -> None:
    from av_fixtures import _write_wav
    video, config, runner = _world(tmp_path)
    quiet = tmp_path / "audio" / "quiet.wav"
    sha = _write_wav(quiet, np.full(SR, 1e-5, dtype=np.float32))
    runner.table[str(quiet.resolve())] = np.full(SR, 1e-5, dtype=np.float32)
    spec = {"start_frame": 150, "end_frame_exclusive": 180, "max_rms": 0.04}
    config["wav_bindings"].append({"name": "dlg Q", "path": "audio/quiet.wav", "sha256": sha, "start_frame": 150,
                                   "expect_silent": spec})
    ok = _run(tmp_path, config, video, runner)
    measured = ok["wav_starts"][1]["expect_silent"]["export_rms"]
    assert 0.005 < measured < 0.04 and ok["verdict"] == "PASS"  # the export bed is really there (noise RMS ~0.01)
    spec["max_rms"] = measured / 2
    tight = _run(tmp_path, config, video, runner)
    assert tight["verdict"] == "FAIL" and not tight["wav_starts"][1]["ok"]


# ---- v003 baseline: the onset fix changes exactly the seven first words, nothing else ---------------
FIRST_WORD_ENTRIES = {"S01_A", "S02_A", "S03_A", "S04_A", "S04_B", "S05_A", "S06_A"}


def test_v001_to_v003_changes_exactly_the_seven_first_word_frames(tmp_path) -> None:
    (tmp_path / "v001").mkdir()
    (tmp_path / "v003").mkdir()
    old = Inputs(tmp_path / "v001", HISTORICAL_TIMING_V001).build()
    new = Inputs(tmp_path / "v003").build()
    assert old.events["icon_events"] == new.events["icon_events"]  # icons untouched
    assert old.events["transitions"] == new.events["transitions"]
    assert old.events["ending"] == new.events["ending"]
    assert old.config["wav_bindings"] == new.config["wav_bindings"]
    assert old.config["motion"] == new.config["motion"]
    changed = set()
    for before, after in zip(old.config["dialogue"], new.config["dialogue"]):
        assert before["id"] == after["id"]
        for index, (wb, wa) in enumerate(zip(before["words"], after["words"])):
            if wb != wa:
                assert index == 0, f"{before['id']} word {index} changed"
                assert {k for k in wb if wb[k] != wa[k]} == {"startF"}
                assert wa["startF"] > wb["startF"]
                changed.add(before["id"])
        assert {k: v for k, v in before.items() if k != "words"} == {k: v for k, v in after.items() if k != "words"}
    assert changed == FIRST_WORD_ENTRIES
    karaoke = {a["shot"] for a, b in zip(old.events["karaoke_lines"], new.events["karaoke_lines"]) if a != b}
    assert karaoke == FIRST_WORD_ENTRIES
    assert old.config["word_timing"]["sha256"] != new.config["word_timing"]["sha256"]
    assert math.isclose(sum(len(d["words"]) for d in old.config["dialogue"]),
                        sum(len(d["words"]) for d in new.config["dialogue"]))
