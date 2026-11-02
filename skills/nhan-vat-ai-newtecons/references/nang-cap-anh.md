# Nâng cấp ảnh — khoá mặt, da thật, upscale, ghép người vào ảnh có sẵn

Anh Long dạy 16/09/2026. Dùng CHUNG cho mọi nhân vật; khác `prompt-nhan-vat.md` (chữ dài
của bốn nhân vật) và `prompt-sua-anh.md` (đổi áo/quần/giày).

## ① Khối FACE LOCK — bản mạnh, chèn vào mọi prompt có ảnh mặt tham chiếu

Tiếng Việt (giữ nguyên văn, đặt NGAY ĐẦU prompt):

```text
QUAN TRỌNG TỐI CAO, LỆNH BẮT BUỘC: Giữ nguyên 100% khuôn mặt, nét mặt, nụ cười, màu da và mái tóc từ ảnh gốc. TUYỆT ĐỐI KHÔNG thay đổi bất kỳ đặc điểm, danh tính hay biểu cảm nào. CỰC KỲ QUAN TRỌNG: mọi chi tiết độc nhất như sẹo, nốt ruồi, mụn, nếp nhăn và kết cấu da PHẢI được giữ lại y hệt. Khuôn mặt đã được khoá hoàn toàn — chỉ được thay bối cảnh, trang phục và phong cách.
```

Tiếng Anh + bộ từ khoá phải có (model bám từ khoá tốt hơn câu dài):

```text
Keep original face exactly. Use the uploaded face as reference — keep 100%. Keep the reference image face uploaded 100%. Only change the setting, the outfit and the style, never the person.
Face lock · identity lock · high fidelity face · do not change face · keep original face · skin texture must be preserved · all marks like acne, scars, moles must be kept.
```

🩸 Bốn cụm ăn tiền nhất khi model chịu ảnh tham chiếu: **face lock · identity lock ·
high fidelity face · keep original face**. Thiếu chúng thì model vẽ "một người hao hao".

## ② Nâng cấp ảnh chân dung (Makeup / Upscale) — giữ nguyên bố cục

```text
Enhance and upscale the image while keeping composition and colors identical. Eliminate blur and give the skin a lifelike, detailed look: clear pores, faint fine lines, light freckles, and realistic transitions between shadow and highlight. Maintain the tone of the light and the background; refine edge sharpness around eyes, lashes, lips and hair strands so the portrait appears like a high-end beauty photograph with natural, unplastic skin.
```

## ③ Chữa "da nhựa" (Plastic Skin Fix) — câu thay thế

```text
Before: "Portrait of woman, smooth flawless skin, airbrushed"
After : "Portrait of woman, natural skin texture with visible pores, fine lines, subtle skin imperfections, realistic detail, not airbrushed, unretouched photography"
```

🩸 Áp cho MỌI nhân vật: bỏ `smooth/flawless/airbrushed`, thêm `visible pores · fine lines ·
subtle imperfections · unretouched`. Prompt nào còn `flawless skin` là còn nguy cơ da nhựa.

## ④ Ghép MỘT NGƯỜI THỨ HAI vào ảnh đã có (Mẫu thực chiến & Khung chuẩn)

Khung chuẩn:
`	ext
Use [ẢNH NỀN] as the main base image. Keep the original person in it exactly the same: same face, same hair, same skin, same outfit, same pose, same background.
Use [ẢNH NGƯỜI THỨ HAI] as the reference for the second person — keep their real face, hairstyle, skin tone and clothing style.
Add that second person standing close, with natural body proportions and realistic height, interacting naturally (an arm gently around the waist or shoulders, body slightly leaning in, both natural, happy and gentle).
FACE LOCK (both people): giữ nguyên 100% khuôn mặt, nét mặt, màu da, mái tóc của cả hai ảnh gốc; mọi sẹo, nốt ruồi, mụn, nếp nhăn và kết cấu da giữ y hệt. Không chỉnh sửa khuôn mặt.
Perfectly blend the second person into the original scene so lighting, colors, shadows, sharpness and perspective match seamlessly. Do not distort or change the original person's body, pose, outfit or background. 4K, 16:9.
`

