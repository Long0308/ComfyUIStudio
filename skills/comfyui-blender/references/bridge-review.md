# Bridge upstream: đã kiểm tra 2026-10-18

**Applies to:** hạ tầng dùng chung, mọi domain (không chứa nội dung cast/prompt của domain nào).

> **Trạng thái live 2026-10-27:** custom node `ComfyUI-Blender` có trên đĩa nhưng KHÔNG nằm trong `--whitelist-custom-nodes` của container `Comfyui-Studio`, nên không có node `Blender*` trong `/object_info`. Phần "Cài và thử" bên dưới là quy trình chung cho một lần bật có chủ đích; ở máy này việc bật cần quyết định của user (sửa whitelist + tạo lại container), xem `SKILL.md`.

## Nguồn và phạm vi

- Repo: https://github.com/alexisrolland/ComfyUI-Blender
- Revision được đọc: `1203383bf899aecfe9e521f2155bdc5564cefa8c` (2026-08-21).
- Release mới nhất tại lần kiểm tra: `v4.5.1` (2026-07-22). Không xem thông tin này là phiên bản mới nhất vĩnh viễn.
- Đây là add-on Blender cộng custom nodes ComfyUI. Nó không phải skill Codex hoặc MCP server.
- README ghi add-on 4.x hỗ trợ Blender 5.0; Blender 4.5 dùng nhánh cuối 3.3.4. Điều này không chứng minh mọi operator chạy đúng trên Blender 5.2.2/ComfyUI 0.41.0 của máy hiện tại.

