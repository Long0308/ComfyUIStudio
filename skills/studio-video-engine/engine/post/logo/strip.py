"""Dải ảnh before/after cắt 1:1 quanh tâm vùng bám (và bản phóng to để soi)."""
from __future__ import annotations

import cv2
import numpy as np

LABEL_H = 18


def _crop(frame: np.ndarray, center: tuple[float, float], size: int) -> np.ndarray:
    h, w = frame.shape[:2]
    half = size // 2
    cx, cy = int(round(center[0])), int(round(center[1]))
    x0 = min(max(0, cx - half), max(0, w - size))
    y0 = min(max(0, cy - half), max(0, h - size))
    return frame[y0:y0 + size, x0:x0 + size].copy()


def _tile(crop: np.ndarray, label: str, zoom: int) -> np.ndarray:
    if zoom != 1:
        crop = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
    bar = np.full((LABEL_H, crop.shape[1], 3), 255, dtype=np.uint8)
    cv2.putText(bar, label, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (64, 37, 10), 1, cv2.LINE_AA)
    return np.vstack([bar, crop])


def build_strip(frames_before: dict[int, np.ndarray], frames_after: dict[int, np.ndarray],
                centers: dict[int, tuple[float, float]], size: int = 128, zoom: int = 1) -> np.ndarray:
    tiles = []
    for idx in sorted(frames_before):
        tiles.append(_tile(_crop(frames_before[idx], centers[idx], size), f"f{idx} before", zoom))
        tiles.append(_tile(_crop(frames_after[idx], centers[idx], size), f"f{idx} after", zoom))
    gap = np.full((tiles[0].shape[0], 4, 3), 255, dtype=np.uint8)
    pieces: list[np.ndarray] = []
    for tile in tiles:
        pieces += [tile, gap]
    return np.hstack(pieces[:-1])


def build_track_preview(frames: dict[int, np.ndarray], quads: dict[int, np.ndarray],
                        logo_quads: dict[int, np.ndarray], size: int = 200, zoom: int = 2) -> np.ndarray:
    """Vẽ hộp bám (đỏ) và quad logo (xanh) lên crop để kiểm bám trước khi ghép."""
    tiles = []
    for idx in sorted(frames):
        center = tuple(quads[idx].mean(axis=0))
        crop = _crop(frames[idx], center, size)
        h, w = frames[idx].shape[:2]
        half = size // 2
        x0 = min(max(0, int(round(center[0])) - half), max(0, w - size))
        y0 = min(max(0, int(round(center[1])) - half), max(0, h - size))
        crop = cv2.resize(crop, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        for quad, color in ((quads[idx], (0, 0, 255)), (logo_quads[idx], (255, 128, 0))):
            pts = np.round((quad - np.array([x0, y0])) * zoom).astype(np.int32)
            cv2.polylines(crop, [pts], True, color, 1, cv2.LINE_AA)
        tiles.append(_tile(crop, f"f{idx}", 1))
    return np.hstack(tiles)
