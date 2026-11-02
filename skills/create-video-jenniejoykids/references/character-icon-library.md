# Thư viện Mẹ & Alice — 2026-10-18

## Yêu cầu người dùng phải giữ qua các phiên

Thứ tự mới nhất người dùng chốt: HOÀN THÀNH VIDEO SỮA TRƯỚC, sau đó hoàn thiện Blender và tạo skill dùng chung để dựng các nhân vật khác. Skill mới phải nhận hồ sơ/reference của nhân vật mới, không hardcode Alice; có quy trình giữ nhận diện, module tóc/trang phục/nón/kính, góc nhìn/biểu cảm, mesh/rig và động tác tái sử dụng. Không chuyển GPU sang job3D trong khi phim còn chờ render. Các ảnh turnaround đã sinh là chuẩn bị nguồn, không phải hoàn thành Blender.

Skill dùng chung hiện đã tạo và kiểm cấu trúc/forward-test với nhân vật thầy giáo khác: [create-reusable-character](C:/Users/Admin/.codex/skills/create-reusable-character/SKILL.md). Nó mô tả quy trình và hợp đồng tài sản; không tuyên bố rig Mẹ/Alice đã hoàn thành. Bản đọc trên Studio ở `/api/character-library/files/guides/create-reusable-character/SKILL.md`. Sau khi sửa skill nguồn, cập nhật bản sao tài liệu web tương ứng.

Hoàn thiện engine/Studio/skill và sản xuất phim Sữa thật theo nguồn đã cào; UAT, concept hay intro không thay thế phim. Agent chuẩn bị ba ảnh Mẹ/Alice/bối cảnh rồi nạp đúng node, không hỏi lại đường dẫn đã có. Làm cả hai mẹ con cùng phong cách hoạt hình2D/3D đã chọn, giữ nhận diện, góc nhìn và biểu cảm nhất quán. Tạo tài sản có thể dùng lại: bộ biểu cảm riêng, turnaround/góc cạnh, cử chỉ/pose và về sau mesh/rig Blender có thể đổi tóc, trang phục, nón, kính. Chỉ đánh dấu phần nào thực sự có file và đã kiểm phần đó;24 PNG không hoàn thành toàn bộ yêu cầu3D.

UAT cần giữ nguồn để làm video hướng dẫn có con trỏ chuột nhìn thấy và subtitle thao tác trong cả Remotion lẫn HyperFrames. Mọi lỗi phát hiện phải có artifact, trạng thái và sửa/retest; không dừng ở báo cáo UAT. Cập nhật cùng yêu cầu vào cả hai skill và hướng dẫn trên web app, giữ tracker/handover để phiên sau tiếp tục đúng trạng thái.

Sao lưu toàn bộ ảnh gốc của task, kể cả bản bị thay thế, vào `J:/1.JennieHomeSchool/guilineicon/original-generated/`. Thư mục thực của công cụ trên máy là `C:/Users/Admin/.codex/generated_images/01a14cec-3bad-7bc1-89ee-cd8418899331`; người dùng có lần viết `generated/_images`, phải đối chiếu file thực, không bỏ sót hay xóa nguồn. `original-generated/index.json` giữ ánh xạ vàSHA256.

## Web app và engine hiện đã có

