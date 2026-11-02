"""WAV loading and the windowed RMS measure shared by every timing rule (numpy, no ffmpeg).

The arithmetic is the one of the verified hand-run tools: PCM16 -> float64 / 32768, stereo mean,
RMS of ``[round(t*sr), round((t+win)*sr))``, ``20*log10(rms + 1e-12)`` (an empty window is -120 dBFS).
"""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..core.errors import Refused, Uncertain

EMPTY_DB = -120.0


@dataclass(frozen=True)
class Sound:
    """Mono float64 samples (-1..1) and the sample rate of one WAV."""

    samples: np.ndarray
    rate: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.rate


def frame_of(seconds: float, fps: float) -> int:
    """Frame index of a time: ``floor(s * fps + 0.5)`` (the rule every word-timing document uses)."""
    return int(math.floor(seconds * fps + 0.5))


def load_sound(path: Path) -> Sound:
    """Read a PCM16 WAV as mono; an unreadable file is Uncertain, a non-PCM16 one Refused."""
    try:
        with wave.open(str(path), "rb") as handle:
            rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
            raw = handle.readframes(handle.getnframes())
    except (OSError, wave.Error, EOFError) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error
    if width != 2:
        raise Refused(f"{path}: expected PCM16, sample width is {width} bytes")
    values = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    return Sound(values.reshape(-1, channels).mean(1) if channels > 1 else values, rate)


def rms_db(sound: Sound, t0: float, win: float) -> float:
    """RMS level in dBFS of the window starting at ``t0`` seconds."""
    first, last = int(round(t0 * sound.rate)), int(round((t0 + win) * sound.rate))
    segment = sound.samples[first:last]
    if len(segment) == 0:
        return EMPTY_DB
    return float(20 * np.log10(np.sqrt((segment ** 2).mean()) + 1e-12))
