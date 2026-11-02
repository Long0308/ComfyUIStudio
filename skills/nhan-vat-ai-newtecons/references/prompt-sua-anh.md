# Bộ prompt SỬA ẢNH — đổi trang phục / phụ kiện trên ảnh đã có

Anh Long dạy 16/09/2026. Sáu prompt dưới đây chuẩn hoá từ sáu mẫu thô của anh.

## Quy ước chung — đọc trước khi dùng bất kỳ prompt nào

- **ẢNH GỐC** = ảnh nhân vật đã khoá mặt do người dùng gửi kèm. Đây là thứ DUY NHẤT giữ
  mặt, dáng, biểu cảm, tư thế, phông nền, tỉ lệ cơ thể.
- **ẢNH THAM CHIẾU** = ảnh sản phẩm (áo, quần, váy, giày, túi, kính) người dùng gửi kèm.
- 🩸 Prompt chỉ được nhắc đúng những tấm **thật sự đính kèm** — nhắc tên một tấm không gửi
  là model bịa (đã trả giá với `logo nguyen ban.png` / `logo trang.png`).
- 🩸 **Luật bất khả xâm phạm bộ nhận diện:** đồng phục `KHỐI KỸ THUẬT` (gile + sơ mi + nón
  + logo trắng ngực phải) là **bộ mặt thương hiệu**, không phải quần áo. Đổi áo/quần/váy/giày
  ra khỏi bộ đó = **rời nhận diện**. Được phép: chân dung ngoài công việc, ảnh đời thường,
  chiến dịch riêng đã duyệt. **CẤM tuyệt đối:** ảnh đại diện công việc, hồ sơ dự án, báo cáo,
  danh thiếp, trang giới thiệu — sai đồng phục ở đó là làm lại cả series.

## E1 — Mặc áo ngoài lên người

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer (this defines the person). ẢNH THAM CHIẾU = the attached photo of the [blazer/top].
EDIT REQUEST: Put this [blazer/top] on her. Fit it naturally to her real body: correct shoulder line, correct sleeve length, realistic fabric drape and folds, realistic collar position, natural contact shadows where the garment meets the body. Match the lighting, white balance and grain of the original photo so the new garment looks photographed in the same shot.
KEEP UNCHANGED — DO NOT TOUCH: the pose and the facial expression exactly as in ẢNH GỐC; hair (length, parting, strands); skin tone and skin texture; jewelry; the entire background; camera angle, framing and aspect ratio; body proportions.
NEGATIVE — ABSOLUTELY FORBIDDEN: do not change hair, skin tone, jewelry or background; no face swap; no body reshaping; no different pose; no pasted-on garment with mismatched lighting; no new accessories; no added people; no text or logos other than the ones already present in ẢNH GỐC.
```

**Nhận diện:** rời đồng phục ⇒ không dùng cho ảnh đại diện công việc, hồ sơ dự án, báo cáo, danh thiếp.

## E2 — Thay quần theo ảnh tham chiếu

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer. ẢNH THAM CHIẾU = the attached photo of the trousers.
EDIT REQUEST: Replace her trousers with the ones from the reference image. Keep the fit as [wide/straight/skinny] and keep the exact reference design: fabric, color, waistband, pleats, stitching. Preserve the real length relationship to the shoes and keep realistic fabric folds, creases and contact shadows at the hip, knee and hem.
KEEP UNCHANGED — DO NOT TOUCH: shoes exactly as in ẢNH GỐC; stance and leg position; the torso, arms, hands and face; hair, makeup and skin tone; the background; camera angle, framing and aspect ratio; the tucked-in shirt and belt as they already are.
NEGATIVE — ABSOLUTELY FORBIDDEN: do not change shoes or stance; no leg reshaping or lengthening; no slimmer waist; no different pose; no new garment beyond the trousers; no pattern or logo added to the trousers; no lighting mismatch between the trousers and the rest of the frame.
```

**Nhận diện:** quần tây đen là phần bắt buộc của đồng phục ⇒ cấm jeans/quần ngắn/quần bó trong mọi ảnh công việc.

