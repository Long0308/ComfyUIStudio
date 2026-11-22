"""Ghép bản đồ (render_map.py) vào màn hình xanh #00FF00 của ảnh shot.
Dùng: python composite_screen.py <ảnh_shot.png> <ảnh_ra.png> [--blur PX]
- mặt nạ = điểm ảnh xanh lá (G trội hẳn R,B) ⇒ người đứng trước màn hình tự che bản đồ
- bản đồ co vừa khung chữ nhật bao vùng xanh (contain, đệm màu nền bản đồ), --blur cho cảnh nông độ sâu
- khử ánh xanh trên viền (G <= max(R,B)) trong dải 6 px quanh mặt nạ."""
from __future__ import annotations

import sys
import numpy as np
from pathlib import Path
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
MAP = HERE / "out/MAP_VN_NHANLUC_1920x1080.png"
MAP_BG = (6, 18, 42)


def main(src: str, dst: str, blur: float = 0.0) -> None:
    im = np.asarray(Image.open(src).convert("RGB")).astype(np.int32)
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    green = (g > 120) & (g > r + 60) & (g > b + 60)
    ys, xs = np.nonzero(green)
    if len(xs) < 1000:
        raise SystemExit("không thấy màn hình xanh")
    x0, x1 = np.percentile(xs, [0.2, 99.8]).astype(int); y0, y1 = np.percentile(ys, [0.2, 99.8]).astype(int)
    sw, sh = x1 - x0 + 1, y1 - y0 + 1
    mp = Image.open(MAP).convert("RGB"); k = min(sw / mp.width, sh / mp.height)
    mp = mp.resize((max(1, int(mp.width * k)), max(1, int(mp.height * k))), Image.LANCZOS)
    plate = Image.new("RGB", (sw, sh), MAP_BG); plate.paste(mp, ((sw - mp.width) // 2, (sh - mp.height) // 2))
    if blur > 0:
        plate = plate.filter(ImageFilter.GaussianBlur(blur))
    full = Image.new("RGB", (im.shape[1], im.shape[0]), (0, 0, 0)); full.paste(plate, (x0, y0))
    # soft key + unmix: I = a*K + (1-a)*F  ⇒  F = (I - a*K)/(1-a); out = (1-a)*F + a*MAP  (no grey halo)
    box = np.zeros(green.shape, bool); box[max(0, y0 - 4):y1 + 5, max(0, x0 - 4):x1 + 5] = True
    K = np.median(im[green], axis=0).astype(np.float32)
    ex = (g - np.maximum(r, b)).astype(np.float32); kex = float(K[1] - max(K[0], K[2]))
    a = np.clip((ex - 12.0) / (kex - 12.0), 0, 1) * box
    a = np.where(a > 0.93, 1.0, a)[..., None].astype(np.float32)
    I = im.astype(np.float32); M = np.asarray(full).astype(np.float32)
    F = np.where(a < 0.999, (I - a * K) / np.maximum(1 - a, 1e-3), 0)
    F[..., 1] = np.minimum(F[..., 1], (F[..., 0] + F[..., 2]) / 2 + 4)  # residual spill (average despill, no yellow)
    o = np.where(a > 0, (1 - a) * F + a * M, I)
    Image.fromarray(np.clip(o, 0, 255).astype(np.uint8)).save(dst)
    print("ok", dst, "screen box", (int(x0), int(y0), int(sw), int(sh)), "green px", int(green.sum()))


if __name__ == "__main__":
    args = sys.argv[1:]; blur = 0.0
    if "--map" in args:
        i = args.index("--map"); MAP = Path(args[i + 1]); del args[i:i + 2]
    if "--blur" in args:
        i = args.index("--blur"); blur = float(args[i + 1]); del args[i:i + 2]
    main(args[0], args[1], blur)
