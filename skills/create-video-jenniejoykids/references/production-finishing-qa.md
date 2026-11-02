# Kiểm trước khi xuất phim theo lô

Áp dụng khi nối asset đã sinh vào hậu kỳ hoặc sửa icon, bản dịch và SFX. Kiểm
trước render giúp phát hiện lỗi dữ liệu; việc nghiệm thu vẫn dựa trên phim xuất
thật, giọng/khẩu hình và âm thanh đã kiểm. Không hứa mọi video theo lô sẽ không lỗi.

## Ảnh từ asset 3D phải đi vào bộ dựng

Có GLB/PNG trong thư viện chưa chứng minh ảnh xuất hiện trong phim. Khi người dùng
chọn học liệu 3D, dùng `vocabulary_art_mode=blender_render`. Nạp manifest qua
`POST /api/vocabulary/art/register` với `manifest_path` tuyệt đối. Manifest có
`assets[]`, mỗi item gồm `term`, `asset_id`, `full_description`, `geometry`,
`geometry_sha256`, `render.path`, `render.sha256`, `render.receipt`.
Receipt phải trỏ đúng hash geometry và PNG đầu ra; PNG phải giải mã được.

Engine sao chép ảnh theo hash vào `assets/vocabulary-3d/`, lưu prompt/provenance
và gắn ảnh vào intro nếu dùng từ đầu, icon cạnh phụ đề, spotlight trong cảnh và
từng thẻ cuối phim. Thiếu từ, hash đổi hoặc bộ từ trùng phải dừng; không thay ngầm
bằng SVG. SVG chỉ dùng khi đó là chế độ học liệu đã chọn. Nhân vật vẫn phải có
full description + canonical/reference/hash ở từng shot theo character library.

Kiểm ảnh ở cảnh có từ tương ứng và đủ từng thẻ outro từ file Master; không dùng
gallery hay ảnh preview của thư viện làm bằng chứng rằng phim đã ghép ảnh.
Raster render của vật dụng 3D là học liệu trong hậu kỳ, không có nghĩa nhân vật
đã có rig hoặc toàn bộ phim được render bằng Blender.

## Nghĩa ôn bài chỉnh riêng

Studio **Bước 5 → Minh họa 3D và nghĩa tiếng Việt · Ôn bài cuối phim** hiển thị
ảnh + từng từ + ô nghĩa. Bấm **Lưu nghĩa ôn bài** rồi xuất lại. API
`POST /api/outro/translations` nhận `translations` đủ các khóa từ được chuẩn hóa
chữ thường, dấu câu thành khoảng trắng; giá trị không rỗng, tối đa64 ký tự.

Engine lưu `outro_translations` riêng. Manifest dùng `outro_vi`; không ghi đè `vi`
của curriculum hoặc `dialogue_vi` của shot. Một nghĩa outro đổi chỉ dựng lại thẻ
đó, giữ hình cảnh, tiếng thoại và clip H3. PNG đổi thì dựng các phần thực dùng nó;
cache phải băm byte ảnh, không chỉ đường dẫn. Đổi mã compositor có thể cần dựng
lại toàn bộ hậu kỳ một lần; không sinh lại native.

## SFX theo frame và mẫu âm thanh thực

Nạp qua `/api/effects/register`: `source_path` stem WAV, `cue_sheet` JSON và `gain`.
SFX mới cần cue sheet, không lấy sự tồn tại của nhạc/âm native đã mute làm bằng chứng.
JSON gồm `fps:30`, `sample_rate:48000`, `mix_rule:"pcm16-additive-v1"`,
`timeline_sha256`, `stem_sha256`, `events[]`. Mỗi event có:

- `cue_id` duy nhất, `shot_id` (hoặc `outro`), `start_frame`, `duration_frames`.
- `clip_sha256` của clip đã chọn đối với cue trong cảnh; `action_note` về hành động.
- `source_path`, `source_sha256`: WAV PCM16 stereo48k đã trim, fade và chỉnh gain,
  đúng `duration_frames × 1600` mẫu mỗi kênh. Gain từng cue đã nằm trong WAV.
- Lưu nguồn/license, trim và contact-frame evidence khi thiết kế Foley.

Engine xác minh **từng mẫu stem bằng tổng cộng cue WAV**, kể cả3s intro và thời
lượng các shot trước. Không normalization/limiter ngầm; cộng gây clipping phải
giảm nguồn cue. Stem câm/lệch vị trí không được qua chỉ vì từng file có hash đúng.
Cue, stem, clip hoặc timeline đổi phải dựng/nạp lại. Nguồn cue được stage vào
`audio/effects/sources/`; cue sheet lưu cạnh stem và được băm trong production digest.

Xem hành động thật trước khi đặt cue: tiếng rót kết thúc cùng dòng sữa; khăn lau
mặt cần tiếng vải mềm nhỏ theo tiếp xúc, không hiss dài hay tiếng lau kính. Kiểm
thêm nghe thử; sample integrity không xác nhận cảm giác âm thanh phù hợp.

## Lệnh kiểm theo lô

Từ workspace, với Studio5050 đang chạy:

```powershell
python -X utf8 production-local/studio-app/batch_preflight.py --episodes 03-drinking-milk --require-3d --require-sfx --output production-local/JennieJoyKids-Story/03-drinking-milk/qa/production-preflight.json
```

Truyền nhiều mã tập sau `--episodes`. Cờ yêu cầu3D/SFX dùng cho lô cần các lớp
này. Lệnh không submit H3/Blender; mã thoát khác0 nếu tập bị chặn. Report ghi hash
hiện hành, số phần dùng lại/cần dựng và phạm vi kiểm. Giữ cả report lỗi để sửa,
không sửa report thành passed thủ công. Trước khi render, kiểm đủ native đã chọn,
ảnh đúng bộ, nghĩa đầy đủ, tiếng đúng lời/giọng, cue/stem, file đầu vào giải mã được.

Xuất tên `JennieJoyKids-<ma-hoac-ten-tap>-Master-1080p-vNNN.mp4` vào
`production-local/JennieJoyKids-Story/<episode>/comfyui-out-render/`.
Draft/Intro có role và độ phân giải tương ứng; không dùng hash job làm tên phim.
Version không ghi đè file cũ, kể cả tên khác hoa/thường trên Windows.

Sau render: full decode, probe độ phân giải/FPS/48k stereo/thời lượng, kiểm hình
thật của icon/caption/card, kiểm cue/mix, nghe giọng và đối chiếu môi. Receipt
nghiệm thu phải gắn hash Master mới; test code hoặc preflight không cho phép tự
đánh dấu9/9 phát sóng. Model nâng nét cũng cần so cùng crop/frame, giữ mặt, màu,
chữ và độ ổn định theo thời gian; output1080p riêng không chứng minh phục hồi chi tiết.
