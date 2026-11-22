---
name: hyperframes-hieu-ung-lp
description: Thư viện hiệu ứng kéo thả "lp-*" cho HyperFrames lấy từ phim intro Workshop AI V8f (ball action ráp chữ, cú đập sóng xung kích, chữ đập, số đếm, biển neon, nền HUD, vũ trụ, đèn rọi, cửa chớp, khung phim, Ken Burns, zoom theo nhịp) + 448 khối kho HyperFrames đã cài sẵn + trang web xem toàn bộ hiệu ứng. Dùng khi cần thêm hiệu ứng motion graphic / chữ / CGI / neon / chuyển cảnh / zoom-pan vào một video HyperFrames, khi viết hiệu ứng lp-* mới, hoặc khi mở và sửa phim intro V8f trên HyperFrames.
---

# Thư viện hiệu ứng LP cho HyperFrames

Đọc `revit-live-demo-20261110/INTRO-HYPERFRAMES_v8f_20261115/README.md` trước. Máy công ty là `D:\61.SetupAgent`, máy nhà là `D:\61.SetupAgent`.
Gọi skill `/hyperframes` (và `/hyperframes-registry` khi tìm khối kho) trước khi sửa composition.

## ⓿ Đọc trước tiên: những thứ đã đo, đừng đoán lại

1. **Composition con nhận GIỜ CỤC BỘ qua timeline của chính nó.**
   - Đo: gắn ở giây 2, chụp ở giây 2,5 thì `onUpdate` của tween nhận 0,5.
   - Sự kiện `hf-seek` mang giờ CỦA CẢ PHIM (2,5), không phải giờ cục bộ.
   - Vì vậy hiệu ứng canvas vẽ trong `onUpdate` của tween proxy (`lpClock`), không vẽ theo `e.detail.time`.
2. **Cùng một hiệu ứng gắn nhiều lần vẫn chạy đúng, mỗi lần một bộ biến.** Đã kiểm 2 lần gắn `lp-cu-dap` (vàng/trái, đỏ/phải). Muốn được vậy thì:
   - Tìm gốc bằng `lpRoot(id)` qua thuộc tính `data-lp`.
   - Truy phần tử bằng class trong gốc đó, không dùng id.
3. **KHÔNG dùng class `clip` cho thứ không có giờ.** HyperFrames dành tên này cho phần tử có `data-start`. Intro gốc dùng `clip` cho mẩu báo giấy: CSS hai bên đè nhau, SSIM tụt còn 0,62. Đã đổi thành `nclip`.
4. **Trang dựng theo kiểu tween `from` chồng nhau phải chạy lại từ 0 khi tua lùi.** Nếu không, cảnh "Phần 2" mất (SSIM 0,876 ở giây 115). Ca này chỉ lộ khi chụp theo thứ tự có tua lùi: cổng phải có một lượt chụp ngược.
5. **"Bơm theo phách" của intro phóng từ góc trên trái vùng hình (0, 58)**, theo chuỗi ffmpeg gốc: crop rồi scale rồi crop, x và y bị chốt ở 0.
   - Đo mép chữ qua 21 khung quanh giây 88: tâm giữa lệch 7,55 px, tâm góc lệch dưới 0,12 px.
6. **Khối kho kiểu zoom / lia / chuyển cảnh / vén màn không tự có hình.** Chúng tác động lên nội dung đặt vào, nên dựng ảnh xem trước ra ảnh trống là ĐÚNG, không phải lỗi.
7. **Tiếng phim intro phải phát đúng `mix.wav` đã giao, KHÔNG cộng các track rời.**
   - Các track rời lấy trước bước né nhạc và limiter. Cộng 4 track trừ bản trộn còn −12,8 dB, to hơn cả bản trộn (−15,2 dB).
   - Phát `mix.wav` thì trọn phim khớp: −12,9 LUFS cả hai bản; hiệu −42,8 dB, chỉ còn sai khác do nén AAC.
