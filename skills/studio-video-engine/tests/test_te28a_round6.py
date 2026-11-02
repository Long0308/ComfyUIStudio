"""T-E28a round 6: floors from the episode (never the checked config), partial verdicts, malformed rows."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from av_fixtures import HAS_FFMPEG, SR, _jjv, _run, _world, np
from engine.config import pins
from engine.core.errors import Refused
from engine.qa import av, bindings
from engine.seedvr2 import seam_blend_policy


def _reference_world(tmp_path, *, diverge_from_s: float, qa=None, extra=None):
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


# ---- M1: the floor never comes from the config being checked ----------------------------------------------
def test_m1_a_main_frames_field_in_the_checked_config_does_not_lower_the_floor(tmp_path) -> None:
    # critic: main_frames=30 + reference_seconds=1.0 passed with a divergence at 3 s
    video, reference, config, runner = _reference_world(
        tmp_path, diverge_from_s=3.0, qa={"reference_seconds": 1.0}, extra={"main_frames": 30})
    with pytest.raises(Refused, match="reference_seconds"):
        _run(tmp_path, config, video, runner, reference=reference)


def test_m1_the_floor_is_the_episode_main_film_passed_by_the_caller(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, diverge_from_s=5.5, qa={"reference_seconds": 1.0})
    with pytest.raises(Refused, match="main film"):
        _run(tmp_path, config, video, runner, reference=reference, main_frames=150)  # episode: 5 s main film
    config["qa"]["av"]["reference_seconds"] = 5.0
    receipt = _run(tmp_path, config, video, runner, reference=reference, main_frames=150)
    assert receipt["pcm_identity"]["window_source"] == "config" and receipt["pcm_identity"]["ok"] is True
    assert receipt["verdict"] == "PASS" and receipt["partial"] is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="the CLI resolves ffmpeg before running")
def test_m1_the_cli_passes_the_episode_timeline_main_frames(tmp_path, monkeypatch) -> None:
    seen = {}

    def fake_run_av(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "verdict": "PASS", "params": {"tolerance_ms": 1}, "wav_starts": [], "pcm_identity": None}

    monkeypatch.setattr(av, "run_av", fake_run_av)
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    code = _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(tmp_path / "v.mp4"),
                        "--config", str(config), "--json", "--allow-outside", str(tmp_path)])
    assert code == 0 and seen["main_frames"] == 3384  # rules.timeline_frames of the episode contract, not a config field


# ---- M2: a CLI window shorter than the floor is a PARTIAL verdict ---------------------------------------------
def test_m2_a_short_cli_window_over_identical_exports_is_pass_partial_not_pass(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, diverge_from_s=5.9)
    receipt = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=3)
    assert receipt["pcm_identity"]["ok"] is True and receipt["pcm_identity"]["partial"] is True
    assert receipt["partial"] is True and receipt["verdict"] == "PASS_PARTIAL" and receipt["ok"] is False


def test_m2_a_short_cli_window_that_sees_a_divergence_is_fail(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, diverge_from_s=1.0)
    receipt = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=3)
    assert receipt["verdict"] == "FAIL" and receipt["partial"] is True


def test_m2_a_cli_window_covering_the_floor_is_a_full_pass(tmp_path) -> None:
    video, reference, config, runner = _reference_world(tmp_path, diverge_from_s=1.0)
    full = _run(tmp_path, config, video, runner, reference=reference, reference_seconds=6.0)
    assert full["partial"] is False and full["verdict"] == "FAIL"  # the divergence is inside the window: FAIL, not partial
    (tmp_path / "ok").mkdir()
    video2, reference2, config2, runner2 = _reference_world(tmp_path / "ok", diverge_from_s=5.99)
    at_floor = _run(tmp_path / "ok", config2, video2, runner2, reference=reference2, reference_seconds=6.0)
    assert at_floor["partial"] is False and at_floor["verdict"] == "PASS"  # the AAC slack is dropped once, inside pcm
    below = _run(tmp_path / "ok", config2, video2, runner2, reference=reference2, reference_seconds=5.97)
    assert below["partial"] is True and below["verdict"] == "PASS_PARTIAL"  # no second margin below the floor


def test_m2_no_reference_means_no_partial_flag(tmp_path) -> None:
    video, config, runner = _world(tmp_path)
    receipt = _run(tmp_path, config, video, runner)
    assert receipt["partial"] is False and receipt["verdict"] == "PASS"


@pytest.mark.skipif(not HAS_FFMPEG, reason="the CLI resolves ffmpeg before running")
@pytest.mark.parametrize("receipt,code", [
    ({"ok": True, "verdict": "PASS", "partial": False}, 0),
    ({"ok": False, "verdict": "PASS_PARTIAL", "partial": True}, 1),  # fails closed for exit-code/`ok` automation
])
def test_m2_the_cli_exit_code_of_a_partial_receipt_is_not_zero(tmp_path, monkeypatch, receipt, code) -> None:
    full = {"params": {"tolerance_ms": 1}, "wav_starts": [], "pcm_identity": None, **receipt}
    monkeypatch.setattr(av, "run_av", lambda **kwargs: full)
    config = tmp_path / "c.json"
    config.write_text("{}", encoding="utf-8")
    assert _jjv().main(["qa", "av", "--episode", "04-milk-and-mom", "--video", str(tmp_path / "v.mp4"),
                        "--config", str(config), "--json", "--allow-outside", str(tmp_path)]) == code


# ---- LOW: malformed hand-built rows are Refused (exit 1), not KeyError/AttributeError --------------------------
_AUDIO = {"path": "a.wav", "sha256": "a" * 64}


@pytest.mark.parametrize("config", [
    {"dialogue": [{"start_frame": 10, "audio": _AUDIO}]},                       # no id
    {"dialogue": [{"id": "A", "audio": _AUDIO}]},                                # no start_frame
    {"dialogue": [{"id": "A", "start_frame": 10, "audio": {"sha256": "a" * 64}}]},  # no path
    {"dialogue": ["oops"]},
    {"dialogue": [{"id": "A", "start_frame": 10, "audio": ["x"]}]},
    {"dialogue": "oops"},
    {"outro_cards": [{"start_frame": 5, "audio": _AUDIO}]},                      # no term
    {"outro_cards": [{"term": "t", "audio": _AUDIO}]},                           # no start_frame
    {"outro_cards": [{"term": "t", "start_frame": 5, "audio": {"sha256": "a" * 64}}]},
    {"outro_cards": [None]},
    {"outro_cards": {"a": 1}},
])
def test_low_a_malformed_hand_built_row_is_refused(config: dict) -> None:
    with pytest.raises(Refused):
        av.bindings_from_config(config)
    explicit = {"wav_bindings": [{"name": "x", "path": "x.wav", "sha256": "a" * 64, "start_frame": 0}], **config}
    with pytest.raises(Refused):
        av.bindings_from_config(explicit)


@pytest.mark.parametrize("hand_path", ["./audio/a.wav", "audio\\a.wav", "audio/../audio/a.wav", "audio//a.wav"])
def test_low_hand_built_paths_are_normalised_before_the_agreement_check(hand_path: str) -> None:
    config = {"wav_bindings": [{"name": "dlg A", "path": "audio/a.wav", "sha256": "a" * 64, "start_frame": 10}],
              "dialogue": [{"id": "A", "start_frame": 10, "audio": {"path": hand_path, "sha256": "a" * 64}}]}
    assert [b.path for b in av.bindings_from_config(config)] == ["audio/a.wav"]


def test_low_a_different_file_is_still_refused_after_normalisation() -> None:
    config = {"wav_bindings": [{"name": "dlg A", "path": "audio/a.wav", "sha256": "a" * 64, "start_frame": 10}],
              "dialogue": [{"id": "A", "start_frame": 10, "audio": {"path": "./audio/b.wav", "sha256": "a" * 64}}]}
    with pytest.raises(Refused, match="wav_bindings"):
        av.bindings_from_config(config)
    assert bindings.normalise_path(".\\audio\\a.wav") == "audio/a.wav"


# ---- LOW: finite thresholds in SeamPolicy, NaN in pins -------------------------------------------------------
def _seam_config(**changes):
    block = {"policy_version": "t", "window_half_frames": 4, "blend_frames": 8, "low_motion_max": 1.0,
             "excess_trigger": 2.0, "hf8_sigma": 1.0, "allow_clipped_tail": False,
             "motion_metric": "native_mean_absdY", "excess_metric": "mean_excess_peak", **changes}
    return SimpleNamespace(domain={"domain_id": "d", "seam_blend": block})


def test_low_the_seam_policy_thresholds_must_be_finite() -> None:
    assert seam_blend_policy.SeamPolicy.from_config(_seam_config()).low_motion_max == 1.0
    for key in ("low_motion_max", "excess_trigger", "hf8_sigma"):
        for bad in (float("nan"), float("inf")):
            with pytest.raises(Refused, match="finite"):
                seam_blend_policy.SeamPolicy.from_config(_seam_config(**{key: bad}))


def test_low_pins_reads_json_through_the_strict_reader(tmp_path) -> None:
    good, bad = tmp_path / "g.json", tmp_path / "b.json"
    good.write_text('{"x": 1}', encoding="utf-8")
    bad.write_text('{"x": NaN}', encoding="utf-8")
    assert pins._read(good) == {"x": 1} and pins._read(bad) is None
