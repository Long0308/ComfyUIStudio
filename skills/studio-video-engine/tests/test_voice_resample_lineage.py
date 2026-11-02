"""Explicit resample lineage tests: generated tones exclusively, never real takes."""

from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from engine.core.errors import Refused
from engine.core.io import sha256_file
from engine.voice import resample_lineage as lineage
from engine.voice.wavio import WavData, read_wav

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not found")


def generated_tone(path: Path, kind: str = "440", *, rate: int = 24000) -> Path:
    frames = rate
    pcm = []
    for index in range(frames):
        t = index / rate
        envelope = math.sin(math.pi * index / (frames - 1)) ** 2
        if kind == "440":
            signal = math.sin(2 * math.pi * 440 * t)
        else:
            # Two simultaneous chirped tones, 220->1720 and 700->3700 Hz.
            signal = (math.sin(2 * math.pi * (220 * t + 750 * t * t))
                      + math.sin(2 * math.pi * (700 * t + 1500 * t * t))) / 2
        pcm.append(round(16000 * envelope * signal))
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, rate, frames, "NONE", "not compressed"))
        handle.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))
    return path


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["440", "two-tone-sweep"])
def test_conversion_metrics_zero_delay_and_repeat_hash(tmp_path: Path, kind: str) -> None:
    source = generated_tone(tmp_path / "source.wav", kind)
    source_sha = sha256_file(source)
    destination = tmp_path / "derived.wav"
    receipt = lineage.convert(FFMPEG, source, destination)
    repeated = lineage.convert(FFMPEG, source, tmp_path / "repeated.wav")
    checks = receipt["checks"]
    print(f"METRICS {kind} duration_delta_ms={checks['duration_delta_ms']:.9f} "
          f"correlation={checks['correlation']:.12f} residual_db={checks['residual_db']:.9f} "
          f"delay_samples={checks['delay_samples']} compared_samples={checks['compared_samples']} "
          f"channels_identical={int(checks['channels_identical'])} "
          f"repeat_sha_equal={int(receipt['derived_sha256'] == repeated['derived_sha256'])}")
    assert checks["duration_delta_ms"] <= 1
    assert checks["correlation"] >= 0.9999
    assert checks["residual_db"] <= -60
    assert checks["delay_samples"] == 0
    assert checks["channels_identical"]
    assert receipt["derived_sha256"] == repeated["derived_sha256"] == sha256_file(destination)
    assert receipt["source_sha256"] == source_sha == sha256_file(source)
    assert receipt["source_format"]["sample_rate"] == 24000
    assert receipt["derived_format"]["sample_rate"] == 48000
    assert receipt["derived_format"]["channels"] == 2
    assert receipt["derived_format"]["bits_per_sample"] == 16
    assert receipt["schema"] == "jjv/voice-resample-lineage/v1"
    assert receipt["converter_version"].startswith("ffmpeg version ")
    assert lineage.CONVERSION_FILTER in receipt["converter_command"]
    assert "loudnorm" not in receipt["converter_command_line"]
    assert receipt["processing"]["dither_method"] == "default 0 (none); option omitted"
    assert not list(tmp_path.glob(".voice-resample-*"))


@needs_ffmpeg
def test_existing_destination_is_write_once(tmp_path: Path) -> None:
    source = generated_tone(tmp_path / "source.wav")
    destination = tmp_path / "derived.wav"
    first = lineage.convert(FFMPEG, source, destination)
    again = lineage.convert(FFMPEG, source, destination)
    assert first == again
    before = b"existing protected file"
    destination.unlink()
    destination.write_bytes(before)
    with pytest.raises(Refused, match="E_RESAMPLE_OUTPUT_EXISTS"):
        lineage.convert(FFMPEG, source, destination)
    assert destination.read_bytes() == before


@needs_ffmpeg
def test_wrong_source_format_does_not_create_destination(tmp_path: Path) -> None:
    source = generated_tone(tmp_path / "wrong.wav", rate=48000)
    destination = tmp_path / "derived.wav"
    with pytest.raises(Refused, match="E_RESAMPLE_SOURCE_FORMAT"):
        lineage.convert(FFMPEG, source, destination)
    assert not destination.exists()


