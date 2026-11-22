---
name: 18xtao-anh-prompt-as-code
description: Thư viện và công cụ chuyên tạo prompt ảnh và video nghệ thuật 18+ / NSFW uncensored theo chuẩn Prompt-As-Code (tương thích MOSS-Image-SFT, Qwen Image 2.1, Noct-Q V4, MiniMax H3). Chứa trọn bộ 9 prompt mẫu chính thức từ axiomofmind, danh mục model local, và kiến trúc 2 workflow ComfyUI hoàn chỉnh (Step 1 Ảnh -> Step 2 Video -> Upscale 2K/FHD).
---

# 🔞 THƯ VIỆN PROMPT & PIPELINE 18+ CHUẨN PROMPT-AS-CODE (MOSS-IMAGE & MINIMAX H3)

Hệ thống sản xuất ảnh và video nghệ thuật 18+ / NSFW uncensored cục bộ trên **NVIDIA RTX 5080**, đạt chuẩn điện ảnh (Cinematic Photorealism) dựa trên bộ dữ liệu kiểm định từ **axiomofmind/Moss-image-nsfw-uncensored-lora**, **OpenMOSS-Team/MOSS-Image-SFT**, và **AfterMidnight-MiniMax-H3-NSFW**.

---

## 🗂️ 1. DANH MỤC MODEL CHUẨN CỤC BỘ (LOCAL INVENTORY)

Tất cả các model dưới đây đã được lưu trữ sẵn sàng trên máy và kiểm tra đường dẫn 100%:

### A. Pipeline Step 1: Tạo Ảnh Nhân Vật (Image Gen)
| Thành phần | Tên Model File | Kích thước | Thư mục lưu trữ |
| :--- | :--- | :---: | :--- |
| **Diffusion Model** | `NoctQ_V4_int8_convrot.safetensors` | 6.76 GB | `models/diffusion_models/` |
| **LoRA MOSS (Chính)** | `Moss_image_nsfw_uncensored_lora.safetensors` | 70.9 MB | `models/loras/` |
| **LoRA Qwen (Hỗ trợ)** | `NSFW_Qwen_Lora.safetensors` | 152 MB | `models/loras/` |
| **Merged Model Full** | MOSS-Image-SFT Merged Checkpoint | 27.2 GB | `Moss-image-nsfw-uncensored-lora/merged-model/` |
| **VAE Ảnh** | `qwen_image_2.1_vae_bf16.safetensors` | 644 MB | `models/vae/` |

### B. Pipeline Step 2: Tạo Video Chuyển Động (Video Gen)
| Thành phần | Tên Model File | Kích thước | Ghi chú kỹ thuật quan trọng |
| :--- | :--- | :---: | :--- |
| **Video Engine** | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | 19.53 GB | MiniMax H3 Reference-to-Video Audio |
| **Text Encoder** | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 14.61 GB | **BẮT BUỘC 32B (5120 dim)**. Không dùng 8B (4096 dim) gây lỗi ma trận |
| **Video LoRA** | `AfterMidnight_ref2va_h3_sexytime_rank64-v1.2.safetensors` | 1.11 GB | Chuyên dụng H3 Ref2VA uncensored |
| **Video VAE** | `minimax_h3_video_vae_int8_convrot.safetensors` | 2.62 GB | Giải mã 124 frames |
| **Audio VAE** | `minimax_h3_audio_vae_fp32.safetensors` | 577 MB | Giải mã âm thanh nền |

### C. Pipeline Upscale & Tỉ Lệ (2K / Full HD)
| Thành phần | Tên Model File | Kích thước | Ứng dụng |
| :--- | :--- | :---: | :--- |
| **Upscale Model** | `RealESRGAN_x4plus.pth` | 64 MB | Nâng nét chi tiết 4X cho 124 frames (<10s trên RTX 5080) |
| **Upscale Dự phòng** | `seedvr2_7b_int8_convrot.safetensors` | 7.76 GB | SeedVR2 7B Super-resolution |

---

## ⚙️ 2. HỆ THỐNG WORKFLOW COMFYUI HOÀN CHỈNH

Hệ thống gồm 2 workflow chạy tuần tự, lưu tại Desktop và thư mục ComfyUI:
* `C:\Users\Admin\Desktop\01_Moss-image-nsfw-uncensored-lora.json`
* `C:\Users\Admin\Desktop\02_Moss-video-nsfw-uncensored-lora.json`

