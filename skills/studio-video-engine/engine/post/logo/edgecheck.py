"""Cổng kiểm mép ve cổ: dải band_px pixel dọc các cạnh dài (Canny) quanh logo phải gần như không đổi
giữa before/after (chỉ còn nhiễu nén). Trả MAD trên dải + ảnh crop 6× để soi."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ...core.errors import Refused
from .strip import LABEL_H

EDGE_FAIL = "EDGE_BAND_FAIL"


class EdgeGateError(Refused):
    """Cổng mép đỏ: dải cạnh dài quanh logo bị đổi nhiều hơn phần còn lại của crop; output không được publish."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(f"{EDGE_FAIL}: {message}", evidence={"code": EDGE_FAIL, **(details or {})})
        self.code = EDGE_FAIL
        self.details = details or {}


@dataclass(frozen=True)
class EdgeCheckParams:
    crop: int = 96
    band_px: int = 6
    canny_lo: int = 60
    canny_hi: int = 140
    min_edge_extent: int = 30  # thành phần cạnh có bề rộng/cao ≥ ngưỡng = cạnh dài (mép cổ), không phải glyph
    tile: int = 64
    zoom: int = 6


@dataclass(frozen=True)
class EdgeCheckResult:
    frame: int
    band_px_count: int
    mad_band: float
    mad_reference: float
    ratio: float
    tile: np.ndarray

    def as_dict(self) -> dict:
        return {"frame": self.frame, "band_px_count": self.band_px_count, "mad_band": round(self.mad_band, 3),
                "mad_reference_outside": round(self.mad_reference, 3), "ratio_band_over_reference": round(self.ratio, 2)}


def _crop_rect(shape: tuple[int, ...], center: tuple[float, float], size: int) -> tuple[int, int]:
    h, w = shape[:2]
    half = size // 2
    x0 = min(max(0, int(round(center[0])) - half), max(0, w - size))
    y0 = min(max(0, int(round(center[1])) - half), max(0, h - size))
    return x0, y0


def long_edge_band(gray: np.ndarray, params: EdgeCheckParams) -> np.ndarray:
    """Mask uint8 dải quanh các cạnh dài trong ảnh xám (đã blur nhẹ để bỏ hạt vải)."""
    edges = cv2.Canny(cv2.GaussianBlur(gray, (0, 0), 1.0), params.canny_lo, params.canny_hi)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, 8)
    keep = np.zeros_like(edges)
    for j in range(1, count):
        if max(stats[j, cv2.CC_STAT_WIDTH], stats[j, cv2.CC_STAT_HEIGHT]) >= params.min_edge_extent:
            keep[labels == j] = 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (params.band_px + 1, params.band_px + 1))
    return cv2.dilate(keep, kernel)


def edge_check(frame_idx: int, before: np.ndarray, after: np.ndarray, center: tuple[float, float],
               exclude_quads: list[np.ndarray], params: EdgeCheckParams,
               extra: np.ndarray | None = None, extra_label: str = "") -> EdgeCheckResult:
    """MAD before/after trên dải cạnh dài (loại vùng hộp/logo), so với MAD phần còn lại của crop."""
    x0, y0 = _crop_rect(before.shape, center, params.crop)
    crop_b = before[y0:y0 + params.crop, x0:x0 + params.crop]
    crop_a = after[y0:y0 + params.crop, x0:x0 + params.crop]
    gray_b = cv2.cvtColor(crop_b, cv2.COLOR_BGR2GRAY)
    band = long_edge_band(gray_b, params) > 0
    excl = np.zeros(band.shape, dtype=np.uint8)
    for quad in exclude_quads:
        cv2.fillPoly(excl, [np.round(quad - np.array([x0, y0])).astype(np.int32)], 255)
    excl = cv2.dilate(excl, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
    band &= ~excl
    diff = np.abs(crop_a.astype(np.int16) - crop_b.astype(np.int16)).mean(axis=2)
    rest = ~band & ~excl
    mad_band = float(diff[band].mean()) if band.any() else 0.0
    mad_ref = float(diff[rest].mean()) if rest.any() else 0.0
    ratio = mad_band / mad_ref if mad_ref > 1e-6 else 0.0
    tile = _tiles(frame_idx, crop_b, crop_a, band, mad_band, mad_ref, params,
                  None if extra is None else extra[y0:y0 + params.crop, x0:x0 + params.crop], extra_label)
    return EdgeCheckResult(frame_idx, int(band.sum()), mad_band, mad_ref, ratio, tile)


def _label(img: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((LABEL_H, img.shape[1], 3), 255, dtype=np.uint8)
    cv2.putText(bar, text, (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (64, 37, 10), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def _tiles(frame_idx: int, crop_b: np.ndarray, crop_a: np.ndarray, band: np.ndarray, mad_band: float,
           mad_ref: float, params: EdgeCheckParams, crop_x: np.ndarray | None, extra_label: str) -> np.ndarray:
    """Crop tile×tile quanh trọng tâm dải (đoạn mép gần logo), phóng zoom; cột 1 có dải tô đỏ nhạt."""
    ys, xs = np.where(band)
    cy, cx = (float(ys.mean()), float(xs.mean())) if len(ys) else (params.crop / 2, params.crop / 2)
    tx, ty = _crop_rect(crop_b.shape, (cx, cy), params.tile)
    sl = (slice(ty, ty + params.tile), slice(tx, tx + params.tile))
    overlay = crop_b.copy()
    overlay[band] = (0.6 * overlay[band] + 0.4 * np.array([80, 80, 255])).astype(np.uint8)
    pieces = [(overlay[sl], f"f{frame_idx} band"), (crop_b[sl], f"f{frame_idx} before"),
              (crop_a[sl], f"f{frame_idx} after MAD={mad_band:.1f}/{mad_ref:.1f}")]
    if crop_x is not None:
        pieces.append((crop_x[sl], f"f{frame_idx} {extra_label}"))
    z = params.zoom
    tiles = [_label(cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC), text) for img, text in pieces]
    gap = np.full((tiles[0].shape[0], 4, 3), 255, dtype=np.uint8)
    out: list[np.ndarray] = []
    for t in tiles:
        out += [t, gap]
    return np.hstack(out[:-1])


def edge_gate(results: list["EdgeCheckResult"], slack: float) -> dict:
    """Đạt khi MỌI frame đo có ``mad_band <= mad_reference_outside + slack`` (cả hai đo trên bản đã giải mã)."""
    if not results:
        raise EdgeGateError("no edge-check frames were measured", {"frames": []})
    rows = [r.as_dict() for r in results]
    failing = [r.frame for r in results if r.mad_band > r.mad_reference + slack]
    report = {"pass": not failing, "rule": "mad_band <= mad_reference_outside + slack", "slack": slack,
              "frames": rows, "failing_frames": failing}
    if failing:
        raise EdgeGateError(f"edge band changed more than the surround at frame(s) {failing}", report)
    return report


def stack_results(results: list[EdgeCheckResult]) -> np.ndarray:
    gap = np.full((6, results[0].tile.shape[1], 3), 255, dtype=np.uint8)
    rows: list[np.ndarray] = []
    for r in results:
        rows += [r.tile, gap]
    return np.vstack(rows[:-1])