@pytest.mark.parametrize("field,value,code", [
    ("duration_delta_ms", 1.01, "E_RESAMPLE_DURATION"),
    ("roundtrip_duration_delta_ms", 1.01, "E_RESAMPLE_DURATION"),
    ("correlation", 0.9998, "E_RESAMPLE_CORRELATION"),
    ("residual_db", -59.9, "E_RESAMPLE_NULL"),
    ("channels_identical", False, "E_RESAMPLE_CHANNELS"),
    ("delay_samples", 24, "E_RESAMPLE_DELAY_BOUNDARY"),
])
def test_measured_thresholds_are_enforced(field: str, value, code: str) -> None:
    checks = {"duration_delta_ms": 0.0, "roundtrip_duration_delta_ms": 0.0,
              "correlation": 1.0, "residual_db": -100.0,
              "channels_identical": True, "delay_samples": 0}
    checks[field] = value
    with pytest.raises(Refused, match=code):
        lineage.require_checks(checks)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, None])
def test_nonfinite_checks_are_refused(value) -> None:
    checks = {"duration_delta_ms": 0.0, "roundtrip_duration_delta_ms": 0.0,
              "correlation": value, "residual_db": -100.0,
              "channels_identical": True, "delay_samples": 0}
    with pytest.raises(Refused, match="E_RESAMPLE_CHECK_VALUE"):
        lineage.require_checks(checks)


@needs_ffmpeg
def test_existing_work_directory_is_never_deleted(tmp_path: Path) -> None:
    source = generated_tone(tmp_path / "source.wav")
    destination = tmp_path / "derived.wav"
    work = tmp_path / ".voice-resample-derived.wav.work"
    work.mkdir()
    (work / "protected.txt").write_text("busy or stale")
    with pytest.raises(Refused, match="E_RESAMPLE_BUSY"):
        lineage.convert(FFMPEG, source, destination)
    assert (work / "protected.txt").read_text() == "busy or stale"
    assert not destination.exists()


def test_alignment_finds_documented_three_sample_delay(tmp_path: Path) -> None:
    source = read_wav(generated_tone(tmp_path / "source.wav", "two-tone-sweep"))
    stereo_pcm = b"".join(source.pcm[i:i + 2] * 2 for i in range(0, len(source.pcm), 2))
    # Two copies of each source frame at 48k, solely a carrier for check inputs.
    derived = WavData(48000, 2, 2, source.frames * 2,
                      b"".join(stereo_pcm[i:i + 4] * 2 for i in range(0, len(stereo_pcm), 4)))
    delayed = WavData(24000, 1, 2, source.frames, b"\0" * 6 + source.pcm[:-6])
    checks = lineage.measure_checks(source, derived, delayed)
    print(f"ALIGNMENT injected_delay_samples=3 measured_delay_samples={checks['delay_samples']} "
          f"correlation={checks['correlation']:.12f} residual_db={checks['residual_db']:.9f}")
    assert checks["delay_samples"] == 3
    assert checks["correlation"] == 1
    assert checks["residual_db"] == -300


def test_silence_cannot_claim_measured_correlation() -> None:
    mono = WavData(24000, 1, 2, 100, b"\0" * 200)
    stereo = WavData(48000, 2, 2, 200, b"\0" * 800)
    with pytest.raises(Refused, match="E_RESAMPLE_SILENCE"):
        lineage.measure_checks(mono, stereo, mono)


def test_measured_gain_change_fails_null_without_gain_fitting(tmp_path: Path) -> None:
    source = read_wav(generated_tone(tmp_path / "source.wav"))
    half = [round(value / 2) for value in source.samples()]
    back = WavData(24000, 1, 2, source.frames, struct.pack(f"<{len(half)}h", *half))
    # The derived carrier is duplicated stereo with precisely doubled frames.
    stereo = b"".join(source.pcm[i:i + 2] * 4 for i in range(0, len(source.pcm), 2))
    derived = WavData(48000, 2, 2, source.frames * 2, stereo)
    checks = lineage.measure_checks(source, derived, back)
    print(f"GAIN_NEGATIVE_TEST correlation={checks['correlation']:.12f} "
          f"residual_db={checks['residual_db']:.9f} delay_samples={checks['delay_samples']}")
    assert checks["correlation"] >= 0.9999
    with pytest.raises(Refused, match="E_RESAMPLE_NULL"):
        lineage.require_checks(checks)


@needs_ffmpeg
def test_failed_fidelity_check_publishes_no_destination(tmp_path: Path, monkeypatch) -> None:
    source = generated_tone(tmp_path / "source.wav")
    destination = tmp_path / "derived.wav"
    measure = lineage.measure_checks
    def bad_null(*args):
        checks = measure(*args)
        checks["residual_db"] = -40.0
        return checks
    monkeypatch.setattr(lineage, "measure_checks", bad_null)
    with pytest.raises(Refused, match="E_RESAMPLE_NULL"):
        lineage.convert(FFMPEG, source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".voice-resample-*"))
