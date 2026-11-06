---
name: create-video-childrent-flashcard-chinese
description: "Tạo video flashcard tiếng Trung cho bé mầm non: pinyin + Hán tự + bản dịch Việt + bé NGƯỜI THẬT nhép miệng đúng từ + avatar 3D, dựng bằng Remotion với nhạc nền và SFX pop. Dùng khi cần sinh thẻ từ vựng tiếng Trung (说话/听/看/笑/没关系…), giữ nhân dạng nhân vật qua lip-sync MiniMax H3, hoặc sửa lỗi da bé bị lông/mốc."
---

# create-video-childrent-flashcard-chinese

Video flashcard tiếng Trung cho bé 3–5 tuổi. Mỗi thẻ: pinyin trên, Hán tự + nghĩa Việt dưới
(cột trái), bé người thật đang nói trong khung bo góc (cột phải), nền kem nhạt,
nhạc nền + SFX pop, kết bằng outro cảm ơn.

**Dự án:** `J:\1.JennieHomeSchool\03 Voice\create-video-childrent-flashcard-chinese`
**Bàn giao:** `WORKFLOW-BAN-GIAO.md`

---

## Hợp đồng đầu ra

| Hạng mục | Giá trị |
|---|---|
| Canvas | 1920×1080, 30 fps |
| Thời lượng | 5 thẻ × 5 s + outro 4,7 s = **29,72 s** |
| Mỗi thẻ | 4 giây **bé thật nói** + 1 giây **avatar 3D** |
| Audio | giọng bé + nhạc nền −20 dB + 2 SFX/thẻ |
| Đầu ra | `out/zh-kids-v4.mp4` |

## 3 bước bắt buộc (đừng gộp)

```
STEP 1  text -> ảnh bé thật          Qwen-Image 2512       ~66 s/ảnh
STEP 2  ảnh + audio -> bé nói        MiniMax H3 ref2va     ~280 s/clip
STEP 3  ghép thẻ + nhạc + SFX        Remotion              ~2 phút
```

Workflow đã lưu, đặt tên có cấu trúc, có group theo step:
```
production-local/ComfyUI/user/default/workflows/JENNIEJOYKIDS/ChineseFlashcard/
  FLASHCARD-ZH_S1-3D_ALICE_v1-{speaking,listening,looking,laughing,okay}.json
  FLASHCARD-ZH_S1-3D_JENSU_v1-{…}.json
  FLASHCARD-ZH_S1-REAL_C1-girl-bangs_v1-speaking.json … C5
  FLASHCARD-ZH_S2-TALK_C1-girl-bangs_v1-shuohua.json … C5
  _NAMING.md                     <- quy ước đặt tên + bảng nhân vật
  _archive-superseded/           <- bản cũ, KHÔNG dùng
```

**Mẫu tên:** `FLASHCARD-ZH_{STEP}_{KIND}_{ASSET}_v{N}-{VARIANT}.json`

| Phần | Giá trị |
|---|---|
| `S1` / `S2` / `S3` | bước sinh ảnh / lip-sync / ghép |
| `3D` / `REAL` / `TALK` | avatar cartoon / bé thật / clip đang nói |
| `ALICE` `JENSU` `C1…C5` | mã nhân vật |
| `v1` | tăng khi đổi prompt hoặc model |
| `speaking` `shuohua` … | tư thế hoặc từ vựng |

---

## Hai loại nhân vật — hai pipeline khác nhau

| Loại | Dùng cho | Model | File workflow |
|---|---|---|---|
| **Người thật** | bé đọc từ (4 giây đầu mỗi thẻ) | Qwen-Image 2512 | `*_S1-REAL_*.json` |
| **3D cartoon** | avatar đóng thẻ (giây thứ 5) | Krea2 Identity Edit | `*_S1-3D_*.json` |

### Pipeline A — Nhân vật 3D (Alice / Jensu)

Dùng **Krea2 Identity Edit**: giữ nhân dạng qua ảnh tham chiếu, đổi tư thế bằng prompt.

