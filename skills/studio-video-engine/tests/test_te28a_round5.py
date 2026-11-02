"""T-E28a round 5: search window, reference window, one-sided sources, non-finite numbers."""

from __future__ import annotations

import pytest

from av_fixtures import FPS, SR, FakeFfmpeg, _noise, _run, _world, _write_wav, np
from editorial_fixtures import Inputs
from engine.config import rules, schema
from engine.core.errors import Refused, Uncertain
from engine.core.io import read_json
from engine.qa import av
from engine.seedvr2 import seam_blend_policy


def _harmonic(seconds: float = 1.0, f0: float = 100.0, peak: float = 0.5):
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 11))
    return (x / np.max(np.abs(x)) * peak).astype(np.float32)


def _mix_late(wav, late_ms: float, start_frame: int = 60):
    mix = _noise(6.0, 3, 0.001)
    first = int(round(start_frame / FPS * SR)) + int(late_ms / 1000 * SR)
    mix[first:first + len(wav)] += wav
    return mix


@pytest.fixture()
def inputs(tmp_path) -> Inputs:
    return Inputs(tmp_path)


# ---- H1: search_s floor/ceiling and the edge-hit ------------------------------------------------------
@pytest.mark.parametrize("value", [0.0, 0.01, 0.09, -0.1, 0.6, 5.0, True, float("nan")])
def test_h1_a_search_s_outside_the_allowed_range_is_refused(value) -> None:
    with pytest.raises(Refused, match="search_s"):
        av.params_from_config({"qa": {"av": {"search_s": value}}}, FPS)


@pytest.mark.parametrize("value", [av.MIN_SEARCH_S, 0.25, av.DEFAULT_SEARCH_S])
def test_h1_a_search_s_inside_the_range_is_accepted(value: float) -> None:
    assert av.params_from_config({"qa": {"av": {"search_s": value}}}, FPS)[0].search_s == value


@pytest.mark.parametrize("search_s", [0.01, 0.0])
def test_h1_a_periodic_wav_40_ms_late_fails_even_with_a_tiny_engine_level_window(search_s: float) -> None:
    wav = _harmonic()
    row = av.check_binding(_mix_late(wav, 40), wav, av.Binding("dlg A", "a.wav", "a" * 64, 60), fps=FPS,
                           params=av.AvParams(tolerance_ms=av.default_tolerance_ms(FPS), search_s=search_s),
                           actual_sha256="a" * 64)
    assert row["ok"] is False  # critic N1 (periodic WAV, clamped window) used to PASS


def _smooth_wav(seconds: float = 1.0):
    """Low-frequency noise (about 100 ms correlation length): its ncc rises smoothly toward the true start."""
    raw = _noise(seconds + 0.3, 21, 0.3)
    kernel = np.ones(4800) / 4800
    return (np.convolve(raw, kernel, mode="same")[: int(seconds * SR)] * 8).astype(np.float32)


def test_h1_a_peak_on_the_window_edge_is_an_edge_hit_and_fails() -> None:
    wav = _smooth_wav()
    mix = _mix_late(wav, 120)  # 120 ms late with a 100 ms window: the best match is clipped at the edge
    row = av.check_binding(mix, wav, av.Binding("dlg A", "a.wav", "a" * 64, 60), fps=FPS,
                           params=av.AvParams(tolerance_ms=av.default_tolerance_ms(FPS), search_s=0.1),
                           actual_sha256="a" * 64)
    assert row["status"] == "edge-hit" and row["ok"] is False and "edge" in row["reason"]


def test_h1_locate_ex_flags_the_edge_but_not_a_window_clamped_by_the_start_of_the_export() -> None:
    wav = _noise(1.0, 22, 0.3)
    mix = _noise(6.0, 3, 0.001)
    mix[:len(wav)] += wav  # WAV at sample 0, expected start frame 0: the window is clamped by the export start
    lag, ncc, edge = av.locate_ex(mix, wav, 0, fps=FPS, search_s=0.1)
    assert lag == 0 and ncc > 0.99 and edge is False
    lag, ncc, edge = av.locate_ex(_mix_late(wav, 5), wav, 60, fps=FPS, search_s=0.1)
    assert edge is False and abs(lag) == int(0.005 * SR)


