# BÀN GIAO — Chinese Flashcard Video

**Ngày:** 2026-11-06 · **Trạng thái:** HOÀN THÀNH

---

## 1. Sản phẩm

**Video:** `out/zh-kids-v4.mp4` — 9.72 MB

| Thông số | Giá trị |
|---|---|
| Thời lượng | 29.72 s |
| Độ phân giải | 1920 × 1080 |
| FPS | 30 |
| Video codec | H.264 |
| Audio | AAC stereo — giọng bé + nhạc nền −20 dB + SFX pop |
| Số thẻ | 5 + outro cảm ơn |

### Nội dung 5 thẻ

| # | Hán tự | Pinyin | Nghĩa Việt | Nhân vật | Cảm xúc |
|---|---|---|---|---|---|
| 1 | 说话 | shuō huà | nói chuyện | C1 gái tóc mái | đang nói |
| 2 | 听 | tīng | nghe | C2 trai áo xanh | lắng nghe |
| 3 | 看 | kàn | nhìn | C3 gái hai bím | tò mò nhìn |
| 4 | 笑 | xiào | cười | C4 trai áo vàng | cười lớn |
| 5 | 没关系 | méi guān xì | không sao đâu | C5 gái tóc dài | trấn an |

**Outro:** Alice 3D vẫy tay + `谢谢你！ xiè xiè nǐ! · Cảm ơn con!` + `你真棒！ Con giỏi quá!`

### Cấu trúc 1 thẻ (5 s)

```
0s        1s        2s        3s        4s        5s
|--be NOI (lip-sync MiniMax H3, 4 giay)------------|--avatar 3D--|
     pinyin + Han tu + nghia Viet hien tu frame 0
     SFX pop-text @f0   ·   SFX pop-sticker @f96
```

---

## 2. Kết quả rea-video (xác nhận kỹ thuật)

Phân tích `zh-kids-v4.mp4`:

| Chỉ số | Giá trị |
|---|---|
| Số shot | 11 |
| Thành phần | **71 % AI video + 16 % code render + 13 % 3D render** |
| Nhạc | 145.6 BPM |
| SFX | 6 hiệu ứng, **5 cái rơi đúng nhịp** text/sticker pop |
| Overlay | 5 dòng subtitle, 1 styled text, 7 text label |

So sánh với bản v2 (chưa lip-sync): v2 chỉ **40 % "still image + pan/zoom"**.
v4 đã có chuyển động thật trong **71 %** thời lượng — đạt yêu cầu.

---

## 3. Workflow ComfyUI — 20 file, đặt tên có cấu trúc

**Local:** `production-local/ComfyUI/user/default/workflows/JENNIEJOYKIDS/ChineseFlashcard/`
**Repo:** `_push/ComfyUIStudio/comfyui/workflows/user/JENNIEJOYKIDS/ChineseFlashcard/`

### Mẫu tên

```
FLASHCARD-ZH_{STEP}_{KIND}_{ASSET}_v{N}-{VARIANT}.json
```

Ví dụ: `FLASHCARD-ZH_S2-TALK_C1-girl-bangs_v1-shuohua.json`
= thể loại flashcard Trung · bước 2 · clip đang nói · bé C1 · phiên bản 1 · từ 说话.

### Bảng file

| Bước | Kind | Số file | Model | Group trong editor |
|---|---|---|---|---|
| S1 | `3D` ALICE | 5 | Krea2 Identity Edit | `STEP 1 - CHARACTER` |
| S1 | `3D` JENSU | 5 | Krea2 Identity Edit | `STEP 1 - CHARACTER` |
| S1 | `REAL` C1–C5 | 5 | Qwen-Image 2512 | `STEP 1 - CHARACTER` |
| S2 | `TALK` C1–C5 | 5 | MiniMax H3 ref2va | `STEP 2a/2b/2c` |

Chi tiết đầy đủ: `_NAMING.md` trong thư mục workflow.

### Lưu trữ

`_archive-superseded/` — 5 file `TALK_0N_*.json` bản đầu **thiếu `MiniMaxH3AddGuide`**
→ sinh sai nhân vật hoàn toàn. Giữ lại để đối chiếu, không dùng.

---

## 4. Tài sản

### Ảnh bé thật — `public/real/` (Qwen-Image 2512, 30 steps / cfg 4.5)

| File | Nhân vật | Thời gian sinh |
|---|---|---|
| `c1-girl-bangs.png` | gái 4t, mái ngang, áo mint | ~66 s |
| `c2-boy-blue.png` | trai 5t, tóc rẽ, áo xanh | ~66 s |
| `c3-girl-pigtail.png` | gái 4t, hai bím, áo hồng | ~66 s |
| `c4-boy-yellow.png` | trai 5t, tóc xoăn, áo vàng | ~66 s |
| `c5-girl-long.png` | gái 5t, tóc dài, kẹp trắng | ~66 s |

### Clip lip-sync — `public/lipsync/` (MiniMax H3, ~280 s/clip)

`c1-shuohua.mp4` · `c2-ting.mp4` · `c3-kan.mp4` · `c4-xiao.mp4` · `c5-guanxi.mp4`
Mỗi clip 768×768, 124 frame @ 24 fps = 5.17 s, có audio.

