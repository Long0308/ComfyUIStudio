# IMGRT-FIX — báo cáo builder

Ngày 2026-10-31. ParentSessionId: `30c5e1c7-1da0-4a7c-9d0b-6b6f93b352aa`.

Đã sửa ba gap và cài bốn file production bằng file tạm + `fsync` + `os.replace`, sau khi candidate đạt **85 passed**. Không commit, không restart tiến trình render, không gửi job GPU/API, không sửa production-local. Bản gốc được giữ trong `original/`; bản đã kiểm thử nằm trong `candidate/`.

## Thay đổi và file:line

| Gap | Vị trí | Kết quả |
|---|---|---|
| 1 — domain không rõ | `engine/images/codex_queue.py:63`, `:100`, `:112`, `:254` | Loader giữ domain row và domain document. Hỗ trợ document `{ "domain": "...", "rows": [...] }`; từ chối domain mâu thuẫn. Domain provenance_required không còn chấp nhận row thiếu domain tùy ý. |
| 1 — legacy r005 | `engine/images/codex_queue.py:100` | Chỉ queue có tên khớp `queue-r005[a-z]*.json`, domain episode NEWTECONS, đường dẫn đã resolve nằm trong staging của episode. Ngoại lệ lịch sử còn yêu cầu đúng cả ID và canonical root của `Newtecons-TienDo-KichTinh-30s` trước khi nhận staging tập trung `production-local/engine/staging/newtecons-30s`. |
| 1/2 — cả hai submit | `engine/images/codex.py:110`, `:226`; `engine/images/local.py:96`; `engine/images/prompt_route.py:211` | Các cổng real submit truyền Context vào kiểm tra chung. Comfy loader cũng kiểm tra domain trước khi tạo prompt tạm. |
| 2 — xác nhận | `engine/images/prompt_route.py:146`; `engine/images/codex_queue.py:131`, `:172`, `:257` | Batch và row mới mang `source=prompt_route`; nhận diện thêm marker cũ `text_source=free-form`. Với provenance_required, đọc confirmation ngay tại gate, so schema, prompt_id, toàn bộ SHA-256 của text thực, tên queue, người xác nhận và timestamp có giá trị. Toggle dispatch_allowed không đủ. |
| 3 — canvas | `engine/images/prompt_route.py:108`, `:143`, `:152` | Vẫn chạy canvas gate cho mọi kind khi recipe có lock hoặc có aspect; lưu `canvas_check`. Khi không có lock/aspect, ghi đúng `no canvas lock for kind X`. |
| Tương thích | `engine/images/prompt_route.py:136`; `tests/test_images_codex_imgrt.py:107` | Chặn prompt ID trùng trong document-shaped queue. Test alias staging thật và episode khác; JennieJoy cả queue cũ và free-form giữ hành vi dispatch cũ. |

Tên biên lai giữ tương thích `confirmations/<prompt_id>-<sha12>.json`. Nội dung được đối chiếu **đủ 64 ký tự hash**, không chỉ prefix tên file. Không đổi recipe hoặc tự đặt lock mới cho SHOT/ASSET/SET/FIX.

## RED / GREEN — output thật

| Lượt | Output cuối | Log |
|---|---|---|
| RED ba gap, trước mọi sửa production | `18 failed, 7 passed in 2.47s`, exit 1 | `red-valid.txt` |
| RED staging alias và document duplicate | `2 failed, 32 passed in 21.22s`, exit 1 | `red-compatibility.txt` |
| RED bảo toàn cartoon free-form | `1 failed, 34 passed in 3.58s`, exit 1 | `red-cartoon-compat.txt` |
| GREEN candidate cuối, đủ bộ yêu cầu | `85 passed in 53.81s`, exit 0 | `green-ready.txt` |
| GREEN file đã cài | `85 passed in 56.07s`, exit 0 | `green-installed.txt` |

RED đầu gồm thiếu domain lọt qua cả hai provider, domain khác lọt qua Codex, queue document chưa được hỗ trợ, legacy nằm ngoài staging vẫn qua, thiếu source, toggle cờ bỏ qua confirmation, receipt sai vẫn qua, và thiếu ghi nhận canvas. Bốn test lock SHOT/ASSET/SET/FIX có recipe đã PASS trước sửa; lỗi gap 3 nằm ở việc không ghi rõ trạng thái khi không có lock.

Lệnh tái hiện (đứng tại skill root; đổi tên lượt chạy nếu đã tồn tại):

```powershell
python -I -B -c "import runpy; h=runpy.run_path('docs/IMGRT-FIX/run_tests.py'); raise SystemExit(h['run']('verification-new'))"
```