```
UNETLoader(krea2_turbo_int8_convrot)
  → LoraLoaderModelOnly(krea2_identity_edit_v2)      ← BẮT BUỘC trước patch
  → Krea2EditModelPatch(ref_boost=1.0, fit_mode=fit, target_latent=...)
  → KSampler(10 steps, cfg 1.0, euler/simple)
CLIPLoader(qwen3vl_4b_fp8_scaled, type=krea2)
VAELoader(qwen_image_vae)
Krea2EditGroundedEncode(clip, prompt, image=ref, grounding_px=768)  ← positive
Krea2EditGroundedEncode(clip, prompt="", image=ref)                 ← negative (rỗng là ĐÚNG)
```

**Ảnh tham chiếu gốc:**

| Nhân vật | Đường dẫn canonical |
|---|---|
| Alice | `production-local/character-library/alice/2026-10-18-v1/canonical-approved.png` |
| Alice expressions | `…/expressions/3d/alice-{neutral,happy,laughing,wink,thinking,surprised,…}.png` (12 icon) |
| Jensu | `create-video-childrent-flashcard-chinese/public/portraits/jensu-canonical.png` |

**Bắt buộc:** làm phẳng `canonical.png` (RGBA) → RGB trên nền kem, lưu
`production-local/ComfyUI/input/<name>-flat.png`. Không làm phẳng → tóc đỏ, nền đen.

**Prompt mẫu (Alice):**
```
the same preschool girl from the reference, identical face, identical large dark-brown
eyes, identical black bob with straight bangs and a pink bow on the anatomical right,
identical rose-pink pyjama top with one centred white heart, identical warm peach skin,
identical stylized 3D animation sculpt with soft hair strands. chest-up portrait,
centred, front-facing. flat solid pale cream background, no gradient, no floor,
no props, soft studio key light, warm and gentle. {action}
```

`{action}` cho 5 tư thế:

| File | Action |
|---|---|
| `S1-3D_ALICE_v1-speaking` | mouth open in a rounded speaking shape, one small hand raised near the chest |
| `S1-3D_ALICE_v1-listening` | head tilted, eyebrows raised, one hand cupped behind the ear |
| `S1-3D_ALICE_v1-looking` | one hand shading the eyes like a visor, eyes wide open |
| `S1-3D_ALICE_v1-laughing` | big open-mouth smile, cheeks lifted, eyes crinkled |
| `S1-3D_ALICE_v1-okay` | both palms open at chest height, warm gentle smile |

**Chất lượng đo được:** lap_var 160 ở 1536 px / 30 steps (so với 100 ở 1024/24).
Sinh ở 1536 rồi hạ xuống cho nét hơn.

### Pipeline B — Bé người thật

Text → ảnh, **không dùng ảnh tham chiếu** (mỗi bé là nhân vật mới).

```
UNETLoader(qwen_image_2512_fp8_e4m3fn)
CLIPLoader(qwen_2.5_vl_7b_fp8_scaled, type=qwen_image)
VAELoader(qwen_image_vae)
EmptySD3LatentImage(1024, 1024)
CLIPTextEncode ← prompt đầy đủ (xem Bước 1)
KSampler(30 steps, cfg 4.5, euler/simple)
```

**Casting 5 bé** (khớp video mẫu):

| File | Giới | Tuổi | Tóc | Áo | Nền |
|---|---|---|---|---|---|
| `c1-girl-bangs` | gái | 4 | mái ngang, ngang cằm | mint | pale peach |
| `c2-boy-blue` | trai | 5 | rẽ ngôi mềm | xanh dương | sky blue |
| `c3-girl-pigtail` | gái | 4 | hai bím buộc hồng | hồng | warm apricot |
| `c4-boy-yellow` | trai | 5 | xoăn ngắn | vàng nhạt | pale lemon |
| `c5-girl-long` | gái | 5 | ngang vai, kẹp trắng | vàng nhạt | soft lavender |

