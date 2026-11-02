"""Dò tự động seed box của dấu thêu trên cổ áo: blob tối, gọn, màu chỉ đúng, trên nền vải sáng (CPU, OpenCV).

Đo 31/10 trên clip C2 (2560x1440, 12 frame đầu, vùng tìm giữa khung): dấu thật score 0.177..0.273, margin >= 0.079,
12/12 frame đồng thuận; vùng không có dấu: score <= 0.092, margin <= 0.030, 4/12 đồng thuận. Ngưỡng nằm trong
domain JSON (``post.logo_composite.detect``), không phải hằng số code. Mọi ca mờ ⇒ từ chối có tên, không đoán.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ...core.errors import Refused
from .policy import DetectConfig

NOT_FOUND = "SEED_BOX_NOT_FOUND"
AMBIGUOUS = "SEED_BOX_AMBIGUOUS"


class SeedBoxError(Refused):
    """Dò seed box thất bại; ``code`` cố định để máy đọc, ``details`` mang điểm số thật."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(f"{code}: {message}; pass --seed-box to override", evidence={"code": code, **(details or {})})
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class Candidate:
    rect: tuple[int, int, int, int]  # mark bbox in frame coordinates
    score: float
    contrast: float
    ring: float
    color_sim: float
    fill: float
    aspect: float
    area: int

    def as_dict(self) -> dict:
        return {"rect_xywh": list(self.rect), "score": round(self.score, 4), "contrast": round(self.contrast, 4),
                "ring_brightness": round(self.ring, 4), "color_sim": round(self.color_sim, 3),
                "fill": round(self.fill, 3), "aspect": round(self.aspect, 3), "area": self.area}


@dataclass(frozen=True)
class Detection:
    frame: int
    rect: tuple[int, int, int, int]
    box: tuple[int, int, int, int]
    score: float
    margin: float
    agreement: float
    per_frame: list[dict]
    region_px: tuple[int, int, int, int]

    def as_dict(self) -> dict:
        return {"frame": self.frame, "rect_xywh": list(self.rect), "box_xywh": list(self.box),
                "score": round(self.score, 4), "margin": round(self.margin, 4), "agreement": round(self.agreement, 3),
                "search_region_px": list(self.region_px), "per_frame": self.per_frame}


def _chroma(rgb) -> np.ndarray:
    v = np.asarray(rgb, dtype=np.float64)
    return v - v.mean()


def color_similarity(core_bgr: np.ndarray, mark_rgb: tuple[int, int, int]) -> float:
    """Cosine giữa chroma (màu trừ xám) của lõi blob và của màu chỉ khai báo; màu chỉ gần xám ⇒ không gate (1.0)."""
    target = _chroma(mark_rgb)
    norm_t = float(np.linalg.norm(target))
    if norm_t < 8.0:
        return 1.0
    sample = _chroma(np.asarray(core_bgr, dtype=np.float64)[::-1])
    norm_s = float(np.linalg.norm(sample))
    return float(sample @ target / (norm_s * norm_t)) if norm_s > 1e-6 else 0.0


def region_pixels(cfg: DetectConfig, width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = cfg.search_region
    return int(x * width), int(y * height), max(1, int(w * width)), max(1, int(h * height))


def frame_candidates(frame: np.ndarray, cfg: DetectConfig, icon_aspect: float) -> list[Candidate]:
    """Blob tối (black-hat) có chiều cao trong dải, aspect gần icon, độ đầy hợp lý, chroma đúng màu chỉ; sắp theo score."""
    height = frame.shape[0]
    rx, ry, rw, rh = region_pixels(cfg, frame.shape[1], height)
    h_min = max(2, int(round(cfg.mark_height_frac[0] * height)))
    h_max = max(h_min, int(round(cfg.mark_height_frac[1] * height)))
    crop = frame[ry:ry + rh, rx:rx + rw]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * h_max + 1, 2 * h_max + 1))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    mask = (blackhat > cfg.dark_threshold).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    lum = gray.astype(np.float32)
    lo_aspect, hi_aspect = icon_aspect * (1 - cfg.aspect_tolerance), icon_aspect * (1 + cfg.aspect_tolerance)
    out: list[Candidate] = []
    for j in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[j])
        if not (h_min <= h <= h_max) or not (lo_aspect <= w / h <= hi_aspect):
            continue
        fill = area / (w * h)
        if not (cfg.fill_range[0] <= fill <= cfg.fill_range[1]):
            continue
        if x <= 0 or y <= 0 or x + w >= rw or y + h >= rh:
            continue
        component = labels == j
        core_bgr = np.median(crop[component].reshape(-1, 3), axis=0)
        sim = color_similarity(core_bgr, cfg.mark_rgb)
        if sim < cfg.color_min_similarity:
            continue
        margin = int(round(0.75 * max(w, h)))
        inner = int(round(0.15 * max(w, h)))
        ring = np.zeros(gray.shape, dtype=bool)
        ring[max(0, y - margin):y + h + margin, max(0, x - margin):x + w + margin] = True
        ring[max(0, y - inner):y + h + inner, max(0, x - inner):x + w + inner] = False
        ring_median = float(np.median(lum[ring])) if ring.any() else 0.0
        contrast = max(0.0, ring_median - float(lum[component].mean())) / 255.0
        out.append(Candidate(rect=(rx + x, ry + y, w, h), score=contrast * ring_median / 255.0, contrast=contrast,
                             ring=ring_median / 255.0, color_sim=sim, fill=fill, aspect=w / h, area=area))
    out.sort(key=lambda c: -c.score)
    return out


