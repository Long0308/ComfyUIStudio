# Thư viện prompt theo thể loại — mục B và G (user, 2026-10-30)

Nguồn: [USER-PROMPT-NOTES-2026-10-30.md](J:/1.JennieHomeSchool/03%20Voice/docs/prompts/USER-PROMPT-NOTES-2026-10-30.md), mục **B** và **G**.
Ghi chú: root đã loại 2 mẫu (sửa người thật thành ảnh gợi dục; ghép hai người thật đang hôn nhau). Không có mẫu nào trong thư viện này.

Liên kết chéo: [tao-anh-prompt-as-code SKILL](../SKILL.md) · nhân vật NEWTECONS: [nhan-vat-ai-newtecons SKILL](../../nhan-vat-ai-newtecons/SKILL.md) · phong cách và sửa ảnh: [gpt-image-2-style-library SKILL](../../gpt-image-2-style-library/SKILL.md).

## B. Cấu trúc prompt tạo ảnh/video (nguồn: mục B của ghi chú)

### B.1 Năm lớp
1. **Chủ thể** (subject).
2. **Ngoại hình – hành động** (appearance, action).
3. **Bối cảnh – không gian – thời gian** (environment, time).
4. **Phong cách** (style).
5. **Kỹ thuật** (máy ảnh, ánh sáng, tỉ lệ).

### B.2 Công thức S + A + E + ST + T
- S = Subject, A = Action/Appearance, E = Environment, ST = Style, T = Technical.
- Dạng: `[S] wearing …, [A] …, in/at [E] …, in [ST] style, [T: resolution, lens, lighting, fps]`.

### B.3 Viết từ 5W1H
- Ai (who), làm gì (what), ở đâu (where), khi nào (when), phong cách gì (style), kỹ thuật thế nào (how).
- Viết 6 câu, mỗi câu một W/H, rồi ghép lại thành prompt.

### B.4 Tư duy quảng cáo: đủ 7 yếu tố
Chủ thể · bối cảnh · phong cách · ánh sáng · chất liệu · cảm xúc · thông điệp.

### B.5 Công thức agency S + M + E + V + ST + L + T
Subject, Message, Environment, Visual elements (đạo cụ, điểm nhấn), Style, Lighting, Technical.

Khuôn điền 7 ô (EN, giữ nguyên dạng):
> Create a high-end commercial visual featuring [S]. Convey the message of [M]. Place the scene in [E], incorporating key visual elements like [V]. Render the composition in [ST] style, with [L] lighting. Ensure hyper-realistic textures, premium materials, and a polished, studio-quality look suitable for modern advertising.

Ba hướng phong cách mẫu ở B.6 của ghi chú nằm trong [gpt-image-2-style-library SKILL](../../gpt-image-2-style-library/SKILL.md), không chép lại ở đây.

## G. Khối biến prompt-as-code (kiểu Nano Banana Pro) (nguồn: mục G của ghi chú)

Khối biến dùng cú pháp `{argument name="…" default="…"}`. Nhóm và tên biến:

- **[Chủ thể]**: `person`, `facial_reference` (EXACT_MATCH), `hair_style`, `hair_action`, `accessories`, `outfit_base`, `outfit_outer`, `legwear`.
- **[Môi trường]**: `location_type`, `time_of_day`, `lighting_style`, `lighting_temp`, `atmosphere`, `main_object`, `interaction`.
- **[Cài đặt máy ảnh]**: `model` (ví dụ Canon EOS R5), `lens` (ví dụ 50mm f/1.2), `aperture`, `iso`, `shutter_speed`, `white_balance` (K), `focus`, `depth_of_field`.
- **[Hậu kỳ]**: `skin_texture`, `aesthetic`, `highlight_behavior`, `visual_effects`.

Ví dụ khai báo một biến:
```
{argument name="lens" default="50mm f/1.2"}
```

**Ghi chú mâu thuẫn (bắt buộc đọc):** mẫu gốc đặt `skin_texture` = "da trắng sứ, mịn màng". Điều này ngược với lời khuyên tránh da mịn/nhựa ở [nhan-vat-ai-newtecons SKILL](../../nhan-vat-ai-newtecons/SKILL.md) (mục C, E của ghi chú) và ở ⑥ phần *Anti-Plastic Skin* của file này. Với nhân vật NEWTECONS live-action, mặc định `skin_texture` là da thật có lỗ chân lông, không dùng giá trị "trắng sứ, mịn màng" của mẫu gốc.