- Header: **Mẹ & Alice · Thư viện biểu cảm** → `/api/character-library/files/catalog.html`, hiển thị ảnh, JSON, full prompt, ZIP và danh mục toàn bộ ảnh gốc.
- Bước 4: **Nạp Mẹ + Alice + bếp Sữa từ thư viện** → `POST /api/assets/stage-library`. Chỉ stage các ảnh đã tạo và kiểm hash, không tự gọi image model. Không hỏi lại người dùng đường dẫn ba ảnh đã biết. Chờ queue đang chạy trước khi stage lại.
- Bước 4: **Chọn biểu cảm cho nhân vật trong shot** → `POST /api/characters/bind-expression` với `shot_id`, `node_id=30|31`, `expression_id=01-neutral...12-thinking`. API kiểm character_id/canonical hash/file hash, đóng băng toàn bộ mô tả nhân vật + biểu cảm và ảnh vào episode assets. Binding mới yêu cầu duyệt lại storyboard/anchor. Workflow gửi toàn bộ mô tả và diễn xuất, không chỉ một PNG.
- Shot Mẹ nói: thử Alice neutral/khép môi để nghe, không tự coi prompt là bằng chứng không nhép chéo. Shot Alice nói: Mother neutral/khép môi; biểu cảm Alice theo kịch bản. S06_B vẫn mở mắt nói xong mới nhắm mắt ngủ, không dùng sleeping icon ngay từ đầu.
- Cut có chủ đích: `/api/update-shot` nhận `transition_in:"cut"`, `cut_reason` không rỗng. Sau clip trước đã duyệt, đăng ký ảnh `kind:"scene_cut"` qua `/api/assets/register`, đúng `shot_id`. Anchor phải được review. Cut không nhận `/api/anchors/carry`; đoạn liên tục vẫn giữ Frame119.
- Carry liên tục tạo nhánh graph editorial thực: input PNG native-size tại frame0 + generated frames1..last-used. Full native video/audio ở sink18; editorial ở sink903, PNG đầu chính xác ở sink904. Shot 5s/24fps dùng frame119; shot 6s dùng143. Scan lưu riêng `native_source` và `editorial_source`, không trộn theo thứ tự history outputs. Exact pre-encode tensor không chứng minh equality sau H264 hay đúng diễn xuất.
- Sửa take: giữ native cũ, QA và `render_job_history`. S01_A hiện đã được chọn hình cho draft; nghe/khẩu hình chưa nghiệm thu. Nụ cười há miệng tự nó không chứng minh nhép chéo: phải xem diễn tiến và nghe đúng thoại. S01_B take đầu bị loại vì tự cắt cận cảnh và Alice ngồi trên mặt bàn; take sau giữ cảnh rộng và Alice trên ghế. Không gọi video thử là Master.

Mã nguồn engine đã qua47 regression tests; renderer10 tests tại lần kiểm gần nhất. Điều này chứng minh các nhánh kỹ thuật được kiểm tra, không chứng nhận lip sync/film/broadcast.
### Native audio speaker binding repair

Inspection found the Studio graph had temporal AddGuide WAV but lacked standalone H3 `ref_audios.ref_audio_0`. Dispatch ALSO connects LoadAudio7 there, supplies explicit `<Picture 1>` Mother / `<Picture 2>` Alice / `<Audio 1>` speaker casting, and repeats silent-listener instructions around complete character descriptions. The exact queued graph must contain that audio link and the right speaker tag. Current S01_A `3dc5b488-3de3-440d-be6f-61b6b0edcb87` is visually selected for draft; actual mouth/voice review remains required. Do not claim the generative lip problem solved from code tests alone.
Thư viện người dùng yêu cầu: `J:/1.JennieHomeSchool/guilineicon/`.
Mở `catalog.html`; mã `alice` và `mom-alice`; mỗi mã có `character.json`, version `2026-10-18-v1`, `manifest.json`, và `expressions/3d/<mã>-<biểu-cảm>.png` + JSON cùng tên. Toàn bộ file gốc trong thư mục generated_images của task được sao lưu dưới `original-generated/`, kèm hash và trạng thái lịch sử. Ảnh cũ/loại bỏ không được dùng làm canonical.

## Quy tắc bắt buộc khi tái sử dụng

KHÔNG chỉ đưa đường dẫn PNG hoặc nói “same Alice/as above”. Trong MỖI icon, shot và subshot, ghi lại TOÀN BỘ `character_description` cho TẤT CẢ nhân vật xuất hiện, rồi thêm bối cảnh, ánh sáng, camera, hành động, biểu cảm, người nói, trang phục/phụ kiện đầy đủ. Ảnh tham chiếu bổ sung cho văn bản; không thay văn bản. Dùng `full_reuse_prompt` của JSON làm điểm bắt đầu, thay `scene_context` bằng bối cảnh thực tế, không giữ nền portrait trong prompt phim.

## Alice — mô tả phải triển khai đầy đủ

Alice is a HUMAN preschool cartoon toddler girl, Homo sapiens, about TWO years old. Petite short torso, short soft limbs and oversized round toddler head, warm peach skin and full rosy cheeks, no added unique marks. Very large DARK-BROWN eyes, near-black pupils, white catchlights, fine dark eyebrows, delicate upper lashes. Tiny rounded button nose, small pink lips, small baby teeth, rounded chin, small rounded ears. DARK BLACK-BROWN straight CHIN-LENGTH BOB with STRAIGHT forehead BANGS and small tied side sections. ONE pink bow stays on ANATOMICAL RIGHT, viewer LEFT from the front; never mirror. Full wardrobe: rose-pink LONG-SLEEVE two-piece pyjama top, ONE WHITE HEART centered on the FRONT chest only, matching rose-pink loose pyjama trousers with ribbed cuffs and pale-pink socks; no shoes in the current Milk outfit. No hat, glasses, jewelry, other logos or accessories by default. Premium detailed stylized cinematic 3D animation with soft hair strands, fabric detail and warm natural soft lighting, not a photographic human or anime. Use the user-approved canonical face and stable head/eye/cheek/nose/mouth/ear proportions; changing expression permits facial muscles, blinks and speech phonemes without changing age or identity.