## E3 — Thay toàn bộ trang phục bằng váy

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer. ẢNH THAM CHIẾU = the attached photo of the [dress].
EDIT REQUEST: Replace her outfit with the [dress] from the reference image; keep the length [midi/maxi] and keep the exact reference design — cut, fabric, color, neckline, sleeves, seam lines. Dress it onto her real body with correct drape, natural folds and realistic contact shadows, matching the original photo's light direction, white balance and grain.
KEEP UNCHANGED — DO NOT TOUCH: the background exactly as in ẢNH GỐC; body proportions exactly as in ẢNH GỐC; pose, hands and facial expression; hair, makeup, skin tone and skin texture; camera angle, framing and aspect ratio.
NEGATIVE — ABSOLUTELY FORBIDDEN: no body reshaping, no waist slimming, no leg lengthening, no height change; no different pose; no added accessories or jewelry; no background change; no second garment layered over the dress; no suggestive styling, no low cut, no tight body-con silhouette; no change to the person's face.
```

**Nhận diện:** xung đột gay gắt nhất — nữ kỹ sư Newtecons không có váy trong bộ đồng phục, và váy
cũng vi phạm quy tắc an toàn công trường. Cấm cho mọi ảnh công việc; chỉ chạy khi người dùng nói
rõ đây là ảnh đời thường/chiến dịch riêng **và** ảnh không mang chữ hay logo Newtecons.

## E4 — Đi giày theo ảnh tham chiếu

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer. ẢNH THAM CHIẾU = the attached photo of the [sneakers/heels].
EDIT REQUEST: Put these [sneakers/heels] on her. Match the exact reference design, color and material. Place them on the existing foot position with correct perspective, correct scale and realistic contact shadow on the ground; keep the pant hem length exactly as in ẢNH GỐC and let the hem fall naturally over the shoe.
KEEP UNCHANGED — DO NOT TOUCH: pant hem length and pant leg shape; stance and foot placement; the rest of the outfit; face, hair and skin tone; the background; camera angle, framing and aspect ratio.
NEGATIVE — ABSOLUTELY FORBIDDEN: do not change stance; no foot or ankle distortion; no extra or mirrored shoes; no floating feet; no changed hem; no leg lengthening; no added shadow that contradicts the original light direction.
```

**Nhận diện:** trên công trường giày bảo hộ mũi thép là PPE bắt buộc — sneaker/cao gót ở đó là sai
**an toàn lao động**, không chỉ sai nhận diện. Văn phòng: giày da đen công sở.

## E5 — Thêm túi xách vào tay phải

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer. ẢNH THAM CHIẾU = the attached photo of the [handbag].
EDIT REQUEST: Add this [handbag] in her right hand at hip level. Keep the exact reference design, color, hardware and material. The hand must close around the handle with anatomically correct fingers; the strap must fall naturally from the hand with a real gravity curve and a realistic contact shadow against the hip and thigh.
KEEP UNCHANGED — DO NOT TOUCH: fingers and pose exactly as in ẢNH GỐC; the outfit; face, hair, makeup and skin tone; the background; camera angle, framing and aspect ratio; any existing text or logo on the clothing — nothing may cover or clip them.
NEGATIVE — ABSOLUTELY FORBIDDEN: no extra, missing, fused or reshaped fingers; no second bag; no bag floating or merged into the body; no strap melting into the fabric; no change to the pose; no change to the background; the bag must not obscure the chest text or the chest logo.
```

**Nhận diện:** không phá đồng phục ⇒ **được dùng cả trong ảnh công việc**, với hai điều kiện:
không che chữ `KHỐI KỸ THUẬT` ngực trái và logo trắng ngực phải; và hợp cảnh (túi xách bên người
đội nón giữa công trường là chi tiết lạc tông — nên để văn phòng hoặc đời thường).

## E6 — Đeo kính râm

```text
INPUTS: ẢNH GỐC = the attached original photograph of the engineer. ẢNH THAM CHIẾU = the attached photo of the [sunglasses].
EDIT REQUEST: Put these [sunglasses] on her face. Match the exact reference frame shape, color and lens tint, correct scale for her face width, correct temple arms resting on the ears, correct bridge position on the nose, and keep the lens reflections natural — reflecting the real environment of ẢNH GỐC, not a generic studio reflection.
KEEP UNCHANGED — DO NOT TOUCH: makeup and hair exactly as in ẢNH GỐC; the rest of the face below the glasses; skin tone and skin texture; the outfit; the background; camera angle, framing and aspect ratio.
NEGATIVE — ABSOLUTELY FORBIDDEN: no change to makeup or hair; no altered background; no mirrored or duplicated glasses; no floating frames; no fake or painted-on lens reflections; no enlarged eyes, no beautified face behind the lenses; no change to jawline, nose or skin.
```

**Nhận diện:** kính râm che mắt ⇒ phá eye-lock, thứ đắt nhất của bộ nhân vật. Cấm cho ảnh nhận diện,
ảnh đại diện công việc, hồ sơ dự án. Không dùng trên công trường (kính an toàn mới đúng). Kể cả khi
được phép, vẫn phải nói rõ với người dùng: **mặt sẽ không còn khớp 100%**.

## 🩸 Trạng thái kỹ thuật — đọc trước khi hứa với ai

`tao_anh.py` hiện **CHỈ TẠO ảnh mới**, chưa có nhánh nhận ảnh gốc để sửa. Sáu prompt trên chỉ
chạy được khi payload gửi kèm ảnh gốc + ảnh tham chiếu. Hứa trước khi có nhánh đó là lặp lại
đúng lỗi "prompt bảo dùng ảnh đính kèm mà model chưa từng nhận tấm nào".
