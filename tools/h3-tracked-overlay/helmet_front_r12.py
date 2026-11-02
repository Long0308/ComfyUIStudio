#!/usr/bin/env python3
"""r12 — logo mũ CHỈ Ở MẶT TRƯỚC, theo canon user ("logo nón chỉ có phía trước nón, bên hông trái phải đều không có";
Blender v004 helmet_front / helmet_3q_left). Pass 2 sau tracked_overlay (pass 1 = chữ + xoá vết lạc + tracker vỏ mũ).

Mỗi người, mỗi khung:
  1. Vỏ mũ = đa giác khung 0 mang theo tracker similarity (track json pass 1) → tâm C, bán kính r (nửa bề rộng đa giác).
  2. Yaw đầu (°, + = quay về bên phải khung) — KHÔNG có model landmark cục bộ (mediapipe/insightface/dlib/Haar/YuNet
     đều không có trên máy, không tải): dùng proxy hình học = trọng tâm vùng DA MẶT dưới vành mũ so với tâm vỏ:
     d = (x_mặt − C_x)/r, yaw = asin(clip(d/0.6)). Lọc trung vị 5 + Gaussian σ2 theo thời gian. Sai số ước ±15°.
  3. Xoá MỌI vết logo H3 (đỏ ∪ xanh) trong đa giác vỏ mũ bằng inpaint Telea.
  4. Dán logo lên điểm MẶT TRƯỚC: chiếu trụ/cầu — pixel (x,y) → θ = asin((x−C_x)/r_lat), u = ½ + (θ − yaw)/Δ;
     Δ = góc mở logo (chord 0,62 r); alpha_bề_mặt = cos θ (mờ dần ở viền); alpha_luật: |yaw|<30° → 1;
     30–70° → cos(yaw)/cos30°; >70° → 0 (profile: không thấy logo). Vị trí dọc = C_y + 0,40 r (ngay trên vành, như canon).
  5. Ghi frame → ffmpeg libx264 crf 14, mux audio gốc (copy). Ghi mới, không đè.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOGO = ROOT / "docs/media-stage/S07-PPE-ANCHORS-V004/helmet_logo_rgba.png"
PERSONS = {  # tên tracker vỏ mũ, hướng mặt ban đầu (+1 phải / −1 trái) chỉ để chọn dấu khi vùng da mơ hồ
    "LA": {"shell": "LA_shell", "sign": +1},
    "HM": {"shell": "HM_shell", "sign": -1},
    "CHT": {"shell": "CHT_shell", "sign": -1},
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def apply_h(H, pts):
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def smear_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    red = ((h <= 8) | (h >= 168)) & (s >= 110) & (v >= 90)
    cyan = (h >= 85) & (h <= 125) & (s >= 70) & (v >= 90)
    return ((red | cyan).astype(np.uint8)) * 255


def skin_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = ((h <= 25) | (h >= 170)) & (s >= 50) & (s <= 185) & (v >= 80)
    return m.astype(np.uint8) * 255


def dome_geometry(poly: np.ndarray):
    """Tâm và bán kính vỏ: tâm x = giữa bề rộng, tâm y = đỉnh + bán kính; r = nửa bề rộng."""
    x0, x1 = poly[:, 0].min(), poly[:, 0].max()
    r = (x1 - x0) / 2
    return np.array([(x0 + x1) / 2, poly[:, 1].min() + r]), r


def refine_dome(frame: np.ndarray, C: np.ndarray, r: float):
    """Chỉnh tâm/bán kính vỏ theo dải TRẮNG thực tế trên hàng y = C_y − 0,2 r (quét từ tâm ra hai bên tới khi
    hết trắng 3 px liên tiếp). Chỉ nhận nếu bề rộng đo trong 0,7–1,4× r mang theo; không thì giữ tracker."""
    H, W = frame.shape[:2]
    y = int(round(C[1] - 0.2 * r))
    if not (0 <= y < H):
        return C, r, False
    hsv = cv2.cvtColor(frame[y:y + 1], cv2.COLOR_BGR2HSV)[0]
    white = (hsv[:, 1] < 90) & (hsv[:, 2] > 120)   # vỏ trắng kể cả mặt trong bóng (đo f90: V 179–245, S ≤ 47; bóng S tới 116 loại)
    cx = int(round(C[0]))
    if not (0 <= cx < W):
        return C, r, False
    if not white[cx]:  # tâm rơi vào vết logo/bóng: tìm điểm trắng gần nhất trong 12 px
        near = [x for x in range(max(0, cx - 12), min(W, cx + 13)) if white[x]]
        if not near:
            return C, r, False
        cx = min(near, key=lambda x: abs(x - cx))
    def run(step):
        x, miss = cx, 0
        while 0 <= x + step < W:
            x += step
            miss = miss + 1 if not white[x] else 0
            if miss >= 6:
                return x - step * 6
        return x
    xl, xr = run(-1), run(+1)
    span = xr - xl
    if 0.7 * 2 * r <= span <= 1.4 * 2 * r:
        return np.array([(xl + xr) / 2.0, C[1]]), span / 2.0, True
    return C, r, False


def estimate_yaw(frame: np.ndarray, C: np.ndarray, r: float, sign0: int):
    H, W = frame.shape[:2]
    # cửa sổ MẶT ngay dưới vành: hẹp (±1,05 r ngang, 0,6–1,6 r dọc) để không ăn mặt/tay người bên cạnh
    x0, x1 = int(max(0, C[0] - 1.05 * r)), int(min(W, C[0] + 1.05 * r))
    y0, y1 = int(max(0, C[1] + 0.6 * r)), int(min(H, C[1] + 1.6 * r))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None, 0
    m = skin_mask(frame[y0:y1, x0:x1])
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return None, 0
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = int(stats[i, cv2.CC_STAT_AREA])
    if area < 0.04 * r * r:
        return None, area
    fx = cents[i][0] + x0
    d = (fx - C[0]) / r
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, d / 0.6))))
    return yaw, area


def smooth_series(vals: list, sigma: float = 2.0):
    arr = np.array([np.nan if v is None else v for v in vals], dtype=np.float64)
    idx = np.arange(len(arr))
    ok = ~np.isnan(arr)
    if ok.sum() == 0:
        return np.zeros_like(arr), ok
    arr = np.interp(idx, idx[ok], arr[ok])
    # trung vị 5
    pad = np.pad(arr, 2, mode="edge")
    arr = np.array([np.median(pad[i:i + 5]) for i in range(len(arr))])
    rr = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-rr, rr + 1) / sigma) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(arr, rr, mode="edge"), k, mode="valid"), ok


def rule_alpha(yaw_deg: float) -> float:
    a = abs(yaw_deg)
    if a < 30:
        return 1.0
    if a > 70:
        return 0.0
    return math.cos(math.radians(a)) / math.cos(math.radians(30))


def draw_front_logo(frame: np.ndarray, logo: np.ndarray, C: np.ndarray, r: float, yaw_deg: float, seed: int):
    """Chiếu cầu/trụ logo lên điểm mặt trước. Trả frame mới + bbox + alpha luật."""
    a_rule = rule_alpha(yaw_deg)
    if a_rule <= 0:
        return frame, None, 0.0
    H, W = frame.shape[:2]
    yaw = math.radians(yaw_deg)
    r_lat = 0.92 * r                      # bán kính ngang tại vĩ độ logo (0,40 r dưới tâm)
    chord = 0.62 * r
    delta = 2 * math.asin(min(0.999, chord / (2 * r_lat)))   # góc mở logo
    lh, lw = logo.shape[:2]
    h_px = chord / (lw / lh)              # cao logo theo tỉ lệ asset
    yc = C[1] + 0.40 * r
    x0, x1 = int(max(0, C[0] - r_lat - 2)), int(min(W, C[0] + r_lat + 3))
    y0, y1 = int(max(0, yc - h_px / 2 - 3)), int(min(H, yc + h_px / 2 + 4))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return frame, None, a_rule
    ss = 2
    yy, xx = np.mgrid[0:(y1 - y0) * ss, 0:(x1 - x0) * ss].astype(np.float32) / ss
    X = xx + x0
    Y = yy + y0
    s = (X - C[0]) / r_lat
    valid = np.abs(s) < 0.999
    theta = np.arcsin(np.clip(s, -0.999, 0.999))
    u = 0.5 + (theta - yaw) / delta
    v = (Y - (yc - h_px / 2)) / h_px
    inside = valid & (u >= 0) & (u <= 1) & (v >= 0) & (v <= 1)
    map_x = (u * (lw - 1)).astype(np.float32)
    map_y = (v * (lh - 1)).astype(np.float32)
    warped = cv2.remap(logo, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)).astype(np.float32)
    facing = np.clip(np.cos(theta), 0, 1) ** 0.5          # mờ dần về viền silhouette
    alpha2 = (warped[..., 3] / 255.0) * inside * facing * a_rule
    warped = cv2.resize(warped, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(alpha2, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.6)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    lum = cv2.cvtColor(roi.astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    shade = np.clip(cv2.GaussianBlur(lum, (0, 0), 2.0) / 240.0, 0.5, 1.0)
    hp = lum - cv2.GaussianBlur(lum, (0, 0), 1.0)
    ring = (cv2.dilate((alpha > 0.02).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0) & (alpha < 0.02)
    sigma = float(hp[ring].std()) if ring.any() else 0.0
    noise = np.random.default_rng(seed).normal(0, sigma, size=(y1 - y0, x1 - x0, 1)).astype(np.float32)
    rgb = warped[..., :3] * shade[..., None] + noise
    a = alpha[..., None]
    out = frame.copy()
    out[y0:y1, x0:x1] = np.clip(np.rint(roi * (1 - a) + np.clip(rgb, 0, 255) * a), 0, 255).astype(np.uint8)
    return out, [x0, y0, x1, y1], a_rule


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-frames", required=True, type=Path, help="thư mục f_%%04d.png của pass 1 (đã có chữ, chưa có logo mũ)")
    ap.add_argument("--orig-video", required=True, type=Path)
    ap.add_argument("--track-json", required=True, type=Path)
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--out-frames", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--yaw-json", required=True, type=Path)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--yaw-keyframes", type=Path, default=None,
                    help="JSON {who: [[frame, yaw_deg], ...]} ĐO TAY — ghi đè yaw tự động (proxy da mặt sai dấu trên clip này); nội suy tuyến tính")
    args = ap.parse_args()
    for p in (args.out, args.yaw_json, args.receipt):
        if p.exists():
            raise FileExistsError(f"từ chối ghi đè: {p}")
        p.parent.mkdir(parents=True, exist_ok=True)
    args.out_frames.mkdir(parents=True, exist_ok=True)
    track = json.loads(args.track_json.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    logo = cv2.imdecode(np.fromfile(str(LOGO), np.uint8), cv2.IMREAD_UNCHANGED)
    files = sorted(args.base_frames.glob("f_*.png"))
    T = len(files)
    geo = {}
    for who, cfg in PERSONS.items():
        r = next(x for x in spec["regions"] if x["name"] == cfg["shell"])
        poly0 = np.array(r["ctx_poly"], np.float64)
        q0 = np.array(r["quad"], np.float32)
        quads = np.array(track["smoothed_quads"][cfg["shell"]], np.float64)
        polys = [apply_h(cv2.getPerspectiveTransform(q0, quads[t].astype(np.float32)), poly0) for t in range(T)]
        geo[who] = polys
    # ---- yaw
    yaw_raw = {who: [] for who in PERSONS}
    skin_px = {who: [] for who in PERSONS}
    dome = {who: [] for who in PERSONS}
    for t in range(T):
        frame = cv2.imread(str(files[t]))
        for who, cfg in PERSONS.items():
            C, r = dome_geometry(geo[who][t])
            C, r, refined = refine_dome(frame, C, r)
            dome[who].append((C, r, refined))
            y, area = estimate_yaw(frame, C, r, cfg["sign"])
            yaw_raw[who].append(y)
            skin_px[who].append(area)
    # làm mượt tâm/bán kính vỏ theo thời gian (σ 1,5 khung)
    for who in PERSONS:
        cx, _ = smooth_series([c[0][0] for c in dome[who]], 1.5)
        cy, _ = smooth_series([c[0][1] for c in dome[who]], 1.5)
        rr, _ = smooth_series([c[1] for c in dome[who]], 1.5)
        dome[who] = [(np.array([cx[t], cy[t]]), float(rr[t]), dome[who][t][2]) for t in range(T)]
    yaw = {}
    keyf = json.loads(args.yaw_keyframes.read_text(encoding="utf-8")) if args.yaw_keyframes else None
    for who in PERSONS:
        sm, ok = smooth_series(yaw_raw[who])
        yaw[who] = {"raw": yaw_raw[who], "auto_smooth": [float(v) for v in sm], "measured_frames": int(ok.sum()),
                    "auto_method": "skin-centroid vs dome centre proxy, yaw=asin(d/0.6), median5+gauss2 — KHÔNG tin được trên clip này (sai dấu LA/HM), chỉ ghi để so"}
        if keyf and who in keyf:
            kf = np.array(keyf[who], dtype=np.float64)
            yaw[who]["smooth"] = [float(v) for v in np.interp(np.arange(T), kf[:, 0], kf[:, 1])]
            yaw[who]["method"] = "HAND-MEASURED keyframes (đo tay từ khung, ±10°), nội suy tuyến tính"
        else:
            yaw[who]["smooth"] = yaw[who]["auto_smooth"]
            yaw[who]["method"] = yaw[who]["auto_method"]
    # ---- composite
    stats = {who: [] for who in PERSONS}
    for t in range(T):
        frame = cv2.imread(str(files[t]))
        H, W = frame.shape[:2]
        for i, (who, cfg) in enumerate(PERSONS.items()):
            poly = geo[who][t]
            C, r, refined = dome[who][t]
            # 1) xoá mọi vết logo H3 trong vỏ mũ (đa giác nở 6 px)
            mask = np.zeros((H, W), np.uint8)
            cv2.fillPoly(mask, [np.rint(poly).astype(np.int32).reshape(-1, 1, 2)], 255)
            mask = cv2.dilate(mask, np.ones((13, 13), np.uint8))
            sm = cv2.bitwise_and(smear_mask(frame), mask)
            sm = cv2.dilate(sm, np.ones((9, 9), np.uint8))
            erased = int((sm > 0).sum())
            if erased:
                frame = cv2.inpaint(frame, sm, 4, cv2.INPAINT_TELEA)
            # 2) logo mặt trước theo yaw
            yv = yaw[who]["smooth"][t]
            vis = ((poly[:, 0] >= 0) & (poly[:, 0] <= W)).sum() >= 3
            bbox, a_rule = None, 0.0
            if vis:
                frame, bbox, a_rule = draw_front_logo(frame, logo, C, r, yv, 20261101 + 1000 * i + t)
            stats[who].append({"frame": t, "yaw_deg": round(yv, 1), "alpha_rule": round(a_rule, 3), "erased_px": erased, "dome_refined": bool(refined),
                               "dome_centre": [round(float(C[0]), 1), round(float(C[1]), 1)], "r": round(float(r), 1), "bbox": bbox})
        cv2.imwrite(str(args.out_frames / f"f_{t + 1:04d}.png"), frame)
        if t % 20 == 0:
            print(f"r12 t={t}", flush=True)
    args.yaw_json.write_text(json.dumps({"yaw": yaw, "per_frame": stats}, ensure_ascii=False, indent=1), encoding="utf-8")
    probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(args.orig_video)]))
    fps = next(s for s in probe["streams"] if s["codec_type"] == "video")["r_frame_rate"]
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-framerate", fps, "-i", str(args.out_frames / "f_%04d.png"), "-i", str(args.orig_video),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:a", "copy", "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "bt709", "-color_range", "tv",
                    "-movflags", "+faststart", str(args.out)], check=True)
    receipt = {"tool": "H3-TRACKED-OVERLAY-V001/helmet_front_r12.py", "status": "candidate_pending_review",
               "canon": "logo chỉ mặt trước mũ (user 2026-11-01); Blender v004 helmet_front/helmet_3q_left",
               "base_track_json": str(args.track_json), "spec": str(args.spec), "logo_asset": str(LOGO), "logo_sha256": sha256(LOGO),
               "output": str(args.out), "output_sha256": sha256(args.out), "yaw_json": str(args.yaw_json),
               "yaw_summary": {who: {"min": round(min(v["smooth"]), 1), "max": round(max(v["smooth"]), 1), "measured_frames": v["measured_frames"],
                                     "frames_logo_visible": sum(1 for s in stats[who] if s["alpha_rule"] > 0),
                                     "frames_logo_hidden_profile": sum(1 for s in stats[who] if s["alpha_rule"] == 0)} for who, v in yaw.items()},
               "execution": "OpenCV/NumPy CPU; no GPU; no generative model; inpaint Telea"}
    args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": receipt["output_sha256"], "yaw_summary": receipt["yaw_summary"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
