# Workflow NEWTECONS ComfyUI: thực thi, tùy chỉnh và kết quả

## Phạm vi và nguồn đã phân tích

Hai nguồn người dùng yêu cầu đã được Astra đọc và kiểm kê trong [báo cáo GitHub](../../../../docs/research/comfyui-github-20261023/REPORT.md), [ledger](../../../../docs/research/comfyui-github-20261023/WORKFLOW-LEDGER.md) và [route matrix](../../../../docs/research/comfyui-github-20261023/WORKFLOW-ROUTE-MATRIX.md). Phạm vi đo: 88 cây repository ZHO và RMBG, 214 JSON; 15 ví dụ RMBG, 100 payload graph duy nhất. Không suy rằng mọi repository/model đã cài, live-loaded hoặc chạy thành công.

Đọc [phân tích screenshot Qwen và character look sheet](../../comfyui-video-pipeline/references/character-sheet-and-hd-4k.md) để chọn bố cục, phân biệt nhánh portrait/body và điều kiện HD→QA→4K. Không lắp LoRA chỉ vì tên đọc được trên ảnh; kiểm đúng checkpoint, schema và giấy phép nguồn.

## Hợp đồng của một workflow hoàn chỉnh

Canvas đọc từ trái sang phải: **đầu vào → giữ mặt/dáng → trang phục/RMBG → prompt/thông số/sampling → ảnh thử HD → kiểm → job 4K riêng**. Các khối phải nối thật hoặc được đánh dấu rõ đang thiếu; không thay bước xử lý bằng một ô Note. Đồ thị hiện hành còn thiếu swap/RMBG/trang phục đã chạy và batch 20 đủ chất lượng; không mô tả nó là pipeline sản xuất hoàn tất.

| Khối | Đầu vào và thao tác thật | Điều chỉnh riêng | Bằng chứng cần có |
|---|---|---|---|
| Nguồn nhân vật | Ảnh gốc đúng tên/hash; crop một người/một góc từ sheet | Tên file, góc, crop, pose | Loader và đường tới output thực |
| Giữ mặt / face swap | Dùng route identity phù hợp; Krea đã chuẩn bị, phải có node live và pilot | Face source, mức giữ danh tính, mask | Cùng mặt, kính, tuổi; không coi prose là face lock |
| Dáng người | Nạp body view tách riêng, giữ tỷ lệ, init/control phù hợp | Góc, tư thế, hành động | So toàn thân với body master, không kiểm từ ảnh mặt |
| RMBG / mask trang phục | Node từ 1038lab, model segmentation đúng loại; ảnh một người | Person/clothes/hair, vùng và feather | Mask/alpha và ảnh composite phải xem được |
| Áp dụng đồng phục | Ảnh áo/nón/gile thật đi vào nhánh edit và mask; khôi phục chữ/logo đúng phối cảnh | Bộ đồ, chữ bộ phận, mask; office/site | Ảnh trước/sau, full-frame và crop chữ/sọc |
| HD | Mô tả tiếng Anh đầy đủ, nguồn có tên, seed và thông số nhìn thấy | Task cụ thể, biểu cảm, ánh sáng | Một PNG riêng tối thiểu 1536×2048 cho 3:4 |
| QA | Kiểm chính PNG HD/hash: mặt, hành động, dáng, đồ, chữ/sọc/texture | Tiêu chí từng task | FAIL/UNKNOWN không tự lên 4K |
| 4K | Job riêng nhận HD đã PASS; upscale/detail phù hợp | Mức phục hồi, seed, kích thước | 3072×4096 và QA lại, không chỉ resize rồi gọi chất lượng đạt |

RMBG tạo nền trong suốt hoặc mask, không tự tạo áo mới. Face swap không sửa dáng sai. LivePortrait điều khiển bằng ảnh, không tiêu thụ Note tiếng Anh. InstantID ZHO pose reference là keypoint khuôn mặt, không là full-body OpenPose. BananaFace/cloud wrapper không phải inference local. Negative portrait cấm full body không được dùng cho action/body.