Sau khi sinh → làm phẳng → `ComfyUI/input/<name>-flat.png` → dùng làm reference cho STEP 2.

---

## ⚠ 6 lỗi đã gặp thật — đọc trước khi làm

### 1. Da bé bị LÔNG / MỐC — lỗi nặng nhất

Prompt cũ ghi `"visible fine pores on the nose and cheeks, subtle peach fuzz along the jaw"`.
Qwen-Image render thành **vệt lông đen trên má**, trông như râu. Với bé mầm non đây là lỗi
không thể chấp nhận.

**Sai:**
```
Natural skin texture with visible fine pores on the nose and cheeks,
subtle peach fuzz along the jaw, natural uneven tone
```

**Đúng:**
```
SKIN - CRITICAL: this is a young preschool child, so the skin must be perfectly smooth,
plump, soft and luminous like a baby's. Absence of facial hair is mandatory:
NO peach fuzz, NO vellus hair, NO beard shadow, NO stubble, NO dark hair strokes on the
cheeks, NO hair on the upper lip, NO fuzz along the jaw or chin. The cheeks are clean,
round, plump and smooth with a soft natural rosy blush. Poreless, flawlessly clean baby
skin with a gentle natural sheen on the nose and forehead, subtle subsurface scattering
making the skin look translucent and alive. Soft baby fat on the cheeks.
```

Negative bắt buộc thêm:
```
facial hair, peach fuzz, vellus hair, beard shadow, stubble, five o'clock shadow,
hair on cheeks, dark hair strokes on skin, hairy face, mustache, adult skin texture
```

> Nguyên tắc: **chân thật đến từ subsurface scattering + sheen**, KHÔNG đến từ "pores" hay
> "peach fuzz". Hai từ đó phá hỏng da em bé.

### 2. Lip-sync sinh người KHÁC hoàn toàn

Triệu chứng: ảnh bé gái tóc mái → clip ra bé trai áo navy; ảnh bé trai → ra bé tóc vàng.

Nguyên nhân: **thiếu `MiniMaxH3AddGuide`**. Node này neo ảnh ở frame 0 nên mặt không trôi.

5 thứ phải có đủ, thiếu 1 là hỏng:

| # | Phải có | Giá trị |
|---|---|---|
| 1 | `MiniMaxH3AddGuide` | `frame_idx: 0`, nối `image` = ảnh gốc |
| 2 | `ref_image_size` | `"max"` (không phải `"match"`) |
| 3 | Prompt nêu tên ảnh | khối `REFERENCE ORDER AND AUTHORITY` |
| 4 | `SamplerCustomAdvanced` + `BasicGuider` | không dùng `KSampler` |
| 5 | `res_multistep` + `beta` + 20 steps | không dùng `euler`/`simple` |

Prompt chuẩn:
```
REFERENCE ORDER AND AUTHORITY:
<Picture 1> is the user-approved portrait of the child. The face, hair, skin tone and
clothing come from <Picture 1> and must stay identical for the whole shot.
Do not change age, ethnicity, hairstyle or outfit.

SKIN - CRITICAL: ...   (khối da ở mục 1)

SHOT: the same child from <Picture 1> speaks the Mandarin word {word} directly to the
camera. Mouth shapes match the audio exactly, jaw and lips move with each syllable,
eyes blink naturally, tiny head movement, shoulders relaxed.

CAMERA: locked-off frontal shot, no camera move, eye level.
LIGHT: soft frontal key, warm 3500K, even and flattering, no harsh shadows.
STYLE: photorealistic live-action footage of a real preschool child,
clean smooth baby skin, no cartoon, no 3D render, no illustration.
```

### 3. Ảnh có alpha → tóc đỏ, nền đen

`VAEEncode` nhận RGBA thì kênh alpha thành đen. **Luôn làm phẳng RGBA→RGB trên nền kem
(`#FAF6EC`) trước khi nạp vào ComfyUI.**

### 4. Krea2 patch thiếu LoRA → cháy màu, mất chất 3D

