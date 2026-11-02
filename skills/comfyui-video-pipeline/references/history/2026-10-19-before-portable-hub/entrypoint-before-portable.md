---
name: comfyui-video-pipeline
description: "Điều phối video AI local bằng ComfyUI, Blender và hậu kỳ Remotion với nguồn/hash, carry và QA; hỗ trợ chỉnh từng lớp. Nguồn cào web/TTS online được ghi riêng."
---

> **GPU hiện hành: RTX5080 16GB, đã lắp/kiểm18/10/2026.** Các đoạn5070/12GB
> bên dưới là baseline lịch sử. Dùng smart-memory, đo VAE tile theoVRAM thực;
> NVENC dành mã hóa video, OptiX cho Blender bake/render. Không giới hạn máy theo
> card cũ. Nguồn đo: `docs/handoffs/rtx5080-video-vae-tuning/comparison.json` và
> launcher `production-local/Start-JennieJoyStudio.ps1` trong workspace.

> **QA hậu kỳ và sản xuất theo lô:** đọc [binding ảnh 3D, sửa nghĩa ôn bài tại Bước 5, cue/stem SFX và preflight](../create-video-jenniejoykids/references/production-finishing-qa.md). Khi chọn ảnh từ asset 3D, bộ dựng phải nhận đúng PNG/hash ở cảnh và từng thẻ; không tự fallback SVG. SFX cần nguồn cue và stem khớp từng mẫu. Kiểm code không thay nghiệm thu phim thật.



> **Blender + AI local mở rộng:** đọc [ảnh/asset 3D → Blender script → H3](../create-video-jenniejoykids/references/blender-local-ai.md). Nối node renderer thật cho GLB/packed BLEND; ảnh render làm reference/first-frame cho H3. Asset từ vựng và mỗi stage có recipe/hash/receipt riêng. Canonical/full prompt vẫn bắt buộc; AI không bảo đảm giữ mọi chi tiết geometry. Cào nguồn dùng mạng, inference và nguồn TTS/imagegen ghi riêng.

# 🎬 COMFYUI LOCAL VIDEO PRODUCTION PIPELINE (E2E)

> **VoiceStudio + app5050 và thử model mặt:** đọc [contract thư viện vai/giọng và kết quả thực](../create-video-jenniejoykids/references/voicestudio-role-library.md). App5050 điều phối sản xuất; API VoiceStudio8080 sở hữu profile/TTS; ComfyUI8188 sở hữu H3/SeedVR2. Đã có giọng Ba, bốn ứng viên Mẹ, trẻ em và các nguồn dẫn chuyện; sáu biến thể Alice cũ được tách riêng. Pipeline ứng viên là `WAV đã chọn → sửa nhép theo WAV → nâng nét → caption theo WAV → dựng bản kiểm`. Không tuyên bố SeedVR2/FlashVSR sửa khẩu hình hoặc model7B tốt hơn3B khi chưa kiểm artifact.

> **3D mô-đun và trạng thái thật:** Bộ3D dùng lại phải có geometry/UV/material/rig/weights/shape keys và module thay được thật; icon/GLB thô không hoàn thành yêu cầu. Đồ thị từng stage và trạng thái Mẹ/Alice hiện tại nằm tại `production-local/JennieJoyKids-Story/03-drinking-milk/assets3d/approved-cast-v3/modular-pipeline.json`. Đổi tóc/áo chỉ dựng module và shot phụ thuộc; sửa caption/SFX chỉ hậu kỳ.

> **Chỉnh từng phần, không chạy lại toàn bộ H3:** đọc [pipeline mở rộng và cache theo lớp](../create-video-jenniejoykids/references/incremental-pipeline.md). Thiếu icon/subtitle sửa nhánh hậu kỳ; nhạc/SFX phối riêng. Workflow phụ bắt đầu bằng LoadVideo/LoadImage/LoadAudio của artifact đã lưu, không nối upstream H3 chỉ để hậu kỳ. Studio Bước5 có plan cache, tạo graph phụ và nạp output từng lớp.