## Mom-Alice — mô tả phải triển khai đầy đủ

Mom-Alice (Mother) is a HUMAN adult mother, Homo sapiens, approximately THIRTY years old, about TWICE Alice's height, slender natural adult build with softly rounded oval face. Warm light-peach skin with subtle freckles, large warm BROWN eyes with near-black pupils and white catchlights, softly arched CHESTNUT eyebrows and delicate lashes, small rounded nose, natural pink lips and rounded ears/chin. CHESTNUT shoulder-length SOFT WAVES, side part and gently swept front hair, no bow. Full wardrobe: dusty-TEAL short-sleeve CREWNECK top with no print or logos, CREAM straight tailored trousers, OFF-WHITE low flat shoes. No hat, glasses, jewelry, handbag or other accessories by default. Premium detailed stylized cinematic 3D animation with softly layered hair strands, woven fabric and warm diffuse light, not photographic humans or anime. Preserve the same Mother face geometry, eye spacing, nose, lips, skin tone, freckles, age and adult proportions from the production canonical reference. Expression, eyelids, gaze and speech phonemes may change for acting. Different hairstyles, clothes, headwear or eyewear are explicit variants only, and never silently alter facial identity.

## Dữ liệu và cách chọn

12 expression IDs cho cả hai: 01-neutral, 02-happy, 03-sad, 04-angry, 05-surprised, 06-afraid, 07-laughing, 08-crying, 09-sleepy, 10-sleeping, 11-wink, 12-thinking. Chọn icon qua `manifest.json`, đọc JSON icon để có full description, expression/performance, pose, scene_context, full_reuse_prompt, ảnh canonical+SHA256, PNG+SHA256, appearance modules và edit_contract. Kiểm nguồn thực trên đĩa; không tự gọi file chưa tạo là available.

Biểu cảm chỉ thay cơ mặt, mí mắt, gaze và khẩu hình. Tóc, khuôn mặt, tuổi, tỷ lệ, màu da và trang phục mặc định không đổi. Alice theo đúng ảnh người dùng đã chốt: bob đen nâu/mái thẳng/nơ bên PHẢI giải phẫu; các bản Alice tóc xoăn hạt dẻ đã bị thay thế. Mẹ là mẫu sản xuất hiện có, chưa có xác nhận duyệt riêng bộ icon từ người dùng. Không chèn engineer/NEWTECONS/PPE từ prompt ví dụ vào phim.

## Thay module

Các operation: replace_top, replace_trousers, replace_outfit, replace_shoes, replace_hair, add_headwear, add_eyewear, add_handbag. Dùng icon làm edit target, canonical làm identity reference, ảnh module mới làm garment/accessory reference. Khóa expression, pose, identity, ánh sáng, alpha và tất cả module không được yêu cầu đổi. Với tóc: chỉ mở khóa tóc khi có yêu cầu rõ; với nón/kính: che khuất tự nhiên, không đổi hình học mặt. Quần/giày/túi cần full-body derivative riêng. Không đảo ngang ảnh để tạo hướng mới.

Lưu biến thể version mới và JSON đầy đủ, giữ nguyên canonical và originals. PNG render là raster, không phải layer tóc/áo tách sẵn, rig, mesh hay bộ viseme hoạt họa hoàn chỉnh. Việc khai báo module JSON hướng dẫn sinh/chỉnh sửa biến thể; không chứng minh đã có nón/kính hay chỉnh được mesh 3D. Kiểm hình+alpha+hash sau mỗi edit.

## Sản xuất Sữa

### Profile Studio hiện hành — áp dụng trước các mô tả cũ

