# -*- coding: utf-8 -*-
"""
End-to-End Automated Film Character Pipeline
Executes Step 1 (Hero Character) -> Applies 100% Vector Branding & 3D Logo -> Executes Step 2 (Master Sheet 4K)
"""
import urllib.request
import json
import time
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

COMFY_URL = "http://127.0.0.1:8188"
INPUT_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\input")
OUTPUT_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\NEWTECONS\production-local\ComfyUI\output")
DELIVER_DIR = Path(r"D:\63.ComfyuiStudio\FilmStudio-NEWTECONS-JENNIEJOY\UAT_RESULTS")
DELIVER_DIR.mkdir(parents=True, exist_ok=True)

def queue_prompt(prompt_dict):
    data = json.dumps({"prompt": prompt_dict}).encode('utf-8')
    req = urllib.request.Request(f"{COMFY_URL}/prompt", data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def wait_for_completion(prompt_id, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}")
            history = json.loads(req.read().decode('utf-8'))
            if prompt_id in history:
                return history[prompt_id]
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"Job {prompt_id} timed out after {timeout} seconds")

def apply_branding(image_path, out_path, department_text="BAN TRUYỀN\nTHÔNG"):
    base = Image.open(image_path).convert("RGBA")
    w, h = base.size
    scale_w = w / 1024.0
    scale_h = h / 1024.0
    draw_base = ImageDraw.Draw(base)

    # 1. Left Chest: Unicode Vietnamese Text
    font_path = "C:/Windows/Fonts/arialbd.ttf"
    if not Path(font_path).exists():
        font_path = "C:/Windows/Fonts/tahomabd.ttf"
    font = ImageFont.truetype(font_path, int(22 * scale_w))

    navy_color = (20, 32, 54, 255)
    draw_base.rectangle([int(340 * scale_w), int(392 * scale_h), int(460 * scale_w), int(444 * scale_h)], fill=navy_color)
    txt_img = Image.new("RGBA", (int(140 * scale_w), int(55 * scale_h)), (0, 0, 0, 0))
    draw_txt = ImageDraw.Draw(txt_img)
    draw_txt.multiline_text((0, 0), department_text, fill=(255, 255, 255, 255), font=font, align="center", spacing=4)
    base.paste(txt_img, (int(344 * scale_w), int(394 * scale_h)), txt_img)

    # 2. Right Chest: Crisp White Logo
    logo_white_path = INPUT_DIR / "LOGO_TRANG.png"
    if logo_white_path.exists():
        logo_white = Image.open(logo_white_path).convert("RGBA")
        draw_base.rectangle([int(565 * scale_w), int(365 * scale_h), int(660 * scale_w), int(438 * scale_h)], fill=navy_color)
        lw_w, lw_h = int(85 * scale_w), int(65 * scale_h)
        logo_white_res = logo_white.resize((lw_w, lw_h), Image.Resampling.LANCZOS)
        base.paste(logo_white_res, (int(568 * scale_w), int(368 * scale_h)), logo_white_res)

    # 3. Helmet: Crisp 3D Blender Logo
    logo_color_path = INPUT_DIR / "LOGO_NGUYEN_BAN.png"
    if logo_color_path.exists():
        logo_color = Image.open(logo_color_path).convert("RGBA")
        draw_base.rectangle([int(450 * scale_w), int(58 * scale_h), int(555 * scale_w), int(116 * scale_h)], fill=(245, 246, 248, 255))
        lc_w, lc_h = int(96 * scale_w), int(52 * scale_h)
        logo_color_res = logo_color.resize((lc_w, lc_h), Image.Resampling.LANCZOS)
        base.paste(logo_color_res, (int(454 * scale_w), int(61 * scale_h)), logo_color_res)

    base.convert("RGB").save(out_path)
    print(f"[COMPOSITOR] Perfect vector branding saved to: {out_path}")