8. **WebGPU chạy được trong app trên máy công ty** (RTX 5070 Ti, Direct3D11): đã dựng aurora và chrome-orb ra hình.
9. **Kho HyperFrames (`registry` trong `hyperframes.json`) chỉ đọc qua https.** Không trỏ được về thư mục trên máy, cũng không trỏ được kho GitHub riêng tư. Hiệu ứng riêng nằm trong `compositions/` của dự án là kéo thả được.
10. **Lottie phải nằm trong khối con nếu không bắt đầu ở giây 0 của phim.** HyperFrames tua mọi hoạt hình trong `window.__hfLottie` theo giây của composition chứa nó. Đặt thẳng ở gốc, bắt đầu giây 4,5 thì hình đứng ở khung cuối (đo: chấm đỏ không quay). Chuyển vào khối con: góc đo 89,7° · 180,3° · 270,3° so với 90 · 180 · 270.
11. **Cảnh 3D (three.js) vẽ theo `hf-seek`, mọi thứ là hàm của giây phim.** Vật lý không tua ngược được nên nướng trước bằng Node (`e2e/nuong_vat_ly.mjs`, Rapier) rồi nội suy; hạt `three.quarks` thì mỗi lần tua chạy lại từ 0 với `Math.random` thay bằng bộ số có hạt giống. Đo: chụp xuôi và ngược ở 3 mốc, 0 điểm ảnh khác. Bloom dùng `pmndrs/postprocessing` bản không React. Thư viện ESM nạp bằng `importmap` ở thẻ head của tệp gốc.
12. **`<video>` có `data-start` không được nằm trong khối cha cũng có `data-start`.** Lệnh `check` chặn (video lấy sai khung rồi biến mất giữa chừng). Cho khối cha không có giờ, tự làm mờ bằng GSAP.
13. **WhisperX tiếng Việt: mô hình căn giờ mặc định cho mốc SAI** (cả câu dồn vào 1,4 s, mốc cuối lệch 2,9 s, chữ thì vẫn đúng nên dễ tưởng là đạt). Truyền `model_name="nguyenvulebinh/wav2vec2-base-vietnamese-250h"` cho `load_align_model`: lệch tối đa 0,20 s. Cài `whisperx` sẽ thay torch GPU bằng bản CPU.
14. **Manim: số trên trục và công thức cần LaTeX.** Máy chưa cài LaTeX thì dùng `Text(...)`, bỏ `include_numbers`. Xuất `-qm --fps 30` rồi đặt MP4 làm `<video class="clip" muted>`.
15. **Khối nhúng bộ kiểu dùng chung phải khai báo đủ họ chữ.** `lp-chu-dap`, `lp-bi-rap-chu`, `lp-bien-neon`, `lp-the-chip` từng gọi LPJM/LPBV mà không có `@font-face`; chỉ lộ khi chạy `check` trên một phim dùng chúng. `tools/dung_thu_vien.py` giờ tự khai báo phần thiếu và dừng nếu còn họ chữ nào gọi mà không khai báo.
16. **Cú đập đặt theo phách đo được, rồi đo lại trên khung.** `e2e/e18_librosa.py` dò phách; đặt `data-start` của `lp-cu-dap` bằng đúng giây phách; `e2e/do_phim.py <mp4> <phách...>` tìm khung độ chói bật lên và so (phim thử: lệch 17 · 10 · 0 ms). Cho phách sai 0,3 s thì cổng báo hỏng.
17. **Khối kho bọc trong `<template>`, hoặc nạp tài nguyên "nằm cạnh tệp", không xuất đứng một mình được.** `render -c <khối>` báo "is not mounted from index.html", hoặc bước dựng không bao giờ báo xong (extruded-logo nạp phông 3D). `tools/xuat_video_xem_truoc.py` dựng một dự án tạm ("khung chủ") có `index.html` gắn đúng khối đó. Thư mục `compositions` của khung chủ phải là thư mục thật: tệp nạp động đi qua junction bị máy chủ dựng trả 404.
18. **Lệnh xuất báo thành công chưa chắc hình đúng: có tệp 404 thì hình thiếu thứ gì đó.** `lottie-character-walk` xuất ra mã 0 nhưng video không có nhân vật vì `assets/mascot.json` bị 404; kiểm "không trống" vẫn qua vì còn thẻ chữ. Script giờ coi lần xuất có "404 Not Found" là hỏng và thử lại qua khung chủ. Nhìn ảnh khối mới xuất trước khi tin số đếm.
19. **Mô hình Blender vào phim bằng GLB, có cổng đo kích thước.** Dựng qua Blender MCP, xuất GLB, nạp bằng `GLTFLoader` trong cảnh three.js (mẫu: `e2e/blender-thu/`). Phải đăng ký `window.__hf.buildReady` và chỉ báo xong khi nạp xong; nạp hỏng thì để lệnh xuất dừng. `e2e/do_glb.py` đo khung bao trong tệp GLB: mẫu ống co 90° ra 2,200 × 2,200 × 0,300 m, lệch 0 mm so với số dựng trong Blender. Máy quay lấy bán kính bằng nửa đường chéo khung bao; lấy nửa cạnh dài nhất thì vật bị cắt khi quay.