> **Sửa phim Sữa sau khi người dùng xem draft:** [yêu cầu icon trong shot, outro từng thẻ lớn, đúng giọng Mẹ, nhạc nhẹ khác và SFX thực](../create-video-jenniejoykids/references/milk-revision-v2.md). Bắt buộc kiểm file render; chữ tô màu không thay icon, native audio đã mute không cung cấp SFX. Bản76s đầu bị yêu cầu sửa, không được ghi là đã duyệt. Người dùng yêu cầu sửa và xuất1080p trực tiếp cho phiên bản này.

> **Bộ nhân vật và biểu cảm dùng lại:** [quy tắc prompt đầy đủ + thư viện icon](references/character-icon-library.md), tại `D:/23.JennieHomeSchool/guilineicon`. Tên file `alice-<expression>` / `mom-alice-<expression>`. Mỗi icon/shot có JSON đầy đủ nhân vật, bối cảnh, diễn xuất và ảnh tham chiếu/hash; không dùng PNG thay toàn bộ mô tả. Mẫu Sữa hiện hành là cinematic stylized 3D, Alice bob đen nâu, mái thẳng, nơ bên phải giải phẫu. Giữ nguyên mặt khi đổi module tóc/trang phục/nón/kính theo yêu cầu.

> Studio production API and measured UAT: [operating contract](../create-video-jenniejoykids/references/studio-production-api.md). Keep current evidence gates; workflow/template existence is not a finished episode.


Khi dùng Blender để bố trí camera/nhân vật hoặc xuất beauty, depth, lineart và mask cho ComfyUI, đọc [comfyui-blender](C:/Users/Admin/.codex/skills/comfyui-blender/SKILL.md). Skill đó bổ sung điều phối hai MCP và kiểm tra bridge; dùng hướng dẫn AEC riêng cho kiến trúc/kết cấu/MEP/thi công, không áp preset JennieJoy của tài liệu này sang AEC.

> 🔗 **LIÊN KẾT ĐỒNG HÀNH BẮT BUỘC VỚI CREATE-VIDEO-JENNIEJOYKIDS:**
> Skill này là cánh tay thực thi sinh video trên phần cứng nội bộ RTX 5070 của [create-video-jenniejoykids](../create-video-jenniejoykids/SKILL.md). Mọi kịch bản (Intro Banner, Phân cảnh nội dung động, Outro Vocabulary), cấu trúc dữ liệu JSON, giao diện Studio App 5 bước (`http://localhost:5050`) và tổng hợp hậu kỳ Remotion phải tuân thủ nghiêm ngặt quy chuẩn của `create-video-jenniejoykids`.

> 🔴 **NGUYÊN TẮC BẮT BUỘC 100% CÓ PHỤ ĐỀ (CAPTIONS MANDATORY):**
> Trong mọi bản xuất Remotion Full HD (`defaultProps: {captions: true}`), bắt buộc 100% phải bật phụ đề tiếng Anh chữ chạy động nhép miệng (kinetic word-by-word highlight) kèm phụ đề tiếng Việt mờ ở dưới. CẤM xuất bản không có phụ đề!

> 📁 **QUY CHUẨN THƯ MỤC LƯU VIDEO MASTER BẮT BUỘC:**
> Toàn bộ video thành phẩm Master 1080p sau khi render BẮT BUỘC phải lưu vào thư mục:
> `production-local/JennieJoyKids-Story/{topic}/comfyui-out-render/`
> (Thay thế hoàn toàn cấu trúc cũ `master-renders` hay `episodes/`).

---

## 0. QUY TRÌNH VẬN HÀNH 5 BƯỚC TRÊN STUDIO APP (`http://localhost:5050`)

Studio App (`http://localhost:5050`) được thiết kế theo chuẩn UI 2 cột cao cấp (lấy cảm hứng từ Untitled UI):
- **Cột bên trái (Step Wizard Sidebar - 330px)**: Thanh tiến trình 5 bước có thể thu gọn `< / >` thành icon bar. Mỗi khi hoàn thành bước nào, vòng tròn số thứ tự chuyển thành màu xanh lá với dấu tick `✔` và xuất hiện nút chuyển tiếp `Tiếp tục ➔`.
- **Cột bên phải (Workspace Main Area)**: Toàn bộ không gian làm việc chuyên biệt theo từng bước.

