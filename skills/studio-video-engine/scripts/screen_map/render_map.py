"""Bản đồ Việt Nam cho màn hình phòng họp Cảnh 4 (user 16/11: «bản đồ việt nam có quần đảo hoàng sa và trường sa …
dấu đỏ thiếu nhân lực ở miền bắc và miền nam»).

Đất liền: Natural Earth 1:50m admin-0 (public domain), file `data/ne_50m_admin_0_countries.geojson`
sha256 3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb.
Hai quần đảo: chấm theo toạ độ các đảo/đá thật (độ thập phân), nhãn bằng font thật — không để model ảnh vẽ.
Xuất `out/MAP_VN_NHANLUC_1920x1080.png`.
"""
from __future__ import annotations

import json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
W, H, SS = 1920, 1080, 2  # supersample 2x
LON0, LON1, LAT0, LAT1 = 100.2, 118.6, 7.0, 24.2
BOX = (0.0, 0.03, 0.88, 0.97)  # vùng vẽ bản đồ (tỉ lệ khung) — đổi theo chỗ người đứng che màn hình
TX = 0.78; TITLE_Y = 0.065; NAME = "MAP_VN_NHANLUC_1920x1080.png"
SKIP_TEXT = False  # render_screen.py vẽ tiêu đề/chú thích/KPI riêng
FONT = "C:/Windows/Fonts/segoeui.ttf"; FONTB = "C:/Windows/Fonts/segoeuib.ttf"

BG = (6, 18, 42); LAND = (24, 86, 196); LAND_EDGE = (120, 190, 255); NEIGH = (40, 70, 120)
RED = (255, 48, 48); OK = (90, 200, 255); TXT = (225, 238, 255); MUTE = (140, 165, 205)

HOANG_SA = [(16.83, 112.33), (16.98, 112.27), (16.53, 111.61), (16.45, 111.70), (16.58, 111.77), (16.54, 111.50),
            (15.78, 111.20), (16.05, 112.50), (16.67, 112.73), (16.95, 112.22), (16.47, 111.55)]
TRUONG_SA = [(8.64, 111.92), (11.43, 114.33), (9.88, 114.33), (10.18, 114.36), (10.38, 114.48), (11.05, 114.28),
             (10.38, 114.36), (7.89, 112.92), (8.85, 112.20), (8.97, 113.69), (10.06, 113.85), (8.81, 113.98),
             (8.18, 113.30), (9.43, 112.89), (10.85, 114.95), (9.55, 115.45), (8.40, 114.60), (11.10, 115.02)]
RED_SITES = [(21.03, 105.85), (20.86, 106.68), (21.18, 106.07), (20.95, 107.08),   # Bắc
             (10.78, 106.70), (11.00, 106.65), (10.95, 106.95), (10.55, 106.40)]   # Nam
OK_SITES = [(16.05, 108.20), (12.25, 109.19)]                                     # Trung


def to_px(lon: float, lat: float) -> tuple[float, float]:
    # equirectangular with cos(mid-lat) so the S-shape keeps its true proportions; fitted & centred inside BOX
    k = math.cos(math.radians((LAT0 + LAT1) / 2))
    bw, bh = (BOX[2] - BOX[0]) * W, (BOX[3] - BOX[1]) * H
    s = min(bw / ((LON1 - LON0) * k), bh / (LAT1 - LAT0))
    ox = BOX[0] * W + (bw - (LON1 - LON0) * k * s) / 2; oy = BOX[1] * H + (bh - (LAT1 - LAT0) * s) / 2
    return ((ox + (lon - LON0) * k * s) * SS, (oy + (LAT1 - lat) * s) * SS)


SOVEREIGN_BOXES = [(15.3, 17.8, 110.5, 113.2),   # Hoàng Sa (lat0, lat1, lon0, lon1)
                   (6.8, 12.2, 111.0, 117.0)]    # Trường Sa
DROPPED: list[str] = []


def in_sovereign_box(poly: list) -> bool:
    lon = sum(p[0] for p in poly) / len(poly); lat = sum(p[1] for p in poly) / len(poly)
    return any(a <= lat <= b and c <= lon <= e for a, b, c, e in SOVEREIGN_BOXES)


def rings(geom: dict, code: str = "VNM"):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if code != "VNM" and in_sovereign_box(poly[0]):
            DROPPED.append(code)  # never draw another country's polygon over Hoàng Sa / Trường Sa
            continue
        yield [to_px(x, y) for x, y in poly[0]]