### Avatar 3D — `public/portraits/`

17 icon Alice (5 tư thế mới + 12 gốc) + `jensu-*.png`

### Audio — `public/audio/`

| File | Nội dung | Thời lượng |
|---|---|---|
| `shuohua.wav` … `meiguanxi.wav` | 5 từ tiếng Trung (edge-tts XiaoyiNeural) | 1.87 s mỗi file |
| `music-bed.wav` | NHAC-V2-6 glockenspiel | 119.65 s |
| `sfx/pop-text.wav` | pop chữ | 1.30 s |
| `sfx/pop-sticker.wav` | chime sticker | 1.49 s |

Nhạc: sha256 `4378428cf2938e7e01fa1d51236a210737d66aefe23c9967f8ccc007b3e3efa1`
khớp registry `JennieJoyKids-Story/_library/music-beds/REGISTRY.json`.

---

## 5. Cách chạy lại

```powershell
cd "J:\1.JennieHomeSchool\03 Voice\create-video-childrent-flashcard-chinese"

npm install
npx tsc --noEmit

# xem truoc
npm run studio                    # http://localhost:3038

# render
npx remotion render src/index.tsx ChineseFlashcard out/zh-kids-v4.mp4 `
  --props=out/props-on.json --concurrency=6
```

Render mất ~3 phút với 6 luồng.

---

## 6. Skill

`03 Voice/.agents/skills/create-video-childrent-flashcard-chinese/SKILL.md`
(15.5 KB, đồng bộ với `_push/ComfyUIStudio/skills/create-video-childrent-flashcard-chinese/`)

Nội dung:

- Hợp đồng đầu ra, cấu trúc 5 beat
- **Hai pipeline nhân vật**: A = 3D Krea2 Identity Edit, B = bé thật Qwen-Image
- **6 lỗi đã gặp thật** + cách sửa:
  1. Da bé có lông (prompt "peach fuzz" → cấm tuyệt đối)
  2. Lip-sync sinh người khác (thiếu `MiniMaxH3AddGuide`)
  3. Alpha vào VAE → tóc đỏ nền đen
  4. Krea2 patch thiếu LoRA → cháy màu
  5. Ghi file chữ Hán bằng `Set-Content` → ô vuông
  6. Remotion `--props` inline JSON trên Windows
- Bảng chi phí VRAM thực đo
- Ngưỡng độ nét (Laplacian variance)
- Quy ước đặt tên workflow

---

## 7. Cập nhật skill trong engine — TRẠNG THÁI

### Đã làm

- `create-video-childrent-flashcard-chinese/SKILL.md` — viết mới, đề cập `studio-video-engine`
  như engine cha, ghi rõ 3 stage tương ứng `jjv` (`plan` / `images` / `h3` / `audio` / `edit`)
- Workflow đặt tên theo cấu trúc, có `_NAMING.md` mô tả quy ước
- Đồng bộ sang repo `ComfyUIStudio`

### CHƯA làm — cần bạn duyệt

| Việc | Cần sửa | Rủi ro |
|---|---|---|
| Thêm domain `flashcard_zh` | `domains/flashcard_zh.json` | Thấp — file mới |
| Thêm recipe 3 stage | `recipes/flashcard/*.json` | Thấp — file mới |
| Thêm verb `jjv flashcard run` | `bin/jjv.py` | **Trung bình** — sửa CLI đang chạy |
| Đăng ký skill vào `sync_skills.py` | 1 dòng | Thấp |
| `/cognee-hindsight-mesh` | gọi skill | Chưa chạy lần nào |
| Syn harness recall | gọi skill | Chưa chạy lần nào |

**Đề xuất:** làm 3 việc rủi ro thấp trước (domain + recipe + sync_skills), rồi mới
đụng `jjv.py`. Cần bạn xác nhận trước khi sửa engine.

---

## 8. Vị trí file

```
03 Voice\create-video-childrent-flashcard-chinese\
├── out\zh-kids-v4.mp4              <- VIDEO BAN GIAO
├── out\qa5\                        <- frame QA
├── public\real\                    <- 5 anh be that
├── public\lipsync\                 <- 5 clip be noi
├── public\portraits\               <- avatar 3D
├── public\audio\                   <- tu + nhac + sfx
├── src\theme.ts                    <- tu vung + layout
├── src\Flashcard.tsx               <- 1 the (4s noi + 1s 3D)
├── src\ChineseFlashcard.tsx        <- composition + nhac + SFX + outro
├── WORKFLOW-BAN-GIAO.md            <- file nay
└── PROMPT-LIBRARY.md               <- thu vien prompt

03 Voice\production-local\ComfyUI\user\default\workflows\JENNIEJOYKIDS\ChineseFlashcard\
├── FLASHCARD-ZH_S1-3D_ALICE_v1-*.json      (5)
├── FLASHCARD-ZH_S1-3D_JENSU_v1-*.json      (5)
├── FLASHCARD-ZH_S1-REAL_C*_v1-*.json       (5)
├── FLASHCARD-ZH_S2-TALK_C*_v1-*.json       (5)
├── _NAMING.md
└── _archive-superseded\                    (5, khong dung)

03 Voice\.agents\skills\create-video-childrent-flashcard-chinese\SKILL.md
```
