"""PCM16 WAV reading/writing, metrics and the two ffmpeg steps (resample, pitch transform).

Stdlib only (``wave``, ``array``, ``subprocess``).  Every written WAV goes through
``write_once``: an existing file must hold identical bytes.  The editorial format
(rate, channels) and the rubberband options come from the recipe, never from here.
"""

from __future__ import annotations

import array
import io
import math
import subprocess
import sys
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.io import write_once

RIFF_MIN_BYTES = 44


@dataclass(frozen=True)
class WavData:
    rate: int
    channels: int
    sample_width: int
    frames: int  # samples per channel
    pcm: bytes

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.sample_width

    @property
    def duration_s(self) -> float:
        return self.frames / self.rate

    def samples(self) -> array.array:
        values = array.array("h", self.pcm)
        if sys.byteorder != "little":
            values.byteswap()
        return values


def validate_riff(data: bytes, label: str = "WAV") -> None:
    if len(data) < RIFF_MIN_BYTES or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise Uncertain(f"{label}: not a RIFF/WAVE file")


def read_wav(path: Path) -> WavData:
    """Read a PCM16 WAV fully; an unreadable or non-PCM16 file is Uncertain."""
    try:
        with wave.open(str(path), "rb") as handle:
            data = WavData(handle.getframerate(), handle.getnchannels(), handle.getsampwidth(),
                           handle.getnframes(), handle.readframes(handle.getnframes()))
    except (OSError, wave.Error, EOFError) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error
    if data.sample_width != 2:
        raise Refused(f"{path}: expected PCM16, sample width is {data.sample_width} bytes")
    if len(data.pcm) != data.frames * data.frame_bytes:
        raise Uncertain(f"{path}: truncated PCM payload")
    return data


def wav_bytes(rate: int, channels: int, sample_width: int, pcm: bytes) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(sample_width)
        handle.setframerate(rate)
        handle.writeframes(pcm)
    return stream.getvalue()


def write_wav_once(path: Path, rate: int, channels: int, sample_width: int, pcm: bytes) -> str:
    """Write-once WAV; returns the file sha256 (identical existing bytes are accepted)."""
    return write_once(Path(path), wav_bytes(rate, channels, sample_width, pcm))


def metrics(data: WavData) -> dict:
    values = data.samples()
    peak = max((abs(v) for v in values), default=0)
    clipped = sum(1 for v in values if abs(v) >= 32767)
    peak_norm = peak / 32768.0
    return {
        "sample_rate": data.rate,
        "channels": data.channels,
        "sample_width_bytes": data.sample_width,
        "samples_per_channel": data.frames,
        "duration_s": data.duration_s,
        "peak": peak_norm,
        "peak_dbfs": round(20.0 * math.log10(peak_norm), 2) if peak_norm > 0 else -100.0,
        "clipped_samples": clipped,
    }


def ffmpeg_version(ffmpeg: str) -> str:
    try:
        completed = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run {ffmpeg}: {error}") from error
    first = (completed.stdout or "").splitlines()[:1]
    return first[0].strip() if first else "unknown"


def ffmpeg_has_filter(ffmpeg: str, name: str) -> bool:
    try:
        completed = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True,
                                   timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot list ffmpeg filters: {error}") from error
    return any(line.split()[1:2] == [name] for line in completed.stdout.splitlines() if line.strip())


def _run_ffmpeg_to_bytes(ffmpeg: str, source: Path, audio_filter: str, rate: int, channels: int) -> bytes:
    """Run one ffmpeg audio pass into a sibling temp WAV and return its bytes (temp removed)."""
    temporary = Path(source).parent / f".{Path(source).stem}.{uuid.uuid4().hex}.tmp.wav"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i", str(source),
               "-af", audio_filter, "-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le", str(temporary)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
        if completed.returncode != 0:
            raise Uncertain(f"ffmpeg failed ({completed.returncode}): {completed.stderr.strip()[:400]}")
        return temporary.read_bytes()
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"ffmpeg could not run: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def convert_to_editorial(ffmpeg: str, source: Path, destination: Path, *, rate: int, channels: int) -> str:
    """Real resample/channel conversion (filter ``anull``) to the editorial format; write-once."""
    payload = _run_ffmpeg_to_bytes(ffmpeg, source, "anull", rate, channels)
    validate_riff(payload, "ffmpeg output")
    return write_once(Path(destination), payload)


def pitch_factor(semitones: float) -> float:
    return 2 ** (semitones / 12)


def rubberband_filter(semitones: float, sample_count: int, transform: dict) -> str:
    """The exact filter chain of the first batch: pitch shift, pad, cut back to the base sample count."""
    return (f"rubberband=tempo=1:pitch={pitch_factor(semitones):.12f}:formant={transform['formant']}:"
            f"pitchq={transform['pitchq']}:channels={transform['channels']},apad,atrim=end_sample={sample_count}")


def pitch_shift(ffmpeg: str, source: Path, destination: Path, *, semitones: float, sample_count: int,
                rate: int, channels: int, transform: dict) -> str:
    """Pitch-shift with formants preserved and an identical sample count; write-once."""
    if transform.get("method") != "rubberband":
        raise Refused(f"unsupported transform method {transform.get('method')!r}")
    if not ffmpeg_has_filter(ffmpeg, "rubberband"):
        raise Uncertain("ffmpeg has no 'rubberband' filter; the pitch transform cannot run")
    payload = _run_ffmpeg_to_bytes(ffmpeg, source, rubberband_filter(semitones, sample_count, transform),
                                   rate, channels)
    validate_riff(payload, "ffmpeg output")
    return write_once(Path(destination), payload)
