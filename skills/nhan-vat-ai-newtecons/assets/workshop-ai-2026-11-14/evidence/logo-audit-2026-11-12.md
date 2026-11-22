# Bổ sung audit logo độc lập — 12.11.2026

Audit chi tiết diễn ra **sau** [review nội dung và kỹ thuật](independent-review-2026-11-12.md). Nó thu hẹp kết luận nhận diện; không hủy các kết quả đã đo về chữ, lịch, kích thước và QR. **Hai PNG Navy–Cyan chưa được sửa sau audit này.**

Nguồn được reviewer xem: N riêng 317×380 do người dùng cung cấp; logo màu và trắng đầy đủ 1134×633; asset header ngang 1508×373. Bản sao và hash ở [branding](../branding/README.md). Reviewer dùng ảnh cuối native 2160×3840 và 3840×2160, không dùng tên file làm bằng chứng đúng logo.

| Vị trí | Kết quả có bằng chứng | Giới hạn |
|---|---|---|
| Header hai khổ | Đọc đúng NEWTECONS, Build on trust và ®; không trùng wordmark | **FAIL về khoảng thoáng bảng trắng**; chưa xác minh giữ nguyên mọi tỷ lệ nguồn |
| Nón nam và nữ | Nhận diện thương hiệu được | **UNCERTAIN về source fidelity**, tagline/® và hình học nhỏ chưa đủ pixel để chứng nhận |
| Áo nam và nữ | Đọc được NEWTECONS trắng | **UNCERTAIN về source fidelity**, ảnh hưởng phối cảnh/vải và kích thước raster |
| Logo giữa QR | Nhận diện N + tên được; QR đã được giải mã ở lượt kiểm kỹ thuật | Tagline/® quá nhỏ để chứng nhận; QR decode không thay cho kiểm logo |

Lỗi rõ nhất là N chạm/vượt mép bảng trắng, **không phải N bị cắt mất**:

- Dọc: bbox N đỏ `(120,38,276,222)`, bảng trắng y=`[40,220)`; vượt khoảng 2 px trên/dưới.
- Ngang: bbox N đỏ `(120,41,273,222)`, bảng trắng y=`[42,222)`; vượt khoảng 1 px trên và chạm đáy.
- Tỷ lệ bbox N khác nguồn N riêng khoảng **1,63% dọc / 1,33% ngang**, sai số cạnh khoảng 1 px. Đây là chênh lệch nhỏ đo trên raster, không đủ để gọi là biến dạng nghiêm trọng.

Các bbox dùng `(left, top, right, bottom)`, cạnh phải/dưới loại trừ. Chưa có tài liệu clearspace chính thức nên không tự gán một khoảng cách là chuẩn công ty.

Crop thật: [header dọc](../styles/navy-cyan-2026-11-12/audit-logo-2026-11-12/independent/9x16-header.png), [header ngang](../styles/navy-cyan-2026-11-12/audit-logo-2026-11-12/independent/16x9-header.png), [nón nam](../styles/navy-cyan-2026-11-12/audit-logo-2026-11-12/independent/9x16-helmet-man.png), [nón nữ](../styles/navy-cyan-2026-11-12/audit-logo-2026-11-12/independent/9x16-helmet-woman.png). File `*-4x-inspection.png` chỉ là crop phóng nearest-neighbor để soi pixel, không phải bản nâng nét.

Logo nón/áo nằm trong hero sinh mới; **chưa có lớp ghép logo chính thức riêng được xác minh**. Không có đủ bằng chứng để nói các logo nhỏ sai chính tả, cũng không đủ để nói tất cả giữ nguyên 100% artwork.

Hướng sửa cho phiên bản sau: logo header đúng tỷ lệ nằm trọn bảng có khoảng thoáng; logo nhỏ dùng nguồn thật và phép đặt theo bề mặt, hoặc nguồn/bố cục lớn hơn; kiểm từng ký tự và dòng xanh theo [quy tắc nhận diện](../branding/README.md). Không chuyển trạng thái sang PASS trước khi có PNG mới và audit độc lập.
