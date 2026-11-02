# JennieKidJoys — tiến độ hiện tại

**Đã có bản xem thử 5 giây đầu ở 720p. Phim 60 giây chưa hoàn tất.**

| Hạng mục | Trạng thái đã kiểm chứng |
| --- | --- |
| Skill cấp user | 137/137 kiểm thử Python đạt; FL2VA đã được review code/Python độc lập PASS. Các kiểm tra React/TypeScript/phụ đề trước đó đạt. ZIP v7 là gói trước bản FL2VA; v8 chưa đóng. |
| Scene 1A | Chuyển động đi vào của v9 đã qua kiểm tra khung hình. Bản xem thử v3 ghép Hyperframes, Remotion và Alice; phụ đề góc trên trái tránh đầu và bàn chân ở các khung đã kiểm tra. |
| Scene 1B | v9 bị loại vì bóng chồng và nhấp sáng. v10 bị loại vì tự chuyển sang cận mặt. v11 thử lịch simple cũng bị loại vì tự cắt cận mặt. FL2VA v12 đã xuất MP4 trong297,863s, kỹ thuật đạt nhưng vẫn quay cận mặt nên bị loại. Thử nghiệm v13 đang chạy: chỉ chiếu prompt sang văn xuôi, giữ45giá trị đặc điểm nhân vật và toàn bộ cấu hình. Chưa biết kết quả. |
| Scene 2–6 | Đã có kịch bản MD/JSON và SOUND-PLAN cho từng cảnh; chưa render. Khung đầu Scene 2 phải lấy từ khung cuối thực tế đã chọn của Scene 1B. |
| Âm thanh | Giữ nguyên 12 câu Alice canonical. Bản nền giọng + nhạc + không gian dài 60 giây đạt kiểm tra kỹ thuật; Foley theo hình và nghe duyệt còn chờ. |
| Phim hoàn chỉnh | Còn thiếu hai bản 720p đủ 60 giây, đối chiếu từng cảnh với Higgsfield và báo cáo cuối. SRT theo clock Alice đã chuẩn bị, cần kiểm tra cùng bản dựng. |
| 1080p | Chờ người dùng duyệt bản nháp 720p hoàn chỉnh. |

Lượt v11 `f0472c3b-1da2-420c-b485-97e37f47728a` đã hoàn tất 304,771 giây nhưng bị loại về hình ảnh. Lượt FL2VA v12 `17047713-25b5-4aae-9d64-754401b24b65` đã hoàn tất297,863s và bị loại về chuyển động. 27 nodes và toàn bộ input cấu hình/prompt trong queue khớp; PNG đầu bằng pixel khung A119. ComfyUI đang chạy v13 `741cd009-e681-4704-b3ce-06df75a535ec`; prompt và toàn bộ input đã đối chiếu khớp. ASR chạy CPU đã hoàn tất: kiểm tra từng câu không VAD nhận đủ hai từ “Look!” từng bị bỏ sót khi chạy cả track. Vẫn cần nghe cùng hình; chưa đổi giọng hoặc clock Alice.

Bản xem thử: [A5 v3 — 720p, tiếng Anh](<D:/23.JennieHomeSchool/03 Voice/production-local/A5-preview-v3/edit/renders/JennieKidJoys-A5-workpreview-v3-720p-English.mp4>). Native 864×480 được upscale lên 720p. Bản này chưa có Foley sự kiện và chưa nghe duyệt cuối.

Gói skill: [Create Video JennieJoyKids v7](<D:/23.JennieHomeSchool/03 Voice/JennieJoyKids-Archive/Create-Video-JennieJoyKids-2026-10-17-v7.zip>), SHA256 `621060e5f68dadfc06ac4e042fbc40c160938a49b84575ff947bb069d69721cc`. Các bản ZIP trước vẫn được giữ.

## Lịch sử các mốc trước

# JennieKidJoys — báo cáo phim 60 giây

Cập nhật UTC: 2026-10-16T20:19:44.648554+00:00. **Chưa có Scene 1 mới được chấp nhận hoặc phim ComfyUI 60 giây hoàn chỉnh.**

## Mốc 11 — render v9 hoàn tất, kiểm tra hình và âm thanh còn tiếp tục

Job `00af6f7c-e581-4ea2-ad77-cc0ea018bb27` đã kết thúc thành công trong **1512.716 giây**. Cả S01_A và S01_B có MP4 native, MP4 editorial và PNG đầu/cuối trong `ComfyUI/output/JennieKidJoys/Scene-01-v9/`. A đã được kiểm tra toàn bộ khung hình dùng 0–119: cả nhà quay lưng và đi tới. B xuất hiện chớp sáng; nghi bóng chồng, đang chờ xem các frame liên tiếp để xác định. **Chưa duyệt cặp A/B, âm thanh hay toàn cảnh.**

Render v9 dùng bản nguồn v8 đã khóa. Kịch bản hiện tại cho công việc tiếp theo là `production-request-v9.json`, `stages-v9`, SHA256 `3dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643`. Không thay lịch sử nguồn render bằng tên kịch bản mới.

Sửa carry-in đầu cảnh liên job đã qua code review: **121/121 tests**, nhóm kiểm tra tập trung **7/7**. Trạng thái `code_reviewed_runtime_pending`; còn preflight ảnh boundary thực của Scene 2 và xác minh runtime trước khi coi là đạt.

