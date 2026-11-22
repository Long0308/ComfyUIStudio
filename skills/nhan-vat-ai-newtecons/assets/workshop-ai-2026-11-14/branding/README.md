# Logo NEWTECONS và tên khối — quy tắc dùng cho mọi style

Chốt theo yêu cầu người dùng ngày **12.11.2026**. Đây là quy tắc sản xuất cho lần dựng tiếp theo; **không phải thông báo các poster lưu trữ đã được sửa logo**. Xem [audit logo độc lập](../evidence/logo-audit-2026-11-12.md).

## Logo công ty cố định, tên khối thay được

Header gồm **một logo NEWTECONS hoàn chỉnh + một lớp chữ tên đơn vị riêng**. Mặc định Workshop này là `KHỐI CƠ ĐIỆN`; khi làm cho khối khác, thay `header_department_text`, đo lại độ rộng và dàn lại khoảng cách. Không gõ thêm NEWTECONS cạnh logo, không nhúng tên khối vào artwork logo gốc.

| Thành phần | Quy tắc |
|---|---|
| Biểu tượng N | Giữ hình học, tỷ lệ, hướng và màu nguồn; không thay bằng chữ N của một font |
| Wordmark | Đúng **NEWTECONS**, giữ cấu trúc nét và khoảng cách chữ theo nguồn |
| Ký hiệu | Giữ **®** nếu có trong biến thể nguồn được dùng |
| Dòng xanh và tagline | Giữ vị trí, chiều dài, độ dày dòng kẻ và dòng chữ nhỏ **Build on trust** đúng nguồn |
| Tên khối ở header | Lớp chữ Unicode riêng, mặc định **KHỐI CƠ ĐIỆN**, đổi được theo yêu cầu |
| Tên đơn vị trên áo | Biến riêng `wardrobe_department_text`; không mặc định đổi theo header |

**Cấm dùng “Build on strust”, “Build on Trust” hoặc tự bỏ tagline vì chữ nhỏ.** Chuỗi theo nguồn là `Build on trust`, gồm 14 ký tự kể cả hai dấu cách, viết hoa chữ B. Nếu logo quá nhỏ để đọc dòng này, tăng vùng thương hiệu hoặc thay bố cục/ảnh nguồn. Không kết luận đạt chỉ vì đọc được NEWTECONS.

Việc đổi tên khối của poster **không đổi nội dung chương trình**, ví dụ `Văn phòng : Khối Kỹ Thuật` của diễn giả. Không tìm–thay toàn bộ các chữ “Khối” trong ảnh/lịch. Biến trong [brand-contract.json](brand-contract.json) là hợp đồng thiết kế; các renderer lưu trữ hiện vẫn có chuỗi cố định, chưa có API đổi khối tự động.

## Nguồn có sẵn trong gói

| Nguồn | Vai trò |
|---|---|
| [Logo màu đầy đủ](assets/newtecons-full-color.png) | Tham chiếu nón: N đỏ, wordmark xanh, ®, dòng kẻ xanh và tagline |
| [Logo trắng đầy đủ](assets/newtecons-full-white.png) | Nhận diện trên nền áo navy; xem trên nền tối để thấy pixel trắng |
| [Biểu tượng N do người dùng gửi](assets/newtecons-n-symbol.png) | Kiểm hình học N; **không đủ thay cho logo đầy đủ** |
| [Logo ngang đang dùng trong poster](../assets/newtecons-original-logo.png) | Asset lịch sử của header; tên file và hash không tự chứng minh đúng mọi tỷ lệ |
| [Manifest nguồn](reference-assets.json) | Kích thước, dung lượng, SHA-256 và nguồn chép |

![Logo màu đầy đủ và dòng Build on trust](assets/newtecons-full-color.png)

Các PNG được **chép nguyên byte**, không sharpen, không vẽ lại, không đổi sang JPEG. Hiện gói chỉ có các nguồn raster trên; **chưa có vector công ty đã xác minh**.

## Nếu phải dựng lại từng chữ bằng vector