def _grown(rect: tuple[int, int, int, int], pad: int, width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0 = max(0, rect[0] - pad), max(0, rect[1] - pad)
    x1, y1 = min(width, rect[0] + rect[2] + pad), min(height, rect[1] + rect[3] + pad)
    return x0, y0, x1 - x0, y1 - y0


def detect_seed(frames: list[np.ndarray], cfg: DetectConfig, icon_aspect: float) -> Detection:
    """Seed frame = frame có ứng viên mạnh nhất; từ chối khi điểm thấp, margin mỏng hoặc các frame không đồng thuận."""
    if not frames:
        raise SeedBoxError(NOT_FOUND, "no frames to search")
    height, width = frames[0].shape[:2]
    region = region_pixels(cfg, width, height)
    per_frame: list[dict] = []
    bests: list[tuple[int, Candidate, float]] = []
    for index, frame in enumerate(frames):
        cands = frame_candidates(frame, cfg, icon_aspect)
        row: dict = {"frame": index, "candidates": len(cands), "best": cands[0].as_dict() if cands else None,
                     "second": cands[1].as_dict() if len(cands) > 1 else None}
        per_frame.append(row)
        if cands:
            bests.append((index, cands[0], cands[0].score - (cands[1].score if len(cands) > 1 else 0.0)))
    thresholds = {"min_score": cfg.min_score, "min_margin": cfg.min_margin, "min_agreement": cfg.min_agreement,
                  "frames_searched": len(frames), "search_region_px": list(region)}
    if not bests:
        raise SeedBoxError(NOT_FOUND, f"no candidate passed the size/aspect/fill/colour gates in {len(frames)} frames",
                           {**thresholds, "per_frame": per_frame})
    seed_index, best, margin = max(bests, key=lambda item: item[1].score)
    if best.score < cfg.min_score:
        raise SeedBoxError(NOT_FOUND, f"best candidate score {best.score:.3f} < min_score {cfg.min_score} "
                                      f"(frame {seed_index}, rect {list(best.rect)})",
                           {**thresholds, "best": best.as_dict(), "frame": seed_index, "per_frame": per_frame})
    if margin < cfg.min_margin:
        raise SeedBoxError(AMBIGUOUS, f"margin {margin:.3f} between the best and second candidate < min_margin "
                                      f"{cfg.min_margin} at frame {seed_index}",
                           {**thresholds, "best": best.as_dict(), "margin": round(margin, 4), "frame": seed_index,
                            "per_frame": per_frame})
    cx, cy = best.rect[0] + best.rect[2] / 2, best.rect[1] + best.rect[3] / 2
    tolerance = 2 * max(best.rect[2], best.rect[3])
    agreeing = [i for i, c, _ in bests if abs(c.rect[0] + c.rect[2] / 2 - cx) <= tolerance
                and abs(c.rect[1] + c.rect[3] / 2 - cy) <= tolerance]
    agreement = len(agreeing) / len(frames)
    if agreement < cfg.min_agreement:
        raise SeedBoxError(AMBIGUOUS, f"only {len(agreeing)}/{len(frames)} frames agree on the mark position "
                                      f"(min_agreement {cfg.min_agreement})",
                           {**thresholds, "best": best.as_dict(), "frame": seed_index, "agreement": round(agreement, 3),
                            "per_frame": per_frame})
    pad = int(round(cfg.box_pad_frac * best.rect[3]))
    return Detection(frame=seed_index, rect=best.rect, box=_grown(best.rect, pad, width, height), score=best.score,
                     margin=margin, agreement=agreement, per_frame=per_frame, region_px=region)


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, bx1, by1 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = max(0, min(ax1, bx1) - max(a[0], b[0])), max(0, min(ay1, by1) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union else 0.0