def test_h1_the_critic_scenario_fails_by_default_and_a_tiny_window_in_the_config_is_refused(tmp_path) -> None:
    wav = _harmonic()
    (tmp_path / "audio").mkdir()
    sha = _write_wav(tmp_path / "audio" / "a.wav", wav)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    runner = FakeFfmpeg({video: _mix_late(wav, 40), tmp_path / "audio" / "a.wav": wav})
    config = {"fps": 30, "wav_bindings": [{"name": "dlg A", "path": "audio/a.wav", "sha256": sha, "start_frame": 60}]}
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"
    config["qa"] = {"av": {"search_s": 0.01}}
    with pytest.raises(Refused, match="search_s"):
        _run(tmp_path, config, video, runner)


# ---- M1: the PCM identity window ----------------------------------------------------------------------
def _reference_world(tmp_path, *, diverge_from_s: float = 1.0, qa=None, extra=None):
    video, config, runner = _world(tmp_path)
    reference = tmp_path / "ref.mp4"
    reference.write_bytes(b"ref")
    base = runner.table[str(video.resolve())]
    runner.table[str(reference.resolve())] = base.copy()
    changed = base.copy()
    t = np.arange(len(base) - int(diverge_from_s * SR)) / SR
    changed[int(diverge_from_s * SR):] += (0.2 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    runner.table[str(video.resolve())] = changed
    if qa:
        config["qa"] = {"av": qa}
    config.update(extra or {})
    return video, reference, config, runner


def test_m1_without_a_window_the_whole_overlap_is_compared(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path)
    receipt = _run(tmp_path, config, video, runner, reference=reference)  # divergence at 1 s of 6 s
    pcm = receipt["pcm_identity"]
    assert receipt["verdict"] == "FAIL" and pcm["ok"] is False
    assert pcm["compared_samples"] == 6 * SR - av.DEFAULT_SLACK_SAMPLES and pcm["window_source"] == "full overlap"


@pytest.mark.parametrize("value", [0.1, 3, 5.9])
def test_m1_a_config_window_shorter_than_the_overlap_is_refused(tmp_path, value: float) -> None:
    video, reference, config, runner = _reference_world(tmp_path, qa={"reference_seconds": value})
    with pytest.raises(Refused, match="reference_seconds"):
        _run(tmp_path, config, video, runner, reference=reference)  # critic N2: 0.1 hid a 1 s divergence


def test_m1_a_config_window_may_not_go_below_the_episode_main_film(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, qa={"reference_seconds": 5.0})
    receipt = _run(tmp_path, config, video, runner, reference=reference, main_frames=150)  # episode: 5 s main film
    assert receipt["pcm_identity"]["window_source"] == "config" and receipt["verdict"] == "FAIL"
    config["qa"]["av"]["reference_seconds"] = 4.9
    with pytest.raises(Refused, match="main film"):
        _run(tmp_path, config, video, runner, reference=reference, main_frames=150)


def test_m1_an_explicit_cli_window_is_used_as_given(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, diverge_from_s=4.0)
    receipt = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=3)
    assert receipt["pcm_identity"]["ok"] is True and receipt["pcm_identity"]["window_source"] == "cli"
    assert receipt["verdict"] == "PASS_PARTIAL"  # shorter than the floor (round 6: never a plain PASS)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 0.0])
def test_l2_a_non_finite_or_non_positive_cli_window_is_refused_not_a_crash(tmp_path, value: float) -> None:
    video, reference, config, runner = _reference_world(tmp_path)
    with pytest.raises(Refused, match="reference-seconds"):
        _run(tmp_path, config, video, runner, reference=reference, reference_seconds=value)


# ---- M2: wav_bindings next to hand-built audio rows ---------------------------------------------------
def _binding(path: str = "a.wav", start: int = 10, sha: str = "a" * 64) -> dict:
    return {"name": "dlg A", "path": path, "sha256": sha, "start_frame": start}


def test_m2_a_dialogue_audio_row_that_wav_bindings_does_not_carry_is_refused() -> None:
    config = {"wav_bindings": [_binding()],
              "dialogue": [{"id": "B", "start_frame": 6, "audio": {"path": "b.wav", "sha256": "b" * 64}}]}
    with pytest.raises(Refused, match="wav_bindings"):  # critic N6: B was silently never verified
        av.bindings_from_config(config)


@pytest.mark.parametrize("change", [{"start_frame": 11}, {"sha256": "c" * 64}])
def test_m2_a_hand_built_row_that_disagrees_with_its_binding_is_refused(change: dict) -> None:
    config = {"wav_bindings": [_binding()], "dialogue": [{
        "id": "A", "start_frame": 10, "audio": {"path": "a.wav", "sha256": "a" * 64}}]}
    row = config["dialogue"][0]
    row["start_frame"] = change.get("start_frame", row["start_frame"])
    row["audio"]["sha256"] = change.get("sha256", row["audio"]["sha256"])
    with pytest.raises(Refused, match="wav_bindings"):
        av.bindings_from_config(config)


