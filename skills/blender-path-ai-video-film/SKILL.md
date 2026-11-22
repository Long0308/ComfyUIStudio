---
name: "blender-path-ai-video-film"
description: "Dựng phim nhân vật bay theo path (rồng…) bằng Blender làm không gian tham chiếu + Higgsfield/ComfyUI render theo chuỗi ảnh đầu–cuối, hậu kỳ chữ/logo/SFX trên máy và ghép theo storyboard."
---

# Phim nhân vật bay theo path: Blender → Higgsfield / ComfyUI → ghép

Dùng khi cần một phim 1–3 phút có nhân vật CGI (rồng, linh vật) bay qua nhiều bối cảnh: bản đồ, thành phố, toà nhà có mô hình IFC, công trình chỉ có ảnh render. Đúc kết từ phim GIA BÌNH DRAGON (11/2026, 153 giây, 720p).

## Vai trò từng công cụ

- **Blender = không gian tham chiếu**, không phải bản render cuối. Giữ: stage theo tỉ lệ thật (toà nhà từ IFC đặt ở gốc, bản đồ và sân bay đặt ở stage riêng), anchor, `PATH_*` cho đường bay, camera `CAM_Sxx` gắn marker timeline, nhân vật proxy chạy theo path, mốc sự kiện (chạm đất, ngậm ngọc, cất cánh). Xuất guide 720p theo shot và **pass riêng khớp camera** (matte toà nhà, logo trên mặt kính) để hậu kỳ.
- **Higgsfield = render hình đẹp.** Seedance 2.5 cho cảnh nhân vật chuyển động mạnh (múa, bay nhanh, đáp, cất cánh). Wan 3.0 cho ảnh → video nhẹ và cầu nối ngắn. gpt_image_2_6 để tạo ảnh chốt (đặt nhân vật vào ảnh render có sẵn). mirelo_text_to_audio cho SFX.
- **ComfyUI local = phương án không tốn credit** cho shot ảnh đầu → ảnh cuối (MiniMax H3 fl2va). Chậm hơn nhiều, cần kiểm bối cảnh kỹ.
- **Hậu kỳ trên máy (Python + ffmpeg):** logo mở đầu, đếm số, tiêu đề, địa danh, nhãn khu vực, chuyển cảnh đồ hoạ, phát sáng, thông điệp cuối. Chữ luôn là lớp riêng có alpha.

## Nguyên tắc đã chốt với người dùng

1. **Chuỗi ảnh đầu–cuối.** Shot n chạy từ ảnh chốt n đến ảnh chốt n+1. Ảnh chốt lấy từ khung cuối / khung đầu của clip liền kề, hoặc từ ảnh render thật của người dùng. Không ghép hai clip rời rồi hy vọng liền mạch.
2. **Tận dụng clip đã có.** Khi người dùng góp ý, chỉ thêm cầu nối và cảnh mới; không render lại toàn bộ.
3. **Chạy thử trước khi chạy đại trà.** 2–3 shot đại diện, gửi bảng khung hình + bản ghép thử, báo credit còn lại, chờ duyệt.
4. **Khác bối cảnh thì dùng chuyển cảnh đồ hoạ** (ngọc loé, loé sáng); cùng mạch bay thì dùng shot nối tốc độ cao (xuyên mây) thay cho cắt. **Một hiệu ứng (hoặc một tệp SFX nghe rõ như nhau) dùng tối đa 2 lần mỗi phim**; lần thứ 3 đổi hiệu ứng cùng ý nghĩa hoặc bỏ, và mỗi lần nhân vật chạm đất phải khác nhau. Đếm bằng bảng kiểm `KIEM_HIEU_UNG_LAP` trước mỗi bản dựng (v4m: ngọc loé 3 lần, SFX flyby 6 lần). Chèn chuyển cảnh: skill `hyperframes-add-transition`.
5. **Nhân vật chạm đất ở mỗi khu vực** rồi mới bay tiếp: ảnh chốt của khu vực là nhân vật đang đứng trên nền ở đó.
6. **Luôn có storyboard** (`storyboard_<bản>.json` + bản `.md`) là nguồn duy nhất: mã shot, giây vào–ra, tệp nguồn, model, ảnh đầu → ảnh cuối, lớp chữ, SFX. Ghép phim đọc từ tệp này.
7. **Mỗi lần giao là một bản có hậu tố mới** (v2, v3, v3b…), không ghi đè; giao bản 720p đầy đủ, không giao bản nén thấp hơn trừ khi người dùng hỏi.
8. Nói rõ: chỉ kiểm bằng khung hình và số đo mức âm, không nghe được âm thanh.

