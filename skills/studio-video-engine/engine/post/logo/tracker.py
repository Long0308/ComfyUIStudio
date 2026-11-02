"""Theo dõi vùng vải bằng KLT (pyramidal Lucas-Kanade, kiểm forward-backward)
+ similarity RANSAC (estimateAffinePartial2D) tính so với keyframe, không cộng dồn từng frame.

Toạ độ làm việc là toạ độ cửa sổ (window) đã cắt quanh seed; CLI cộng offset về toạ độ khung.
Frame mất bám: giữ ma trận cuối (held); nếu kẹp giữa hai frame bám tốt thì nội suy (interpolated).
"""
from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, replace

import cv2
import numpy as np

from ...core.errors import Refused

LOG = logging.getLogger(__name__)
TRACKER_TYPE = "KLT pyramidal Lucas-Kanade (fwd-bwd check) + RANSAC similarity vs keyframe; seed-NCC drift check"


@dataclass(frozen=True)
class TrackParams:
    max_corners: int = 400
    quality: float = 0.01
    min_distance: int = 4
    block_size: int = 5
    lk_win: int = 21
    lk_levels: int = 4
    fb_err: float = 1.0
    ransac_thr: float = 2.0
    min_inliers: int = 8
    min_conf: float = 0.3
    rekey_inliers: int = 40
    rekey_every: int = 24
    max_step_px: float = 40.0
    max_step_scale: float = 0.15
    max_step_rot_deg: float = 15.0
    ring_scale: float = 2.0  # đo 31/10: ring 3.0 trôi −16 px ở f100 (dính vải thân áo); 2.0 lệch ≤2 px
    inner_scale: float = 1.15
    reanchor: bool = True  # kéo tịnh tiến về đỉnh NCC của seed đã warp (chống trôi tích luỹ)
    reanchor_radius: int = 16
    reanchor_min_score: float = 0.6
    reanchor_median: int = 3
    gate_max_lost_fraction: float = 0.10  # cổng trước render: tỉ lệ frame held+interpolated tối đa
    gate_max_gap_frames: int = 6  # chuỗi interpolated liên tiếp dài nhất được phép

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class TrackGateError(Refused):
    """Cổng bám từ chối render (exit 1, chưa encode gì); `code` là tên lỗi cố định để máy đọc."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(f"{code}: {message}", evidence={"code": code, **(details or {})})
        self.code = code
        self.details = details or {}


def gate_tracks(tracks: list["FrameTrack"], margin_violations: list[int], params: TrackParams) -> dict:
    """Từ chối khi mất bám ở đầu/cuối clip (không nội suy được ⇒ logo đứng hình), khi tỉ lệ frame mất
    vượt ngưỡng, khi một chuỗi nội suy quá dài, hoặc khi hộp bám chạm biên cửa sổ. Trả báo cáo nếu đạt."""
    held = [t.index for t in tracks if t.status == "held"]
    interpolated = [t.index for t in tracks if t.status == "interpolated"]
    leading = [t.index for t in itertools.takewhile(lambda t: t.status == "held", tracks)]
    trailing = [t.index for t in itertools.takewhile(lambda t: t.status == "held", reversed(tracks))]
    longest_gap = max((len(list(g)) for k, g in itertools.groupby(tracks, key=lambda t: t.status) if k == "interpolated"),
                      default=0)
    lost_fraction = (len(held) + len(interpolated)) / max(1, len(tracks))
    report = {"frames_total": len(tracks), "held": held, "interpolated": interpolated, "leading_loss": leading,
              "trailing_loss": sorted(trailing), "lost_fraction": round(lost_fraction, 4),
              "longest_interpolated_gap": longest_gap, "window_margin_violations": margin_violations,
              "thresholds": {"max_lost_fraction": params.gate_max_lost_fraction,
                             "max_gap_frames": params.gate_max_gap_frames}}
    if leading:
        raise TrackGateError("LEADING_LOSS", f"mất bám {len(leading)} frame đầu (tới f{leading[-1]}), không nội suy được", report)
    if trailing:
        raise TrackGateError("TRAILING_LOSS", f"mất bám {len(trailing)} frame cuối (từ f{min(trailing)}), logo sẽ đứng hình", report)
    if lost_fraction > params.gate_max_lost_fraction:
        raise TrackGateError("LOST_FRACTION_EXCEEDED",
                             f"{lost_fraction:.1%} frame mất bám > {params.gate_max_lost_fraction:.0%}", report)
    if longest_gap > params.gate_max_gap_frames:
        raise TrackGateError("INTERPOLATED_GAP_TOO_LONG",
                             f"chuỗi nội suy {longest_gap} frame > {params.gate_max_gap_frames}", report)
    if margin_violations:
        raise TrackGateError("WINDOW_MARGIN_VIOLATION",
                             f"hộp bám chạm biên cửa sổ ở {len(margin_violations)} frame (vd f{margin_violations[0]}); tăng --track-window", report)
    return report


@dataclass(frozen=True)
class FrameTrack:
    index: int
    matrix: np.ndarray  # 3x3, seed-window → frame-window
    status: str  # seed | tracked | held | interpolated
    confidence: float
    inliers: int
    alive: int
    keyframe: int
    ncc_seed: float
    ncc_peak: float = 1.0
    reanchor_dx: float = 0.0
    reanchor_dy: float = 0.0

    def as_dict(self, offset: tuple[int, int], box: tuple[float, float, float, float]) -> dict:
        quad = transform_points(self.matrix, box_corners(box)) + np.array(offset, dtype=np.float64)
        _, _, theta, log_s = decompose(self.matrix)
        return {
            "frame": self.index, "status": self.status, "confidence": round(self.confidence, 4),
            "inliers": self.inliers, "alive": self.alive, "keyframe": self.keyframe,
            "ncc_seed": round(self.ncc_seed, 4), "ncc_peak": round(self.ncc_peak, 4),
            "reanchor_dxdy": [round(self.reanchor_dx, 2), round(self.reanchor_dy, 2)],
            "rotation_deg": round(math.degrees(theta), 2), "scale": round(math.exp(log_s), 4),
            "box_quad": [[round(float(x), 2), round(float(y), 2)] for x, y in quad],
            "center": [round(float(v), 2) for v in quad.mean(axis=0)],
        }


def box_corners(box: tuple[float, float, float, float]) -> np.ndarray:
    x, y, w, h = box
    return np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float64)


def transform_points(matrix: np.ndarray, pts: np.ndarray) -> np.ndarray:
    homo = np.hstack([pts, np.ones((len(pts), 1))])
    out = homo @ matrix.T
    return out[:, :2] / out[:, 2:3]


def decompose(matrix: np.ndarray) -> tuple[float, float, float, float]:
    """similarity 3x3 → (tx, ty, góc rad, log-scale)."""
    a, b = matrix[0, 0], matrix[1, 0]
    return float(matrix[0, 2]), float(matrix[1, 2]), math.atan2(b, a), math.log(math.hypot(a, b))


def compose(tx: float, ty: float, theta: float, log_s: float) -> np.ndarray:
    s = math.exp(log_s)
    return np.array([[s * math.cos(theta), -s * math.sin(theta), tx],
                     [s * math.sin(theta), s * math.cos(theta), ty], [0.0, 0.0, 1.0]])


def _ring_mask(shape: tuple[int, int], matrix: np.ndarray, box: tuple[float, float, float, float],
               params: TrackParams) -> np.ndarray:
    """Vành quanh hộp: lấy đặc trưng trên vải/ve cổ quanh logo, loại vùng glyph (không ổn định)."""
    quad = transform_points(matrix, box_corners(box))
    cx, cy = quad.mean(axis=0)
    hw = (quad[:, 0].max() - quad[:, 0].min()) / 2
    hh = (quad[:, 1].max() - quad[:, 1].min()) / 2
    mask = np.zeros(shape, dtype=np.uint8)
    outer = (int(cx - hw * params.ring_scale), int(cy - hh * params.ring_scale),
             int(cx + hw * params.ring_scale), int(cy + hh * params.ring_scale))
    inner = (int(cx - hw * params.inner_scale), int(cy - hh * params.inner_scale),
             int(cx + hw * params.inner_scale), int(cy + hh * params.inner_scale))
    cv2.rectangle(mask, outer[:2], outer[2:], 255, -1)
    cv2.rectangle(mask, inner[:2], inner[2:], 0, -1)
    margin = params.lk_win
    mask[:margin, :] = 0
    mask[-margin:, :] = 0
    mask[:, :margin] = 0
    mask[:, -margin:] = 0
    return mask


def _detect(gray: np.ndarray, matrix: np.ndarray, box: tuple[float, float, float, float],
            params: TrackParams) -> np.ndarray:
    mask = _ring_mask(gray.shape, matrix, box, params)
    pts = cv2.goodFeaturesToTrack(gray, params.max_corners, params.quality, params.min_distance,
                                  mask=mask, blockSize=params.block_size)
    if pts is None:
        return np.zeros((0, 1, 2), dtype=np.float32)
    return pts.astype(np.float32)


def _flow(prev: np.ndarray, cur: np.ndarray, pts: np.ndarray, params: TrackParams) -> tuple[np.ndarray, np.ndarray]:
    lk = dict(winSize=(params.lk_win, params.lk_win), maxLevel=params.lk_levels,
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, **lk)
    back, st2, _ = cv2.calcOpticalFlowPyrLK(cur, prev, nxt, None, **lk)
    fb = np.linalg.norm((back - pts).reshape(-1, 2), axis=1)
    good = (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (fb < params.fb_err)
    return nxt, good


def _step_ok(prev_m: np.ndarray, cur_m: np.ndarray, box: tuple[float, float, float, float],
             params: TrackParams) -> bool:
    c_prev = transform_points(prev_m, box_corners(box)).mean(axis=0)
    c_cur = transform_points(cur_m, box_corners(box)).mean(axis=0)
    _, _, th_p, ls_p = decompose(prev_m)
    _, _, th_c, ls_c = decompose(cur_m)
    d_rot = abs(math.degrees((th_c - th_p + math.pi) % (2 * math.pi) - math.pi))
    return (np.linalg.norm(c_cur - c_prev) <= params.max_step_px
            and abs(ls_c - ls_p) <= math.log1p(params.max_step_scale)
            and d_rot <= params.max_step_rot_deg)


def seed_ncc(seed_gray: np.ndarray, cur_gray: np.ndarray, matrix: np.ndarray,
             box: tuple[float, float, float, float], params: TrackParams) -> float:
    """NCC giữa frame seed đã warp theo ma trận và frame hiện tại, chỉ trên vành quanh hộp."""
    h, w = cur_gray.shape
    warped = cv2.warpAffine(seed_gray, matrix[:2].astype(np.float64), (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(np.full_like(seed_gray, 255), matrix[:2].astype(np.float64), (w, h))
    ring = _ring_mask(cur_gray.shape, matrix, box, params)
    sel = (ring > 0) & (valid > 200)
    if sel.sum() < 50:
        return 0.0
    a = warped[sel].astype(np.float64)
    b = cur_gray[sel].astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denom = math.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / denom) if denom > 0 else 0.0


def _track_direction(windows: list[np.ndarray], seed_idx: int, step: int,
                     box: tuple[float, float, float, float], params: TrackParams) -> dict[int, FrameTrack]:
    results: dict[int, FrameTrack] = {}
    key_idx = seed_idx
    key_m = np.eye(3)
    last_m = np.eye(3)
    pts_key = _detect(windows[seed_idx], key_m, box, params)
    pts_prev = pts_key.copy()
    prev = windows[seed_idx]
    end = len(windows) if step > 0 else -1
    for k in range(seed_idx + step, end, step):
        cur = windows[k]
        if len(pts_prev) < params.min_inliers:
            key_idx, key_m = k - step, last_m
            pts_key = _detect(prev, key_m, box, params)
            pts_prev = pts_key.copy()
        nxt, good = _flow(prev, cur, pts_prev, params) if len(pts_prev) else (pts_prev, np.zeros(0, bool))
        status, inliers, cur_m = "held", 0, last_m
        alive = int(good.sum())
        if alive >= params.min_inliers:
            src = pts_key[good].reshape(-1, 2)
            dst = nxt[good].reshape(-1, 2)
            affine, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                      ransacReprojThreshold=params.ransac_thr, confidence=0.995)
            if affine is not None:
                inliers = int(inl.sum())
                cand = np.vstack([affine, [0, 0, 1]]) @ key_m
                conf = (inliers / max(alive, 1)) * min(1.0, inliers / 30.0)
                if inliers >= params.min_inliers and conf >= params.min_conf and _step_ok(last_m, cand, box, params):
                    status, cur_m = "tracked", cand
                    keep = good.copy()
                    keep[good] = inl.reshape(-1) == 1
                    pts_key, nxt = pts_key[keep], nxt[keep]
        conf = (inliers / max(alive, 1)) * min(1.0, inliers / 30.0) if status == "tracked" else 0.0
        results[k] = FrameTrack(k, cur_m, status, conf, inliers, alive, key_idx,
                                seed_ncc(windows[seed_idx], cur, cur_m, box, params))
        if status == "tracked":
            pts_prev = nxt
            if len(pts_key) < params.rekey_inliers or abs(k - key_idx) >= params.rekey_every:
                key_idx, key_m = k, cur_m
                pts_key = _detect(cur, key_m, box, params)
                pts_prev = pts_key.copy()
        else:
            LOG.warning("frame %d: mất bám (alive=%d inliers=%d) → giữ ma trận frame trước", k, alive, inliers)
            key_idx, key_m = k, cur_m
            pts_key = _detect(cur, key_m, box, params)
            pts_prev = pts_key.copy()
        prev, last_m = cur, cur_m
    return results


def _interpolate_held(tracks: list[FrameTrack]) -> list[FrameTrack]:
    out = list(tracks)
    good = [i for i, t in enumerate(out) if t.status in ("seed", "tracked")]
    for a, b in zip(good, good[1:]):
        if b - a <= 1:
            continue
        pa, pb = decompose(out[a].matrix), decompose(out[b].matrix)
        for i in range(a + 1, b):
            t = (i - a) / (b - a)
            vals = [pa[j] + (pb[j] - pa[j]) * t for j in range(4)]
            out[i] = replace(out[i], matrix=compose(*vals), status="interpolated")
    return out


def _subpixel(res: np.ndarray, px: int, py: int) -> tuple[float, float]:
    def fit(left: float, mid: float, right: float) -> float:
        denom = left - 2 * mid + right
        return float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5)) if denom != 0 else 0.0
    dx = fit(res[py, px - 1], res[py, px], res[py, px + 1]) if 0 < px < res.shape[1] - 1 else 0.0
    dy = fit(res[py - 1, px], res[py, px], res[py + 1, px]) if 0 < py < res.shape[0] - 1 else 0.0
    return dx, dy


def ncc_peak_offset(seed_gray: np.ndarray, cur_gray: np.ndarray, matrix: np.ndarray,
                    box: tuple[float, float, float, float], params: TrackParams) -> tuple[float, float, float]:
    """Warp seed theo ma trận, lấy mảng vành quanh hộp (vùng glyph thay bằng median) làm mẫu,
    tìm đỉnh NCC trong ±radius trên frame hiện tại. Trả (dx, dy, score) theo toạ độ frame."""
    h, w = cur_gray.shape
    warped = cv2.warpAffine(seed_gray, matrix[:2].astype(np.float64), (w, h), flags=cv2.INTER_LINEAR)
    quad = transform_points(matrix, box_corners(box))
    cx, cy = quad.mean(axis=0)
    hw = (quad[:, 0].max() - quad[:, 0].min()) / 2
    hh = (quad[:, 1].max() - quad[:, 1].min()) / 2
    x0, y0 = int(cx - hw * params.ring_scale), int(cy - hh * params.ring_scale)
    x1, y1 = int(cx + hw * params.ring_scale), int(cy + hh * params.ring_scale)
    r = params.reanchor_radius
    if x0 - r < 0 or y0 - r < 0 or x1 + r > w or y1 + r > h:
        return 0.0, 0.0, 0.0
    patch = warped[y0:y1, x0:x1].copy()
    ix0, iy0 = int(cx - hw * params.inner_scale) - x0, int(cy - hh * params.inner_scale) - y0
    ix1, iy1 = int(cx + hw * params.inner_scale) - x0, int(cy + hh * params.inner_scale) - y0
    patch[max(0, iy0):iy1, max(0, ix0):ix1] = np.median(patch)
    search = cur_gray[y0 - r:y1 + r, x0 - r:x1 + r]
    res = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    sx, sy = _subpixel(res, loc[0], loc[1])
    return float(loc[0] - r + sx), float(loc[1] - r + sy), float(score)


def _reanchor(windows: list[np.ndarray], tracks: list[FrameTrack], seed_idx: int,
              box: tuple[float, float, float, float], params: TrackParams) -> list[FrameTrack]:
    raw = [(0.0, 0.0, 1.0) if t.index == seed_idx else ncc_peak_offset(windows[seed_idx], windows[t.index], t.matrix, box, params)
           for t in tracks]
    usable = np.array([[dx, dy] if s >= params.reanchor_min_score else [np.nan, np.nan] for dx, dy, s in raw])
    half = params.reanchor_median // 2
    out = []
    for i, t in enumerate(tracks):
        win = usable[max(0, i - half):i + half + 1]
        if np.isnan(usable[i]).any() or np.isnan(win).all():
            out.append(replace(t, ncc_peak=raw[i][2]))
            continue
        dx, dy = (float(v) for v in np.nanmedian(win, axis=0))
        shift = np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64)
        out.append(replace(t, matrix=shift @ t.matrix, ncc_peak=raw[i][2], reanchor_dx=dx, reanchor_dy=dy))
    return out


def track_sequence(windows: list[np.ndarray], seed_idx: int, box: tuple[float, float, float, float],
                   params: TrackParams) -> list[FrameTrack]:
    """windows: ảnh xám cùng kích thước cho mọi frame; box theo toạ độ cửa sổ."""
    if not 0 <= seed_idx < len(windows):
        raise ValueError("seed frame ngoài dải")
    seed = FrameTrack(seed_idx, np.eye(3), "seed", 1.0, 0, 0, seed_idx, 1.0)
    merged = {seed_idx: seed}
    merged.update(_track_direction(windows, seed_idx, +1, box, params))
    merged.update(_track_direction(windows, seed_idx, -1, box, params))
    ordered = _interpolate_held([merged[i] for i in range(len(windows))])
    if params.reanchor:
        ordered = _reanchor(windows, ordered, seed_idx, box, params)
    return [replace(t, ncc_seed=seed_ncc(windows[seed_idx], windows[t.index], t.matrix, box, params))
            if t.index != seed_idx else t for t in ordered]