Ví dụ thực chiến mẫu (ghép nam vào ảnh nữ bên cửa sổ tòa nhà Capital Place):
`	ext
4k ultra high resolution, 16:9 aspect ratio, hyper realistic photo, natural lighting, shallow depth of field.

Use Ngan.jpg as the main base image. Keep the original girl from Ngan.jpg exactly the same: she is sitting on the indoor window ledge, long black hair, fair skin, beige polka-dot spaghetti strap dress, background with the glass building "CAPITAL PLACE" and city view.

Use Hien.png as the reference for the man and keep his real face, hairstyle, skin tone and clothing style.

Add the man from Hien.png standing close on the right side of the girl, with natural body proportions and realistic height. One arm gently around her waist or shoulders, his body slightly leaning toward her and giving her a soft kiss on her cheek. Both look natural, happy and intimate but gentle.

QUAN TRỌNG TỐI CAO, LỆNH BẮT BUỘC: Giữ nguyên 100% khuôn mặt, nét mặt, nụ cười, màu da, và mái tóc từ ảnh gốc của cô gái trong Ngan.jpg và người đàn ông trong Hien.png. TUYỆT ĐỐI KHÔNG thay đổi bất kỳ đặc điểm, danh tính hay biểu cảm nào. CỰC KỲ QUAN TRỌNG: Mọi chi tiết độc nhất như sẹo, nốt ruồi, mụn, nếp nhăn, và kết cấu da PHẢI được giữ lại y hệt. Khuôn mặt đã được khóa hoàn toàn, không được chỉnh sửa.

Perfectly blend the man into the original Ngan.jpg scene so that lighting, colors, shadows, sharpness and perspective match seamlessly. Do not distort or change the girl's body, pose, outfit or the city background; only add the man from Hien.png in a realistic photographic style, 4k, 16:9.
`

## ⑤ Đổi áo · đổi quần · đổi giày · thêm phụ kiện

Sáu prompt đầy đủ ở `prompt-sua-anh.md` — mỗi prompt nêu rõ ẢNH GỐC + ẢNH THAM CHIẾU và
danh sách "giữ nguyên". Đọc tệp đó trước khi hứa với người dùng.

## ⑥ GHÉP NHÓM THEO SỐ NAM / SỐ NỮ — cấu trúc, không phải mẫu cứng

Câu có SỐ đi kèm giới tính vào nhánh `newtecons_nhom_theo_gioi`: *"3 nam 2 nữ"* ·
*"2 nam và 2 nữ"* · *"ba nam hai nữ"* · *"4 nam 1 nữ"* (không kèm chủ đề One Team)
⇒ `EXACTLY N people: X men and Y women`.

- Người nam ĐẦU TIÊN khoá vào `AI HUMAN FACE.png`; người nữ ĐẦU TIÊN khoá vào `FaceNu.png`.
- Mọi người còn lại là **đồng nghiệp Việt Nam KHÁC**, tả rõ khác khuôn mặt.
- Câu bắt buộc phải có: *"Do NOT clone, duplicate or reuse the reference faces for more than
  one person"* — chỉ có 2 tấm mặt thật cho N người, thiếu câu này là model nhân bản mặt.
- Nhóm (≥2 người) đi **16:9**; câu không nói số thì về nhánh CẶP hoặc MỘT người như cũ.
- Nhóm ở văn phòng vẫn theo tầng biến: áo caro trơn, không nón, nữ đi gót cao.

## 🩸 MỘT THỨ CỐ Ý KHÔNG ĐƯA VÀO HỆ NÀY

Trong bộ prompt anh Long dạy có phần sửa CƠ THỂ (bikini, "full bust", "bigger buttocks") gắn
với khuôn mặt thật. Phần đó **không được mã hoá** vào skill nhân vật Newtecons: đây là bộ mặt
thương hiệu của Khối Kỹ Thuật và là khuôn mặt người thật — gợi cảm hoá khuôn mặt thật rồi gắn
logo công ty là rủi ro nhận diện, không phải "đẹp hơn". Muốn dùng cho ảnh đời thường thì làm ở
**bộ asset riêng, KHÔNG mang logo/chữ Newtecons**, và phải có người chịu trách nhiệm duyệt.
Nữ kỹ sư trong hệ này đẹp bằng **dáng đứng, sự tự tin và ánh mắt** — không bằng hở hang.