```
┌─────────────────────────────────┬────────────────────────────────────────────────────────┐
│ 🧭 BƯỚC QUY TRÌNH (Collapsible) │ 🖥️ KHÔNG GIAN LÀM VIỆC THEO TỪNG BƯỚC                  │
│ [✔] 1. Cấu hình & Từ Vựng       │ ➔ Bước 1: Quản lý từ vựng, thêm/sửa/xóa, sinh kịch bản │
│ [✔] 2. Kịch Bản & Phân Cảnh     │ ➔ Bước 2: Storyboard linh hoạt, keywords nhấn nhá      │
│ [✔] 3. VoiceStudio & Nhép Miệng │ ➔ Bước 3: Lọc tiền tố thoại, kiểm soát diễn xuất S06B  │
│ [✔] 4. ComfyUI Video Render     │ ➔ Bước 4: Review Gate ảnh neo, Frame 119, MiniMax H3   │
│ [✔] 5. Remotion Master 1080p    │ ➔ Bước 5: Player 1080p, xuất file vào comfyui-out-render│
└─────────────────────────────────┴────────────────────────────────────────────────────────┘
```

### Bước 1: Cấu Hình Dự Án & Giáo Trình Từ Vựng Mục Tiêu
1. **Quản lý từ vựng linh hoạt**:
   - Giao diện cung cấp danh sách từ vựng trọng tâm bài học (gồm Từ tiếng Anh, Phiên âm IPA, Nghĩa tiếng Việt).
   - Thao tác trực tiếp: Bấm `+ Thêm Từ Vựng` để thêm từ mới, bấm `✏️ Sửa` để chỉnh sửa, bấm `✕ Xóa` để xóa từ.
2. **Nút "✨ Tự Động Sinh Kịch Bản & Cập Nhật Video"**:
   - Khi bấm nút này, hệ thống tự động quét danh sách từ vựng hiện hành và đối chiếu với thoại của toàn bộ các phân cảnh trong kịch bản.
   - Tự động gắn các từ vựng tìm thấy vào trường `target_keywords` của từng phân cảnh để Remotion tự động in đậm highlight.
3. Bấm **`Tiếp tục ➔ Bước 2: Kịch Bản & Phân Cảnh`** để chuyển bước.

### Bước 2: Kịch Bản & Phân Cảnh Storyboard Động (Dynamic Scenes)
1. **Storyboard linh hoạt - Không cố định 12 khung hình**:
   - Tùy theo độ dài kịch bản (teaser 20s = 4 shot, bài học tiêu chuẩn 60s = 12 shot, bài mở rộng 90s = 16 shot), storyboard tự động hiển thị số lượng phân cảnh thực tế.
   - Hỗ trợ thêm/xóa phân cảnh: Bấm `+ Thêm Phân Cảnh` để bổ sung shot mới, bấm `🗑️ Xóa Phân Cảnh` để rút gọn.
2. **Trường `🎯 Keywords Cần Nhấn Nhá Trong Câu`**:
   - Khi bấm `✏️ Chỉnh Sửa Phân Cảnh`, modal chỉnh sửa cung cấp trường nhập `🎯 Keywords Cần Nhấn Nhá Trong Câu`.
   - Các từ khóa này được Remotion dùng làm căn cứ để nhảy chữ lò xo và highlight màu hồng pastel `#FF2E7E` trên phụ đề động (Kinetic Text Highlight).
3. **Phê Duyệt Storyboard & Khóa Kịch Bản**:
   - Bấm nút `Phê Duyệt Storyboard & Khóa Kịch Bản` để xác nhận bố cục, hành động và tạo Review Gate trước khi render video.
4. Bấm **`Tiếp tục ➔ Bước 3: VoiceStudio TTS`** để chuyển bước.

### Bước 3: VoiceStudio TTS & Nhép Miệng Chuẩn Xác
1. **Quy tắc lọc sạch tiền tố thoại (Zero Speaker Prefix)**:
   - Khi gửi câu thoại sang mô hình TTS (EdgeTTS / VoiceStudio), **BẮT BUỘC LỌC BỎ HOÀN TOÀN** các tiền tố như "Mother:", "Alice:", "[Mẹ]:", "[Alice]:".
   - Chỉ truyền chuỗi văn bản thoại nguyên chất (`speech_text`). Nếu để sót tiền tố, AI sẽ đọc to tên nhân vật, gây sai lệch khẩu hình (lip-sync drift) và vỡ nhịp video.
