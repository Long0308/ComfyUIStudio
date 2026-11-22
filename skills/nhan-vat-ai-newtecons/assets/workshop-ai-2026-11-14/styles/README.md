# Workshop AI — danh mục 4 style và ảnh mẫu

Chọn **style trước, tỷ lệ sau**. Mỗi style có hai PNG thật: **9:16 = 2160×3840**, **16:9 = 3840×2160**. Bốn prompt 01–04 của gói gốc là hai hợp đồng poster và hai công thức hero/tham chiếu; **không phải bốn style**.

| ID | Style và điểm nhấn | Hai ảnh 4K | Prompt / cách dựng | Trạng thái |
|---|---|---|---|---|
| `blue-white` | Blue–White corporate: nền trắng, xanh doanh nghiệp, ảnh MEP, đường chéo | [9:16](../assets/Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png) · [16:9](../assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png) | [01](../prompts/01-portrait-9x16.json) · [02](../prompts/02-landscape-16x9.json) · [hướng dẫn](../README.md) | Bản chọn đã có kiểm chữ/lịch/QR; không lấy đó làm chứng nhận mọi logo nhỏ |
| `editorial` | Editorial: lưới thoáng, chữ lớn, ảnh công trường, điểm nhấn đỏ | [9:16](editorial-2026-11-05/final/Option-01-Editorial-9x16-4K.png) · [16:9](editorial-2026-11-05/final/Option-01-Editorial-16x9-4K.png) | [prompt](editorial-2026-11-05/prompt-as-code.json) · [hướng dẫn](editorial-2026-11-05/README.md) | Phương án lưu trữ 05.11; xem evidence riêng, logo nhỏ chưa xác minh |
| `signature-navy` | Signature Navy: nền navy sâu, mảng trắng, nhấn đỏ, giờ nổi bật | [9:16](signature-navy-2026-11-05/final/Option-02-Signature-Navy-9x16-4K.png) · [16:9](signature-navy-2026-11-05/final/Option-02-Signature-Navy-16x9-4K.png) | [prompt](signature-navy-2026-11-05/prompt-as-code.json) · [hướng dẫn](signature-navy-2026-11-05/README.md) | Phương án lưu trữ 05.11; không nhầm với Navy–Cyan |
| `navy-cyan` | Navy–Cyan: nền navy, cyan, bảng timeline viền mảnh, nhãn góc chéo | [9:16](navy-cyan-2026-11-12/final/Newtecons-Workshop-AI-Navy-Cyan-9x16-4K.png) · [16:9](navy-cyan-2026-11-12/final/Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png) | [prompt](navy-cyan-2026-11-12/prompt-as-code.json) · [hướng dẫn](navy-cyan-2026-11-12/README.md) | Có kiểm chữ/lịch/QR; **header còn lỗi khoảng thoáng, PPE fidelity UNCERTAIN** |

## Xem nhanh ảnh ngang

**Blue–White**

![Blue–White 16:9](../assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png)

**Editorial**

![Editorial 16:9](editorial-2026-11-05/final/Option-01-Editorial-16x9-4K.png)

**Signature Navy**

![Signature Navy 16:9](signature-navy-2026-11-05/final/Option-02-Signature-Navy-16x9-4K.png)

**Navy–Cyan**

![Navy–Cyan 16:9](navy-cyan-2026-11-12/final/Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png)

## Khi dùng lại

1. Theo tên style/ảnh tham chiếu người dùng chọn. Khi không có chỉ định, dùng Blue–White làm điểm bắt đầu. Dùng `content.json` để giữ nội dung; ảnh style chỉ cấp bố cục/màu/chất liệu, không cho phép rút gọn tên hay đổi lịch.
2. Đọc [quy tắc logo và đổi tên khối](../branding/README.md) trước khi tạo prompt. Logo công ty cố định; `KHỐI CƠ ĐIỆN` là lớp chữ thay được, không phải phần wordmark. **Build on trust** phải đúng từng ký tự.
3. Mỗi lần đổi hero, tên khối hoặc bố cục là một phiên bản mới cần kiểm lại. Ảnh mẫu lưu trữ có thể có lỗi đã biết; dùng để tham chiếu style không đồng nghĩa duyệt mọi chi tiết logo.
4. Không ép toàn bộ raster 9:16 thành 16:9. Dựng lại bố cục cho khổ đích, giữ font thật, PNG lossless, trọn nón/chữ/QR. Xem số pixel hero trong README từng style; canvas 4K không chứng minh hero native 4K.

Hai skill chứa **bản sao thật của cả gói ảnh/prompt/source/evidence**, nằm trong `assets/workshop-ai-2026-11-14/`. Gói nguồn chính vẫn ở `awesome-gpt-image-2/AI-Newteons/workshop-ai-2026-11-14/`. Chỉnh tại gói chính rồi đồng bộ các bản snapshot và đối chiếu manifest; không phát triển các bản skill thành những nguồn khác nhau. Xem [bundle-manifest.json](../bundle-manifest.json).
