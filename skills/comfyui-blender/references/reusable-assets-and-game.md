# Asset mô-đun cho hoạt hình, vật thể, bối cảnh và game

**Applies to: `jenniejoy_cartoon_3d` only** (character GLB/rig/Action, props, sets). Not for `newtecons_live_action` (previz proxies only, never character creation) and not for `aec` (model renders). **Game content in this file (the "Asset game" row, LOD/collider/engine export, runtime budgets, "Bối cảnh và game") is kept but OUT OF SCOPE until a user decision: game is not one of the three domains.**

Đọc khi tạo model dùng lại hoặc mở rộng scene/game. Đây là workflow tổng quát;
không mang nhân vật, trang phục hay bài học JennieJoy sang dự án khác.

## Chọn đầu ra theo nhu cầu

| Loại asset | Phần cần chứng minh |
|---|---|
| Nhân vật diễn xuất | Likeness/silhouette, topology biến dạng, UV/material, rig/weights, biểu cảm/visemes và Action thật |
| Vật thể tĩnh: ly, ghế, cây, nhà | Tỷ lệ/pivot, silhouette, topology/UV/material phù hợp; collider/LOD khi game cần; không bắt buộc armature |
| Đạo cụ có cơ cấu: cửa, xe, vòi nước | Các phần chuyển động tách được, pivot/constraint đúng, đóng/mở hoặc chuyển động mẫu |
| Bối cảnh/bộ lắp ghép | Asset library và instance, đơn vị, grid/snap/pivot, ánh sáng, lối đi/khe nối, camera và chunk/collection |
| Asset game *(out of scope until a user decision)* | Những mục ở trên theo loại asset, cộng bằng chứng nhập/chạy trong engine đích và ngân sách runtime thực |

Nếu chỉ yêu cầu tạo model, không tự cài game engine, tạo dự án game hay publish.
Khi thực sự xuất cho game, resolve engine/version, nền tảng, góc nhìn, tỷ lệ và
ngân sách từ dự án; thiếu mới hỏi phần ảnh hưởng xuất file. Chưa có engine đích
thì giao `.blend` và interchange phù hợp, để runtime/performance là chưa kiểm.

## Danh tính, mô tả và nguồn

Mỗi asset có `asset_id`, loại, phiên bản, phong cách, kích thước/đơn vị, mô tả đầy
đủ, ảnh/scene tham chiếu với role/path/hash và phạm vi chọn/duyệt. Vật thể mô tả
hình dáng, bộ phận, vật liệu, màu, tỷ lệ và chức năng; không áp trường tuổi/mặt
người cho bàn ghế hay bối cảnh. Mỗi generation request có đầy đủ mô tả và context,
không chỉ tên file/asset ID. Với ảnh-to-mesh chỉ nhận ảnh, ghi đúng mô tả là
provenance/brief; đừng ghi text metadata là prompt đã được model dùng.

Inspect canonical và các góc đã có. View sinh từ một ảnh là diễn giải, không phải
đo hình học mặt khuất. Không ghép sheet nhiều người vào loader một vật thể để
giả đa góc. Chỉ dùng multi-view khi model/node/weights thật hỗ trợ. Tách foreground
khỏi bóng/nền nếu inference phù hợp và giữ bản nguồn; shadow mặt sàn có thể bị
chuyển thành geometry thừa. Seed cố định không bảo đảm likeness.

## Stage và dependency trên đĩa

```text
reference/brief → source geometry → cleanup/retopology → UV/material
                                       ├→ rig/weights/shape keys → Actions
                                       ├→ appearance modules
                                       └→ game LOD/collision
exact asset/module/Action versions → scene instances → render từng shot
render đã lưu → caption/icon/voice/music/SFX → mux/export
```

