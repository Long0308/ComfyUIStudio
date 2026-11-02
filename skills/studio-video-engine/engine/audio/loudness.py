"""Loudness measurement through ffmpeg ``ebur128`` (EBU R128 / BS.1770): integrated LUFS and true peak.

PCM16 is piped to ffmpeg on stdin (no temp files).  A section shorter than one gating block cannot be
measured (``integrated`` is -inf): it is reported as ``measurable: false`` and never invented.
"""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..core.errors import Uncertain

Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]
_INTEGRATED = re.compile(r"Integrated loudness:\s*\n\s*I:\s+(-?\d+(?:\.\d+)?|-inf)\s+LUFS")
ABSOLUTE_GATE_LUFS = -70.0
_PEAK = re.compile(r"True peak:\s*\n\s*Peak:\s+(-?\d+(?:\.\d+)?|-inf)\s+dBFS")


@dataclass(frozen=True)
class Loudness:
    duration_s: float
    integrated_lufs: float | None
    true_peak_dbtp: float | None

    @property
    def measurable(self) -> bool:
        # ebur128 reports its -70 LUFS absolute-gate floor for silence and for audio shorter than a block
        return self.integrated_lufs is not None and self.integrated_lufs > ABSOLUTE_GATE_LUFS + 0.05

    def as_dict(self) -> dict:
        return {"duration_s": round(self.duration_s, 6), "integrated_lufs": self.integrated_lufs,
                "true_peak_dbtp": self.true_peak_dbtp, "measurable": self.measurable}


def _number(text: str | None) -> float | None:
    if text is None or text == "-inf":
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def parse_summary(stderr: str, duration_s: float) -> Loudness:
    integrated, peak = _INTEGRATED.findall(stderr), _PEAK.findall(stderr)
    if not integrated or not peak:
        raise Uncertain("ffmpeg ebur128 produced no summary (is the ebur128 filter available?)",
                        evidence={"stderr_tail": stderr[-300:]})
    return Loudness(duration_s, _number(integrated[-1]), _number(peak[-1]))


def measure(pcm: np.ndarray, rate: int, ffmpeg: str, *, runner: Runner = subprocess.run) -> Loudness:
    """``pcm``: int16 (n, 2).  Returns integrated LUFS (None when below one gating block) and true peak."""
    data = np.ascontiguousarray(pcm.astype("<i2")).tobytes()
    command = [ffmpeg, "-hide_banner", "-nostats", "-nostdin", "-f", "s16le", "-ar", str(rate),
               "-ac", str(pcm.shape[1]), "-i", "pipe:0", "-af", "ebur128=peak=true:framelog=quiet",
               "-f", "null", "-"]
    try:
        done = runner(command, input=data, capture_output=True, timeout=900, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run ffmpeg for loudness: {error}") from error
    stderr = done.stderr.decode("utf-8", "replace") if isinstance(done.stderr, bytes) else str(done.stderr)
    if done.returncode != 0:
        raise Uncertain(f"ffmpeg ebur128 failed ({done.returncode}): {stderr[-300:]}")
    return parse_summary(stderr, pcm.shape[0] / rate)