## Quy trình

### 1. Blender
- Dựng stage, path, camera, marker theo storyboard gốc. Render guide theo shot (nền, matte nhân vật, lớp nhãn).
- Cần logo hay chữ bám vào công trình trong clip AI: tạo scene phụ chỉ có camera của shot + mặt phẳng logo (hoặc mesh công trình phủ trắng làm matte), render dãy khung trong suốt hoặc nền đen, rồi chồng lên clip. Chỉ khớp khi clip AI giữ hình học của guide (chế độ edit / video reference).

### 2. Ảnh chốt
- Trích khung đầu/cuối clip: `ffmpeg -sseof -0.1 -i clip.mp4 -frames:v 1` (cuối), `-frames:v 1` (đầu), scale 1280×720.
- Ảnh render của người dùng: cắt 16:9, 1280×720. Đặt nhân vật vào bằng gpt_image_2_6 với 2 ảnh tham chiếu (ảnh nền + ảnh nhân vật chuẩn), prompt "keep image 1 EXACTLY… add the dragon from image 2…", ghi rõ WINGLESS, kích cỡ nhân vật, đang bay hay đã chạm đất.
- Ảnh có chữ sẵn: xoá chữ bằng model ảnh, chữ dựng lại thành lớp phủ.

### 3. Tải ảnh lên Higgsfield khi không có shell trên máy người dùng
- `media_upload` → URL ký sẵn. PUT phải chạy **trên máy người dùng bằng curl.exe** (qua Python của Blender: `subprocess.run(["curl.exe","-X","PUT","-H","Content-Type: image/jpeg","--data-binary","@file",url])`); urllib bị Cloudflare chặn 1010. Sau đó `media_confirm`.
- Kết quả tải về cũng bằng curl.exe trên máy người dùng.
- ffmpeg/ffprobe gọi bằng đường dẫn đầy đủ; tiến trình dài chạy tách rời (`creationflags=0x00000008|0x08000000`), ghi log có dòng DONE rồi thăm lại.
- Không quét cả ổ đĩa bằng `os.walk` trong Blender: làm Blender treo. Chỉ kiểm các đường dẫn cụ thể.

### 4. Sinh video
- Seedance: `mode: omni_reference`, `start_image`, `end_image`, 4–5 giây, 720p. Prompt: "One continuous shot, no cuts. Starts exactly on the first frame and ends exactly on the last frame…", mô tả hành động theo thứ tự, camera, "No wings at any time", dòng Sound.
- **Không thêm ảnh tham chiếu nhân vật có bối cảnh khác** khi đã có ảnh đầu và cuối: cảnh sẽ lạc sang bối cảnh của ảnh tham chiếu.
- Wan: `start_image` (+ `end_image`), không kèm ảnh tham chiếu. Gặp 429 thì gửi lại sau.
- Sau mỗi clip: bảng khung hình (6–10 khung), so khung đầu/cuối với clip liền kề và kiểm bối cảnh.

