---
name: opus-motion-engineering
description: "Quy trình Motion Engineering viết hoạt họa bằng code (Remotion/HyperFrames) cho JennieJoyKids 3D và NEWTECONS live-action: BRIEF.md theo sự kiện-có-số-frame, cổng 3 ảnh tĩnh, vòng sửa 4 trường với critic độc lập (tối đa 5 sửa/lượt), cue âm thanh trên frame sự kiện, hợp đồng vào/ra giữa cảnh, ffprobe/xem tốc độ thường. Dùng cho title card, flashcard từ vựng, intro/outro, overlay giải thích, clip launch; KHÔNG dùng để sinh footage nhân vật (nhân vật vẫn là ComfyUI local)."
---

**Last updated:** 2026-10-27. Nguồn quy trình: bài [Motion Engineering with Opus 5.5](https://x.com/beamnxw/status/2108616740846420354) (beamnxw) và danh sách prompt cộng đồng [awesome-opus5-5-videos](https://github.com/yihui-dev/awesome-opus5-5-videos). Bài học rút gọn đã có ở [motion engineering lessons](../create-video-jenniejoykids/references/motion-engineering-lessons.md); skill này là **bản chạy được** (vai, mẫu, cổng, lệnh).

Đây là quy trình tăng cường cho [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md) và [jenniejoy-hyperframes](../jenniejoy-hyperframes/SKILL.md). Nó **không thay** hợp đồng điều phối [engine dispatch](../create-video-jenniejoykids/references/engine-dispatch-contract.md): chủ lane vẫn là root/agent ID ghi trong PLAN của phim; tên skill không phải owner.

## 1. Khi nào dùng / không dùng

| Dùng (motion do code vẽ, tái tạo được từng frame) | KHÔNG dùng |
|---|---|
| Title card, intro 3 s (90 f), outro | Sinh footage nhân vật, mặt, khẩu hình, diễn xuất: **ComfyUI local RTX 5080** ([comfyui-video-pipeline](../comfyui-video-pipeline/SKILL.md)) |
| Flashcard từ vựng EN/VI, pill từ khóa hồng `#FF2E7E` | Sinh ảnh/video nhân vật bằng dịch vụ cloud (cấm cho NEWTECONS; JennieJoy theo hợp đồng hybrid riêng, không mở rộng ở đây) |
| Overlay giải thích, lower-third, đếm số, thanh tiến độ | Thay thế gate casting / gate nhân vật |
| Clip launch/teaser cho một tính năng hoặc một tập phim | Tuyên bố phim hoàn thành khi mới có receipt |

Mọi thứ do skill này tạo ra là **component/graphic** đặt lên timeline master. Một component xuất riêng không phải phim hoàn chỉnh.

## 2. E2E ROLE MAP — mỗi vai là MỘT phiên agent riêng

Nguyên tắc OpenAI-Dots của hệ thống: **người làm không tự chấm**. Mỗi vai mở phiên mới, chỉ nhận đúng đầu vào của vai đó.

| # | Vai (phiên riêng) | Đầu vào | Đầu ra (artifact thật) | Route khuyến nghị (xác minh route đang cấu hình, ghi model quan sát được) |
|---|---|---|---|---|
| 1 | **Director / Brief-writer** | Yêu cầu user, script đã chốt, danh sách từ vựng, tài sản thương hiệu | `BRIEF.md` đủ 5 quyết định + bảng sự kiện theo frame ([mẫu](references/brief-template.md)) | Sonnet 5.5 (viết brief); Opus 5.5 root duyệt |
| 2 | **Reference analyst** | `reference.mp4` (nếu có) + 1 mục đích cho mỗi reference | `frames/` (2 fps), ảnh liên tiếp quanh sự kiện, ghi chú quyết định có nhãn fps nguồn | Gemini 3.8 Flash High (vai `explorer`/`tester`, xem cách gọi bên dưới) |
| 3 | **Motion builder** | `BRIEF.md`, tài sản, ranh giới vào/ra cảnh | Composition Remotion/HyperFrames, still 3 ảnh, preview | Sonnet 5.5 (cảnh phức tạp) hoặc OpenCode Go DeepSeek V4.1 `worker` (code theo spec chặt) |
| 4 | **Sound-cue editor** | Bảng sự kiện + file SFX/music rời | Cue list theo frame sự kiện, ducking, stem tách | Sonnet 5.5; kiểm sóng âm bằng đo, không bằng tai một mình |
| 5 | **Independent critic** | Brief + ảnh/frame đã render, **context sạch** (không thấy hội thoại của builder) | ≤ 5 sửa theo [định dạng 4 trường](references/critic-loop.md) + verdict nhị phân PASS/FAIL | Haiku 5.5 (lint/rẻ) hoặc Gemini 3.8 Flash High (QA hình); **không bao giờ là builder** |
| 6 | **Delivery verifier** | File export thật | Biên bản `ffprobe` + xem tốc độ thường + SHA256 | Gemini 3.8 Flash High / Haiku 5.5 chạy lệnh; root đọc lại output |

**Cách gọi route (đo 2026-10-27, R27 — đọc lại `router-mix.mjs list` trước mỗi đợt):**
- Claude (Sonnet 5.5 / Haiku 5.5): tool `Agent` của Claude Code với `model: sonnet|haiku`.
- Gemini 3.8 Flash High = vai `explorer`/`tester` → `custom/oauth-anti-gemini-flash-high`; DeepSeek = vai `worker` → `opencode-go/deepseek-v4.1-flash` (cấu hình `C:/Users/Admin/.codex/codex-router/astra-router-mix.json`).
- Đường chuẩn: `L:/61.SetupAgent/codex_router/tools/harness-cli.ps1 -Executor windows -Vai <vai> -KiemTra` rồi chạy thật. Nếu harness dừng ở recall (`harness-precode-recall-venv-missing` trong error-db của create-video-jenniejoykids), dùng `Get-Content brief.md -Raw | codex exec -m <slug> -c model_reasoning_effort=high -s read-only|workspace-write -C <dir> --skip-git-repo-check --json -o final.md` và ghi rằng không có biên nhận 4 bằng chứng của harness.

Root là **Opus 5.5 orchestrator**: giữ PLAN, GPU queue, tích hợp, và **tự chạy lại** mọi cổng mà sub-agent khai `PASS` (lời khai chỉ là tham khảo). Bảng route là khuyến nghị theo năng lực hiện có, không ghim model vĩnh viễn; nếu route không có, nói rõ model thực tế đã dùng, không âm thầm thay.

Giao việc cho mỗi sub-agent theo 6 phần của quy ước hệ thống: ĐỌC TRƯỚC · VIỆC · RÀNG BUỘC CỨNG · CỬA NGHIỆM THU (output chạy thật) · PHẠM VI FILE (không hai agent cùng sửa một file) · "CHỖ NÀO BẠN ĐOÁN — NÓI THẲNG".

## 3. Quy trình theo thứ tự

1. **Brief trước, code sau.** Director viết `BRIEF.md` ([mẫu](references/brief-template.md)). Chưa có brief thì builder chưa được mở.
2. **Reference có việc làm** (tùy chọn). Mỗi reference chỉ trả lời MỘT câu: card vào thế nào / chuyển cảnh giữ chủ thể ra sao / hold bao lâu. Lấy mẫu 2 fps để nhìn tổng quan, rồi lấy các frame liên tiếp quanh sự kiện. Ước lượng vị trí của model chỉ gần đúng; đối chiếu với ảnh đã tách.
3. **Cổng 3 ảnh tĩnh** (xem §5) trước khi chỉnh chi tiết chuyển động.
4. **Dựng chuyển động** từng cảnh; sau mỗi cảnh render still + khoảng quanh biên cảnh.
5. **Critic độc lập** ≤ 5 sửa/lượt → builder sửa cục bộ → render lại đúng phần bị sửa ([vòng sửa](references/critic-loop.md)).
6. **Cue âm thanh** gắn vào frame sự kiện (§7), kiểm tai nghe và loa điện thoại.
7. **Export đúng bản được duyệt**, `ffprobe`, xem ở tốc độ thường từ đầu đến cuối.
8. **Lưu cùng nhau**: brief, bảng thời gian cảnh, cue list, hash, ghi chú bản đã duyệt.

## 4. Viết cảnh như SỰ KIỆN có số frame

Mỗi cảnh = chuỗi sự kiện người xem theo dõi được: trạng thái đầu → hành động → kết quả → **hold đọc**. Viết giây trước, đổi sang frame theo fps, **luôn kèm nhãn fps** (số frame vô nhãn là sai).

- JennieJoyKids: 30 fps. `frame = round(giây × 30)`: 0,6 s = 18 f; 3,0 s = 90 f; 12 s = 360 f.
- Frame cục bộ trong `<Sequence from=G>`: `global = G + local` (local 30 trong sequence bắt đầu ở 120 = global 150). Luôn gắn nhãn `local`/`global`.
- Mỗi sự kiện có: `id`, `frame`, `chủ thể`, `hành vi`, `đích`, `thời lượng`, `tham số spring` (duration/damping/stiffness/overshoot), `cue âm thanh`. Gom entrance offset, đích, thời lượng, spring vào **một khối hằng số** để một lần sửa chỉ chạm một chỗ.
- Hold đọc tính từ lúc chữ **đọc được**, không từ lúc bắt đầu vào. Đọc to ở tốc độ thường; hold nào hết trước khi đọc xong thì kéo dài. Với trẻ 2–4 tuổi, từ vựng cần hold dài hơn mức người lớn đọc nhanh; chốt số trong brief rồi đo (không có số thì ghi "chưa đo").
- Khi hold đọc đang chạy, chuyển động phụ phải yên để chữ là tâm điểm. Một đối tượng chính vào trước, thông tin phụ vào trễ ~3 f (0,1 s) rồi chỉnh trong lúc xem.
- Mọi biến thiên ngẫu nhiên lấy từ **seed cố định**. Không CSS transition/animation, không `Date.now()`, không `Math.random()` không seed: chuyển động chỉ lái bằng `useCurrentFrame()` + `interpolate`/`spring`. Mỗi frame phải render ra đúng như nhau ở mọi lần.
- Scale/mờ nhẹ kiểu "push": chỉ định tổng thay đổi theo thời gian (vd 1,00 → 1,03 trong 3 s), không dùng phần trăm lặp mỗi frame (cộng dồn).

## 5. Cổng 3 ảnh tĩnh (trước mọi chỉnh chuyển động)

Render ảnh MỞ ĐẦU, ảnh KẾT QUẢ (chốt vật chính/ chữ cần học), ảnh KẾT THÚC. Duyệt thông điệp và bố cục trước khi tinh chỉnh chuyển động:

- Chữ chính có đọc được? (kiểm **bản dài nhất**: từ dài nhất, bản dịch VI dài nhất, tiêu đề dài nhất; wrap sang dòng thứ 3 thì dừng chuyển động, rút ngắn/mở hộp/tách cảnh)
- Kết quả có nhìn thấy, không bị che/cắt/chồng?
- Khoảng trống cho logo, caption song ngữ EN/VI, vùng an toàn?
- Đổi tiêu đề thì **render lại frame đáp** trước khi xem lại entrance.

Thứ tự ưu tiên khi sửa: thiếu thông tin / chữ không đọc được → thời gian → chi tiết thị giác.

## 6. Hợp đồng ranh giới cảnh (scene boundary)

- Mỗi cảnh khai **trạng thái vào** và **trạng thái ra** (vị trí, scale, trường được highlight, khung giữ lại). Với chuyển liên tục, trạng thái ra của cảnh trước là trạng thái vào của cảnh sau.
- Font, bảng màu, khoảng cách, phần tử lặp nằm trong **cài đặt chung**; ngoại lệ của một cảnh phải ghi tường minh.
- Chuyển cảnh chồng nhau phải tính phần chồng vào tổng thời lượng theo manifest của chính phim. Ngoại lệ JennieJoy: TransitionSeries is not used for the JennieJoy master: any overlap > 0 shortens the total below 2520 f; transitions are tail-handle overlays inside a fixed 2520 f timeline. Phần đuôi (tail handle) của cảnh ra phủ lên cảnh vào, frame bắt đầu của mọi WAV không đổi ([quy tắc Remotion §3](../jenniejoy-remotion/SKILL.md#review-cut-motion-layer-user-mandated-2026-10-27-domain-jenniejoy_cartoon_3d)).
- Sửa cục bộ xong phải xem **cả hai** biên lân cận trước khi xem phim ghép; render từng đoạn quanh biên bằng `--frames=a-b` ([lệnh](references/critic-loop.md)).
- Component dùng lại (entrance, pill, card) lưu lại; xem lại timing khi đổi tài sản hoặc chữ.
- JennieJoy review cut/master: mỗi ranh giới cảnh còn phải có chuyển cảnh được thiết kế (không hard cut vô cớ), cầu nối hành động khi đổi địa điểm và kiểm trên render chuyển động quanh ranh giới, theo [Review-cut gates](../create-video-jenniejoykids/SKILL.md#review-cut-gates-user-mandated-2026-10-27) (G-CUT, G-BRIDGE, G-END).

## 7. Âm thanh có frame sự kiện

- Click đặt đúng frame nhấn nhìn thấy được; nhấn mạnh nhất của âm "reveal" đặt đúng frame reveal hình. File có lead-in/ lặng đầu thì đo đỉnh âm bằng sóng + nghe, rồi **offset clip** cho đỉnh rơi đúng frame sự kiện.
- Ghi cue cạnh sự kiện hình: `event_id | frame (nhãn fps) | file | offset | gain`.
- Dialogue, music, SFX/Foley là stem **riêng**; ducking nhạc -14 đến -18 dB dưới lời thoại theo [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md). Không trộn music vào SFX.
- Kiểm tiếng to nhất, cue nhỏ nhất còn hữu ích, và phần kết trên tai nghe và loa điện thoại. Tuyệt đối không tự cắt khoảng lặng lời thoại ở Remotion: quy tắc "trim một lần ở upstream" của jenniejoy-remotion vẫn thắng.

## 8. Biến thể theo dự án

| | JennieJoyKids (`jenniejoy_cartoon_3d`) | NEWTECONS (`newtecons_live_action`) |
|---|---|---|
| Master | 30 fps, 3840×2160 (2K 2560×1440 = lanczos downscale của Master 4K đã hoàn thành (downscale: PLAN T-V10; lanczos: `editorial/master-4k-v001/DOWNSCALE-2K.md`); không có lượt SeedVR2 2K riêng) | Theo manifest của chính phim NEWTECONS ([create-video-newtecons](../create-video-newtecons/SKILL.md)); không ghi số khung/fps ở đây khi chưa trích được từ manifest |
| Phong cách chữ | Pill hồng đậm `#FF2E7E`, chữ trắng đậm; caption song ngữ EN/VI | Chữ doanh nghiệp theo bộ nhận diện NEWTECONS; logo gốc, không dùng logo/asset hoạt hình |
| Nhân vật | Chỉ dùng ảnh cast đã duyệt hash ([casting gate](../create-video-jenniejoykids/references/character-casting-gate.md)) | Footage CHAR_01–08 do ComfyUI local; skill này chỉ làm overlay/title/lower-third |
| Chặn | Không trộn asset NEWTECONS | Không trộn asset JennieJoy; không dùng cloud sinh footage |

## 9. Cổng nghiệm thu

1. **Receipt ≠ acceptance.** Có file/hash/job ID chưa có nghĩa đạt. Đạt khi critic độc lập đã soi artifact thật (still, frame range, file export) và ra PASS.
2. **Critic không bao giờ là builder**, và không nhận hội thoại của builder (context sạch). Sub-agent tự khai PASS thì root chạy lại cổng.
3. **Một gap lớn nhất mỗi vòng** khi vòng sửa kéo dài; thoát khi cổng xanh, không thoát theo số vòng. Hết ngân sách hoặc user dừng: báo trạng thái thật.
4. **Cổng phải chạm chỗ hai bản tách nhau** (vd từ dài nhất, không chỉ từ ngắn; frame sát biên cảnh, không chỉ giữa cảnh).
5. **Still không chứng minh được chuyển động, khẩu hình, cảm giác nhịp.** Phần đó chỉ được tuyên bố sau khi xem tốc độ thường.
6. **Delivery verifier** `ffprobe` bản export: độ phân giải, `r_frame_rate`, số frame/thời lượng, luồng audio. JennieJoy master phải đúng 3840×2160, `30/1`, 2520 frames (84 s) và không được gọi là Master khi còn slot giữ chỗ.
7. **Review-cut gates (2026-10-27).** Với review cut/master JennieJoy phải qua đủ G-CAP, G-ICON, G-CUT, G-BRIDGE, G-END, G-MOTION ([định nghĩa](../create-video-jenniejoykids/SKILL.md#review-cut-gates-user-mandated-2026-10-27)); critic phải xem render chuyển động quanh mọi ranh giới và phần kết, đối chiếu timing với word-timing JSON ([critic-loop §7](references/critic-loop.md)). Still không đủ.
8. **Prompt cộng đồng chỉ là điểm xuất phát.** Không chép thân prompt dài; xem [chỉ mục](references/awesome-opus55-prompt-index.md) về giấy phép và cách thích nghi.

## 10. Tham chiếu

- [references/brief-template.md](references/brief-template.md): BRIEF.md (JennieJoyKids + ghi chú NEWTECONS).
- [references/awesome-opus55-prompt-index.md](references/awesome-opus55-prompt-index.md): chọn và thích nghi prompt.
- [references/critic-loop.md](references/critic-loop.md): định dạng sửa, vòng sửa, lệnh Remotion/ffmpeg/ffprobe.
- Template Remotion có sẵn trong repo: [remotion-template](../create-video-jenniejoykids/assets/remotion-template/) (dùng lại package đã cài, không cài renderer mới).
- Cập nhật skill này là hoàn thiện quy trình biên tập đã kiểm chứng; không phải huấn luyện lại trọng số model.