def test_m2_a_hand_built_row_that_agrees_is_accepted_and_not_verified_twice() -> None:
    config = {"wav_bindings": [_binding()], "dialogue": [{
        "id": "A", "start_frame": 8, "audio": {"path": "a.wav", "sha256": "a" * 64, "offset_frames": 2}}]}
    assert [b.name for b in av.bindings_from_config(config)] == ["dlg A"]


def test_m2_an_engine_built_config_with_wav_bindings_and_card_audio_is_accepted(inputs: Inputs) -> None:
    config = inputs.build().config
    assert config["outro_cards"] and all("audio" in card for card in config["outro_cards"])
    assert len(av.bindings_from_config(config)) == len(config["wav_bindings"])


# ---- L1: NaN / Infinity everywhere ---------------------------------------------------------------------
@pytest.mark.parametrize("text", ['{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}'])
def test_l1_read_json_rejects_non_finite_constants(tmp_path, text: str) -> None:
    path = tmp_path / "n.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(Uncertain, match="cannot read JSON"):
        read_json(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_l1_the_schema_validator_rejects_non_finite_numbers(value: float) -> None:
    for node in ({"type": "number"}, {"type": "number", "minimum": 1}, {"type": "number", "exclusiveMinimum": 0}):
        assert schema.validate(value, node), node
    assert schema.validate(1.5, {"type": "number", "minimum": 1}) == []


def test_l1_a_nan_timeline_is_a_violation() -> None:
    episode = {"timeline": {"intro_s": float("nan"), "dialogue_s": 70.0, "outro_s": 10.0}}
    domain = {"delivery": {"master": {"duration_s": 84.0}}, "frame_rates": {"delivery_fps": 30}}
    assert rules.check_timeline(episode, domain)


def _policy() -> seam_blend_policy.SeamPolicy:
    return seam_blend_policy.SeamPolicy(
        policy_version="t", window_half_frames=4, blend_frames=8, low_motion_max=1.0, excess_trigger=2.0,
        hf8_sigma=1.0, allow_clipped_tail=False, motion_metric="native_mean_absdY",
        excess_metric="mean_excess_peak", source="test")


def test_l1_a_nan_motion_measurement_is_refused_by_the_seam_policy() -> None:
    for bad in ({"native_mean_absdY": float("nan"), "mean_excess_peak": 5.0},
                {"native_mean_absdY": 0.1, "mean_excess_peak": float("nan")},
                {"native_mean_absdY": float("inf"), "mean_excess_peak": 1.0}):
        with pytest.raises(Refused, match="finite"):
            seam_blend_policy.decide_policy("auto", _policy(), bad)
    assert seam_blend_policy.decide_policy("auto", _policy(), {"native_mean_absdY": 0.5,
                                                               "mean_excess_peak": 5.0})["mode"] == "hf8"


# ---- L3: survivors of the r4 mutation run ----------------------------------------------------------------
@pytest.mark.parametrize("key", ["search_s", "tolerance_ms", "ncc_min", "silent_peak_max", "pcm_max_abs",
                                 "slack_samples", "reference_seconds"])
def test_l3_bool_and_negative_knobs_are_refused(key: str) -> None:
    for bad in (True, False, -0.5):
        with pytest.raises(Refused, match=key):
            av.params_from_config({"qa": {"av": {key: bad}}}, FPS)


@pytest.mark.parametrize("bad", [0.0, False, 1.5, True])
def test_l3_the_build_path_needs_an_integer_word_timing_offset(inputs: Inputs, bad) -> None:
    inputs.entry("S01_B")["audio"]["offset_frames"] = bad
    with pytest.raises(Refused, match="offset_frames"):
        inputs.build()


def test_l3_a_config_cannot_weaken_the_verdict_through_ncc_min(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    runner.table[str(video.resolve())] = _noise(6.0, 777, 0.01)  # the bound WAV is nowhere in the export
    assert _run(tmp_path, config, video, runner)["verdict"] == "FAIL"
    config["qa"] = {"av": {"ncc_min": 0}}
    with pytest.raises(Refused, match="ncc_min"):
        _run(tmp_path, config, video, runner)


def test_l3_infinite_reference_values_do_not_escape_as_overflow() -> None:
    for bad in (float("inf"), float("nan")):
        with pytest.raises(Refused):
            av.params_from_config({"qa": {"av": {"reference_seconds": bad}}}, FPS)
