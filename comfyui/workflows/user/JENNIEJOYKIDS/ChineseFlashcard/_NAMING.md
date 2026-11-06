# FLASHCARD-ZH — quy ước đặt tên workflow

Mọi workflow trong thư mục này theo một mẫu tên duy nhất để biết ngay
**loại video nào · bước nào · nhân vật nào · phiên bản nào**.

## Mẫu

```
FLASHCARD-ZH_{STEP}_{KIND}_{ASSET}_v{N}-{VARIANT}.json
```

| Phần | Giá trị | Nghĩa |
|---|---|---|
| `FLASHCARD-ZH` | cố định | thể loại video: thẻ từ vựng tiếng Trung |
| `S1` | bước 1 | sinh ảnh nhân vật |
| `S2` | bước 2 | lip-sync (ảnh + audio → video) |
| `S3` | bước 3 | ghép thẻ (Remotion, ngoài ComfyUI) |
| `3D` | loại tài sản | avatar cartoon (Alice / Jensu) |
| `REAL` | loại tài sản | bé người thật |
| `TALK` | loại tài sản | clip bé đang nói |
| `ALICE` / `JENSU` / `C1…C5` | nhân vật | xem bảng dưới |
| `v1` | phiên bản | tăng khi prompt/model đổi |
| `speaking` … `guanxi` | biến thể | tư thế hoặc từ vựng |

## Bảng đầy đủ hiện có

### Bước 1 — nhân vật 3D (Krea2 Identity Edit)

```
FLASHCARD-ZH_S1-3D_ALICE_v1-speaking.json
FLASHCARD-ZH_S1-3D_ALICE_v1-listening.json
FLASHCARD-ZH_S1-3D_ALICE_v1-looking.json
FLASHCARD-ZH_S1-3D_ALICE_v1-laughing.json
FLASHCARD-ZH_S1-3D_ALICE_v1-okay.json

FLASHCARD-ZH_S1-3D_JENSU_v1-speaking.json
FLASHCARD-ZH_S1-3D_JENSU_v1-listening.json
FLASHCARD-ZH_S1-3D_JENSU_v1-looking.json
FLASHCARD-ZH_S1-3D_JENSU_v1-laughing.json
FLASHCARD-ZH_S1-3D_JENSU_v1-okay.json
```

### Bước 1 — bé người thật (Qwen-Image 2512)

```
FLASHCARD-ZH_S1-REAL_C1-girl-bangs_v1-speaking.json
FLASHCARD-ZH_S1-REAL_C2-boy-blue_v1-listening.json
FLASHCARD-ZH_S1-REAL_C3-girl-pigtail_v1-looking.json
FLASHCARD-ZH_S1-REAL_C4-boy-yellow_v1-laughing.json
FLASHCARD-ZH_S1-REAL_C5-girl-long_v1-okay.json
```

### Bước 2 — lip-sync (MiniMax H3 ref2va + AddGuide)

```
FLASHCARD-ZH_S2-TALK_C1-girl-bangs_v1-shuohua.json      → 说话
FLASHCARD-ZH_S2-TALK_C2-boy-blue_v1-ting.json           → 听
FLASHCARD-ZH_S2-TALK_C3-girl-pigtail_v1-kan.json        → 看
FLASHCARD-ZH_S2-TALK_C4-boy-yellow_v1-xiao.json         → 笑
FLASHCARD-ZH_S2-TALK_C5-girl-long_v1-guanxi.json        → 没关系
```

### Lưu trữ

`_archive-superseded/` — workflow cũ đã bị thay thế.
Chứa `TALK_0N_*.json` (bản đầu thiếu `MiniMaxH3AddGuide` → sinh sai nhân vật).
**Không dùng lại.**

---

## Danh sách nhân vật

| Mã | Giới | Tuổi | Tóc | Áo | Nền | Dùng cho |
|---|---|---|---|---|---|---|
| `ALICE` | gái 3D | ~2 | bob đen + mái ngang + nơ hồng | pyjama hồng, tim trắng | kem | avatar đóng thẻ |
| `JENSU` | trai 3D | ~4 | đen, mái rẽ mềm | áo xanh dương | kem | avatar đóng thẻ |
| `C1-girl-bangs` | gái thật | 4 | mái ngang, ngang cằm | mint | pale peach | 说话 shuō huà |
| `C2-boy-blue` | trai thật | 5 | rẽ ngôi mềm | xanh dương | sky blue | 听 tīng |
| `C3-girl-pigtail` | gái thật | 4 | hai bím buộc hồng | hồng | warm apricot | 看 kàn |
| `C4-boy-yellow` | trai thật | 5 | xoăn ngắn | vàng nhạt | pale lemon | 笑 xiào |
| `C5-girl-long` | gái thật | 4 | ngang vai, kẹp trắng | vàng nhạt | soft lavender | 没关系 méi guān xì |

---

## Luồng chạy

```
S1-REAL  (text → ảnh bé thật)
   │  làm phẳng RGBA→RGB trên #FAF6EC
   │  → ComfyUI/input/<name>-flat.png
   ▼
S2-TALK  (ảnh + audio đã pad ≥5s → clip bé nói)
   │  → public/lipsync/<name>.mp4
   ▼
S1-3D    (ảnh canonical → avatar cùng tư thế)
   │  → public/portraits/<name>.png
   ▼
S3       (Remotion ghép thẻ + nhạc + SFX)
   → out/zh-kids-v4.mp4
```

## Quy tắc đặt tên khi thêm mới

1. **Không bao giờ** dùng tên không có tiền tố `FLASHCARD-ZH_`.
2. Bước mới → thêm `S3`, `S4`… tương ứng.
3. Đổi prompt/model → tăng `v1` → `v2`, **giữ file cũ** trong `_archive-superseded/`.
4. Nhân vật mới → thêm dòng vào bảng trên.
5. Mỗi file có **group** trong editor, ghi rõ `STEP N - …`.

## Kết quả rea-video (xác nhận cấu trúc đúng)

Phân tích `zh-kids-v4.mp4`:

| Chỉ số | Giá trị |
|---|---|
| Số shot | 11 (5 thẻ × 2 + outro) |
| Thành phần | **71% AI video + 16% code render + 13% 3D render** |
| Nhạc | 145.6 BPM |
| SFX | 6 hiệu ứng, 5 cái rơi đúng nhịp text/sticker pop |
| Overlay | 5 dòng subtitle, 1 styled text, 7 text label |

So với v2 (chưa lip-sync): v2 chỉ có **40% "still image + pan/zoom"** → v4 đã có
chuyển động thật trong 71% thời lượng.
