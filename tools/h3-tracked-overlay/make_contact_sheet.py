#!/usr/bin/env python3
"""Bảng đối chiếu TRƯỚC/SAU 4 khung cho clip tracked-overlay (CPU, OpenCV).

Mỗi hàng = một khung: [gốc 1280→640] [sau 1280→640] [zoom 6 vùng: gốc trên, sau dưới].
Vị trí vùng lấy từ smoothed_quads trong track json nên zoom bám đúng vùng ở mọi khung.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def grab(video: Path, idx: int, work: Path) -> np.ndarray:
    out = work / f"{video.stem}_f{idx:03d}.png"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select='eq(n\\,{idx})'",
                        "-frames:v", "1", str(out)], check=True)
    img = cv2.imread(str(out), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"không đọc được khung {idx} của {video}")
    return img


def crop_zoom(img: np.ndarray, quad: np.ndarray, pad: int, zoom_w: int, zoom_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    x0 = max(0, int(quad[:, 0].min()) - pad)
    y0 = max(0, int(quad[:, 1].min()) - pad)
    x1 = min(w, int(quad[:, 0].max()) + pad + 1)
    y1 = min(h, int(quad[:, 1].max()) + pad + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return np.full((zoom_h, zoom_w, 3), 40, np.uint8)
    c = img[y0:y1, x0:x1]
    return cv2.resize(c, (zoom_w, zoom_h), interpolation=cv2.INTER_CUBIC)


def label(img: np.ndarray, text: str, org=(6, 18), color=(0, 255, 255)) -> np.ndarray:
    out = img.copy()
    cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1, cv2.LINE_AA)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", required=True, type=Path)
    ap.add_argument("--after", required=True, type=Path)
    ap.add_argument("--track-json", required=True, type=Path)
    ap.add_argument("--frames", default="0,35,70,106")
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists():
        raise FileExistsError(f"từ chối ghi đè: {args.out}")
    args.work.mkdir(parents=True, exist_ok=True)
    track = json.loads(args.track_json.read_text(encoding="utf-8"))
    names = [r["name"] for r in track["regions"]]
    quads = {k: np.array(v, dtype=np.float64) for k, v in track["smoothed_quads"].items()}
    idxs = [int(x) for x in args.frames.split(",")]

    ZW, ZH, PAD = 176, 88, 8
    rows = []
    for idx in idxs:
        b = grab(args.before, idx, args.work)
        a = grab(args.after, idx, args.work)
        bs = label(cv2.resize(b, (640, 352), interpolation=cv2.INTER_AREA), f"TRUOC  frame {idx}")
        as_ = label(cv2.resize(a, (640, 352), interpolation=cv2.INTER_AREA), f"SAU  frame {idx}", color=(0, 255, 0))
        cols = []
        for n in names:
            q = quads[n][idx]
            zb = label(crop_zoom(b, q, PAD, ZW, ZH), n, (4, 14), (0, 255, 255))
            za = label(crop_zoom(a, q, PAD, ZW, ZH), "", (4, 14))
            col = np.vstack([zb, np.full((4, ZW, 3), 255, np.uint8), za])
            cols.append(col)
            cols.append(np.full((col.shape[0], 4, 3), 255, np.uint8))
        zoom = np.hstack(cols[:-1])
        zh = zoom.shape[0]
        panel = np.full((352, zoom.shape[1], 3), 20, np.uint8)
        panel[(352 - zh) // 2:(352 - zh) // 2 + zh, :] = zoom
        row = np.hstack([bs, np.full((352, 4, 3), 255, np.uint8), as_, np.full((352, 4, 3), 255, np.uint8), panel])
        rows.append(row)
        rows.append(np.full((6, row.shape[1], 3), 255, np.uint8))
    sheet = np.vstack(rows[:-1])
    ok, enc = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("encode thất bại")
    with args.out.open("xb") as f:
        f.write(enc.tobytes())
    print(json.dumps({"out": str(args.out), "size_wh": [sheet.shape[1], sheet.shape[0]], "frames": idxs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