Mỗi node ghi input artifact hashes, settings/model/tool version, job ID nếu có,
output thật/hash, trạng thái và evidence. Tái sử dụng node có recipe và artifact
còn đúng; dừng tại stage thiếu/hỏng. Đừng đánh dấu `ready` từ tên file hay số lượng
trong manifest. Giữ bản source và các take bị loại; ghi lỗi và sửa đúng stage.

| Chỉnh sửa | Phạm vi phải kiểm/dựng lại |
|---|---|
| Tóc, nón, kính, material | Module đó và các render/export sử dụng nó; kiểm occlusion/attachment |
| Áo/quần/giày | Module đó, skinning/deformation/contact liên quan và render/export bị ảnh hưởng |
| Pose/động tác | Action và shot sử dụng nó khi rig contract còn đúng |
| Topology | Weights, shape keys, UV/bake/LOD phụ thuộc vào vertex/order/surface đã đổi |
| Surface/kích thước/pivot/scale | Collider sinh từ geometry và export/runtime test phụ thuộc phải kiểm lại; chỉ đổi vertex order, giữ nguyên surface/transform thì collider không nhất thiết đổi |
| Skeleton/rest pose | Binding, constraints, Actions/retargeting và module bám xương liên quan |
| Collider/LOD | Export/runtime test liên quan; giữ source high-detail |
| Caption, nhạc, SFX | Hậu kỳ; giữ geometry, rig, Action và render Blender |

Không đổi topology sau khi làm shape keys mà vẫn gọi keys cũ là hợp lệ. Giữ vertex
order/contract hoặc chuyển và kiểm deformation. Đổi material không tự thay tuổi,
mặt hoặc silhouette nhân vật. LOD/proxy có mức chất lượng riêng; không dùng proxy
làm source mới rồi mất high-detail model.

## Geometry, texture và module thật

Kiểm phần nền/sàn bị sinh kèm, mặt thừa, self-intersection, normals, tỷ lệ, hands,
mắt/miệng và các bộ phận cần chuyển động. Tối ưu dựa vào vùng quan trọng và góc
nhìn, không dùng một tỷ lệ Decimate cố định cho mọi asset. Render so cùng camera
trước/sau; silhouette, khuôn mặt và ngón tay là vùng kiểm riêng. Decimate không
chứng minh đã có edge loops tốt cho biến dạng.

UV unwrap/bake thật, texture có đường dẫn tương đối/đóng gói đúng, record màu không
gian màu theo loại map và cách material dùng chúng. Baked shadows/highlights từ
ảnh có thể làm sai ánh sáng trong game; kiểm trong light rig khác. Ảnh đẹp dán
lên mesh không tự tạo PBR, mắt/miệng hay topology mặt khuất.

Module là object/collection/material/bone binding thực theo contract: socket,
local transform, shared skeleton/rest pose, material slots, dependency version.
Nhân vật thay áo/tóc cần có body/head hợp lệ dưới phần tháo được, không lỗ hoặc
phần dính từ mesh gộp. JSON khai báo `hair/top/hat` không chứng minh đã tách chúng.
Đạo cụ có part tháo/lắp dùng nguyên tắc tương tự; giữ pivot/contact chức năng.

## Rig, biểu cảm và Action

Chọn anatomy/rig theo asset. Với người: body/root, tay/chân, fingers/thumbs, gaze,
jaw/lids và facial controls cần cho diễn xuất. Kiểm weights ở tư thế cực trị và
tay cầm đạo cụ; không gắn auto-weights rồi coi là đạt. Bộ icon chỉ là tham chiếu
diễn xuất, không thay shape keys/visemes/control rig.

Mỗi Action có ID, frame/FPS, rig version, contact frames, loop/root-motion policy
và clip render kiểm. Chọn idle/walk/sit/grasp/pour hoặc động tác theo dự án;
không áp tất cả động tác cho mọi vật thể. Kiểm chân chạm đất, cổ tay/ngón tay,
vật cầm giữ/thả và gaze. Tên Action hay `rigged:true` không phải evidence.

