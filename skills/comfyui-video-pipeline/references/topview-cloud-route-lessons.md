# Bài học từ đường Topview (WAN 3.0 / MiniMax H3) → áp cho ComfyUI local

Đo thật 15–16/11/2026, Cảnh 5 (phòng làm việc AI) và Cảnh 1 (mở đầu) phim NEWTECONS.
Mã chạy được: `docs/media-stage/S05-OFFICE-REBUILD-V001/video/run_wan.py`, `run_h3.py`, `assemble_v4.py`;
`docs/media-stage/S01-INTRO-REBUILD-V001/video/run_wan.py`.

## 1. Đường cloud đã đo

| Model (Topview Platform API) | Endpoint | Giá đo (`charged_usd`) | Thời gian/clip | Nhận gì |
|---|---|---|---|---|
| WAN 3.0 image-to-video, 720P, có tiếng | `/models/alibaba/wan-3.0/image-to-video/predictions` | **$0,0618/giây** (3 s = 0,1853; 4 s = 0,2471; 5 s = 0,3088) | 108–141 s | `first_frame`, `last_frame` tuỳ chọn, `duration` 3/4/5, `audio:true` |
| MiniMax H3, 768P | `/models/minimax/minimax-h3/image-to-video/predictions` | 0,149–0,179 $/clip (~$0,03/giây) | — | ảnh + **`reference_audio`** (khẩu hình khớp file giọng) |
| Seedance 2.5 | (chưa chạy) | bảng giá $0,1965/giây | chưa đo | — |

- **WAN 3.0 KHÔNG nhận file giọng** (`reference_audio` ⇒ 400 `UNSUPPORTED_GENERATION_INPUT`). Nó tự sinh giọng **mới mỗi clip** ⇒ cùng nhân vật khác giọng giữa các shot.
- H3 trên Topview bị **429 (quá số việc đồng thời)** ⇒ vòng thử lại tối đa 40 lần, chỉ thử lại khi lỗi là 429.
- Khoá `TOPVIEW_API_KEYnew` chỉ nằm trong `.env` (gitignored). Không dán vào chat/file.

## 2. Quy trình rút ra (dùng cho CẢ cloud lẫn ComfyUI local)

1. **Storyboard Cảnh → Shot được duyệt từng ảnh trước** (xem skill create-video-newtecons). Mỗi shot = một ảnh khung đầu đã duyệt.
2. **Một receipt mỗi clip**, ghi `task_id`/`prompt_id` NGAY khi gửi, kèm `Idempotency-Key`. Chạy lại script **không bao giờ gửi lại** clip đã có task id; chỉ hỏi lại trạng thái. Đây là thứ cứu tiền khi script chết giữa chừng.
3. **Prompt video = 4 khối**: (a) máy quay + chuyển động cụ thể (Steadicam theo sau, máy thấp mắt cá, đẩy vào chậm…); (b) thoại tiếng Việt trong ngoặc kép + câu giọng (`natural Vietnamese, northern accent, lips in sync`); (c) dòng **Sound:** liệt kê từng tiếng (bước chân khớp gót, khoan, máy cắt, hô gọi, cộp nón…); (d) khối LOOK chống "vẻ AI" + `No subtitles, no captions, no music`.
4. **720p trước, user duyệt clip, rồi mới nâng cấp local** (SeedVR2). Không upscale clip chưa duyệt.
5. **Giọng nhất quán**: giọng WAN mà user khen thì cắt 3–20 s, clone sang VoiceStudio (skill newtecons-voice-studio), thu lại mọi câu của nhân vật bằng giọng đó, rồi tạo hình bằng **H3 có `reference_audio`** (Topview hoặc graph H3 local).
6. **SFX/foley không phó mặc model video**: tiếng do WAN sinh giữ làm nền, tiếng chính (bước chân, cú đặt nón, khoan/cắt, giám sát hô) lồng tại máy theo mốc khung hình. Câu hô của giám sát thu bằng VoiceStudio (tiếng người phải rõ chữ).
7. **Đổi ảnh khung sau khi đã gửi clip = clip đó bỏ.** Chỉ gửi video khi MỌI shot của cảnh đã duyệt và đã soát đồng nhất giữa các shot (16/11: K0 bị bác vì gile khác K1 sau khi clip đã gửi, mất $0,25).
8. **Ảnh shot đã duyệt làm Image 1 cho shot kế bên** để giữ cùng bối cảnh + trang phục (K0 V002 lấy K1 đã duyệt làm chuẩn).

## 3. Ánh xạ sang ComfyUI local (RTX 5080, :8188)

