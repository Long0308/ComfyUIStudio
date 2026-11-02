# Hợp đồng sản xuất phim nhân vật NEWTECONS

## Nguồn và phiên bản hiện hành

Đường dẫn workspace gốc: `J:/1.JennieHomeSchool/03 Voice`. Trong tài liệu này, **topic** là `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s`, **pack** là `topic/production-v2-45s`.

- Script: `pack/script/screenplay-astra-45s.json` và `.md`, model GPT-6 Astra theo orchestration; 8 cảnh, 45s, 1080 frame tại 24fps. Thoại và thời điểm hiện là dự kiến, chưa thay được số đo WAV.
- Trạng thái hiện hành: đọc `SESSION-HANDOVER-LATEST.md` và JSON bàn giao 2026-10-23. r003 là lịch sử; r004 chỉ có kế hoạch. `pack/active-image-requests-160.json` trộn revision và chưa được chốt theo chuẩn trang phục mới. Đọc `pack/qa/wardrobe-rebuild-required.json` trước khi chọn ảnh; không chạy compiler mặc định để ghi đè lịch sử.
- `pack/characters/CHAR_01/` đến `CHAR_08/`: mỗi thư mục có nguồn, prompt, faces/actions theo revision và receipt. Đủ kế hoạch 160 không có nghĩa đủ 160 PNG.
- Giữ nguyên script, ảnh nguồn và revision cũ. Nếu nguồn/prompt/brand đổi, tạo revision mới cùng hash; không ghi đè output đã có.

## Cast, khuôn mặt và trang phục

| CHAR | Vai chính | Trang phục / chữ bộ phận theo ảnh gốc |
|---|---|---|
| 01 Nguyễn Văn Minh | Kỹ sư AI/trưởng nhóm kỹ thuật | KHỐI KỸ THUẬT |
| 02 Trần Đình Tuấn | GĐDA, nhãn SITE MANAGER theo user | SITE MANAGER |
| 03 Lê Văn Thọ | Trưởng PHÒNG THIẾT BỊ | PHÒNG THIẾT BỊ |
| 04 Phạm Quang Hoàng | Giám đốc điều hành | Suit charcoal tại văn phòng; nếu ra công trường theo quy định đã chốt |
| 05 Đỗ Mạnh Thắng | SITE MANAGER | SITE MANAGER |
| 06 Nguyễn Lan Anh | Kỹ sư/chăm lo đời sống | KHỐI KỸ THUẬT |
| 07 Hoàng Minh | BIM/AI | KHỐI KỸ THUẬT |
| 08 Trần Thảo Mai | BIM/kiểm soát tiến độ | Sơ mi văn phòng; nếu có cảnh công trường: KHỐI KỸ THUẬT |

Mặt riêng từng CHAR lấy từ `casting/CHAR_nn_MASTER_FACE_LOCKED.png` và hash nguồn; không dùng các link mặt chung trong bible cũ. CHAR_03 giữ kính chữ nhật gọng đen/titan. CHAR_08 dùng thêm `casting/CHAR_08_6_GOC_XOAY_GOI_CAM_4K.png` như user đã chọn: kính, ponytail, sơ mi kín đáo vừa dáng, quần tây navy/đen, cao gót đen. Không thay bằng mặt nữ khác; ảnh nhiều góc chỉ là reference, không sao chép bố cục collage hoặc nhân bản nhân vật trong cảnh.

Mỗi CHAR: 10 PNG biểu cảm + 10 PNG hành động, từng ảnh riêng và từng prompt đầy đủ. Có cận/trung/toàn, nhận diện nhất quán. Giữ cấu trúc mặt, màu da, tóc, sẹo, nốt ruồi, nếp nhăn, kết cấu da; biểu cảm và tư thế thay đổi đúng chỉ đạo. “100% face lock” là mục tiêu kiểm ảnh, không phải bảo đảm từ một câu prompt. Cấm blend mặt, làm mịn nhựa, trẻ hóa hoặc tự tạo dấu hiệu da mới. Prompt mỗi scene lặp đầy đủ visible cast, trang phục, nguồn/hash, vị trí, hành động, ánh sáng, camera; ID hay “như cảnh trước” không thay mô tả.

