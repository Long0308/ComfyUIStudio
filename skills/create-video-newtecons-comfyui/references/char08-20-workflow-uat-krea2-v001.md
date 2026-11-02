# CHAR_08 — 20 workflow Krea2 chuẩn bị UAT

Ngày cập nhật: 2026-10-26  
Trạng thái: 20 graph đã chọn face anchor người dùng duyệt; sẵn sàng UAT HD do người dùng bấm Run. Chưa gửi job ComfyUI; ảnh đầu ra mới vẫn chờ người dùng review.

## Những gì đã có trước revision này

- `casting/CHAR_08_Tran_Thao_Mai/prompts.json` chứa 20 prompt tiếng Anh chung: 10 biểu cảm và 10 hành động, mỗi prompt có `prompt_id` và `prompt_sha256`.
- `production-v2-45s/local-image-e2e/r081/` đã có GUI/API graph cho đủ 20 prompt. Cả 20 prompt trong graph khớp chính xác nội dung và hash của thư viện chung.
- Mỗi graph dùng Krea2 Turbo, 1536×2048 và ba LoadImage: body/dáng, face anchor, ảnh áo. Cả ba file ảnh hiện có trong input của Docker.
- Các graph nguồn chỉ có SaveImage, chưa có PreviewImage. Một số workflow cũ nằm trong cây receipts/E2E thay vì nhóm dễ tìm ở ComfyUI picker.
- Workflow `CHAR_08_Tran_Thao_Mai_10_Bieu_Cam_10_Hanh_Dong` đang mở là bảng kết quả/lịch sử cùng một nhánh sinh ảnh đang chọn; nó không thay cho 20 workflow riêng. Tab unsaved đã báo ba Missing Inputs nên không dùng tab đó làm cổng UAT.

## Revision đã chuẩn bị

- Thư mục nguồn UAT: `casting/CHAR_08_Tran_Thao_Mai/comfyui/uat20-krea2-v001/`.
- Thư mục hiển thị trong ComfyUI: `production-local/ComfyUI/user/default/workflows/NEWTECONS_CHAR08_UAT20_KREA2_V001/`.
- Mỗi prompt có một GUI workflow riêng và một API graph riêng trong nguồn UAT; GUI picker có 20 graph, mỗi graph có một prompt, một SaveImage và một PreviewImage.
- Tiêu đề node và ghi chú UAT trong GUI viết tiếng Việt; nội dung prompt sinh ảnh giữ tiếng Anh và khớp hash thư viện chung.
- Output dùng prefix riêng `Newtecons_CHAR08_UAT20_KREA2_V001/<prompt_id>`; HD 1536×2048. Không có nhánh SeedVR2/4K.
- Nội dung 20 prompt chung được giữ nguyên. KSampler seed và thông số model lấy từ graph r081 tương ứng để bảo toàn khả năng tái lập.

## Vai trò các ảnh đầu vào

| Node hiển thị | Ảnh mặc định | Cách thay |
|---|---|---|
| Mỏ neo khuôn mặt — thay bằng face đã chốt trước UAT | `CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png` | Ảnh gốc đính kèm `codex-clipboard-c921dfea-3332-4f0d-94b0-66af2df517e4.png`, anh đã duyệt cho tóc/áo/logo/face. SHA256 `e98503e940625c25e8be87d8abff507578cbecd4775d5a62c42b76d25cd43359`; hard link từ `references/CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png`. Đã chọn trong cả 20 workflow. |
| Ảnh tham chiếu dáng / vóc dáng — có thể thay | `CHAR_08_BODY_PROPORTIONS_r066_1536x2048.png` | Hard link trong input root tới `newtecons-r078/CHAR_08_BODY_PROPORTIONS_r066_1536x2048.png`. Thay ảnh dáng phù hợp nếu task cần tư thế tham chiếu khác. |
| Ảnh tham chiếu trang phục — đổi áo bằng ảnh tại đây | `CHAR_08_APPROVED_SHIRT_FINE_GRID_N_COLLAR_1536x2048.png` | Hard link trong input root tới `newtecons-r078/CHAR_08_APPROVED_SHIRT_FINE_GRID_N_COLLAR_1536x2048.png`. Chọn ảnh áo/trang phục thực muốn áp dụng. Đổi outfit phải có ảnh tham chiếu. |

Nếu đổi khỏi đồng phục caro xanh-trắng chuẩn, cập nhật phần mô tả outfit trong prompt adapter riêng của workflow đó và ghi nội dung/hash trong manifest run. Không chỉnh `prompts.json`: prompt chung phải giữ nguyên để benchmark. Không tuyên bố workflow đã khóa face cho tới khi thay mỏ neo bằng face đã duyệt và người dùng UAT.

## Kiểm tra tĩnh đã đạt

