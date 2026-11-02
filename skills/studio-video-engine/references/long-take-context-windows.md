# Long take bằng H3 + context windows (nhánh LONG-TAKE, ĐÃ XÂY trên CPU, CHƯA ĐO GPU)

Trạng thái 2026-11-01: **đã xây và test trên CPU (BP-42), CHƯA chạy GPU, CHƯA qualify.** Mục d mô tả đúng cái đã xây. Không có số nào ở đây là kết quả chạy GPU, trừ các mục ghi rõ "đo 2026-11-01 qua /object_info". Runbook UAT GPU: `docs/plans/2026-11-01-two-systems/LONGTAKE-UAT-RUNBOOK.md`.

## a. Mục đích

- Dùng khi **một shot là một cú máy liền dài hơn khoảng 15 s** (một chuyển động camera liên tục). Ngưỡng 15 s khớp với vùng huấn luyện của node H3 (xem mục b).
- Phim cắt (nhiều shot 2–5 s) **không cần** nhánh này. Cắt giữ khuôn mặt và logo ổn định hơn một cú dài. Ep05 NEWTECONS là phim cắt nên không dùng nhánh này.
- Phù hợp cho: NEWTECONS đi quanh công trường (tracking, reveal một cú), và JennieJoyKids các cảnh kể chuyện liền dài.

## b. Đã đo 2026-11-01 qua ComfyUI `/object_info` (ComfyUI 0.41.0, `system_stats` xác nhận)

Đo bằng GET read-only tới `127.0.0.1:8188/object_info/<node>`. Không POST, không queue, không GPU.

Node có sẵn, **không cần cài thêm**:

| Node | Ghi chú đo được |
|---|---|
| `ContextWindowsManual` (core) | input bắt buộc: `model`, `context_length`, `context_overlap`, `context_schedule`, `context_stride`, `closed_loop`, `fuse_method`, `dim`, `freenoise`, `cond_retain_index_list`, `split_conds_to_windows`, `latent_retain_index_list`, `causal_window_fix`. Mặc định: `context_length` 16, `context_overlap` 4, `context_schedule` `standard_static`, `context_stride` 1, `freenoise` false, `split_conds_to_windows` false. Output: `MODEL`. |
| `MiniMaxH3ImageToVideo` | `width` 1344 (mặc định, bước 32), `height` 768 (mặc định, bước 32), `length` mặc định 124, min 5, bước 17. |
| `MiniMaxH3ReferenceToVideo` | có mặt. |
| `MiniMaxH3AddGuide` | có mặt. |
| `MiniMaxH3FunControlNetApply` | input: `model`, `model_patch`, `vae`, `strength`, `start_percent`, `end_percent`. Đây là khóa dáng cho VIDEO, cần model patch Fun-ControlNet của H3. **Model patch đó chưa tải** (theo ghi chú của user, chưa kiểm file trong phiên này). |
| `MiniMaxH3SigmaShift` | có mặt, mặc định `shift_video` 12.0. |
| `EmptyMiniMaxH3LatentAV` | có mặt, mặc định 1344 px. |
| `ConditioningCombine` | có mặt (dùng để nối prompt từng window). |

Tooltip của `length` (đọc nguyên văn từ node):
> Frame count at 24 fps, snapped up to the model's 17k+5 grid (124 = ~5s; trained range is ~124-362, longer is untested).

Từ đó:
- **Lưới frame H3 là 17k+5** (bước 17, lệch 5). Node tự làm tròn lên lưới này. Kiểm số học: 124 = 17×7+5, 719 = 17×42+5. Trước đó file `recipes/video/routes-v001.json` ghi lưới này là từ README của workflow NEWTECONS, với ghi chú "chưa đo trên NEWTECONS". Tooltip node là nguồn xác nhận mạnh hơn, nhưng vẫn chưa đo chất lượng trên NEWTECONS.
- **Vùng huấn luyện là 124–362 frame ở 24 fps**, tức khoảng 5–15 s. Đây là lý do ngưỡng 15 s. Trên 362 frame là "chưa thử" (untested), không phải "không chạy được".
- `context_length` đếm theo **latent**, không phải frame. Tỉ lệ latent↔frame của H3 **chưa đo**.

## c. Phương pháp từ post tham khảo (Pika H3 Flex, KHÔNG đo bằng máy của chúng ta)

