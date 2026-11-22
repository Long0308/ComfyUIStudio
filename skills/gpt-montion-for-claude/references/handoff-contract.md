# Hợp đồng bàn giao ảnh → motion cho Claude

Đây là cấu trúc dữ liệu và nội dung cần có khi công việc yêu cầu một bộ tài nguyên
chuyển động hoàn chỉnh. Giữ cấu trúc project hiện có nếu đã đáp ứng các phần này.

## Asset manifest

Mỗi asset cần ID bền, đường dẫn tương đối, provenance, chiều rộng/cao thật, alpha,
content bounds, điểm neo/pivot, layer order và giới hạn sử dụng. Ghi SHA-256 khi
cần chứng minh sao chép hoặc đồng nhất logo. Không suy alpha từ nền caro nhìn thấy.

Phân loại provenance:

- `source-copy`: giữ nguyên byte nguồn, đo hash.
- `generated-reconstruction`: imagegen tái dựng theo reference; không khẳng định pixel-exact.
- `native-vector`: đường nét/hình học được dựng bằng code.
- `compound`: ảnh/lớp nguồn được ghép; ghi từng source và transform.

Part cùng assembly giữ chung viewBox/canvas; cắt từng PNG riêng sẽ làm mất điểm lắp.
Với ảnh mặt/người, chọn rigid 2D reframe nếu không có yêu cầu và tài nguyên cho chuyển động cơ thể.

## Nội dung và typography

Giữ `text-content.json` hoặc nguồn tương đương với ID, text nguyên văn, file SVG/PNG,
font family/style/size, group/run IDs. Title/presenter có cấp bậc khác nhau. Nếu text
gắn với agenda, dùng nguồn agenda để kiểm tên, dự án, thứ tự và khoảng giờ cha/con.
Không tự suy ra giờ của các ý con khi nguồn không có.

Biến thương hiệu nên độc lập: `company_logo`, `header_department`,
`wardrobe_department`, `presenter_text`. Đổi header chỉ thay trường header và
text tương ứng; không thay logo, áo hoặc dòng diễn giả theo phép thay toàn cục.

Font dùng để dựng lại cần có phiên bản/hash hoặc nguồn có giấy phép rõ. SVG outline
đã xuất không cần font ở runtime. Không đóng gói font khi chưa có căn cứ phân phối.

## Prompt ảnh

Mỗi prompt ghi `subject`, `style`, `composition`, `lighting`, `palette`,
`material`, `aspect/size`, `negative`, thêm `text_content` nếu có chữ.
Với chỉnh ảnh: ghi **Target / Change / Preserve / Allow** và chỉ rõ vai trò từng reference.
Lưu câu prompt thực tế nếu tool trả/lưu được; bản tái ghi từ ghi nhớ phải gọi là
recipe tái dựng, không giả là transcript API gốc. Không bịa model, seed hoặc kích thước.

## Storyboard và clock

Ghi `fps`, `duration_frames`, aspect, kích thước canvas và scene intervals
`[start inclusive, end exclusive)`. Mỗi scene nối actor trước/sau, có file ID,
chuyển động chính, easing, thời điểm text vào/giữ/ra. Các nhóm cần xuất hiện hai lần
phải có hai display windows; một khoảng frame lớn dễ làm title hiện cả giữa phim.

Trạng thái hình là hàm của frame. Clock UI chỉ chọn frame, không tích lũy vật lý
hoặc tăng transform. Play/Pause/Seek/Restart phải hủy callback cũ. Nếu target dùng
60fps và proof 30fps, ghi rõ chuyển đổi `masterFrame = proofFrame × 2`; không đổi
frame trực tiếp mà quên tỷ lệ clock. Trong mẫu, 20s tương ứng 1200/600 frames.

## Prompt Claude tối thiểu

```text
Mục tiêu và nguồn đã chọn:
Thư mục project/output:
Tệp nội dung chuẩn và brand artwork:
Asset manifest + text manifest:
Tỷ lệ, canvas, fps, duration_frames:
Scene intervals và text windows:
Layer order + pivot + entry/hold/exit cho từng actor:
Các điều phải giữ, thay đổi đã được user cho phép:
Lệnh chạy và các phụ thuộc thực tế:
File preview/render phải tạo:
Phép kiểm đầu ra + giới hạn chưa xác nhận:
```

Viết prompt giao thật từ [template portable](portable-claude-prompt.md).
[Brief lịch sử](../assets/workshop-navy-cyan/prompts/CLAUDE-MOTION-INTRO.md)
và [shot prompts](../assets/workshop-navy-cyan/prompts/SHOT-PROMPTS.md) chỉ cung cấp
ví dụ về actor/frame. Không gửi nguyên văn các lệnh, đường dẫn tuyệt đối và yêu cầu
skill của môi trường cũ. Tên người/ngày/sự kiện cũng chỉ thuộc mẫu; lấy nội dung user
cho task mới thay vì áp mặc định.
