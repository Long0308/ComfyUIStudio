# Tổng hợp review độc lập — bộ intro Workshop AI Navy–Cyan

Đây là bản tổng hợp của root từ các reviewer độc lập và receipt thực tế. Các phạm vi bên dưới được kiểm riêng; một phép đo hash không thay cho kiểm tra đọc chữ hoặc chất lượng hình.

| Phạm vi | Bằng chứng | Kết quả |
|---|---|---|
| Chữ và C#/PowerShell | [independent-text-audit.md](independent-text-audit.md) | 34 kiểm tra nội dung; 68/68 tệp dựng lại khớp; đúng `tầm` U+1EA7; lề pixel tối thiểu 19px |
| JavaScript chuyển động | [independent-motion-code-audit.md](independent-motion-code-audit.md) | Đã sửa callback Play/Pause và cửa sổ tiêu đề; thứ tự seek không làm đổi markup ở các frame kiểm |
| Gói bàn giao và nguồn logo | [independent-package-audit.md](independent-package-audit.md) | 98/98 tài nguyên đúng hash/dung lượng; 34 cặp chữ; 5 lớp PNG nhúng của A02 khớp nguồn; thiếu tệp bắt buộc thì dừng |
| Hình ảnh và diễn tiến | [independent-visual-audit.md](independent-visual-audit.md) | Kiểm khung ngang/dọc, chữ/logo và 6 thời điểm giải mã từ MP4; xem chi tiết giới hạn ở báo cáo |
| Timeline chương trình | [agenda-verification.json](agenda-verification.json) | 150 phút, mục cha liên tục; các mục con có thời gian nằm đúng trong cha; không thêm giờ cho ý con phần 2 |
| Video | [motion-preview-video.json](motion-preview-video.json) | H.264 1920×1080, 30 fps, 600 frame, 20 giây, giải mã đầy đủ thành công |
| Pixel theo thứ tự seek | [motion-preview-render.json](motion-preview-render.json) | 0 tài nguyên tải lỗi; 5 lần đối chiếu SHA256 pixel khớp |

MP4 cuối: `42576bf13437c787d89a05fb64ed5c8d9a4c7bf53928d871cb6ea853d66e495b`, 3.841.629 byte. Reviewer riêng dùng `ffprobe -count_frames` thấy 600/600 frame và `ffmpeg -xerror` giải mã exit 0, không stderr. Bộ finalizer đã bổ sung `-xerror` theo khuyến nghị đó. Clip cơ khí riêng có 90 frame / 3 giây.

Reviewer ảnh đã xem các thời điểm 5,2 / 5,6 / 6,0 / 6,4 / 6,9 / 7,4 giây được giải mã từ chính MP4: đế vào, khung/ống gió với tay gắp trái, ống/máng với tay gắp phải, panel vào vị trí, tay gắp rút/chốt khóa, rồi nét sáng kích hoạt. Các trạng thái được lấy mẫu giữ khoảng hở với tiêu đề. Đây là minh họa kỹ thuật 2.5D có chuyển động lắp ráp; không có chứng nhận là cảnh máy móc photoreal.

Giới hạn còn được ghi rõ:

- Logo nguồn được giữ nguyên byte trong compound. Tagline **Build on trust** trên nón/áo quá nhỏ để đọc như dòng văn bản ở cỡ video; không gán PASS độ đọc microtext chỉ từ hash nguồn.
- Nhân vật có chút nhiễu mép ở mức zoom lớn. Kiểm alpha độc lập không thấy mảng matte trắng lớn gây mất tập trung trong cảnh nền navy đã kiểm.
- Tiêu đề dài bản dọc giữ nguyên câu, đọc được nhưng nhỏ hơn tương quan bản ngang. Chân đế phụ của tay gắp có phần đi ra ngoài hai cạnh bản dọc; mô hình chính và chữ nguyên vẹn.
- Bản video giao là proof ngang 1080p/30 fps, im lặng. Bản dọc là HTML có chuyển động và các frame mẫu. Chưa xuất video dọc hoặc master 4K/60 fps ở lượt này.
- Lịch và tên trong chương trình khớp nguồn đã lưu; không phải xác nhận lại với ban tổ chức.
- Lượt recall của root qua MCP thành công và tái dùng đúng gói hiện có. Lượt phụ Opus bổ sung bị HTTP 429, không được ghi là recall thành công. Lưu fact cuối dùng bank `may-agent-memory`.
