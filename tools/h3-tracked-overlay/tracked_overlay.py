#!/usr/bin/env python3
"""Tracked-overlay compositor cho clip H3 NEWTECONS — CPU thuần (OpenCV/NumPy/PIL).

Mục đích: H3 (diffusion) vẽ lại chữ/logo nhỏ ở mỗi khung nên chữ thêu trên áo và
logo mũ bị nhoè. Tool này KHÔNG dùng model sinh ảnh: nó bám (track) vùng vải/mũ
quanh mỗi mảnh, rồi dán (warp) một patch sạch — chữ vai trò render bằng font thật
hoặc logo đã duyệt — vào từng khung, khớp bóng sáng và hạt nhiễu cục bộ.

Thuật toán mỗi vùng:
  1. Khung 0: quad (TL,TR,BR,BL) do spec cấp. Cửa sổ ngữ cảnh = bbox quad nới
     thêm pad; vùng lõi (chữ nhoè) bị che khỏi dò feature vì nó đổi mỗi khung.
  2. Mỗi khung: LK pyramidal khung trước → khung này, kiểm tra xuôi-ngược (FB),
     rồi RANSAC khớp homography (≥ 12 inlier) → affine (≥ 8) → similarity (≥ 4).
     Ghép dồn: H(0→t) = H(t-1→t) · H(0→t-1). Bổ sung feature mới mỗi khung.
  3. Làm mượt thời gian: Gaussian σ (khung) trên quỹ đạo 4 góc quad.
  4. Vẽ: inpaint (Telea) vùng che để xoá chữ nhoè nhưng giữ bóng vải; warp patch
     RGBA độ phân giải cao vào khung; nhân độ sáng cục bộ; thêm hạt theo σ cục bộ.
  5. Ghi frame PNG → ffmpeg libx264, mux lại audio gốc (copy). Ghi mới, không đè.

Sai số báo cáo: trung bình residual inlier RANSAC (px) theo khung và theo vùng,
cộng độ dịch do làm mượt (px). Tool không tự tuyên bố PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

UNIT = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)


# ----------------------------------------------------------------------------- utils
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_new_json(path: Path, obj) -> None:
    with path.open("x", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def imread_any(path: Path, flags=cv2.IMREAD_UNCHANGED) -> np.ndarray:
    # cv2.imread không đọc được đường dẫn có dấu tiếng Việt trên Windows → đọc bytes.
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, flags)
    if img is None:
        raise ValueError(f"không đọc được ảnh: {path}")
    return img


class FrameStore:
    """Đọc khung từ đĩa theo chỉ số, giữ cache 3 khung gần nhất — RAM máy dùng chung với lane GPU
    (đo 01/11: 3,1 GB trống/65 GB) nên không giữ 107 khung màu + xám trong bộ nhớ."""

    def __init__(self, files: list[Path], gray: bool = False, keep: int = 3):
        self.files, self.gray, self.keep, self.cache = files, gray, keep, {}

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, t: int) -> np.ndarray:
        if t in self.cache:
            return self.cache[t]
        img = cv2.imread(str(self.files[t]), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"không đọc được khung {self.files[t]}")
        if self.gray:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.cache[t] = img
        for k in sorted(self.cache)[:-self.keep]:
            del self.cache[k]
        return img


def quad_bbox(q: np.ndarray, pad_x: float = 0, pad_y: float = 0, w: int = 0, h: int = 0):
    x0 = int(math.floor(q[:, 0].min() - pad_x))
    y0 = int(math.floor(q[:, 1].min() - pad_y))
    x1 = int(math.ceil(q[:, 0].max() + pad_x)) + 1
    y1 = int(math.ceil(q[:, 1].max() + pad_y)) + 1
    if w and h:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
    return x0, y0, x1, y1


def apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.hstack([pts, np.ones((len(pts), 1), dtype=np.float64)]) @ H.T
    return p[:, :2] / p[:, 2:3]


def to3x3(A: np.ndarray) -> np.ndarray:
    H = np.eye(3, dtype=np.float64)
    H[:2, :] = A
    return H


# ----------------------------------------------------------------------------- patches
def render_text_patch(text: str, font_path: Path, height_px: int, color=(255, 255, 255)) -> np.ndarray:
    """Patch RGBA (nền trong suốt) chứa chữ, cao đúng height_px kể cả dấu."""
    font = ImageFont.truetype(str(font_path), 200)
    l, t, r, b = font.getbbox(text)
    tw, th = r - l, b - t
    scale = height_px / th
    W, Hh = int(round(tw * scale)) + 8, int(round(th * scale)) + 8
    big = Image.new("RGBA", (tw + 8, th + 8), (0, 0, 0, 0))
    ImageDraw.Draw(big).text((4 - l, 4 - t), text, font=font, fill=(*color, 255))
    small = big.resize((W, Hh), Image.LANCZOS)
    return cv2.cvtColor(np.array(small), cv2.COLOR_RGBA2BGRA)


def load_logo_patch(path: Path) -> np.ndarray:
    img = imread_any(path, cv2.IMREAD_UNCHANGED)
    if img.ndim != 3 or img.shape[2] != 4:
        raise ValueError(f"asset phải RGBA: {path}")
    return img  # BGRA


def bend_uv(u: np.ndarray, theta: float) -> np.ndarray:
    """Uốn trụ như logo_composite.py: u∈[0,1] → u' theo góc theta (rad)."""
    if abs(theta) < 1e-6:
        return u
    s = math.sin(theta / 2)
    return 0.5 + np.arcsin(np.clip((2 * u - 1) * s, -0.999999, 0.999999)) / theta