`LoraLoaderModelOnly(krea2_identity_edit_v2)` **phải** đứng trước `Krea2EditModelPatch`.
Thiếu `target_latent` → chậm gấp 4 lần.

### 5. Đọc ghi file chữ Hán: KHÔNG dùng `Set-Content`

PowerShell trên máy này ghi sai encoding → chữ Hán thành ô vuông. Dùng `create` tool
hoặc Python `open(..., encoding="utf-8")`.

### 6. Remotion `--props` trên Windows

Không truyền JSON inline. Ghi ra file rồi `--props=out/props-on.json`.

---

## Bước 1 — Ảnh bé người thật

| Parameter | Value |
|---|---|
| Model | `qwen_image_2512_fp8_e4m3fn.safetensors` |
| Text encoder | `qwen_2.5_vl_7b_fp8_scaled.safetensors` (type `qwen_image`) |
| VAE | `qwen_image_vae.safetensors` |
| Steps / CFG | **30 / 4.5** (tăng từ 28/4.0 để nét da tốt hơn) |
| Resolution | 1024×1024 |
| Thời gian | ~66 s/ảnh (offload RAM vì 19 GB > 16 GB VRAM) |

Sau khi sinh: làm phẳng và copy vào `production-local/ComfyUI/input/<name>-flat.png`
để STEP 2 dùng làm reference.

## Bước 2 — Bé nói (lip-sync)

| Parameter | Value |
|---|---|
| Model | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (type `minimax`) |
| Video VAE | `minimax_h3_video_vae_int8_convrot.safetensors` |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` |
| Size | 768×768 |
| Length | **124 frame @ 24 fps = 5.17 s** (min của model) |
| Steps | 20, `res_multistep`, `beta` |
| Thời gian | **~280 s/clip** |

Audio phải **pad đủ ≥5 s** bằng silence trước khi nạp:
```powershell
ffmpeg -i word.wav -af "apad=pad_dur=4.13" -t 6.0 word-pad.wav
```

## Bước 3 — Remotion

```bash
cd "J:\1.JennieHomeSchool\03 Voice\create-video-childrent-flashcard-chinese"
npm install
npx tsc --noEmit
npx remotion render src/index.tsx ChineseFlashcard out/zh-kids-v4.mp4 `
  --props=out/props-on.json --concurrency=6
```

### Layout (đo từ video mẫu)

| Thành phần | Giá trị |
|---|---|
| Khung ảnh | x 0.497–0.959 · y 0.078–0.950 |
| Bo góc | 72 px @1080p |
| Viền | 10 px `rgba(255,255,255,0.92)` |
| Pinyin | tâm y 401 · 84 px · `#4A6274` |
| Hán tự | tâm y 594 · 268 px · `#3B3B3B` |
| Nghĩa Việt | dưới Hán tự · 48 px · `#8A8A8A` |
| Nền | `#FAF6EC` toàn bộ |
| Nhạc nền | −20 dB, fade in 0.6 s / out 1.2 s |
| SFX text pop | −11 dB, frame 0 mỗi thẻ |
| SFX sticker pop | −14 dB, frame 96 mỗi thẻ (beat 3D) |

### Từ vựng

```ts
{
  hanzi: '说话',
  pinyin: ['shuō', 'huà'],
  meaning: 'nói chuyện',   // hiện dưới Hán tự
  bg: BACKGROUND,
  photo: 'c1-girl-bangs.png',   // public/real
  avatar: 'alice-speaking.png', // public/portraits
  clip: 'c1-shuohua.mp4',      // public/lipsync  <- bé nói
  audio: 'shuohua.wav',        // public/audio
}
```

## Nhạc nền — dùng thư viện có sẵn

**Đừng sinh mới trước.** Thư viện đã có 6 bed qua cổng vocal-free:
```
production-local/JennieJoyKids-Story/_library/music-beds/REGISTRY.json
```
Chọn bed có `used_in: []`. Đã dùng cho dự án này: **NHAC-V2-6** (glockenspiel, 119.6 s,
−17.6 LUFS, sha256 `4378428c…e3efa1`).