### 5. ComfyUI local (MiniMax H3 fl2va)
- Graph API: UNETLoader `minimax_h3_fl2va…` → MiniMaxH3SigmaShift (video 12, audio 3) → MiniMaxH3ImageToVideo (prompt, 1280×704, length 124, first_frame, last_frame) → KSampler (20 bước, cfg 4, euler/simple) → VAEDecode + VAEDecodeAudio → CreateVideo 24 fps → SaveVideo. Negative bằng CLIPTextEncode.
- Ảnh vào đặt trong thư mục `input` của ComfyUI, scale 1280×704. Số khung theo lưới 17k+5.
- Đo được ~18,5 phút cho 124 khung trên card 16 GB. Một lần một job.
- Gửi lệnh: dùng công cụ gửi có khoá của người dùng; nếu nó lỗi thì **dừng và hỏi**, chỉ gửi thẳng `POST /prompt` khi người dùng cho phép, sau khi kiểm hàng đợi trống.
- **Ảnh đầu phải thấy rõ bối cảnh.** Ảnh đầu là cận cảnh thì model tự bịa nền khi lùi máy. Prompt ghi địa điểm cụ thể, "same location from start to end", negative liệt kê thứ không được có (street, road, trees…).
- Muốn so chất lượng: chạy song song cùng ảnh đầu–cuối trên Seedance, lấy bản Seedance làm chuẩn để chỉnh prompt/thông số ComfyUI, ghi kết quả vào tệp bài học.
- **Dựng lại cả phim bằng ComfyUI local (từ 18/11, theo cảnh từ đầu):** nguồn chỉ là ảnh chốt đã tạo trên Higgsfield + prompt video Higgsfield của shot đó, không lấy khung từ video Higgsfield. Shot có path Blender phải bám path: guide Canny từ render Blender → ControlNet H3 (`MiniMaxH3FunControlNetApply`, strength 0,7). Shot chưa có path thì hỏi dựng path hay chạy ảnh chốt + prompt. Benchmark với bản Higgsfield lượt cuối (bảng chuẩn hybrid, sau này thêm TopView AI). Chỉ gửi theo hàng đợi đã duyệt (`05.ComfyUI/00.Hang_doi/HANG_DOI_<bản>.csv`), Manual từng job hoặc Auto theo cảnh, luôn 1 job một lúc; dừng khi lỗi hoặc hết cảnh. Cây workflow/output, nút KẾT QUẢ, cấu hình RAM máy (WSL 48GB + swap 16GB ổ C, container 40g, `--disable-pinned-memory`) và cách gửi job: skill `studio-video-engine`, mục "Cây workflow ComfyUI theo kịch bản" và các mục ngay sau. Khi render: đóng Blender, tạm dừng VoiceStudio.
- **Làm lại một shot đã duyệt bằng local (18/11, SC06_SH04_GB2, v01 → v05):** chỉ ảnh đầu + ảnh cuối thì H3 tự bịa đường đi (v01: rồng không bay). Thêm `MiniMaxH3AddGuide` nối tiếp sau `MiniMaxH3ImageToVideo`, mỗi node một khung lấy từ clip đã duyệt (ảnh 1280×720, `frame_idx` = khung gốc × 124/121). Đặt neo dày ở đoạn hành động nhanh: 3 neo mất rồng ở đoạn xuyên kính; 6 neo đủ mạch nhưng cú đạp chân ra khói trắng; 9 neo (thêm đúng các khung của hiệu ứng 94/98/104) + tả hiệu ứng bằng chữ trong prompt ("thin ring of golden light spreads flat… no smoke, no dust, no steam"; `BasicGuider` không có negative) thì khớp gốc. 960×544 ~5 phút nhưng xem toàn màn hình mềm hơn Higgsfield; bản giao chạy 1280×704 (~13,6 phút, độ nét Laplacian 141 so gốc 108) rồi SeedVR2 ×2 chia đoạn 29 khung chồng 4 khung (không nâng RAM). Đây là chạy lại có neo, không phải retrain. Mỗi workflow video có node xanh "KẾT QUẢ vNN" (LoadVideo trỏ bản đã render chép vào input) để mở workflow là thấy kết quả. So các bản bằng trang benchmark (kéo chia đôi / cạnh nhau / tất cả, nhảy theo nhịp, bảng ✓/✗, chuyển động, độ nét).
- **Ảnh chốt bằng Krea2 (local):** `Krea2EditModelPatch` + LoRA identity_edit (ref_boost 2, 1536×864, 14 bước) → general_edit (phát sáng) → SeedVR2 7B lên 2560×1440. Ảnh tham chiếu nhân vật phải cùng hướng đầu với cảnh đích (lật ngang nếu cần), dùng ảnh cắt gốc.
- **Đặt tên theo cảnh:** ảnh chốt `SCxx_Knn` (đánh số trong cảnh), shot `SCxx_SHnn_<ID>` = `Kaa → Kbb`, shot cùng mạch dùng lại đúng K cuối của shot trước; khung neo `SCxx_SHnn_N<khung>`; workflow `SCxx_SHnn_<ID>_{IMG,VID}_vNN_<model>_Kaa-Kbb[_neoN].json`; bảng chuỗi ở `CHUOI_CANH_SHOT_ANH_<bản>.md`. Phim mới dùng khung chuẩn của skill `film-project-structure` (SQ/SH bước 10).