```
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 1: 01_Moss-image-nsfw-uncensored-lora.json                       │
│ 3 Ảnh Đầu Vào: [Mặt CHAR_08] + [Dáng Pose] + [Trang Phục]             │
│   ──► Noct-Q V4 + LoRA MOSS (CFG 3.0, 30 steps)                       │
│   ──► Xuất Ảnh Nét: Gothic Lace Ensemble                              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Nối sang Step 2)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ STEP 2: 02_Moss-video-nsfw-uncensored-lora.json                       │
│ [Ảnh Step 1] + [Prompt H3 Ref2VA] + [Qwen3VL 32B] + [AfterMidnight]    │
│   ──► KSampler: euler + beta (BẮT BUỘC), 30 steps, CFG 5.0            │
│   ──► VAEDecode: 124 frames 768x512                                   │
│         │                                                              │
│         ├──► [Node 13: CreateVideo] ──► [Node 14: SaveVideo]           │
│         │    💾 XUẤT OUT 1: Video Gốc MP4 (768x512)                    │
│         │                                                              │
│         └──► [Node 16: Upscale RealESRGAN 4X]                          │
│                    │                                                   │
│                    ▼                                                   │
│              [Node 17: ImageScale (crop: center)]                      │
│              📐 CHỌN ĐỘ PHÂN GIẢI & TỈ LỆ                               │
│                    │                                                   │
│                    ▼                                                   │
│              [Node 19: CreateVideo] ──► [Node 20: SaveVideo]           │
│              🎬 XUẤT OUT 2: Video Cuối MP4 Siêu Nét (2K / Full HD)     │
└────────────────────────────────────────────────────────────────────────┘
```

### Bảng Cấu Hình Độ Phân Giải (Nhập tại Node 17)
* **TikTok / Reels / Shorts 2K (Mặc định):** Width = `1440` | Height = `2560` | crop = `center`
* **TikTok / Reels / Shorts Full HD:** Width = `1080` | Height = `1920` | crop = `center`
* **Màn Ngang 16:9 2K:** Width = `2560` | Height = `1440` | crop = `center`
* **Màn Ngang 16:9 Full HD:** Width = `1920` | Height = `1080` | crop = `center`

---

## ⚡ 3. QUY TẮC VẬN HÀNH & THÔNG SỐ KỸ THUẬT

| Thông số | Giá trị chuẩn | Ghi chú |
| :--- | :--- | :--- |
| **Trigger Phrase (Ảnh)** | `moss_xvstyle` | Bắt buộc đứng ở đầu prompt khi dùng mô hình MOSS-Image / LoRA MOSS. |
| **Inference Steps (Ảnh)** | `30` | 28–35 steps cho độ chi tiết nếp da và ánh sáng tối ưu. |
| **Guidance Scale (CFG Ảnh)** | `3.0` | Không để quá cao để tránh bết màu và cháy da. |
| **Sampler Video H3** | `euler` + `beta` | **BẮT BUỘC** cho LoRA AfterMidnight để chống méo tiếng/giật hình. |
| **CFG Video H3** | `5.0` | Giữ độ bám prompt và chuyển động tự nhiên. |
| **Độ dài Video** | `124 frames` | ~5.1 giây ở 24fps. |

---

## 📚 4. BỘ 9 PROMPT ẢNH CHUẨN MẪU (OFFICIAL DATASET)

### 📌 Sample 0 — Rear Close-up Bending Forward (Góc cận phía sau)
* **Thông số:** Scale `0.9` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, a close-up photograph of an adult woman with fair skin and long blonde hair, viewed from behind as she bends forward over a gray surface. Her body is positioned with her buttocks prominently displayed, revealing her vulva and labia in a natural, unposed state. She wears a white thong that is pulled down to expose her intimate area. The lighting is soft and natural, highlighting the smooth texture of her skin. The background is blurred, suggesting an indoor setting with neutral tones.
```

### 📌 Sample 1 — Bedroom Mirror Scene (Cảnh phòng ngủ phản chiếu gương)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A full-body photograph shows an adult woman with a curvaceous body and long brown hair styled in a braid, kneeling on a wooden floor with her back to the camera and her head resting on her arms. Her skin tone is light tan, and she is completely nude, with her large buttocks prominently displayed and her vulva visible between her thighs. She wears a gold anklet and a green floral hair accessory. Her gaze is directed downward, and her expression is neutral. The setting is a bedroom with a large mirror reflecting her pose, a white upholstered chair, and light-colored curtains. The lighting is soft and indoor, and the camera angle is a medium shot from behind.
```

### 📌 Sample 2 — Crouching Room Portrait (Góc thấp ngồi xổm)
* **Thông số:** Scale `0.9` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, a nude adult woman with fair skin and shoulder-length light brown hair is photographed in a medium close-up from a slightly low angle. She is crouching with her legs spread wide, exposing her vulva and labia, while her left hand rests on a wooden surface behind her. Her right arm is raised above her head. She has a belly button piercing with a silver stud and is wearing white ankle socks with yellow smiley faces. Her facial expression is neutral, and she gazes directly at the camera. The setting is an indoor room with a white wall, a dark television screen, and a white lamp in the background. The lighting is soft and even, highlighting her smooth skin and large breasts. The image is a photograph.
```

### 📌 Sample 3 — Reclining POV (Góc nhìn thứ nhất nằm ngửa)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, an adult woman with long blonde hair styled in loose waves and fair skin is positioned in a close-up POV shot, lying on her back with her legs spread wide to expose her vulva and labia. She wears a black halter-style top that leaves her breasts bare and has a tattoo on her lower abdomen. Her right hand rests between her thighs with fingers near her clitoris, and she wears a ring on her finger. Her mouth is slightly open and she gazes directly at the camera with an aroused expression. The setting appears to be a modern indoor room with light-colored walls, a metal railing, and wooden cabinetry in the background, illuminated by soft overhead lighting. The image is a photograph.
```