1. Ưu tiên artwork vector chính thức nếu người dùng đã cung cấp. Giữ SVG/PDF/AI/EPS gốc cùng phiên bản xuất và nguồn gốc.
2. Khi chỉ có raster, dùng nguồn sạch nhất; đo N, wordmark, ®, dòng kẻ và tagline thành các lớp riêng. Với chữ đặc trưng, dựng outline/path của **từng glyph** theo nguồn, không chọn một font gần giống rồi gọi là logo gốc.
3. Đối chiếu lần lượt `N E W T E C O N S`, rồi `B u i l d [space] o n [space] t r u s t`. Kiểm thân nét, counter, baseline, kerning, khoảng cách hai từ, dấu ® và quan hệ giữa chữ với dòng xanh. Giữ một bản master vector chưa biến dạng.
4. Đặt bản dựng cạnh nguồn và chồng biên để reviewer độc lập so sánh. Ghi `reconstructed_candidate` cho đến khi kiểm hình học và chữ đạt; không tự nâng trạng thái thành `official_vector`. Không tạo chi tiết không có đủ bằng chứng từ nguồn.
5. Xuất từ master ở kích thước cần dùng. **Vector hóa một raster mờ không khôi phục được chi tiết gốc đã mất**; nếu không đủ dữ liệu, ghi rõ chưa xác minh và dùng nguồn/bố cục tốt hơn.

Đây là phương án xử lý được phép khi cần; lượt cập nhật skill này **chưa dựng master vector mới**.

## Nón, áo: ghép theo bề mặt và kiểm riêng từng người

- Dùng logo màu cho nón, logo trắng cho gile theo mẫu. Giữ form nón, da, mặt, tóc, ánh sáng và thớ vải. Không đặt logo lên túi áo.
- Logo trên bề mặt cong phải có phối cảnh/độ cong phù hợp, mask theo bề mặt và độ che khuất thật. Giữ chữ đủ tương phản; không dùng glow, halo, sharpen mạnh hoặc làm nét giả.
- Dùng công cụ tạo/sửa ảnh được hỗ trợ. Nếu cần ghép vector hoặc compositor để bảo toàn artwork, làm theo workflow được người dùng yêu cầu và khả năng công cụ; lưu lớp nguồn và phép biến đổi. Không giả định prompt sinh ảnh đã giữ đúng logo.
- Nếu dùng hero có logo do mô hình sinh, kiểm lại từng logo nam/nữ; **đọc được thương hiệu** và **khớp artwork gốc** là hai kết luận riêng.
- Không dùng chất lượng của header lớn để cấp PASS cho logo trên nón nhỏ. Nếu tagline/® không đủ pixel để xác minh ở PNG cuối, trạng thái là `UNCERTAIN`, không phải `PASS` và cũng không tự suy thành “AI viết sai”.

## Cổng nhận diện trước khi giao bản mới

Reviewer độc lập xem **nguồn thật + từng PNG cuối**. Mỗi vị trí header/nón nam/nón nữ/áo nam/áo nữ/QR có kết quả riêng, vị trí crop, kích thước logo ở pixel cuối, file nguồn và phép biến đổi nếu có.

1. Header chỉ có một wordmark; tên khối đúng yêu cầu, đứng riêng, không đè logo.
2. N và toàn bộ logo nằm trọn trong bảng chứa, giữ tỷ lệ và có khoảng thoáng thực. Khi chưa có brand guideline, ghi khoảng cách pixel đã đo; không tự gọi một giá trị bịa ra là chuẩn công ty.
3. NEWTECONS, ®, **Build on trust** và dòng xanh đều được kiểm chữ/nét/độ tương phản; không dừng ở OCR tên thương hiệu.
4. Xem crop **1:1 pixel gốc**. Có thể thêm crop phóng nearest-neighbor, ghi rõ chỉ là ảnh soi pixel; không dùng nó làm bằng chứng tăng độ nét.
5. Tách kết quả `readability`, `geometry`, `source_fidelity`, `clearspace`. Chỉ dùng PASS khi có bằng chứng cho tiêu chí đó. Hash chứng minh byte của nguồn, không chứng minh logo ở đầu ra đã đúng.
6. Sau sửa logo, kiểm lại toàn ảnh: dấu Việt, tên khối, mặt/tay, timeline cha–con, QR decode, full frame và đúng **2160×3840 / 3840×2160**. Canvas 4K không bảo đảm ảnh hero hoặc logo nhỏ là chi tiết 4K.