Nguồn: [README](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/README.md), [release](https://github.com/alexisrolland/ComfyUI-Blender/releases/tag/v4.5.1), [metadata](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/pyproject.toml).

## Có thể tái sử dụng

Bảng dưới liệt kê đủ 19 class trong `NODE_CLASS_MAPPINGS` (đối chiếu `__init__.py` ngày 2026-10-27); các hàng cho Boolean/Sampler/Download3D/String được ghi từ tên class và import, chưa chạy thử. API workflow chứa các input/output đặc biệt để add-on tự dựng panel. Node title trở thành nhãn; input group/order hỗ trợ nhóm và sắp thứ tự. Đọc node schema thực, vì wiki có thể chậm hơn mã nguồn.

| Class ID | Vai trò |
| --- | --- |
| `BlenderInputLoadImage` | Ảnh beauty/depth/lineart hoặc reference; mã hiện tại kế thừa `LoadImage` và trả cả IMAGE/MASK |
| `BlenderInputLoadMask` | Mask từ alpha; kiểm tra chiều mask trước inpaint |
| `BlenderInputString`, `BlenderInputStringMultiline` | Prompt và text controls |
| `BlenderInputSeed`, `BlenderInputInt`, `BlenderInputFloat` | Seed và tham số số |
| `BlenderInputGroup`, `BlenderInputCombo` | Nhóm UI và danh sách lựa chọn |
| `BlenderInputBoolean`, `BlenderInputSampler` | Công tắc true/false và chọn sampler (danh sách từ `/blender/samplers`) |
| `BlenderInputLoadCheckpoint`, `BlenderInputLoadDiffusionModel`, `BlenderInputLoadLora` | Loader tương ứng; cần weights cùng họ |
| `BlenderOutputSaveImage` | Lưu ảnh, hiển thị đầu ra trong add-on |
| `BlenderInputLoad3D`, `BlenderOutputSaveGlb` | Trao đổi asset 3D khi workflow và dependency hỗ trợ |
| `BlenderOutputDownload3D`, `BlenderOutputString` | Tải về asset 3D và trả chuỗi văn bản ra add-on |

Add-on có image projection/material, camera render, depth, lineart, viewport preview và render-on-run. Các ví dụ Flux, SDXL, Qwen Image, Z-Image và Hunyuan3D là điểm tham khảo; không đồng nghĩa weights/custom nodes của chúng đã có trên máy. Video sequencing, giữ danh tính nhiều shot, lipsync và 4D thi công cần thêm quy trình ở skill/project.

Nguồn: [class mappings](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/__init__.py), [image node](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/nodes/blender_input_load_image.py), [ví dụ](https://github.com/alexisrolland/ComfyUI-Blender/tree/1203383bf899aecfe9e521f2155bdc5564cefa8c/example_workflows), [tính năng](https://github.com/alexisrolland/ComfyUI-Blender/wiki/Blender-Add%E2%80%90on-Features).

## Vấn đề quan sát trực tiếp trong mã

1. `render_view.py` gán `scene.compositing_node_group` sang cây tạm rồi xóa cây; `reset_scene` không lưu/khôi phục con trỏ compositor cũ. `render_depth_map.py` và `render_lineart.py` cũng tạo/gán/xóa compositor. Chưa kiểm thử runtime; coi việc bảo toàn compositor tùy biến là chưa được đảm bảo.
2. Depth dùng `scene.view_layers["ViewLayer"]` và bật `use_pass_z`; lineart dùng tên cố định này và bật `use_pass_grease_pencil`. Reset hiện tại không khôi phục các pass đó. Scene có layer đổi tên có thể thất bại; không đổi tên layer của người dùng để né lỗi.
3. Các operator view/depth/lineart dùng tên file tạm cố định. Chưa có bằng chứng an toàn khi chạy đồng thời nhiều render. Dùng thư mục/take riêng và thực thi tuần tự trong bản thử.

Nguồn mã: [render_view](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/comfyui_blender/operators/render_view.py), [render_depth_map](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/comfyui_blender/operators/render_depth_map.py), [render_lineart](https://github.com/alexisrolland/ComfyUI-Blender/blob/1203383bf899aecfe9e521f2155bdc5564cefa8c/comfyui_blender/operators/render_lineart.py).

Khi thực sự phát triển wrapper/fork: lưu camera, frame, render/color settings, compositor pointer, layer passes, visibility/selection/mode; thao tác trên scene sao chép, restore bằng `try/finally`, kể cả cancel/exception. Phép thử phải gồm scene có compositor sẵn và view layer đổi tên. Không hứa bản fork đã sửa nếu mới viết hướng dẫn này.

## Cài và thử khi đã có yêu cầu cài đặt

1. Kiểm tra queue trước khi restart ComfyUI; không ngắt job hiện tại.
2. Xác minh release tương thích, chuẩn bị vị trí và bản sao cấu hình user. `comfyui_blender_v4.5.1.zip` là gói Blender, không thay thế phần custom nodes trên server.
3. Cài custom node từ registry qua `install_node` nếu registry ID được xác minh; upstream khai báo project `comfyui-blender`. Không dùng URL thay registry ID. Nếu Manager không được nhận diện, chuẩn bị phương án cài thủ công trong thư mục user sở hữu và nêu rõ cần nạp mã bên thứ ba.
4. Enable Blender add-on và trỏ tới `http://127.0.0.1:8188`. Giữ MCP Blender trên `127.0.0.1:9876`; đây là hai endpoint khác vai trò.
5. Sau restart được phép, xác minh `category="blender"` và đọc đúng schema. Cùng một ảnh có thể dùng input beauty hoặc control, nhưng model/control family phải khớp.
6. Thử API workflow tối thiểu chỉ `BlenderInputLoadImage` → `BlenderOutputSaveImage` trên ảnh thử đã có, không cần diffusion. Xác minh ảnh đầu ra và round trip; không khẳng định model inference được qua phép thử này.
7. Tiếp theo mới kiểm thử một workflow sinh ảnh có model thật, rồi depth/lineart trên bản sao scene. Chỉ sau đó phát triển batch animation/AEC.

Không cần cài bridge để dùng hai MCP theo luồng trao đổi file. Không tự thay graph đang mở bằng ví dụ upstream.
