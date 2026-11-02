"""Small stdlib WAV readers used by build-config (PCM only)."""

from __future__ import annotations

import array
import sys
import wave
from pathlib import Path

from ..core.errors import Uncertain

SILENT_PEAK_MAX = 1e-3  # a WAV whose peak is below this is silent (cannot be located by correlation)


def read_pcm(path: Path) -> tuple[tuple[int, int, int], bytes]:
    """((channels, sample width, rate), raw PCM bytes) of a WAV file."""
    try:
        with wave.open(str(path)) as stream:
            params = (stream.getnchannels(), stream.getsampwidth(), stream.getframerate())
            return params, stream.readframes(stream.getnframes())
    except (OSError, wave.Error, EOFError) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error


def peak(path: Path) -> float:
    """Largest absolute sample as a fraction of full scale (16-bit PCM only)."""
    params, data = read_pcm(path)
    if params[1] != 2:
        raise Uncertain(f"{path}: only 16-bit PCM WAV can be inspected, got {8 * params[1]}-bit")
    samples = array.array("h")
    samples.frombytes(data)
    if sys.byteorder == "big":
        samples.byteswap()
    return max((abs(value) for value in samples), default=0) / 32768


def is_silent(path: Path) -> bool:
    return peak(path) < SILENT_PEAK_MAX
