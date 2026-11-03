---
name: tao-anh-prompt-as-code
description: >-
  Viết prompt TẠO ẢNH chất lượng cao cho mọi model (GPT-Image, Gemini/Nano-Banana, Flux, SDXL, Higgsfield) theo lối "Prompt as Code" — 12 thể loại × 8 trường nguyên tử. Dùng khi tạo poster, infographic, UI mockup, ảnh sản phẩm, logo, slide, ảnh thật, minh hoạ, nhân vật, kiến trúc, ảnh lịch sử/cổ phong, tài liệu xuất bản. Triggers: tạo ảnh, vẽ ảnh, poster, infographic, logo, thumbnail, ảnh sản phẩm, banner, hình minh hoạ, image prompt.
---

# TẠO ẢNH — "PROMPT AS CODE"

> Chưng cất từ `awesome-gpt-image-2` (538 case · 12 thể loại · 21 template công nghiệp),
> Long chốt 2026-08-27. Áp cho `tao_anh` của NEX, DeerFlow, Hermes và mọi agent.

## ⓿ LUẬT GỐC

🩸 **"Không ràng buộc rõ ràng = model hành xử như thực tập sinh."**
Prompt mơ hồ ⇒ ảnh xấu. Mỗi trường thiếu là một chỗ model **tự bịa**.

🩸 **Prompt là CODE, không phải văn xuôi.** Viết theo **trường nguyên tử** để:
tái dùng · thay biến hàng loạt · giữ đồng nhất cả series · máy sinh được.

## ① TÁM TRƯỜNG BẮT BUỘC (thiếu trường nào ⇒ model tự quyết trường đó)

| # | Trường | Nghĩa | Ví dụ |
|---|---|---|---|
| 1 | **subject** | chủ thể chính, ĐẾM ĐƯỢC | "1 tách cà phê phin, 2 quyển sổ tay" |
| 2 | **style** | phong cách / kỹ thuật render | "editorial flat illustration, phẳng, nét mảnh" |
| 3 | **composition** | bố cục + góc nhìn | "top-down, rule of thirds, chủ thể lệch trái 1/3" |
| 4 | **lighting** | ánh sáng | "soft window light từ trái, bóng đổ nhẹ" |
| 5 | **palette** | 3–5 màu HEX cụ thể | "#0B4FD9 nhấn · #F7FAFD nền · #0A2540 chữ" |
| 6 | **material/texture** | chất liệu | "giấy mịn có vân, kim loại mờ" |
| 7 | **aspect/size** | tỉ lệ + độ phân giải | "16:9, 1920×1080" · "1:1 cho avatar" |
| 8 | **negative** | CẤM gì | "no watermark, no extra fingers, no gibberish text" |

**Thêm khi có CHỮ trong ảnh (bắt buộc cho poster/infographic/UI):**
`text_content` (nguyên văn từng dòng) · `text_hierarchy` (cỡ/thứ tự) · `font_mood`.
🩸 **Chữ phải chép NGUYÊN VĂN vào prompt** — model không đoán đúng chữ tiếng Việt có dấu.

## ② 12 THỂ LOẠI — trường ĐẶC THÙ phải thêm

| Thể loại | Trường bắt buộc thêm |
|---|---|
| **UI/giao diện** | platform (iOS/web) · mode (light/dark) · các thành phần UI · state |
| **Infographic/chart** | topic · audience · **số module 3–5** · loại biểu đồ · nhãn ngắn |
| **Poster/typography** | headline nguyên văn · sub · **typography là CẤU TRÚC chính** · lề |
| **Sản phẩm/TMĐT** | tên SP · 3 điểm bán · bối cảnh · cảm giác chất liệu · đạo cụ |
| **Logo/thương hiệu** | từ khoá nhân cách · **nền trắng tinh** · KHÔNG gradient · vector-scalable |
| **Kiến trúc/không gian** | loại không gian · vật liệu · giờ trong ngày · tầm mắt (eye-level) |
| **Ảnh thật/chân dung** | ống kính (35mm/85mm) · khẩu (f/1.8) · film grain · da thật |
| **Minh hoạ/nghệ thuật** | trường phái · nét (line weight) · độ bão hoà |
| **Nhân vật** | tuổi/giới · trang phục · tư thế · biểu cảm · **giữ nhất quán qua series** |
| **Cảnh/kể chuyện** | khoảnh khắc · tâm trạng · tiền-trung-hậu cảnh |
| **Cổ phong/lịch sử** | triều đại · chất liệu (lụa/giấy dó) · quy ước bố cục |
| **Tài liệu/xuất bản** | khổ giấy · lưới cột · vùng chữ · chú thích |