Nguồn: ảnh graph và bảng user gửi ngày 01/11 (xem `docs/plans/2026-11-01-two-systems/USER-REQUEST-2026-11-01.md`, mục "Gợi ý user 01/11: MiniMax H3 Context Windows").

- Bảng số window theo độ dài:

| Độ dài (s) | 20 | 25 | 30 | 40 | 50 | 60 |
|---|---|---|---|---|---|---|
| Số window | 6 | 7 | 8 | 11 | 14 | 17 |

- Prompt được chia thành **phần tổng thể** (cast, wardrobe, style, lens, light, quy tắc âm thanh) và **một phần cho mỗi window**. Phần chia do LLM làm.
- Điều kiện của mỗi window được nối bằng `Conditioning (Combine)`.
- Giá trị trong graph tham chiếu: `MiniMaxH3ImageToVideo` 1344×768, `length` 719.
- Hai lưu ý của tác giả: (1) chuyển động liên tục **trôi theo độ dài**; (2) hành động có thứ tự (A rồi B) **làm không tốt**.

Suy luận của tôi, chưa đo: 719 frame ở 24 fps = 29.96 s, khớp với hàng 30 s của bảng. Có thể 719 là độ dài cả shot chứ không phải độ dài một window. Chưa xác nhận.

Ghi chú tên model: post gọi "Pika H3 Flex", còn node trong ComfyUI của chúng ta tên `MiniMaxH3*`. Chưa xác nhận hai cái là một.

## d. Cái đã xây (BP-42, CPU, 2026-11-01; chưa đo GPU)

Mã: `engine/video/longtake.py`; test `tests/video/test_longtake.py` (13 test); dữ liệu: khối `long_take` trong hàng `newtecons_live_action` của `recipes/video/routes-v001.json`.

1. **Input `take_mode`** = `short` | `long` | `auto` (mặc định `auto`). `auto` chọn long khi `duration_s` > 15 s (`long_take.auto_long_over_s`) hoặc shot có `long_take: true`; còn lại short. `decide_take_mode` trả `{take_mode, route, reason}` để ghi vào plan/run receipt. `short` -> route `h3-ref2va` (v008); `long` -> route `h3-longtake`.
2. **Từ chối có tên, không cắt lặng lẽ**: `short` tường minh trên shot dài = `TAKE_SHORT_ROUTE_REFUSED`; shot dài trên route ngắn = `LONG_TAKE_ON_SHORT_ROUTE` (`guard_route`); domain không có khối `long_take` = `LONG_TAKE_DOMAIN_REFUSED`; vượt 8 window = `LONG_TAKE_TOO_MANY_WINDOWS`; thiếu beat = `LONG_TAKE_NO_BEATS`.
3. **Route `h3-longtake`**: template `production-local/ComfyUI/user/default/workflows/NEWTECONS_H3/NEWTECONS_H3_LONGTAKE_v001.api.json`, sha256 `c4009207d6e3d74b2224dd46fbce6703b730a187a9ff26092d3b73dcb0ed8cdb` (v008 giữ nguyên `809fa9da…`). Cùng model, LoRA turbo 8 bước, cổng ref/anchor/WAV với v008; thêm `ContextWindowsManual` (node 22) trên đường MODEL (cho Guider và Scheduler); mỗi window một node prompt + một `MiniMaxH3ReferenceToVideo` (window 0 = node 19/6 giữ nguyên cổng của v008, window 1..7 = node 41..47 / 51..57), nối bằng `ConditioningCombine` (61..67) rồi vào `MiniMaxH3AddGuide`. 8 slot, cỡ 1280x704 (preview 864x480 do engine ghi đè qua `build_graph(width, height, length)`). `validate_workflow`: hợp lệ, 0 lỗi.
4. **Số window** `window_count`: BẢNG THAM KHẢO 20 s=6, 25 s=7, 30 s=8, 40 s=11, 50 s=14, 60 s=17 (bài đăng bên thứ ba, KHÔNG đo); giữa các điểm fit `floor(0.275*T+0.5)`. Ít window hơn 8 thì `build_graph` bỏ slot thừa và nối lại `AddGuide.positive` vào combine cuối; 60 s (17 window) cần template lớn hơn, hiện bị từ chối.
5. **Chia prompt** `split_prompt`: khối CHUNG là đúng kết quả `prompt.compose` (cast, luật trang phục, props, style, lens, light, luật âm thanh), không sửa; mỗi window = khối chung + một dòng `Window k of n (t0-t1 s ...): beat`. Vì mỗi window được mã hoá riêng nên luật trang phục/props có trong MỌI window. Beat lấy từ `windows[]` (đúng n phần tử) hoặc `beats[]` (trải đều), không tự bịa.
6. **Nhật ký từng window** `window_log`: chỉ số, giây, khoảng frame (chia đều, ước lượng), sha256 prompt.
7. **Qualification riêng**: `long_take.qualification` là `null`. Receipt h3 `30cd429b…` chỉ phủ `h3-ref2va`. Sau pilot GPU 20 s thành công, người vận hành ghi receipt hash-pinned riêng cho `h3-longtake`.
8. **Chưa nối vào CLI**: `video render --route h3-longtake` chưa được `engine/video/verbs.py` chấp nhận (nó chỉ nhận `h3_route`). Chỗ nối: `decide_take_mode` trong `plan.py`, `guard_route` thay phép so ở `verbs.py:57`, trường INPUT panel BP-20.

