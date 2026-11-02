"""``jjv qa av``: correlation, per-binding verdicts (tolerance, sha, silence), bindings, PCM identity."""

from __future__ import annotations

import pytest

from av_fixtures import (FPS, HAS_FFMPEG, SR, FakeFfmpeg, P, _jjv, _make_export, _mix_with, _noise,
                         _run, _world, _write_wav, np)
from engine.core.errors import Refused  # noqa: E402
from engine.qa import av  # noqa: E402


# ---- correlation -------------------------------------------------------------------------
def test_locate_finds_the_wav_exactly_at_its_start() -> None:
    wav = _noise(1.0, 1)
    start = int(round(60 / FPS * SR))
    lag, ncc = av.locate(_mix_with(wav, start), wav, 60, fps=FPS, search_s=0.5)
    assert lag == 0 and ncc > 0.99


def test_locate_reports_the_signed_lag_in_samples() -> None:
    wav = _noise(1.0, 2)
    early, late = int(2 * SR) - 4800, int(2 * SR) + 2400  # 100 ms early, 50 ms late
    assert av.locate(_mix_with(wav, early), wav, 60, fps=FPS, search_s=0.5)[0] == -4800
    assert av.locate(_mix_with(wav, late), wav, 60, fps=FPS, search_s=0.5)[0] == 2400


def test_locate_ncc_is_low_when_the_wav_is_not_in_the_mix() -> None:
    _lag, ncc = av.locate(_noise(6.0, 5), _noise(1.0, 6), 60, fps=FPS, search_s=0.5)
    assert ncc < 0.1


def test_locate_returns_none_when_the_export_is_shorter_than_the_wav() -> None:
    assert av.locate(_noise(0.5, 1), _noise(1.0, 2), 0, fps=FPS, search_s=0.5) is None


# ---- per-binding verdict -----------------------------------------------------------------
P = av.AvParams(tolerance_ms=av.default_tolerance_ms(FPS))


def _row(lag_samples: int, params: av.AvParams = P, *, sha: str | None = "a" * 64,
         bound: str = "a" * 64) -> dict:
    wav = _noise(1.0, 3)
    mix = _mix_with(wav, 2 * SR + lag_samples)
    return av.check_binding(mix, wav, av.Binding("w", "w.wav", bound, 60), fps=FPS, params=params, actual_sha256=sha)


def test_a_lag_inside_half_a_frame_passes() -> None:
    row = _row(int(0.016 * SR))  # 16 ms < 16.67 ms
    assert row["ok"] and row["status"] == "located" and abs(row["lag_ms"] - 16.0) < 0.1


def test_a_lag_outside_half_a_frame_fails() -> None:
    row = _row(int(0.020 * SR))  # 20 ms > default 16.67 ms
    assert not row["ok"] and row["lag_ms"] > 16.67


def test_the_tolerance_comes_from_the_config_and_may_only_tighten() -> None:
    params, sources = av.params_from_config({"qa": {"av": {"tolerance_ms": 12}}}, FPS)
    assert sources["tolerance_ms"] == "config" and params.tolerance_ms == 12
    assert _row(int(0.010 * SR), params)["ok"] and not _row(int(0.015 * SR), params)["ok"]  # default would pass 15 ms
    assert _row(int(0.015 * SR))["ok"]
    with pytest.raises(Refused, match="tolerance_ms"):
        av.params_from_config({"qa": {"av": {"tolerance_ms": 60}}}, FPS)
    tight, _ = av.params_from_config({"qa": {"av": {"tolerance_ms": 10}}}, FPS)
    assert not _row(int(0.02 * SR), tight)["ok"]


def test_default_tolerance_is_half_a_frame_of_the_delivery_rate() -> None:
    params, sources = av.params_from_config({}, 30)
    assert params.tolerance_ms == pytest.approx(500 / 30) and sources["tolerance_ms"] == "engine default"
    assert av.params_from_config({}, 24)[0].tolerance_ms == pytest.approx(500 / 24)


def test_a_wav_whose_hash_differs_from_the_receipt_binding_fails() -> None:
    assert not _row(0, sha="b" * 64)["ok"]
    assert _row(0, sha="b" * 64)["sha_ok"] is False


def _silent(spec: dict | None, mix=None, sha_ok: bool = True) -> dict:
    quiet = np.full(int(1.0 * SR), 1e-5, dtype=np.float32)
    binding = av.Binding("sleep", "s.wav", "a" * 64, 60, spec)
    return av.check_binding(_noise(6.0, 1, 0.01) if mix is None else mix, quiet, binding, fps=FPS, params=P,
                            actual_sha256="a" * 64 if sha_ok else "c" * 64)


def test_a_silent_wav_must_declare_an_expect_silent_window() -> None:
    row = _silent(None)
    assert row["status"] == "silent-undeclared" and not row["ok"] and row["placement_proven"] is False