## SFX

Sinh bằng `stable_audio_3_small_sfx.safetensors` + `t5gemma_b_b_ul2.safetensors`:

| File | Prompt | Thời lượng |
|---|---|---|
| `pop-text.wav` | short bright cartoon pop, clean transient, no reverb tail | 1.30 s |
| `pop-sticker.wav` | short cute sparkle chime, glockenspiel ding + tiny glitter tail | 1.49 s |

---

## Quy tắc bất biến

1. **Da bé phải nỏn nà.** Không bao giờ dùng "pores", "peach fuzz", "skin texture" cho trẻ mầm non.
2. **Lip-sync phải có `MiniMaxH3AddGuide`.** Không có = sinh người khác.
3. **Ảnh tham chiếu phải làm phẳng RGBA→RGB** trên nền kem.
4. **Audio phải pad ≥5 s** trước khi đưa vào MiniMax H3.
5. **Hình học khung nằm trong `src/theme.ts`**, không trong prompt.
6. **Nền là hằng số `BACKGROUND`**, không đổi theo từ.
7. **Độ tuổi cố định 3–5**, ghi rõ "preschool" trong prompt.
8. **Nhạc: thư viện trước, sinh mới sau.**

---

## Chi phí VRAM thực đo (RTX 5080 16 GB)

| Model | Size | Thời gian | Ghi chú |
|---|---|---|---|
| Krea2 Turbo | 12.6 GB | 20 s | vừa VRAM, nhanh nhất |
| Qwen-Image 2512 | 19.0 GB | 66 s | offload RAM |
| Qwen-Image-Edit 2511 | 19.1 + 8.7 GB | 110 s | chậm nhất |
| MiniMax H3 ref2va | 19.5 + 14.6 GB | **280 s** | `ref_image_size=max` chậm 2–3× |
| SeedVR2 7B | 7.8 GB | — | restore độ nét |

RAM 64 GB không phải nút thắt — **VRAM 16 GB** mới là.

## Đo độ nét (Laplacian variance, chuẩn hoá 1024)

| Nguồn | lap_var |
|---|---|
| Alice gốc 1254 | 315 |
| Jensu 1536/30 steps | 160 |
| Jensu 1024/24 steps | 120 |

Sinh ở 1536 rồi hạ xuống 1024 cho kết quả nét nhất.

---

## Lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách sửa |
|---|---|---|
| Má bé có vệt lông đen | prompt "peach fuzz / pores" | khối SKIN-CRITICAL ở mục 1 |
| Lip-sync ra người khác | thiếu `MiniMaxH3AddGuide` | thêm node, `frame_idx=0` |
| Tóc đỏ, nền đen | alpha vào VAE | làm phẳng RGBA→RGB |
| Cháy màu, mất 3D | thiếu identity LoRA | LoRA trước patch |
| Chậm gấp 4 | thiếu `target_latent` | nối latent vào patch |
| Hán tự thành ô vuông | file TS sai encoding | ghi UTF-8 bằng `create` |
| Remotion 404 audio | wav chưa sinh | chạy edge-tts trước |
| Remotion `--props` lỗi | Windows escaping | dùng file JSON |

---

## Cấu trúc project

```
create-video-childrent-flashcard-chinese\
├── out\zh-kids-v4.mp4          <- video bàn giao
├── public\real\                <- 5 ảnh bé thật (STEP 1)
├── public\lipsync\             <- 5 clip bé nói (STEP 2)
├── public\portraits\           <- 17 icon Alice 3D
├── public\audio\               <- 5 wav từ + nhạc nền + sfx/
├── src\theme.ts                <- từ vựng + layout
├── src\Flashcard.tsx           <- 1 thẻ (4s nói + 1s 3D)
├── src\ChineseFlashcard.tsx    <- composition + nhạc + SFX
├── WORKFLOW-BAN-GIAO.md
└── PROMPT-LIBRARY.md
```
