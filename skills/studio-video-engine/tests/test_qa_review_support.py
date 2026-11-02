"""Shared QA helpers: synthetic media, retained exports, and hash-bound regression clips.

Bundled negative controls never fall back to the deleted historical exports or skip when missing.
"""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from engine.qa import review_media as media  # noqa: E402
from engine.qa.review_recipe import load_recipe  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402

try:
    FFMPEG: str | None = find_ffmpeg()
    FFPROBE: str | None = media.find_ffprobe(FFMPEG)
except Exception:  # noqa: BLE001 - a machine without ffmpeg skips the media tests
    FFMPEG = FFPROBE = None
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg/ffprobe not available")

EP = Path(Path(__file__).resolve().parents[4], r"production-local\JennieJoyKids-Story\04-milk-and-mom\editorial")
needs_ep = pytest.mark.skipif(not (EP / "review-hd-v015").is_dir(), reason="real review exports not on this machine")
W, H, FPS = 320, 180, 30
RECIPE, RECIPE_SHA = load_recipe()
NEGATIVE_CONTROLS = Path(__file__).parent / "fixtures" / "ep04-negative-controls"
FIXTURE_VERSIONS = {"005", "012"}


def sha_of(path: Path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recipe() -> dict:
    import copy
    return copy.deepcopy(RECIPE)


def scene(seed: int, h: int = H, w: int = W) -> "np.ndarray":
    """A structured RGB picture (random rectangles on a mid-grey ground): a stand-in for a shot."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 120, dtype=np.uint8)
    for _ in range(14):
        y, x = int(rng.integers(0, h - 20)), int(rng.integers(0, w - 20))
        hh, ww = int(rng.integers(12, 60)), int(rng.integers(12, 80))
        img[y:y + hh, x:x + ww] = rng.integers(20, 235, 3)
    return img


def gray_of(frames: "np.ndarray") -> "np.ndarray":
    return frames.astype(np.float64).mean(axis=3).round().astype(np.uint8)


def write_video(path: Path, frames: "np.ndarray", fps: int = FPS) -> Path:
    n, h, w, _ = frames.shape
    result = subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
                             "-i", "-", "-c:v", "libx264", "-crf", "6", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                             str(path)], input=frames.tobytes(), capture_output=True)
    assert result.returncode == 0, result.stderr.decode()[:300]
    return path


def cut_clip(src: Path, dst: Path, first: int, count: int) -> Path:
    """``count`` frames of ``src`` starting at global frame ``first`` (re-encoded, picture only)."""
    if not Path(src).is_file():
        pytest.fail(f"required review source is missing: {src}")
    result = subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", f"{first / FPS:.6f}", "-i", str(src), "-frames:v", str(count),
                             "-an", "-c:v", "libx264", "-crf", "10", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dst)],
                            capture_output=True)
    assert result.returncode == 0, result.stderr.decode()[:300]
    assert media.probe(dst, FFPROBE).frames == count
    return dst


def _fixture_manifest() -> dict:
    path = NEGATIVE_CONTROLS / "MANIFEST.json"
    assert path.is_file(), f"required negative-control manifest is missing: {path}"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "jjv/ep04-negative-controls/v1"
    return manifest


def _fixture_file(binding: dict) -> Path:
    path = (NEGATIVE_CONTROLS / binding["file"]).resolve()
    assert path.is_relative_to(NEGATIVE_CONTROLS.resolve()), "fixture escapes its directory"
    assert path.is_file(), f"required negative-control file is missing: {path}"
    assert sha_of(path) == binding["sha256"], f"negative-control hash mismatch: {path}"
    return path


def review_clip(version: str, tmp_path: Path, first: int, count: int) -> Path:
    """Use the pinned fixture for retired versions; cut retained exports for other controls."""
    if version in FIXTURE_VERSIONS:
        rows = [r for r in _fixture_manifest()["clips"]
                if (r["version"], r["first_frame"], r["frame_count"]) == (version, first, count)]
        assert len(rows) == 1, f"expected one fixture for v{version} {first}+{count}"
        path = _fixture_file(rows[0])
        info = media.probe(path, FFPROBE)
        assert info.frames == count and float(info.fps) == FPS
        assert (info.width, info.height) == tuple(rows[0]["size"])
        return path
    return cut_clip(ep_video(version), tmp_path / f"v{version}-{first}.mp4", first, count)


def review_config_path(version: str) -> Path:
    if version in FIXTURE_VERSIONS:
        return _fixture_file(_fixture_manifest()["configs"][version])
    return EP / f"review-hd-v{version}" / "config" / f"review-config-v{version}.json"


def ep_config(version: str) -> dict:
    """The config as shipped (its absolute source paths name the retired ``D:`` root; the engine reads them where the
    tree lives now, ``machine.legacy_roots``)."""
    return json.loads(review_config_path(version).read_text(encoding="utf-8"))


def ep_video(version: str) -> Path:
    return EP / f"review-hd-v{version}" / f"milk-and-mom-REVIEW-1080p30-native-upscaled-v{version}.mp4"


def transition(boundary: int, kind: str, frames: int, *, start: int | None = None, end: int | None = None, **extra) -> dict:
    start = boundary if start is None else start
    return {"id": f"T{boundary}", "boundary": boundary, "type": kind, "frames": frames, "start": start,
            "end_exclusive": start + frames if end is None else end, "from": "S01_A", "to": "S01_B", **extra}


def make_config(transitions: list[dict], **extra) -> dict:
    config = {"fps": FPS, "width": W, "height": H, "main_frames": 600, "end_hold_frames": 0, "motion": {"transitions": transitions},
              "dialogue": [{"id": "S01_A", "start_frame": 0, "end_frame_exclusive": 300, "words": [], "segments": []},
                           {"id": "S01_B", "start_frame": 300, "end_frame_exclusive": 600, "words": [], "segments": []}],
              "outro_cards": []}
    config.update(extra)
    return config


def write_png_rgb(path: Path, rgb: tuple[int, int, int], size: int = 64) -> Path:
    media.write_png(path, np.full((size, size, 3), rgb, dtype=np.uint8), FFMPEG)
    return path


def write_wav(path: Path, parts: list[tuple[float, float]], rate: int = 48000, freq: float = 1000.0) -> Path:
    """Mono 16-bit sine; ``parts`` = [(seconds, peak amplitude)]."""
    chunks = []
    for seconds, amplitude in parts:
        t = np.arange(int(seconds * rate)) / rate
        chunks.append(amplitude * np.sin(2 * np.pi * freq * t))
    pcm = (np.concatenate(chunks) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return path
