"""Shared fakes of the music-library tests: a throw-away library, fake separators, a fake Demucs (no GPU, no Demucs)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from audio_fixtures import RATE, tone, wav_bytes, write_tone

from engine.audio import library, vocalgate, vocalstrip
from engine.core.io import read_json
from engine.voice.wavio import read_wav

SKILL = Path(__file__).resolve().parents[1]
PICK_RECIPE = SKILL / "recipes" / "audio" / "music-pick-v001.json"
SCHEMA = read_json(PICK_RECIPE)["library"]["registry_schema"]
GOOD_GATE = {"vocal_minus_bed_rms_db": -50.0, "vocal_minus_bed_lufs_db": -46.0, "vocal_rms_dbfs": -64.0,
             "windows_over_-40dBFS": 0, "rule": "v2", "pass": True}
BRIEF = {"bpm": 100.0, "key": "C major", "instruments": "ukulele, glockenspiel, soft piano, light hand percussion"}
EVIDENCE = {"overall_energy": "gentle"}


def bed_row(bed_id: str, description: str, seconds: float, freq: float, root: Path, *, used_in=(), status="approved_vocal_free",
            gate: dict | None = None, write: bool = True, amplitude: float = 0.2, brief: dict | None = None) -> dict:
    name = f"{bed_id}-bed-48k.wav"
    sha = write_tone(root / library.BEDS_DIR / name, seconds, amplitude, freq) if write else "0" * 64
    row = {"id": bed_id, "file": name, "sha256": sha, "duration_s": seconds, "generator": "acestep", "take": bed_id,
           "description_vi": description, "loudness": {"integrated_lufs": -20.0, "true_peak_dbfs": -12.0},
           "vocal_gate": dict(gate or GOOD_GATE), "domain": "jenniejoy_cartoon_3d", "used_in": [dict(u) for u in used_in],
           "status": status}
    if brief:
        row["brief"] = brief
    return row


def make_library(tmp_path: Path, rows: list[dict]) -> Path:
    root = tmp_path / "lib"
    (root / library.BEDS_DIR).mkdir(parents=True, exist_ok=True)
    document = {"schema": SCHEMA, "updated": "2026-10-27", "beds": rows}
    (root / library.BEDS_DIR / library.REGISTRY_FILE).write_text(json.dumps(document, indent=1), encoding="utf-8")
    return root


def standard_rows(root: Path) -> list[dict]:
    """The brief's own palette, a guitar/marimba bed, a lullaby bed, and one that is too short."""
    return [
        bed_row("B-PASTORAL", "ukulele, glockenspiel and soft piano with hand percussion, 100 BPM C major", 30.0, 262.0, root),
        bed_row("B-GUITAR", "nylon guitar and marimba, 108 BPM F major", 30.0, 330.0, root),
        bed_row("B-LULLABY", "music box and celesta, soft felt piano, 90 BPM G major", 30.0, 392.0, root),
        bed_row("B-SHORT", "ukulele, glockenspiel and soft piano with hand percussion, 100 BPM C major", 9.0, 440.0, root),
    ]


def registry_bytes(lib: Path) -> bytes:
    return library.registry_path(lib).read_bytes()


def separator(vocal_amplitude_for):
    """A vocal-gate runner: leaves ``vocals.wav`` (a tone whose level comes from ``vocal_amplitude_for(input path)``)."""
    calls: list[str] = []

    def runner(argv, **kwargs):
        source = Path(argv[argv.index("--in") + 1])
        out_dir = Path(argv[argv.index("--out") + 1])
        calls.append(str(source))
        amplitude = vocal_amplitude_for(source)
        seconds = read_wav(source).duration_s
        data = tone(seconds, amplitude, 880.0) if amplitude else np.zeros((int(seconds * RATE), 2))
        (out_dir / "vocals.wav").write_bytes(wav_bytes(data))
        return subprocess.CompletedProcess(argv, 0, "", "")
    runner.calls = calls
    return runner


def gate() -> vocalgate.VocalGate:
    return vocalgate.VocalGate(("separate", "--in", "{input}", "--out", "{out_dir}"), "vocals.wav", -35.0, 5.0, "test",
                               -40.0, "v2")


def demucs(vocal_from_s: float = 0.0, *, rate: int = RATE, code: int = 0, amplitude: float = 0.1):
    """A fake Demucs: vocals = a tone from ``vocal_from_s`` on, no_vocals = input - vocals (exact), written at ``rate``."""
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        if "demucs" not in argv:
            return subprocess.run(argv, **kwargs)  # the real ffmpeg resample (only when rate != the bed's)
        if code:
            return subprocess.CompletedProcess(argv, code, "", "boom")
        scratch, source = Path(argv[argv.index("-o") + 1]), Path(argv[-1])
        data = read_wav(source)
        pcm = np.frombuffer(data.pcm, dtype="<i2").reshape(-1, data.channels).astype(np.float64) / 32768.0
        voc = np.zeros_like(pcm)
        start = int(vocal_from_s * data.rate)
        voc[start:] = tone(len(pcm) / data.rate, amplitude, 880.0, data.rate)[: len(pcm) - start]
        folder = scratch / "htdemucs" / source.stem
        folder.mkdir(parents=True, exist_ok=True)
        clean = pcm - voc
        if rate != data.rate:  # Demucs works at 44.1 kHz whatever the input rate was: same seconds, other sample count
            grid = np.linspace(0, len(pcm) - 1, int(len(pcm) / data.rate * rate))
            voc, clean = (np.stack([np.interp(grid, np.arange(len(x)), x[:, c]) for c in range(2)], axis=1) for x in (voc, clean))
        (folder / "vocals.wav").write_bytes(wav_bytes(voc, rate))
        (folder / "no_vocals.wav").write_bytes(wav_bytes(clean, rate))
        return subprocess.CompletedProcess(argv, 0, "", "")
    runner.calls = calls
    return runner


def strip_settings(ffmpeg: str = "ffmpeg") -> vocalstrip.StripSettings:
    return vocalstrip.StripSettings("python-demucs", "htdemucs", "cpu", 60.0, ffmpeg)