- 20/20 GUI prompt khớp `prompts.json`.
- 20/20 API prompt khớp `prompts.json`.
- 20/20 graph có face anchor đã duyệt, body/pose reference và wardrobe reference; các file đều tồn tại trong ComfyUI Docker input.
- 20/20 graph dùng node class có trong `/object_info`, Krea2 Turbo và kích thước 1536×2048.
- 20/20 graph có liên kết GUI hợp lệ, PreviewImage và SaveImage prefix duy nhất.
- Hàng đợi ComfyUI không nhận job từ lần chuẩn bị này. Các graph mới có `execution_status: NOT_SUBMITTED` và `user_uat_status: READY_FOR_USER_UAT`; ảnh đầu ra vẫn chờ người dùng duyệt.

## Prompt IDs

**Biểu cảm:** `CHAR_08_FACE_01_NEUTRAL_FOCUS`, `FACE_02_WARM_SMILE`, `FACE_03_TACTICAL_CONCERN`, `FACE_04_DECISIVE_COMMAND`, `FACE_05_SURPRISE_DISCOVERY`, `FACE_06_FEAR_TENSION`, `FACE_07_RELIEF`, `FACE_08_DETERMINATION`, `FACE_09_ACTIVE_LISTENING`, `FACE_10_PRIDE_SUCCESS`.

**Hành động:** `CHAR_08_ACTION_01_FRONT_FULL_BODY`, `ACTION_02_THREE_QUARTER_FULL_BODY`, `ACTION_03_WALK_INSPECTION`, `ACTION_04_TABLET_REVIEW`, `ACTION_05_PHONE_COORDINATION`, `ACTION_06_DRAWING_BRIEF`, `ACTION_07_SITE_DIRECTION`, `ACTION_08_BIM_PRESENTATION`, `ACTION_09_RADIO_REPORT`, `ACTION_10_TEAM_SUCCESS`.

Các biến thể FLUX1 và Z-Image chưa được tạo trong revision này. Khi làm tiếp, clone cùng 20 `prompt_id`/hash, nhưng lưu model, graph, sampler, seed và adapter riêng theo model.

## Rerun ACTION02 — R2 pose reference

Ảnh `ComfyUI_temp_gkxvk_00001_.png` khớp job ComfyUI `3c4f8fbf-96bd-470c-9a25-c004debdcc5e`, workflow `CHAR_08_KREA2_UAT_ACTION_02_THREE_QUARTER_FULL_BODY`. Prompt gốc ACTION02 được gửi nguyên văn; seed `202610810012`, KSampler 12 bước, CFG 1.0, denoise 1.0, latent đầu vào `EmptySD3LatentImage` 1536×2048. Ba ref thực tế là BODY_PROPORTIONS, canonical face và approved shirt.

Nguyên nhân chính là workflow sinh từ latent trống và body reference chỉ vào conditioning; không có base latent hay pose skeleton khóa tỷ lệ. Ảnh GPT ACTION02 còn có tablet/office và góc ba phần tư, trong khi prompt chung chỉ yêu cầu tay thả lỏng; vì vậy prompt, reference target và conditioning không thống nhất. Sai lệch không thể quy cho prompt riêng lẻ.

Đã chuẩn bị graph R2 và đưa vào slot ACTION02 hiện có trong picker folder 20 workflow: `NEWTECONS_CHAR08_UAT20_KREA2_V001/CHAR_08_KREA2_UAT_ACTION_02_THREE_QUARTER_FULL_BODY.json`. R2 dùng `CHAR_08_GPT_ACTION_02_THREE_QUARTER_FULL_BODY_UAT.png` làm ref dáng/khung hình/gesture, giữ face và wardrobe thành hai input riêng, và thêm Krea2 adapter phân vai + cân bằng tỷ lệ. Prompt chung `prompts.json` không đổi; adapter riêng có hash trong revision manifest. Seed giữ `202610810012`, output prefix đổi sang `_R2`; job chưa submit. Bản R1 được lưu trong `comfyui/uat20-krea2-v001/history/ACTION_02_R1_BEFORE_POSE_ANCHOR/`. Face anchor R2 hiện dùng ảnh `CHAR_08_FACE_ANCHOR_USER_APPROVED_c921dfea.png` anh đã duyệt. UAT vẫn chưa submit và kết quả sinh ra vẫn phải chờ anh review.

## Asset picker của ComfyUI

ComfyUI 1.55.17 ban đầu báo `SERVICE_DISABLED` cho Assets. Đã thêm `--enable-assets` vào `production-local/comfyui-docker/compose.yaml`; custom-node hardening/whitelist giữ nguyên và không bật asset hashing. Comfyui-Studio đã restart khi queue rỗng; asset scan hoàn tất ở trạng thái IDLE với 0 lỗi. Ba alias input-root là NTFS hard link tới nguồn trong `newtecons-r078`, cùng SHA256, không nhân đôi dữ liệu; mỗi ảnh cũng có asset record để UI picker hiển thị.

Sau khi refresh phiên mới, FACE01 và ACTION06 mở trên 8188 với ba ảnh tham chiếu đã chọn, nút Run hoạt động và không có Missing Inputs. Không có job nào được gửi. Tab board `CHAR_08_Tran_Thao_Mai_10_Bieu_Cam_10_Hanh_Dong` trong phiên cũ vẫn giữ ba lỗi ở trạng thái unsaved; bỏ qua tab đó khi UAT và chọn các graph trong folder UAT mới.