Nguồn trang phục canonical: `production-local/character-library/newtecons/wardrobe/v001/wardrobe-requirements-latest.json`, `source-lock.json` và `originals/`. Sơ mi lưới xanh–trắng cực nhỏ/dày đúng ảnh thật, không ô gingham to, có logo NEWTECONS nhỏ thêu trên lá cổ. Phom vừa vặn. Gile navy, dây kéo, túi, mesh và vị trí dải cam-bạc phải khớp mặt trước/sau gốc. Chữ bộ phận ở trái ảnh, brand ở phải ảnh trong ảnh chính diện gốc; không lật gương hay dùng mô tả giải phẫu ngược nguồn. Logo không in trên túi. Thêm biến thể BCH dùng lại, không tự gán thay cast. Không giữ chữ BAN TRUYỀN THÔNG trên gile cuối. Nón trắng dùng hình/logo nguồn đỏ-xanh; nguồn crop nhỏ nên góc mới là diễn giải chờ kiểm. Văn phòng không mũ/gile; sơ mi vẫn có logo cổ theo quyết định mới, không tự thêm huy hiệu/thẻ. CHAR_04: suit charcoal, sơ mi trắng, cà vạt navy, giày đen.

**Tạo và áp dụng, không chỉ lập thư viện:** tạo bộ trang phục có mã lookup, prompt/nguồn/hash và kiểm ảnh; sau đó sửa/tạo revision mới cho tất cả ảnh nhân vật/cảnh sai, cập nhật ảnh neo/đầu vào video và binding từng scene. Lưu `old_path/old_hash → replacement_path/replacement_hash`, mã trang phục và QA đúng hash trong manifest. File/prompt/receipt lịch sử bất biến, không còn được chọn làm chuẩn quần áo. 35 PNG hiện có đều chưa được nghiệm thu theo yêu cầu mới; đây là danh sách kiểm/sửa, không phải kết luận mọi chi tiết trong 35 ảnh đều sai. Chỉ nhận ảnh không cần sửa khi QA trang phục mới gắn đúng hash chứng minh phù hợp. Chưa đóng checklist nếu vẫn còn ảnh sai hoặc shot phụ thuộc chưa được cập nhật.

`casting/newtecons.jpg` là tòa nhà NEWTECONS và `casting/boicanh.jpg` là công trường thật do parent xác minh; chỉ lấy kiến trúc/bối cảnh. Ba nội thất mới ở `pack/environments/`: `NEWTECONS_EXECUTIVE_OFFICE_ORIGINAL.jpg`, `NEWTECONS_OPEN_OFFICE_EMPTY_ORIGINAL.jpg`, `NEWTECONS_OPEN_OFFICE_OCCUPIED_ORIGINAL.jpg`, nguồn/hash trong `environment-sources.json`. Dùng phòng GĐ cho CHAR04, văn phòng mở cho CHAR02/03/07/08; không lấy danh tính nhân sự nền. **Loại** `newtecons_project_setting.jpg` và `BOI_CANH_CONG_TRINH_NEWTECONS.jpg`: đó là screenshot ComfyUI đặt nhầm tên. Payload thực phải chứa mọi reference được nhắc, với vai trò rõ ràng; đừng gửi chỉ tên file.

## Các công cụ đang có và giới hạn

Các script sau nằm trong **pack**, không phải thư mục skill:

| Script | Làm gì | Không chứng minh |
|---|---|---|
| `build_character_pack.py` | Lập manifest/prompt, default r004 | Còn quy tắc áo cũ; sửa compiler, chọn revision mới và binding wardrobe trước chạy. Không sinh ảnh. |
| `generate_image2_pack.py` | Runner OpenRouter lịch sử, model yêu cầu `openai/gpt-5.4-image-2` | Đã dừng sau HTTP402; không retry. Lựa chọn mới cho NEWTECONS là ComfyUI local; không tự fallback GPT/cloud. Giữ backend unknown cho các ảnh built-in lịch sử không công bố model. |
| `record_image.py` | Receipt dispatch/fallback/completion và hash PNG có thật | Không sinh ảnh; trạng thái DISPATCHED không phải hoàn tất. Đọc cú pháp hiện tại trước dùng. |
| `build_review_gallery.py` | Xuất bảng xem từ PNG/receipt khớp hash | Không tự nghiệm thu mặt/trang phục; không phải master video. |

Bảng xem dự kiến: `http://127.0.0.1:5050/model-review/newtecons-45s-casting/`; kiểm dịch vụ trước khi gọi đó là link đang hoạt động. Mỗi receipt cần task ID, prompt/ref hashes, engine/tool, model requested/returned nếu có, thời gian, đường dẫn output, SHA256, kích thước, trạng thái QA. Imagegen tool không lộ backend thì ghi **unknown**, không quảng cáo tất cả ảnh là GPT Image 2. Ảnh dùng lại phải khớp đúng revision/recipe/hash; không retry job còn chạy hoặc kết quả chưa rõ.

