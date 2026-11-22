"""Ghép màn hình động (bản đồ VN + 2 quần đảo + KPI đỏ nháy) vào video Topview quay trên màn XANH.

  python video_screen.py <raw.mp4> <layout k1|k2> <out.mp4> [--blur PX]

Mỗi khung: tìm vùng xanh → hộp màn hình (làm mượt trung vị 9 khung, bám máy đẩy vào) → render_screen.frame(layout, t)
→ khoá nền mềm + gỡ trộn (như composite_screen.py) → mã hoá H.264, giữ nguyên tiếng gốc."""
from __future__ import annotations

import json, shutil, subprocess, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_screen as rs  # noqa: E402

MAP_BG = (6, 18, 42)


def green_of(im: np.ndarray) -> np.ndarray:
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    return (g > 110) & (g > r + 50) & (g > b + 50)


def bbox(green: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(green)
    if len(xs) < 2000:
        return None
    x0, x1 = np.percentile(xs, [0.3, 99.7]); y0, y1 = np.percentile(ys, [0.3, 99.7])
    return int(x0), int(y0), int(x1), int(y1)


def comp(im: np.ndarray, green: np.ndarray, box: tuple[int, int, int, int], plate: Image.Image, blur: float) -> np.ndarray:
    x0, y0, x1, y1 = box; sw, sh = x1 - x0 + 1, y1 - y0 + 1
    k = min(sw / plate.width, sh / plate.height)
    mp = plate.resize((max(1, int(plate.width * k)), max(1, int(plate.height * k))), Image.LANCZOS)
    pl = Image.new("RGB", (sw, sh), MAP_BG); pl.paste(mp, ((sw - mp.width) // 2, (sh - mp.height) // 2))
    if blur > 0:
        pl = pl.filter(ImageFilter.GaussianBlur(blur))
    full = Image.new("RGB", (im.shape[1], im.shape[0]), MAP_BG); full.paste(pl, (x0, y0))
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    inbox = np.zeros(green.shape, bool); inbox[max(0, y0 - 4):y1 + 5, max(0, x0 - 4):x1 + 5] = True
    K = np.median(im[green], axis=0).astype(np.float32)
    ex = (g - np.maximum(r, b)).astype(np.float32); kex = max(30.0, float(K[1] - max(K[0], K[2])))
    a = np.clip((ex - 12.0) / (kex - 12.0), 0, 1) * inbox
    a = np.where(a > 0.93, 1.0, a)[..., None].astype(np.float32)
    I = im.astype(np.float32); M = np.asarray(full).astype(np.float32)
    F = np.where(a < 0.999, (I - a * K) / np.maximum(1 - a, 1e-3), 0)
    F[..., 1] = np.minimum(F[..., 1], (F[..., 0] + F[..., 2]) / 2 + 4)
    return np.clip(np.where(a > 0, (1 - a) * F + a * M, I), 0, 255).astype(np.uint8)


def main(src: str, layout: str, dst: str, blur: float) -> None:
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                                       "-of", "json", src], capture_output=True, text=True, check=True).stdout)
    n, d = probe["streams"][0]["r_frame_rate"].split("/"); fps = float(n) / float(d)
    tmp = Path(tempfile.mkdtemp(prefix="s04scr_"))
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-i", src, str(tmp / "in_%04d.png")], check=True)
        files = sorted(tmp.glob("in_*.png")); frames = [np.asarray(Image.open(f).convert("RGB")).astype(np.int32) for f in files]
        greens = [green_of(f) for f in frames]; boxes = [bbox(g) for g in greens]
        valid = [b for b in boxes if b]
        if not valid:
            raise SystemExit("không thấy màn xanh trong video")
        arr = np.array([b if b else valid[0] for b in boxes], dtype=float); sm = arr.copy()
        for i in range(len(arr)):
            lo, hi = max(0, i - 4), min(len(arr), i + 5); sm[i] = np.median(arr[lo:hi], axis=0)
        drift = (arr.max(axis=0) - arr.min(axis=0)).tolist()
        for i, (f, g) in enumerate(zip(frames, greens)):
            out = comp(f, g, tuple(int(v) for v in sm[i]), rs.frame(layout, i / fps), blur)
            Image.fromarray(out).save(tmp / f"out_{i + 1:04d}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps}", "-i", str(tmp / "out_%04d.png"), "-i", src,
                        "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", dst], check=True)
        print(json.dumps({"ok": True, "out": dst, "frames": len(frames), "fps": fps, "frames_without_green": sum(b is None for b in boxes),
                          "box_first": [int(v) for v in sm[0]], "box_last": [int(v) for v in sm[-1]], "box_range_px": [round(x) for x in drift]}))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = sys.argv[1:]; blur = 0.0
    if "--blur" in a:
        i = a.index("--blur"); blur = float(a[i + 1]); del a[i:i + 2]
    main(a[0], a[1], a[2], blur)