2. **Phân vai rạch ròi - Tránh nhép chéo**:
   - Alice nói riêng với âm sắc bé gái mầm non 2 tuổi (`pitch: +4Hz, rate: +0%`).
   - Mẹ nói riêng với âm sắc dịu dàng, ấm áp mầm non.
3. **🔴 QUY TẮC BẮT BUỘC CỦA PHÂN CẢNH KẾT THÚC (S06_B)**:
   - **Bé Alice phải là người mở mắt to tròn mỉm cười nói trước**: "Goodnight, Mommy... Sweet dreams...".
   - **Mẹ ngồi bên cạnh mỉm cười dịu dàng vuốt tóc bé, miệng Mẹ khép hoàn toàn**: Tuyệt đối **KHÔNG ĐƯỢC ĐỂ MẸ NHÉP MIỆNG THEO CÂU THOẠI CỦA ALICE**!
   - **Sau khi Alice nói xong câu chúc ngủ ngon, Alice mới từ từ khép mắt ngủ ngoan**: Đèn ngủ mờ dần, chuyển cảnh kết êm ái.
4. Bấm **`Tiếp tục ➔ Bước 4: ComfyUI Video Render`** để chuyển bước.

### Bước 4: ComfyUI AI Video Render (Phần Cứng RTX 5070 Cục Bộ)
1. **Kết nối & Kiểm tra hệ thống**:
   - Trạng thái ComfyUI hiển thị Online tại `http://127.0.0.1:8188`, nhận diện card GPU NVIDIA GeForce RTX 5070.
2. **Quy luật frame cuối USED ➔ Frame 0**:
   - Trích đúng frame cuối thực dùng:119 cho5s/24fps,143 cho6s. Studio tạo nhánh editorial PNG-frame0 + generated frames1..last-used; lưu native AV riêng. Kiểm chuyển động và trang phục thật, không bảo đảm liên tục chỉ từ frame đầu hoặc cờ HTTP.
3. **Nút "Tự Động Kết Nối & Lấy Video Từ ComfyUI"**:
   - Tự động quét và nạp các shot video raw vừa sinh từ thư mục output của ComfyUI vào bảng kiểm duyệt.
4. **Nút "Giải Phóng VRAM / RAM"**:
   - Gửi yêu cầu `POST /free` (`{"unload_models": true, "free_memory": true}`) tới ComfyUI để giải phóng VRAM GPU RTX 5070 và kích hoạt Python GC dọn sạch bộ nhớ.
5. Bấm **`Tiếp tục ➔ Bước 5: Remotion Master 1080p`** để chuyển bước.

### Bước 5: Remotion Master 1080p Export & Kiểm Định Phát Sóng
1. **Trình phát video Master 1080p**:
   - Xem trước trực tiếp video hoàn thiện Full HD 1080p kèm âm thanh, nhạc nền, phụ đề nhép miệng và sticker đạo cụ.
2. **Nút tải file video Master**:
   - Tên file: `<series>-<ma-hoac-ten-tap>-<role>-<resolution>-vNNN.mp4`; ví dụ `JennieJoyKids-03-Drinking-Milk-Master-1080p-v003.mp4`.
   - Studio tự tăng phiên bản, giữ cả số đã dành cho job lỗi; không ghi đè hay dùng hash job làm tên phim. Role có thể là `Draft`, `Master`, `Intro-HyperFrames`.
3. **Bảng kiểm định phát sóng 7 tiêu chí**:
   - [ ] 1. Phụ đề kinetic highlight tiếng Anh + sub tiếng Việt dưới câu thoại.
   - [ ] 2. Không để nhãn tên nhân vật ("Mother", "Alice") trên màn hình video.
   - [ ] 3. S06_B: Alice nói xong mới ngủ, Mẹ khép miệng, kiểm theo video/tiếng thực.
   - [ ] 4. Sticker hoạt hình sạch tại khoảng trống, không che thao tác.
   - [ ] 5. Outro từ vựng có nhạc, không để Alice đọc theo.
   - [ ] 6. Logo JennieJoy Kids góc trên bên phải rõ, tách nền.
   - [ ] 7. Master được lưu đúng `production-local/JennieJoyKids-Story/{topic}/comfyui-out-render/`.
   Đây là checklist yêu cầu, không phải kết quả đạt sẵn. Bảng nghiệm thu Studio hiện có9 tiêu chí, cần artifact/hash đúng Master cho từng tiêu chí.

