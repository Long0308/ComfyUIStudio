"""Ghép logo lên một frame: xoá glyph cũ trong hộp bám, warp perspective, shading theo vải,
relief thêu, feather mép. Không ghi đè frame đầu vào (trả về bản sao)."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class RenderParams:
    thread_rgb: tuple[int, int, int] = (18, 53, 86)  # màu chỉ mặc định (navy); run thay bằng màu đo tại seed hoặc màu CLI
    remove_thr: float = 0.72  # pixel tối hơn 0.72×median hộp = glyph cũ
    remove_dilate: int = 2
    remove_pad: int = 8  # glyph H3 tự trượt ~7 px so với vải ⇒ tìm glyph trong hộp nới thêm remove_pad
    remove_max_area_ratio: float = 0.6  # thành phần tối lớn hơn tỉ lệ này × diện tích hộp = không phải glyph
    protect_edges: bool = True  # v002: v001 ăn vào mép ve cổ tạo khuyết ⇒ bảo vệ cạnh dài (Canny) và bỏ thành phần chạm biên vùng tìm
    protect_min_extent: int = 30  # cạnh Canny có bề rộng/cao ≥ ngưỡng = mép cổ (glyph ≤ ~27 px)
    protect_dilate: int = 2
    protect_canny: tuple[int, int] = (60, 140)
    roi_pad: int = 10
    supersample: int = 4
    feather_sigma: float = 0.7
    relief_gain: float = 0.5
    light_dir: tuple[float, float] = (-0.55, -0.83)  # ánh sáng từ trên-trái
    shade_sigma: float = 4.0
    shade_gamma: float = 0.8
    opacity: float = 0.96
    ao_gain: float = 0.08
    thread_noise: float = 0.04
    stitch_period_px: float = 2.0  # chu kỳ sợi satin theo pixel khung tại seed; co giãn cùng logo
    stitch_angle_deg: float = 45.0
    stitch_gain: float = 0.18
    grain: bool = True

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RenderDebug:
    roi_xyxy: tuple[int, int, int, int]
    removed_px: int
    logo_px: float
    fabric_mean_l: float


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)


def _roi_rect(frame_shape: tuple[int, ...], quads: list[np.ndarray], pad: int) -> tuple[int, int, int, int]:
    pts = np.vstack(quads)
    x0 = int(np.floor(pts[:, 0].min())) - pad
    y0 = int(np.floor(pts[:, 1].min())) - pad
    x1 = int(np.ceil(pts[:, 0].max())) + pad
    y1 = int(np.ceil(pts[:, 1].max())) + pad
    return max(0, x0), max(0, y0), min(frame_shape[1], x1), min(frame_shape[0], y1)


def _long_edge_protect(lum: np.ndarray, params: RenderParams) -> np.ndarray:
    """Mask uint8 các cạnh Canny dài (mép ve cổ) đã nới protect_dilate; glyph nhỏ không lọt ngưỡng."""
    gray = cv2.GaussianBlur(lum, (0, 0), 1.0).astype(np.uint8)
    edges = cv2.Canny(gray, params.protect_canny[0], params.protect_canny[1])
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, 8)
    keep = np.zeros_like(edges)
    for j in range(1, count):
        if max(stats[j, cv2.CC_STAT_WIDTH], stats[j, cv2.CC_STAT_HEIGHT]) >= params.protect_min_extent:
            keep[labels == j] = 1
    if params.protect_dilate > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * params.protect_dilate + 1,) * 2)
        keep = cv2.dilate(keep, kernel)
    return keep


def remove_old_mark(roi: np.ndarray, box_quad_roi: np.ndarray, params: RenderParams,
                    rng: np.random.Generator) -> tuple[np.ndarray, int]:
    """Xoá pixel tối (glyph cũ) trong hộp bám nới thêm remove_pad bằng inpaint Telea + trả lại hạt vải.
    Chỉ giữ thành phần tối có tâm gần hộp và diện tích nhỏ (loại bóng mép cổ / vải thân áo)."""
    center = box_quad_roi.mean(axis=0)
    grown = (box_quad_roi - center) * (1 + 2 * params.remove_pad / max(1.0, np.ptp(box_quad_roi[:, 1]))) + center
    inside = np.zeros(roi.shape[:2], dtype=np.uint8)
    cv2.fillPoly(inside, [np.round(grown).astype(np.int32)], 255)
    lum = _gray(roi)
    ref = float(np.median(lum[inside > 0])) if (inside > 0).any() else float(np.median(lum))
    dark = ((lum < params.remove_thr * ref) & (inside > 0)).astype(np.uint8)
    protect = _long_edge_protect(lum, params) if params.protect_edges else np.zeros_like(dark)
    dark &= (protect == 0)
    rim = inside - cv2.erode(inside, np.ones((3, 3), np.uint8))  # viền 1 px của vùng tìm
    box_area = float(cv2.contourArea(box_quad_roi.astype(np.float32)))
    count_cc, labels, stats, centroids = cv2.connectedComponentsWithStats(dark, 8)
    keep = np.zeros_like(dark)
    half_w, half_h = np.ptp(box_quad_roi[:, 0]) / 2 + params.remove_pad, np.ptp(box_quad_roi[:, 1]) / 2 + params.remove_pad
    for j in range(1, count_cc):
        comp = labels == j
        near = abs(centroids[j][0] - center[0]) <= half_w and abs(centroids[j][1] - center[1]) <= half_h
        touches_rim = params.protect_edges and bool((rim[comp] > 0).any())  # tối đi xuyên biên = mép cổ/thân áo
        if near and not touches_rim and stats[j, cv2.CC_STAT_AREA] <= params.remove_max_area_ratio * box_area:
            keep[comp] = 1
    dark = keep
    if params.remove_dilate > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * params.remove_dilate + 1,) * 2)
        dark = cv2.dilate(dark, kernel)
    dark &= (inside > 0) & (protect == 0)
    count = int(dark.sum())
    if count == 0:
        return roi.copy(), 0
    filled = cv2.inpaint(roi.astype(np.uint8), dark * 255, 3, cv2.INPAINT_TELEA).astype(np.float32)
    if params.grain:
        high = roi.astype(np.float32) - cv2.GaussianBlur(roi.astype(np.float32), (0, 0), 1.2)
        donor = (inside > 0) & (dark == 0)
        std = high[donor].std(axis=0) if donor.sum() > 20 else np.zeros(3, np.float32)
        noise = rng.standard_normal(roi.shape).astype(np.float32) * std
        noise = cv2.GaussianBlur(noise, (0, 0), 0.6) * 1.4
        filled = filled + noise * dark[..., None]
    return np.clip(filled, 0, 255), count


def _stitch_texture(size_wh: tuple[int, int], logo_w_px: float, params: RenderParams) -> np.ndarray:
    """Sọc satin ∈[-1,1] trong không gian logo; chu kỳ quy về stitch_period_px pixel khung."""
    w, h = size_wh
    period = params.stitch_period_px * (w / max(logo_w_px, 1e-3))
    phi = np.radians(params.stitch_angle_deg)
    u, v = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return np.sin(2 * np.pi * (u * np.cos(phi) + v * np.sin(phi)) / period).astype(np.float32)


def warp_logo_alpha(logo_alpha: np.ndarray, quad_roi: np.ndarray, roi_hw: tuple[int, int],
                    params: RenderParams) -> tuple[np.ndarray, np.ndarray]:
    """Warp alpha logo (và vân sợi satin) vào quad bằng perspective với supersample, hạ mẫu INTER_AREA.
    Trả (alpha 0..1, stitch -1..1) cùng kích thước ROI."""
    ss = params.supersample
    edges = np.linalg.norm(np.roll(quad_roi, -1, axis=0) - quad_roi, axis=1)
    target_w = max(4, int(round(max(edges[0], edges[2]) * ss * 2)))
    target_h = max(4, int(round(max(edges[1], edges[3]) * ss * 2)))
    small = cv2.resize(logo_alpha, (target_w, target_h), interpolation=cv2.INTER_AREA)
    stitch = _stitch_texture((target_w, target_h), float(max(edges[0], edges[2])), params)
    src = np.array([[0, 0], [target_w, 0], [target_w, target_h], [0, target_h]], dtype=np.float32)
    dst = (quad_roi * ss).astype(np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    size = (roi_hw[1] * ss, roi_hw[0] * ss)
    big_alpha = cv2.warpPerspective(small, matrix, size, flags=cv2.INTER_LINEAR)
    big_stitch = cv2.warpPerspective(stitch, matrix, size, flags=cv2.INTER_LINEAR)
    alpha = cv2.resize(big_alpha, (roi_hw[1], roi_hw[0]), interpolation=cv2.INTER_AREA)
    stitch_roi = cv2.resize(big_stitch, (roi_hw[1], roi_hw[0]), interpolation=cv2.INTER_AREA)
    return np.clip(alpha, 0.0, 1.0).astype(np.float32), np.clip(stitch_roi, -1.0, 1.0).astype(np.float32)


def sample_thread_color(frame: np.ndarray, box_quad: np.ndarray, core_ratio: float = 0.45) -> tuple[int, int, int]:
    """Lấy màu chỉ từ glyph cũ tại seed: median BGR các pixel lõi tối (< core_ratio × median hộp) → RGB."""
    x0, y0, x1, y1 = _roi_rect(frame.shape, [box_quad], 0)
    roi = frame[y0:y1, x0:x1]
    lum = _gray(roi)
    core = lum < core_ratio * float(np.median(lum))
    if core.sum() < 10:
        raise ValueError("Không đủ pixel tối trong hộp seed để lấy màu chỉ; cho --thread-rgb tay")
    bgr = np.median(roi[core], axis=0)
    return int(bgr[2]), int(bgr[1]), int(bgr[0])


def shade_thread(filled: np.ndarray, alpha_soft: np.ndarray, stitch: np.ndarray, params: RenderParams,
                 rng: np.random.Generator) -> tuple[np.ndarray, float]:
    """Màu chỉ = màu chỉ × độ sáng vải cục bộ, cộng relief thêu, sọc satin và nhiễu sợi chỉ."""
    lum = cv2.GaussianBlur(_gray(filled), (0, 0), params.shade_sigma)
    weight = alpha_soft.sum()
    mean_l = float((lum * alpha_soft).sum() / weight) if weight > 1e-3 else float(lum.mean())
    factor = np.clip(lum / max(mean_l, 1.0), 0.6, 1.4) ** params.shade_gamma
    thread = np.array(params.thread_rgb[::-1], dtype=np.float32)[None, None, :] * factor[..., None]
    gx = cv2.Sobel(alpha_soft, cv2.CV_32F, 1, 0, ksize=3, scale=1 / 8)
    gy = cv2.Sobel(alpha_soft, cv2.CV_32F, 0, 1, ksize=3, scale=1 / 8)
    relief = gx * params.light_dir[0] + gy * params.light_dir[1]
    thread = thread * (1.0 + params.relief_gain * 2.0 * relief)[..., None]
    if params.stitch_gain > 0:
        thread = thread * (1.0 + params.stitch_gain * stitch)[..., None]
    if params.thread_noise > 0:
        noise = cv2.GaussianBlur(rng.standard_normal(alpha_soft.shape).astype(np.float32), (0, 0), 0.5)
        thread = thread * (1.0 + params.thread_noise * noise)[..., None]
    return np.clip(thread, 0, 255), mean_l


def composite_frame(frame: np.ndarray, box_quad: np.ndarray, logo_quad: np.ndarray, logo_alpha: np.ndarray,
                    params: RenderParams, rng: np.random.Generator) -> tuple[np.ndarray, RenderDebug]:
    x0, y0, x1, y1 = _roi_rect(frame.shape, [box_quad, logo_quad], params.roi_pad)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    offset = np.array([x0, y0], dtype=np.float64)
    filled, removed = remove_old_mark(roi, box_quad - offset, params, rng)
    alpha, stitch = warp_logo_alpha(logo_alpha, logo_quad - offset, roi.shape[:2], params)
    alpha_soft = cv2.GaussianBlur(alpha, (0, 0), params.feather_sigma) if params.feather_sigma > 0 else alpha
    thread, mean_l = shade_thread(filled, alpha_soft, stitch, params, rng)
    occlusion = cv2.GaussianBlur(alpha, (0, 0), 1.5) * (1.0 - alpha_soft)
    base = filled * (1.0 - params.ao_gain * occlusion)[..., None]
    a = (alpha_soft * params.opacity)[..., None]
    out_roi = np.clip(base * (1.0 - a) + thread * a, 0, 255).astype(np.uint8)
    out = frame.copy()
    out[y0:y1, x0:x1] = out_roi
    return out, RenderDebug((x0, y0, x1, y1), removed, float(alpha.sum()), mean_l)
