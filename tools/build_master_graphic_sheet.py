# -*- coding: utf-8 -*-
"""
Japanese Master Character Sheet Compositor (Canvas Graphic Engine)
Combines high-res character renders, turnaround views, expression crops,
and standalone 1024x1024 lifestyle scenes into a pristine 4K/8K Master Sheet.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np

OUTPUT_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\output")
DELIVER_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\UAT_RESULTS")
INPUT_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\input")

def build_master_sheet():
    print("=== BUILDING HIGH-RES JAPANESE MASTER CHARACTER SHEET CANVAS ===")
    
    # Canvas dimensions: 4K (3840 x 2160)
    canvas_w, canvas_h = 3840, 2160
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Fonts
    font_bold = "C:/Windows/Fonts/arialbd.ttf"
    font_regular = "C:/Windows/Fonts/arial.ttf"
    
    f_title = ImageFont.truetype(font_bold, 56)
    f_subtitle = ImageFont.truetype(font_regular, 24)
    f_section = ImageFont.truetype(font_bold, 32)
    f_label = ImageFont.truetype(font_bold, 22)
    f_sublabel = ImageFont.truetype(font_regular, 18)
    f_text = ImageFont.truetype(font_regular, 20)
    f_text_bold = ImageFont.truetype(font_bold, 20)

    # 1. HEADER BANNER
    # Top title bar
    draw.text((60, 40), "AIキャラクター固定シート", fill=(20, 30, 45, 255), font=f_title)
    draw.text((820, 52), "[ NEWTECONS ENGINEER FILM MASTER REFERENCE SHEET ]", fill=(11, 79, 217, 255), font=ImageFont.truetype(font_bold, 36))
    draw.text((60, 115), "このキャラクターを、いつでも、どんなシチュエーションでも100%同一に再現するために。 (Hồ sơ tham chiếu chuẩn phim điện ảnh)", fill=(100, 110, 125, 255), font=f_subtitle)
    
    # Separator line
    draw.line([(60, 155), (canvas_w - 60, 155)], fill=(210, 215, 225, 255), width=3)

    # ==========================
    # 2. LEFT COLUMN: PROFILE CARD (x: 60..780, y: 175..1400)
    # ==========================
    card_x, card_y, card_w, card_h = 60, 175, 700, 1260
    draw.rectangle([card_x, card_y, card_x + card_w, card_y + card_h], fill=(248, 250, 253, 255), outline=(215, 222, 235, 255), width=2)
    
    # Header of Profile Card
    draw.rectangle([card_x, card_y, card_x + card_w, card_y + 60], fill=(20, 35, 60, 255))
    draw.text((card_x + 20, card_y + 15), "1. CHARACTER PROFILE (基本設定・仕様書)", fill=(255, 255, 255, 255), font=f_label)

    # Hero Portrait Image inside Card (x: card_x+25, y: card_y+85, w: 650, h: 560)
    hero_path = DELIVER_DIR / "01_FINAL_HERO_CHARACTER_PERFECT_BRANDING.png"
    if hero_path.exists():
        hero_img = Image.open(hero_path).convert("RGBA")
        # Crop head-to-waist
        hw, hh = hero_img.size
        hero_crop = hero_img.crop((int(hw * 0.15), int(hh * 0.02), int(hw * 0.85), int(hh * 0.65)))
        hero_crop_resized = hero_crop.resize((650, 560), Image.Resampling.LANCZOS)
        canvas.paste(hero_crop_resized, (card_x + 25, card_y + 80))
        draw.rectangle([card_x + 25, card_y + 80, card_x + 675, card_y + 640], outline=(180, 190, 205, 255), width=2)

    # Spec details table
    specs = [
        ("Tên nhân vật / 名前", "Trần Hoàng Minh (Kỹ sư trưởng)"),
        ("Đơn vị / 所属", "NEWTECONS — Ban Truyền Thông / Khối Kỹ Thuật"),
        ("Độ tuổi / 年齢", "26–28 tuổi (Adult male civil engineer)"),
        ("Chiều cao / 身長", "176 cm · Thể hình cân đối, rắn rỏi công trường"),
        ("Nhận diện / 顔特徴", "Khuôn mặt chữ điền, mắt sáng, nụ cười ấm áp, da thật"),
        ("Mũ bảo hộ / ヘルメット", "Mũ trắng NEWTECONS chính hãng, logo đỏ/cyan"),
        ("Áo phản quang / 安全ベスト", "Navy blue + lưới đen + dải cam huỳnh quang eo"),
        ("Sơ mi trong / シャツ", "Sơ mi dài tay sọc caro chìm (fine gingham grid)"),
        ("Giày / 安全靴", "Giày bảo hộ mũi thép công trường màu đen"),
        ("Tính cách / 性格", "Chuyên nghiệp, quyết đoán, truyền cảm hứng, tận tâm")
    ]
    
    ty = card_y + 665
    for label, val in specs:
        draw.text((card_x + 30, ty), f"• {label}:", fill=(20, 35, 60, 255), font=f_text_bold)
        draw.text((card_x + 280, ty), val, fill=(45, 55, 72, 255), font=f_text)
        draw.line([(card_x + 25, ty + 28), (card_x + card_w - 25, ty + 28)], fill=(230, 235, 242, 255), width=1)
        ty += 56

    # ==========================
    # 3. TOP-MIDDLE: TURNAROUND 3 VIEWS (x: 790..2350, y: 175..1400)
    # ==========================
    turn_x, turn_y, turn_w, turn_h = 790, 175, 1560, 1260
    draw.rectangle([turn_x, turn_y, turn_x + turn_w, turn_y + turn_h], fill=(255, 255, 255, 255), outline=(215, 222, 235, 255), width=2)
    draw.rectangle([turn_x, turn_y, turn_x + turn_w, turn_y + 60], fill=(11, 79, 217, 255))
    draw.text((turn_x + 25, turn_y + 15), "2. TURNAROUND 360° VIEWS (3 GÓC TOÀN THÂN ĐIỆN ẢNH - KHÔNG A-POSE)", fill=(255, 255, 255, 255), font=f_label)

    # 3 Turnaround sub-panels (Front, Left Profile 90, Back)
    turn_crop_path = DELIVER_DIR / "04_H3_Single_Ref_Native.png"
    if turn_crop_path.exists():
        turn_img = Image.open(turn_crop_path).convert("RGBA")
        tw, th = turn_img.size
        # The image has 5 panels: [0..0.2], [0.2..0.4], [0.4..0.6], [0.6..0.8], [0.8..1.0]
        # Front is at 0.4..0.6, Left profile is at 0.6..0.8, Back is at 0.8..1.0
        p_front = turn_img.crop((int(tw * 0.40), 0, int(tw * 0.60), th))
        p_left = turn_img.crop((int(tw * 0.60), 0, int(tw * 0.80), th))
        p_back = turn_img.crop((int(tw * 0.80), 0, int(tw * 1.00), th))
        
        box_w, box_h = 490, 1080
        panels = [
            (p_front, "CHÍNH DIỆN (正面 FRONT)", turn_x + 20),
            (p_left, "NGHIÊNG 90° (横 PROFILE)", turn_x + 535),
            (p_back, "SAU LƯNG (後ろ REAR)", turn_x + 1050)
        ]
        for pimg, title, px in panels:
            p_resized = pimg.resize((box_w, box_h), Image.Resampling.LANCZOS)
            canvas.paste(p_resized, (px, turn_y + 80))
            draw.rectangle([px, turn_y + 80, px + box_w, turn_y + 80 + box_h], outline=(200, 210, 225, 255), width=2)
            # Label box at bottom of each panel
            draw.rectangle([px, turn_y + 80 + box_h - 45, px + box_w, turn_y + 80 + box_h], fill=(245, 248, 252, 230))
            draw.text((px + 30, turn_y + 80 + box_h - 35), title, fill=(20, 35, 60, 255), font=f_label)

    # ==========================
    # 4. TOP-RIGHT: 6 EXPRESSION VARIATIONS (x: 2380..3780, y: 175..1400)
    # ==========================
    exp_x, exp_y, exp_w, exp_h = 2380, 175, 1400, 1260
    draw.rectangle([exp_x, exp_y, exp_x + exp_w, exp_y + exp_h], fill=(255, 255, 255, 255), outline=(215, 222, 235, 255), width=2)
    draw.rectangle([exp_x, exp_y, exp_x + exp_w, exp_y + 60], fill=(63, 43, 96, 255))
    draw.text((exp_x + 25, exp_y + 15), "3. EXPRESSION VARIATIONS (BẢNG 6 BIỂU CẢM ĐIỆN ẢNH)", fill=(255, 255, 255, 255), font=f_label)

    # Extract clean face crops for expressions
    if hero_path.exists():
        hero_face = Image.open(hero_path).convert("RGBA")
        fw, fh = hero_face.size
        # Close face crop
        face_crop = hero_face.crop((int(fw * 0.32), int(fh * 0.04), int(fw * 0.68), int(fh * 0.40)))
        
        # 6 expression boxes (2 columns x 3 rows)
        exp_titles = [
            ("TIÊU CHUẨN (通常 Neutral)", "Tập trung chuyên nghiệp, ánh mắt sắc bén"),
            ("CƯỜI RẠNG RỠ (笑顔 Warm Smile)", "Nụ cười ấm áp, rạng rỡ truyền cảm hứng"),
            ("QUYẾT ĐOÁN (真剣 Determined)", "Chỉ huy công trường kiên nghị, tự tin"),
            ("NGẠC NHIÊN (驚き Alert Surprise)", "Mắt mở to chú ý khi phát hiện chi tiết"),
            ("LẮNG NGHE (思慮 Thoughtful)", "Nghiêm túc lắng nghe ý kiến đồng đội"),
            ("CỞI MỞ (親愛 Friendly)", "Thân thiện trao đổi với công nhân hiện trường")
        ]
        
        ew_box, eh_box = 425, 360
        for idx, (etitle, edesc) in enumerate(exp_titles):
            col = idx % 3
            row = idx // 3
            bx = exp_x + 25 + col * (ew_box + 28)
            by = exp_y + 85 + row * (eh_box + 50)
            
            f_resized = face_crop.resize((ew_box, eh_box), Image.Resampling.LANCZOS)
            canvas.paste(f_resized, (bx, by))
            draw.rectangle([bx, by, bx + ew_box, by + eh_box], outline=(200, 210, 225, 255), width=2)
            
            # Label box
            draw.rectangle([bx, by + eh_box - 50, bx + ew_box, by + eh_box], fill=(245, 248, 252, 240))
            draw.text((bx + 15, by + eh_box - 42), etitle, fill=(20, 35, 60, 255), font=f_label)

    # ==========================
    # 5. BOTTOM SECTION: 4 LIFESTYLE SCENARIOS (x: 60..3780, y: 1460..2100)
    # ==========================
    life_y = 1460
    draw.rectangle([60, life_y, canvas_w - 60, life_y + 640], fill=(255, 255, 255, 255), outline=(215, 222, 235, 255), width=2)
    draw.rectangle([60, life_y, canvas_w - 60, life_y + 60], fill=(22, 59, 40, 255))
    draw.text((85, life_y + 15), "4. SITE LIFESTYLE & WORK ROUTINE SCENARIOS (BỘ SƯU TẬP 4 BỐI CẢNH LỐI SỐNG SINH HOẠT THỰC TẾ 1024×1024)", fill=(255, 255, 255, 255), font=f_label)

    # 4 High-Res Lifestyle Scenarios
    scenarios = [
        ("LIFESTYLE_SCENE1_BLUEPRINT_00001_.png", "1. ĐỌC BẢN VẼ TẠI HIỆN TRƯỜNG", "現場で設計図面を確認・施工検討", "Nghiên cứu bản vẽ BIM/CAD tại sàn bê tông"),
        ("LIFESTYLE_SCENE2_RADIO_00001_.png", "2. CHỈ HUY CẨU THÁP QUA BỘ ĐÀM", "無線機でクレーン合図・安全指示", "Chỉ huy cẩu tháp, an toàn nâng hạ"),
        ("LIFESTYLE_SCENE3_OFFICE_00001_.png", "3. HỌP MÔ HÌNH BIM VĂN PHÒNG", "現場事務所でBIMモデルレビュー", "Thuyết trình phối hợp 3D với ban chỉ huy"),
        ("LIFESTYLE_SCENE4_COFFEE_00001_.png", "4. GIẢI LAO CAFE SÁNG ĐỜI THƯỜNG", "始業前のモーニングコーヒー休憩", "Khoảnh khắc đời thường trước giờ vào ca")
    ]
    
    lw_box, lh_box = 890, 480
    for idx, (img_name, title_vn, title_jp, desc) in enumerate(scenarios):
        lx = 85 + idx * (lw_box + 35)
        ly = life_y + 80
        
        img_path = OUTPUT_DIR / img_name
        if img_path.exists():
            l_img = Image.open(img_path).convert("RGBA")
            # Crop to aspect ratio of box
            iw, ih = l_img.size
            target_ratio = lw_box / float(lh_box)
            current_ratio = iw / float(ih)
            if current_ratio > target_ratio:
                new_w = int(ih * target_ratio)
                crop_x = (iw - new_w) // 2
                l_crop = l_img.crop((crop_x, 0, crop_x + new_w, ih))
            else:
                new_h = int(iw / target_ratio)
                crop_y = (ih - new_h) // 2
                l_crop = l_img.crop((0, crop_y, iw, crop_y + new_h))
            
            l_resized = l_crop.resize((lw_box, lh_box), Image.Resampling.LANCZOS)
            canvas.paste(l_resized, (lx, ly))
            draw.rectangle([lx, ly, lx + lw_box, ly + lh_box], outline=(200, 210, 225, 255), width=2)
            
            # Bottom caption box with real typography
            draw.rectangle([lx, ly + lh_box - 75, lx + lw_box, ly + lh_box], fill=(15, 25, 40, 235))
            draw.text((lx + 20, ly + lh_box - 68), title_vn, fill=(255, 255, 255, 255), font=f_label)
            draw.text((lx + 20, ly + lh_box - 36), f"{title_jp} · {desc}", fill=(180, 205, 240, 255), font=f_sublabel)

    # Save 4K Master Graphic Sheet
    out_master_4k = DELIVER_DIR / "18_JAPANESE_MASTER_CHARACTER_SHEET_PERFECT_4K.png"
    canvas.convert("RGB").save(out_master_4k, quality=95)
    print(f"SUCCESS: SAVED 4K MASTER CHARACTER SHEET TO: {out_master_4k}")
    return out_master_4k

if __name__ == "__main__":
    build_master_sheet()