---

## 1. SO SÁNH COMFYUI NỘI BỘ VỚI CÁC CLOUD ENGINES

| Tiêu chí | ComfyUI Native (MiniMax H3 + SeedVR2) | Higgsfield / Haiper | Runway Gen-3 / Kling / Luma |
| :--- | :--- | :--- | :--- |
| **Chi phí** | GPU cục bộ, vẫn có chi phí điện/phần cứng | Tùy dịch vụ/gói hiện hành | Tùy dịch vụ/gói hiện hành |
| **Quyền riêng tư / IP** | **100% nội bộ**, không lọt dữ liệu ra ngoài | Dữ liệu tải lên server cloud | Dữ liệu qua cloud, nguy cơ lộ IP nhân vật |
| **Kiểm soát Continuity** | Có carry frame đầu; chuyển động sau đó cần kiểm thực tế | Kiểm theo từng pipeline/output | Kiểm theo từng pipeline/output |
| **Độ ổn định giải phẫu** | Bố trí3/4 giảm tình huống khó; vẫn có thể lỗi | Kiểm thực tế | Kiểm thực tế |
| **Đồng bộ âm thanh** | Có WAV guide/reference, chưa chứng nhận khớp môi | Kiểm thực tế | Kiểm thực tế |
| **Độ phân giải xuất** | Native 864×480 → **SeedVR2 Upscale 1080p/4K** | Bị nén bitrate, dính watermark gói free | 720p hoặc 1080p trả phí cao |

---

## 2. PHẦN CỨNG & MÔI TRƯỜNG THIẾT LẬP (SETUP)

### Phần cứng khuyến nghị
* **GPU**: NVIDIA RTX 4070 / 4080 / 4090 / 5070 (Tối thiểu 12GB VRAM).
* **RAM**: 32GB DDR4/DDR5.
* **Storage**: SSD NVMe (Tốc độ đọc > 3000MB/s cho model weights nặng).

### Danh mục Trọng số Mô hình (Model Weights Inventory)
Tất cả đặt trong thư mục `ComfyUI/models/`:
1. **UNet / DiT**: `minimax_h3_ref2va_pruned_int8_convrot.safetensors` (đặt tại `models/unet/`)
2. **Text / Vision Encoder**: `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (đặt tại `models/clip/`)
3. **Video VAE**: `minimax_h3_video_vae_int8_convrot.safetensors` (đặt tại `models/vae/`)
4. **Audio VAE**: `minimax_h3_audio_vae_fp32.safetensors` (đặt tại `models/vae/`)
5. **Upscaler**: `SeedVR2_3B_INT8.safetensors` (đặt tại `models/upscale_models/`)

### Khởi động Server ComfyUI & Studio App
- ComfyUI Server (`http://127.0.0.1:8188`):
  ```powershell
  python.exe main.py --port 8188 --listen 127.0.0.1 --windows-standalone-build
  ```
- JennieJoy Kids Studio App (`http://localhost:5050`):
  ```powershell
  python production-local/studio-app/server.py
  ```

---

## 3. BA QUY TẮC VÀNG CHO ANIMATION CHUẨN (GOLDEN RULES)

### Quy tắc 1: Khóa giải phẫu bằng "3/4 Tableau" (Triệt tiêu lỗi xoay cổ)
* **Nguyên nhân lỗi xoay cổ của AI**: Khi ép AI chuyển góc quay liên tục từ lưng (Rear View) sang mặt (Front View) trong một shot 5s, AI sẽ nội suy bằng cách vặn vẹo thân thể và xoay đầu 180 độ không tự nhiên.
* **Giải pháp dứt điểm**: Thiết lập **Tableau 3/4 chính diện** ngay từ Frame 0:
  * Cảnh Mẹ và Bé: Mẹ ở bên trái hoặc quỳ bên cạnh bé, Alice ở trọng tâm.
  * Nhân vật luôn nhìn thẳng hoặc nhìn nhau góc 3/4 thân thiện, hai chân chạm sàn chắc chắn (`grounded feet`), không bao giờ để nhân vật quay lưng rồi giật ngược mặt 180 độ.

