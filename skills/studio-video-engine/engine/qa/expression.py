"""CPU-only, domain-neutral facial-expression checks for one video take.

This gate reports measurements, not a claim that a face is emotionally convincing.
Thresholds ship in ``expression-params-v001.json`` and are explicitly provisional.
Optional MediaPipe/OpenCV support is detected at runtime; no package is installed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from ..post.logo.video_io import iter_frames, probe
from ..qa.review_media import find_ffprobe
from ..seedvr2.seam_media import find_ffmpeg


SCHEMA = "jjv/qa-expression-receipt/v1"
PARAMS_PATH = Path(__file__).with_name("expression-params-v001.json")
_FACE_MESH_EYES = ((33, 160, 158, 133, 153, 144), (362, 385, 387, 263, 373, 380))
_FACE_MESH_EYE_BOXES = ((33, 133, 159, 145), (362, 263, 386, 374))


@dataclass(frozen=True)
class FaceObservation:
    """Coordinates and optional landmarks in the downscaled RGB frame."""

    box: tuple[int, int, int, int]
    eye_box: tuple[int, int, int, int] | None = None
    ear: float | None = None
    mouth_open: float | None = None


def _load_params(path: Path | None) -> tuple[dict[str, Any], Path]:
    source = path or PARAMS_PATH
    data = read_json(source)
    if not isinstance(data, dict) or data.get("schema") != "jjv/qa-expression-params/v1":
        raise Refused(f"invalid expression params file: {source}")
    required = {
        "analysis_fps": (0.1, 60.0), "max_analysis_side": (64, 4096),
        "frozen_face.energy_floor": (0.0, 1.0), "frozen_face.frozen_pair_fraction_fail": (0.0, 1.0),
        "frozen_face.minimum_pairs": (1, 100000), "blink.ear_closed_max": (0.0, 1.0),
        "blink.luminance_dip_fraction": (0.0, 1.0), "blink.min_blink_duration_s": (0.0, 10.0),
        "blink.max_blink_duration_s": (0.0, 10.0), "blink.minimum_observation_s": (0.0, 100000.0),
        "mouth_audio.rms_window_s": (0.0, 10.0), "mouth_audio.min_speech_rms": (0.0, 1.0),
        "mouth_audio.min_active_fraction": (0.0, 1.0), "mouth_audio.minimum_samples": (2, 100000),
        "mouth_audio.pass_at_or_above_correlation": (-1.0, 1.0),
        "mouth_audio.fail_below_correlation": (-1.0, 1.0),
    }
    for dotted, (minimum, maximum) in required.items():
        value: Any = data
        try:
            for key in dotted.split("."):
                value = value[key]
            if isinstance(value, bool):
                raise TypeError("boolean is not a numeric threshold")
            number = float(value)
        except (KeyError, TypeError, ValueError):
            raise Refused(f"missing or non-numeric expression param {dotted}: {source}") from None
        if not math.isfinite(number) or number < minimum or number > maximum:
            raise Refused(f"expression param {dotted} must be in [{minimum}, {maximum}]: {source}")
    if float(data["blink"]["min_blink_duration_s"]) > float(data["blink"]["max_blink_duration_s"]):
        raise Refused(f"expression blink duration limits are inverted: {source}")
    if float(data["mouth_audio"]["fail_below_correlation"]) >= float(data["mouth_audio"]["pass_at_or_above_correlation"]):
        raise Refused(f"expression mouth/audio correlation limits are inverted: {source}")
    return data, source


def _clip_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    x0 = max(0, min(width - 1, int(x0)))
    y0 = max(0, min(height - 1, int(y0)))
    x1 = max(x0 + 1, min(width, int(x1)))
    y1 = max(y0 + 1, min(height, int(y1)))
    return x0, y0, x1, y1


def _gray(rgb: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722),
                   0, 255).astype(np.uint8)


def _normalised_crop(gray: np.ndarray, box: tuple[int, int, int, int], size: int = 64) -> np.ndarray:
    x0, y0, x1, y1 = _clip_box(box, gray.shape[1], gray.shape[0])
    region = gray[y0:y1, x0:x1]
    if region.size == 0:
        return np.zeros((size, size), dtype=np.uint8)
    ys = np.linspace(0, region.shape[0] - 1, size).astype(np.intp)
    xs = np.linspace(0, region.shape[1] - 1, size).astype(np.intp)
    return region[ys[:, None], xs[None, :]]


def _change_energy(previous: np.ndarray, current: np.ndarray, region: tuple[slice, slice] | None = None) -> float:
    if region is not None:
        previous = previous[region]
        current = current[region]
    delta = current.astype(np.float32) - previous.astype(np.float32)
    # Remove a frame-wide exposure/codec offset; retain local facial changes.
    delta -= float(np.median(delta))
    return float(np.mean(np.abs(delta)) / 255.0)


def _ear(points: np.ndarray, indices: tuple[int, ...]) -> float:
    p = points[np.asarray(indices)]
    width = float(np.linalg.norm(p[0] - p[3]))
    if width <= 1e-8:
        return 0.0
    return float((np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])) / (2.0 * width))


def _face_box(points: np.ndarray, width: int, height: int) -> tuple[int, int, int, int]:
    return _clip_box((int(points[:, 0].min()), int(points[:, 1].min()),
                      int(points[:, 0].max()) + 1, int(points[:, 1].max()) + 1), width, height)


class _MediaPipeDetector:
    name = "mediapipe_face_mesh"
    landmarks = True

    def __init__(self, mp: Any) -> None:
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False, max_num_faces=1, refine_landmarks=True,
            min_detection_confidence=0.5, min_tracking_confidence=0.5)

    def detect(self, rgb: np.ndarray) -> FaceObservation | None:
        height, width = rgb.shape[:2]
        result = self._mesh.process(rgb)
        if not result.multi_face_landmarks:
            return None
        points = np.asarray([(item.x * width, item.y * height) for item in result.multi_face_landmarks[0].landmark],
                            dtype=np.float32)
        boxes = []
        for ids in _FACE_MESH_EYE_BOXES:
            eye_points = points[np.asarray(ids)]
            boxes.append((int(eye_points[:, 0].min()), int(eye_points[:, 1].min()),
                          int(eye_points[:, 0].max()) + 1, int(eye_points[:, 1].max()) + 1))
        eye_box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                   max(b[2] for b in boxes), max(b[3] for b in boxes))
        ear = float(np.mean([_ear(points, ids) for ids in _FACE_MESH_EYES]))
        mouth_width = float(np.linalg.norm(points[61] - points[291]))
        mouth_open = float(np.linalg.norm(points[13] - points[14]) / mouth_width) if mouth_width else None
        return FaceObservation(_face_box(points, width, height), _clip_box(eye_box, width, height), ear, mouth_open)

    def close(self) -> None:
        self._mesh.close()


class _OpenCvDetector:
    name = "opencv_haar_face_eye_regions"
    landmarks = False

    def __init__(self, cv2: Any) -> None:
        self._cv2 = cv2
        root = Path(cv2.data.haarcascades)
        self._faces = cv2.CascadeClassifier(str(root / "haarcascade_frontalface_default.xml"))
        self._eyes = cv2.CascadeClassifier(str(root / "haarcascade_eye_tree_eyeglasses.xml"))
        if self._faces.empty():
            raise RuntimeError("OpenCV face cascade is unavailable")

    def detect(self, rgb: np.ndarray) -> FaceObservation | None:
        cv2 = self._cv2
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        found = self._faces.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(28, 28))
        if len(found) == 0:
            return None
        x, y, width, height = max(found, key=lambda row: int(row[2]) * int(row[3]))
        upper_h = max(1, int(height * 0.62))
        eyes = self._eyes.detectMultiScale(gray[y:y + upper_h, x:x + width], scaleFactor=1.1,
                                           minNeighbors=3, minSize=(max(8, width // 9), max(6, height // 14)))
        if len(eyes) >= 1:
            selected = sorted(eyes, key=lambda row: int(row[2]) * int(row[3]))[-2:]
            eye_box = (x + min(int(row[0]) for row in selected), y + min(int(row[1]) for row in selected),
                       x + max(int(row[0] + row[2]) for row in selected),
                       y + max(int(row[1] + row[3]) for row in selected))
        else:
            eye_box = (x + int(width * 0.18), y + int(height * 0.20),
                       x + int(width * 0.82), y + int(height * 0.47))
        return FaceObservation(_clip_box((x, y, x + width, y + height), rgb.shape[1], rgb.shape[0]),
                               _clip_box(eye_box, rgb.shape[1], rgb.shape[0]))


class _CenterCropFallback:
    """Documented no-landmark fallback: a centered upper-frame face proxy."""

    name = "heuristic_center_face_proxy"
    landmarks = False

    def detect(self, rgb: np.ndarray) -> FaceObservation:
        height, width = rgb.shape[:2]
        box = _clip_box((int(width * 0.27), int(height * 0.08),
                         int(width * 0.73), int(height * 0.78)), width, height)
        x0, y0, x1, y1 = box
        eye_box = _clip_box((x0 + int((x1 - x0) * 0.17), y0 + int((y1 - y0) * 0.20),
                             x0 + int((x1 - x0) * 0.83), y0 + int((y1 - y0) * 0.45)), width, height)
        return FaceObservation(box, eye_box)


def _make_detector() -> Any:
    try:
        import mediapipe as mp  # type: ignore[import-not-found]  # optional
        if getattr(mp, "solutions", None) and getattr(mp.solutions, "face_mesh", None):
            return _MediaPipeDetector(mp)
    except (ImportError, AttributeError, RuntimeError, ValueError):
        pass
    try:
        import cv2  # type: ignore[import-not-found]  # optional
        return _OpenCvDetector(cv2)
    except (ImportError, AttributeError, RuntimeError, ValueError):
        return _CenterCropFallback()


def _count_runs(mask: list[bool], times: list[float], min_s: float, max_s: float) -> int:
    count = 0
    index = 0
    while index < len(mask):
        if not mask[index]:
            index += 1
            continue
        start = index
        while index + 1 < len(mask) and mask[index + 1]:
            index += 1
        end = index
        period = (times[-1] - times[0]) / max(1, len(times) - 1) if len(times) > 1 else 0.0
        duration = (times[end] - times[start]) + period
        surrounded = start > 0 and end + 1 < len(mask) and not mask[start - 1] and not mask[end + 1]
        if surrounded and min_s <= duration <= max_s:
            count += 1
        index += 1
    return count


def _blink_count(records: list[dict[str, Any]], params: dict[str, Any]) -> tuple[int, str]:
    blink = params["blink"]
    times = [float(row["time_s"]) for row in records]
    ears = [row["ear"] for row in records]
    if sum(value is not None for value in ears) >= 3:
        mask = [value is not None and float(value) <= float(blink["ear_closed_max"]) for value in ears]
        return _count_runs(mask, times, float(blink["min_blink_duration_s"]),
                           float(blink["max_blink_duration_s"])), "eye_aspect_ratio"
    luminance = np.asarray([row["eye_luminance"] for row in records if row["eye_luminance"] is not None],
                           dtype=np.float32)
    lum_times = [float(row["time_s"]) for row in records if row["eye_luminance"] is not None]
    if len(luminance) < 3:
        return 0, "unavailable"
    baseline = float(np.quantile(luminance, 0.75))
    if baseline <= 1e-6:
        return 0, "eye_region_luminance_dips"
    threshold = baseline * (1.0 - float(blink["luminance_dip_fraction"]))
    mask = [float(value) <= threshold for value in luminance]
    return _count_runs(mask, lum_times, float(blink["min_blink_duration_s"]),
                       float(blink["max_blink_duration_s"])), "eye_region_luminance_dips"


def _wav_samples(path: Path) -> tuple[np.ndarray, int]:
    try:
        with wave.open(str(path), "rb") as stream:
            channels = stream.getnchannels()
            rate = stream.getframerate()
            width = stream.getsampwidth()
            raw = stream.readframes(stream.getnframes())
    except (OSError, wave.Error) as error:
        raise Uncertain(f"cannot read WAV {path}: {error}") from error
    if channels < 1 or rate < 1:
        raise Refused(f"invalid WAV channel count/sample rate: {path}")
    if width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        bytes3 = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = bytes3[:, 0] | (bytes3[:, 1] << 8) | (bytes3[:, 2] << 16)
        values = (values ^ 0x800000) - 0x800000
        samples = values.astype(np.float32) / 8388608.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise Refused(f"unsupported WAV sample width {width * 8} bits: {path}")
    if samples.size % channels:
        raise Uncertain(f"incomplete interleaved WAV frame: {path}")
    mono = samples.reshape(-1, channels).mean(axis=1)
    return mono, rate


def _audio_rms_at(samples: np.ndarray, rate: int, times: Iterable[float], window_s: float) -> list[float]:
    radius = max(1, int(round(rate * window_s / 2.0)))
    out = []
    for time_s in times:
        center = int(round(float(time_s) * rate))
        start, end = max(0, center - radius), min(len(samples), center + radius)
        part = samples[start:end]
        out.append(float(np.sqrt(np.mean(part * part))) if part.size else 0.0)
    return out


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    a, b = np.asarray(left, dtype=np.float64), np.asarray(right, dtype=np.float64)
    if float(np.std(a)) <= 1e-10 or float(np.std(b)) <= 1e-10:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _audio_sync(records: list[dict[str, Any]], lower_motion: list[float], pair_times: list[float],
                wav: Path | None, params: dict[str, Any]) -> dict[str, Any]:
    if wav is None:
        return {"status": "SKIP", "reason": "no --wav supplied", "correlation": None,
                "sample_count": 0, "speech_active_fraction": None}
    samples, rate = _wav_samples(wav)
    mouth_landmarks = [row["mouth_open"] for row in records]
    if sum(value is not None for value in mouth_landmarks) >= 8:
        valid = [(float(row["time_s"]), float(row["mouth_open"])) for row in records
                 if row["mouth_open"] is not None]
        times = [item[0] for item in valid]
        mouth = [item[1] for item in valid]
        mouth_method = "landmark_mouth_open_ratio"
    else:
        times, mouth = pair_times, lower_motion
        mouth_method = "lower_face_frame_difference_proxy"
    audio = _audio_rms_at(samples, rate, times, float(params["mouth_audio"]["rms_window_s"]))
    enough = min(len(mouth), len(audio))
    mouth, audio = mouth[:enough], audio[:enough]
    correlation = _correlation(mouth, audio)
    cfg = params["mouth_audio"]
    active_fraction = float(np.mean(np.asarray(audio) >= float(cfg["min_speech_rms"]))) if audio else 0.0
    if len(audio) < int(cfg["minimum_samples"]) or active_fraction < float(cfg["min_active_fraction"]) or correlation is None:
        status, reason = "WARN", "insufficient speech/activity or mouth variation for a stable correlation"
    elif correlation <= float(cfg["fail_below_correlation"]):
        status, reason = "FAIL", "mouth/audio envelope correlation is below the proposed failure floor"
    elif correlation < float(cfg["pass_at_or_above_correlation"]):
        status, reason = "WARN", "mouth/audio envelope correlation is below the proposed pass floor"
    else:
        status, reason = "PASS", "mouth/audio envelope correlation meets the proposed floor"
    return {"status": status, "reason": reason,
            "correlation": round(correlation, 5) if correlation is not None else None,
            "sample_count": len(audio), "speech_active_fraction": round(active_fraction, 4),
            "mouth_signal": mouth_method, "rms_window_s": cfg["rms_window_s"]}


def _analyse_records(video: Path, info: Any, sampled: list[tuple[float, np.ndarray, FaceObservation | None]],
                     detector: Any, wav: Path | None, params: dict[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    crops: list[np.ndarray] = []
    previous_box: tuple[int, int, int, int] | None = None
    detected_count = 0
    for time_s, image, observation in sampled:
        gray = image if image.ndim == 2 else _gray(image)
        detected = observation is not None and getattr(detector, "name", "") != "heuristic_center_face_proxy"
        if observation is not None:
            box = observation.box
            previous_box = box
        elif previous_box is not None:
            box = previous_box
            observation = FaceObservation(box)
        else:
            observation = _CenterCropFallback().detect(image)
            box = observation.box
        detected_count += int(detected)
        face_crop = _normalised_crop(gray, box)
        crops.append(face_crop)
        eye_box = observation.eye_box
        if eye_box is None:
            x0, y0, x1, y1 = box
            eye_box = (x0 + int((x1 - x0) * 0.18), y0 + int((y1 - y0) * 0.18),
                       x0 + int((x1 - x0) * 0.82), y0 + int((y1 - y0) * 0.45))
        ex0, ey0, ex1, ey1 = _clip_box(eye_box, gray.shape[1], gray.shape[0])
        eye_luminance = float(np.mean(gray[ey0:ey1, ex0:ex1])) if ex1 > ex0 and ey1 > ey0 else None
        records.append({"time_s": time_s, "ear": observation.ear,
                        "mouth_open": observation.mouth_open, "eye_luminance": eye_luminance,
                        "face_detected": detected})

    face_cfg = params["frozen_face"]
    energies = [_change_energy(a, b) for a, b in zip(crops, crops[1:])]
    frozen_fraction = (sum(value <= float(face_cfg["energy_floor"]) for value in energies) / len(energies)
                       if energies else None)
    enough_pairs = len(energies) >= int(face_cfg["minimum_pairs"])
    frozen = enough_pairs and frozen_fraction is not None and frozen_fraction >= float(face_cfg["frozen_pair_fraction_fail"])
    face_detected_fraction = detected_count / len(sampled) if sampled else 0.0
    if face_detected_fraction < 0.5:
        frozen_status, frozen_reason = "WARN", "face not localized reliably; proxy-region motion cannot prove a frozen face"
    elif not enough_pairs:
        frozen_status, frozen_reason = "WARN", "too few sampled frame pairs"
    elif frozen:
        frozen_status, frozen_reason = "FAIL", "face-region difference energy is below the proposed floor for most samples"
    else:
        frozen_status, frozen_reason = "PASS", "face-region difference energy exceeds the proposed frozen floor"
    frozen_check = {"status": frozen_status, "reason": frozen_reason,
                    "mean_frame_difference_energy": round(float(np.mean(energies)), 6) if energies else None,
                    "median_frame_difference_energy": round(float(np.median(energies)), 6) if energies else None,
                    "frozen_pair_fraction": round(float(frozen_fraction), 4) if frozen_fraction is not None else None,
                    "pairs": len(energies), "energy_floor": face_cfg["energy_floor"]}

    blink_count, blink_method = _blink_count(records, params)
    duration_s = float(info.nb_frames / info.fps) if info.fps > 0 else 0.0
    blink_cfg = params["blink"]
    if blink_method == "unavailable":
        blink_status, blink_reason = "WARN", "eye signal unavailable"
    elif blink_count == 0:
        blink_status, blink_reason = "WARN", "no blink observed; absence is provisional and does not alone fail the take"
    else:
        blink_status, blink_reason = "PASS", "at least one blink was detected"
    blink_check = {"status": blink_status, "reason": blink_reason, "count": blink_count,
                   "per_minute": round(blink_count * 60.0 / duration_s, 3) if duration_s > 0 else None,
                   "method": blink_method, "observation_duration_s": round(duration_s, 3),
                   "minimum_observation_s": blink_cfg["minimum_observation_s"]}

    lower_motion: list[float] = []
    pair_times: list[float] = []
    for first, second, first_time, second_time in zip(crops, crops[1:],
                                                       [r["time_s"] for r in records],
                                                       [r["time_s"] for r in records][1:]):
        lower_motion.append(_change_energy(first, second, (slice(34, 58), slice(12, 52))))
        pair_times.append((float(first_time) + float(second_time)) / 2.0)
    audio_check = _audio_sync(records, lower_motion, pair_times, wav, params)
    face_localization = {"status": "PASS" if face_detected_fraction >= 0.5 else "WARN",
                         "reason": ("face region localized in at least half of sampled frames"
                                    if face_detected_fraction >= 0.5 else
                                    "using a proxy region; face localization needs human confirmation"),
                         "detected_sample_fraction": round(face_detected_fraction, 4)}
    checks = {"face_localization": face_localization, "frozen_face": frozen_check,
              "blink": blink_check, "mouth_audio": audio_check}
    statuses = [row["status"] for row in checks.values() if row["status"] != "SKIP"]
    verdict = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"
    if getattr(detector, "name", "") == "heuristic_center_face_proxy":
        verdict = "WARN" if verdict == "PASS" else verdict
    return {"take_id": video.stem, "verdict": verdict, "duration_s": round(duration_s, 3),
            "checks": checks,
            "face_detection": {"backend": getattr(detector, "name", type(detector).__name__),
                               "landmarks": bool(getattr(detector, "landmarks", False)),
                               "detected_sample_fraction": round(face_detected_fraction, 4),
                               "sample_count": len(sampled)},
            "analysis": {"sample_count": len(sampled), "analysis_fps": round(len(sampled) / duration_s, 3)
                         if duration_s > 0 else None}}


def analyze_video(video: Path, *, wav: Path | None = None, ffmpeg: str | None = None,
                  ffprobe: str | None = None, params_path: Path | None = None,
                  detector: Any | None = None) -> dict[str, Any]:
    """Measure one take. The video and optional WAV are opened read-only."""
    video = Path(video)
    if not video.is_file():
        raise Refused(f"video input is not a file: {video}")
    if wav is not None and not Path(wav).is_file():
        raise Refused(f"WAV input is not a file: {wav}")
    params, params_source = _load_params(params_path)
    ffmpeg_path = find_ffmpeg(ffmpeg)
    probe_path = ffprobe or find_ffprobe(ffmpeg_path)
    info = probe(video, probe_path)
    if info.fps <= 0 or info.nb_frames <= 0:
        raise Uncertain(f"video has no measurable frames/fps: {video}")
    detector = detector or _make_detector()
    sample_rate = float(params["analysis_fps"])
    stride = max(1, int(round(info.fps / sample_rate)))
    max_side = max(info.width, info.height)
    spatial_stride = max(1, int(math.ceil(max_side / int(params["max_analysis_side"]))))
    sampled: list[tuple[float, np.ndarray, FaceObservation | None]] = []
    try:
        for frame_index, frame in enumerate(iter_frames(video, info, ffmpeg_path)):
            if frame_index % stride:
                continue
            small_bgr = frame[::spatial_stride, ::spatial_stride]
            rgb = np.ascontiguousarray(small_bgr[..., ::-1])
            observation = detector.detect(rgb)
            sampled.append((frame_index / info.fps, _gray(rgb), observation))
    finally:
        close = getattr(detector, "close", None)
        if close:
            close()
    if len(sampled) < 2:
        raise Uncertain(f"not enough decodable frames for expression analysis: {video}")
    take = _analyse_records(video, info, sampled, detector, Path(wav) if wav else None, params)
    receipt = {"schema": SCHEMA, "verdict": take["verdict"], "ok": take["verdict"] == "PASS",
               "inputs": {"video": {"path": str(video), "sha256": sha256_file(video)},
                          "wav": ({"path": str(wav), "sha256": sha256_file(Path(wav))} if wav else None)},
               "video": {"width": info.width, "height": info.height, "fps": round(info.fps, 6),
                         "frames": info.nb_frames},
               "params": {"path": str(params_source), "sha256": sha256_file(params_source),
                          "status": params.get("status"), "values": params},
               "takes": [take]}
    return receipt


def register_cli(verbs: Any) -> None:
    parser = verbs.add_parser("expression", help="measure face motion, blink presence and optional mouth/audio sync")
    parser.add_argument("--in", dest="video", required=True, help="one take MP4")
    parser.add_argument("--wav", default=None, help="matching dialogue WAV for mouth/audio envelope correlation")
    parser.add_argument("--out", default=None, help="write a write-once JSON receipt here")
    parser.add_argument("--params", default=None, help="override the provisional params JSON")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--ffprobe", default=None)


def run_qa_expression(args: argparse.Namespace) -> int:
    receipt = analyze_video(Path(args.video), wav=Path(args.wav) if args.wav else None,
                            ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                            params_path=Path(args.params) if args.params else None)
    if args.out:
        write_json_once(Path(args.out), receipt, mode="ascii")
    print(json.dumps(receipt, indent=2, ensure_ascii=True))
    return {"PASS": 0, "FAIL": 1, "WARN": 2}[receipt["verdict"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-expression", description=__doc__)
    register_cli(parser.add_subparsers(dest="verb", required=True))
    args = parser.parse_args(argv)
    return run_qa_expression(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