## Dùng hiệu ứng

- Trong app (`npx --yes hyperframes@0.9.51 preview`): kéo thẻ composition `lp-*` hoặc khối từ bảng danh mục vào timeline.
- Bằng mã:

```html
<div id="x1" style="z-index:3" data-composition-id="lp-cu-dap" data-composition-src="compositions/lp-cu-dap.html"
     data-start="12.0" data-duration="1.2" data-track-index="3" data-track-kind="graphics" data-width="1920" data-height="1080"
     data-variable-values='{"mau":"vang","x":960,"y":470}'></div>
```

- Sang dự án khác: `python -I -X utf8 tools/chep_hieu_ung.py <dự án> [--ca-kho]`.

## Viết hiệu ứng lp-* mới

1. Viết nguồn ở `thu-vien-hieu-ung/nguon/lp-<tên>.html`:
   - Mở đầu bằng khối chú thích: dòng 1 `lp-<tên> · TÊN (nguồn)`, các dòng mô tả, dòng `Biến:`.
   - `<html data-composition-id data-composition-duration data-composition-variables>`.
   - Bên trong `<template><div id="root" data-composition-id="lp-<tên>" data-lp="lp-<tên>" data-duration>`.
   - Chỗ trống `{{FONTS:LPAnton,...}}`, `{{STYLE_KIT}}`, `{{HELPERS}}`.
   - `var ID = 'lp-<tên>'` và kết thúc bằng `lpRegister(ID, root, tl)`.
2. `python -I -X utf8 tools/dung_thu_vien.py`. Script dừng nếu thiếu mục nào ở bước 1.
3. Gắn vào `thu-vien-hieu-ung/index.html`, chạy `lint`, chụp `snapshot`, nhìn ảnh.
4. Xuất bản trình diễn rồi chạy `tools/cat_xem_truoc_lp.py` để trang xem có video.

Luật HyperFrames vẫn áp dụng đủ:

- mọi thứ là hàm của thời gian
- số ngẫu nhiên có seed (`rng`)
- không `requestAnimationFrame`, không hẹn giờ
- dùng `fromTo` chứ không dùng `from`
- font qua `@font-face` tới `assets/fonts/`

## Ghép với studio-video-engine (jjv)

`studio-video-engine` là skill đồng bộ từ tài khoản Claude (bản trên máy ở `~/.claude/skills/synced/…/studio-video-engine`, chỉ đọc). Bộ máy của nó (`bin/jjv.py`) KHÔNG nằm trong kho này. Chỗ nối là tệp clip: HyperFrames làm ra clip, bộ máy ghép clip vào phim.

