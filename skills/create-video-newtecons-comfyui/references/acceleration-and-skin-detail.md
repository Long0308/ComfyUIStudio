# Tăng tốc, texture da và SeedVR2 — kiểm chứng 2026-10-23

Đọc [audit và giới hạn nguồn](../../../../docs/research/comfyui-acceleration-bilibili-20261023/REPORT.md) khi áp dụng Bilibili/Civitai. BV1ycP4z3E6G là Z-Image14:41; đoạn Sage/Triton người dùng dán thuộc tutorial khác. Đã đọc mô tả, screenshot, upstream và **graph T2I63nodes/72links đã tải thật**; chưa có transcript/video xem đầy đủ hoặc graph ControlNet. Không nhận đã học trọn video hay tăng tốc1.5×.

## Quyết định vận hành

- Máy kiểm ngày23/10: Python3.12.14, torch2.14.1+cu130, RTX5080sm120; comfy-kitchen0.2.37 đã cài và `int8_attention_is_available()` true. Core hỗ trợ `--use-ck-attention`, worker8188 chưa bật flag. Đây là **candidate benchmark**, không phải trạng thái đã tăng tốc. Không đổi runtime giữa batch; không lấy audit làm lệnh restart.
- Triton/Sage/Flash/xformers chưa cài. [Triton upstream](https://github.com/triton-lang/triton-windows) map torch2.14 với Triton3.8; không áp bundle3.5/3.6 vào môi trường này. [Sage Windows](https://github.com/woct0rdho/SageAttention) hiện khuyến nghị CK cho ComfyUI. `PatchSageAttentionKJ` dự phòng overflow cần đúng package/schema; local chưa có node này. LivePortraitKJ không phải KJNodes.
- Chưa có artifact/benchmark chứng minh Flash2.8.3 phù hợp Windows/Python3.12/torch2.14/CUDA13/sm120. Manager chỉ quản lý node. Không trì hoãn pilot ảnh hợp lệ để cài cả bộ acceleration.

## Chất lượng ảnh và model family

Screenshot Civitai chọn **Skin Texture ZTurbo v4.5 / base ZImageTurbo**. Không dùng file đó cho Qwen/SDXL/Flux hoặc họ khác. Chưa có metadata/hash/license/trigger của model đã xác minh; không coi LoRA đã tải. Parent thấy Personal Use Only trên workflow RunningHub, nên chưa nhập graph vào production doanh nghiệp.

Graph thực có hai stage: Z-Image base+FDPO0.5,CFG3,bước0–3 → Z-Image Turbo+skin4.5 strength0.5,CFG1,bước3–9; Euler/simple,shift8. Total9/split3 là primitive nối dây, ghi đè widgets sampler cũ. Sau đó Klein9B+consistency0.8 phục hồi4MP, color-match/sharpen, rồi wrapper SeedVR2 **FP16**7B/SDPA/36blocksoffload/tile1024 overlap128. Đây là thiết lập nguồn, không phải recipe đã thử local; không chép sang Qwen hoặc native SeedVR2 INT8.

Prompt tiếng Trung đang nối QwenVL; template tiếng Anh rời. Graph không có nguồn mặt/body identity; negative cấm text/logo xung đột đồng phục. Nhánh SeedVR2 chỉ Preview/comparer, thiếu SaveImage cuối. Áp dụng ở local: prompt tiếng Anh đầy đủ, nguồn mặt/dáng thực, kiểm dây nối/giá trị override, QA trước upscale và SaveImage+receipt sau upscale. Không suy4MP=4K, không lấy ảnh preview làm output đã lưu.

Giữ nhánh portrait/expression riêng nhánh full-body/action, nguồn mặt/body đúng crop/hash và prompt đầy đủ. Identity/pose, diễn xuất, trang phục/chữ/sọc phải đạt trước skin polish. Texture da không khóa mặt, không sửa biểu cảm hay body. So tuổi, kính, mắt, tóc và màu da; lỗ chân lông/nét mạnh hơn không chứng minh đúng người.

Native SeedVR2 **7B INT8 ConvRot đã có**: giữ engine/recipe đã chọn và HD→QA→4K riêng. Numz wrapper có attention/compile/BlockSwap nhưng schema đó không đồng nghĩa native nodes. Source native gọi core optimized_attention, cho phép xem xét benchmark CK sau. [SeedVR2 upstream](https://github.com/ByteDance-Seed/SeedVR) nêu khả năng tạo chi tiết thừa; kiểm lại mặt, chữ/sọc và texture sau upscale. Không tải7B lại, không đổi3B theo ví dụ cũ, không gán cảnh báo7B_FP8 trong tutorial cho INT8ConvRot khi chưa tái hiện.

## Cổng benchmark

Cùng source/checkpoint/VAE/prompt/seed/sampler/steps/CFG/kích thước; thay một backend. Đo cold riêng warm, ít nhất3 lần warm có inference thực (loại cache hit), tổng thời gian/VRAM/backend log; giữ graph/job/output hashes. So PNG/crop mặt, da, dáng/tay, chữ, sọc và lỗi đen/nhiễu. Chỉ đổi recipe khi nhanh hơn và chất lượng không lùi. Chưa benchmark thì ghi pending; request/model name không chứng minh model thực đã chạy.
