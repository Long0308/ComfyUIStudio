"""Synthetic CPU-only frame sequences for the staged expression gate."""

from __future__ import annotations

import importlib.util
import math
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[2] / "engine" / "qa" / "expression.py"
REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents
                 if (parent / ".agents/skills/studio-video-engine/engine/post/logo/video_io.py").is_file())
SKILL_ROOT = REPO_ROOT / ".agents" / "skills" / "studio-video-engine"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

spec = importlib.util.spec_from_file_location("engine.qa.expression_staged", MODULE_PATH)
assert spec and spec.loader
expression = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = expression
spec.loader.exec_module(expression)


class SyntheticFaceDetector:
    name = "synthetic_test_face_region"
    landmarks = False

    def detect(self, rgb: np.ndarray):
        mouth = rgb[70:92, 69:91]
        return expression.FaceObservation(
            box=(40, 10, 120, 110), eye_box=(54, 34, 106, 47),
            mouth_open=float(np.mean(mouth[:, :, 0] < 100)))


def _frames(moving: bool, count: int = 32) -> list[np.ndarray]:
    out = []
    for index in range(count):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[10:110, 40:120] = (155, 155, 155)
        frame[35:44, 56:75] = (230, 230, 230)
        frame[35:44, 85:104] = (230, 230, 230)
        if moving and index in (10, 11):
            frame[34:47, 54:106] = (75, 75, 75)
        mouth_height = 3 + (index % 4) * 3 if moving else 3
        frame[72:72 + mouth_height, 72:88] = (20, 20, 20)
        out.append(frame)
    if not moving:
        out = [out[0].copy() for _ in range(count)]
    return out


def _measure(name: str, frames: list[np.ndarray], *, wav: Path | None = None, detector=None):
    detector = detector or SyntheticFaceDetector()
    sampled = []
    for index, frame in enumerate(frames):
        rgb = np.ascontiguousarray(frame[..., ::-1])
        sampled.append((index / 8.0, rgb, detector.detect(rgb)))
    params, _ = expression._load_params(None)
    return expression._analyse_records(Path(name), SimpleNamespace(nb_frames=len(frames), fps=8.0),
                                       sampled, detector, wav, params)


def test_static_face_frames_fail_frozen_face() -> None:
    take = _measure("static-face.mp4", _frames(moving=False))
    assert take["checks"]["frozen_face"]["status"] == "FAIL"
    assert take["verdict"] == "FAIL"


def test_moving_face_frames_pass_and_sync_with_synthetic_audio() -> None:
    frames = _frames(moving=True)
    face = SyntheticFaceDetector()
    mouth_open = [face.detect(np.ascontiguousarray(frame[..., ::-1])).mouth_open for frame in frames]
    rate = 8000
    audio = np.zeros(rate * len(frames) // 8, dtype=np.float32)
    for index, value in enumerate(mouth_open):
        amplitude = 0.02 + 0.35 * float(value or 0.0)
        start = index * (rate // 8)
        offsets = np.arange(rate // 8, dtype=np.float32)
        audio[start:start + len(offsets)] = amplitude * np.sin(2 * math.pi * 440 * offsets / rate)
    original = expression._wav_samples
    expression._wav_samples = lambda _path: (audio, rate)
    try:
        take = _measure("moving-face.mp4", frames, wav=Path("synthetic.wav"))
    finally:
        expression._wav_samples = original
    assert take["checks"]["frozen_face"]["status"] == "PASS"
    assert take["checks"]["blink"]["count"] >= 1
    assert take["checks"]["mouth_audio"]["correlation"] is not None
    assert take["verdict"] == "PASS"


def test_unlocalized_static_proxy_warns_instead_of_failing_face_gate() -> None:
    class NoFaceDetector:
        name = "synthetic_no_face"
        landmarks = False

        def detect(self, rgb: np.ndarray):
            return None

    take = _measure("unlocalized.mp4", _frames(moving=False), detector=NoFaceDetector())
    assert take["checks"]["face_localization"]["status"] == "WARN"
    assert take["checks"]["frozen_face"]["status"] == "WARN"
    assert take["verdict"] == "WARN"


def test_partial_landmark_series_does_not_crash_audio_correlation() -> None:
    params, _ = expression._load_params(None)
    records = [{"time_s": index / 8.0,
                "mouth_open": (0.05 + (index % 4) * 0.03) if index % 2 else None}
               for index in range(24)]
    rate = 8000
    audio = np.zeros(rate * 3, dtype=np.float32)
    for index in range(24):
        start = index * (rate // 8)
        audio[start:start + rate // 8] = (0.04 + (index % 4) * 0.025) * np.sin(
            2 * math.pi * 440 * np.arange(rate // 8, dtype=np.float32) / rate)
    original = expression._wav_samples
    expression._wav_samples = lambda _path: (audio, rate)
    try:
        result = expression._audio_sync(records, [], [], Path("synthetic.wav"), params)
    finally:
        expression._wav_samples = original
    assert result["sample_count"] == 12
    assert result["correlation"] is not None


def test_nonfinite_threshold_is_rejected() -> None:
    from engine.core.errors import Refused

    params, _ = expression._load_params(None)
    bad = deepcopy(params)
    bad["frozen_face"]["energy_floor"] = float("nan")
    original = expression.read_json
    expression.read_json = lambda _path: bad
    try:
        try:
            expression._load_params(Path("bad-params.json"))
        except Refused:
            return
        raise AssertionError("non-finite threshold was accepted")
    finally:
        expression.read_json = original
