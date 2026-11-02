# JENNIEJOYKIDS_04_MILK_AND_MOM — ghi chú xuất bản T-W04 (2026-10-27)

Bản gốc có version nằm trong `production-local/JennieJoyKids-Story/04-milk-and-mom/workflows/`; thư mục này chỉ là **bản sao byte-giống** để mở trong ComfyUI. Bảng kiểm kê đầy đủ, sha256, trạng thái: `workflows/WORKFLOW-MANIFEST-ep04.json` và `workflows/WORKFLOW-INDEX.md`.

| Thư mục | Nội dung | Nguồn | Trạng thái |
|---|---|---|---|
| `03_MOTION_H3/` | 14 graph H3 của 14 shot đang nằm trong phim (S01_A hybrid-v001, S01_B v002, S02_A v004, S02_B v005, S03_A v004, S03_B v005, S04_A v003, S04_B v004, S05_A v005, S05_B v003, S06_A v004, S06_B1 v005, S06_B2 v006, S06_B3 v006) | `workflows/motion-v00N/<shot>.workflow.json` | candidate (job COMPLETED, duyệt AV chưa chốt từng shot) |
| `04_SEEDVR2_UPSCALE/` | đại diện 1 chunk (`chunk-0000`) cho mỗi shot trong 14 shot của lần chạy 4K v004 (134 chunk có đủ trong thư mục phim) | `workflows/seedvr2-production-v004/<shot>/chunk-0000-*.gui.json` | accepted ở mức lần chạy (134/134 COMPLETED); `extra.status` bên trong còn ghi `PREPARED_NOT_RENDERED` — chữ cũ từ lúc chuẩn bị |
| `05_SEEDVR2_TAILS/` | 3 graph khôi phục 4K cho đuôi chuyển cảnh S03_B / S04_B / S05_B | `workflows/seedvr2-tails-v001/<shot>/chunk-0000-*.gui.json` | PLANNED_NOT_RENDERED; chưa chạy GPU |

Lưu ý khi mở: node `LoadVideo` trỏ tên file trong `ComfyUI/input/`; file đầu vào của tails (`seedvr2-tail-v001-...mp4`) chỉ được engine đưa vào `input/` lúc chạy, nên trước đó ô `file` có thể báo thiếu — bình thường.
Các thư mục cũ (`30_MOTION_HYBRID/`, `40_MOTION_REVIEW/`, `90_REJECTED_OR_BLOCKED/`, ...) giữ nguyên, không đụng.