Yêu cầu engine mới: ưu tiên **ComfyUI local** cho ảnh, thay mặt/áo và video. Đọc [local routing](local-comfyui-routing.md) và audit `docs/handoffs/2026-10-23-COMFYUI-LOCAL-CAPABILITIES.json` trước chọn graph. File workflow có sẵn chưa chứng minh runtime: swap/InstantID/LivePortrait/HunyuanT2V còn dependency; model H3/Seed7B đã thấy. Hoàn thiện một đường ảnh local, lưu graph thực/seed/prompt/ref/model/output hashes và chạy pilot rồi batch. GPT/Gemini chỉ giữ lớp viết/điều phối/review theo lựa chọn hiện tại.

Mốc batch `image-batch-r003-20261023T004224164168.json`: 16 GENERATED_QA_PENDING, 144 HTTP_FAILED_NO_RETRY; parent xác nhận HTTP402 hết credit. Đây là số của batch lịch sử, không phải bộ đếm sống sau fallback. Đếm ảnh hiện tại bằng file vật lý và receipt hợp lệ; chỉ tính hoàn thành QA khi có đánh giá gắn đúng hash. Không tự thanh toán/nạp credit hay gửi lại hàng loạt. Fallback đã được parent triển khai; bảo toàn receipt lỗi và provenance mới, không thay đổi lời khai engine cũ.

## Tiến trình, bằng chứng và recovery

1. **Trang phục rồi cast/ảnh:** tạo/kiểm bộ sơ mi, nón, bốn biến thể gile và suit; cấp registry/mã lookup. Áp dụng sửa mọi ảnh sai trong `pack/qa/wardrobe-rebuild-required.json` và mọi scene/anchor liên quan, lưu thay thế theo hash. Sửa compiler/bible/screenplay theo chuẩn mới rồi tạo revision mới, đủ 8×20 ảnh riêng, prompt/ref hashes; kiểm mặt, biểu cảm, cận/trung/toàn, tay, logo/chữ và trang phục. Không đếm contact sheet là 20 ảnh.
2. **Giọng:** kiểm 8 vai người lớn tiếng Việt, nghe độ tự nhiên/rõ/chậm vừa câu; không dùng profile Alice/Mẹ mặc định hoặc coi pitch variant là người nói khác. Lưu profile ID, text sạch, WAV, hash và thời lượng thật. Cảnh 05 có hai người: giữ hai stem, khoảng im và lượt lời; không ép nhanh/time-stretch để vừa dự kiến.
3. **H3:** trước dispatch kiểm queue/history, job ID và input hashes. Job H3 cũ đang chạy phải được đối chiếu quyền sở hữu và kết quả; không duplicate/interrupt. Builder hiện hardcode preschool/English và Studio dispatch Mother/Alice, nên phải adapter corporate VI/cast/voices trước dùng. Không phải bằng chứng có adapter production sẵn.
4. **Native/lip:** dùng exact final WAV làm guide và reference đúng speaker; native sinh lời không bảo đảm giữ sample/khẩu hình. Lưu native AV bất biến, tạo editorial dùng WAV cuối, kiểm người im lặng không nhép, đúng phụ âm/điểm vào. Cảnh 05 cần hai reference audio/speaker bindings hoặc subshot phù hợp; builder một ref_audio hiện chưa đủ tự phân vai. **WAV thoại của shot** là WAV nêu trong biên bản chuẩn bị H3 (`preparation.json` → `wav.sha256`); biên bản job H3 ghi cùng SHA256, H3 và mix Remotion dùng đúng file đó. Nếu cắt im lặng thì cắt MỘT lần trước H3; cắt sau H3 không bao giờ thay WAV biên bản. Cảnh 05 hai người: cách gắn WAV (một WAV trộn hay subshot mỗi người một WAV) là quyết định mở của người dùng; chưa phải quy tắc.
5. **Restoration:** SeedVR2 **7B** đã chọn. Chỉ restore sau khi hình/diễn/nhép đủ tốt; giữ recipe/model/source/output hashes. GPU nặng chạy tuần tự trên RTX5080 16GB, xác minh nhả VRAM; không mặc nhiên gọi scale Lanczos là SeedVR2.
   - Mọi footage NEWTECONS, kể cả 864×480, cần pilot SeedVR2 GPU riêng do người dùng cho phép và biên bản kiểm định trước mọi batch. Công thức v003 (tile 768, overlap 64, nội bộ 17, thô 21, prompt `43f87ebe`) chỉ được kiểm định cho domain hoạt hình `jenniejoy_cartoon_3d` (864×480 → 3888×2160); không mượn công thức hoạt hình. tile1024/max40 là lịch sử đã bị thay thế.
   - SeedVR2 đệm đầu vào lên 4n+1 nhưng cắt đầu ra về đúng số frame thô của đoạn (`nodes_seedvr.py:188-196`); kiểm clip đã phục hồi theo số frame thô, không theo số frame đệm.
   - Đoạn có độ dài đệm ≤ `frames_per_chunk` (17 trong v003, node 8) chạy đường sampler một chunk (`nodes_seedvr.py:499-500`), pilot 21 frame chưa chạm tới: canary đoạn 5, 9, 17 frame đệm trước khi batch.
   - Sau khi pilot NEWTECONS đạt, nếu đầu vào là 864×480 (1,8:1): xử lý ra 3888×2160, cắt 24 px mỗi bên thành 3840×2160 (`crop=3840:2160:24:0`), không resize. Tỷ lệ khác: tính vùng cắt từ công thức đã kiểm định riêng.
