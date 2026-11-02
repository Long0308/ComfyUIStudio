"""Ghép logo thật (có màu) lên một frame: xoá glyph cũ trong hộp, warp (homography/trụ), nhân độ sáng bề mặt,
làm mềm cho khớp độ nét footage, thêm hạt. Không ghi đè frame vào (trả bản sao)."""
from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from .marks import Mark, MarkAsset
from .render import RenderParams, _long_edge_protect
from .warp import warp_logo


@dataclass(frozen=True)
class MarkRenderParams:
    erase_grow: float = 0.12        # glyph AI trượt khỏi vải: vùng tìm nới thêm grow x cạnh dài hộp (cộng erase_pad)
    erase_pad: int = 6              # nới hộp seed khi tìm glyph cũ (glyph AI trượt vài px)
    erase_min_dist: float = 14.0    # khoảng cách màu BGR tối thiểu so với màu nền để tính là glyph
    erase_k: float = 3.0            # ... hoặc k x độ lệch chuẩn của vành nền, lấy số lớn hơn
    erase_dilate: int = 2
    protect_scale: float = 1.5      # cạnh Canny dài >= scale x cạnh dài hộp = mép vải (ve cổ), không xoá
    ring_px: int = 10               # độ dày vành lấy màu nền
    blur_sigma: float = 0.8         # khớp độ mềm footage (SeedVR2 1440 hơi mềm)
    light_sigma_frac: float = 0.30  # sigma ánh sáng = frac x cạnh dài hộp
    shade_gamma: float = 1.0
    shade_clip: tuple[float, float] = (0.55, 1.25)
    opacity: float = 0.97
    supersample: int = 3
    roi_pad: int = 12
    grain: bool = True

    def with_overrides(self, overrides: dict) -> "MarkRenderParams":
        return replace(self, **{k: v for k, v in overrides.items() if k in self.__dict__})

    def as_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


def _gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)


def _poly_mask(shape: tuple[int, int], quad: np.ndarray, grow: float) -> np.ndarray:
    center = quad.mean(axis=0)
    size = max(1.0, float(np.ptp(quad[:, 1])), float(np.ptp(quad[:, 0])))
    pts = (quad - center) * (1 + 2 * grow / size) + center
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [np.round(pts).astype(np.int32)], 255)
    return mask > 0


def erase_glyph(roi: np.ndarray, box_quad: np.ndarray, params: MarkRenderParams,
                rng: np.random.Generator) -> tuple[np.ndarray, int]:
    """Glyph = pixel trong hộp (nới) lệch màu khỏi nền đo ở vành quanh hộp; inpaint Telea rồi trả hạt vải."""
    reach = params.erase_pad + params.erase_grow * max(float(np.ptp(box_quad[:, 0])), float(np.ptp(box_quad[:, 1])))
    inside = _poly_mask(roi.shape[:2], box_quad, reach)
    outer = _poly_mask(roi.shape[:2], box_quad, reach + params.ring_px)
    ring = outer & ~inside
    if ring.sum() < 20:
        return roi.copy(), 0
    bg = np.median(roi[ring], axis=0)
    ring_dist = np.linalg.norm(roi[ring] - bg, axis=1)
    thr = max(params.erase_min_dist, params.erase_k * float(ring_dist.std()))
    dist = np.linalg.norm(roi - bg, axis=2)
    lum = _gray(roi)
    ring_lum = lum[ring]
    lo, hi = float(np.percentile(ring_lum, 2)), float(np.percentile(ring_lum, 98))
    slack = params.erase_min_dist / 2
    extreme = (lum < lo - slack) | (lum > hi + slack)   # vải có hoạ tiết (caro): glyph nằm NGOÀI dải sáng của vành nền
    dark = ((((dist > thr) | extreme)) & inside).astype(np.uint8)
    if params.erase_dilate > 0:
        dark = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * params.erase_dilate + 1,) * 2))
    dark &= inside.astype(np.uint8)
    if params.protect_scale > 0:                      # không xoá mép vải dài (ve cổ, đường may) và thành phần chạm biên vùng tìm
        extent = int(params.protect_scale * max(np.ptp(box_quad[:, 0]), np.ptp(box_quad[:, 1])))
        protect = _long_edge_protect(_gray(roi), replace(RenderParams(), protect_min_extent=max(30, extent)))
        dark &= (protect == 0)
        rim = inside.astype(np.uint8) - cv2.erode(inside.astype(np.uint8), np.ones((3, 3), np.uint8))
        count_cc, labels, _, _ = cv2.connectedComponentsWithStats(dark, 8)
        for j in range(1, count_cc):
            if rim[labels == j].any():
                dark[labels == j] = 0
    count = int(dark.sum())
    if count == 0:
        return roi.copy(), 0
    filled = cv2.inpaint(roi.astype(np.uint8), dark * 255, 5, cv2.INPAINT_TELEA).astype(np.float32)
    if params.grain:
        high = roi - cv2.GaussianBlur(roi, (0, 0), 1.2)
        donor = ring & (dist <= thr)
        std = high[donor].std(axis=0) if donor.sum() > 20 else np.zeros(3, np.float32)
        noise = cv2.GaussianBlur(rng.standard_normal(roi.shape).astype(np.float32) * std, (0, 0), 0.6) * 1.4
        filled = filled + noise * dark[..., None]
    return np.clip(filled, 0, 255), count