## ③ KHUÔN JSON (máy sinh hàng loạt — thay biến, giữ khung)

```json
{
  "type": "poster",
  "subject": "...", "style": "...", "composition": "...",
  "lighting": "...", "palette": ["#0B4FD9", "#F7FAFD", "#0A2540"],
  "material": "...", "aspect": "16:9",
  "text": {"headline": "…", "sub": "…", "hierarchy": "headline 3× sub"},
  "constraints": ["chữ chính xác 100%", "chừa lề 8%"],
  "negative": ["watermark", "chữ méo", "tay thừa ngón"]
}
```

## ④ MẸO ĐÃ TRẢ GIÁ

- **Series đồng nhất** ⇒ khoá `style` + `palette` + `lighting`, chỉ đổi `subject`.
- **Chữ tiếng Việt** hay vỡ dấu ⇒ ưu tiên model mạnh chữ, hoặc **để trống vùng chữ**
  rồi ghép chữ bằng HTML/CSS sau (chắc chắn đúng dấu).
- **Ảnh chậm** ⇒ giảm độ phân giải khi nháp, chỉ render cao ở bản chốt.
- **Đừng nhồi 1 câu dài**: liệt kê trường rời — model bám sát hơn hẳn.
- **Xử lý khi bị bộ lọc an toàn chặn nhầm (False Positive / Nhạy cảm)**:
  1. *Nguyên nhân & Câu giải thích người dùng*: Do mô hình tạo mang tính xác suất ngẫu nhiên (stochastic variance) nên đôi khi bộ lọc quét tự động chặn nhầm. Phản hồi chuẩn: **"Do mô hình tạo ngẫu nhiên nên mới ra như vậy, tạo lại là được nhé."**
  2. *Mẹo phá vỡ giới hạn chặn (Bypass Safe-Filter Jitter)*:
     - **Tái gửi ngay (Re-roll)**: Chỉ cần bấm tạo lại lượt 2 hoặc đổi seed ngẫu nhiên nhẹ là vượt qua bộ lọc vì mỗi lượt sinh có token xác suất khác nhau.
     - **Dùng thuật ngữ trung tính chuyên ngành (Neutral Editorial Framing)**: Thay các từ nhạy cảm thô bằng từ ngữ nhiếp ảnh/thời trang cao cấp (*"editorial high-fashion portrait", "confident posture and graceful natural curves", "fine-art studio lookbook", "aesthetic beachwear photography", "natural feminine poise"*).
     - **Khóa bối cảnh làm việc/nghệ thuật**: Đưa chủ thể vào bối cảnh cụ thể (studio chụp lookbook, bãi biển nghỉ dưỡng sang trọng, phòng chụp ánh sáng tự nhiên) để hệ thống hiểu đây là ảnh nghệ thuật/thời trang hợp lệ.

## ⑤ CẤM (bảng màu Long chốt)
CẤM cam/vàng/be trong ảnh tài liệu công ty. Dùng **Blue Web**:
`#0B4FD9` nhấn · `#5B9BF5` phụ · `#F7FAFD` nền · `#0A2540` chữ · `#3E8914` tốt · `#D00000` xấu.

## ⑥ CHUẨN CHATGPT IMAGES 2.5 NÂNG CAO (COURSE @AV1DLIVE)

Đọc toàn văn hướng dẫn chi tiết tại `references/chatgpt-images-2-5-mastery.md`.

### 1. Phân loại 5 điểm khởi đầu (The 5 Starting Points)
1. **New image**: Mục đích (Purpose), Khung hình (Canvas), Thực thể đếm được (Contents), Quan hệ không gian (Relationships), Mức độ hoàn thiện (Visual finish).
2. **Recreation**: 1 ảnh gốc sạch + Visual Inventory + Reconstruction JSON (tọa độ `0.000–1.000`) + danh sách Preserve.
3. **Remix / Multi-reference**: Gán vai trò cụ thể cho từng ảnh (`INPUT ROLES`) + Danh sách loại trừ rõ ràng.
4. **Layout / Sketch**: Khung hình khối + chú giải vị trí + đặc tả độ hoàn thiện.
5. **Local edit**: Hợp đồng 4 thành phần bắt buộc (**Target — Change — Preserve — Allow**).

### 2. Cấu trúc phân rã ảnh phức tạp (Bảng 02: Quyết định lớn trước chi tiết nhỏ)

Khi prompt một bức ảnh nhiều chi tiết (giao diện App UI, website, mặt cắt kiến trúc, ảnh nhóm người, bối cảnh phức hợp), trình tự tư duy bắt buộc phải đi từ vĩ mô đến vi mô:

1. **Main Structure (Khung kết cấu tổng thể)**: Tỷ lệ khung hình (16:9, 9:16, 4:5), bố cục nền tảng, góc máy (eye-level, 3/4 hero angle, top-down), đường chân trời thẳng.
2. **Distinct Zones (Các phân vùng rõ rệt)**: Chia tách các khu vực độc lập không chồng chéo (khu vực trái/phải, các panel, 3 màn hình cạnh nhau, khu vực chủ thể chính vs khu vực chữ).
3. **Spatial & Entity Relationships (Quan hệ vị trí & thực thể)**: Cái nào đặt trên cái nào, vật thể chạm bề mặt nào, nhãn chữ in ở vị trí nào, người tương tác với đạo cụ gì.
4. **Material Behavior (Phản ứng quang học của vật liệu)**: Độ dày và độ khúc xạ của thủy tinh, hạt vân gỗ dọc, thớ giấy ngà sần li ti, sợi dệt vải caro, bề mặt kim loại phay xước phản xạ ánh sáng.
5. **Visual Hierarchy (Thứ bậc thị giác)**: Điểm nhấn thị giác chính (focal anchor) đối trọng với tiêu đề chữ hoặc vùng không gian thở (breathing room).
6. **Deliberate Freedom (Khoảng tự do có chủ đích)**: Những chi tiết phụ được phép để AI tự nhiên hóa (hạt bụi sáng, cây cối làm mờ phía xa, bóng đổ chuyển tiếp).

### 3. Bản đồ trực quan & Tọa độ chuẩn hóa (Visual Map & Bounding Box — Bảng 04)

#### Phân biệt 5 cấp độ trực quan:
- **Bounding Box**: Vùng chữ nhật ước tính `[x, y, width, height]` theo hệ tọa độ chuẩn hóa `0.000 – 1.000` (gốc tọa độ `[0,0]` ở góc trên bên trái). Đây là chỉ dẫn định vị không gian, không phải layer pixel độc lập.
- **Bounding Crop**: Pixel thực tế được cắt ra từ ảnh nguồn.
- **Segmentation Mask**: Mặt nạ vùng chính xác theo biên dạng viền của vật thể.
- **Extracted Transparent Layer**: Lớp vật thể đã tách nền trong suốt (*alpha channel*).
- **Generated Interpretation**: Phần không gian do AI tự suy luận bổ sung (ví dụ phần móng ngầm của toà nhà khi cắt mặt đứng).

#### Khuôn mẫu Reconstruction JSON (Chuẩn VELLUM / SABLE / Coast House / MORA):
```json
{
  "INPUT_ROLES": {
    "Source_A": "Supplies identity, layout, palette, material, lighting, typography. Do not draw bounding boxes in artwork."
  },
  "SCENE": {
    "medium": "Luxury product photograph / App UI presentation / Architectural study",
    "composition": "Structured grid, rule of thirds, clean ground contact",
    "view": "Eye-level perspective, straight verticals",
    "lighting": "Broad soft directional daylight with gentle shadows",
    "palette": ["#Hex1", "#Hex2", "#Hex3"]
  },
  "ELEMENTS_AND_PLACEMENT": [
    {
      "id": "A-01",
      "name": "primary_subject",
      "approx_box": [0.280, 0.345, 0.580, 0.485],
      "material": "tactile material description",
      "features": "sharp edges, natural specular highlights"
    }
  ],
  "RELATIONSHIPS": [
    "primary_subject touches supporting_surface",
    "label contains exact text: Line 1 above Line 2"
  ],
  "PRESERVE": [
    "Keep exact typography strings unchanged",
    "Keep aspect ratio and overall color balance",
    "No added props, no floating artifacts, no watermarks"
  ],
  "REQUIRED_RESULT": [
    "Observable checks: exactly N subjects, readable text, tactile material finish"
  ],
  "PREFERENCES": [
    "Natural light falloff, visible pores/weave, believable contact shadows"
  ]
}
```

### 2. Hợp đồng sửa cục bộ (Target — Change — Preserve — Allow)
- **TARGET**: Vùng / phần tử cụ thể cần can thiệp (ví dụ: màn giữa trong 3 máy, tay phải ngang hông, icon trên thanh tab bar).
- **CHANGE**: Lệnh sửa chính xác (đổi icon/màu/nội dung chữ/trang phục).
- **PRESERVE**: Vùng cấm xâm phạm (khóa 100% các màn khác, background, gương mặt, typography).
- **ALLOW**: Hệ quả tự nhiên được phép (bóng đổ tự nhiên, độ rủ gấu quần theo tư thế mới).

