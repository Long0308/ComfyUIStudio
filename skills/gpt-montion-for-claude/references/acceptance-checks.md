# Kiểm tra tương ứng với đầu ra đã hứa

## Bộ asset và prompt

- Mọi ID/path cần dùng tồn tại; PNG/SVG có đủ cặp theo manifest. Thiếu file bắt buộc
  thì dừng bước đóng gói và nêu đúng đường dẫn, không lặng lẽ bỏ khỏi inventory.
- Đọc kích thước/alpha từ tệp hiện tại. Metadata cache không được ghi đè checksum
  mới; byte count, hash và dimensions phải thuộc cùng phiên bản.
- Chữ khớp nguồn Unicode; kiểm thêm ảnh render với dấu tiếng Việt, đường biên và
  thứ bậc title/presenter. Tên dự án/người không sửa bằng phỏng đoán OCR.
- Source-copy logo phải khớp byte/hash. Kiểm hình học, clearspace, vị trí trên từng
  nón/áo và khả năng đọc chữ nhỏ riêng; không gộp thành “logo PASS” không điều kiện.
- Các layer/viewBox/pivot có thể lắp đúng. Prompt Claude trỏ đến tệp thật, không trỏ
  vào Downloads/Temp của máy tác giả như một phụ thuộc bắt buộc.

## Preview/video khi task yêu cầu

- Bắt đầu bằng frame có ý nghĩa; chữ có đủ thời gian đọc. Kiểm entry/exit, đặc biệt
  part bay qua vùng title và bản dọc. Kiểm occlusion/tiếp xúc tay gắp theo chất lượng
  đã hứa; minh họa 2.5D khác với mô phỏng tiếp xúc vật lý.
- Decode thực sự: `ffprobe -count_frames` và `ffmpeg -xerror -i <video> -f null -`.
  Đo width/height, fps, duration, decoded-frame count; không kết luận từ tên “4K”.
- Seek một frame rồi sang frame khác và quay lại; so hash pixel trong cùng môi
  trường. Markup giống nhau chỉ chứng minh markup; không tự nâng thành pixel proof.
- Missing required resource phải làm renderer báo lỗi trước khi encode/báo thành công.
- Bản ngang và bản dọc cần bố cục riêng. Không khẳng định đã có video dọc khi mới có
  HTML hoặc stills; không nói đã xuất master khi mới có storyboard.

## Bàn giao

ZIP chứa ảnh thật, chữ, code cần chạy, prompt, manifest, sample và receipt tương ứng.
Loại profile/cache/token/cấu hình cá nhân, output frame trung gian không cần dùng.
Kiểm entry và hash trong ZIP. Báo trung thực những phần chưa được chứng minh.

Với task cần review độc lập, người kiểm xem artifact thật, không chỉ đọc lời builder.
Chỉ làm thêm phép kiểm khi có thay đổi, lỗi mới hoặc khoảng chưa xác nhận liên quan;
không render lại toàn bộ chỉ để lặp một phép kiểm đã ổn.