### 6. Lớp dựng trên máy
- Video nền đen hoặc `.mov` codec png có alpha, 1280×720 @24. Mỗi loại một script để sửa chữ không phải render lại hình: mở đầu (logo ráp từ mảnh kim loại, loé sáng ra màu thật, tan thành hạt ráp thành số, chỉ hai số cuối lật), tiêu đề/địa danh/nhãn, chuyển cảnh, kết (toà nhà toả tia sáng, số năm đặt một bên, thông điệp hiện bên dưới, chuyển đen sâu, thông điệp 2, logo).
- Chữ tiếng Việt: font Be Vietnam Pro; từ khoá màu vàng, còn lại trắng; có bóng mờ để đọc được trên nền sáng.
- Logo: chỉ dùng tệp người dùng cấp.

### 7. Ghép (`assemble_vN.py <BASE> <TAG>`)
- Mỗi shot: fps 24, scale 1280×720, cắt đúng số khung, chồng lớp logo/chữ, nửa chuyển cảnh ở đầu/cuối shot → tệp part. Nối bằng concat copy. Xuất hai bản: master không chữ và bản có chữ.
- **Chuyển cảnh chồng ở tầng shot**, không chồng ở lượt cuối (chồng nhiều lớp lệch giờ ở lượt cuối làm rớt khung).
- Đường dẫn ffprobe đặt riêng, không suy từ đường dẫn ffmpeg bằng thay chuỗi.
- **Âm thanh:** tiếng gốc clip Seedance/Gemini rất nhỏ (−23…−26 dB), Wan to (−9 dB) → cân từng clip về −18 LUFS trước khi trộn; nhạc 0,5; SFX riêng theo mốc trong storyboard; loudnorm cuối −14. Nhạc ngắn hơn phim thì nối đuôi một bài cùng bộ bằng crossfade.
- Sau khi ghép: kiểm số khung = tổng storyboard, bảng khung hình ở các mốc cắt và mốc chữ, đo mức âm.

### 8. Giao và ghi nhận
- Gửi bản 720p vào chat; tệp lớn chuyển từ máy người dùng có thể quá thời gian, thử lại một lần.
- Cập nhật storyboard `.md` vào Project, ghi credit trước/sau, shot nào làm lại và vì sao.

## Ba tầng ghép: sửa ở tầng nào thì chỉ chạy lại tầng đó

Giữ ba tầng tách nhau để mỗi lần sửa chạy lại ít nhất:

1. **Hình nền** (`assemble_vN.py`, ffmpeg, vài phút): các shot + chuyển cảnh ngọc + mở đầu/kết dựng sẵn, xuất bản không chữ và `parts_<TAG>/concat_clean.mp4` (tiếng gốc của clip). Chỉ chạy lại khi đổi shot, thứ tự, tốc độ.
2. **Lớp HyperFrames** (`make_hf_post.py <B> <TAG>` → `hf_post_<TAG>/index.html`, render vài phút): tiêu đề, địa danh, nhãn, hiệu ứng nền, video chồng kiểu screen (nhân vật trên nền đen), và mọi clip âm thanh. Chỉ render lại khi đổi chữ hoặc hình chồng. Storyboard có `parts_tag` để dùng lại hình nền của bản trước.
3. **Âm thanh** (`remix_audio.py <B> <TAG> <picture.mp4> [out.mp4]`, vài giây): trộn lại tiếng gốc + nhạc + SFX theo `storyboard_<TAG>_timed.json` rồi ghép với `-c:v copy`, không mã hoá lại hình. Mọi yêu cầu thêm / bỏ / dời SFX, đổi nhạc, đổi âm lượng đi đường này: sửa `sfx_timed` (giây, gain) hoặc `music` (file, gain, delay) trong JSON → chạy → gửi. Sau đó chạy `make_hf_post.py` (không render) để project HyperFrames khớp storyboard.

Sau mỗi lần trộn lại: đo mức âm từng giây của bản mới so với bản trước và liệt kê các giây lệch quá 1 dB; chúng phải nằm trong đoạn định sửa.

**Khi phim dài ra hoặc ngắn đi** (thêm shot, đổi tốc độ): giữ nhạc bắt đầu từ giây 0 và đổi nhịp nhạc bằng `atempo` (giữ cao độ, trong khoảng ±2 %) để cú dứt vẫn trùng mốc logo. Không lùi nhạc bằng `delay`: đoạn mở êm của nhạc sẽ trượt vào giữa phần mở đầu và để lại khoảng lặng (đã gặp: 0:04–0:06 còn −45 dB).

