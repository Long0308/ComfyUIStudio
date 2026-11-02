# AUDIT — vì sao logo mũ và chữ thêu trên áo bị nhoè trong clip H3 NEWTECONS

Ngày 2026-11-01 · worker Claude (Fable 5.1) · phạm vi: 3 graph H3 đã chạy thật (S07_A, S06_A, S05F) + ảnh neo + clip ra.

## 1. Thiết lập H3 THỰC TẾ đã dùng (đọc từ graph đã POST, không phải từ lời kể)

Graph nguồn: `production-local/engine/staging/newtecons-30s/h3-ep05-final-v001/S07_A_rev2b/graph.api.json`
(SHA-256 `f55a4b16…c468` theo `docs/media-stage/SOL6-S07-H3/S07_A/seed-202611071/receipt.json`).
Graph đã chạy cho clip demo: `docs/media-stage/SOL6-S07-H3/S07_A/seed-202611071/graph.api.json`
(diff với nguồn chỉ ở: 5/8/31–35 `image`, 7 `audio`, 11 `noise_seed`, 18 `filename_prefix`, 19 `value`).

| Tham số | Giá trị | Bằng chứng (file:dòng, graph nguồn S07_A_rev2b) |
|---|---|---|
| Bước lấy mẫu | **8** | `graph.api.json:58` `"steps": 8` (BasicScheduler, `scheduler: simple` :57) |
| Sampler | `res_multistep` | `:43` |
| CFG | **không có** — `BasicGuider`, không negative, tương đương CFG 1.0 | `:16` `"class_type": "BasicGuider"`; benchmark.json ghi `"cfg": 1.0` cho A_turbo8 |
| LoRA | **`pika_h3_flex_turbo_8step_hd_ref2va.safetensors` @ 1.0** | `:176`–`:181` |
| Sigma shift | video 12.0 / audio 3.0 | `:191`–`:192` |
| UNET | `minimax_h3_ref2va_pruned_int8_convrot` (pruned, int8) | `:8` |
| Text encoder | `qwen3vl_32b_minimax_h3_nvfp4_awq` (nvfp4) | `:168` |
| Độ phân giải | **1280 × 704**, 107 khung, 24 fps | `:264` height 704, `:300` width 1280, `:266` length |
| Số ảnh tham chiếu | **6 ref (ref_image_0…5) + 1 guide frame 0 = 7 slot** | `:272`–`:295` (node 6), node 9 `MiniMaxH3AddGuide` `frame_idx: 0` `:335` |
| Ảnh thực nạp vào 7 slot | **CÙNG MỘT ảnh** `S07_A_IMAGEGEN2_c03_logo.png` (1672×941, sha `ad157228…`) | `render_s07.py:148`–`149`: `for node… if class_type == "LoadImage": node["inputs"]["image"] = uploaded[shot]["image"]`; diff graph đã chạy: 5/8/31/32/33/34/35 đều = `SOL6_S07_H3_S07_A_anchor_ad157228cd0aed1c.png` |

S06_A (`docs/media-stage/S06A-H3-C07-LOGO-V001/seed-20261106/graph.api.json`) và S05F (`S05F-H3-C04/seed-20261030/graph.api.json`): **y hệt** — steps 8, simple, res_multistep, cùng LoRA turbo 8-step @1.0, shift 12/3, 1280×704, BasicGuider, int8 UNET; S06_A nạp cùng một ảnh logo vào 6 slot, S05F nạp ảnh c04 vào 4 slot + 2 ref khác.

Benchmark có sẵn (`docs/media-stage/H3-BENCHMARK-BASE-VS-FLEX/benchmark.json`): A turbo 8 bước 372 s GPU · B Kijai flex 6 bước 333 s · C base 20 bước + CFG 4 (CFGGuider, không LoRA) 1 085 s — **chậm 2,9×**. Lưới khung A/B/C (`FRAME-GRID_rows-A-B-C_cols-0.5-2.2-4.2s.png`) cho thấy C ra **bố cục và ánh sáng khác hẳn** A/B (tối hơn, khung khác), không phải "A sắc hơn".

