# Chỉnh sửa từng phần — Studio, ComfyUI, Remotion, HyperFrames

Yêu cầu người dùng: khi thiếu icon, phụ đề, giọng, nhạc hoặc SFX, sửa đúng lớp,
giữ phần đã sản xuất và thêm nhánh phụ trợ; không chạy lại toàn bộ workflow H3.
Đây là quy tắc hiện hành cho hai skill sản xuất và Studio. Không bỏ review/hash.

| Thay đổi | Phần phải dựng | Phần giữ lại |
| --- | --- | --- |
| Bản dịch / keywords một shot | Hình hậu kỳ của shot đó + ghép file | Native, các shot khác, âm thanh |
| Icon hoặc nội dung một từ vựng | Các shot dùng từ đó, thẻ tương ứng; intro nếu dùng icon đầu | Native và các phần không dùng từ đó |
| Giọng hậu kỳ, cùng thời lượng | Phối âm thanh + mux | Toàn bộ hình; vẫn cần kiểm khẩu hình |
| Giọng hậu kỳ, khác thời lượng | Hình phụ đề của shot đó + phối âm thanh | Native và các shot khác |
| Nhạc / SFX / gain | Phối âm thanh + mux | Toàn bộ hình đã cache |
| Scale / màu / mask một clip | Nhánh ComfyUI từ LoadVideo, rồi hình hậu kỳ shot đó | Native AV và chuỗi carry gốc |
| Prompt / ảnh neo / giọng conditioning / diễn xuất | Shot H3 bị đổi; kiểm các carry phụ thuộc | Các shot độc lập không bị ảnh hưởng |
| HTML/JSON/vendor của intro HyperFrames | Component intro đó | Native và Remotion độc lập |

Luồng artifact:

```text
ComfyUI H3 → native AV bất biến → clip được chọn
                                  ├→ LoadVideo → node xử lý phụ → video derivative
                                  └→ hình Remotion: intro / từng shot / từng thẻ
Giọng hậu kỳ + nhạc + SFX ───────────→ WAV phối riêng
Cache hình + WAV ───────────────────→ concat/copy video + AAC mux → Master
HyperFrames snapshot ───────────────→ component intro riêng có fingerprint
```

## Cách dùng trên app

Trong Bước5 mở **Chỉnh từng phần và mở rộng pipeline**:

1. Chọn1080p hoặc720p, bấm **Xem phần cần dựng lại**. Plan kiểm file/hash thật,
   không submit GPU. `BUILD` là cache chưa có/hết hợp lệ; `REUSE` là có artifact
   đúng recipe và SHA256. Plan chưa phải bằng chứng đã render/QA.
2. Sửa bản dịch, keywords, icon bằng các điều khiển hiện có. Thay giọng hậu kỳ,
   nhạc/SFX hoặc video xử lý bằng **Nạp phần đã chỉnh**. Không đổi giọng conditioning
   ở Bước3 khi chỉ muốn revoice hậu kỳ. WAV phải48kHz stereo.
3. Muốn thêm node ComfyUI: chọn shot và nhánh scale/frames rồi **Tạo workflow phụ trợ**.
   Tải JSON và mở trong ComfyUI; nối node xử lý giữa GetVideoComponents và CreateVideo.
   Graph đọc clip đã lưu, không chứa sampler H3. File được tạo chưa có nghĩa GPU đã chạy.
   Nhánh scale mặc định là Lanczos; không gọi đó là SeedVR2 hoặc phục hồi chi tiết AI.
4. Nạp video output vào lớp hình của shot. API giữ native/carry riêng, gắn derivative
   với hash clip gốc và kiểm thời lượng/fps/tỷ lệ. Nguồn đổi thì dừng, không fallback âm thầm.
5. Xuất draft/Master theo quyền đã có. Lần đầu tạo cache, lần sau chỉ dựng phần thay đổi.
   Kiểm artifact mới cùng frame nối, phụ đề, SFX và khẩu hình. Bản Sữa sửa có chỉ đạo
   xuất1080p trực tiếp, không ghi draft76s bị yêu cầu sửa là đã duyệt.

## API / dữ liệu

`POST /api/pipeline/plan` với `{"width":1920}` trả native statuses, visual segments,
audio status và số phần tái sử dụng. `POST /api/pipeline/auxiliary` với
`{"shot_id":"S01_A","mode":"scale"}` hoặc `"frames"` lưu graph và provenance.
`GET /api/pipeline/artifacts/<name>.api.json?episode_id=...` tải graph đúng tập.