**Lớp chữ trong HyperFrames phải đủ như bản ghép cũ.** Khi chuyển phần chữ sang HyperFrames trên nền phim không chữ, đối chiếu từng trường của storyboard mà bản ghép ffmpeg dùng cho bản có chữ: `overlays`, `label_screen` (lớp nhãn Blender nền đen, chồng kiểu screen), `logo_seq`. Lỗi đã gặp: nhãn bốn ga (`label_screen`) biến mất suốt nhiều bản vì project HyperFrames chỉ đọc `overlays`. Sau lần chuyển đầu tiên, so khung hình của bản mới với bản có chữ trước đó ở mọi shot có lớp chữ.

## Gói bàn giao: 3 lớp tách rời

Mỗi lần chốt bản, chạy `export_stems.py <B> <TAG> <final.mp4> <thư mục>` để xuất vào `film/BAN_GIAO_<TAG>/`:

- phim hoàn chỉnh;
- `01_VIDEO_khong_tieng.mp4` — lớp hình (copy luồng hình, không mã hoá lại);
- `02_MUSIC.wav` — nhạc đúng vị trí, nhịp và âm lượng trong phim, dài bằng phim;
- `03_SFX.wav` — toàn bộ SFX;
- `04_TIENG_GOC_CLIP.wav` — tiếng gốc của các clip AI (để riêng, vì nó không phải nhạc cũng không phải SFX đặt tay);
- `SFX_cue_sheet.csv` (giây, tệp, gain, sự kiện), storyboard `.json`, bản có giờ và bản `.md`.

Kiểm: cộng ba lớp tiếng phải ra đúng mức của bản trộn (đo LUFS). Cập nhật storyboard `.md` trong Project theo đúng bản bàn giao.

## Soát SFX trước khi giao

- Lập bảng sự kiện → SFX cho cả phim: logo loé kim loại, nhân vật xuất hiện, bay ngang, đáp / chạm đất, nhặt vật (ngọc), dậm chân, bật vọt lên trời, chạm nước, chuyển cảnh, tách lớp, số năm bật sáng, nổ trước logo cuối. Sự kiện nào chưa có tiếng thì sinh tiếng riêng (mirelo), không dùng lại một tiếng cho nhiều loại sự kiện.
- Kiểm tự động: cùng một tệp SFX không được lặp lại trong khoảng ngắn hơn độ dài của nó + 1 giây (lỗi đã gặp: tiếng chuyển cảnh đặt ở 6,85 s và 9,2 s nghe như bị trùng).
- Đo mức âm theo cửa sổ 0,25–1 giây trên bản đã trộn để tìm khoảng hụt (lỗi đã gặp: 7–10 s chỉ còn −30 dB vì nhạc mở êm và bỏ mất SFX). Đoạn mở đầu nhạc còn nhỏ thì hình nào chuyển động mạnh cũng phải có SFX riêng.
- SFX sinh ra thường có đoạn dẫn nhỏ rồi mới tới cú chính: đo đỉnh của tệp rồi đặt sao cho **cú chính** trùng khung hình sự kiện, không đặt theo đầu tệp.
- Mốc đáp / dậm chân lấy từ bảng khung hình của clip nguồn (đổi theo tốc độ shot), ghi rõ là đặt theo hình và cần người nghe duyệt.

## Cảnh giới thiệu công trình từ một ảnh mặt cắt / phối cảnh

- Không cắt lát hay đẩy khối trực tiếp từ ảnh tham chiếu (người dùng bác: "lấy ảnh cắt đi là sai"). Dựng mô hình khối thật trong Blender theo ảnh (mái, sàn, cột, lõi, hồ, cây, nền), chia collection theo lớp, làm hoạt cảnh tách lớp kiểu exploded-stack.
- Blender chỉ là khung bố cục: render một khung tách lớp không nhãn → gpt_image với 2 ảnh tham chiếu (khung Blender cho bố cục + ảnh gốc cho vật liệu, chi tiết) → gửi ảnh chốt cho người dùng duyệt → video Wan từ ảnh gốc sang ảnh chốt.
- Nhãn lớp, đường dẫn, hiệu ứng nền (lưới blueprint, vòng xoay, vạch quét) là lớp HyperFrames đặt lên đoạn giữ khung cuối; nền có mặt nạ chừa vùng mô hình.
- Tên lớp / tên khu vực không có trong tài liệu thì đặt theo hình và nói rõ là tự đặt, chờ xác nhận.

