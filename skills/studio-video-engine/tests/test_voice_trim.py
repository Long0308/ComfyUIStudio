"""trim (legacy equivalence + onset rule), split (proof, pad, refusals), and the static rules."""

from __future__ import annotations

import ast
import io
import random
import wave
from pathlib import Path

import pytest
from wav_fixtures import noise_burst, pcm16, segments_wav_bytes, silence, tone

from engine.config.loader import SKILL_ROOT
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.voice import split as split_mod
from engine.voice.trim import TrimParams, trim_bounds, trim_pcm, window_frames
from engine.voice.wavio import WavData, read_wav

RECIPE = SKILL_ROOT / "recipes" / "voice" / "omnivoice-en-broadcast-v001.json"


def params() -> TrimParams:
    return TrimParams.from_recipe(read_json(RECIPE))


def wav_data(parts: list[list[int]], rate: int = 48_000, channels: int = 2) -> WavData:
    raw = segments_wav_bytes(parts, rate, channels)
    with wave.open(io.BytesIO(raw), "rb") as handle:
        return WavData(rate, channels, 2, handle.getnframes(), handle.readframes(handle.getnframes()))


def test_recipe_trim_parameters_are_the_verified_tool_values() -> None:
    p = params()
    assert (p.threshold_dbfs, p.window_ms, p.pre_roll_s, p.post_roll_s) == (-40.0, 10, 0.08, 0.1)
    assert window_frames(48_000, 10) == 480 and window_frames(24_000, 10) == 240


def test_plain_speech_matches_the_legacy_arithmetic() -> None:
    data = wav_data([silence(0.2, 48_000), tone(0.5, 48_000), silence(0.3, 48_000)])
    bounds = trim_bounds(data, params())
    assert bounds.voiced_start_sample == 9_600 and bounds.voiced_end_sample == 33_600
    assert bounds.start_sample == max(0, round((9_600 / 48_000 - 0.08) * 48_000)) == 5_760
    assert bounds.end_sample == round((33_600 / 48_000 + 0.1) * 48_000) == 38_400
    assert bounds.onset["differs_from_naive"] is False
    assert len(trim_pcm(data, bounds)) == bounds.samples * 4


def test_short_burst_followed_by_silence_is_not_the_onset() -> None:
    rate = 48_000
    data = wav_data([silence(0.1, rate), noise_burst(0.1, rate), silence(0.6, rate), tone(0.5, rate), silence(0.2, rate)])
    bounds = trim_bounds(data, params())
    assert bounds.onset["naive_first_speech_sample"] == 4_800  # the burst
    assert bounds.voiced_start_sample == round(0.8 * rate) and bounds.onset["differs_from_naive"] is True
    assert bounds.onset["skipped_bursts"] == [{"start_window": 10, "end_window": 20, "gap_windows_after": 60}]
    assert bounds.start_sample == round((0.8 - 0.08) * rate)


def test_short_burst_right_before_speech_keeps_the_legacy_onset() -> None:
    rate = 48_000
    data = wav_data([silence(0.1, rate), noise_burst(0.1, rate), silence(0.2, rate), tone(0.5, rate), silence(0.2, rate)])
    bounds = trim_bounds(data, params())
    assert bounds.voiced_start_sample == 4_800 and bounds.onset["differs_from_naive"] is False


def test_isolated_bursts_everywhere_fall_back_to_the_file_start() -> None:
    rate = 48_000
    data = wav_data([silence(0.1, rate), noise_burst(0.1, rate), silence(0.8, rate)])
    bounds = trim_bounds(data, params())
    assert bounds.voiced_start_sample is None and bounds.start_sample == 0
    assert bounds.voiced_end_sample == 9_600 and bounds.end_sample == round((0.2 + 0.1) * rate)


def test_silent_file_and_whole_file_speech() -> None:
    quiet = wav_data([silence(0.5, 48_000)])
    bounds = trim_bounds(quiet, params())
    assert (bounds.start_sample, bounds.end_sample) == (0, quiet.frames)
    loud = wav_data([tone(0.5, 48_000)])
    bounds = trim_bounds(loud, params())
    assert (bounds.start_sample, bounds.end_sample) == (0, loud.frames)
    with pytest.raises(Refused, match="empty"):
        trim_bounds(WavData(48_000, 2, 2, 0, b""), params())


def test_mono_24k_input_and_min_run_edge() -> None:
    rate = 24_000
    data = wav_data([silence(0.3, rate), tone(0.15, rate), silence(0.7, rate), tone(0.4, rate)], rate, 1)
    bounds = trim_bounds(data, params())
    assert bounds.voiced_start_sample == round(0.3 * rate)  # a 0.15 s run is speech
    data = wav_data([silence(0.3, rate), tone(0.14, rate), silence(0.7, rate), tone(0.4, rate)], rate, 1)
    assert trim_bounds(data, params()).voiced_start_sample == round(1.14 * rate)