## Bối cảnh và game

> **Applies to: out of scope until a user decision (game is not a domain).** Scene-assembly ideas (instances, grid/pivot) may still inform `jenniejoy_cartoon_3d` sets; LOD, collider, navmesh and engine export may not be started.

Tách thư viện source asset khỏi scene assembly; dùng instance/linked data khi
muốn dùng chung có chủ đích. Cần sửa riêng một instance thì tạo variant thật,
không vô tình sửa mọi bản sao. Modular environment ghi kích thước tile, grid,
pivot/snap, orientation, material palette và seam/doorway checks.

LOD budgets, texture resolution/material count và draw calls phải theo nền tảng
và cảnh thực; không có một số polygon tối ưu cho mọi game. Tách high-detail,
render/game mesh, các LOD và collider. Collider cần đơn giản, đúng loại va chạm
và kiểm với nhân vật/physics thật. Navmesh, lightmap UV, streaming/chunking hoặc
root motion chỉ cấu hình khi engine/game yêu cầu.

Giữ editable `.blend` và source texture/rig/Actions. Xuất GLB/FBX hoặc format
đích phù hợp, record exporter options, units/axis/time mapping. Không tự quay
toàn scene để chữa khác hệ trục; kiểm export/import thực. Mở lại saved `.blend`
và nhập export vào scene sạch; so scale/pivot/material/bones/weights/Actions.
Sau đó thử trong engine đích: animation, collisions, modules, camera và profiling.
Import thành công trong Blender không phải bằng chứng game chạy tốt.

Manifest mẫu: [reusable-asset.template.json](../assets/reusable-asset.template.json).
Output chưa tạo giữ `null`/`planned`, không điền đường dẫn/hash hay kết quả đo giả.
Xuất asset không đồng nghĩa đã tạo xong game hoặc phim.

## Hai đường vào ComfyUI và script tự động

- **Ảnh render**: Blender tạo PNG/EXR từ scene/camera/frame đã ghi. LoadImage hoặc
  BlenderInputLoadImage nạp ảnh; ghi image hash, scene/asset hash, camera, frame,
  color space và prompt ID/output. Kiểm pixel roundtrip riêng với kiểm inference.
- **Asset 3D**: GLB/BLEND thật được loader/renderer đọc và tạo geometry trong Blender
  hoặc backend phù hợp. Ghi riêng asset hash, importer, scene inventory, render
  recipe, ảnh đầu ra và import/render receipt. BlenderInputLoad3D chỉ trả path;
  path qua node hay PNG roundtrip chưa chứng minh đã đọc mesh.

Để ComfyUI điều khiển Blender tự động, dùng node gọi script tin cậy qua Blender
background process, scene làm việc riêng, input có cấu trúc và output/receipt
theo job. Không nhận Python tùy ý từ prompt/node. Bản BLEND có camera/Action thật
có thể xuất chuỗi frame; model AI tiếp tục dùng ảnh/sequence đã render qua socket
đúng schema. Không nói model ảnh/video trực tiếp điều khiển bpy nếu chưa có cầu nối
như vậy. Các shot cần hình học/chuyển động chính xác giữ render Blender làm nguồn;
denoise thấp/seed cố định vẫn không bảo đảm AI giữ mọi chi tiết.

Vật dụng từ vựng có asset ID, term IDs, mô tả hình dáng/vật liệu đầy đủ, reference
bindings, recipe tham số, mesh/module thực, file chỉnh sửa, GLB, PNG render riêng,
camera/light/frame, hashes và QA. Nhiều term được phép dùng chung ly/nội dung sữa
với variant đã ghi; không nhân bản nguồn không cần thiết. Render icon không có
nghĩa vật thể đã đạt chất lượng cận cảnh hay game runtime.

Mỗi stage ghi `execution_location` và nguồn online/offline. Blender/ComfyUI chạy
local không biến cào web, cloud image generation hay online TTS thành offline.
