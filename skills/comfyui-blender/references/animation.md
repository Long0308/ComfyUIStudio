# Phim hoạt hình cá nhân hóa

**Applies to:** `jenniejoy_cartoon_3d` (Alice/JennieJoy). Không dùng cho `newtecons_live_action` (phim người thật: Blender chỉ làm previz bố cục/camera bằng proxy, xem `SKILL.md` mục Domain routing) hay `aec`.

## Vai trò Blender trong pipeline hiện có

Blender cung cấp bố cục, camera, staging, rig/pose, ánh sáng và control passes. ComfyUI thực hiện phần sinh/chỉnh ảnh hoặc video mà workflow đã hỗ trợ. VoiceStudio và công cụ hậu kỳ của dự án giữ vai trò âm thanh, subtitle và edit. ~~Không biến phim preschool 2D thành phong cách 3D bóng chỉ vì nguồn dựng ở Blender.~~ **[Đính chính 2026-10-27: câu gốc "preschool 2D" là chữ cũ; JennieJoyKids hiện là `jenniejoy_cartoon_3d`, hoạt hình 3D điện ảnh cách điệu, theo `create-video-jenniejoykids/SKILL.md`. Điều còn đúng: nguồn dựng Blender không quyết định phong cách, cast đã duyệt quyết định hình dạng; graybox/beauty pass của Blender chỉ là hình điều khiển, không bao giờ là ảnh storyboard cuối.]**

Chọn mức điều khiển theo shot:

- Ảnh neo/storyboard: dựng blocking, render beauty và control, sinh một keyframe để kiểm tra danh tính/bố cục.
- Chuyển động cần độ chính xác: keyframe/rig trong Blender, dùng frame sequence làm căn cứ; chọn workflow video/conditioning có thật. Đừng giả định render độc lập từng frame sẽ nhất quán.
- Chuyển động sinh tự do: ảnh/reference + workflow video đã được xác minh. Giữ camera/điểm bắt đầu rõ ràng và đánh giá mức trôi danh tính theo từng take.

## Hợp đồng nhân vật và shot

Mỗi nhân vật có identity ID, mô tả đầy đủ, ảnh nguồn, role của từng ảnh, trạng thái duyệt và phạm vi áp dụng. Phân tách face/wardrobe/gesture; ảnh gợi ý động tác không được đổi trang phục. Không ghi ảnh chưa xem hoặc chưa tạo thành approved.

Với Alice/JennieJoy, đọc local-profile và bible của tập. Nhân vật mới dùng hồ sơ của chính họ; không kế thừa váy, giọng hoặc gia đình của Alice. Identity lock giữ hình học khuôn mặt, silhouette, màu, trang phục và dấu bất đối xứng; biểu cảm/nhìn/chớp mắt/phoneme/tư thế vẫn được diễn xuất.

Mỗi shot ghi:

| Trường | Ý nghĩa |
| --- | --- |
| scene_id / shot_id | Khóa liên kết scene/workflow/output |
| characters / reference_bindings | Toàn bộ nhân vật thấy trong khung; role, path và status ảnh |
| start / duration / fps | Timeline dự kiến; đo lại clip thực sau render |
| camera / frame_range | Camera, lens, framing và các frame nguồn Blender |
| action_beats / dialogue | Hành động nhân quả và người nói đúng thời điểm |
| entry_state / exit_state | Vị trí, tay/đạo cụ, gaze, trang phục, ánh sáng |
| controls / workflow / models | File control, schema, workflow và weights chính xác |
| take / prompt_id / outputs / review | Bằng chứng chạy và quyết định chọn take |

Trong prompt mỗi shot, mô tả đầy đủ các nhân vật xuất hiện; tên/ID/reference tag không thay mô tả. Giữ source references bất biến, các turnaround/expressions mới là derived assets cần duyệt.

## Continuity và âm thanh

Seed cố định hỗ trợ tái lập trong cùng cấu hình, không đảm bảo danh tính giữa shot. Dùng reference đúng role, bố cục/camera nhất quán, pose/depth/lineart nếu workflow hỗ trợ, rồi kiểm tra frame thực.

Hard-carry chỉ áp dụng khi hai shot liên tục về không gian/hành động: lấy ảnh cuối **được dùng trong bản dựng đã chấp nhận** làm điểm bắt đầu tiếp theo; lưu actual frame index, kích thước và hash. `Frame 119` chỉ đúng cho đoạn 120 frame tương ứng; không áp dụng máy móc cho clip có duration/FPS khác hoặc cut sang góc máy mới. Không ép carry khi transition đã chủ đích thay cảnh.

Audio canonical lấy từ VoiceStudio/project. Không gửi tên vai `Alice:`/`Mother:` vào câu TTS; speaker metadata nằm riêng. Khóa speech windows theo nhân vật, kiểm tra miệng người không nói và không giữ trùng generated speech + VO. Bridge upstream không tự cung cấp lipsync.

Subtitle/logo/chữ giáo dục chính xác nên ghép ở hậu kỳ; giữ vùng trống đã quy định trong composition. Với JennieJoy giữ caption Anh/Việt và đường dẫn output hiện có; không áp quy định đó cho các domain khác.

## Review trước batch

Chọn một shot đại diện cho mặt nghiêng, tay/đạo cụ và thoại nếu có. Xem đầu/giữa/cuối, kiểm tra nơ đúng phía giải phẫu, tỷ lệ mặt, trang phục, chân chạm đất, số chi, cử chỉ, nhép miệng, camera và nối shot. Kiểm tra thêm vùng chuyển động mạnh hoặc cut; ba frame riêng lẻ không đủ kết luận video không flicker.

Lưu bản thử và kết quả đo. Chỉ tăng số shot/resolution khi take đại diện đạt yêu cầu thực. Upscale làm tăng kích thước ảnh, không chứng minh đã sửa trôi danh tính, sai động tác hoặc lỗi miệng.