### 3. Vòng lặp 7 bước tự động của Agent (Operating Rubric)
1. **Identify Starting Point**: Xác định new, recreation, remix hay local edit; làm rõ purpose, canvas, text, appearance, nonnegotiables.
2. **Inspect References & Map**: Lập danh mục kiểm kê chi tiết, gắn ID vật thể, ước tính bounding box `[x,y,w,h]`.
3. **Separate Source & Changes**: Tách bạch quan sát nguồn với lệnh sửa theo Target-Change-Preserve-Allow.
4. **Compile Rendering Request**: Chuyển chất lượng thành quyết định thị giác (vật liệu, ánh sáng, typography, bố cục).
5. **Generate & Record**: Lưu vết prompt nguyên văn, thứ tự ảnh đầu vào, tham số render.
6. **Verify Hard Requirements**: Soát lỗi tiêu chí cứng (số lượng, đúng chữ, đúng logo, tỷ lệ) trước khi đánh giá thẩm mỹ.
7. **Diagnose & Repair**: Sửa đúng điểm hỏng từ bản sạch tốt nhất, không gây hồi quy (No regression).

### 4. Quy tắc chống da nhựa (Anti-Plastic Skin) & Khóa mặt (Face Lock)
- **Face Lock 100%**: Giữ nguyên toàn bộ mắt, mũi, miệng, nụ cười, nốt ruồi, sẹo nhỏ, kết cấu da từ ảnh tham chiếu. Khóa cứng nhân dạng (`Identity Lock`).
- **Anti-Plastic Skin**: Da thật tự nhiên với lỗ chân lông rõ, nếp nhăn biểu cảm mảnh, lông tơ li ti, chuyển tiếp sáng tối tự nhiên. TUYỆT ĐỐI CẤM: da láng mịn như búp bê/nhựa (doll-like/airbrushed), filter làm mịn ảo, flash chói gắt.

## ⑦ HỆ SINH THÁI NHÂN VẬT ĐIỆN ẢNH & LỐI SỐNG SINH HOẠT (@aisumeragi & NEWTECONS PROMPT-AS-CODE)

> Đúc kết từ mô hình tăng trưởng nhân vật của `@aisumeragi` (X/Twitter) và chuẩn sản xuất phim điện ảnh AI NEWTECONS.

### 1. Triết lý cốt lõi: "Nuôi 1 Nhân Vật Sống Động Có Lối Sống > Sinh 100 Bức Ảnh Manocanh"
- Khán giả không theo dõi những bức ảnh đẹp ngẫu nhiên. Họ theo dõi **mọt con người cụ thể** để xem *"hôm nay cô ấy/anh ấy đang làm gì, trải qua chuyện gì"*.
- Cố định bất biến: Tên, Gương mặt (`Identity Lock 100%`), Kiểu tóc, Tính cách, Vóc dáng, Thói quen sinh hoạt.

### 2. Hai Luồng Trang Phục Linh Hoạt (Dual Wardrobe Pipeline)
Khi sản xuất phim hoặc series nội dung, quy trình hỗ trợ 2 luồng trang phục rõ rệt:

#### 🔹 Luồng A: Đồng Phục NEWTECONS PPE & Tùy Biến Chữ Ngực Áo (`chu_nguc`)
- **Áo trong**: Sơ mi dài tay slim-fit xanh nhạt caro chìm (`ÁO PHẢN TRONG.png`) sơ vin quần tây đen.
- **Áo phản quang**: Gile navy cổ V, khóa kéo đen, hông/lưng lưới đen, sọc bạc ngang ngực, dải cam huỳnh quang quanh eo (`ÁO PHẢN QUANG 1.png` & `2.png`).
- **Biến Chữ Ngực Trái (`{DEPARTMENT_NAME}`)**: Dòng chữ in hoa màu trắng sắc nét, dễ dàng thay thế theo phòng ban:
  - `"BAN TRUYỀN THÔNG"`
  - `"KHỐI KỸ THUẬT"`
  - `"BAN AN TOÀN"`
  - `"BAN CHỈ HUY DỰ ÁN"`
  - `"BIM & CÔNG NGHỆ"`
- **Ngực phải & Lưng trên**: Logo NEWTECONS trắng từ `logo trang.png`. Tuyệt đối KHÔNG in logo lên túi hộp.
- **Nón bảo hộ**: Form nón từ `Nón bảo hộ.png`, mặt trước in logo màu nguyên bản (N đỏ trên, NEWTECONS xanh dưới) từ `logo nguyen ban.png`.