- Giữ full-body canonical Mẹ ở node30 và Alice ở31. Icon đã chọn là reference diễn xuất BỔ SUNG tại32/33, không thay canonical bằng ảnh bust; ghi rõ không đổi framing. Prompt mỗi shot phải triển khai lại đầy đủ cả hai nhân vật và bối cảnh thực tế.
- `/api/guides/register` nhận `shot_id`, `frame_idx`, `source_path`, `full_prompt`. Chỉ dùng ảnh đã nhìn và kiểm nội dung; prompt ít nhất350 ký tự và phải mô tả đầy đủ nhân vật/bối cảnh/hành động ở mốc đó. Guide sau frame0, trong đoạn USED; ảnh và prompt được snapshot/hash. Chaining conditioning dùng latent gốc, không nối latent của guide cũ. Seed quyết định từ input hash, lưu ở receipt.
- S06_A ở lại ghế bếp, đặt ly xuống và nắm tay Mẹ. S06_B cut có lý do sang phòng ngủ; 6s, native158 frames, USED144. Neo frame0/60/120 còn mở mắt; frame143 nhắm mắt SAU câu4.76s. Mother nghe với môi khép. Tổng nội dung61s + intro3s + outro12s = draft dự kiến76s. Chỉ kết quả thật mới chứng nhận nhịp này.
- Mỗi clip có `review_scope`. `draft_visual` là chọn hình tạm để dựng, không phải duyệt toàn bộ âm thanh/khẩu hình hay9/9 phát sóng. Khi quét output lại, giữ scope/notes của đúng hash đã duyệt; không tự nâng thành `full_av`.
- Nhạc nền riêng48kHz stereo được đăng ký qua `/api/music/register`; hash và gain nằm trong production digest. Gain0.3, giảm85% trong thoại; attack5 frame trước, release6 frame sau. Nghe bản mix cuối vẫn bắt buộc; không coi thông số ducking là duyệt nghe.
- `milk_production.py`: `status` → `collect SHOT` → xem contact sheet có frame LAST USED → `accept SHOT --sha256 ... --notes ...` → `prepare NEXT` → `dispatch NEXT`. Không gửi trùng prompt đang chạy. Helper không tự duyệt ảnh chưa xem. Native AV, prompt/history, rejected takes và QA phải giữ lại.
- Tutorial UAT và phim Sữa là hai sản phẩm khác nhau. Hai bản18 bước/204s đã render lại với cursor di chuyển/vòng nhấn và subtitle Việt; full-decode exit0 và khung xuất thực đã được nhìn. Cursor là lớp minh họa có nhãn, không phải telemetry chuột thật. Giữ video cũ `before-cursor-*`; receipt ở `uat/2026-10-18/tutorial/verified-delivery.json`. Ảnh UAT có trước các nút thư viện mới; hướng dẫn Step4 web là bản hiện hành. Không gọi screenshot walkthrough là quay màn hình liên tục. Studio phục vụ hai bản qua `/api/tutorial/remotion.mp4?episode_id=03-drinking-milk` và `hyperframes.mp4` cùng query, cóSRT/VTT.
- Mesh/rig Blender, turnaround đầy đủ và hành động toàn thân chưa được nghiệm thu chỉ vì đã có24 icon. Giữ chúng là hạng mục sản xuất riêng, không báo hoàn thành thay cho tài sản thật.

Agent tự tạo/stage ba ảnh: Mẹ node30, Alice node31, bếp Sữa đầu tiên node8. `production-local/character-library/prepare_milk.py` nạp các file đã được tạo và rà hình qua API Studio; script không tự gọi image model. Tạo ảnh dùng built-in image_gen (model ID không được công bố). Không tuyên bố API generation tự động trong Studio đã hoàn chỉnh chỉ vì stage/import chạy được.

Prompt workflow node20 và prompt các shot đều phải dùng nhận diện/costume 3D hiện hành. Ánh sáng bếp chiều tối, bình/ly sữa trắng, bánh quy tròn, tranh bò; chỉ hai mẹ con. S06_B là cut có chủ đích sang phòng ngủ, cần anchor riêng và hỗ trợ cut có kiểm soát; không giả làm continuous hard-carry hoặc ép đi/tuck-in cả ngôi nhà trong 5 giây. Alice nói khi mở mắt, xong mới ngủ; Mẹ luôn khép miệng ở shot này.

Lưu prompt_id, native AV, hash, nhận xét diễn xuất và carry thực. Một field HTTP `carry_in_first_frame:true` KHÔNG được ComfyUI thực thi; cần graph editorial thực (tham khảo continuous builder) và kiểm seam, không chứng nhận từ field đó. Review từng clip trước khi carry; draft 720p có phụ đề, Master 1080p chỉ sau người dùng duyệt draft. Icon/concept/intro/UAT không phải phim Sữa thành phẩm.


Góc chuẩn bị Blender bổ sung2026-10-18: Alice có sheet front/left/back và ảnh right profile đã sửa; Mẹ có sheet front/right/back và ảnh left profile bổ sung. Tất cả ở `<mã>/2026-10-18-v1/turnaround/3d/`, có JSON/prompt đầy đủ. Xem README thư viện để chọn đúng file. Bản Alice góc3/4 thử nghiệm được giữ riêng; không nhầm với profile. Đây là diễn giải raster, chưa xác nhận mesh/rig.
