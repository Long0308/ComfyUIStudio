"""Màn hình phòng họp Cảnh 4 = bản đồ VN (2 quần đảo) + infographic KPI nhân lực đỏ nhấp nháy.
User 16/11: «kế bên ảnh bản đồ là infographic nhấp nháy hiệu ứng đỏ nhân lực công nhân trễ tiến độ bản đồ KPI».

  python render_screen.py still k1 out.png [--t 0.17]
  python render_screen.py frames k1 OUTDIR --seconds 5 --fps 24

Bố cục theo chỗ GĐĐH che màn hình: k1 (đứng giữa ⇒ KPI trái, bản đồ phải), k2 (đứng 1/3 trái ⇒ KPI giữa-trên, bản đồ phải).
Số KPI là số MINH HOẠ cho phim (user đổi được ở KPI_*)."""
from __future__ import annotations

import math, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import render_map as rm

FONT, FONTB = rm.FONT, rm.FONTB
RED, BLUE, TXT, MUTE, ACC = (255, 52, 52), (90, 200, 255), (232, 240, 255), (150, 172, 210), (11, 79, 217)
KPI_ALERT = "6 DỰ ÁN TRỄ TIẾN ĐỘ"
KPI_BIG = ("THIẾU", "1.150", "CÔNG NHÂN")
KPI_BARS = (("Miền Bắc", 69, True), ("Miền Trung", 96, False), ("Miền Nam", 74, True))
PULSE_HZ = 1.5

LAYOUTS = {
    "k1": dict(W=2000, H=1000, BOX=(0.62, 0.03, 0.995, 0.97), PANEL=(0.025, 0.05, 0.345, 0.95)),
    "k2": dict(W=1520, H=1000, BOX=(0.585, 0.03, 0.995, 0.97), PANEL=(0.365, 0.05, 0.57, 0.58)),
}
_CACHE: dict[str, Image.Image] = {}


def plate(name: str) -> Image.Image:
    if name not in _CACHE:
        L = LAYOUTS[name]
        rm.W, rm.H, rm.BOX = L["W"], L["H"], L["BOX"]
        rm.LON0, rm.LON1, rm.LAT0, rm.LAT1 = 101.6, 117.2, 7.3, 23.7
        rm.SKIP_TEXT = True; rm.NAME = f"_plate_{name}.png"
        _CACHE[name] = rm.main().convert("RGB")
    return _CACHE[name]


def pulse(t: float) -> float:
    return 0.5 + 0.5 * math.sin(2 * math.pi * PULSE_HZ * t - math.pi / 2)  # 0 at t=0, peak at 1/(2·HZ)


