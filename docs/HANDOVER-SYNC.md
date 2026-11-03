# Bàn giao đồng bộ giữa hai máy (HOME / COMPANY)

Vấn đề: `git pull` chỉ mang theo workflow JSON và custom node. Model, node chưa được nạp vào ComfyUI đang chạy và ảnh input **không nằm trong git**, nên workflow mở lên có thể lỗi mà không ai báo. `tools/sync_machine.ps1` đo và báo các chỗ thiếu đó.

## Bố cục máy HOME (đo thực tế)

| Thứ | Đường dẫn |
|---|---|
| Code repo (git) | `J:\1.JennieHomeSchool\_push\ComfyUIStudio` |
| ComfyUI root (bind mount `/opt/ComfyUI`, container `Comfyui-Studio`) | `J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI` |
| Workflows | `<root>\user\default\workflows` |
| Custom nodes | `<root>\custom_nodes` |
| Input | `<root>\input` |
| Model root (**ổ C:**) | `C:\AI-Models-Fast\2.Model-AI-Local\ComfyUI` (`-BaseDir` của DOWNLOAD-MODELS = thư mục cha `C:\AI-Models-Fast\2.Model-AI-Local`) |
| API | `http://127.0.0.1:8188` |

Hồ sơ máy nằm ở `machines/<tên>.json`. Máy công ty: copy `machines/company.example.json` thành `machines/company.json` và điền đường dẫn thật (không đoán).

## TRƯỚC KHI PUSH (trên máy đang đẩy)

1. Chạy báo cáo yêu cầu của workflow:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools\sync_machine.ps1 -Machine <me> -Report
   ```
   Lệnh này cập nhật `comfyui/REQUIREMENTS.json` (model + dung lượng, node type + custom node định nghĩa nó, ảnh input của từng workflow).
2. Ảnh input nhỏ (PNG/JPG) mà workflow cần: chép vào `comfyui/input/` rồi commit.
3. Thêm một dòng có ngày vào bảng "Nhật ký bàn giao" bên dưới: đổi gì, model/node/input mới.
4. Commit `comfyui/REQUIREMENTS.json`, `comfyui/input/*`, file này, rồi push.

## SAU KHI PULL (trên máy nhận)

1. Dry-run (chỉ đọc, exit 0 = đủ, 2 = còn thiếu):
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools\sync_machine.ps1 -Machine <me> [-Scope H3_Character_Sheet]
   ```
2. Đọc các chỗ thiếu, rồi `-Apply` để chép workflow và custom_nodes (chỉ thêm; file lệch được sao lưu `.bak-yyyyMMdd`; không xoá gì).
3. Model thiếu: chạy lệnh `DOWNLOAD-MODELS.ps1 -BaseDir ... -Only ...` mà script đã in sẵn (script đồng bộ không bao giờ tải).
4. Node thiếu: node đã được chép bởi `-Apply`; thêm tên folder vào `--whitelist-custom-nodes` trong `docker/comfyui/compose.yaml` (xem README 3.2), restart container `Comfyui-Studio`, tải lại trang (Ctrl+F5). Script không sửa compose, không restart.
5. Ảnh input thiếu: lấy từ `comfyui/input/` (nếu máy kia đã commit) hoặc chép tay vào `<root>\input`.
6. Chạy lại dry-run, mong đợi exit 0. Biên nhận lưu ở `docs/sync/SYNC-<máy>-<yyyyMMdd-HHmm>.json`.

Lưu ý: nếu ComfyUI API không lên, script ghi "NOT CHECKED" cho node type (không bao giờ báo OK giả); model chỉ kiểm bằng tìm file dưới model root.

## Nhật ký bàn giao

| Ngày | Máy | Đổi gì | Model / node / input mới |
|---|---|---|---|
| 2026-11-03 | home | Thêm cơ chế sync (`tools/sync_machine.ps1`, `machines/`, REQUIREMENTS.json) | Chưa có gì mới. Đo H3_Character_Sheet trên HOME: thiếu 3 model, node `H3CharacterSheetDesignerReferenceV13`, nhiều ảnh input (xem receipt trong `docs/sync/`) |