Harness gọi `pytest.main` với `tests/test_images_prompt_route.py` và toàn bộ `tests/test_images_codex*.py`, `-q --tb=short -p no:cacheprovider --basetemp .pytest_work_tmp/IMGRT-FIX`. Danh sách đầy đủ nằm đầu log. Mỗi lượt có cwd riêng dưới `docs/IMGRT-FIX/<label>/`; không tái sử dụng/xóa thư mục bằng chứng.

Lượt thử ban đầu `red.txt` gặp WinError 5 ở basetemp tại root. `red-regressions.txt` tiếp theo gặp thiếu thư mục cha; cả hai là lỗi harness, **không tính RED sản phẩm**. Harness dùng ACL kế thừa khi tạo thư mục test thay vì mode 0700 của Python 3.14 Windows. Candidate trial đầu `green-candidate.txt` có 74 passed/1 failed vì `codex.__file__` trỏ vào candidate làm test tìm sai recipe; đã sửa metadata đường dẫn trong harness. Các log lỗi được giữ nguyên.

## Bảo vệ lượt r005f đang chạy

Probe chỉ đọc đã kiểm tra **13 batch / 95 prompt** thực tế: load refs/hash và domain gate đều qua, không submit. Queue hash trước/sau bằng nhau:

`2e707950b74ce0f3f2ef606aa175ca6f653fc29388a491e02382925ab12543a4`

Chi tiết: `live-probe.json`; chương trình: `probe_live.py`. Mapping episode ↔ staging được đối chiếu trực tiếp tại `production-local/engine/staging/newtecons-30s/plan-r005f.json:4` và `:9`. Probe không đọc machine/auth.

`install.py` so byte production với snapshot trước khi thay, compile candidate, ghi file tạm sibling, flush/fsync rồi os.replace từng file. Thứ tự: codex_queue → codex → local → prompt_route, để signature mới có trước caller. Receipt `install-receipt.json` lưu hash trước/sau và hash log GREEN. Atomic ở mức từng file; không tuyên bố transaction bốn file hoặc hot reload tiến trình đã import module.

## Review độc lập

Code reviewer phát hiện alias staging thật và duplicate scan document-shaped queue; cả hai có RED rồi đã sửa. Python reviewer xác nhận không còn lỗi HIGH/CRITICAL trong scope, AST parse qua; đã kiểm lại việc giới hạn confirmation gate cho provenance_required để giữ JennieJoy.

Đã gọi đúng role `router_custom_oauth_anti_gemini_flash_high` (route cấu hình `custom/oauth-anti-gemini-flash-high`). Agent này tự báo model khác (`Claude 3.7 Sonnet`) và mô tả cả thao tác ngoài read-only bị chặn, nên **không coi tự khai đó là chứng cứ model thực hay chứng cứ PASS**. Không chủ động thay model. Backend model chưa được xác minh độc lập; kết luận dựa trên output test/probe trực tiếp và hai review trên. Các child đã được interrupt khi hoàn tất.

## SHA-256

`install-receipt.json` chứa hash bốn file production trước/sau. `SHA256SUMS.json` liệt kê hash file code, test, harness, report, log và snapshot do task tạo/giữ; không quét fixture pytest, không đọc `.env` hoặc `auth.json`. Manifest không tự hash chính nó.

## CHỖ NÀO BẠN ĐOÁN — NÓI THẲNG

1. Ban đầu giả định staging nằm dưới ctx.root; test đầu chưa đại diện layout thật. Đã sửa bằng alias hẹp sau khi đọc episode và plan r005f thực tế, rồi probe đủ 95 prompt đang có trong batch.
2. Chọn format document `{domain, rows}` để thể hiện domain ở cấp file vì queue cũ chỉ là JSON array; đây là quyết định triển khai, không phải format lịch sử đã đo được.
3. Không suy diễn canvas lock của phim từ kích thước delivery. Recipe đang chỉ khóa FACE/ACTION; kind khác được ghi rõ không có lock, đúng phương án user cho phép.
4. Confirmation là chứng cứ local có hash, không có chữ ký số. Người sửa được cả queue, batch và receipt vẫn có thể giả mạo toàn bộ; task này chặn toggle cờ và receipt không khớp, không xây hệ thống xác thực người dùng mới.
5. Không chạy GPU, không đo chất lượng ảnh, không chứng nhận toàn bộ pipeline hoặc trạng thái hoàn thành live render. Test dùng fake Codex; live probe chỉ đọc.