def main() -> Image.Image:
    feats = {f["properties"]["ADM0_A3"]: f for f in json.load(open(HERE / "data/ne_50m_admin_0_countries.geojson", encoding="utf-8"))["features"]}
    img = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(img)
    for step in range(0, W * SS, 80 * SS):  # faint grid
        d.line([(step, 0), (step, H * SS)], fill=(12, 30, 62), width=SS)
    for step in range(0, H * SS, 80 * SS):
        d.line([(0, step), (W * SS, step)], fill=(12, 30, 62), width=SS)
    for code in ("CHN", "LAO", "KHM", "THA", "MMR", "PHL", "MYS", "TWN"):
        if code in feats:
            for r in rings(feats[code]["geometry"], code):
                d.polygon(r, fill=(10, 26, 56), outline=NEIGH)
    glow = Image.new("RGB", img.size, (0, 0, 0)); gd = ImageDraw.Draw(glow)
    for r in rings(feats["VNM"]["geometry"]):
        gd.polygon(r, fill=(40, 120, 255))
    img = Image.composite(img, img, Image.new("L", img.size, 255))
    img = Image.blend(img, Image.eval(glow.filter(ImageFilter.GaussianBlur(18 * SS)), lambda v: v), 0.0)
    img.paste(Image.new("RGB", img.size, (30, 90, 220)), mask=glow.convert("L").filter(ImageFilter.GaussianBlur(22 * SS)).point(lambda v: int(v * 0.45)))
    d = ImageDraw.Draw(img)
    for r in rings(feats["VNM"]["geometry"]):
        d.polygon(r, fill=LAND, outline=LAND_EDGE, width=2 * SS)
    isl = Image.new("L", img.size, 0); idr = ImageDraw.Draw(isl)
    for pts in (HOANG_SA, TRUONG_SA):  # sovereign archipelagos: halo + dots in Vietnam's land colour
        for lat, lon in pts:
            x, y = to_px(lon, lat); idr.ellipse([x - 30 * SS, y - 30 * SS, x + 30 * SS, y + 30 * SS], fill=255)
    img.paste(Image.new("RGB", img.size, (30, 90, 220)), mask=isl.filter(ImageFilter.GaussianBlur(20 * SS)).point(lambda v: int(v * 0.40)))
    d = ImageDraw.Draw(img)
    for pts in (HOANG_SA, TRUONG_SA):
        for lat, lon in pts:
            x, y = to_px(lon, lat); rr = 7 * SS
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=LAND, outline=LAND_EDGE, width=2 * SS)
    f_lab = ImageFont.truetype(FONTB, 30 * SS); f_s = ImageFont.truetype(FONT, 20 * SS)
    x, y = to_px(112.0, 17.55); d.text((x, y), "QĐ. Hoàng Sa", font=f_lab, fill=TXT, anchor="mm")
    x, y = to_px(113.6, 12.15); d.text((x, y), "QĐ. Trường Sa", font=f_lab, fill=TXT, anchor="mm")
    halo = Image.new("L", img.size, 0); hd = ImageDraw.Draw(halo)
    for sites, col in ((RED_SITES, RED), (OK_SITES, OK)):
        for lat, lon in sites:
            x, y = to_px(lon, lat)
            if col == RED:
                hd.ellipse([x - 26 * SS, y - 26 * SS, x + 26 * SS, y + 26 * SS], fill=200)
    img.paste(Image.new("RGB", img.size, RED), mask=halo.filter(ImageFilter.GaussianBlur(12 * SS)).point(lambda v: int(v * 0.55)))
    d = ImageDraw.Draw(img)
    for sites, col in ((RED_SITES, RED), (OK_SITES, OK)):
        for lat, lon in sites:
            x, y = to_px(lon, lat); r = 9 * SS
            d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(255, 255, 255), width=2 * SS)
    if SKIP_TEXT:
        out = img.resize((W, H), Image.LANCZOS); out.save(OUT / NAME); return out
    # legend (bottom-right) + title (top-right)
    f_t = ImageFont.truetype(FONTB, 34 * SS)
    tx = int(W * TX) * SS
    d.text((tx, int(H * TITLE_Y) * SS), "NHÂN LỰC CÁC DỰ ÁN", font=f_t, fill=TXT)
    d.line([(tx, int(H * TITLE_Y + 52) * SS), (tx + 330 * SS, int(H * TITLE_Y + 52) * SS)], fill=(11, 79, 217), width=4 * SS)
    ly = H * SS - 190 * SS
    tx = int(W * TX) * SS
    for i, (col, lab) in enumerate(((RED, "Thiếu nhân lực"), (OK, "Đủ nhân lực"))):
        cy = ly + i * 48 * SS
        d.ellipse([tx, cy, tx + 22 * SS, cy + 22 * SS], fill=col, outline=(255, 255, 255), width=2 * SS)
        d.text((tx + 38 * SS, cy - 6 * SS), lab, font=f_s, fill=TXT)
    out = img.resize((W, H), Image.LANCZOS)
    out.save(OUT / NAME)
    print("ok", OUT / NAME, "| polygon nuoc khac bi bo trong vung 2 quan dao:", DROPPED or "khong co")
    return out


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if "--layout" in a and a[a.index("--layout") + 1] == "k1_right":
        # Shot 1: GĐĐH che giữa màn hình (≈36–64 % ngang) ⇒ cả VN + 2 quần đảo dồn sang PHẢI, chữ sang TRÁI
        W, H = 2000, 1000; BOX = (0.64, 0.04, 0.995, 0.97); TX = 0.035; TITLE_Y = 0.08
        LON0, LON1, LAT0, LAT1 = 101.6, 117.2, 7.3, 23.7; NAME = "MAP_VN_NHANLUC_K1_RIGHT_2000x1000.png"
    main()