# ----------------------------------------------------------------------------- tracking
class RegionTracker:
    def __init__(self, name: str, quad0: np.ndarray, pad: tuple[float, float], core_pad: float,
                 model: str, frame_wh: tuple[int, int], ctx_poly: list | None = None):
        self.name = name
        self.quad0 = quad0.astype(np.float64)
        self.pad = pad
        self.core_pad = core_pad
        self.ctx_poly = np.array(ctx_poly, dtype=np.float64) if ctx_poly else None
        self.model_pref = model
        self.W, self.H = frame_wh
        self.H0t = np.eye(3)
        self.pts = None  # Nx1x2 float32 trong khung hiện tại
        self.records: list[dict] = []
        self.lost_streak = 0
        self.last_rel = np.eye(3)  # chuyển động khung trước, dùng khi mất bám (tối đa 3 khung)

    # vùng ngữ cảnh / lõi tại khung t từ H0t hiện tại
    def windows(self, H0t: np.ndarray):
        q = apply_h(H0t, self.quad0)
        scale = math.sqrt(max(abs(cv2.contourArea(q.astype(np.float32))), 1.0) /
                          max(abs(cv2.contourArea(self.quad0.astype(np.float32))), 1.0))
        px, py = self.pad[0] * scale, self.pad[1] * scale
        ctx = quad_bbox(q, px, py, self.W, self.H)
        core = quad_bbox(q, self.core_pad * scale, self.core_pad * scale, self.W, self.H)
        return q, ctx, core, scale

    def detect(self, gray: np.ndarray, H0t: np.ndarray, existing: np.ndarray | None, want: int = 220):
        _, (x0, y0, x1, y1), (cx0, cy0, cx1, cy1), _ = self.windows(H0t)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return existing
        mask = np.zeros(gray.shape, np.uint8)
        if self.ctx_poly is not None:
            # mask đa giác (vd vỏ + vành mũ) mang theo H0t: loại feature nền ngoài vật;
            # co 4 px để không lấy "góc" trên đường viền vật-nền (nền chuyển động khác)
            poly = apply_h(H0t, self.ctx_poly)
            cv2.fillPoly(mask, [np.rint(poly).astype(np.int32).reshape(-1, 1, 2)], 255)
            mask = cv2.erode(mask, np.ones((9, 9), np.uint8))
        else:
            mask[y0:y1, x0:x1] = 255
            mask[cy0:cy1, cx0:cx1] = 0
        if existing is not None and len(existing):
            for p in existing.reshape(-1, 2):
                cv2.circle(mask, (int(p[0]), int(p[1])), 4, 0, -1)
            want = max(0, want - len(existing))
        if want <= 0:
            return existing
        new = cv2.goodFeaturesToTrack(gray, maxCorners=want, qualityLevel=0.01, minDistance=3,
                                      blockSize=5, mask=mask, useHarrisDetector=False)
        if new is None:
            return existing
        new = new.astype(np.float32)
        return new if existing is None or not len(existing) else np.concatenate([existing, new], axis=0)

    def init(self, gray0: np.ndarray):
        self.pts = self.detect(gray0, self.H0t, None)
        self.records.append({"frame": 0, "model": "identity", "inliers": int(len(self.pts) if self.pts is not None else 0),
                             "tracked_pts": int(len(self.pts) if self.pts is not None else 0),
                             "residual_px": 0.0, "lost": False, "quad": self.quad0.tolist()})

    def step(self, prev_gray: np.ndarray, gray: np.ndarray, t: int):
        rec = {"frame": t, "model": "hold", "inliers": 0, "tracked_pts": 0, "residual_px": None, "lost": True}
        Hrel = np.eye(3)
        if self.pts is not None and len(self.pts) >= 4:
            lk = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
            p1, st, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, self.pts, None, **lk)
            p0r, st2, _ = cv2.calcOpticalFlowPyrLK(gray, prev_gray, p1, None, **lk)
            fb = np.linalg.norm((self.pts - p0r).reshape(-1, 2), axis=1)
            ok = (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (fb < 0.8)
            inside = (p1[:, 0, 0] > 1) & (p1[:, 0, 0] < self.W - 2) & (p1[:, 0, 1] > 1) & (p1[:, 0, 1] < self.H - 2)
            ok &= inside
            src = self.pts[ok].reshape(-1, 2).astype(np.float64)
            dst = p1[ok].reshape(-1, 2).astype(np.float64)
            rec["tracked_pts"] = int(len(src))
            Hrel, model, inl, resid = self.fit(src, dst)
            if Hrel is not None:
                rec.update({"model": model, "inliers": int(inl.sum()), "residual_px": float(resid), "lost": False})
                self.pts = dst[inl].reshape(-1, 1, 2).astype(np.float32)
                self.lost_streak = 0
                self.last_rel = Hrel
            else:
                self.pts = dst.reshape(-1, 1, 2).astype(np.float32) if len(dst) else None
                self.lost_streak += 1
                Hrel = self.last_rel if self.lost_streak <= 3 else np.eye(3)
        else:
            self.lost_streak += 1
            Hrel = self.last_rel if self.lost_streak <= 3 else np.eye(3)
        self.H0t = Hrel @ self.H0t
        q = apply_h(self.H0t, self.quad0)
        rec["quad"] = q.tolist()
        self.records.append(rec)
        # bổ sung feature trong cửa sổ hiện tại (tránh lõi chữ)
        self.pts = self.detect(gray, self.H0t, self.pts)
        return rec

    def fit(self, src: np.ndarray, dst: np.ndarray):
        """Thứ tự ưu tiên theo model_pref; rơi xuống model ít tham số hơn khi thiếu inlier."""
        order = {"homography": ["homography", "affine", "similarity"],
                 "affine": ["affine", "similarity"],
                 "similarity": ["similarity"]}[self.model_pref]
        n = len(src)
        # ngưỡng inlier cao cho model nhiều bậc tự do: vùng đang ra khỏi khung (ít feature)
        # tự rơi về similarity thay vì homography "vặn" quad.
        for model in order:
            if model == "homography" and n >= 40:
                Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 1.5, maxIters=2000, confidence=0.995)
                if Hm is not None:
                    inl = inl.reshape(-1).astype(bool)
                    if inl.sum() >= 40 and self.sane(Hm):
                        return Hm, model, inl, self.resid(Hm, src[inl], dst[inl])
            elif model == "affine" and n >= 20:
                A, inl = cv2.estimateAffine2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=1.5,
                                              maxIters=2000, confidence=0.995, refineIters=10)
                if A is not None:
                    inl = inl.reshape(-1).astype(bool)
                    if inl.sum() >= 20:
                        Hm = to3x3(A)
                        if self.sane(Hm):
                            return Hm, model, inl, self.resid(Hm, src[inl], dst[inl])
            elif model == "similarity" and n >= 4:
                A, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=1.5,
                                                     maxIters=2000, confidence=0.995, refineIters=10)
                if A is not None:
                    inl = inl.reshape(-1).astype(bool)
                    if inl.sum() >= 4:
                        Hm = to3x3(A)
                        if self.sane(Hm):
                            return Hm, model, inl, self.resid(Hm, src[inl], dst[inl])
        return None, "hold", np.zeros(n, bool), float("nan")

    def sane(self, Hrel: np.ndarray) -> bool:
        """Chặn biến dạng vô lý trong một khung: diện tích quad đổi >25 %, góc lệch > 15°, hoặc lồi → lõm."""
        q_prev = apply_h(self.H0t, self.quad0).astype(np.float32)
        q_new = apply_h(Hrel @ self.H0t, self.quad0).astype(np.float32)
        a0, a1 = abs(cv2.contourArea(q_prev)), abs(cv2.contourArea(q_new))
        if a0 < 1 or a1 < 1 or not (0.75 < a1 / a0 < 1.33):
            return False
        if not cv2.isContourConvex(q_new.reshape(-1, 1, 2)):
            return False
        v0 = q_prev[1] - q_prev[0]
        v1 = q_new[1] - q_new[0]
        ang = abs(math.degrees(math.atan2(v1[1], v1[0]) - math.atan2(v0[1], v0[0])))
        ang = min(ang, 360 - ang)
        return ang < 15

    @staticmethod
    def resid(Hm, src, dst) -> float:
        if len(src) == 0:
            return float("nan")
        return float(np.linalg.norm(apply_h(Hm, src) - dst, axis=1).mean())