## Nhân vật chồng lên đoạn đồ hoạ (kết phim)

- Sinh nhân vật trên nền đen tuyệt đối (ảnh chốt nền đen → Seedance, prompt "PURE BLACK background for the entire shot"), chồng bằng `mix-blend-mode: screen`.
- Trước khi chồng: ép đen (`curves=all='0/0 0.14/0 0.5/0.5 1/1'`) và làm mềm mép (vignette + mặt nạ radial trong CSS), nếu không sẽ lộ khung chữ nhật của clip trên nền sáng màu.
- Đo giây xảy ra cú chính trong clip (nổ sáng, nhập vào chữ) rồi đặt giờ bắt đầu sao cho cú đó trùng mốc đồ hoạ (số bật sáng).
- Trước khi tốn credit: gửi ảnh chốt nhân vật VÀ bảng storyboard các nhịp ghép phác trên khung hình thật của đoạn đó; người dùng không duyệt khi chỉ thấy ảnh nhân vật.

## Khi chèn cảnh mới

- Chỉ chèn ở chỗ đã có chuyển cảnh đồ hoạ (ngọc). Không chèn vào giữa hai shot nối liền bằng ảnh chốt chung, và không thêm chuyển cảnh ngọc lên cuối một shot đang nối liền: nó che mất đoạn nhân vật bay tới (lỗi đã gặp ở Masterplan → toàn cảnh).
- Tăng tốc shot để dồn nhịp: không tăng tốc shot mà người dùng coi là cảnh chính; nói rõ shot nào tăng bao nhiêu.
- Tăng tốc bằng trường `speed` của shot: tiếng gốc dùng `atempo` (giữ cao độ); SFX gắn theo `shot + offset` nên tự dời; sau đó đo lại mức âm cả đoạn.
- Thêm địa danh bám theo một điểm trên hình (cột sáng trên bản đồ): đo vị trí điểm đó trên vài khung, đặt chữ bằng keyframe GSAP; nếu ngay sau đó đã có nhãn cùng tên thì chỉ giữ một.

## Chuyển cảnh biến hoá giữa hai cảnh (số → vật, cảnh A → cảnh B)

- Ảnh đầu = khung thật cuối của cảnh trước, ảnh cuối = khung thật đầu của cảnh sau; tạo thêm **ảnh giữa** bằng gpt_image với hai ảnh đó làm tham chiếu (ví dụ: bốn chữ số tách ra bay về bốn góc, mảnh ghép xoáy mở ra vật thể). Gửi bảng 3 ảnh cho người dùng duyệt rồi mới chạy video.
- Chạy hai đoạn ảnh đầu → ảnh giữa → ảnh cuối (Wan là đủ cho đồ hoạ; cú nhân vật lao mạnh thì Seedance cho đoạn có nhân vật).
- **Không ghép thẳng hai đoạn rồi tua nhanh**: mỗi đoạn AI chậm dần ở cuối và khởi động chậm ở đầu nên chỗ nối bị khựng, và khung cuối của Wan không trùng hẳn ảnh cuối nên bị giật ở điểm cắt. Dựng một đoạn liền bằng script (`make_x01.py`): bỏ phần chậm hai bên chỗ nối, ánh xạ thời gian tốc độ đều rồi giảm tốc liên tục về cuối, hoà các khung nguồn khi tua nhanh và nội suy khi chậm hơn 1 khung, hoà 10–14 khung cuối vào **đúng khung đầu của cảnh sau**.
- Kiểm bằng số: chênh lệch khung liền kề (`tblend=difference` + `signalstats YAVG`) suốt đoạn chuyển và qua điểm cắt; không được có chỗ tụt về gần 0 giữa chừng hay nhảy vọt ở điểm cắt.
- Cảnh nối có nhân vật đi qua hai bối cảnh (lao qua thác vào vườn): cắt cảnh trước ở khung nhân vật còn trong hình để làm ảnh đầu; ảnh giữa là khoảnh khắc mạnh nhất (xuyên màn nước, nước nổ); cảnh sau có thể vào bằng cắt theo hành động thay vì ảnh chốt chung, và phải nói rõ điều đó. Âm thanh cần đủ: tiếng nền của nơi chốn (thác đổ), tiếng nhân vật (gầm), tiếng va chạm (nước nổ, tỏm).

