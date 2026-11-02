"""Vocal-free gate of a music bed: an external source separator (Demucs-style) splits the bed, the VOCAL stem
must sit at or below ``limit_db`` relative to the bed (standard -35 dB; a recipe may only tighten it).

Rule ``v2`` (what ``resolve`` builds, as the audio lane's ``vocal_gate.py`` after its sparse-stem finding): the whole-region
RMS of the vocal stem relative to the bed's RMS <= ``limit_db`` AND no 1 s window of the vocal stem above
``window_limit_dbfs`` RMS; the LUFS figures stay in the result as information only (integrated loudness gates out silence, so
a vocal stem that is 99 % silent reports the loudness of its 1 %).  Rule ``v1`` (a ``VocalGate`` built by hand keeps it): the
relative figure is LUFS when ffmpeg is given.

The separator is not engine code: it is a command from the machine config (``machine.audio.vocal_gate.command``,
an argv list with ``{input}`` and ``{out_dir}`` placeholders) or ``--vocal-gate-command`` (a JSON argv list).  It
must leave a PCM16 WAV named ``vocals_file`` (searched below ``out_dir``) at the bed's sample rate.  The result,
numbers included, goes into the receipt; no configured command is ``NOT_RUN`` (never a silent pass), a command
that fails or leaves nothing usable is ``ERROR``.  ``jjv audio mix`` refuses a music receipt that is not ``PASS``.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..core.errors import Refused
from ..core.io import sha256_file
from ..voice.wavio import read_wav
from . import dsp, loudness

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class VocalGate:
    command: tuple[str, ...]
    vocals_file: str
    limit_db: float
    timeout_s: float
    source: str
    window_limit_dbfs: float = -40.0
    rule: str = "v1"


def parse_command(value: object, label: str) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as error:
            raise Refused(f"{label} must be a JSON list of strings: {error}") from error
    if not isinstance(value, (list, tuple)) or not value or not all(isinstance(x, str) and x for x in value):
        raise Refused(f"{label} must be a non-empty list of strings")
    if not any("{input}" in part for part in value):
        raise Refused(f"{label} must contain the {{input}} placeholder")
    return tuple(value)


def resolve(machine: dict, recipe_gate: dict, cli_command: str | None) -> VocalGate | None:
    """CLI command > ``machine.audio.vocal_gate.command``; None when neither exists (the gate is NOT_RUN)."""
    configured = ((machine.get("audio") or {}).get("vocal_gate") or {}) if isinstance(machine, dict) else {}
    if cli_command:
        command, source = parse_command(cli_command, "--vocal-gate-command"), "cli"
    elif configured.get("command"):
        command, source = parse_command(configured["command"], "machine.audio.vocal_gate.command"), "machine.audio.vocal_gate"
    else:
        return None
    return VocalGate(command, recipe_gate["vocals_file"], float(recipe_gate["limit_db"]),
                     float(recipe_gate.get("timeout_s", 3600.0)), source, float(recipe_gate.get("window_limit_dbfs", -40.0)),
                     rule=str(recipe_gate.get("rule", "v2")))


def not_run(reason: str, limit_db: float) -> dict:
    return {"status": "NOT_RUN", "reason": reason, "limit_db": limit_db}


def _error(gate: VocalGate, why: str, **extra: object) -> dict:
    return {"status": "ERROR", "reason": why, "limit_db": gate.limit_db, "source": gate.source, **extra}


def window_levels_dbfs(wav, rate: int) -> list[float]:
    """RMS (dBFS) of every whole 1 s window of a WAV (one window when it is shorter than a second)."""
    pcm = np.frombuffer(wav.pcm, dtype="<i2").astype(np.float32) / 32768.0
    size = rate
    count = max(1, pcm.shape[0] // size)
    return [dsp.rms_dbfs(pcm[i * size:(i + 1) * size]) for i in range(count)]


def _windows_peak_dbfs(wav, rate: int) -> float:
    return max(window_levels_dbfs(wav, rate))


def run(gate: VocalGate, bed: Path, out_dir: Path, runner: Runner = subprocess.run, ffmpeg: str | None = None) -> dict:
    """Separate ``bed`` into ``out_dir`` and measure the vocal stem against it."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [part.format(input=str(bed), out_dir=str(out_dir)) for part in gate.command]
    try:
        done = runner(argv, capture_output=True, text=True, timeout=gate.timeout_s, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return _error(gate, f"separator could not run: {error!r}", command=argv)
    tail = (done.stderr or "")[-300:]
    if done.returncode != 0:
        return _error(gate, f"separator exited {done.returncode}", command=argv, stderr_tail=tail)
    found = sorted(out_dir.rglob(gate.vocals_file))
    if len(found) != 1:
        return _error(gate, f"expected exactly one {gate.vocals_file} below {out_dir}, found {len(found)}", command=argv)
    try:
        bed_wav, vocals = read_wav(Path(bed)), read_wav(found[0])
    except Exception as error:  # noqa: BLE001 - an unreadable stem is an ERROR row, not a crash
        return _error(gate, f"cannot read the stems: {error}", command=argv)
    if vocals.rate != bed_wav.rate:
        return _error(gate, f"vocal stem {vocals.rate} Hz differs from the bed {bed_wav.rate} Hz", command=argv)

    def level(wav) -> float:
        return dsp.rms_dbfs(np.frombuffer(wav.pcm, dtype="<i2").astype(np.float32) / 32768.0)

    bed_db, vocal_db = level(bed_wav), level(vocals)
    relative, metric = round(vocal_db - bed_db, 3), "rms"
    lufs: dict = {}
    if ffmpeg:
        pair = [loudness.measure(np.frombuffer(w.pcm, dtype="<i2").reshape(-1, w.channels), w.rate, ffmpeg)
                for w in (bed_wav, vocals)]
        lufs = {"bed_lufs": pair[0].integrated_lufs, "vocals_lufs": pair[1].integrated_lufs}
        floor = loudness.ABSOLUTE_GATE_LUFS
        lufs_relative = round((pair[1].integrated_lufs if pair[1].measurable else floor) - (pair[0].integrated_lufs or floor), 3)
        if gate.rule == "v2":
            lufs["vocals_relative_lufs_db"] = lufs_relative  # information only under rule v2
        else:
            relative, metric = lufs_relative, "lufs"
    levels = window_levels_dbfs(vocals, vocals.rate)
    worst_window = round(max(levels), 3)
    over = sum(1 for level in levels if level > gate.window_limit_dbfs)
    passed = relative <= gate.limit_db and worst_window <= gate.window_limit_dbfs
    return {"status": "PASS" if passed else "FAIL", "limit_db": gate.limit_db, "source": gate.source, "metric": metric,
            "rule": gate.rule, "windows_over_limit": over,
            "window_limit_dbfs": gate.window_limit_dbfs, "vocals_worst_1s_window_dbfs": worst_window, **lufs,
            "command": argv, "bed_rms_dbfs": bed_db, "vocals_rms_dbfs": vocal_db, "vocals_relative_db": relative,
            "vocals": {"path": found[0].relative_to(out_dir).as_posix(), "sha256": sha256_file(found[0])},
            "stderr_tail": tail}
