# Render kiến trúc, kết cấu, MEP và biện pháp thi công

**Applies to:** `aec` only. Không mang cast, trang phục, phụ đề, logo hay quy tắc JennieJoy (`jenniejoy_cartoon_3d`) hoặc NEWTECONS (`newtecons_live_action`) vào đây.

## Nguồn hình học và chế độ đầu ra

Blender scene hoặc mô hình BIM đã được cung cấp giữ vai trò nguồn hình học. Xác minh đơn vị, scale, origin/georeference, axes, level, revision và mapping IFC/Revit ID nếu có. Không giả định add-on ComfyUI-Blender nhập được RVT/IFC hoặc giữ BIM metadata; cần importer/exporter đã xác minh riêng. Giữ element IDs trong custom properties hoặc sidecar mapping khi chuyển đổi định dạng.

Phân biệt mục tiêu trong brief:

- Concept/diễn họa: có thể đề xuất vật liệu, cây xanh, người, ánh sáng trong phạm vi được yêu cầu; ghi phần AI diễn giải.
- Hình kỹ thuật/phối hợp: lấy geometry/edges/masks gốc làm căn cứ. Dùng render xác định từ Blender cho vùng bắt buộc đúng; chỉ cho AI xử lý vùng được phép hoặc đưa ra lớp minh họa tách biệt.
- Trình tự thi công: trạng thái/hành động theo dữ liệu schedule/method statement của dự án; bước chưa có nguồn được đánh dấu đề xuất.

Depth/ControlNet không bảo đảm giữ chính xác kích thước. Không dùng ảnh sinh để đo kích thước, xác nhận chịu lực, clearance hoặc kiểm tra xung đột. Các kết quả đó phải được tính từ mô hình/dữ liệu kỹ thuật bằng công cụ phù hợp.

## Quy trình theo ngành

| Nhánh | Dữ liệu khóa | Đầu ra nên chuẩn bị |
| --- | --- | --- |
| Kiến trúc | Grid, cao độ, kích thước lỗ mở, tỷ lệ mặt đứng, camera | Beauty + depth/lineart + mask vật liệu; các phương án ánh sáng/vật liệu có nhãn |
| Kết cấu | Vị trí/kích thước cột dầm sàn, liên kết, rebar khi có dữ liệu | Cutaway/exploded view từ geometry thật; overlay ID/cao độ ở hậu kỳ |
| MEP | System, tuyến, cao độ, tiết diện/DN, fittings, thiết bị, support khi có | View phân hệ, section, mask theo system, phối hợp theo element IDs |
| Thi công | Work package, predecessors, giai đoạn và hạng mục tạm | Ảnh theo bước hoặc animation visibility/transform trong Blender + chú thích |

Không tự bổ sung cốt thép, fitting, giá đỡ, chằng chống hay đường cẩu vào ảnh rồi coi đó là thiết kế đã duyệt. Có thể dựng phương án đề xuất khi được yêu cầu và lưu provenance của giả định.

## Control passes và đối chiếu

Tạo beauty, depth, lineart và mask theo object/material/discipline từ cùng camera/frame/resolution. Normal và segmentation chỉ dùng khi pass đã được thiết lập và workflow nhận đúng kiểu dữ liệu. Object IDs/Cryptomatte, dimension labels và legends phải lấy từ nguồn xác định; không nhờ diffusion viết mã cấu kiện hoặc số đo.

Depth dùng raw EXR cho dữ liệu tuyến tính và một bản normalized riêng khi control model cần; ghi near/far, inverse hay metric, màu/channel và camera clipping. Mask ghi foreground là 0 hay 1 theo node schema; xem thumbnail kiểm chứng trước inpaint. Không để color grading beauty áp lên depth/normal.

Giữ một bản render kỹ thuật gốc cạnh bản AI. Với yêu cầu giữ hình học, so silhouette/edge/keypoints của vùng khóa cùng source camera; nếu lệch, dùng lại render gốc hoặc composite vùng được phép. Một ngưỡng pixel/IoU phải gắn với mục tiêu dự án, không tự tuyên bố độ chính xác kỹ thuật từ metric ảnh.

Chữ, dimension, grid, elevation, system legend và element IDs đặt ở Blender hoặc hậu kỳ để giữ nội dung chính xác. Image projection trong add-on tạo lớp vật liệu/view, không biến hình ảnh thành BIM có thông số.

## Biện pháp thi công và 4D

Mỗi bước có `step_id`, task/WBS nếu có, element IDs, predecessor IDs, thời gian hoặc thứ tự, trạng thái trước/sau, camera và nguồn chỉ dẫn. Dùng visibility/keyframe/collection cho các trạng thái `existing`, `temporary`, `installing`, `complete`, `removed`. Phân biệt màu trạng thái với màu system.

Kiểm tra predecessor tồn tại và không có vòng lặp; chỉ bật đối tượng khi đến bước, không để cấu kiện hoàn thiện xuất hiện trước lắp đặt. Giữ giáo/chống/cẩu và thứ tự tháo dỡ khi dữ liệu phương án yêu cầu. Không suy năng lực thiết bị, tải trọng hoặc vùng an toàn từ ảnh; nếu brief thiếu thông tin này, vẫn có thể chuẩn bị storyboard minh họa có ghi phần chưa xác minh.

Lưu view/bước cùng model revision, source IDs, workflow, AI parameters và ảnh đối chiếu. Xuất nhãn phù hợp `concept`, `model-based illustration` hoặc trạng thái dự án cung cấp; không tự nâng thành hồ sơ thi công được duyệt.