ĐOÁN, chưa kiểm (UAT phải trả lời): `context_length` 24 / `context_overlap` 6 / `dim` 2 trong template là giá trị đoán (đơn vị latent); `split_conds_to_windows=true` có gán đúng MỘT prompt cho MỖI window hay không (tôi không đọc được mã nguồn node); `MiniMaxH3AddGuide` có nhận conditioning nhiều phần tử đã Combine hay không; tám node R2V mỗi cái nạp lại ảnh ref (VRAM/thời gian thêm chưa đo).

## e. Dùng theo từng domain

**NEWTECONS (live action)**
- Trường hợp dùng: tracking đi quanh công trường, reveal một cú.
- H3 (route `h3-ref2va`, template v008-c2turbo) **đã được qualify cho NEWTECONS**: receipt `production-local/engine/qualifications/h3/newtecons-live-action-v001.json` có trên đĩa, sha256 `30cd429b…` khớp pin trong `recipes/h3/routes-v001.json` (root đo 01/11/2026). Receipt đó KHÔNG phủ nhánh long-take: `h3-longtake` phải có receipt qualification riêng sau pilot GPU do user duyệt, chưa có thì không chạy batch.
- Wardrobe (theo rule 31/10 trong `recipes/video/routes-v001.json`, `wardrobe_prompts`): `van_phong` (văn phòng, kể cả văn phòng container trên công trường) là áo sơ mi công ty, không mũ, không áo bảo hộ, không phản quang. `cong_truong` (ngoài trời trên công trường) là đủ bảo hộ, đội mũ. Long take không được đổi quy tắc này giữa các window.

**JennieJoyKids (3D cartoon)**
- Trường hợp dùng: cảnh kể chuyện liền dài.
- Tiêu chí nghiệm thu, recipe và prompt của cartoon **không** được chuyển sang NEWTECONS và ngược lại.

## f. CHƯA ĐO (kế hoạch pilot)

Các điều sau chưa đo:
- VRAM đỉnh và thời gian ở 1344×768 hoặc 1280×704, với độ dài dài, trên RTX 5080 16 GB.
- Trôi nhận diện (identity drift) giữa các window.
- Độ ổn định logo qua các window.
- Giá trị `context_length` và `context_overlap` phù hợp với H3.
- Tỉ lệ latent↔frame.

**Kế hoạch pilot:**
1. Chờ các job GPU đang chạy xong (theo ghi chú user 01/11: sau khi render xong 6 shot). Không chen vào.
2. Pilot **một shot 20 s** trên GPU, **chỉ khi người dùng duyệt** bằng câu lệnh rõ ràng cho đúng run đó.
3. Đo: VRAM đỉnh, thời gian, và mặt, wardrobe, logo của từng window (mỗi window một bản ghi).
4. Chỉ sau khi có kết quả đo mới qualify route. Ghi receipt qualification theo đúng mẫu `recipes/h3/QUALIFICATION.md` (receipt là file có hash, do người vận hành đặt, engine không tự ghi).

## g. Chỗ chưa biết

- Tên model trong post (Pika H3 Flex) và trong ComfyUI (MiniMax H3) có phải một không.
- Số 719 là độ dài cả shot hay độ dài một window.
- Ý nghĩa đúng của `context_length` theo latent với H3.
- Model patch Fun-ControlNet H3 có đang nằm trên máy hay không (chưa kiểm file).