# ---- split -------------------------------------------------------------------------------
def plan(*segments: tuple[str, int, bool], pad: bool = False) -> split_mod.SplitPlan:
    return split_mod.parse_split_plan(
        {"pad_tail_silence": pad, "segments": [{"label": a, "samples": b, "speech_conditioning": c} for a, b, c in segments]},
        "test")


@pytest.mark.parametrize("document, message", [
    ({}, "non-empty list"),
    ({"segments": []}, "non-empty list"),
    ({"segments": [{"label": "a b", "samples": 1, "speech_conditioning": True}]}, "plain token"),
    ({"segments": [{"label": "a", "samples": -1, "speech_conditioning": True}]}, "positive integer"),
    ({"segments": [{"label": "a", "samples": True, "speech_conditioning": True}]}, "positive integer"),
    ({"segments": [{"label": "a", "samples": 1, "speech_conditioning": "yes"}]}, "boolean"),
    ({"segments": [{"label": "a", "samples": 1, "speech_conditioning": True}] * 2}, "duplicate"),
    ({"segments": [{"label": "a", "samples": 1, "speech_conditioning": True}], "extra": 1}, "unknown keys"),
    ({"segments": [{"label": "a", "samples": 1}]}, "exactly label"),
])
def test_split_plan_refusals(document, message) -> None:
    with pytest.raises(Refused, match=message):
        split_mod.parse_split_plan(document, "test")


def test_split_exact_pad_and_refusal() -> None:
    source = pcm16(list(range(-500, 500)), 2)  # 1000 frames
    parts = split_mod.apply_split(source, 4, plan(("a", 400, True), ("b", 600, True)))
    proof = split_mod.concat_proof(parts, source, 4, plan(("a", 400, True), ("b", 600, True)))
    assert b"".join(p.pcm for p in parts) == source and proof["padded_samples"] == 0 and proof["ok"]
    padded = plan(("a", 700, True), ("tail", 500, False), pad=True)
    parts = split_mod.apply_split(source, 4, padded)
    assert [p.real_samples for p in parts] == [700, 300] and parts[1].padded_samples == 200
    assert parts[1].pcm.endswith(b"\x00" * 800) and split_mod.concat_proof(parts, source, 4, padded)["padded_samples"] == 200
    with pytest.raises(Refused, match="pad_tail_silence is false"):
        split_mod.apply_split(source, 4, plan(("a", 700, True), ("tail", 500, False)))
    with pytest.raises(Refused, match="whole frames"):
        split_mod.apply_split(source[:-1], 4, padded)


def test_split_property_segments_concatenate_to_the_source() -> None:
    rng = random.Random(7)
    for _ in range(25):
        frames = rng.randint(1, 3_000)
        source = pcm16([rng.randint(-32768, 32767) for _ in range(frames)], 2)
        cuts = sorted({rng.randint(1, frames) for _ in range(rng.randint(1, 5))} | {frames})
        sizes = [b - a for a, b in zip([0] + cuts[:-1], cuts)]
        extra = rng.randint(0, 50)
        segments = [(f"s{i}", n, True) for i, n in enumerate(sizes)]
        if extra:
            segments.append(("pad", extra, False))
        spec = plan(*segments, pad=True)
        parts = split_mod.apply_split(source, 4, spec)
        proof = split_mod.concat_proof(parts, source, 4, spec)
        assert b"".join(p.pcm for p in parts)[:len(source)] == source
        assert proof["concatenated_samples"] == frames + extra and proof["padded_samples"] == extra


# ---- static rules --------------------------------------------------------------------------
def _imports_trim(source: Path) -> bool:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith("trim") or (module in ("", ".", "engine.voice") and any(a.name == "trim" for a in node.names)):
                return True
        if isinstance(node, ast.Import) and any(a.name.endswith("voice.trim") for a in node.names):
            return True
    return False


def test_only_finalize_imports_the_trimmer() -> None:
    engine = SKILL_ROOT / "engine"
    importers = sorted(p.relative_to(engine).as_posix() for p in engine.rglob("*.py") if _imports_trim(p))
    assert importers == ["voice/finalize.py"]


def test_voice_modules_stay_small_and_neutral() -> None:
    folder = SKILL_ROOT / "engine" / "voice"
    for source in folder.glob("*.py"):
        assert len(source.read_text(encoding="utf-8").splitlines()) <= 400, source
    read_wav  # the public WAV reader is the only PCM entry point used by finalize