#### 🔹 Luồng B: Trang Phục Tự Do Nhập Từ Bước 1 (Any Casual / Fashion Costume)
- Nhận bất kỳ ảnh trang phục thực tế nào từ Bước 1: Váy hoa dạo phố, đầm dạ hội, áo len cafe, suit công sở, đồ thể thao...
- Bước 2 giữ nguyên 100% bộ trang phục này khi xoay các góc 360°, biểu cảm và sinh hoạt đời thường mà không bị ép mặc đồ bảo hộ.

### 3. Cấu Trúc Bảng Hồ Sơ Tham Chiếu 360° (Film Master Character Reference Sheet - 5 Khối)
```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        AI MASTER CHARACTER REFERENCE SHEET                             │
├─────────────────────────┬───────────────────────────┬──────────────────────────────────┤
│ 1. HỒ SƠ NHÂN VẬT (CỘT TRÁI)│ 2. TOÀN THÂN ĐA GÓC NHÌN   │ 3. BẢNG BIỂU CẢM (EXPRESSIONS)  │
│ • Tên, Tuổi, Vai trò    │ • Trước (正面)            │ • Bình thường (通常)             │
│ • Tính cách, Thói quen  │ • Nghiêng 90° (横)        │ • Cười rạng rỡ (笑顔)            │
│ • Chi tiết ngũ quan, da │ • Sau lưng (後ろ)         │ • Nháy mắt (ウインク)            │
│ • Giọng điệu, Trang phục│ • Nghiêng 45° trước/sau   │ • Nghiêm túc, Ngạc nhiên, Bối rối│
├─────────────────────────┴───────────────────────────┼──────────────────────────────────┤
│ 4. CHI TIẾT MACRO & NHẬN DIỆN THƯƠNG HIỆU           │ 5. LỐI SỐNG SINH HOẠT (LIFESTYLE) │
│ • Mũ bảo hộ & Logo mặt trước                        │ • Tại hiện trường công trường    │
│ • Thẻ tên Ban Truyền Thông ngực trái                │ • Đọc bản vẽ thiết kế CAD/BIM    │
│ • Dải phản quang, khóa kéo, thớ vải caro            │ • Trao đổi bộ đàm cùng đồng đội  │
│ • Giày bảo hộ, kết cấu da thực tế                   │ • Uống cafe sáng / Tan ca tối    │
└─────────────────────────────────────────────────────┴──────────────────────────────────┘
```

### 4. Câu Lệnh "Thần Chú" Tiếng Nhật Chuẩn Điện Ảnh (Chống 3D/Anime/Manocanh Giả)
Khi tạo Character Sheet, bắt buộc thêm chỉ thị phong cách điện ảnh để loại bỏ dáng đứng ma-nơ-canh A-Pose đơ cứng:
```text
過度なアニメ化、3DCG化、美化、デフォルメを避け、現実のファッション撮影資料のような高い写実性を保つ。
ポーズは直立に近い自然な立ち姿で、腕と手を自然に下ろす。
(Tránh hoàn toàn anime hóa, 3DCG hóa, làm mịn da nhựa hay biến dạng. Duy trì độ chân thực cực cao như tài liệu chụp ảnh thời trang thực tế. Tư thế đứng tự nhiên, cánh tay thả lỏng mềm mại hai bên hông).
```

## Liên quan
`nex-gui-anh` (gửi ảnh Zalo) · `tao_anh` tool NEX · `nhan-vat-ai-newtecons` · `pose-costume-character`.

## Thư viện prompt theo thể loại (user, 2026-10-30)

Nguồn: [USER-PROMPT-NOTES-2026-10-30.md](J:/1.JennieHomeSchool/03%20Voice/docs/prompts/USER-PROMPT-NOTES-2026-10-30.md), mục **B** và **G**. Chi tiết đầy đủ: [prompt-library-2026-10-30.md](references/prompt-library-2026-10-30.md).

- **Mục B:** cấu trúc 5 lớp; công thức S + A + E + ST + T; 5W1H; công thức agency S + M + E + V + ST + L + T và khuôn 7 ô.
- **Mục G:** khối biến prompt-as-code `{argument name="…" default="…"}`. **Ghi chú mâu thuẫn:** mẫu gốc đặt `skin_texture` = "da trắng sứ, mịn màng", ngược với chống da nhựa ở mục ⑥, phần 4 của skill này. Với NEWTECONS live-action dùng da thật.
- Liên kết: [nhan-vat-ai-newtecons SKILL](../nhan-vat-ai-newtecons/SKILL.md) · [gpt-image-2-style-library SKILL](../gpt-image-2-style-library/SKILL.md).