def quad_scale_rot(q: np.ndarray, q0: np.ndarray) -> tuple[float, float]:
    """Tỉ lệ (sqrt diện tích) và góc xoay (rad) của quad q so với q0."""
    a0 = max(abs(cv2.contourArea(q0.astype(np.float32))), 1.0)
    a1 = max(abs(cv2.contourArea(q.astype(np.float32))), 1.0)
    v0, v1 = q0[1] - q0[0], q[1] - q[0]
    rot = math.atan2(v1[1], v1[0]) - math.atan2(v0[1], v0[0])
    return math.sqrt(a1 / a0), rot


def colour_mask(bgr: np.ndarray, mode: str) -> np.ndarray:
    """Mask màu của vết logo H3: 'red' = chữ N đỏ, 'cyan' = wordmark xanh. uint8 0/255."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    if mode == "red":
        m = ((h <= 8) | (h >= 168)) & (s >= 110) & (v >= 90)
    elif mode == "cyan":
        m = (h >= 85) & (h <= 125) & (s >= 70) & (v >= 90)
    else:
        raise ValueError(mode)
    return (m.astype(np.uint8) * 255)


def blob_centroid(mask: np.ndarray, min_px: int) -> tuple[np.ndarray | None, int]:
    """Trọng tâm của thành phần liên thông lớn nhất trong mask (toạ độ cục bộ)."""
    n, lab, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None, 0
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[i, cv2.CC_STAT_AREA])
    if area < min_px:
        return None, area
    return cents[i].astype(np.float64), area


def bright_centroid(frame: np.ndarray, quad: np.ndarray, pad: tuple[float, float], min_px: int):
    """Trọng tâm điểm sáng (chữ thêu H3 vẽ) trong quad nới pad; ngưỡng = median nền + 35."""
    H, W = frame.shape[:2]
    x0, y0, x1, y1 = quad_bbox(quad, pad[0], pad[1], W, H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None, 0
    roi = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    c = quad.mean(axis=0)
    grown = c + (quad - c) * np.array([(quad[1, 0] - quad[0, 0] + 2 * pad[0]) / max(quad[1, 0] - quad[0, 0], 1),
                                       (quad[3, 1] - quad[0, 1] + 2 * pad[1]) / max(quad[3, 1] - quad[0, 1], 1)])
    mask = np.zeros(roi.shape, np.uint8)
    cv2.fillConvexPoly(mask, np.rint(grown - np.array([x0, y0])).astype(np.int32), 255)
    if not mask.any():
        return None, 0
    med = float(np.median(roi[mask > 0]))
    bright = ((roi.astype(np.float32) > med + 35) & (mask > 0)).astype(np.uint8)
    # vật sáng lạ (áo sơ mi, tay áo, vạch phản quang) kéo dài ra ngoài cửa sổ → thành phần
    # liên thông chạm biên cửa sổ bị loại; chữ thêu nằm gọn trong cửa sổ nên giữ lại.
    n, lab, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    border = np.zeros_like(mask)
    border[mask > 0] = 255
    border = cv2.morphologyEx(border, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    keep = np.zeros_like(bright, dtype=bool)
    for i in range(1, n):
        comp = lab == i
        if not (comp & border).any():
            keep |= comp
    ys, xs = np.nonzero(keep)
    if len(xs) < min_px:
        return None, int(len(xs))
    return np.array([xs.mean() + x0, ys.mean() + y0], np.float64), int(len(xs))


def anchor_text_chain(tr: "RegionTracker", frames: list[np.ndarray], cfg: dict) -> dict:
    """Chống trôi cho chuỗi LK: mỗi khung kéo TÂM quad về trọng tâm vết chữ H3 (blend), giữ
    chuyển động/tỉ lệ/hình quad từ chuỗi. Sửa thẳng vào tr.records[t]['quad']."""
    chain = np.array([rec["quad"] for rec in tr.records], dtype=np.float64)
    cc = chain.mean(axis=1)
    pad = tuple(cfg.get("pad", [6, 3]))
    min_px = int(cfg.get("min_px", 15))
    alpha = float(cfg.get("blend", 0.5))
    tr.raw_quads = chain.copy()  # chuỗi LK thô, dùng làm chuyển động cho logo mũ cùng người
    c0, n0 = bright_centroid(frames[0], chain[0], pad, min_px)
    if c0 is None:
        raise ValueError(f"{tr.name}: không thấy vết chữ sáng ở khung 0 (px={n0})")
    # hiệu tâm-quad / tâm-vết lấy TRUNG VỊ 5 khung đầu (một khung có thể bị vật sáng lạ lọt vào)
    rels, counts = [], []
    for t in range(min(5, len(chain))):
        s_t, _ = quad_scale_rot(chain[t], chain[0])
        c_t, n_t = bright_centroid(frames[t], chain[t], (pad[0] * s_t, pad[1] * s_t), min_px)
        if c_t is not None:
            rels.append((cc[t] - c_t) / s_t)
            counts.append(n_t / (s_t * s_t))
    rel0 = np.median(np.array(rels), axis=0)
    n0 = float(np.median(counts))
    center = cc[0].copy()
    offs, fallback = [], []
    lo, hi = cfg.get("px_ratio_gate", [0.35, 2.5])
    recent = [float(n0)]  # số điểm sáng đã chuẩn hoá theo scale² của các khung được chấp nhận gần nhất
    for t in range(1, len(chain)):
        pred = center + (cc[t] - cc[t - 1])
        scale, rot = quad_scale_rot(chain[t], chain[0])
        q_pred = chain[t] + (pred - cc[t])
        blob, n = bright_centroid(frames[t], q_pred, (pad[0] * scale, pad[1] * scale), min_px)
        gate = float(cfg.get("max_jump_px", 10)) * scale
        off = None
        # cổng số điểm sáng: so với TRUNG VỊ CHẠY của các khung đã chấp nhận (độ sáng chữ H3 đổi theo khung)
        expected = float(np.median(recent[-12:])) * scale * scale
        plausible = blob is not None and lo * expected <= n <= hi * expected
        n0 = expected
        if blob is not None:
            R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
            meas = blob + R @ (rel0 * scale)
            off = float(np.linalg.norm(meas - pred))
        if plausible and off <= gate:
            center = pred + alpha * (meas - pred)
            offs.append(off)
            recent.append(n / (scale * scale))
        else:
            # không thấy vết, hoặc vết nhảy quá cổng (vệt sáng lạ lọt cửa sổ) → đi theo chuỗi
            center = pred
            fallback.append(t)
        tr.records[t]["quad"] = (chain[t] + (center - cc[t])).tolist()
        if plausible and off <= gate:
            tr.records[t]["anchor"] = "bright"
        elif blob is None:
            tr.records[t]["anchor"] = "chain"
        elif not plausible:
            tr.records[t]["anchor"] = "chain(px %d vs expected %d)" % (n, int(expected))
        else:
            tr.records[t]["anchor"] = "chain(gated %.1f>%.1f)" % (off, gate)
        tr.records[t]["anchor_offset_px"] = off if tr.records[t]["anchor"] == "bright" else None
        tr.records[t]["anchor_offset_raw_px"] = off
        tr.records[t]["bright_px"] = n
    return {"anchor_mode": "bright centroid of H3 embroidery, blend %.2f" % alpha,
            "frames_anchored": len(offs), "frames_fallback_chain": fallback,
            "anchor_vs_prediction_px_mean": float(np.mean(offs)) if offs else None,
            "anchor_vs_prediction_px_max": float(np.max(offs)) if offs else None}


def shell_mask_from_poly(poly0: np.ndarray, q0: np.ndarray, qt: np.ndarray, frame_wh: tuple[int, int]) -> np.ndarray:
    """Đa giác vỏ mũ khung 0 mang theo phép biến đổi quad0→quad_t của tracker vỏ mũ → mask toàn khung.
    (Màu không tách được vỏ trắng khỏi trời hoàng hôn: đo f90 vỏ S 18–47/V 205–245, trời S 27–46/V 241–247.)"""
    Ht = cv2.getPerspectiveTransform(q0.astype(np.float32), qt.astype(np.float32))
    poly = apply_h(Ht, poly0)
    mask = np.zeros((frame_wh[1], frame_wh[0]), np.uint8)
    cv2.fillPoly(mask, [np.rint(poly).astype(np.int32).reshape(-1, 1, 2)], 255)
    return mask


class AnchorTracker:
    """Bám logo mũ: vị trí = trọng tâm vết N đỏ do H3 vẽ (mỗi khung); tỉ lệ/xoay/chuyển động = từ
    tracker `scale_from` (áo cùng người, hoặc tracker vỏ mũ đa giác). Mất vết → giữ tư thế theo
    tracker đó. Tuỳ chọn cfg['shell'] = {"poly_from": <tên tracker vỏ mũ>}: vết N đỏ phải CHẠM
    đa giác vỏ mũ mang theo; vết trôi ra nền (H3 vẽ logo rời mũ) bị loại."""

    def __init__(self, name: str, quad0: np.ndarray, cfg: dict, frame_wh: tuple[int, int]):
        self.name = name
        self.quad0 = quad0.astype(np.float64)
        self.center0 = self.quad0.mean(axis=0)
        self.cfg = cfg
        self.W, self.H = frame_wh
        self.records: list[dict] = []
        self.c_red0: np.ndarray | None = None
        self.ang0: float | None = None
        self.last_center: np.ndarray | None = None
        self.last_anchor_frame = 0
        self.shell_cfg = cfg.get("shell")

    def window(self, center: np.ndarray, scale: float):
        w = (self.quad0[1, 0] - self.quad0[0, 0]) * scale
        h = (self.quad0[3, 1] - self.quad0[0, 1]) * scale
        pad = float(self.cfg.get("search_pad", 16)) * scale
        x0 = int(max(0, math.floor(center[0] - w / 2 - pad)))
        y0 = int(max(0, math.floor(center[1] - h / 2 - pad)))
        x1 = int(min(self.W, math.ceil(center[0] + w / 2 + pad)))
        y1 = int(min(self.H, math.ceil(center[1] + h / 2 + pad)))
        return x0, y0, x1, y1, w, h

    def find(self, frame: np.ndarray, center: np.ndarray, scale: float, shell_mask: np.ndarray | None = None):
        x0, y0, x1, y1, w, h = self.window(center, scale)
        if x1 - x0 < 6 or y1 - y0 < 6:
            return None, None, 0
        roi = frame[y0:y1, x0:x1]
        red = colour_mask(roi, "red")
        if shell_mask is not None:
            # chỉ nhận vết N có ≥ 50 % điểm NẰM TRONG đa giác vỏ mũ; vết trôi ra nền (H3 vẽ logo rời mũ) bị loại
            inside = shell_mask[y0:y1, x0:x1] > 0
            n, lab = cv2.connectedComponents(red, connectivity=8)
            keep = np.zeros_like(red)
            for i in range(1, n):
                comp = lab == i
                if (comp & inside).sum() >= 0.5 * comp.sum():
                    keep[comp] = 255
            red = keep
        c_red, area = blob_centroid(red, int(self.cfg.get("min_px", 10)))
        if c_red is None:
            return None, None, area
        # vết N chạm mép KHUNG HÌNH (bị cắt) → trọng tâm lệch → không tin
        ys, xs = np.nonzero(red)
        if (y0 == 0 and ys.min() <= 1) or (x0 == 0 and xs.min() <= 1) or \
           (y1 == self.H and ys.max() >= y1 - y0 - 2) or (x1 == self.W and xs.max() >= x1 - x0 - 2):
            return None, None, -area
        c_red = c_red + np.array([x0, y0], np.float64)
        # wordmark: dải phía dưới chữ N
        cy_mask = colour_mask(roi, "cyan")
        band = np.zeros_like(cy_mask)
        bx0 = int(max(0, c_red[0] - 0.8 * w - x0)); bx1 = int(min(x1 - x0, c_red[0] + 0.8 * w - x0))
        by0 = int(max(0, c_red[1] + 0.25 * h - y0)); by1 = int(min(y1 - y0, c_red[1] + 1.2 * h - y0))
        if bx1 > bx0 and by1 > by0:
            band[by0:by1, bx0:bx1] = 255
        c_cy, _ = blob_centroid(cv2.bitwise_and(cy_mask, band), 6)
        if c_cy is not None:
            c_cy = c_cy + np.array([x0, y0], np.float64)
        return c_red, c_cy, area

    def init(self, frame0: np.ndarray, shell_mask: np.ndarray | None = None):
        c_red, c_cy, area = self.find(frame0, self.center0, 1.0, shell_mask)
        if c_red is None and self.shell_cfg:
            # H3 vẽ logo rời khỏi mũ ngay khung 0 → không có neo hợp lệ: logo đặt tay ở quad0,
            # đi theo tracker vỏ mũ suốt clip (giữ tư thế), không nhận vết đỏ nào
            self.c_red0 = None
            self.area0, self.recent, self.ang0 = 1, [1.0], None
            self.last_center = self.center0.copy()
            self.records.append({"frame": 0, "anchor": "no_valid_anchor_on_shell|hold_pose", "red_px": 0,
                                 "offset_px": None, "rot_deg": 0.0, "scale": 1.0, "quad": self.quad0.tolist()})
            return
        if c_red is None:
            raise ValueError(f"{self.name}: không thấy vết N đỏ ở khung 0 quanh {self.center0.tolist()} (area={area})")
        self.c_red0 = c_red
        self.area0 = max(area, 1)
        self.recent = [float(self.area0)]
        self.ang0 = math.atan2(*(c_cy - c_red)[::-1]) if c_cy is not None else None
        self.last_center = self.center0.copy()
        self.records.append({"frame": 0, "anchor": "red", "red_px": area, "offset_px": 0.0,
                             "rot_deg": 0.0, "scale": 1.0, "quad": self.quad0.tolist()})

    def step(self, frame: np.ndarray, t: int, scale: float, rot_vest: float, pred: np.ndarray,
             shell_mask: np.ndarray | None = None):
        """scale/rot_vest: từ tracker scale_from so với khung 0; pred: tâm dự đoán (ngoại suy similarity);
        shell_mask: đa giác vỏ mũ mang theo (nếu có) — vết N đỏ ngoài vỏ bị loại."""
        clamp = math.radians(float(self.cfg.get("rot_clamp_deg", 8)))
        rot = max(-clamp, min(clamp, rot_vest))
        shell_note = "shell_gate" if shell_mask is not None else ""
        if self.c_red0 is None:
            c_red, c_cy, area = None, None, 0  # không có neo khung 0 → giữ tư thế theo tracker vỏ mũ
        else:
            c_red, c_cy, area = self.find(frame, pred, scale, shell_mask)
        # xoay: lấy từ áo (cùng người), kẹp ±rot_clamp_deg; góc N→wordmark chỉ ghi nhận để tham khảo
        gate = float(self.cfg.get("max_jump_px", 12)) * scale
        lo, hi = self.cfg.get("px_ratio_gate", [0.3, 3.0])
        offset = None
        expected = float(np.median(self.recent[-12:])) * scale * scale
        plausible = c_red is not None and lo * expected <= area <= hi * expected
        if c_red is not None:
            rel0 = self.center0 - self.c_red0
            R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
            measured = c_red + R @ (rel0 * scale)
            offset = float(np.linalg.norm(measured - pred))
        if plausible and offset <= gate:
            # trộn đo với dự đoán: giảm ồn trọng tâm vết, vẫn chống trôi
            alpha = float(self.cfg.get("blend", 0.6))
            center = pred + alpha * (measured - pred)
            self.last_center = center
            self.last_anchor_frame = t
            self.recent.append(area / (scale * scale))
            anchor = "red+cyan" if c_cy is not None else "red"
        else:
            center = pred
            self.last_center = center
            if c_red is not None and not plausible:
                anchor = "vest_motion(red px %d vs expected %d)" % (area, int(expected))
            elif c_red is not None:
                anchor = "vest_motion(gated %.1f>%.1f)" % (offset, gate)
            else:
                anchor = "vest_motion" if area >= 0 else "vest_motion(blob clipped at frame edge)"
            area = abs(area)
        R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
        quad = center + (self.quad0 - self.center0) @ (R * scale).T
        if shell_note:
            anchor = f"{anchor}|{shell_note}"
        self.records.append({"frame": t, "anchor": anchor, "red_px": area, "offset_px": offset,
                             "rot_deg": math.degrees(rot), "scale": scale, "quad": quad.tolist()})
        return self.records[-1]


def smooth_quads(quads: np.ndarray, sigma: float) -> np.ndarray:
    """quads: T×4×2. Gaussian theo trục thời gian, biên phản xạ."""
    if sigma <= 0:
        return quads.copy()
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    T = quads.shape[0]
    padded = np.pad(quads, ((r, r), (0, 0), (0, 0)), mode="reflect")
    out = np.zeros_like(quads)
    for i in range(T):
        out[i] = np.tensordot(k, padded[i:i + 2 * r + 1], axes=(0, 0))
    return out


# ----------------------------------------------------------------------------- compositing
def smear_mask(frame: np.ndarray, cover_quad: np.ndarray, mode: str, grow: int | None = None) -> np.ndarray | None:
    """Mask (toàn khung, uint8) của vết chữ/logo nhoè H3 cần xoá thêm ngoài quad che.
    'bright': điểm sáng hơn nền vải (chữ thêu trắng); 'red_cyan': vết N đỏ + wordmark xanh."""
    if not mode:
        return None
    H, W = frame.shape[:2]
    win = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(win, np.rint(cover_quad).astype(np.int32), 255)
    if grow is None:
        grow = 4 if mode == "bright" else 6
    win = cv2.dilate(win, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    x0, y0, x1, y1 = quad_bbox(cover_quad, grow + 1, grow + 1, W, H)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    roi = frame[y0:y1, x0:x1]
    if mode == "bright":
        lum = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        med = float(np.median(lum[win[y0:y1, x0:x1] > 0]))
        m = (lum.astype(np.float32) > med + 35).astype(np.uint8) * 255
        m = cv2.dilate(m, np.ones((5, 5), np.uint8))
    elif mode == "red_cyan":
        m = cv2.bitwise_or(colour_mask(roi, "red"), colour_mask(roi, "cyan"))
        m = cv2.dilate(m, np.ones((7, 7), np.uint8))
    else:
        raise ValueError(mode)
    out = np.zeros((H, W), np.uint8)
    out[y0:y1, x0:x1] = cv2.bitwise_and(m, win[y0:y1, x0:x1])
    return out


def composite_region(frame: np.ndarray, patch_bgra: np.ndarray, quad: np.ndarray, cover_quad: np.ndarray,
                     curvature: float, seed: int, softness: float, inpaint_radius: int,
                     shade_floor: float, grain_gain: float, extra_cover: np.ndarray | None = None,
                     shade_ref_abs: float | None = None) -> tuple[np.ndarray, dict]:
    """Dán patch vào frame theo quad (TL,TR,BR,BL). Trả frame mới + số liệu.
    shade_ref_abs: nếu có, chuẩn sáng tuyệt đối (vd 240 cho vỏ mũ trắng) thay vì p90 của vành —
    để logo trên mặt mũ trong bóng cũng tối theo mũ."""
    H, W = frame.shape[:2]
    q = quad.astype(np.float32)
    cq = cover_quad.astype(np.float32)
    x0, y0, x1, y1 = quad_bbox(np.vstack([q, cq]), 6, 6, W, H)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return frame, {"skipped": "ngoài khung"}
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    rh, rw = roi.shape[:2]
    lq = q - np.array([x0, y0], np.float32)
    lcq = cq - np.array([x0, y0], np.float32)

    # 1) vùng che: inpaint Telea để xoá chữ/logo nhoè, giữ bóng vải/mũ
    cover = np.zeros((rh, rw), np.uint8)
    cv2.fillConvexPoly(cover, np.rint(lcq).astype(np.int32), 255)
    if extra_cover is not None:
        cover = cv2.bitwise_or(cover, extra_cover[y0:y1, x0:x1])
    cover_soft = cv2.GaussianBlur(cover.astype(np.float32) / 255.0, (0, 0), max(softness, 0.3))
    base_u8 = np.clip(roi, 0, 255).astype(np.uint8)
    inpainted = cv2.inpaint(base_u8, cover, inpaint_radius, cv2.INPAINT_TELEA).astype(np.float32)
    # làm mềm vùng inpaint một chút để không lộ vệt
    inpainted = cv2.GaussianBlur(inpainted, (0, 0), 0.8)
    a_cov = cover_soft[..., None]
    covered = roi * (1 - a_cov) + inpainted * a_cov

    # 2) warp patch (inverse map, có uốn trụ)
    Hp = cv2.getPerspectiveTransform(UNIT, lq)
    inv = np.linalg.inv(Hp)
    ph, pw = patch_bgra.shape[:2]
    # siêu lấy mẫu 2× để chữ nhỏ không răng cưa
    ss = 2
    yy2, xx2 = np.mgrid[0:rh * ss, 0:rw * ss].astype(np.float32) / ss
    d2 = np.stack([xx2, yy2, np.ones_like(xx2)], axis=-1) @ inv.T
    den2 = np.where(np.abs(d2[..., 2]) < 1e-8, 1e-8, d2[..., 2])
    u2 = bend_uv(d2[..., 0] / den2, curvature)
    v2 = d2[..., 1] / den2
    map_x = (u2 * (pw - 1)).astype(np.float32)
    map_y = (v2 * (ph - 1)).astype(np.float32)
    warped2 = cv2.remap(patch_bgra, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    warped = cv2.resize(warped2, (rw, rh), interpolation=cv2.INTER_AREA).astype(np.float32)
    inside = np.zeros((rh, rw), np.uint8)
    cv2.fillConvexPoly(inside, np.rint(lq).astype(np.int32), 255)
    inside = cv2.dilate(inside, np.ones((3, 3), np.uint8))
    alpha = (warped[..., 3] / 255.0) * (inside > 0)
    if softness > 0:
        alpha = cv2.GaussianBlur(alpha, (0, 0), softness)

    # 3) khớp bóng sáng: luminance mờ của NỀN ĐÃ CHE / p90 của vành quanh patch
    lum = cv2.cvtColor(np.clip(covered, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(lum, (0, 0), 2.0)
    ring = (cv2.dilate((alpha > 0.02).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0) & (alpha < 0.02)
    ref = max(float(np.percentile(blur[ring], 90)) if ring.any() else 255.0, 1.0)
    if shade_ref_abs is not None:
        ref = float(shade_ref_abs)
    shade = np.clip(blur / ref, shade_floor, 1.0)
    # 4) hạt: σ tần số cao của vành
    hp = lum - cv2.GaussianBlur(lum, (0, 0), 1.0)
    sigma = float(hp[ring].std()) if ring.any() else 0.0
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, sigma * grain_gain, size=(rh, rw, 1)).astype(np.float32)
    patch_rgb = warped[..., :3] * shade[..., None] + noise
    a = alpha[..., None]
    out_roi = covered * (1 - a) + np.clip(patch_rgb, 0, 255) * a
    out = frame.copy()
    out[y0:y1, x0:x1] = np.clip(np.rint(out_roi), 0, 255).astype(np.uint8)
    return out, {"bbox": [x0, y0, x1, y1], "shade_ref": ref, "grain_sigma": sigma,
                 "alpha_px": int((alpha > 0.5).sum())}


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path, help="thư mục tạm cho frame PNG (scratch)")
    ap.add_argument("--out", required=True, type=Path, help="mp4 đầu ra (ghi mới, không đè)")
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--track-json", required=True, type=Path)
    ap.add_argument("--preview", type=Path, default=None, help="mp4 vẽ quad bám lên clip gốc (tuỳ chọn)")
    ap.add_argument("--crf", type=int, default=14)
    args = ap.parse_args()

    for p in (args.out, args.receipt, args.track_json):
        if p.exists():
            raise FileExistsError(f"từ chối ghi đè: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
    if args.preview and args.preview.exists():
        raise FileExistsError(f"từ chối ghi đè: {args.preview}")

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    font_path = Path(spec["font"])
    if not font_path.is_file():
        raise FileNotFoundError(font_path)
    t_start = time.time()

    # decode toàn bộ frame (lossless từ h264) bằng ffmpeg để tracking ổn định
    frames_dir = args.work / "in"
    if not frames_dir.exists() or not any(frames_dir.glob("f_*.png")):
        frames_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(args.video), str(frames_dir / "f_%04d.png")], check=True)
    files = sorted(frames_dir.glob("f_*.png"))
    T = len(files)
    frames = FrameStore(files)
    grays = FrameStore(files, gray=True)
    H, W = frames[0].shape[:2]
    print(f"frames={T} size={W}x{H}", flush=True)

    # ---- quad chữ tự tính từ tâm + chiều cao (kể cả dấu) theo tỉ lệ thật của font
    for r in spec["regions"]:
        if r["kind"] == "text" and "quad" not in r:
            font = ImageFont.truetype(str(font_path), 200)
            l, t, rr, b = font.getbbox(r["text"])
            ratio = (rr - l) / (b - t)
            cx, cy = r["center"]
            hh = float(r["height_px"])
            ww = hh * ratio
            r["quad"] = [[cx - ww / 2, cy - hh / 2], [cx + ww / 2, cy - hh / 2],
                         [cx + ww / 2, cy + hh / 2], [cx - ww / 2, cy + hh / 2]]
            r["_font_ratio"] = ratio

    # ---- tracking: feature (LK + RANSAC) cho vùng áo; neo màu cho logo mũ
    trackers: dict[str, RegionTracker] = {}
    anchors: dict[str, AnchorTracker] = {}
    text_anchor_info: dict[str, dict] = {}
    for r in spec["regions"]:
        q0 = np.array(r["quad"], dtype=np.float64)
        if r.get("anchor", {}).get("mode", "red") == "red" and "anchor" in r:
            a = AnchorTracker(r["name"], q0, r["anchor"], (W, H))
            sm = None
            if a.shell_cfg:
                src_r = next(x for x in spec["regions"] if x["name"] == a.shell_cfg["poly_from"])
                sm = shell_mask_from_poly(np.array(src_r["ctx_poly"], np.float64), np.array(src_r["quad"], np.float64),
                                          np.array(src_r["quad"], np.float64), (W, H))
            a.init(frames[0], sm)
            anchors[r["name"]] = a
        else:
            tr = RegionTracker(r["name"], q0, tuple(r.get("ctx_pad", [40, 30])), float(r.get("core_pad", 4)),
                               r.get("model", "homography"), (W, H), r.get("ctx_poly"))
            tr.init(grays[0])
            trackers[r["name"]] = tr
    for t in range(1, T):
        for tr in trackers.values():
            tr.step(grays[t - 1], grays[t], t)
        if t % 20 == 0:
            print(f"track t={t}", flush=True)
    # chống trôi chuỗi LK: neo tâm vào vết chữ H3 (trước khi mũ dùng chuỗi áo làm chuyển động)
    for r in spec["regions"]:
        if r["name"] in trackers and r.get("anchor", {}).get("mode") == "bright":
            text_anchor_info[r["name"]] = anchor_text_chain(trackers[r["name"]], frames, r["anchor"])
    for name, a in anchors.items():
        src = trackers[a.cfg["scale_from"]]
        # chuyển động/tỉ lệ từ chuỗi LK THÔ của áo (mượt), không dùng quad đã neo (có bước nhảy hiệu chỉnh)
        q_src = getattr(src, "raw_quads", None)
        if q_src is None:
            q_src = np.array([rec["quad"] for rec in src.records], dtype=np.float64)
        c_src = q_src.mean(axis=1)
        poly_src = None
        if a.shell_cfg:
            src_r = next(x for x in spec["regions"] if x["name"] == a.shell_cfg["poly_from"])
            poly_src = (np.array(src_r["ctx_poly"], np.float64), np.array(src_r["quad"], np.float64))
            q_poly = getattr(trackers[src_r["name"]], "raw_quads", None)
            if q_poly is None:
                q_poly = np.array([rec["quad"] for rec in trackers[src_r["name"]].records], dtype=np.float64)
        for t in range(1, T):
            scale, rot = quad_scale_rot(q_src[t], q_src[0])
            s_prev, r_prev = quad_scale_rot(q_src[t - 1], q_src[0])
            ds, dr = scale / max(s_prev, 1e-6), rot - r_prev
            R = np.array([[math.cos(dr), -math.sin(dr)], [math.sin(dr), math.cos(dr)]])
            pred = c_src[t] + R @ ((a.last_center - c_src[t - 1]) * ds)
            sm = shell_mask_from_poly(poly_src[0], poly_src[1], q_poly[t], (W, H)) if poly_src else None
            a.step(frames[t], t, scale, rot, pred, sm)

    # ---- smoothing + metrics
    sigma_t = float(spec.get("smooth_sigma_frames", 1.0))
    region_out = []
    smoothed_quads = {}
    per_frame = {}
    for r in spec["regions"]:
        name = r["name"]
        if name in trackers:
            tr = trackers[name]
            raw = np.array([rec["quad"] for rec in tr.records], dtype=np.float64)  # T×4×2
            sm = smooth_quads(raw, sigma_t)
            resid = [rec["residual_px"] for rec in tr.records[1:] if rec["residual_px"] is not None and not math.isnan(rec["residual_px"])]
            lost = [rec["frame"] for rec in tr.records if rec["lost"] and rec["frame"] > 0]
            models = {}
            for rec in tr.records[1:]:
                models[rec["model"]] = models.get(rec["model"], 0) + 1
            info = {
                "name": name, "kind": r["kind"], "method": "LK pyramidal + FB check + RANSAC", "model_pref": tr.model_pref,
                "frames_total": T, "frames_fit": len(resid), "frames_lost_or_hold": lost,
                "models_used": models,
                "reprojection_px_mean": float(np.mean(resid)) if resid else None,
                "reprojection_px_max": float(np.max(resid)) if resid else None,
                "inliers_min": int(min(rec["inliers"] for rec in tr.records[1:])) if T > 1 else None,
                "inliers_mean": float(np.mean([rec["inliers"] for rec in tr.records[1:]])) if T > 1 else None,
            }
            info.update(text_anchor_info.get(name, {}))
            per_frame[name] = tr.records
        else:
            a = anchors[name]
            raw = np.array([rec["quad"] for rec in a.records], dtype=np.float64)
            sm = smooth_quads(raw, float(r["anchor"].get("smooth_sigma_frames", 1.5)))
            offs = [rec["offset_px"] for rec in a.records[1:] if rec["offset_px"] is not None and rec["anchor"].startswith("red")]
            fallback = [rec["frame"] for rec in a.records[1:] if rec["anchor"].startswith("vest_motion")]
            # jitter = khoảng cách tâm thô (neo màu) so với tâm đã làm mượt → độ ồn của neo
            jitter = np.linalg.norm(raw.mean(axis=1) - sm.mean(axis=1), axis=1)
            info = {
                "name": name, "kind": r["kind"],
                "method": f"colour anchor (red N centroid, cyan wordmark for rotation) + scale/rot from {a.cfg['scale_from']}",
                "frames_total": T, "frames_anchored": T - 1 - len(fallback), "frames_fallback_vest_motion": fallback,
                "anchor_vs_prediction_px_mean": float(np.mean(offs)) if offs else None,
                "anchor_vs_prediction_px_max": float(np.max(offs)) if offs else None,
                "anchor_jitter_px_mean": float(jitter.mean()), "anchor_jitter_px_max": float(jitter.max()),
                "red_px_min": int(min(rec["red_px"] for rec in a.records)),
                "scale_last": float(a.records[-1]["scale"]), "rot_deg_range": [float(min(rec["rot_deg"] for rec in a.records)), float(max(rec["rot_deg"] for rec in a.records))],
            }
            per_frame[name] = a.records
        smoothed_quads[name] = sm
        info["smoothing_displacement_px_mean"] = float(np.linalg.norm(sm - raw, axis=2).mean())
        info["quad_frame0"] = raw[0].tolist()
        info["quad_last"] = raw[-1].tolist()
        region_out.append(info)
    write_new_json(args.track_json, {"video": str(args.video), "video_sha256": sha256(args.video),
                                     "spec_sha256": sha256(args.spec), "smooth_sigma_frames": sigma_t,
                                     "regions": region_out, "per_frame": per_frame,
                                     "smoothed_quads": {k: v.tolist() for k, v in smoothed_quads.items()}})

    # ---- patches
    patches = {}
    for r in spec["regions"]:
        if r["kind"] == "track_only":
            continue
        if r["kind"] == "erase":
            # chỉ xoá (inpaint vùng che + mask vết), không dán gì: patch trong suốt
            patches[r["name"]] = np.zeros((4, 4, 4), np.uint8)
            continue
        if r["kind"] == "text":
            patches[r["name"]] = render_text_patch(r["text"], font_path, int(r.get("render_px", 160)),
                                                   tuple(r.get("color_rgb", [255, 255, 255])))
        else:
            patches[r["name"]] = load_logo_patch(ROOT / r["asset"])

    # ---- compositing
    out_dir = args.work / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()
    comp_stats = {r["name"]: [] for r in spec["regions"]}
    pv_dir = args.work / "preview"
    if args.preview:
        pv_dir.mkdir(exist_ok=True)
        for f in pv_dir.glob("*.png"):
            f.unlink()
    for t in range(T):
        frame = frames[t].copy()
        for i, r in enumerate(spec["regions"]):
            if r["kind"] == "track_only":
                continue
            q = smoothed_quads[r["name"]][t]
            # cover quad: quad nới thêm cover_pad (đơn vị px tại khung 0, nhân theo scale hiện tại)
            scale = math.sqrt(abs(cv2.contourArea(q.astype(np.float32))) / max(abs(cv2.contourArea(np.array(r["quad"], np.float32))), 1))
            cp = np.array(r.get("cover_pad", [3, 3]), np.float64) * scale
            c = q.mean(axis=0)
            ex = (q - c)
            # nới theo trục quad: cộng thêm cp theo hướng mỗi góc
            cover = q + np.sign(ex) * cp
            if "cover_quad" in r:
                cover = apply_h(cv2.getPerspectiveTransform(np.array(r["quad"], np.float32), q.astype(np.float32)),
                                np.array(r["cover_quad"], np.float64))
            vis = ((q[:, 0] >= -2) & (q[:, 0] <= W + 2) & (q[:, 1] >= -2) & (q[:, 1] <= H + 2)).sum()
            if vis == 0:
                comp_stats[r["name"]].append({"frame": t, "skipped": "ngoài khung"})
                continue
            extra = smear_mask(frames[t], cover, r.get("cover_mask", ""), r.get("smear_grow"))
            frame, st = composite_region(frame, patches[r["name"]], q, cover, float(r.get("curvature", 0.0)),
                                         20261101 + 1000 * i + t, float(r.get("softness", 0.55)),
                                         int(r.get("inpaint_radius", 3)), float(r.get("shade_floor", 0.45)),
                                         float(r.get("grain_gain", 1.0)), extra,
                                         r.get("shade_ref_abs"))
            st["smear_px"] = int((extra > 0).sum()) if extra is not None else 0
            st["frame"] = t
            comp_stats[r["name"]].append(st)
        cv2.imwrite(str(out_dir / f"f_{t + 1:04d}.png"), frame)
        if args.preview:
            pv = frames[t].copy()
            for r in spec["regions"]:
                q = smoothed_quads[r["name"]][t]
                cv2.polylines(pv, [np.rint(q).astype(np.int32).reshape(-1, 1, 2)], True, (0, 255, 0), 1)
                cv2.putText(pv, r["name"], (int(q[0, 0]), int(q[0, 1]) - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            cv2.imwrite(str(pv_dir / f"p_{t + 1:04d}.png"), pv)  # ghi ngay, không giữ trong RAM
        if t % 20 == 0:
            print(f"composite t={t}", flush=True)

    # ---- encode + mux audio gốc
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(args.video)]))
    has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
    vs = next(s for s in probe["streams"] if s["codec_type"] == "video")
    fps = vs["r_frame_rate"]
    cmd = ["ffmpeg", "-v", "error", "-n", "-framerate", fps, "-i", str(out_dir / "f_%04d.png")]
    if has_audio:
        cmd += ["-i", str(args.video), "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-preset", "slow", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "bt709", "-color_range", "tv",
            "-movflags", "+faststart", str(args.out)]
    subprocess.run(cmd, check=True)
    if args.preview:
        subprocess.run(["ffmpeg", "-v", "error", "-n", "-framerate", fps, "-i", str(pv_dir / "p_%04d.png"),
                        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(args.preview)], check=True)

    out_probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(args.out)]))
    receipt = {
        "tool": "H3-TRACKED-OVERLAY-V001/tracked_overlay.py", "status": "candidate_pending_review",
        "execution": "OpenCV/NumPy/PIL CPU only; no GPU; no generative model; inpaint = cv2.INPAINT_TELEA (PDE, deterministic)",
        "input_video": str(args.video), "input_sha256": sha256(args.video),
        "spec": str(args.spec), "spec_sha256": sha256(args.spec),
        "font": str(font_path), "font_sha256": sha256(font_path),
        "assets": {r["name"]: {"asset": r.get("asset"), "sha256": sha256(ROOT / r["asset"]) if r.get("asset") else None,
                               "text": r.get("text")} for r in spec["regions"]},
        "output": str(args.out), "output_sha256": sha256(args.out),
        "output_streams": [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "r_frame_rate", "nb_read_frames", "sample_rate", "channels")} for s in out_probe["streams"]],
        "audio_copied_from_source": has_audio,
        "tracking": region_out, "track_json": str(args.track_json),
        "composite_stats_summary": {k: {"frames_drawn": sum(1 for s in v if "bbox" in s), "frames_skipped": sum(1 for s in v if "skipped" in s)} for k, v in comp_stats.items()},
        "seconds": round(time.time() - t_start, 1),
        "python": sys.version.split()[0], "opencv": cv2.__version__, "numpy": np.__version__,
    }
    write_new_json(args.receipt, receipt)
    keys = ("name", "reprojection_px_mean", "reprojection_px_max", "inliers_min", "frames_lost_or_hold", "models_used",
            "frames_anchored", "frames_fallback_vest_motion", "frames_fallback_chain", "anchor_vs_prediction_px_mean", "anchor_vs_prediction_px_max",
            "anchor_jitter_px_mean", "red_px_min", "smoothing_displacement_px_mean")
    print(json.dumps({"output": str(args.out), "sha256": receipt["output_sha256"],
                      "tracking": [{k: v for k, v in r.items() if k in keys} for r in region_out]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
