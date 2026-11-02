"""Vocal separator wrapper for the music vocal-free gate (``machine.audio.vocal_gate.command``).

``python demucs_vocal_gate.py INPUT.wav OUT_DIR`` runs ``demucs -n htdemucs --two-stems vocals`` on the CPU,
and leaves exactly one ``OUT_DIR/vocals.wav`` (16-bit PCM at the INPUT's sample rate, which is what
``engine/audio/vocalgate.py`` reads).  Demucs works in a scratch folder next to OUT_DIR, never inside it,
so the gate's "exactly one vocals.wav below out_dir" check holds.  Run it with the interpreter of the
Demucs venv (``production-local/engine/tools/demucs-venv``); the machine config names both.

Exit codes: 0 vocals.wav written; 2 bad usage or missing input; 3 demucs or the resampler failed.
Options: ``--device`` (default ``cpu`` or $JJV_DEMUCS_DEVICE), ``--model`` (default htdemucs),
``--demucs-cmd`` (JSON argv prefix replacing ``python -m demucs``; tests use it), ``--ffmpeg``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def _rate(path: Path) -> int:
    """Sample rate from the RIFF fmt chunk."""
    with path.open("rb") as stream:
        if stream.read(12)[8:12] != b"WAVE":
            raise ValueError(f"{path} is not a RIFF/WAVE file")
        while True:
            head = stream.read(8)
            if len(head) < 8:
                raise ValueError(f"{path} has no fmt chunk")
            size = struct.unpack("<I", head[4:])[0]
            if head[:4] == b"fmt ":
                return struct.unpack("<I", stream.read(size + (size & 1))[4:8])[0]
            stream.seek(size + (size & 1), 1)


def _find_vocals(scratch: Path) -> Path:
    found = sorted(scratch.rglob("vocals.wav"))
    if len(found) != 1:
        raise RuntimeError(f"demucs left {len(found)} vocals.wav files under {scratch}")
    return found[0]


def separate(source: Path, out_dir: Path, *, device: str, model: str, demucs_cmd: list[str], ffmpeg: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "vocals.wav"
    with tempfile.TemporaryDirectory(prefix="demucs-", dir=out_dir.parent) as scratch_name:
        scratch = Path(scratch_name)
        command = [*demucs_cmd, "-n", model, "--two-stems", "vocals", "-d", device, "-o", str(scratch), str(source)]
        done = subprocess.run(command, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"demucs exited {done.returncode}: {(done.stderr or '')[-400:]}")
        stem = _find_vocals(scratch)
        want = _rate(source)
        if _rate(stem) == want:
            shutil.copyfile(stem, target)
        else:
            convert = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(stem), "-ar", str(want), "-c:a", "pcm_s16le",
                                      str(target)], capture_output=True, text=True, check=False)
            if convert.returncode != 0:
                raise RuntimeError(f"ffmpeg resample to {want} Hz failed: {(convert.stderr or '')[-300:]}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input")
    parser.add_argument("out_dir")
    parser.add_argument("--device", default=os.environ.get("JJV_DEMUCS_DEVICE", "cpu"))
    parser.add_argument("--model", default="htdemucs")
    parser.add_argument("--demucs-cmd", default=None, help="JSON argv prefix; default [python, -m, demucs]")
    parser.add_argument("--ffmpeg", default=os.environ.get("JJV_FFMPEG", "ffmpeg"))
    args = parser.parse_args(argv)
    source = Path(args.input)
    if not source.is_file():
        print(f"input not found: {source}", file=sys.stderr)
        return 2
    cmd = json.loads(args.demucs_cmd) if args.demucs_cmd else [sys.executable, "-m", "demucs"]
    try:
        target = separate(source, Path(args.out_dir), device=args.device, model=args.model, demucs_cmd=cmd,
                          ffmpeg=args.ffmpeg)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"vocal separation failed: {error}", file=sys.stderr)
        return 3
    print(str(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