Đã đọc kế hoạch âm thanh cả sáu cảnh: đủ stem Alice, nhạc, không gian, bước chân, con vật và đồ vật. Chim/cánh/lá, hươu/lá, hổ chuff nhẹ, gấu trúc/tre, bình nước/nắp/hộp/chuối và tiếng bước chân được gắn với hành động; lời vẫn dùng canonical Alice v2. Scene 5A nói 1.00–2.99s rồi dự kiến uống 3.25–4.35s; 5B nói 0.35–3.29s (master 45.35–48.29s), dự kiến cắn 3.55–3.95s. Lời tiếp ở master 51.00s; miệng đã sẵn sàng/nuốt xong phải kiểm tra trên hình. Các mốc ăn/uống là kế hoạch, không phải số đo.

Foley chưa được đặt theo contact/transient cuối cùng; chưa duyệt nghe bản mix. Bed preview 60s hiện chỉ có nền, không chứng minh đã hoàn thành cue hành động. Chờ hình đạt rồi đo PTS, đồng bộ tiếng, duck nhạc và nghe cùng hình. Còn Scenes 2–6, so sánh Higgsfield, hai bản 720p/60s, SRT và báo cáo cuối. 1080p vẫn cần người dùng duyệt 720p. Chưa đóng ZIP mới; root sẽ đóng gói sau chẩn đoán exposure.

## Lịch sử trước mốc 11 — giữ nguyên để đối chiếu

Các trạng thái chạy/chờ bên dưới là bản ghi cũ, đã được cập nhật ở mốc 11 phía trên.

Cập nhật UTC: 2026-10-16T19:46:23.925082+00:00. **Chưa có Scene 1 mới đạt chuyển động hoặc phim ComfyUI60s hoàn chỉnh.**

| Phân cảnh | Tài liệu | Trạng thái |
| --- | --- | --- |
| Scene 1 — Entering the Zoo | [Kịch bản](scenes/scene-01/SCENE.md), [âm thanh](scenes/scene-01/SOUND-PLAN.md) | v8 xuất đủ MP4; loại vì quay mặt/ngược hướng; chuẩn bị guide chuyển động liên tiếp |
| Scene 2 — A Little Bird | [Kịch bản](scenes/scene-02/SCENE.md), [âm thanh](scenes/scene-02/SOUND-PLAN.md) | Kịch bản và kế hoạch âm thanh v8 đã lưu; chưa render |
| Scene 3 — A Tall Giraffe | [Kịch bản](scenes/scene-03/SCENE.md), [âm thanh](scenes/scene-03/SOUND-PLAN.md) | Kịch bản và kế hoạch âm thanh v8 đã lưu; chưa render |
| Scene 4 — Hello, Tiger | [Kịch bản](scenes/scene-04/SCENE.md), [âm thanh](scenes/scene-04/SOUND-PLAN.md) | Kịch bản và kế hoạch âm thanh v8 đã lưu; chưa render |
| Scene 5 — A Hungry Panda | [Kịch bản](scenes/scene-05/SCENE.md), [âm thanh](scenes/scene-05/SOUND-PLAN.md) | Kịch bản và kế hoạch âm thanh v8 đã lưu; chưa render |
| Scene 6 — Bye-bye, Zoo | [Kịch bản](scenes/scene-06/SCENE.md), [âm thanh](scenes/scene-06/SOUND-PLAN.md) | Kịch bản và kế hoạch âm thanh v8 đã lưu; chưa render |

V8 job `5d52c76e-33c6-4a91-9996-c9dea6c98e60` hoàn thành trong 725.589s; prompt thực vào queue nguyên vẹn, đủ cast/action. Cả A/B vẫn quay về máy quay nên không đưa vào master. Raw AV bảo toàn. Thử tiếp chuỗi khung hình chuyển động, chờ code review; không submit trùng.

Đã có canonical Alice v2, 12 bản PCM gốc giữ nguyên; Scene5L2 ở45.35–48.29s. Bé uống3.25–4.35s tại5A, cắnchuối3.55–3.95s tại5B sau lời. Chờ xác minh nuốt/xong miệng trước lời tiếp.

Mỗi cảnh có VO/music/ambience/footsteps/animal/props riêng; tiếng chim, hổ gừ/chuff nhẹ, gấu trúc ăn tre, bình nước, hộp ăn. Ba mẹ phản ứng không lời đến khi có profile riêng. Cue/contact/listening chưa được duyệt; không dùng mốc dự kiến như số đo.

Còn: Scene1 đúng hướng/seam, Scenes2–6, so sánh Higgsfield, cue thật/phối âm/nghe, Hyperframes+Remotion 2 bản720p60s+SRT/báo cáo. 1080p chờ duyệt720p. Lỗi/handoff lưu song songproject+skill.

Mốc9 đang chạy: `00af6f7c-e581-4ea2-ad77-cc0ea018bb27`, 62nodes, một RunChrome; literal12712/13032chars vàtoànbộinputkhớp. Aguide124frames@0; Bguide90frames@24; nguồn24fps/countđãprobe. Chờchuyểnđộngthật.

Mốc đóng gói: skillv6 ZIP237entries,18,173,566bytes, SHA256dced35f6f9214402b913e24e86abdf5275021dbad89303094cc4fd64d4dcbecd; toànbộentrychecksumđãkiểm.114testsPASS0skips. SOUND-DESIGN.md và12cuesSRTcanonicalv2đãlưu; lipsync/listening/visualcontactpending.