def test_a_declared_silent_wav_reports_the_export_level_and_that_placement_is_unproven() -> None:
    spec = {"start_frame": 60, "end_frame_exclusive": 90, "max_rms": 0.05}
    row = _silent(spec)  # export bed: noise at RMS 0.01
    assert row["status"] == "silent-declared" and row["ok"] and row["placement_proven"] is False
    assert row["lag_ms"] is None and row["expect_silent"]["export_rms"] == pytest.approx(0.01, rel=0.2)
    assert "unprovable by correlation" in row["reason"]


def test_a_loud_signal_where_silence_is_declared_fails() -> None:
    loud = _noise(6.0, 4, 0.3)  # speech-level signal in the declared window
    row = _silent({"start_frame": 60, "end_frame_exclusive": 90, "max_rms": 0.05}, mix=loud)
    assert not row["ok"] and row["expect_silent"]["export_rms"] > 0.05


def test_a_silent_binding_with_a_wrong_hash_still_fails() -> None:
    assert not _silent({"start_frame": 60, "end_frame_exclusive": 90, "max_rms": 0.05}, sha_ok=False)["ok"]


def test_a_window_past_the_end_of_the_export_fails() -> None:
    assert not _silent({"start_frame": 60, "end_frame_exclusive": 9000, "max_rms": 0.05})["ok"]


def test_expect_silent_on_an_audible_wav_is_a_contradiction() -> None:
    wav = _noise(1.0, 3)
    binding = av.Binding("w", "w.wav", "a" * 64, 60, {"start_frame": 60, "end_frame_exclusive": 90, "max_rms": 1.0})
    row = av.check_binding(_mix_with(wav, 2 * SR), wav, binding, fps=FPS, params=P, actual_sha256="a" * 64)
    assert row["status"] == "silent-contradiction" and not row["ok"]


def test_unknown_or_negative_config_keys_are_refused() -> None:
    for bad in ({"tolerence_ms": 40}, {"tolerance_ms": -1}, {"tolerance_ms": 0}):
        with pytest.raises(Refused):
            av.params_from_config({"qa": {"av": bad}}, FPS)


# ---- bindings from the two config shapes ---------------------------------------------------
def test_bindings_from_the_engine_config_shape() -> None:
    rows = av.bindings_from_config({"wav_bindings": [
        {"name": "dlg A", "path": "a.wav", "sha256": "a" * 64, "start_frame": 90}]})
    assert rows == [av.Binding("dlg A", "a.wav", "a" * 64, 90)]


def test_bindings_from_the_hand_built_shape_add_the_audio_offset() -> None:
    rows = av.bindings_from_config({
        "dialogue": [{"id": "S01_A", "start_frame": 90, "audio": {"path": "a.wav", "sha256": "a" * 64, "offset_frames": 3}}],
        "outro_cards": [{"term": "Creamy", "start_frame": 2160, "audio": {"path": "c.wav", "sha256": "b" * 64}}]})
    assert [(r.name, r.start_frame) for r in rows] == [("dlg S01_A", 93), ("voc Creamy", 2160)]


@pytest.mark.parametrize("config", [
    {"wav_bindings": [{"name": "a", "path": "a.wav", "start_frame": 0}]},
    {"wav_bindings": [{"name": "a", "path": "a.wav", "sha256": "xyz", "start_frame": 0}]},
    {"dialogue": [{"id": "S01_A", "start_frame": 0, "audio": {"path": "a.wav"}}]},
    {"outro_cards": [{"term": "T", "start_frame": 0, "audio": {"path": "a.wav", "sha256": None}}]}])
def test_a_binding_without_a_sha256_is_refused_not_unverified(config: dict) -> None:
    with pytest.raises(Refused, match="no sha256"):
        av.bindings_from_config(config)


def test_a_config_with_nothing_to_verify_is_refused() -> None:
    with pytest.raises(Refused):
        av.bindings_from_config({"dialogue": []})


# ---- PCM identity --------------------------------------------------------------------------
def test_pcm_identity_is_exact_for_identical_audio_and_fails_on_any_real_difference() -> None:
    base = _noise(3.0, 8)
    same = av.pcm_identity(base, base.copy(), seconds=2.0, params=P)
    assert same["ok"] and same["max_abs"] == 0.0 and same["compared_samples"] == 2 * SR - 2048
    other = base.copy()
    other[1000] += 0.01
    assert not av.pcm_identity(base, other, seconds=2.0, params=P)["ok"]


def test_pcm_identity_ignores_the_tail_slack_but_not_the_body() -> None:
    base = _noise(3.0, 8)
    tail = base.copy()
    tail[2 * SR - 100] += 0.5  # inside the slack of the last 2048 samples of the 2 s window
    assert av.pcm_identity(base, tail, seconds=2.0, params=P)["ok"]


def test_pcm_identity_fails_when_an_export_is_shorter_than_the_window() -> None:
    assert not av.pcm_identity(_noise(1.0, 1), _noise(3.0, 1), seconds=2.0, params=P)["ok"]


