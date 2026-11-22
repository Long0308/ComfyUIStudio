# Revit film toolkit

Verified: 2026-11-10 (Asia/Bangkok). Scope: nguồn user yêu cầu lưu để làm phim Revit; không tự cài hoặc chạy cả bộ repo. Các số lượng dưới đây là công bố upstream tại ngày kiểm, không phải số template đã chạy trên máy này.

## Brief hiện tại

- Tiêu đề chính xác: **Revit -MEP - AI - Agent**.
- **Có nhạc nền và SFX khớp nhịp chuyển động** theo yêu cầu mới; thay thế bản nháp không âm thanh trước đó. Chưa có yêu cầu giọng đọc, nên không tự tạo voiceover.
- Intro dùng kinetic typography, icon từng hệ, đường vẽ có nhịp, định vị căn mẫu/căn triển khai và infographic từ căn đến sheet. Tránh lặp lại bố cục bốn ô tĩnh, chữ nhỏ mờ và khoảng trống không có chức năng.
- CAD/Revit/Codex/Subagents là nguồn thật. Đồ họa giải thích có thể dựng bằng code; không dựng chat, con trỏ, trạng thái agent hoặc kết quả mô hình giả.
- Intro mô phỏng được phép dùng con trỏ đồ họa màu/nhãn agent và thanh tiến trình có nhãn mô phỏng theo [bàn giao create-sheet-apt](../../create-sheet-apt/references/video-handover.md). Quy tắc không giả con trỏ áp dụng cho bằng chứng thao tác thật; không dùng overlay làm bằng chứng đã vẽ trong Revit.
- Năm take hệ riêng, ưu tiên thoát nước SP → VP → WP; một take phối hợp toàn hệ. Raw footage và phim edited có file/receipt riêng.
- Ghi soundtrack/SFX source, license, cue frame, BPM/beat grid, gain/ducking và hash. Thực sự nghe bản mix, kiểm clipping/loudness và nhìn frame tại mỗi điểm nhấn; không suy chất lượng từ render exit 0.

## Tám nguồn user gửi

