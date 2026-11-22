# Template giao Claude theo project hiện tại

Agent tạo một prompt hoàn chỉnh từ cấu trúc dưới, điền dữ liệu đã biết trước khi
giao. Đây là template có tham số, không phải task đã được điền. Không mang đường
dẫn máy tác giả hoặc quyền làm thêm từ brief lịch sử sang task mới.

## Thông tin phải điền

| Trường | Lấy từ |
|---|---|
| `project_root` | Thư mục user yêu cầu hoặc project phù hợp đang có |
| `delivery_requested` | `handoff_only`, `preview`, hoặc `render_master` theo yêu cầu thật |
| `approved_source` | Ảnh/canvas/style user đã chọn, đường dẫn trong project |
| `content_source` | Nguồn nội dung local trong project, không dùng canon tuyệt đối của máy khác |
| `asset_manifest`, `text_manifest`, `motion_manifest` | Các tệp thực có trong project |
| `brand_sources` | Logo thật và quy tắc biến header/wardrobe/presenter riêng |
| `allowed_changes` | Những thay đổi user đã giao, ví dụ chỉ header department |
| `targets` | Aspect/canvas/fps/duration user yêu cầu, tách proof và master |
| `outputs` | Tên và nơi lưu những tệp cần tạo ở lượt này |
| `verified_existing_outputs` | Những tệp đã đo; ghi bằng chứng và giới hạn |

Nếu dùng mẫu Workshop nguyên cấu trúc, đường dẫn tính từ `project_root` là
`references/workshop-content.json`, `asset-manifest.json`, `text-content.json`,
`text-animation.json`, `prompts/motion-scenes.json`, `assets/brand/` và `animation/`.
Những đường dẫn này cần kiểm tồn tại trong bản sao làm việc trước khi ghi prompt.

## Nội dung prompt giao thật

1. Nêu mục tiêu, `project_root` và `delivery_requested`. Đọc các manifest local đã
   chỉ định, giữ ảnh/style đã chọn và áp dụng đúng `allowed_changes`.
2. Tái sử dụng renderer/layers sẵn có. Mọi ảnh, font và code phải lấy từ project hoặc
   công cụ thực có; những skill bổ trợ chỉ là lựa chọn khi được môi trường cung cấp.
3. Chỉ thay header department nếu đó là yêu cầu. Giữ artwork logo, wardrobe và các
   tên/phòng ban trong presenter. Nội dung chỉnh sửa thuộc bản sao làm việc; cập nhật
   nguồn canonical local, hash và nhóm chữ tương ứng theo generator trước khi render.
4. Giữ native outline tiếng Việt; không tách dấu khỏi glyph. Chỉ hứa animation theo
   cấu trúc group thực có. Định nghĩa scene `[start,end)`, text windows và khoảng giữ.
5. Viết layer order/pivot, các bước arrive/align/clamp/lock/activate nếu phù hợp. Reflow
   khổ dọc, giữ khoảng hở title, và phân biệt native vector với ảnh photoreal tĩnh.
6. `handoff_only`: chỉ chuẩn bị asset mapping, nội dung và prompt/plan đã yêu cầu;
   không chạy render mới, cài dependency hay tuyên bố có master xuất ra.
   `preview`: chạy proof theo phạm vi. `render_master`: xuất đúng target và đo file thật.
7. Kiểm theo [acceptance checks](acceptance-checks.md). Nêu số đo, tệp evidence và
   giới hạn. Phân biệt requested target với output thực tế đã có.

Trong prompt đã điền, thay các tên trường bằng giá trị thật; không để Claude đoán
`project_root`, file IDs hoặc tên người từ trí nhớ. Khi dữ liệu đã có trong lịch sử,
đọc và dùng lại, không hỏi user chọn style lần nữa.
