# Blender neon dragon → Claude → Higgsfield

Mở rộng workflow hiện có, không dựng bridge/renderer thứ hai.
Gói dự án đã chuẩn bị trong repo: docs/production/gia-binh-dragon-2026-11-17/v3-neon-full/.
Đọc README.md và CLAUDE-START-HERE.md tại đó; storyboard.json là nguồn timeline duy nhất.
Code helper nằm trong scripts/blender_fx_helpers.py; chỉ import/use theo caller, chưa là phim hoàn chỉnh.

Quy tắc tái sử dụng: khóa một mesh/rig/material rồng cho mọi cảnh; ngọc một object gắn hàm
với transform liên tục; chân contact IK; root path tách spine deformation. Giữ vàng neon
đúng lựa chọn user, không áp palette workshop/navy-cyan cũ lên rồng.

Bản đồ3D nằm ngang có hai quần đảo riêng, chuyển từ trống xoáy; Hà Nội/orbit/cột sáng
và bốn ga dùng cùng địa hình. Tên ga theo nguồn user; không tự xác nhận hướng tuyến.
Ga Gia Bình khác sân bay. Camera-match kiến trúc trước glow; phần khuất/sân bù là minh họa.

Render alpha trước, tạo phông xanh sau; glow riêng. AI finishing chỉ sửa vùng được phép;
geometry/map/đảo/rồng/pearl có lớp Blender gốc để composite lại. Prompt preserve không phải khóa.
Kiểm seek thuận/ngược, contact/pickup/occlusion trên video; không nghiệm thu chuyển động từPNG.

Khi user sửa thứ tự: cập nhật JSON và bản đọc, prompts, board IDs, SFX cùng một phiên bản.
Giữ reference gốc và prompt thực; đo hash/dimensions; đánh dấu bản cũ bị thay thế.
Không nhận có .blend/master hoặc đã cài plugin khi mới làm gói handoff.
