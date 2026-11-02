"""The vocal step of a generated bed: when the vocal-free gate FAILs, deliver Demucs' ``no_vocals`` stem instead.

``separate_two_stems`` runs Demucs (``htdemucs --two-stems vocals``) with the interpreter of the Demucs venv and leaves
``vocals.wav`` and ``no_vocals.wav`` at the bed's sample rate (soxr resample when Demucs' 44.1 kHz differs).  The caller
(``musicpick_adopt``) then:

1. loop-extends ``no_vocals`` to the film length (``loopext``),
2. gates that final bed AGAIN with the configured separator (the same ``vocalgate`` rule, no shortcut),
3. measures the separation residue (``residue``): in the 1 s windows where the ORIGINAL take's vocal stem is quiet,
   how much energy ``original - no_vocals`` still holds (pure separation damage; the first lane: mean -32..-37 dB, worst -17 dB).

The command is data (``machine.audio.vocal_gate.command[0]`` is the Demucs venv interpreter; ``--demucs-python`` overrides);
the runner is injectable so the tests need no Demucs.  Port of the audio lane's ``residue_check.py`` (not edited).
"""

from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..core.errors import Refused
from ..core.io import sha256_file
from . import dsp

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
STEMS = ("vocals.wav", "no_vocals.wav")


@dataclass(frozen=True)
class StripSettings:
    python: str
    model: str
    device: str
    timeout_s: float
    ffmpeg: str


def settings_from(step: dict, python: str | None, gate_command: tuple[str, ...] | None, ffmpeg: str) -> StripSettings:
    """The Demucs interpreter: ``--demucs-python``, else the first word of the configured vocal-gate command."""
    chosen = python or (gate_command[0] if gate_command else None)
    if not chosen:
        raise Refused("no Demucs interpreter: set machine.audio.vocal_gate.command (its first word is the Demucs venv "
                      "python) or pass --demucs-python; without it a failed bed cannot be stripped")
    return StripSettings(chosen, step["strip_model"], step["strip_device"], float(step["strip_timeout_s"]), ffmpeg)


def demucs_argv(settings: StripSettings, scratch: Path, wav: Path) -> list[str]:
    return [settings.python, "-m", "demucs", "-n", settings.model, "--two-stems", "vocals", "-d", settings.device,
            "-o", str(scratch), str(wav)]


def read_pcm(path: Path) -> tuple[np.ndarray, int]:
    """``(float32 (n, channels), rate)`` of a PCM16 WAV."""
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getsampwidth() != 2:
                raise Refused(f"{path}: expected PCM16, got {handle.getsampwidth() * 8} bit")
            rate, channels = handle.getframerate(), handle.getnchannels()
            data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
    except (OSError, wave.Error, EOFError) as error:
        raise Refused(f"cannot read WAV {path}: {error}") from error
    return data.reshape(-1, channels).astype(np.float32) / 32768.0, rate


def _rate(path: Path) -> int:
    with wave.open(str(path), "rb") as handle:
        return handle.getframerate()


def _to_rate(settings: StripSettings, source: Path, target: Path, rate: int, runner: Runner) -> None:
    if _rate(source) == rate:
        target.write_bytes(source.read_bytes())
        return
    done = runner([settings.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(source),
                   "-af", "aresample=resampler=soxr:precision=28", "-ar", str(rate), "-c:a", "pcm_s16le", str(target)],
                  capture_output=True, text=True, timeout=900, check=False)
    if done.returncode != 0:
        raise Refused(f"ffmpeg resample to {rate} Hz failed: {(done.stderr or '')[-300:]}")


def separate_two_stems(wav: Path, out_dir: Path, settings: StripSettings, runner: Runner = subprocess.run) -> dict:
    """Run Demucs on ``wav``; ``out_dir/vocals.wav`` and ``out_dir/no_vocals.wav`` at ``wav``'s rate.  Raises ``Refused``
    when Demucs fails or does not leave exactly one of each stem (never a partial result)."""
    out_dir = Path(out_dir)
    scratch = out_dir / "demucs-work"
    scratch.mkdir(parents=True, exist_ok=True)
    argv = demucs_argv(settings, scratch, Path(wav))
    try:
        done = runner(argv, capture_output=True, text=True, timeout=settings.timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise Refused(f"Demucs could not run: {error!r}") from error
    if done.returncode != 0:
        raise Refused(f"Demucs exited {done.returncode}: {(done.stderr or '')[-300:]}")
    rate, found = _rate(Path(wav)), {}
    for name in STEMS:
        hits = sorted(scratch.rglob(name))
        if len(hits) != 1:
            raise Refused(f"Demucs left {len(hits)} {name} under {scratch}, expected exactly 1")
        target = out_dir / name
        _to_rate(settings, hits[0], target, rate, runner)
        found[name] = {"path": name, "sha256": sha256_file(target), "demucs_rate": _rate(hits[0])}
    return {"command": argv, "model": settings.model, "device": settings.device, "rate": rate, "stems": found}


def _window_db(block: np.ndarray) -> float:
    return dsp.rms_dbfs(block)


def residue(original: np.ndarray, no_vocals: np.ndarray, vocals: np.ndarray, rate: int, spec: dict) -> dict:
    """Separation residue per 1 s window (mono): ``rms(original - no_vocals) - rms(original)`` in dB, split by whether the
    original's vocal stem is quiet there.  Inputs are float (n, channels); lengths are trimmed to the shortest."""
    mono = [x.mean(axis=1) if x.ndim == 2 else x for x in (original, no_vocals, vocals)]
    count = min(len(m) for m in mono)
    orig, nov, voc = (m[:count] for m in mono)
    size = max(1, int(round(float(spec["residue_window_s"]) * rate)))
    free, voiced = [], []
    for start in range(0, count - size + 1, size):
        block = orig[start:start + size]
        if _window_db(block) < float(spec["silence_window_dbfs"]):
            continue
        row = {"t": round(start / rate, 2), "residue_db": round(_window_db(block - nov[start:start + size]) - _window_db(block), 1),
               "vocal_dbfs": round(_window_db(voc[start:start + size]), 1)}
        (free if row["vocal_dbfs"] < float(spec["residue_free_window_dbfs"]) else voiced).append(row)
    free_db = [w["residue_db"] for w in free]
    return {"windows_vocal_free": len(free), "windows_voiced": len(voiced),
            "residue_vocal_free_db": {"mean": round(float(np.mean(free_db)), 1) if free else None,
                                      "max": round(max(free_db), 1) if free else None, "windows": free[:40]},
            "residue_voiced_db_mean": round(float(np.mean([w["residue_db"] for w in voiced])), 1) if voiced else None,
            "note": "residue = energy of (original - no_vocals) relative to the original per 1 s window; in vocal-free "
                    "windows it is pure separation damage (0 dB = everything removed, -20 dB = 1 % of the energy)"}