6. **ASR/caption:** transcript/word timings phải gắn WAV cuối và kiểm nghe; timestamp ước tính không phải ASR hoặc chứng nhận nhép. Subtitle nguyên lời, headline cảnh tách riêng.
7. **Finishing:** Remotion giữ master clock và mix; HyperFrames xuất graphic độc lập, dùng logo gốc, không để image/video generator vẽ lại chữ thương hiệu. Cảnh 08 graphic 4s không cần H3. Kiểm đúng props, asset hashes, duration/alpha trước ghép.
8. **Draft/master:** tạo draft 1280×720 có AV, nghe/xem toàn bộ tốc độ thường, kiểm mặt/brand/motion/lip/sub/SFX/seam; sau đủ điều kiện theo phạm vi đã cho mới master1080p phiên bản mới. File MP4 encode thành công không chứng minh chất lượng. Đăng phim/job IDs thật, output hash và review ở Studio; không dùng content hash giả job ID.

Native profile dự kiến: 864×480, 24fps, batch1, 20steps, res_multistep, scheduler simple khai rõ, encoder default; đọc installed schema/models trước chạy. 5s dùng120/native124/last119; 6s dùng144/native158/last143; 7s dùng168/native175/last167. Native vẫn480p; padding giữ tỷ lệ để ra draft720p. Builder yêu cầu chiều chia hết32 nên 1280×720 không phải cấu hình native hợp lệ của builder hiện tại. Endpoint Studio chỉnh shot mới chỉ nhận5/6s; cần adapter cho cảnh7s. Một số finishing path mặc định30fps; bảo toàn clock24fps của script hoặc ghi rõ conversion, không gọi1350frame là1080frame.

Các cảnh đổi địa điểm dùng cut có chủ đích. Nếu chia subshot liên tục mới lấy last USED frame119/143/167 từ clip đã kiểm, giữ kích thước native và nguồn/hash; frame đầu giống nhau không chứng minh continuity. Không chạy lại H3 khi chỉ sửa subtitle/logo/mix; thay WAV kéo theo kiểm caption/lip; thay identity kéo theo những shot phụ thuộc.

## Trạng thái và đa IDE

Tại bàn giao 2026-10-23: **PHIM45S CHƯA RENDER**; 35 PNG gồm 8 legacy + 1 r002 + 26 r003, 0 được nghiệm thu theo chuẩn trang phục mới, 0 asset wardrobe mới. r003 có 16 ảnh OpenRouter và 10 ảnh built-in imagegen; không còn batch ảnh được ghi nhận đang chạy. Giọng Việt người lớn, native/lips, ASR, Seed7B, Remotion/HyperFrames và nghiệm thu còn phải chạy/kiểm. Khi tiếp tục, dùng receipt/queue mới nhất thay snapshot; chỉ nâng trạng thái khi bằng chứng tồn tại. Session mới dùng subagent Gemini 3.8 Flash theo AGENTS.md; ghi model thực, child hoàn tất thì interrupt_agent.

GPT/Gemini/Opus chỉ khác lớp điều phối/review; engine/artifact contract giữ nguyên. Pointer đa IDE về `create-video-newtecons/SKILL.md`; parent đồng bộ và ghi receipt riêng. Không suy ra IDE đã discovery từ việc copy file. Tách rõ “đã viết skill”, “đã đồng bộ pointer”, “đã chạy engine” và “phim đã nghiệm thu”.