| Nguồn đã kiểm | Điều upstream mô tả / drift so với bài user gửi | Dùng cho Revit | License / giới hạn cần giữ |
|---|---|---|---|
| [xilo-opus-video](https://github.com/Kianzzz/xilo-opus-video), [README](https://github.com/Kianzzz/xilo-opus-video/blob/main/README.md) | Ba hướng khác nhau, mỗi hướng có keyframe hoặc mẫu 2–4s; brief rồi render code theo thời gian. | So sánh hướng mở đầu khi chưa chốt; giữ bố cục/hình chuyển động có chủ đích. User đã chỉ định sửa cụ thể thì sửa phần đó, không ép hỏi lại ba hướng. | MIT code/docs; kiểm tài sản riêng trước khi mang vào phim. |
| [lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar), [README hiện tại](https://github.com/lemomo-ai/lemo-opuscar/blob/main/README.md) | Bài gửi nói 43 style; raw main hiện ghi **66**. Có evidence films, edit/documentary và style riêng. | Ngôn ngữ tư liệu có nguồn, đồ họa từ dữ liệu, camera cận trên màn hình thật. | Code/docs MIT; demo films/stills CC BY 4.0 credit LemoLab; tài sản bên thứ ba giữ license riêng. Sáu narration demo bị loại khỏi CC BY, không tái dùng. |
| [mg-styles-15](https://github.com/Vincentwei1021/mg-styles-15) | 15 phim, mỗi phim 10s, prompt/source đầy đủ; picture và music/SFX bằng code. | Ưu tiên **02 Isometric 2.5D**, **04 Line Art**, **11 Geometric Bauhaus / 20 Beats** cho căn → mạng hệ → bộ sheet. | MIT repo; asset/sample phải kiểm nguồn riêng. Không mặc nhiên copy nhạc chỉ vì code MIT. |
| [dashi-animationstyle](https://github.com/chuspeeism/dashi-animationstyle) | 7 style cho đoạn giải thích tiếng Trung 15–60s; thử chính trên macOS/Opus. | Phân đoạn một ý, draw-on diagram và caption đủ đọc; lấy cơ chế, dùng palette/typography của phim Revit. | Code/docs MIT. Giọng tác giả `examples/token/口播.wav` chỉ thử skill, không dùng trong phim khác. Windows chưa được upstream chứng minh tương đương. |
| [huashu-art-motion](https://github.com/alchaincyf/huashu-art-motion), [README.en](https://github.com/alchaincyf/huashu-art-motion/blob/main/README.en.md) | Bài gửi nói 35 style/9 grammar; README hiện ghi **36 recipe**, 35 Canvas scenes và một SVG; 9 grammar, 8 có demo chạy. | Frame-first, đồ vật chuyển động trong cảnh, diagram/kinetic type, phân tích beat/motion; giữ một thế giới hình ảnh liên tục. | MIT code/docs; font OFL và stroke data Arphic giữ license riêng. Nhân vật Huashu/Clawd và demo likeness có ngoại lệ, không đưa vào phim Revit. |
| [Wattter_openSkills](https://github.com/WaterDJiang/Wattter_openSkills), [skill hiện tại](https://github.com/WaterDJiang/Wattter_openSkills/blob/main/wattter_skills/wtt-code-video-studio/SKILL.md) | Bài gửi gọi `wtt-code-animation-studio`; main hiện dùng **wtt-code-video-studio**. Nội dung → hướng → mẫu code → board → phim, giao source chỉnh sửa được. | Tham khảo cách khóa brief, kiểm mẫu trước render và bàn giao script/storyboard/source. | Repo mặc định **CC BY-NC-SA 4.0** trừ ngoại lệ từng file. Với phim giới thiệu công việc, giữ research-only; không sao chép code/assets có điều kiện NC khi chưa có quyền phù hợp. |
| [video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft), [SKILL](https://github.com/Vincentwei1021/video-shotcraft/blob/main/SKILL.md) | Upstream hiện ghi **124 shot recipe cards / 150 motion previews**, Remotion, beat sync và sound design. | Camera 2.5D, close-up, match-cut từ căn sang view/sheet và cue SFX theo điểm đặt. Giao diện chính phải quay thật. | Apache-2.0 code; giữ NOTICE/attribution nếu sao chép và kiểm từng asset. |
| `archival-doc` (user tự tạo) | Chưa có URL hoặc file skill để xác minh; bài mô tả public-domain/CC historical footage và kiểm quyền. | Nguyên tắc lưu nguồn/quyền của tư liệu thật; không cần footage lịch sử cho demo Revit hiện tại. | **Chưa xác minh**. Không đặt URL hay license giả; không coi là đã cài. |

Các shortlink t.co bị công cụ từ chối ở nhiều mục; các URL canonical phía trên đã được tìm và đọc trực tiếp từ chủ repo. Đây không phải chứng minh shortlink đã resolve thành công. Giữ nguyên nội dung bài user như input tham khảo; ưu tiên revision README đã kiểm khi cần số lượng hiện tại.

## Nguồn bổ sung và vai trò

| Nguồn | Cách áp dụng | Trạng thái / nguồn quyền |
|---|---|---|
| [Barty-Bart/motion-graphics](https://github.com/Barty-Bart/motion-graphics), [explainer-high-energy](https://github.com/Barty-Bart/motion-graphics/blob/main/skills/explainer-high-energy/SKILL.md) | Nhịp intro 12–20s, kinetic type và một hình/đường dẫn mắt qua các cảnh; music tổng hợp có beat grid. `explainer-default` có hướng tái dựng UI nhưng yêu cầu user về Codex/Revit thật thắng hướng đó. | MIT; Geist/OFL và Lucide/ISC có notice riêng. |
| [awesome-opus5-5-videos](https://github.com/yihui-dev/awesome-opus5-5-videos) | Xem prompt/cách kể chuyện và dẫn về nguồn gốc. Chọn đúng ví dụ, chuyển thành thiết kế riêng. | MIT repo/list; **không phải engine hoặc gói template đã cài**. Quyền video gốc theo từng chủ nguồn, không suy từ license của list. |
| [ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill), [SKILL đã đọc](https://github.com/kajisho5/ffmpeg-skill/blob/main/SKILL.md) | Probe → plan/dry-run → edit → check → verify → xem contact sheet. Dùng cắt/ghép/reframe/overlay/sync/mix/loudness/export, số liệu từ probe. | MIT; upstream công bố 42 tools và MCP contract. Cần FFmpeg 6.1+ / Python 3.10+ theo skill; chưa suy thành local install đã đạt. |
| [Playwright](https://playwright.dev/docs/intro), [microsoft/playwright](https://github.com/microsoft/playwright) | Test DOM và UI web, frame rendering/capture trong công cụ render khi phù hợp; kiểm UI thật bằng locator/readback. | Apache-2.0. Không phải native Revit mouse driver. Trong phiên có `cua_repl`, mọi tương tác UI do agent đi qua API được cung cấp, bao gồm Playwright surface của tab khi có. |

`ffmpeg-skill` chọn cách chỉnh file, không quyết định phim có đẹp hay thông điệp đúng. Khi thực sự áp skill đó, dùng tool/contract của nó theo capability đã kiểm; chưa cài repo thì ghi rõ fallback FFmpeg sẵn có, không báo đã gọi tool của skill. Không tự cài MCP hay thay cấu hình global chỉ vì catalog nhắc tên.

## Pipeline áp dụng cho phim Revit

1. **Astra/đạo diễn:** khóa thông điệp, nhịp kể và các khung cần chứng minh; chọn cơ chế từ nguồn phù hợp, ghi nguồn đã dùng.
2. **Sol/builder:** dàn keyframes/scene từ CAD/Revit thật, dựng Remotion frame-driven, icon/infographic và chuyển động; các tên vai chỉ đưa lên phim khi actual event/capture chứng minh.
3. **HyperFrames:** storyboard, scene sub-compositions, một caption track; kiểm frame/safe zones. Không suy Remotion project là HyperFrames-import compatible nếu chưa thử.
4. **Quay thật:** Codex nhập prompt + skill, Send, highlight Subagents thật, chuyển sang Revit; log `actual_mouse`, `direct_api`, `video_overlay`. Không bịa agent count/status hoặc cursor.
5. **Nhạc/SFX:** chọn/tạo track có quyền sử dụng, khóa beat/cue theo frame; SFX nhấn chọn căn, xuất hiện hệ, nối và đặt sheet. Khớp cảm giác hình, không che lỗi hoặc dùng SFX làm bằng chứng kết nối đã thành công.
6. **FFmpeg:** probe raw và output, xử lý file/mix/export, kiểm duration/fps/codec/sync/loudness và nghe/xem thật. Bản edited giữ phiên bản và hash khác raw.
7. **Reviewer độc lập:** xem keyframes, điểm cắt và bản mix; nghiệm thu media riêng với nghiệm thu native model. Các nguồn tham khảo không thay runtime receipts.

## Trạng thái cục bộ cần đọc trước khi báo đã áp dụng

Project: `projects/revit-sheet-live-demo/`. Evidence: `docs/revit-live-demo-20261110/`. Đọc receipt hiện tại thay vì suy từ file skill. V3 là preview lịch sử không nhạc; yêu cầu hiện tại có music + SFX và exact title ở trên. Các đoạn dựng năm hệ/Coordinator vẫn phải có recording thật.

Lệnh user mới cho phép dọn **file TEST riêng**: `C:/Users/Admin/Documents/MTT.BP01A.TA.MEPF_THÁP A_Rev04-test.rvt`. File tham chiếu `...Rev04_<user>.rvt` được bảo vệ. Đây là quyền dọn phạm vi căn triển khai và bộ bản vẽ trong TEST, không phải quyền ghi toàn project hoặc tự dựng fresh CREATE không kiểm. Dùng manifest/backup/dry-run/cascade review và readback thực tế ở `test-cleanup/`.