### 📌 Sample 4 — Side-lying Close-up (Nằm nghiêng tự nhiên)
* **Thông số:** Scale `0.7` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A close-up photograph of an adult woman lying on her side on a gray fabric surface, her left hand resting on her upper thigh with pink-painted fingernails visible. She has light brown skin and is nude, with her legs bent and pressed together, exposing her vulva and inner thighs. Her gaze is directed toward the camera with a neutral expression. The background is softly blurred, suggesting an indoor setting with natural lighting. The image is a photograph.
```

### 📌 Sample 5 — Rear Bedside Pose (Bên mép giường với áo ren đỏ)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A realistic adult photograph of a curvy woman with long dark wavy hair kneeling near the edge of an unmade bed in a rear three-quarter pose. She wears a burgundy lace camisole lifted above her waist and matching panties pulled down around her upper thighs, leaving her buttocks, vulva, and labia visibly exposed. She looks back over her shoulder toward the camera with a calm expression. Soft bedside lamplight mixes with cool evening window light, creating detailed natural skin texture and gentle shadows. The framing is a medium full-body portrait in a tasteful contemporary bedroom.
```

### 📌 Sample 6 — Reclining Velvet Sofa (Nằm nghiêng trên sofa nhung xanh)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A close natural-light photograph of an adult woman with warm brown skin and short curly black hair reclining on her side across a deep green velvet sofa. She is nude with her upper leg raised and bent, naturally revealing her breasts, inner thighs, vulva, and labia while her lower hand rests loosely on her hip. She looks directly at the camera with a neutral, intimate expression. Diffuse morning light from a nearby window creates soft dimensional shadows, realistic pores, and detailed fabric texture. The composition is a horizontal-feeling three-quarter body portrait captured from sofa height in a quiet living room.
```

### 📌 Sample 7 — Marble Vanity (Bàn đá cẩm thạch với áo choàng lụa)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A realistic frontal photograph of an adult East Asian woman with long straight black hair seated on the edge of a white marble bathroom vanity. She wears an open cream satin robe around her shoulders and is otherwise nude, sitting with her legs apart so her breasts, vulva, and labia are naturally and clearly visible. One hand rests beside her on the counter while the other touches the robe collar. Her expression is calm and self-assured as she looks toward the camera. Soft morning window light and warm vanity bulbs create balanced highlights, realistic skin texture, and gentle shadows in a refined modern bathroom.
```

### 📌 Sample 8 — Sunlit Bed Rear Pose (Ánh nắng trưa xuyên rèm)
* **Thông số:** Scale `0.8` | Steps `30` | CFG `3.0` | Seed `42`
* **Prompt:**
```text
moss_xvstyle, A detailed adult photograph of a freckled woman with long copper-red hair posed on her hands and knees across rumpled white bedsheets, viewed from a rear three-quarter angle. She wears a sheer pale-blue lingerie top and matching underwear pulled down below her buttocks, clearly revealing her vulva and labia between her thighs. She turns her head toward the camera with a relaxed expression. Strong but diffused midday sunlight passes through gauzy curtains, producing natural skin tones, visible freckles, soft shadows, and crisp bedding texture in an airy bedroom.
```

---

## 🎬 5. BỘ 9 PROMPT VIDEO CHUẨN MẪU (H3 REF2VA MOTION FLOW)

Sử dụng trực tiếp trong Node 7 `MiniMaxH3ReferenceToVideo` để nối tiếp chuyển động từ ảnh Step 1:

### 🎥 Video Prompt 0 — Bending Forward Motion
```text
The woman from the reference image, maintaining her bent-forward pose over the gray surface, gently shifts her hips from side to side. Her hands adjust their grip on the surface, and her head slowly turns toward the camera, her long blonde hair cascading over her shoulders. The camera maintains a stable close-up shot with subtle breathing motion. Soft natural light shifts gently across her skin.
```

### 🎥 Video Prompt 1 — Bedroom Mirror Movement
```text
The woman from the reference image, kneeling gracefully on the wooden floor, slowly arches her back and lifts her head from her arms. She glances into the large bedroom mirror, her expression soft and alluring. The camera executes a slow cinematic dolly-in toward her reflection. Warm bedroom ambient light highlights the subtle motion of her muscles and curves.
```