| Việc | Cloud (đã đo) | Local tương đương | Trạng thái local |
|---|---|---|---|
| Ảnh → video có khẩu hình theo file giọng | H3 Topview | graph `NEWTECONS_H3_R2V_LIVE_ACTION_v008-c2turbo.api.json` (node 5/31 ảnh ref, 8 khung đầu, 7 audio, 6 = 1280×704 length 124, 19 prompt) | chạy được (cảnh 6 Cảnh 5, 15/11) |
| Ảnh → video có tiếng tự sinh | WAN 3.0 | **chưa có** graph WAN local đã kiểm | chưa đo; không gọi đây là local |
| Nâng 720p → 2K/4K | — | SeedVR2 7B video graph (`seedvr2/S05_C6_seedvr2_2560.api.json`) | **2560×1408 làm sập ComfyUI 16/11 00:43** (container tự bật lại, OOMKilled=false); thử lại ở cỡ nhỏ hơn hoặc tile nhỏ hơn và ĐO trước khi chạy hàng loạt |
| SFX | — | Stable Audio 3 small-SFX (đã có model, skill jenniejoy-music-sfx-yue mô tả graph) | dùng chung hạ tầng; cue sheet NEWTECONS để riêng thư mục |

Luật local giữ nguyên: lưu graph chỉnh sửa được vào `production-local/ComfyUI/user/default/workflows/ProjectStudio5 - Film Newtecons/02 Workflow Video/<CẢNH>/`, receipt có hash output, hỏi user trước mỗi lượt GPU nặng. Script chờ phải kiểm `docker ps` khi `/history` trả rỗng: rỗng có thể là ComfyUI vừa sập chứ không phải "đang chạy".

## 4. Luồng local song song (16/11, Cảnh 1)
- Stable Audio 3 small-SFX local: 4 file 3–4 s, lần đầu 30 s (nạp model), sau đó ~10 s/file; mean −29…−33 dB, đỉnh −7…0 dB.
- H3 local `ref2va` có `MiniMaxH3AddGuide(image, audio)`: không có thoại thì đưa **SFX** làm audio dẫn để chuyển động khớp tiếng (gót chạm sàn, cú đặt nón). Độ dài khung: 4 s ⇒ `length 100`, 3 s ⇒ `76` (bội 8 + 4, 24 fps). Ref ảnh: gile thật + nón V004.
- Lỗi thấy ở WAN 3.0 không thoại: người rời khung cuối clip rồi model tự thêm người lạ (gile vàng); vật cận cảnh (nón) biến hình khi prompt đòi «xô, lắc». Cách tránh đang thử: câu «keep him in frame until the end», bỏ «rocks» khỏi vật có logo.

## 5. Phán quyết user 16/11 (Cảnh 1) — luồng nào thắng
- **Tiếng**: chốt tiếng WAN 3.0 tự sinh trong clip Topview. Stable Audio 3 local làm audio dẫn cho H3 ⇒ user: «bị tiếng sai, không dùng comfyui làm tiếng». Graph SFX local chỉ còn là thử nghiệm, không vào bản dựng NEWTECONS.
- **Giọng hô**: WAN tự sinh (clip SH0_BUSY_V2) thắng 2 giọng VoiceStudio. Khi chạy lại shot có giọng đã chốt: giữ nguyên câu thoại + mô tả giọng («strong, loud, commanding northern Vietnamese male voice»); nếu giọng mới yếu hơn thì lồng lại track tiếng cũ (`voice/` hoặc `audio/GIAMSAT_giong3_WAN_shot0.m4a`).
- **Hình**: Shot 1, Shot 2 V2 Topview chốt. H3 local chưa đạt (mờ, sai diễn, nón méo) ⇒ chỉ tham khảo.
- **Vật đập «2 nhịp»**: tránh «jolts / rocks / rattles / settles»; viết «ONE single impact, exactly once… stays completely still» cả ở hành động lẫn dòng Sound.

## 6. Cảnh 4 (16/11) — giọng GĐĐH, H3 8 s, màn hình ghép
- **So 2 giọng cùng khung**: bản A H3 + giọng VoiceStudio local (`51e40994`) vs bản B WAN 3.0 tự sinh ⇒ user chọn **B** («giọng mạnh nội lực»; giọng local «trẻ quá»). Giọng B đã nhân bản sang VoiceStudio `c7c16006` (`NTC_GDDH_MienBac_WAN_S04_v001`) để dùng lại.
- **H3 Topview nhận `duration: 8`** (768P, $0,2388/8 s); bị 429 «busy» 6 lần liền khi chạy song song WAN — runner chờ 30 s/lần rồi nhận, không mất tiền.
- **WAN 5 s với câu ~25 âm tiết**: nói kín 5,04 s, không có lặng cuối ⇒ nguy cơ cụt đuôi; user nghe duyệt được. Câu dài hơn ~20 âm tiết thì báo user.
- **Đồng thanh tập thể** «Dạ, tụi em rõ ạ!» chạy được bằng WAN 4 s ($0,247): ở giây 1,8 mọi người cùng mở miệng.
- **Màn hình bản đồ/KPI**: chạy video trên khung MÀN XANH rồi ghép từng khung — [screen-map-kpi.md](../../studio-video-engine/references/screen-map-kpi.md).
- VoiceStudio `instruct` (mô tả «middle-aged…») đi cùng profile clone ⇒ HTTP 500; muốn giọng già hơn thì đổi profile hoặc hạ tông `rubberband formant=preserved`.