def run_pipeline(department_name="BAN TRUYỀN\nTHÔNG"):
    print("=== STARTING FULL AUTOMATED FILM CHARACTER PIPELINE ===")
    
    # ------------------ STEP 1: HERO CHARACTER ------------------
    print("\n>>> EXECUTING STEP 1: GENERATING REAL VIETNAMESE HERO CHARACTER (NOCT-Q V4)...")
    prompt_step1 = {
        "1": {"inputs": {"image": "AI_HUMAN_FACE.png"}, "class_type": "LoadImage"},
        "2": {"inputs": {"image": "full_P002_front.png"}, "class_type": "LoadImage"},
        "3": {"inputs": {"image": "AO_PHAN_QUANG_1.png"}, "class_type": "LoadImage"},
        "4": {"inputs": {"image": "SCENE01_HELMET_CANON_FRONT_6454E4094A70.png"}, "class_type": "LoadImage"},
        "10": {"inputs": {"unet_name": "NoctQ_V4_int8_convrot.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
        "11": {"inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader"},
        "12": {"inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}, "class_type": "VAELoader"},
        "13": {
            "inputs": {
                "clip": ["11", 0],
                "prompt": (
                    "Task: Master photographic film portrait of a Vietnamese NEWTECONS civil construction engineer (Prompt-As-Code standard).\n\n"
                    "INPUT ROLES & IDENTITY LOCK:\n"
                    "<image1> (Identity Lock 100%): Faithfully preserve the exact Vietnamese male face from input 1: facial bone structure, warm eyes, nose, lips, natural smile, authentic Asian skin tone with realistic skin pores. Do NOT change identity.\n"
                    "<image2> (Body Posture): Natural upright standing posture, shoulders relaxed and square, arms resting comfortably at sides, confident stance on job site.\n"
                    "<image3> (NEWTECONS Reflective Vest): Wear the exact two-tone reflective safety vest from input 3: navy blue upper chest and shoulders, black breathable mesh sides and lower back, central black zipper with V-neck collar. Crucial vest details: ONE horizontal silver reflective stripe across the mid-chest; prominent bright FLUORESCENT ORANGE horizontal bands wrapping completely around the waist and lower torso, with a silver reflective stripe centered within the orange bands. Worn over a light blue micro-checkered dress shirt and tailored black trousers.\n"
                    "<image4> (NEWTECONS Safety Helmet): Wear the authentic white industrial safety helmet from input 4 sitting cleanly on top of head with NO chin strap covering the neck or chin. Front center clearly displays the original full-color NEWTECONS logo.\n\n"
                    "QUALITY & CINEMA CANON:\n"
                    "過度なアニメ化、3DCG化、美化、デフォルメを避け、現実のファッション撮影資料のような高い写実性を保つ。\n"
                    "Photorealistic live-action cinema look, natural daytime jobsite lighting, realistic soft depth of field, 8k uhd."
                ),
                "negative_prompt": "chin strap, helmet strap under chin, bicycle helmet, missing orange bands, plain blue vest without orange, anime, 3dcg, cartoon, 3d render, plastic skin, doll face, deformed hands, extra fingers, blurry",
                "vae": ["12", 0],
                "resolution": 1024,
                "images": {"image_1": ["1", 0], "image_2": ["2", 0], "image_3": ["3", 0], "image_4": ["4", 0]}
            },
            "class_type": "TextEncodeQwenImage21"
        },
        "15": {
            "inputs": {
                "seed": 20261103, "steps": 20, "cfg": 3.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                "model": ["10", 0], "positive": ["13", 0], "negative": ["13", 1], "latent_image": ["13", 2]
            },
            "class_type": "KSampler"
        },
        "16": {"inputs": {"samples": ["15", 0], "vae": ["12", 0]}, "class_type": "VAEDecode"},
        "17": {"inputs": {"filename_prefix": "PIPELINE_STEP1_HERO", "images": ["16", 0]}, "class_type": "SaveImage"}
    }

    res1 = queue_prompt(prompt_step1)
    pid1 = res1["prompt_id"]
    print(f"Step 1 Queued (ID: {pid1}). Waiting for completion...")
    hist1 = wait_for_completion(pid1)
    
    # Locate output file
    step1_files = sorted(OUTPUT_DIR.glob("PIPELINE_STEP1_HERO_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    step1_img_path = step1_files[0]
    print(f"Step 1 Finished! Output: {step1_img_path}")

    # ------------------ COMPOSITOR: BRANDING & 3D LOGO ------------------
    print("\n>>> APPLYING 100% VECTOR UNICODE BRANDING & 3D BLENDER LOGO...")
    branded_img_path = DELIVER_DIR / "01_FINAL_HERO_CHARACTER_PERFECT_BRANDING.png"
    apply_branding(str(step1_img_path), str(branded_img_path), department_text=department_name)
    
    # Copy branded hero into input folder for Step 2
    fused_input = INPUT_DIR / "NEWTECONS_Character_Fused.png"
    shutil.copy(branded_img_path, fused_input)
    print(f"Updated Step 2 input reference: {fused_input}")

    # ------------------ STEP 2: MASTER CHARACTER SHEET (4K) ------------------
    print("\n>>> EXECUTING STEP 2: MASTER CHARACTER SHEET (360° + LIFESTYLE + 4K)...")
    prompt_step2 = {
        "1": {"inputs": {"image": "NEWTECONS_Character_Fused.png"}, "class_type": "LoadImage"},
        "10": {"inputs": {"unet_name": "NoctQ_V4_int8_convrot.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
        "11": {"inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader"},
        "12": {"inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}, "class_type": "VAELoader"},
        "13": {
            "inputs": {
                "clip": ["11", 0],
                "prompt": (
                    "Task: Complete Photorealistic Master Character Design Sheet (\"AI美女 キャラクター固定シート\" Japanese Film Production Standard) of the professional NEWTECONS engineer in <image1> for a live-action film series.\n\n"
                    "IDENTITY LOCK 100%:\n"
                    "Strictly preserve exact facial features, bone structure, eyes, nose, lips, smile, Asian skin tone, and dark hair from <image1>. Do NOT change identity. Do NOT anime-fy.\n\n"
                    "SHEET STRUCTURE & EDITORIAL CANVAS (Structured multi-panel cheat sheet on clean studio layout with neat Japanese section titles):\n"
                    "1. TOP-LEFT [HERO & PROFILE CARD]: Hero selfie portrait with phone, title \"AI美女 キャラクター固定シート\", and specification table covering Name, Age (26), Profession (NEWTECONS Engineer), Personality, Height, Measurements, and Routine.\n"
                    "2. TOP-MIDDLE [TURNAROUND VIEWS]: Five full-body views showing the same engineer in exact uniform: Front view (正面), Profile (横), Rear (後ろ), 3/4 Front (斜め前), 3/4 Rear (斜め後ろ). Natural relaxed standing posture with arms resting naturally at sides.\n"
                    "3. TOP-RIGHT [EXPRESSION SHEET]: Six close-up facial portraits: Neutral (通常), Radiant Smile (笑顔), Focused (真剣), Alert Surprise (驚き), Pensive (真剣), Friendly Communication.\n"
                    "4. MIDDLE-ROW [MACRO DETAILS]: Multi-angle facial closeups, helmet logo macro, reflective vest zipper and fabric texture.\n"
                    "5. LOWER-MIDDLE [BODY & SKIN TEXTURE]: Collarbone, waistline, hands, safety boots, and authentic skin texture with visible natural pores.\n"
                    "6. BOTTOM ROW [8 SITE LIFESTYLE SCENARIOS]: Eight distinct photo cards: (1) Reviewing technical blueprints on site, (2) Directing crane with walkie-talkie, (3) 3D BIM meeting in modern technical office, (4) Mid-day jobsite break chatting with colleagues, (5) Morning coffee before shift, (6) Laser level floor inspection, (7) Relaxed off-duty casual wear strolling the city, (8) Topping-out ceremony celebration.\n\n"
                    "QUALITY DIRECTIVES:\n"
                    "過度なアニメ化、3DCG化、美化、デフォルメを避け、現実のファッション撮影資料のような高い写実性を保つ。\n"
                    "High-end editorial fashion catalogue aesthetics, photorealistic cinema masterpiece, authentic pores and fine skin texture, soft even studio lighting, 8k resolution."
                ),
                "negative_prompt": "anime, 3dcg, cartoon, 3d render, drawing, illustration, sketch, blurry, plastic skin, doll skin, extra limbs, deformed fingers, low resolution",
                "vae": ["12", 0],
                "resolution": 1024,
                "images": {"image_1": ["1", 0]}
            },
            "class_type": "TextEncodeQwenImage21"
        },
        "15": {
            "inputs": {
                "seed": 20261103, "steps": 20, "cfg": 3.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                "model": ["10", 0], "positive": ["13", 0], "negative": ["13", 1], "latent_image": ["13", 2]
            },
            "class_type": "KSampler"
        },
        "16": {"inputs": {"samples": ["15", 0], "vae": ["12", 0]}, "class_type": "VAEDecode"},
        "30": {"inputs": {"model_name": "RealESRGAN_x4plus.pth"}, "class_type": "UpscaleModelLoader"},
        "31": {"inputs": {"upscale_model": ["30", 0], "image": ["16", 0]}, "class_type": "ImageUpscaleWithModel"},
        "32": {"inputs": {"filename_prefix": "PIPELINE_STEP2_MASTER_4K", "images": ["31", 0]}, "class_type": "SaveImage"}
    }

    res2 = queue_prompt(prompt_step2)
    pid2 = res2["prompt_id"]
    print(f"Step 2 Queued (ID: {pid2}). Waiting for completion...")
    hist2 = wait_for_completion(pid2)
    
    # Locate output file
    step2_files = sorted(OUTPUT_DIR.glob("PIPELINE_STEP2_MASTER_4K_*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    step2_img_path = step2_files[0]
    final_sheet_path = DELIVER_DIR / "02_FINAL_MASTER_CHARACTER_SHEET_4K.png"
    shutil.copy(step2_img_path, final_sheet_path)
    print(f"Step 2 Finished! Master 4K Sheet: {final_sheet_path}")

    print("\n=========================================================")
    print("ALL DELIVERABLES READY IN D:\\63.ComfyuiStudio\\FilmStudio-NEWTECONS-JENNIEJOY\\UAT_RESULTS:")
    print("1. 01_FINAL_HERO_CHARACTER_PERFECT_BRANDING.png (Hero Character with 100% vector branding)")
    print("2. 02_FINAL_MASTER_CHARACTER_SHEET_4K.png (9-panel 4K Film Master Character Sheet)")
    print("=========================================================")

if __name__ == "__main__":
    import sys
    dept = sys.argv[1] if len(sys.argv) > 1 else "BAN TRUYỀN\nTHÔNG"
    run_pipeline(dept)