## 2. Vì sao chữ/logo nhoè — nguyên nhân cụ thể, đo trên clip demo

Clip: `REVIEW/…/26_DUYET_TUNG_CANH/v2/S07_A_H3_s202611071.mp4` (1280×704, 107 khung, AAC 32 kHz).

1. **Ngay khung 0 đã nhoè.** Ảnh neo 1672×941 bị thu về 1280×704 (tỉ lệ 1,777 → 1,818, nên còn bị cắt/ép nhẹ) rồi nén qua VAE video latent (patch không gian 8–16 px). Dòng chữ "KHỐI KỸ THUẬT" trên neo cao ≈ 15 px ảnh → sau thu ≈ 11 px, cỡ **dưới một patch latent**; diffusion **tái tạo** nét chữ từ latent chứ không chép pixel. Đo khung 0 (zoom 5×, `scratchpad/zoom_f000_*.png`): "KHỐI KỸ THUẬT" → đọc ra dạng "BHÔ KT THUAT", wordmark NEWTECONS trên mũ chỉ còn vệt xanh 45×8 px không đọc được, N đỏ còn hình dạng. Cùng cơ chế với CHAR08 V007R1–R3 trước đây.
2. **Mỗi khung sinh lại chữ một lần nữa.** Không có ràng buộc pixel cho khung 1…106 (guide chỉ neo frame 0, node 9 `frame_idx: 0`). Mỗi khung chữ ra một biến thể khác → cả vị trí nét lẫn hình chữ "bơi" (so khung 0/35/70/106 trong `r1/contact_r1.jpg` cột TRUOC).
3. **Turbo 8 bước LoRA @1.0 + không CFG**: đường lấy mẫu rút gọn (8 bước, `simple`, shift 12) ưu tiên chuyển động/da mặt; chi tiết tần số cao như chữ 10 px không được "kéo" bởi conditioning (BasicGuider không có negative/CFG). Đây là lý do mềm ảnh chung (user thấy "soft").
4. **Độ phân giải gốc 1280×704** (mặt ≈ 250 px, chữ 10–15 px) — kể cả render hoàn hảo cũng chỉ 2–3 px cho nét chữ; SeedVR2 phóng 2× sau đó không thể "đọc" ra chữ đúng từ vệt sai.
5. **7 slot ref cùng một ảnh** không tăng thông tin về chữ; bản thân ảnh neo (ImageGen2) có logo mũ/ngực đã dán bằng `logo_composite.py` nhưng chữ vai trò do ImageGen2 sinh — H3 chỉ "thấy" một bản 1280 px của nó.

Kết luận: nhoè chữ/logo là **cấu trúc** của đường H3 hiện tại (VAE + diffusion sinh lại chi tiết nhỏ mỗi khung), không phải do seed hay prompt "no altered lettering" (prompt node 19 đã có câu này, vẫn nhoè). Tăng bước lên 20 có thể giúp độ sắc chung nhưng **không** làm chữ 11 px thành đúng chính tả; benchmark C cho thấy đổi luôn cả bố cục.

## 3. Cách sửa không dựa vào may rủi (đã làm, xem `last.md`)

VFX deterministic sau render: bám vùng rồi dán patch sạch — chữ vai trò render từ font thật (dấu tiếng Việt đúng, đã kiểm bằng PNG `diacritics_check.png`), logo mũ dùng asset đã duyệt `S07-PPE-ANCHORS-V004/helmet_logo_rgba.png`; xoá vệt nhoè bằng inpaint Telea (PDE, không sinh ảnh); khớp bóng sáng và hạt. Chi tiết, số liệu bám, và chỗ còn hỏng: `last.md` cùng thư mục.