### 🎥 Video Prompt 2 — Crouching Pose Dynamic
```text
The woman from the reference image, crouching with legs spread, slowly lowers her raised arm while shifting her center of gravity. She maintains steady, confident eye contact with the camera, a subtle confident smile appearing on her lips. The camera executes a subtle low-angle push-in, keeping her centered with even studio lighting.
```

### 🎥 Video Prompt 3 — Reclining POV Intimate Motion
```text
The woman from the reference image, reclining on her back in POV view, gently moves her hand across her inner thigh in a slow sensual stroke. Her chest rises and falls with rhythmic breathing, and her parted lips whisper softly while gazing upward into the camera. Soft overhead light creates gentle specular highlights on her skin.
```

### 🎥 Video Prompt 4 — Side-lying Elegant Motion
```text
The woman from the reference image, lying on her side on the gray fabric, slowly adjusts her posture, sliding her top leg slightly back to reveal more natural curves. Her fingers trace slowly along her hip as she exhales softly, looking directly into the lens. The camera subtly floats at eye-level with cinematic depth of field.
```

### 🎥 Video Prompt 5 — Bedside Turn & Glance
```text
The woman from the reference image, kneeling beside the bed in her lace camisole, slowly turns her upper body toward the camera. Her hand gently grazes the rumpled sheets as she tilts her head, her dark wavy hair swaying gently. Bedside warm lamplight mixes with cool twilight from the window, creating cinematic skin contrast.
```

### 🎥 Video Prompt 6 — Velvet Sofa Seductive Shift
```text
The woman from the reference image, reclining on the green velvet sofa, extends her bent leg outward slowly and draws her hand across her waist. Her head tilts back against the sofa cushion before turning her intimate gaze back to the camera. Morning sunlight shifts subtly through the window, accentuating natural skin pores and velvet fabric texture.
```

### 🎥 Video Prompt 7 — Marble Vanity Confident Motion
```text
The woman from the reference image, seated on the marble vanity with her open cream robe, slowly raises one hand to adjust her collar while slightly spreading her knees. She leans forward with calm self-assurance, looking directly at the viewer. Soft morning reflections on the marble counter complement the warm vanity lights.
```

### 🎥 Video Prompt 8 — Sunlit Bed Kneeling Motion
```text
The woman from the reference image, on her hands and knees across the rumpled white sheets, slowly rolls her hips in a gentle, fluid motion. She looks back over her shoulder, her relaxed gaze locking onto the camera as a light breeze moves the sheer curtains, creating undulating patterns of warm sunlight across her back.
```

---

## 🚫 6. NEGATIVE PROMPT CHUẨN CHẶN LỖI (CHỐNG NHỰA / 3D / GIẬT LAG)

Dán vào ô Negative Prompt ở cả Step 1 và Step 2:

```text
anime, cartoon, 3d render, cgi, plastic skin, doll face, airbrushed, porcelain skin, illustration, drawing, extra fingers, missing fingers, deformed hands, distorted anatomy, unnatural body proportions, overexposed, low resolution, blurry, watermark, censored, mosaic, blur bar, jittery motion, sudden jumps, unnatural movement, frame flicker, distorted face
```


---

## 🔬 7. CẨM NANG VIẾT PROMPT 18+ NÂNG CAO (TỪ GITHUB & COMFYUI META 2026)

*Tổng hợp từ các kho lưu trữ chuyên biệt hàng đầu trên GitHub:*
- `FineComputer14451/Grok-Imagine-NSFW-Bible` (Tháng 2/2026 Meta)
- `flamin-galah/ComfyUI-Flamin-Galah` (MiniMax H3 Ref2VA & I2VA Node)
- `illuminatianon/Z-Image-Turbo-Prompting-Guide`

---

### A. Công Thức Chuẩn H3 Ref2VA của MiniMax (Từ `ComfyUI-Flamin-Galah`)
Đối với MiniMax H3, cách viết tối ưu nhất để model bám chặt 100% vào ảnh tham chiếu là dùng cú pháp **Anchor Tag**:

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] The scene begins from the supplied still, preserving the subject, facial features, hair, and clothing. The woman slowly shifts her hips, leaning slightly back on the bed while tilting her head with a relaxed intimate smile. The camera executes a subtle slow dolly-in. Warm ambient lighting creates soft specular highlights across her skin.

overall_soundscape: Soft fabric rustling and gentle rhythmic breathing.