| Bước của bộ máy | Phần ở đây đưa sang |
|---|---|
| `jjv edit assemble` (EDL → bản master) | Clip xuất bằng `tools/xuat_cho_studio_engine.py`: đúng cỡ khung và khung/giây của miền, kèm biên nhận có `sha256` (bộ máy từ chối clip thiếu mã băm) |
| `jjv timing words` / `qa words` | Tham khảo chéo: `e2e/e19_whisperx.py` cho giờ từng từ; nhớ đổi mô hình căn giờ tiếng Việt (bài học 13) |
| `jjv audio music` (phách) | `e2e/e18_librosa.py` cho bảng phách để đặt `lp-cu-dap`, `lp-zoom-nhip` |
| `jjv qa …` | Trước khi giao clip: `hyperframes check` 0 lỗi, `e2e/do_phim.py` (có hình, có tiếng, cú đập đúng phách) |

Xuất clip cho miền Newtecons (số lấy từ `domains/newtecons_live_action.json` của skill, lúc viết là 2560×1440, 24 khung/giây):

```
python -I -X utf8 tools/xuat_cho_studio_engine.py <thư mục dự án HyperFrames> --film-id <mã phim> --ten <tên clip>
```

Đã đo 15/11/2026 với phim thử: ra `e2e-thu_phim-thu_2560x1440_24fps.mp4`, 276 khung (11,5 s × 24), có tiếng, kèm `.bien-nhan.json`. HyperFrames chỉ phóng theo bội số nguyên, nên script xuất 4K rồi thu nhỏ Lanczos về 2560×1440. Chạy lần hai cùng tên thì script từ chối ghi đè.

Chưa làm, đừng coi là đã có:
- Chưa chạy `jjv edit assemble --validate-only` với clip này (máy này không có `jjv.py`). Dòng clip trong EDL phải viết theo schema `ntc/ep05-edl/v1` ở máy có bộ máy.
- Miền Newtecons chạy 24 khung/giây, hiệu ứng lp-* và phim thử dựng ở 30. Cú đập theo phách phải đo lại trên bản 24 khung/giây (`e2e/do_phim.py` đang tính theo 30).
- Skill `studio-video-engine` tách hai miền (hoạt hình JennieJoy và người thật Newtecons): clip của phim Newtecons không dùng tài nguyên của miền kia.

## Cổng nghiệm thu

- Phim intro: `sh tools/so_voi_phim.sh <lượt> <giây,...>`, so SSIM theo số khung với `video-intro-v8f_BAN-CUOI/INTRO-Workshop-AI_V8f_CO-SUB.mp4`.
  - Mốc ngày 15/11/2026: 28 khung, thấp nhất 0,9632.
  - Luôn có khung ĐÚNG NHỊP PHÁCH (giây 88, 100,5, 117…). Đó là chỗ hai cách phóng tách nhau; khung ngoài phách không bắt được lỗi tâm phóng.
  - Luôn có một lượt chụp NGƯỢC thứ tự.
- Thư viện: `npx --yes hyperframes@0.9.51 lint` phải ra 0 lỗi; `snapshot` các giây then chốt rồi nhìn ảnh.
- Trang xem: `node tools/kiem_trang_xem.mjs http://127.0.0.1:4401/ <ảnh> zoom` (đặt biến `PUPPETEER_PATH` tới `puppeteer-core` trong bộ đệm npx của hyperframes). Đạt khi khung xem mở và video tiến thời gian.

## Giấy phép

- Hiệu ứng `lp-*` là mã của dự án.
- Khối kho HyperFrames: Apache-2.0; một số khối ghi thêm MIT hoặc OFL-1.1.
- Nguồn ngoài: xem `thu-vien-hieu-ung/xem/nguon-ngoai.js`. Tránh react-bits (Commons Clause), lygia (Prosperity), hydra (AGPL) khi chưa hỏi pháp chế.
