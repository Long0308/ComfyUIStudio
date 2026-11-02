"""Explicit PCM16 24k mono -> 48k duplicated stereo, with measured lineage.

This module neither grants approval nor changes the passthrough path. Callers must
bind ``source_sha256`` to a listen-approval before publishing this lineage.
The null test uses the entire overlapping PCM after a bounded integer delay
search; no gain fit, mean removal, trimming, or perceptual weighting is applied.
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.io import sha256_file, write_once
from .wavio import WavData, read_wav

SCHEMA_ID = "jjv/voice-resample-lineage/v1"
CONVERSION_FILTER = "aresample=48000:resampler=soxr:precision=28,pan=stereo|c0=c0|c1=c0"
ROUNDTRIP_FILTER = "pan=mono|c0=c0,aresample=24000:resampler=soxr:precision=28"
THRESHOLDS = {"duration_delta_ms_max": 1.0, "correlation_min": 0.9999,
              "residual_db_max": -60.0, "delay_search_samples": 24}


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"E_RESAMPLE_CONVERTER: cannot run converter: {error}") from error
    if result.returncode:
        raise Uncertain(f"E_RESAMPLE_CONVERTER: exit {result.returncode}: {result.stderr.strip()[:600]}")
    return result


def _read(path: Path) -> WavData:
    try:
        return read_wav(path)
    except (Refused, Uncertain) as error:
        raise Refused(f"E_RESAMPLE_FORMAT: {error}") from error


def _format(wav: WavData) -> dict:
    return {"sample_rate": wav.rate, "channels": wav.channels, "sample_width_bytes": wav.sample_width,
            "bits_per_sample": wav.sample_width * 8, "encoding": "PCM signed little-endian",
            "samples_per_channel": wav.frames}


def _aligned(source: list[int], derived: list[int], delay: int) -> tuple[list[int], list[int]]:
    # Positive delay means the roundtrip signal arrives later than the source.
    source_start, derived_start = max(0, -delay), max(0, delay)
    length = min(len(source) - source_start, len(derived) - derived_start)
    return source[source_start:source_start + length], derived[derived_start:derived_start + length]


def _correlation(source: list[int], derived: list[int]) -> float:
    source_energy = sum(value * value for value in source)
    derived_energy = sum(value * value for value in derived)
    if not source_energy or not derived_energy:
        return 0.0
    return sum(a * b for a, b in zip(source, derived)) / math.sqrt(source_energy * derived_energy)


def measure_checks(source: WavData, derived: WavData, roundtrip: WavData) -> dict:
    """Measure all samples; select max normalized dot-product over +/-24 samples.

    Ties are resolved by smallest absolute delay, then the lower signed delay.
    Residual dB is 10*log10(sum((roundtrip-source)^2)/sum(source^2)),
    without gain adjustment. Exact zero residual is represented by a -300 dB
    numerical floor so the receipt remains finite JSON. Silence is refused:
    correlation cannot establish waveform preservation for a zero-energy signal.
    """
    if (source.rate, source.channels, source.sample_width) != (24000, 1, 2) or source.frames <= 0:
        raise Refused("E_RESAMPLE_SOURCE_FORMAT: expected nonempty 24000 Hz mono PCM16")
    if (derived.rate, derived.channels, derived.sample_width) != (48000, 2, 2) or derived.frames <= 0:
        raise Refused("E_RESAMPLE_DERIVED_FORMAT: expected nonempty 48000 Hz stereo PCM16")
    if (roundtrip.rate, roundtrip.channels, roundtrip.sample_width) != (24000, 1, 2) or roundtrip.frames <= 0:
        raise Refused("E_RESAMPLE_ROUNDTRIP_FORMAT: expected nonempty 24000 Hz mono PCM16")
    original = list(source.samples())
    back = list(roundtrip.samples())
    stereo = derived.samples()
    if not any(original):
        raise Refused("E_RESAMPLE_SILENCE: source energy is zero; correlation is undefined")
    candidates = []
    for delay in range(-int(THRESHOLDS["delay_search_samples"]), int(THRESHOLDS["delay_search_samples"]) + 1):
        a, b = _aligned(original, back, delay)
        if a:
            candidates.append((_correlation(a, b), -abs(delay), -delay, delay))
    correlation, _, _, delay = max(candidates)
    a, b = _aligned(original, back, delay)
    source_energy = sum(value * value for value in a)
    residual_energy = sum((left - right) ** 2 for left, right in zip(a, b))
    residual_db = 10 * math.log10(max(residual_energy / source_energy, 1e-30))
    return {"duration_delta_ms": abs(source.duration_s - derived.duration_s) * 1000,
            "roundtrip_duration_delta_ms": abs(source.duration_s - roundtrip.duration_s) * 1000,
            "correlation": correlation, "residual_db": residual_db, "delay_samples": delay,
            "delay_ms": delay * 1000 / source.rate, "compared_samples": len(a),
            "source_samples": source.frames, "derived_samples": derived.frames,
            "roundtrip_samples": roundtrip.frames, "channels_identical": stereo[::2] == stereo[1::2],
            "thresholds": dict(THRESHOLDS),
            "delay_method": "maximum normalized dot product over integer lags [-24,24]; ties: min abs lag, then lower signed lag",
            "null_method": "all overlapping aligned samples; RMS residual relative to source; no gain/DC fit; -300 dB floor"}


def require_checks(checks: dict) -> None:
    for key in ("duration_delta_ms", "roundtrip_duration_delta_ms", "correlation", "residual_db", "delay_samples"):
        value = checks.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Refused(f"E_RESAMPLE_CHECK_VALUE: {key} must be a finite number")
    if checks["duration_delta_ms"] < 0 or checks["roundtrip_duration_delta_ms"] < 0:
        raise Refused("E_RESAMPLE_CHECK_VALUE: duration differences cannot be negative")
    if not isinstance(checks["delay_samples"], int):
        raise Refused("E_RESAMPLE_CHECK_VALUE: delay_samples must be an integer")
    if checks["duration_delta_ms"] > THRESHOLDS["duration_delta_ms_max"] or checks["roundtrip_duration_delta_ms"] > THRESHOLDS["duration_delta_ms_max"]:
        raise Refused(f"E_RESAMPLE_DURATION: delta {checks['duration_delta_ms']:.9f} ms; roundtrip {checks['roundtrip_duration_delta_ms']:.9f} ms; max 1 ms")
    if checks["channels_identical"] is not True:
        raise Refused("E_RESAMPLE_CHANNELS: derived stereo channels differ")
    if checks["correlation"] < THRESHOLDS["correlation_min"]:
        raise Refused(f"E_RESAMPLE_CORRELATION: {checks['correlation']:.12f} < {THRESHOLDS['correlation_min']}")
    if checks["residual_db"] > THRESHOLDS["residual_db_max"]:
        raise Refused(f"E_RESAMPLE_NULL: {checks['residual_db']:.9f} dB > {THRESHOLDS['residual_db_max']} dB")
    if abs(checks["delay_samples"]) >= THRESHOLDS["delay_search_samples"]:
        raise Refused("E_RESAMPLE_DELAY_BOUNDARY: best delay touches search boundary")


def _command(ffmpeg: str, source: Path, target: Path, audio_filter: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(source),
            "-map", "0:a:0", "-map_metadata", "-1", "-af", audio_filter,
            "-c:a", "pcm_s16le", str(target)]


def convert(ffmpeg: str, source: Path, destination: Path) -> dict:
    """Convert explicitly, enforce numerical fidelity, then publish write-once.

    Temporary conversion and roundtrip WAVs live only under destination.parent.
    A failed check publishes no destination. An identical existing destination
    is idempotent; different bytes are refused. Receipt commands contain actual
    deterministic temporary paths, because those are the commands executed.
    An exclusive mkdir owns the work directory; an existing directory is refused
    as busy/stale and is never deleted by a second invocation.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise Refused("E_RESAMPLE_DESTINATION: source and destination must differ")
    try:
        source_sha = sha256_file(source)
    except OSError as error:
        raise Uncertain(f"E_RESAMPLE_SOURCE: cannot hash source: {error}") from error
    original = _read(source)
    if (original.rate, original.channels, original.sample_width) != (24000, 1, 2) or original.frames <= 0:
        raise Refused("E_RESAMPLE_SOURCE_FORMAT: expected nonempty 24000 Hz mono PCM16")
    if sha256_file(source) != source_sha:
        raise Refused("E_RESAMPLE_SOURCE_CHANGED: source bytes changed while reading")
    version_lines = _run([ffmpeg, "-version"]).stdout.splitlines()
    if not version_lines:
        raise Uncertain("E_RESAMPLE_CONVERTER_VERSION: ffmpeg -version produced no first line")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".voice-resample-{destination.name}.work"
    try:
        temporary.mkdir()
    except FileExistsError as error:
        raise Refused(f"E_RESAMPLE_BUSY: work directory exists (busy or stale): {temporary}") from error
    converted = temporary / "derived.wav"
    roundtrip = temporary / "roundtrip.wav"
    try:
        command = _command(ffmpeg, source, converted, CONVERSION_FILTER)
        _run(command)
        derived = _read(converted)
        reverse_command = _command(ffmpeg, converted, roundtrip, ROUNDTRIP_FILTER)
        _run(reverse_command)
        back = _read(roundtrip)
        checks = measure_checks(original, derived, back)
        require_checks(checks)
        if sha256_file(source) != source_sha:
            raise Refused("E_RESAMPLE_SOURCE_CHANGED: source bytes changed during conversion")
        try:
            derived_sha = write_once(destination, converted.read_bytes())
        except Refused as error:
            raise Refused(f"E_RESAMPLE_OUTPUT_EXISTS: {error}") from error
    finally:
        converted.unlink(missing_ok=True)
        roundtrip.unlink(missing_ok=True)
        temporary.rmdir()
    return {"schema": SCHEMA_ID, "source_sha256": source_sha, "derived_sha256": derived_sha,
            "converter_command": command, "converter_command_line": subprocess.list2cmdline(command),
            "converter_version": version_lines[0], "source_format": _format(original),
            "derived_format": _format(derived), "source_duration_s": original.duration_s,
            "derived_duration_s": derived.duration_s,
            "processing": {"resampler": "soxr", "precision": 28, "quality": "VHQ",
                           "channel_mapping": "duplicate mono to stereo: c0=c0, c1=c0",
                           "dither_method": "default 0 (none); option omitted",
                           "gain": "none", "normalization": "none", "trim": "none"},
            "roundtrip_command": reverse_command, "roundtrip_command_line": subprocess.list2cmdline(reverse_command),
            "checks": checks}