### Quy tắc 2: Quy luật Hard-Carry "Frame 119 → Frame 0" (Seamless Continuity)
Để chuyển cảnh A sang cảnh B mượt mà không có cú nhảy (jump cut) làm đổi khuôn mặt:
1. Xuất frame cuối cùng của Scene trước (Frame 119 @ 24fps):
   ```powershell
   ffmpeg -y -i scene_A.mp4 -vf "select=eq(n\,119)" -frames:v 1 scene_A_f119.png
   ```
2. Nạp ảnh `scene_A_f119.png` vào Node 8 (`LoadImage`) của Scene B làm điểm neo Frame 0.
3. Studio hard-carry editorial bằng graph thực, giữ native AV riêng. Không coi HTTP flag hoặc input PNG là bằng chứng chuyển động đã nối đúng. Với shot6s lấy143; cảnh cut có lý do dùng anchor riêng.

### Quy tắc 3: Khóa danh tính nhân vật (Dual-Identity Anchoring)
Trong node `MiniMaxH3ReferenceToVideo`:
* **Slot 1 (`ref_image_0`)**: Ảnh bối cảnh/nhân vật người lớn (Mẹ: áo blouse dusty-teal, tóc hạt dẻ).
* **Slot 2 (`ref_image_1`)**: Ảnh chân dung Alice chuẩn đồ ngủ hồng hình tim trắng, nơ tóc bên phải.
* **Tuyệt đối không có Ba**: Trong toàn bộ các tập sinh hoạt mầm non giữa Mẹ và Bé, cấm đưa nhân vật Ba vào prompt hoặc reference.

---

## 4. HẬU KỲ CHUẨN PHÁT SÓNG QUA REMOTION (FULL HD 1080P @ 29.97/30FPS)

Sau khi ComfyUI render xong các raw clips, Remotion thực hiện hoàn thiện bản Master thương mại:
1. **Độ phân giải chuẩn giao khách hàng**: **1920x1080 Full HD**, 30fps (hoặc 29.97fps broadcast standard).
2. **Hiệu ứng chữ chạy Remotion (Kinetic / Karaoke Subtitle)**:
   * **LOẠI BỎ HOÀN TOÀN NHÃN TÊN "Mẹ (Mother)" VÀ "Bé Alice"**: Tuyệt đối không để chữ tên nhân vật trên màn hình video.
   * Chữ phụ đề động: Từng từ (word-by-word) nhảy lên theo nhịp lò xo (`spring({frame, fps, config: {stiffness: 220, damping: 11}})`).
   * **Từ vựng mục tiêu in đậm nổi bật**: Các từ nằm trong danh sách `target_keywords` tự động đổi màu hồng tím `#FF2E7E`, có pill nền pastel ôm trọn từ ngữ.
   * Phía dưới có sub tiếng Việt nhỏ hơn mờ nhẹ.