def frame(name: str, t: float) -> Image.Image:
    L = LAYOUTS[name]; W, H = L["W"], L["H"]; base = plate(name).copy(); p = pulse(t)
    rm.W, rm.H, rm.BOX = W, H, L["BOX"]
    # map: pulsing red halos on shortage sites
    halo = Image.new("L", (W, H), 0); hd = ImageDraw.Draw(halo); rad = 18 + 16 * p
    for lat, lon in rm.RED_SITES:
        x, y = rm.to_px(lon, lat); x /= rm.SS; y /= rm.SS
        hd.ellipse([x - rad, y - rad, x + rad, y + rad], fill=255)
    base.paste(Image.new("RGB", (W, H), RED), mask=halo.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * (0.25 + 0.55 * p))))
    d = ImageDraw.Draw(base)
    for lat, lon in rm.RED_SITES:
        x, y = rm.to_px(lon, lat); x /= rm.SS; y /= rm.SS; r = 6 + 2 * p
        d.ellipse([x - r, y - r, x + r, y + r], fill=RED, outline=(255, 255, 255), width=2)
    # island labels are drawn once by render_map (plate) — do not draw again (ghosting)
    # KPI panel
    x0, y0, x1, y1 = (int(L["PANEL"][0] * W), int(L["PANEL"][1] * H), int(L["PANEL"][2] * W), int(L["PANEL"][3] * H))
    pw, ph = x1 - x0, y1 - y0; u = min(pw / 22.0, ph / 30.0)  # unit size
    d.rounded_rectangle([x0, y0, x1, y1], radius=int(u), fill=(9, 24, 54), outline=(30, 60, 110), width=2)
    ft = ImageFont.truetype(FONTB, int(u * 1.25)); y = y0 + int(u * 0.9)
    d.text((x0 + u, y), "KPI NHÂN LỰC · TIẾN ĐỘ", font=ft, fill=TXT); y += int(u * 1.9)
    d.line([(x0 + u, y), (x0 + u * 9, y)], fill=ACC, width=max(2, int(u * 0.18))); y += int(u * 0.9)
    # alert tile (pulsing red)
    th = int(u * 3.0); a = 0.45 + 0.55 * p
    tile = (int(120 + 135 * a), int(18 + 20 * a), int(22 + 20 * a))
    d.rounded_rectangle([x0 + u, y, x1 - u, y + th], radius=int(u * 0.5), fill=tile)
    tri = [(x0 + u * 1.8, y + th * 0.72), (x0 + u * 2.7, y + th * 0.28), (x0 + u * 3.6, y + th * 0.72)]
    d.polygon(tri, fill=(255, 255, 255)); d.text((x0 + u * 2.7, y + th * 0.6), "!", font=ImageFont.truetype(FONTB, int(u * 0.9)), fill=tile, anchor="mm")
    d.text((x0 + u * 4.3, y + th / 2), KPI_ALERT, font=ImageFont.truetype(FONTB, int(u * 1.05)), fill=(255, 255, 255), anchor="lm")
    y += th + int(u * 1.0)
    # big number
    fb = ImageFont.truetype(FONTB, int(u * 2.6)); fs = ImageFont.truetype(FONT, int(u * 1.0))
    redp = (255, int(70 + 80 * (1 - p)), int(70 + 80 * (1 - p)))
    d.text((x0 + u, y), KPI_BIG[0], font=fs, fill=MUTE); y += int(u * 1.3)
    d.text((x0 + u, y), KPI_BIG[1], font=fb, fill=redp); bw = d.textlength(KPI_BIG[1], font=fb)
    d.text((x0 + u * 1.6 + bw, y + u * 1.5), KPI_BIG[2], font=fs, fill=TXT); y += int(u * 3.3)
    # bars
    d.text((x0 + u, y), "Công nhân hiện có / kế hoạch", font=fs, fill=MUTE); y += int(u * 1.6)
    fbar = ImageFont.truetype(FONTB, int(u * 0.95)); bar_w = pw - 2 * u
    room = (y1 - int(u * 3.0)) - y - len(KPI_BARS) * u * 2.9  # spread bars over the free height
    gap = max(0, room / len(KPI_BARS)); y += int(gap / 2)
    for lab, pct, bad in KPI_BARS:
        d.text((x0 + u, y), lab, font=fbar, fill=TXT); d.text((x1 - u, y), f"{pct}%", font=fbar, fill=redp if bad else BLUE, anchor="ra")
        y += int(u * 1.3)
        d.rounded_rectangle([x0 + u, y, x0 + u + bar_w, y + u * 0.7], radius=int(u * 0.35), fill=(25, 45, 85))
        col = (int(150 + 105 * p), 40, 45) if bad else BLUE
        d.rounded_rectangle([x0 + u, y, x0 + u + bar_w * pct / 100, y + u * 0.7], radius=int(u * 0.35), fill=col)
        y += int(u * 1.6 + gap)
    # legend
    fl2 = ImageFont.truetype(FONT, int(u * 0.9)); ly = y1 - int(u * 2.2)
    for i, (col, lab) in enumerate(((RED, "Thiếu nhân lực"), (BLUE, "Đủ nhân lực"))):
        lx = x0 + u + i * (pw - 2 * u) / 2
        d.ellipse([lx, ly, lx + u * 0.8, ly + u * 0.8], fill=col, outline=(255, 255, 255), width=1)
        d.text((lx + u * 1.2, ly + u * 0.4), lab, font=fl2, fill=TXT, anchor="lm")
    return base


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "still":
        t = float(a[a.index("--t") + 1]) if "--t" in a else 1 / (2 * PULSE_HZ)
        frame(a[1], t).save(a[2]); print("ok", a[2])
    elif a[0] == "frames":
        out = Path(a[2]); out.mkdir(parents=True, exist_ok=True)
        sec = float(a[a.index("--seconds") + 1]) if "--seconds" in a else 5.0
        fps = int(a[a.index("--fps") + 1]) if "--fps" in a else 24
        for i in range(int(sec * fps)):
            frame(a[1], i / fps).save(out / f"f{i:04d}.png")
        print("ok", out, int(sec * fps), "frames")