`POST /api/picture/register` nhận `shot_id, source_path, method`.
`POST /api/editorial-audio/register` nhận `shot_id, source_path, text, engine, voice_id`;
`require_for_role:true` khóa provider/voice cho vai, thiếu override thì block.
`POST /api/music/register` và `/api/effects/register` nhận `source_path, gain`.
Stem SFX gắn timeline; đổi thời lượng cần dựng/nạp lại stem, tránh lệch sự kiện.

CLI (đường dẫn đầy đủ hoặc chạy từ `production-local/studio-app`):

```powershell
node finishing/render.cjs manifest.json output.mp4 1920 --plan --cache-dir=D:/episode/.finishing-cache
node finishing/render.cjs manifest.json output.mp4 1920 --cache-dir=D:/episode/.finishing-cache
node --test finishing/test_renderer.cjs finishing/test_incremental.cjs
```

Cache dùng hash nội dung file, recipe, renderer/font/package versions và độ phân giải.
Hình tách intro, mỗi shot và từng thẻ2s; audio WAV tách khỏi hình. Thay code renderer
có thể làm mất hiệu lực nhiều phần một cách bảo thủ. Mỗi hit kiểm SHA256 artifact.
Source compositor được snapshot trước bundle; media giữ bản staging và kiểm lại trước publish.
Output cache có receipt và metadata; output cuối ghi số phần `BUILT/REUSED`.
Khóa writer bảo vệ tác vụ còn sống; PID đã chết có thể phục hồi, không xóa khóa writer đang chạy.

Cache nằm trên đĩa, không phụ thuộc cache trong RAM của ComfyUI. Nối node vào graph H3
cũ khi runtime dùng `--cache-none` có thể chạy lại toàn bộ upstream. Dùng graph phụ
bắt đầu từ LoadVideo/LoadImage/LoadAudio thay vì nối ngược vào sampler đắt tiền.

HyperFrames hiện chỉ tạo component intro5s có cache nguồn riêng. Nó chưa tự được chèn
vào intro3s của Master Remotion; cần khai báo contract duration/alpha/timeline trước tích hợp.
Không đánh đồng output intro với phim hoàn chỉnh. Caption hỗ trợ `estimated` và
`asr`: đăng ký ASR/review qua `/api/captions/timing/register` với đúng text,
SHA/thời lượng WAV hiện hành và hash bằng chứng. Bảnphimv004 vẫn estimated,
chưa có binding ASR. Cả hai mode không chứng minh nhép miệng. 1080p container
không chứng minh SeedVR2 đã chạy.


## Bằng chứng đã chạy tại máy — 2026-10-18

-56engine +19Node tests pass; independent review không cònHIGH/MEDIUM.
- Phim Sữa84s/1920×1080/30fps/48k stereo xuất tại `comfyui-out-render/Master-1080p-8b803341e7d9.mp4`, SHA256 `c123857dbb15b45997778e5f685f4313acc035f64f872336b5faea82426e41fe`. Full decode exit0; inspected actual shot/icon/outro contact sheets. Lip/listening/broadcast acceptance chưa được chứng nhận.
- QA variant chỉ đổi SFX gain:23/23picture partsREUSED,0picture builds; compressed video packet SHA256 giống Master; audio khác.
- QA variant chỉ sửa bản dịchS01_A:22/23picture partsREUSED,1picture build; audioREUSED và compressed audio packet SHA256 giống Master. Hai variant decodeexit0, không thay phim công bố.
- Receipt chi tiết: episode `qa/incremental-verification.json`.
- Comfy auxiliaryfb15f76c completed9.9s;124frames24fps giữ nguyên,864×480→1944×1080Lanczos; `/api/picture/register` nhận output và12native takes vẫn hợp lệ.
- HyperFramesintro84ef38e3dd9a completed10.5s; gọi lại trảcached:true cùngjobID.
- HTTP SHA cache chỉ trong một request, dùng file identity và NTFSChangeTime thật trên Windows; regression same-size/restoredmtime đã kiểm. Không dùng ctimeWindows làm change time. `/api/episode` đo6329ms trước,4113/4246/4157ms sau; trước/sau khác tải render, không phải benchmark kiểm soát.

##3D cũng tách theo artifact

Giữ version riêng cho mesh gốc, retopology, UV/texture, skeleton, weights/shape keys, từng module ngoại hình và Action. Đổi tóc/áo chỉ cập nhật module và render shot sử dụng nó khi rig/attachment contract còn đúng. Đổi topology phải kiểm lại weights/shape keys. Caption/SFX không kích hoạt Blender. Hiện trạng3D mới nhất là `assets3d/approved-cast-v005/stage-manifest.json`: bodyFK/Actions prototype, production_ready:false; facialrig/visemes/IK và chất lượng deformation/art còn mở. v3 là nguồn lịch sử; geometry trung gian chưa được tính là actor sản xuất dùng lại.
