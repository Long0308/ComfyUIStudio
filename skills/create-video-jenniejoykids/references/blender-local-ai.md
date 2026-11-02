# Blender render và AI local

Khi Blender dùng để khóa camera, vị trí nhân vật/đạo cụ, chuồng/rào hoặc lớp
che khuất cho storyboard, đọc skill `comfyui-blender` tại
`C:/Users/Admin/.codex/skills/comfyui-blender/SKILL.md` và
[hợp đồng bàn giao storyboard](blender-storyboard-control.md). Dựng ảnh guide
từ scene `.blend` đã lưu, rồi đưa ảnh/pass thật vào workflow ComfyUI local có
receipt. Chỉ ảnh ComfyUI cuối đã xem và đạt bố cục mới có thể làm storyboard.

Ảnh tham chiếu có thể cào từ mạng; ghi provenance riêng với nơi inference. H3,
Hunyuan trong ComfyUI và Blender chạy local; online TTS/cloud imagegen ghi riêng.

Canonical image + mô tả đầy đủ giữ thiết kế nhân vật. GLB/BLEND giữ hình học,
module, Action và camera thật. Ảnh/sequence render từ chính asset đó làm reference
hoặc first-frame cho AI. AI có thể đổi hình; shot cần hình học/chuyển động chính
xác dùng render Blender trực tiếp. Không gắn nhãn phim rig3D cho video H3.

## Node và script thực

`ComfyUI/custom_nodes/jennie_blender_renderer`: `JennieBlenderRender` nhận
`asset_file` tương đối trong ComfyUI/input và `settings_json`:

```json
{"width":864,"height":480,"frames":[1,2,3],"camera_mode":"scene","scene":"Shot01","camera":"Camera01","engine":"eevee","transparent":false}
```

`scene` giữ camera/Action đã dựng. `studio` dùng light rig/camera fit toàn bộ các
frame, thêm `azimuth`/`elevation`. `cycles` nhận `samples`. IMAGE là RGB; MASK là
**1-alpha** theo ComfyUI; dùng JoinImageWithAlpha để lưu RGBA. Node này chưa xuất
depth/normal; không báo các pass đó đã chạy. Worker tắt compositor/sequencer/border.

GLB phải tự chứa ảnh/buffer. BLEND phải pack tài nguyên, make libraries local;
Alembic/VDB/fluid/GN bake và disk cache ngoài chưa hỗ trợ. Xuất evaluated GLB
hoặc viết adapter dependency/snapshot thật khi cần mở rộng, không bỏ kiểm hash.

ComfyUI gọi script tin cậy bằng Blender background riêng; không chạy Python từ
prompt/model. Cache theo source, recipe, script snapshot, node, Blender và PNG.
Đổi node code cần restart ComfyUI khi queue rỗng. Worker dừng khi parent chết;
OS lock tự giải phóng sau crash. Không restart trong khi H3 đang chạy.

## Vật dụng và nhánh AI

Thư mục `production-local/blender-bridge/`:

- `build_vocabulary.py`: Blender script tham số hóa; mỗi vật dụng ở scene riêng,
  xuất GLB với `use_active_scene=True` để không lẫn scene khác.
- `prepare_workflows.py`: graph riêng từng vật dụng.
- `run_vocabulary.py --library <folder>`: submit/resume local ComfyUI, kiểm số
  mesh thật sau import, lưu prompt ID, PNG/receipt/hash và contact sheet.
- `prepare_ai_demo.py`: tạo `workflows/blender-glb-to-local-h3.api.json`, nối
  GLB → Blender render → H3 reference + first-frame. Đây là phép thử tích hợp;
  không thay Master hay tính là phim Mẹ/Alice đã hoàn thành.

Bộ Sữa: `03-drinking-milk/assets3d/vocabulary-v4/`,10 từ. Mỗi asset có full
description, curriculum binding, module names, recipe, GLB, PNG và render receipt.
Glass/Warm/Sip dùng chung recipe ly/sữa. Kiểm lòng ly, màu sữa và silhouette trước
khi dùng trong phim. Các bản có lỗi giữ riêng với defect log.

Sửa đạo cụ chỉ xuất/render variant đó; sửa rig/Action chỉ shot liên quan; sửa
caption/icon card chỉ hậu kỳ; sửa nhạc/SFX chỉ stem/mux. Surface/pivot/scale đổi
phải kiểm lại collider/runtime phụ thuộc. Prop tĩnh không cần rig người; actor
Mẹ/Alice cần retopology/UV/module/rig/facial/Action và QA thật.

Studio Bước5 liên kết workspace tùy chỉnh workflow, gallery và JSON. PNG/GLB mới
chưa tự thay icon SVG của Master đã xuất. Nạp bằng adapter hậu kỳ có hash riêng
rồi render card/callout liên quan, giữ native picture/audio. Mỗi icon/shot vẫn
phải có mô tả đầy đủ + reference bindings; không chỉ dùng tên PNG.