## Ba nguồn CHAR08 theo yêu cầu mới

Nguồn gốc ở `casting/` của phim:

- `CHAR_08_ICON_FACE.png`: cắt riêng chân dung làm danh tính/kính/ponytail/nụ cười; không cho model nhận nguyên collage rồi gọi là một chân dung đơn.
- `CHAR_08_CHARACTER_SHEET_MASTER_4096.png`: head/expression/pose/details phải crop theo chức năng; chữ trên sheet không phải canonical spelling mới.
- `CHAR_08_KYSU_TRE_NU_GOC_XOAY.png`: cắt từng góc/người để giữ dáng và tư thế. File sáu góc `_4096` có thể cùng hash với file này; không tính là nguồn độc lập.

Ảnh office CHAR08 không tự thêm mũ/gile. Biến thể công trường/trang phục khác dùng nguồn trang phục đã chọn và giữ đúng người. Quy tắc mới microgrid/collar logo vẫn ưu tiên hơn áo cũ trên sheet. Mỗi task xuất một PNG; review sheet là sản phẩm phụ, không thay 20 ảnh riêng.

## Tự động hóa trên 8188

Pack `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2-45s`:

- `run_comfy_local_job.py`: submit/resume theo prompt ID, kiểm nguồn/hash, thu history/ảnh; sau collect tự gọi publisher và API delivery.
- `embed_workflow_results.py`: 8 file `NEWTECONS_8_NHAN_VAT/CHAR_*.json`, mỗi file 20 ô và toàn bộ lịch sử; POST userdata và GET kiểm hash.
- `newtecons_live_bridge.py`: theo dõi job native có metadata NEWTECONS; journal/lock/retry thu kết quả, không gửi inference, không tự thử lại job tạo ảnh lỗi.
- `comfy-live-ui/newtecons-live-results.js`: tự cập nhật kết quả trên canvas; giữ nguyên prompt/graph người dùng chỉnh. Full graph reload tách khỏi refresh kết quả.
- `attach_character_execution.py` + `layout_character_workflow.py`: nhánh đơn được chọn, bố cục có nhóm; không tuyên bố một pilot là batch 20.
- `prepare_char08_icon_hd.py`: pilot HD dùng ba nguồn thật; r060 đã có job và PNG 1536×2048, chưa có QA toàn diện hoặc nghiệm thu.

Nút Run native, GUI export và API graph phải khớp dữ liệu đang chạy. Khi thay file cùng tên, stage bản đúng bằng tên chứa hash, không ghi đè ảnh người dùng. Preview dùng core `LoadImage` và bản sao hash-verified trong input gốc. `LoadImageOutput` remote combo chỉ thấy placeholder ở output root có thể tự chọn sai; HTTP ảnh tồn tại chưa đủ chứng minh preview chạy.

Không có batch 20 đang chạy thì ghi đúng trạng thái. Không chạy 20 lần một recipe sai, không tính technical success hay preview count là production PASS. Batch chỉ được bật khi route tương ứng đã đạt kiểm nội bộ; người dùng đã cho phép pilot/batch, không xin lại từng ảnh.

## Trạng thái phụ thuộc và reload

Runtime phải kiểm trực tiếp `/object_info` và `/queue`. Krea/LivePortrait đã có package/weight trên đĩa nhưng chưa có trong registry ở lần kiểm 2026-10-23; RMBG đang chuẩn bị tích hợp. Không gọi file workflow đã viết là đã runnable. Lịch sử có lần automatic approval review chặn restart; không đổi shell/API để lách. Nếu cần reload mà công cụ vẫn bị chặn, báo đúng hành động/reason và bàn giao một lệnh khởi động đã chuẩn bị cho người dùng, không giả đã reload.
