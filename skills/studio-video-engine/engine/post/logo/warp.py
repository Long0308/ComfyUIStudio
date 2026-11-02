"""Warp một logo RGBA vào quad 4 điểm: homography (perspective) + tuỳ chọn cong trụ nhẹ (mũ bảo hộ).

Màu được warp ở dạng premultiplied để viền không bị lem màu nền trong suốt; supersample rồi hạ mẫu INTER_AREA.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def fit_homography(src_pts: np.ndarray, dst_pts: np.ndarray) -> np.ndarray:
    """Homography 3x3 chính xác từ đúng 4 cặp điểm (TL, TR, BR, BL)."""
    src, dst = np.asarray(src_pts, np.float32), np.asarray(dst_pts, np.float32)
    if src.shape != (4, 2) or dst.shape != (4, 2):
        raise ValueError("need exactly 4 points each")
    return cv2.getPerspectiveTransform(src, dst).astype(np.float64)


def cylinder_source_u(u: np.ndarray, angle_deg: float) -> np.ndarray:
    """Hiển thị phẳng u∈[0,1] -> toạ độ nguồn s∈[0,1] khi logo dán lên trụ nửa góc ``angle_deg`` (0 = phẳng).
    Mép bị nén (sin), giữa không đổi."""
    if angle_deg <= 0:
        return u
    a = math.radians(angle_deg)
    return (np.arcsin(np.clip((2 * u - 1) * math.sin(a), -1.0, 1.0)) / a + 1.0) / 2.0


def _rect_image(bgr: np.ndarray, alpha: np.ndarray, size_wh: tuple[int, int], cylinder_deg: float) -> np.ndarray:
    """Ảnh premultiplied BGRA (float32) của logo đã đặt vào hình chữ nhật size_wh, đã cong trụ nếu cần."""
    w, h = size_wh
    pre = np.dstack([bgr * alpha[..., None], alpha]).astype(np.float32)
    rect = cv2.resize(pre, (w, h), interpolation=cv2.INTER_AREA)
    if cylinder_deg > 0:
        u = (np.arange(w, dtype=np.float32) + 0.5) / w
        map_x = (cylinder_source_u(u, cylinder_deg) * w - 0.5).astype(np.float32)
        map_x = np.tile(map_x[None, :], (h, 1))
        map_y = np.tile(np.arange(h, dtype=np.float32)[:, None], (1, w))
        rect = cv2.remap(rect, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return rect


def warp_logo(bgr: np.ndarray, alpha: np.ndarray, quad_roi: np.ndarray, roi_hw: tuple[int, int],
              supersample: int = 3, cylinder_deg: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Trả (màu thẳng BGR float32 HxWx3, alpha float32 HxW) trong ROI; quad theo thứ tự TL, TR, BR, BL."""
    ss = max(1, int(supersample))
    edges = np.linalg.norm(np.roll(quad_roi, -1, axis=0) - quad_roi, axis=1)
    w = max(8, int(round(max(edges[0], edges[2]) * ss * 1.5)))
    h = max(8, int(round(max(edges[1], edges[3]) * ss * 1.5)))
    rect = _rect_image(bgr, alpha, (w, h), cylinder_deg)
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    matrix = fit_homography(src, np.asarray(quad_roi, np.float64) * ss)
    big = cv2.warpPerspective(rect, matrix, (roi_hw[1] * ss, roi_hw[0] * ss), flags=cv2.INTER_LINEAR)
    small = cv2.resize(big, (roi_hw[1], roi_hw[0]), interpolation=cv2.INTER_AREA)
    a = np.clip(small[..., 3], 0.0, 1.0)
    colour = small[..., :3] / np.maximum(a, 1e-4)[..., None]
    return np.clip(colour, 0, 255).astype(np.float32), a.astype(np.float32)
