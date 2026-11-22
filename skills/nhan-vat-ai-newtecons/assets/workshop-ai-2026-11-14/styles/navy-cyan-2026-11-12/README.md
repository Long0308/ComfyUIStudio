# Workshop AI — phương án Navy–Cyan

**Bổ sung audit logo 12.11.2026:** hai PNG dưới đây chưa sửa logo. N ở header chạm/vượt mép bảng trắng; logo nón/áo đọc được thương hiệu nhưng tagline/® và source fidelity còn **UNCERTAIN**. Xem [audit chi tiết](../../evidence/logo-audit-2026-11-12.md) và [quy tắc nhận diện](../../branding/README.md). Các kết quả chữ/lịch/QR bên dưới không phải chứng nhận logo nguyên bản 100%.

Phương án bổ sung ngày **12.11.2026**, theo [ảnh phong cách người dùng gửi](assets/user-style-reference.png). Nền navy, điểm nhấn cyan, nhãn phần góc chéo và các bảng timeline có viền mảnh. Bản này giữ nội dung đã chốt trong [gói bốn prompt](../../README.md), gồm **“trong tầm tay”**, **Bason**, đủ tên người, mốc giờ và mục cha–con; không lấy các câu rút gọn trong ảnh phong cách làm nội dung mới.

| File cuối | Kích thước |
|---|---:|
| [Poster dọc 9:16](final/Newtecons-Workshop-AI-Navy-Cyan-9x16-4K.png) | 2160 × 3840 px |
| [Banner ngang 16:9](final/Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png) | 3840 × 2160 px |

![Bản ngang](final/Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png)

<img src="final/Newtecons-Workshop-AI-Navy-Cyan-9x16-4K.png" alt="Bản dọc navy cyan" width="420">

## Tạo mới và giữ nét

Phần hình kỹ sư/MEP/BIM được tạo **mới** bằng `image_gen.imagegen`, dùng ảnh phong cách và ảnh kỹ sư đã chọn làm tham chiếu. [Generation record](generation-record.json) ghi nguyên văn prompt, vai trò ảnh và số pixel thật: công cụ trả **2172 × 724**, dù prompt yêu cầu tối đa 3840 × 1280. Không gọi ảnh nguồn này là ảnh sinh native 4K.

Ảnh mới được đặt **1.0× trong bản ngang** và **0.994475× trong bản dọc**; renderer dừng nếu phép bố trí làm phóng lớn ảnh. Chữ, panel, đường timeline và bố cục được dựng trực tiếp trên canvas cuối 4K. Không dùng poster cũ để upscale. Logo header và QR dùng asset gốc. Tránh nhòe chữ bằng font thật, không đưa lịch tiếng Việt cho mô hình ảnh vẽ lại.

## Chạy lại

Windows PowerShell 5.1 và Roboto Condensed Regular/Bold/Italic như [hướng dẫn gói cha](../../README.md). Từ thư mục chứa README này:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\render.ps1 -HeroPath .\assets\navy-cyan-mep-header.png
```

Lệnh xuất vào `output/`; `final/` giữ hai file đã kiểm tra. C# mở rộng renderer gốc qua partial class để dùng cùng năm tiêu đề, người trình bày, các khung giờ và bốn chủ đề Phần 2. [Prompt-as-code](prompt-as-code.json) mô tả đủ tám trường cùng phân cấp chữ, vùng ảnh, hợp đồng sửa và tiêu chí kiểm tra.

## Kiểm tra

- Hai khổ đúng pixel và tỉ lệ; ảnh minh họa không phóng lớn.
- 80 record chữ (40 mỗi khổ); đo độ rộng, chiều cao dòng và vị trí trong canvas, kèm kiểm trực quan khoảng cách panel.
- Năm tiêu đề Phần 1 cùng cỡ, một dòng đậm: dọc 58 px, ngang 67 px. Dòng người trình bày nhỏ hơn, nghiêng không đậm: 44/50 px.
- Header chỉ có một logo NEWTECONS bên cạnh KHỐI CƠ ĐIỆN; nón giữ trọn hình và wordmark được xem ở crop gốc.
- Timeline vẫn 08:30–11:00, 150 phút, không thêm giờ cho bốn chủ đề Phần 2.
- QR thật nằm trong vùng Phần 3; kiểm giải mã trực tiếp trên cả hai PNG. Xem [bằng chứng](evidence/verification.json).

Các crop và kết quả kiểm tra được lưu cạnh `verification.json`. Kiểm máy về chiều cao dòng không thay thế việc nhìn nét dấu, va chạm giữa chữ và panel hoặc độ rõ logo. Bản navy–cyan là biến thể bổ sung; bốn ảnh nguồn ban đầu vẫn được giữ nguyên trong gói cha.