3. **Đạo cụ học tập minh họa & Icon Nhấn Từ Vựng (Vector SVG & Prop Stickers)**:
   * **TUYỆT ĐỐI KHÔNG DÙNG POLYGON MASK VẼ TAY**: Không vẽ đa giác neon thô cứng làm lệch hình và che khuất thao tác của nhân vật.
   * **HỆ THỐNG ICON VECTOR SVG KAWAII (`VocabIcons.tsx`)**: Tuyệt đối không dùng emoji hệ điều hành (tránh lỗi Chromium trên Windows hiển thị thành que gạch chéo màu đỏ `\`). Dùng SVG ở chế độ SVG; khi chọn ảnh render 3D phải gắn PNG/receipt/hash qua manifest, không thay ngầm bằng SVG.
   * **Nhấn nhá từ vựng kép (Dual-Layer Vocab Reinforcement)**:
     - 12 phân cảnh đều có Spotlight Callout Card nảy lên ở góc với icon to 64px và tiếng Việt.
     - Phụ đề Kinetic Subtitle bọc từ vựng trong pill hồng `#FF2E7E` kèm icon đúng bộ minh họa đã chọn.
     - Outro Review 10 từ vựng có ảnh đúng bộ minh họa đã chọn trên mỗi thẻ từ.
   * Sticker hoạt hình 2D bo tròn trong suốt (`prop_sticker_strawberry_tube.png`, `prop_sticker_cute_toothbrush.png`) xuất hiện với hiệu ứng spring bounce tại các khoảng trống thông thoáng.
4. **Nhạc nền mầm non ru ngủ (Lullaby BGM Ducking)**:
   * Nhạc lofi/ru ngủ êm ái, ducking tự động xuống -18dB khi nhân vật nói và đẩy lên -10dB ở các khoảng lặng.
5. **Logo thương hiệu bản quyền (Brand Watermark)**:
   * Chèn logo chuẩn JennieJoy Kids tại góc trên bên phải video:
     `d:\23.JennieHomeSchool\8.Image\littlelingo\public\images\logo-jenniejoy-kids.png`
   * Kích thước to rõ ràng (rộng ~180-200px trên bản 1080p), viền mềm pastel và bóng đổ nhẹ.
6. **Lệnh render Remotion Master xuất vào comfyui-out-render**:
   ```powershell
   npx remotion render src/index.tsx JennieJoyFinalEnglish "d:/23.JennieHomeSchool/03 Voice/production-local/JennieJoyKids-Story/02-bedtime-routine/comfyui-out-render/JennieJoyKids-02-Bedtime-Routine-Master-1080p-v001.mp4" --concurrency=2
   ```
   Lệnh trên minh họa tập mới; khi sản xuất dùng Studio để dành tên phiên bản trước render. Không chạy lại vào tên đã có.

---

## 5. CHECKLIST SẢN XUẤT MASTER 1080P CHUẨN

- [ ] 1. **Cấu trúc thư mục chuẩn**: Toàn bộ lưu trữ tại `production-local/JennieJoyKids-Story/{topic}/` với output video nằm trong `comfyui-out-render/`.
- [ ] 2. **Duyệt Storyboard động**: Bảng storyboard thể hiện đúng số lượng shot kịch bản, xác nhận đúng nhân vật (Mẹ + Bé, KHÔNG CÓ BA, đồ ngủ hồng tim trắng).
- [ ] 3. **Từ vựng & Keywords nhấn nhá**: Danh sách từ vựng được liên kết tự động vào các shot; keywords in đậm hồng `#FF2E7E` trên phụ đề.
- [ ] 4. **Duyệt Audio Thoại VoiceStudio**: File WAV sạch 48kHz, lọc sạch tiền tố "Mother:" / "Alice:", giọng bé gái 2 tuổi ấm áp (`pitch: +4Hz`).
- [ ] 5. **Kiểm soát diễn xuất cảnh cuối (S06_B)**: Alice mở mắt mỉm cười chúc ngủ ngon trước, nói xong mới nhắm mắt ngủ; Mẹ khép miệng vuốt tóc không nhép chéo.
- [ ] 6. **Chuyển thể Video ComfyUI**: Chạy batch các shot trên RTX 5070 với Frame 119 Hard-Carry và SeedVR2 upscale 1080p.
- [ ] 7. **Tổng hợp Remotion Full HD**: Gắn logo góc phải transparent, kinetic subtitle highlight từ vựng, sticker đạo cụ 2D nổi khối, nhạc nền ducking, outro từ vựng không kèm thoại bé.
- [ ] 8. **Kiểm tra xuất phẩm**: 1920x1080 @ 30fps, âm thanh 48kHz stereo, lưu tại `comfyui-out-render/`.

> **Bàn giao đổi GPU5070→5080:** xem `D:/23.JennieHomeSchool/03 Voice/docs/handoffs/2026-10-18-RTX5080-HANDOVER.md`. Đọc trạng thái job thật trước retry; giữ Python/model và kiểm GPU mới bằng probe. Không cài lại CUDA chỉ vì đổi card, không hứa cấu hình mới nhanh hơn bao nhiêu khi chưa đo.