def _roi_rect(shape: tuple[int, ...], quads: list[np.ndarray], pad: int) -> tuple[int, int, int, int]:
    pts = np.vstack(quads)
    return (max(0, int(np.floor(pts[:, 0].min())) - pad), max(0, int(np.floor(pts[:, 1].min())) - pad),
            min(shape[1], int(np.ceil(pts[:, 0].max())) + pad), min(shape[0], int(np.ceil(pts[:, 1].max())) + pad))


def render_mark(frame: np.ndarray, box_quad: np.ndarray, logo_quad: np.ndarray, asset: MarkAsset, mark: Mark,
                params: MarkRenderParams, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    """Một mark trên một frame. Trả (frame mới, debug)."""
    reach = int(params.erase_pad + params.erase_grow * max(float(np.ptp(box_quad[:, 0])), float(np.ptp(box_quad[:, 1]))))
    x0, y0, x1, y1 = _roi_rect(frame.shape, [box_quad, logo_quad], params.roi_pad + reach + params.ring_px)
    offset = np.array([x0, y0], np.float64)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    filled, removed = erase_glyph(roi, box_quad - offset, params, rng)
    colour, alpha = warp_logo(asset.bgr, asset.alpha, logo_quad - offset, roi.shape[:2], params.supersample,
                              mark.cylinder_deg)
    if params.blur_sigma > 0:
        pre = cv2.GaussianBlur(np.dstack([colour * alpha[..., None], alpha]), (0, 0), params.blur_sigma)
        alpha = np.clip(pre[..., 3], 0, 1)
        colour = pre[..., :3] / np.maximum(alpha, 1e-4)[..., None]
    size = max(float(np.ptp(logo_quad[:, 0])), float(np.ptp(logo_quad[:, 1])))
    low = cv2.GaussianBlur(_gray(filled), (0, 0), max(2.0, params.light_sigma_frac * size))
    weight = float(alpha.sum())
    ref = float((low * alpha).sum() / weight) if weight > 1e-3 else float(low.mean())
    lo, hi = params.shade_clip
    factor = np.clip(low / max(ref, 1.0), lo, hi) ** params.shade_gamma  # nhân độ sáng bề mặt: bóng đổ chạy qua logo
    shaded = colour * factor[..., None]
    if params.grain:
        high = filled - cv2.GaussianBlur(filled, (0, 0), 1.2)
        std = float(high.std())
        noise = cv2.GaussianBlur(rng.standard_normal(alpha.shape).astype(np.float32), (0, 0), 0.6) * 1.4 * std
        shaded = shaded + noise[..., None]
    a = (alpha * params.opacity)[..., None]
    out_roi = np.clip(filled * (1 - a) + shaded * a, 0, 255).astype(np.uint8)
    out = frame.copy()
    out[y0:y1, x0:x1] = out_roi
    return out, {"roi": [x0, y0, x1, y1], "removed_px": removed, "logo_px": round(weight, 1),
                 "surface_mean_l": round(ref, 1)}
