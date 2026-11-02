# Kiểm chữ thêu trên ảnh cuối — bắt buộc từng ký tự

Chỉ kiểm từ PNG cuối đúng SHA256 trong receipt và crop lấy từ chính PNG đó. Xem cả ảnh toàn cảnh để xác định vị trí. Không suy ra kết quả từ prompt, tên file, chuỗi nguồn, ảnh trang phục mẫu hoặc ảnh ở revision khác. Người dùng sẽ nghiệm thu sau.

1. Trước khi xem chuỗi mong đợi, chép lại đúng chữ nhìn thấy trên crop, theo thứ tự các dòng; giữ dấu và khoảng trắng giữa từ. Ký tự không đọc được ghi `?`, không đoán theo tên phòng ban. Có thể phóng gần nhất để xem pixel, không dùng AI tạo thêm nét chữ làm bằng chứng.
2. Đối chiếu bản chép với chuỗi chuẩn NFC và mapping CHAR trong `vest-lettering-contract-v001.json`. Xuống dòng giữa từ được biểu diễn bằng một khoảng trắng khi nối dòng; không bỏ, thêm hoặc sửa ký tự khác để làm khớp. Chữ thêu ở bên trái **ảnh**, trên túi; không lật gương, không đặt trên túi hoặc dải phản quang.
3. Lập một hàng cho TỪNG ký tự, kể cả khoảng trắng: vị trí 1-based, ký tự chuẩn, ký tự quan sát, dấu/nét có nhìn rõ không, PASS/FAIL/UNREADABLE. Dấu là một phần bắt buộc của ký tự. Kiểm rõ `Ố` (mũ+sắc), `Ỹ` (ngã), `Ậ` (mũ+nặng), `Ò` (huyền), `Ế` (mũ+sắc), `Ị` (nặng). Dấu nặng của `Ị` không được biến thành dấu chấm than cạnh chữ.
4. Chuỗi chuẩn duy nhất: `KHỐI KỸ THUẬT`, `BCH`, `SITE MANAGER`, `PHÒNG THIẾT BỊ`. CHAR02/05 dùng SITE MANAGER; CHAR03 dùng PHÒNG THIẾT BỊ; CHAR01/06/07 và CHAR08 khi ở công trường dùng KHỐI KỸ THUẬT. BCH là biến thể thư viện, không tự đổi mapping. CHAR04 suit, CHAR08 ở văn phòng không tự thêm gile/chữ.
5. Kiểm thêm logo trắng gốc bên phải ảnh, logo nón/cổ áo theo nguồn, không thẻ hoặc chữ/logo tự phát trên túi; đủ mesh, túi và dải cam/bạc đúng ảnh gốc. Chữ phải hòa theo bề mặt, nếp vải và ánh sáng; miếng vá chữ nhật, cổ áo dán lộ hoặc dải phản quang sai đều FAIL trang phục dù chữ đọc đúng.
6. Chỉ chấm chữ PASS nếu tất cả ký tự và dấu nhìn rõ, đúng hoàn toàn, vị trí đúng và không lật gương. Một lỗi, một ký tự `?`, chữ bị che/cắt hoặc crop quá nhỏ đều không đạt; không dùng tỷ lệ trung bình, OCR confidence hoặc câu “prompt đúng 100%” để bỏ qua. PASS chữ không tự thành PASS trang phục/nhận diện/nghiệm thu.

Lưu kết quả cùng task ID, PNG/crop SHA256, receipt/job ID, người/model kiểm thật, bản chép trước đối chiếu, từng hàng ký tự, lỗi cụ thể và `user_acceptance: PENDING`. Không ghi tên Gemini nếu route chưa chạy.