## Credit và chuyển tệp

- Trước mỗi lần chạy video: đo credit, báo chi phí từng phương án. Nếu cách làm tốt hơn tốn **nhiều hơn mức đã báo**, hỏi lại trước khi chạy (lỗi đã gặp: báo 35, chạy 44).
- Tệp phim chuyển từ máy người dùng lên chat hay quá thời gian: nén bản xem (crf 27), chia thành phần 8 MB bằng Python trên máy họ, lấy từng 1–2 phần mỗi lần rồi ghép lại bằng `cat`; kiểm thời lượng sau khi ghép. Luôn đưa kèm đường dẫn bản đầy đủ trên máy họ.

## Lỗi đã gặp

| Lỗi | Cách tránh |
|---|---|
| Rồng mọc cánh | Ghi WINGLESS / "no wings at any time" trong mọi prompt |
| Cảnh lạc sang bối cảnh khác | Bỏ ảnh tham chiếu có bối cảnh khác; ảnh đầu phải thấy bối cảnh |
| ComfyUI ra đường phố thay vì sân đá | Prompt địa điểm cụ thể + negative; so với shot trước |
| Vệt sáng ngang đường chân trời khi làm viền sáng | Matte có cả mặt nền mô hình; cắt matte ở hàng nền |
| Chữ bị cắt mép | Đo bề rộng dòng trước, tự xuống dòng |
| Rớt khung ở bản cuối | Chuyển cảnh chồng theo shot, thêm `-r 24` |
| SFX bị chìm | Cân mức từng clip, hạ nhạc |
| Gửi bản nén thấp | Giao đúng độ phân giải đã chốt |
| Mất nhãn ga khi chuyển sang HyperFrames | Đọc cả `label_screen`, `logo_seq`, không chỉ `overlays`; so khung với bản có chữ cũ |
| Khựng ở chỗ nối hai đoạn AI, giật ở điểm cắt | Dựng một đoạn liền có ánh xạ thời gian và hoà vào khung đầu cảnh sau; đo chênh lệch khung |
| Khoảng lặng ở phần mở đầu sau khi phim dài ra | Đổi nhịp nhạc bằng `atempo`, không lùi nhạc |
| Hiệu ứng ngọc che mất đoạn nhân vật bay tới | Không thêm chuyển cảnh ngọc lên shot đang nối liền bằng ảnh chốt |

## Cây thư mục phim Gia Bình v4m (đang dùng)
`GiaBinhDragon_v4m\{00.MUC_LUC_DU_AN.md, 00.Guideline\{01.Kich_ban, 02.Storyboard, 03.Ho_so_phim, 04.Quy_uoc, 05.Kiem_tra, 06.Tai_lieu_goc_v1, 07.Ban_luu_project}, 01.Hyperframe\{index.html, 01.Image, 02.Video, 03.Music, 04.Src, 05.Graphic, 06.Out\{01.Review, 02.Version, 03.Upscale, 04.Final, 05.Stems}}, 02.Premiere, 03.Blender_3D, 04.Tools, 05.ComfyUI\{00.Quy_uoc, SCxx_<Cảnh>\SHnn_<ID>\{01.Anh_chot, 02.Neo_khung, 03.Video, 04.So_sanh\benchmark, 05.Workflow}}, 06.Skill_Quy_trinh\{00.README_SKILL.md, 01.SO_DO_QUAN_HE.md, 02.Ban_sao_skill (4 nhóm), 03.Transition_registry, 04.Benchmark_clip}}`. "Hồ sơ phim" thay cho chữ "Bible". Guideline nằm ngoài project HyperFrames để app không hoàn tác mất tài liệu. Phim mới: khung chuẩn của skill `film-project-structure`.

## Hỏi người dùng khi
- Chọn model đắt cho nhiều shot, hoặc tổng credit vượt mức đã duyệt.
- Vị trí sự kiện trong câu chuyện chưa rõ (ví dụ nhân vật nhặt vật ở sân hay trên mái).
- Cần đường dẫn dự án hiệu ứng (HyperFrames) để dùng hiệu ứng thư viện thay cho lớp tự dựng.
