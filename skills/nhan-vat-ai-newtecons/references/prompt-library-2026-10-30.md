# Thư viện prompt nhân vật NEWTECONS theo thể loại — mục A, C, D, E (user, 2026-10-30)

Nguồn: [USER-PROMPT-NOTES-2026-10-30.md](J:/1.JennieHomeSchool/03%20Voice/docs/prompts/USER-PROMPT-NOTES-2026-10-30.md), mục **A** (áp cho sửa trang phục), **C** (Identity Lock), **D** (câu khoá mặt và negative), **E** (da thật).

**Phạm vi dùng:** chỉ cho nhân vật hoặc diễn viên **đã được duyệt**. Không dùng khoá mặt để ghép người thật chưa đồng ý. Mẫu thân mật/gợi dục với người thật đã bị root loại và không có ở đây.

Liên kết chéo: [nhan-vat-ai-newtecons SKILL](../SKILL.md) · [tao-anh-prompt-as-code SKILL](../../tao-anh-prompt-as-code/SKILL.md) (khối biến, mục B và G) · [gpt-image-2-style-library SKILL](../../gpt-image-2-style-library/SKILL.md) (bảng 6 mẫu trang phục VN/EN, mục A của ghi chú; ảnh thẻ, mục F; nâng nét, mục E).

Các câu sửa trang phục theo E1–E6 đã có tại [prompt-sua-anh.md](prompt-sua-anh.md). Phần nâng nét và da nhựa đã có tại [nang-cap-anh.md](nang-cap-anh.md) mục ② và ③. Các mục dưới đây bổ sung nguồn user và câu khoá, không thay thế.

## A. Sửa trang phục NEWTECONS (nguồn: mục A của ghi chú)

Mẫu cấu trúc chung: [ĐỘNG TỪ thay/thêm] + [món đồ] + [vị trí/phom] + GIỮ (dáng, biểu cảm, tóc, da, nền) + KHÔNG ĐỔI (giày, tư thế) + chi tiết vật lý (bóng đổ, nếp vải, phản xạ).

Mẫu áp cho NEWTECONS:
> Put this [NEWTECONS uniform shirt: very fine blue-white grid, small NEWTECONS logo on the collar / reflective vest / helmet with color logo] on him. Keep face, pose and expression the same. Do not change hair, skin tone or background.

Dịch VN: "Mặc [áo sơ mi đồng phục NEWTECONS: lưới xanh-trắng rất mịn, logo NEWTECONS nhỏ ở cổ áo / áo phản quang / nón có logo màu] lên anh ấy. Giữ nguyên khuôn mặt, tư thế và biểu cảm. Không đổi tóc, màu da hoặc phông nền."

Ảnh áo chuẩn (đường dẫn tương đối từ gốc repo `03 Voice`):
`production-local/character-library/newtecons/wardrobe/v001/user-feedback/SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png`

Lưu ý: nếu ảnh áo chuẩn này không đính kèm trong payload thì không được nhắc đến trong prompt (xem mục CẤM của SKILL).

## C. Khoá danh tính (Identity Lock) — ID + REF + LOCK + DETAIL + LIMIT (nguồn: mục C của ghi chú)

| Phần | Mục đích | Câu mẫu |
|---|---|---|
| ID | khoá danh tính | "Use the exact face from the reference image with 100% identity accuracy." / "Preserve the precise facial structure, proportions, and all unique identity traits." |
| REF | neo theo ảnh gốc | "Match the eyes, eyebrows, jawline, nose, lips exactly as in the reference." / "Do not alter shape, age, or facial geometry." |
| LOCK | chống trôi mặt | "No face blending, no AI beautification, no reconstruction." / "Do not stylize the face." / "Avoid identity drift." / "Strict face preservation required." |
| DETAIL | độ thật | "Ultra-detailed skin texture", "Micro-expressions preserved", "Realistic pores and lighting on facial contours" |
| LIMIT | giới hạn vùng | "Do not change hairstyle unless specified." / "Do not alter facial fat distribution." / "No smoothing or retouching." |

Khoá mặt cho **video**: "Lock the facial identity to the reference image across all frames…". Bản user gửi bị cắt giữa câu, cần user gửi lại phần còn lại trước khi dùng câu này cho video.

**Lỗi làm sai mặt (tránh):**
- Tính từ làm đẹp: "handsome, beautiful, attractive, cool face, strong face, perfect jawline".
- "smooth skin" (ra mặt búp bê).
- Phong cách anime, cartoon hoặc Pixar.
- Ảnh gốc mờ, nghiêng, ngược sáng, hoặc dưới khoảng 600 px.

**Chuẩn ảnh gốc:** rõ nét, chính diện, đủ sáng, không makeup đậm, không filter. Phong cách gần ảnh thật: realistic, cinematic, studio lighting.

## D. Câu khoá mặt ngắn và negative (nguồn: mục D của ghi chú)

Câu ngắn:
- "Keep original face exactly."
- "Keep the reference image face uploaded 100%."
- "Use the uploaded face as reference — keep 100%."

Đoạn VN mạnh:
> QUAN TRỌNG TỐI CAO, LỆNH BẮT BUỘC: Giữ nguyên 100% khuôn mặt, nét mặt, nụ cười, màu da, và mái tóc từ ảnh gốc. TUYỆT ĐỐI KHÔNG thay đổi bất kỳ đặc điểm, danh tính hay biểu cảm nào. CỰC KỲ QUAN TRỌNG: Mọi chi tiết độc nhất như sẹo, nốt ruồi, mụn, nếp nhăn, và kết cấu da PHẢI được giữ lại y hệt. Khuôn mặt đã được khóa hoàn toàn.
> Theo sau: "Chỉ thay đổi bối cảnh, trang phục và phong cách."

Từ khoá EN: face lock, identity lock, high fidelity face, do not change face, keep original face, skin texture must be preserved, all marks like acne, scars, moles must be kept.

Danh sách negative: blurry, low resolution, overexposed, underexposed, distorted face, extra fingers, deformed hands, incorrect anatomy, unnatural pose, doll-like skin, plastic texture, cartoonish, oversaturated colors, flat lighting, grainy, noisy, watermark, text, logo, duplicated objects, cropped body parts, unrealistic shadows, floating objects.

Lưu ý: negative có "text" và "logo" trong danh sách. Với NEWTECONS có logo áo hợp lệ, phải cân nhắc khi dùng danh sách này cho ảnh trang phục (logo cổ áo là yêu cầu, không phải lỗi).

## E. Da thật, không "mặt AI" (nguồn: mục E của ghi chú)

- Nâng nét giữ bố cục: đã có ở [nang-cap-anh.md](nang-cap-anh.md) mục ②.
- Chữa da nhựa: đã có ở [nang-cap-anh.md](nang-cap-anh.md) mục ③.

Nguyên tắc từ nguồn: da thật có lỗ chân lông, nếp nhăn mảnh, khuyết điểm nhỏ, không airbrush, không retouch. Mặc định NEWTECONS là da thật, không dùng "da trắng sứ, mịn màng" (xem mâu thuẫn ở [tao-anh-prompt-as-code prompt library](../../tao-anh-prompt-as-code/references/prompt-library-2026-10-30.md), mục G).
