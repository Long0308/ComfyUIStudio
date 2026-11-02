"""Helpers for the qa av tests: synthetic audio, a fake ffmpeg runner, a small world, real-mp4 export."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from engine.core.io import sha256_file  # noqa: E402
from engine.qa import av  # noqa: E402

SR = av.SAMPLE_RATE
FPS = 30.0
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def _noise(seconds: float, seed: int, level: float = 0.3):
    return (np.random.default_rng(seed).standard_normal(int(seconds * SR)) * level).astype(np.float32)


def _mix_with(wav, at_sample: int, total_s: float = 6.0, seed: int = 99):
    mix = _noise(total_s, seed, 0.01)
    mix[at_sample:at_sample + len(wav)] += wav
    return mix


class FakeFfmpeg:
    """A runner that 'decodes' registered paths to prepared float32 arrays."""

    def __init__(self, table: dict) -> None:
        self.table = {str(Path(key).resolve()): value for key, value in table.items()}

    def __call__(self, command, capture_output=True, check=False):
        path = str(Path(command[command.index("-i") + 1]).resolve())
        if path not in self.table:
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"no such file")
        return SimpleNamespace(returncode=0, stdout=self.table[path].astype("<f4").tobytes(), stderr=b"")


def _write_wav(path: Path, samples) -> str:
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SR)
        stream.writeframes(data.tobytes())
    return sha256_file(path)



P = av.AvParams(tolerance_ms=av.default_tolerance_ms(FPS))



def _world(tmp_path: Path, lag_samples: int = 0, *, bound_sha: str | None = None):
    wav = _noise(1.0, 11)
    wav_path = tmp_path / "audio" / "a.wav"
    wav_path.parent.mkdir()
    sha = _write_wav(wav_path, wav)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    start = int(round(60 / FPS * SR)) + lag_samples
    runner = FakeFfmpeg({video: _mix_with(wav, start), wav_path: wav})
    config = {"fps": 30, "wav_bindings": [{"name": "dlg A", "path": "audio/a.wav",
                                            "sha256": bound_sha or sha, "start_frame": 60}]}
    return video, config, runner


def _run(tmp_path: Path, config: dict, video: Path, runner, **kwargs) -> dict:
    return av.run_av(video=video, config=config, config_sha256="c" * 64, episode_root=tmp_path, fps=30.0,
                     runner=runner, **kwargs)



def _jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli", Path(__file__).resolve().parents[1] / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_export(tmp_path: Path, name: str, wav, start_s: float) -> Path:
    mix = _mix_with(wav, int(start_s * SR), total_s=6.0, seed=7)
    source = tmp_path / f"{name}.wav"
    _write_wav(source, mix)
    out = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x48:r=30:d=6",
                    "-i", str(source), "-shortest", "-c:v", "mpeg4", "-c:a", "aac", "-b:a", "192k", str(out)],
                   check=True)
    return out