non_diegetic_music: N/A
```

---

### B. 5 Lớp Cấu Trúc Khóa Tính Liền Mạch (Continuity Lock từ `NSFW-Bible`)
Khi chuyển từ Ảnh (Step 1) sang Video (Step 2) hoặc nối chuỗi video:

1. **Khóa Danh Tính & Đặc Điểm Cơ Thể (Continuity Lock):**
   * `Seamless continuation from exact last frame: preserve identical nude body, facial features (jawline, full lips, eye shape), long hair flow, exact breast perkiness, narrow waist, skin tone and oil sheen consistency.`
2. **Ngôn Ngữ Giải Phẫu Học Chính Xác (Anatomic Precision):**
   * Tránh dùng từ lóng tục tĩu (dễ làm model sinh hình méo mó). 
   * **Nên dùng thuật ngữ chuẩn:** `vulva, labia, natural breast drape, inner thighs, toned lower abdomen, visible pores, soft specular skin highlights`.
3. **Động Từ Chuyển Động Điện Ảnh (Cinematic Motion Verbs):**
   * *Động từ chất lượng cao cho Video H3:* `gently arches her back`, `slow rhythmic hip undulation`, `breathing rise and fall`, `slides her hand along her thigh`, `head tilts with parted lips`, `cascading hair sway`.
4. **Ánh Sáng & Góc Máy Tạo Khối (Dimensional Lighting):**
   * `volumetric rim lighting`, `soft bedside lamplight mixing with cool window twilight`, `oil sheen on skin`, `cinematic depth of field, subtle bokeh`.
5. **Âm Thanh Nền & Tiếng Động (Audio Multimodal Sync):**
   * MiniMax H3 hỗ trợ cả âm thanh Audio VAE, vì vậy prompt cần bổ sung miêu tả tiếng động để video có sinh khí:
   * `overall_soundscape: soft needy whisper, synced rhythmic breathing rising with movement, faint fabric rustle against bedsheets.`


---

## 🏡 8. CHUẨN PROMPT LỐI SỐNG SINH HOẠT (LIFESTYLE CANDID PROMPT-AS-CODE)

Thay vì ảnh chụp trong studio nhân tạo gượng gạo, phong cách **Lối sống sinh hoạt (Lifestyle Candid)** tạo ra những bức ảnh intimate đời thường chân thực tuyệt đối:

### Cấu Trúc Khóa 4 Yếu Tố Sinh Hoạt:
1. **Bối cảnh đời thường (Authentic Living Space):**
   * Giường ngủ chưa dọn (`unmade low wooden bed with rumpled white linen sheets`).
   * Phòng khách sáng sớm (`relaxing on green velvet living room sofa with coffee mug`).
   * Bàn đá phòng tắm tắm nắng (`sunlit marble bathroom vanity with open silk robe`).
2. **Khoảnh khắc ngẫu hứng không tạo dáng (Unposed Morning Moment):**
   * Vừa thức giấc lười biếng (`waking up naturally, lounging across pillows, stretching`).
   * Tóc rối sáng sớm (`messy morning hair cascading over pillows`).
3. **Ánh sáng tự nhiên (Natural Ambient Sunlight):**
   * Thay vì đèn studio hắt gắt, dùng ánh nắng xiên qua rèm voan (`warm golden morning sunlight filtering through sheer curtains, soft dimensional shadows`).
4. **Trang phục buông lơi tự nhiên (Casual Intimate Loungewear):**
   * Nội y hoặc áo choàng mặc hờ hững (`sheer lingerie draped casually, panties loosely pulled down, unbuttoned silk robe`).


---

## 🎞️ 9. PIPELINE MASTER 20 GIÂY LIỀN MẠCH (STEP 3: LONG TAKE 20S)

*File workflow:* `03_Moss-video-20s-longtake-nsfw-uncensored-lora.json`

### Cơ Chế Hoạt Động Của Step 3:
1. **Đầu vào (Input):** 
   * **ẢNH (từ Step 1)** làm Frame 0 (ảnh bắt đầu của video) + Ảnh tham chiếu nhân vật (Ref Image).
   * *Mẹo nối tiếp:* Nếu muốn nối tiếp chuyển động từ Video Step 2, chỉ cần lấy **Frame cuối cùng (Last Frame)** của Video Step 2 làm ảnh bắt đầu (Frame 0) của Step 3!
2. **Cấu Trúc 8 Cửa Sổ Trượt (8 Context Windows):**
   * Tổng độ dài: **481 frames ở 24 fps = 20.04 giây** không cắt cảnh (Long Take).
   * Chia nhỏ thành 8 khoảng thời gian (Window 0 đến 7) giúp GPU RTX 5080 (16GB VRAM) render 20s mượt mà mà không bao giờ bị tràn bộ nhớ.
3. **Dual LoRA Chạy Song Song (Turbo 8-Step + AfterMidnight):**
   * `pika_h3_flex_turbo_8step_hd_ref2va` (giúp 20 giây chỉ mất 8 steps, render trong ~5–6 phút).
   * `AfterMidnight_ref2va_h3_sexytime_rank64-v1.2` (giữ trọn vẹn đặc trưng giải phẫu 18+ và chuyển động quyến rũ).
4. **Đầu ra (Output):**
   * **OUT 1:** Video gốc 20s MP4 (1280 $	imes$ 704).
   * **OUT 2:** Video 20s MP4 **2K Siêu Nét (1440 $	imes$ 2560 - Chuẩn TikTok 9:16)** hoặc 16:9 ngang!


---

## 🎭 10. CHUẨN KHÓA MẶT 100% (IDENTITY LOCK) & CÔNG THỨC DA THẬT CHỐNG NHỰA (ANTI-PLASTIC SKIN ENGINE)

> Giải quyết dứt điểm lỗi "mặt bị biến dạng", "trôi danh tính (identity drift)" và "nước da trông giả / bóng nhựa / búp bê 3D".

### A. Cấu Trúc 5 Lớp Khóa Mặt Bất Biến (The 5-Layer Face-Lock Protocol)

1. **KEYWORD (Câu Lệnh Mở Khóa Bắt Buộc):**
   * Bắt đầu prompt bằng câu định danh quyền năng:
     * `Use the exact face from the reference image <image1> with 100% identity accuracy.`
     * `Preserve the precise facial structure, proportions, and all unique identity traits.`
2. **REF (Reference Anchors - Điểm Neo Tham Chiếu):**
   * Buộc AI bám chặt từng ngũ quan ảnh gốc, cấm tự bịa:
     * `Match the eyes, eyebrows, jawline, nose, lips exactly as in the reference.`
     * `Do not alter shape, age, or facial geometry.`
3. **LOCK (Anti-Drift Commands - Chống Trôi Mặt):**
   * Ngăn chặn hoàn toàn việc AI "tự chế hoặc pha trộn mặt":
     * `No face blending, no AI beautification, no reconstruction.`
     * `Do not stylize the face.`
     * `Avoid identity drift.`
     * `Strict face preservation required.`
4. **DETAIL (Hyper-Realistic Skin & Pores - Khắc Họa Da Thật):**
   * Ép AI render lỗ chân lông và kết cấu da người thật:
     * `Ultra-detailed skin texture, micro-expressions preserved.`
     * `Realistic visible micro-pores and fine lighting on facial contours.`
     * `Natural epidermal grain, authentic subsurface scattering, unretouched.`
5. **LIMIT (Boundaries - Giới Hạn Cấm Xâm Phạm):**
   * Đặt ranh giới cứng loại bỏ lỗi "da búp bê láng mịn":
     * `Do not change hairstyle unless specified.`
     * `Do not alter facial fat distribution.`
     * `No smoothing, no beauty filter, no plastic airbrushing.`

---

### B. TỔ HỢP VÀNG: PROMPT GIỮ MẶT 100% (BẢN CHUẨN QUỐC TẾ PRO-USE)

Đoạn văn quyền năng dùng ngay cho mọi prompt khi muốn giữ trọn vẹn khuôn mặt thật từ ảnh gốc:

```text
Use the exact facial identity from the reference image <image1> with 100% accuracy. Preserve all facial geometry including jawline, eyes, eyebrows, nose, lips, and micro-expressions exactly as provided. No face blending, no beautification, no stylization, and avoid identity drift at all costs. Maintain original age, proportions, and unique identity traits. Reproduce ultra-detailed skin textures, realistic visible pores, natural shadows, and fine lighting reflections on the face. The identity must remain unchanged throughout the render.
```

---

### C. 5 LỖI THƯỜNG GẶP LÀM HỎNG MẶT VÀ SINH DA BÚP BÊ NHỰA

* ❌ **Dùng từ "handsome, beautiful, attractive, gorgeous":** AI sẽ tự ý "thẩm mỹ hóa" làm lệch sống mũi, gọt cằm và mất 90% nét mặt gốc. Thay vào đó, hãy dùng: *"preserving exact facial features and authentic expression"*.
* ❌ **Dùng từ "smooth skin, soft skin, flawless skin":** AI sẽ bật bộ lọc làm mịn (airbrush), xóa sạch lỗ chân lông và biến da thành búp bê nhựa/tượng sáp. Thay vào đó, bắt buộc dùng: *"natural skin texture with visible micro-pores, fine lines, subtle imperfections, unretouched"*.
* ❌ **Để lọt phong cách anime, cartoon, 3D render, wireframe, polygonal:** Khiến khuôn mặt mất sạch identity embedding và biến thành nhân vật hoạt họa.
* ❌ **Chọn ảnh tham chiếu mờ / mặt nghiêng góc quá gắt / ngược sáng tối đen:** AI không đọc được các điểm mốc (facial landmarks) để neo giữ.
* ❌ **Ảnh gốc độ phân giải < 600px:** Mất vector đặc trưng khuôn mặt trong CLIP Vision encoder.

---

## 🧠 11. HỆ THỐNG CÔNG THỨC TỰ SINH PROMPT ĐIỆN ẢNH & QUẢNG CÁO CAO CẤP

### A. CÔNG THỨC VÀNG ĐIỆN ẢNH: S + A + E + ST + T

| Thành phần | Ý nghĩa | Ví dụ thực tế |
| :--- | :--- | :--- |
| **S (Subject)** | Chủ thể chính, đếm được | `A young adult woman preserving exact face from <image1>` |
| **A (Action/Appearance)** | Ngoại hình + hành động | `wearing unbuttoned white silk cheongsam from <image3>, reclining relaxed with arms behind head, soft natural smile` |
| **E (Environment)** | Bối cảnh không gian & thời gian | `lying on rumpled white silk bedsheets in an airy sunlit bedroom, morning window light` |
| **ST (Style)** | Phong cách nghệ thuật | `candid intimate 35mm photography inspired by Wong Kar-wai & Helmut Newton` |
| **T (Technical)** | Thông số kỹ thuật máy ảnh & ánh sáng | `35mm lens, f/1.4, shallow depth of field, 4k resolution, visible skin pores, unairbrushed, 28 steps Euler` |

#### 👉 Ví dụ áp dụng:
* **Viết sai (Chung chung):** *"Tạo ảnh cô gái đẹp trên giường"* ➔ AI sinh mặt vô hồn, da nhựa.
* **Viết đúng chuẩn S+A+E+ST+T:**
  > *A young Asian woman with exact face from `<image1>` (S), wearing an open white silk cheongsam, smiling softly while resting arms behind head (A), lying across rumpled white silk bedsheets in sunlit modern bedroom (E), in intimate candid cinematic style (ST), 4k resolution, 35mm lens, f/1.4, natural morning lighting, visible pores (T).*

---

### B. PHƯƠNG PHÁP TƯ DUY 5W1H TỰ SÁNG TẠO PROMPT
Trả lời 6 câu hỏi cốt lõi trước khi ghép lệnh:
1. **Who (Ai?):** Nhân vật nữ có danh tính được khóa 100% từ `<image1>`.
2. **What (Làm gì?):** Nằm ngửa thư giãn trên giường, vạt áo buông hờ, ánh mắt gợi cảm.
3. **Where (Ở đâu?):** Phòng ngủ penthouse hiện đại, đệm lụa trắng.
4. **When (Khi nào?):** Ban mai 8:00 AM, ánh sáng dịu nhẹ xuyên qua rèm voan mỏng.
5. **Which Style (Phong cách gì?):** Nhiếp ảnh lookbook điện ảnh cao cấp (High-end candid intimacy).
6. **How (Làm thế nào - Kỹ thuật?):** 35mm raw film, f/1.4, da người thật rõ lỗ chân lông, không làm mịn nhựa.

---

### C. CÔNG THỨC QUẢNG CÁO CAO CẤP (CREATIVE AGENCY): S + M + E + V + ST + L + T

Công thức chuẩn quốc tế mà các Creative Agency hàng đầu sử dụng để tạo concept thương mại triệu đô:

| Ký hiệu | Thành phần | Ý nghĩa chuyên môn |
| :---: | :--- | :--- |
| **S** | **Subject** | Đối tượng quảng cáo / nhân vật trung tâm chuẩn mặt |
| **M** | **Message** | Thông điệp thương hiệu ("sự tự tin, vẻ đẹp thuần khiết và đẳng cấp quyến rũ") |
| **E** | **Environment** | Bối cảnh sang trọng, gợi cảm giác sản phẩm cao cấp |
| **V** | **Visual Elements** | Đạo cụ UI/UX marketing (khối lụa satin, ly rượu vang, rèm voan ban mai) |
| **ST** | **Style** | Phong cách thương hiệu từ studio quốc tế (Editorial, Vogue Lookbook) |
| **L** | **Lighting** | Ánh sáng thương mại có chiều sâu (soft directional lighting, specular highlight) |
| **T** | **Technical** | Chuẩn kỹ thuật studio (4k uhd, 16:9, authentic texture, zero blur) |

#### ⭐ KHUÔN PROMPT QUẢNG CÁO MẪU (AI AD MASTER):
```text
Create a high-end commercial visual featuring [S]. 
Convey the message of [M]. 
Place the scene in [E], incorporating key visual elements like [V]. 
Render the composition in [ST] style, with [L] lighting. 
Ensure hyper-realistic textures, natural skin with visible pores, premium materials, and a polished, studio-quality look suitable for modern advertising, 4k ultra high resolution.
```

#### 🎁 MẪU PHONG CÁCH APPLE KEYNOTE:
```text
Create a minimalist, ultra-clean commercial featuring [S], surrounded by floating pure white silk fabrics and soft morning light, with pure white directional illumination and polished subtle reflections, resembling an Apple keynote advertisement aesthetic, clean, flawless, cinematic 8k.
```

---

## 🎬 12. QUY TRÌNH PHÂN CẢNH ĐA DÁNG (MULTI-SHOT LIFESTYLE SCENE)

> Triết lý sống còn: **"1 Scene phải có nhiều Shot — Nuôi một nhân vật sống động có lối sinh hoạt đời thường thay vì sinh 1 ảnh ma-nơ-canh đơn độc."**

Trong 1 Scene "Phòng ngủ buổi sáng", người dùng có thể tạo một bộ Storyboard hoàn chỉnh gồm 4 đến 8 góc máy khác nhau bằng cách phối hợp:

| Shot # | Tên Shot / Góc máy | Dáng nạp tại Node 2 | Chi tiết bố cục & ánh sáng |
| :---: | :--- | :--- | :--- |
| **Shot 01** | **Toàn cảnh quyến rũ (Wide Angle)** | `full_sexy_P053_front.png` | Toàn thân nằm nghiêng trên đệm lụa, chân co tự nhiên, vạt áo buông hờ khoe đường cong hông |
| **Shot 02** | **Nằm ngửa co gối (Supine Relaxed)** | `full_sexy_P050_front.png` | Nằm ngửa hai chân khép nghiêng, ngực trần tự nhiên, ánh nắng ban mai chiếu xiên qua đệm |
| **Shot 03** | **Hai tay sau đầu (Candid Intimate)** | `full_sexy_P078_low.png` | Nằm ngửa hai tay gối sau đầu, mắt nhìn ống kính cười mỉm, nét mặt tự nhiên |
| **Shot 04** | **Nằm mở rộng chân (Sensual High Angle)** | `full_sexy_P064_front.png` | Góc máy cao (Top-down) nhìn từ trên xuống, dáng nằm tự do, táo bạo |
| **Shot 05** | **Cận cảnh chân dung (Beauty Close-up)** | `upper80v2_P053_front.png` | Cận cảnh gương mặt, bờ vai trần và xương quai xanh, rõ từng lỗ chân lông và vân da |

### 🚀 Cách Vận Hành Tự Động Hóa Trong ComfyUI:
1. **Sinh tự động 4-8 tấm/lượt (Batch Run):** Đổi ô số bên cạnh nút **Run** từ `1` thành `4` (hoặc `6`, `8`). Node KSampler với tính năng `randomize seed` sẽ tự động dệt nên 4-8 bức ảnh với các biến thể biểu cảm và góc sáng khác nhau liên tục.
2. **Khóa 100% nhân diện:** Cột 1 giữ nguyên ảnh mặt `<image1>`, Florence-2/JoyCaption sẽ tự quét các dáng ở Node 2 và tạo ra phân cảnh sống động như phim điện ảnh thật.


---

## 🔒 13. CẨM NANG ĐẠT 100% GIỐNG MẶT & 2 PROMPT KHÓA MẶT READY-TO-USE

### A. 4 Quy Tắc Cốt Lõi Để Đạt 100% Giống Mặt

1. **Tiêu chuẩn ảnh gốc đầu vào (Input Photo):**
   * Phải rõ nét, góc chụp chính diện, ánh sáng đều, không makeup dày cộp, không filter làm mịn. (AI trích xuất tới 80% đặc tính nhận dạng từ ảnh này).
2. **Tuân thủ khung 5 lớp (ID + REF + LOCK + DETAIL + LIMIT):**
   * Đây là xương sống bắt buộc để chống méo mó hoặc trôi mặt qua các góc chụp.
3. **Tuyệt đối không mô tả khuôn mặt bằng tính từ chủ quan:**
   * **CẤM DÙNG:** `cool face`, `strong face`, `perfect jawline`, `handsome`, `beautiful`, `sexy face` ➔ AI sẽ tự động "vẽ lại" khuôn mặt theo định kiến thẩm mỹ của nó.
4. **Luôn dùng phong cách gần với ảnh chụp thực tế (Realistic Photography):**
   * **Nên dùng:** `realistic`, `cinematic`, `studio lighting`, `35mm raw photograph`, `unretouched`.
   * **Cấm tiệt:** `anime`, `cartoon`, `Pixar`, `3D CG`, `wireframe`, `polygonal`.

---

### B. 2 PROMPT KHÓA MẶT READY-TO-USE (BẢN QUỐC TẾ DÙNG NGAY)

#### 📸 (1) Khóa Mặt Khi Tạo Ảnh (Image Generation):
```text
Preserve the exact identity from the reference image <image1> with 100% accuracy. No changes to facial geometry, no stylization, no beautification. Maintain all original proportions including eyes, nose, lips, jawline, and skin texture. Avoid identity drift completely.
```

#### 🎥 (2) Khóa Mặt Khi Tạo Video (Video H3 Ref2VA - Cực Mạnh):
```text
Lock the facial identity to the reference image across all frames. Maintain consistent bone structure, facial proportions, natural micro-expressions, and skin tones without drifting, morphing, or distortion. The woman preserves her exact unique facial features from <Picture 1> throughout all camera movements.
```
