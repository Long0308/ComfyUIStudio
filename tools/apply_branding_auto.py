# -*- coding: utf-8 -*-
"""
NEWTECONS Perfect Branding & Typography Compositor
Deterministic CPU compositor that applies 100% accurate Unicode typography
and official vector logos to generated engineer stills, eliminating AI spelling errors.
"""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def apply_newtecons_branding(
    image_input_path: str,
    image_output_path: str,
    department_text: str = "BAN TRUYỀN\nTHÔNG",
    logo_color_path: str = None,
    logo_white_path: str = None
):
    base = Image.open(image_input_path).convert("RGBA")
    w, h = base.size
    scale_w = w / 1024.0
    scale_h = h / 1024.0

    draw_base = ImageDraw.Draw(base)

    # 1. Left chest: Clean Unicode Department Text
    font_path = "C:/Windows/Fonts/arialbd.ttf"
    if not Path(font_path).exists():
        font_path = "C:/Windows/Fonts/tahomabd.ttf"
    
    font_size = int(22 * scale_w)
    font = ImageFont.truetype(font_path, font_size)

    # Patch over AI generated text with vest navy color
    navy_color = (20, 32, 54, 255)
    x1_txt, y1_txt = int(340 * scale_w), int(392 * scale_h)
    x2_txt, y2_txt = int(460 * scale_w), int(444 * scale_h)
    draw_base.rectangle([x1_txt, y1_txt, x2_txt, y2_txt], fill=navy_color)

    # Render multiline text
    txt_img = Image.new("RGBA", (int(140 * scale_w), int(55 * scale_h)), (0, 0, 0, 0))
    draw_txt = ImageDraw.Draw(txt_img)
    draw_txt.multiline_text((0, 0), department_text, fill=(255, 255, 255, 255), font=font, align="center", spacing=4)
    base.paste(txt_img, (int(344 * scale_w), int(394 * scale_h)), txt_img)

    # 2. Right chest: Crisp white NEWTECONS logo
    if logo_white_path and Path(logo_white_path).exists():
        logo_white = Image.open(logo_white_path).convert("RGBA")
        x1_lw, y1_lw = int(565 * scale_w), int(365 * scale_h)
        x2_lw, y2_lw = int(660 * scale_w), int(438 * scale_h)
        draw_base.rectangle([x1_lw, y1_lw, x2_lw, y2_lw], fill=navy_color)
        lw_w, lw_h = int(85 * scale_w), int(65 * scale_h)
        logo_white_res = logo_white.resize((lw_w, lw_h), Image.Resampling.LANCZOS)
        base.paste(logo_white_res, (int(568 * scale_w), int(368 * scale_h)), logo_white_res)

    # 3. Helmet: Crisp official full color logo
    if logo_color_path and Path(logo_color_path).exists():
        logo_color = Image.open(logo_color_path).convert("RGBA")
        x1_lc, y1_lc = int(450 * scale_w), int(58 * scale_h)
        x2_lc, y2_lc = int(555 * scale_w), int(116 * scale_h)
        draw_base.rectangle([x1_lc, y1_lc, x2_lc, y2_lc], fill=(245, 246, 248, 255))
        lc_w, lc_h = int(96 * scale_w), int(52 * scale_h)
        logo_color_res = logo_color.resize((lc_w, lc_h), Image.Resampling.LANCZOS)
        base.paste(logo_color_res, (int(454 * scale_w), int(61 * scale_h)), logo_color_res)

    base.convert("RGB").save(image_output_path)
    print(f"Branding successfully applied to: {image_output_path}")

if __name__ == "__main__":
    import sys
    inp = sys.argv[1] if len(sys.argv) > 1 else r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\UAT_RESULTS\12_Ky_Su_Newtecons_Canon_Fixed_Native.png"
    out = sys.argv[2] if len(sys.argv) > 2 else r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\UAT_RESULTS\NEWTECONS_HERO_PERFECT.png"
    dept = sys.argv[3] if len(sys.argv) > 3 else "BAN TRUYỀN\nTHÔNG"
    l_color = r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\input\LOGO_NGUYEN_BAN.png"
    l_white = r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\input\LOGO_TRANG.png"
    apply_newtecons_branding(inp, out, dept, l_color, l_white)
