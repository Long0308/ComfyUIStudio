# Bàn giao 2026-10-28 (tối) → phiên 2026-10-29: engine xong vòng sửa, ngày mai làm film NEWTECONS người thật

Người viết: root Claude Opus 5.5. Mọi số dưới đây là số root **tự chạy lại**; chỗ nào chưa đo ghi rõ "chưa đo".

## 0. Đọc trước tiên (theo thứ tự)

1. File này.
2. `.agents/skills/create-video-newtecons/SKILL.md` và `references/local-comfyui-routing.md` (NEWTECONS = **live-action**, tách hẳn khỏi JennieJoyKids 3D cartoon).
3. `.agents/skills/studio-video-engine/SKILL.md` (verb index + gates), rồi `production-local/engine/WAVE-2026-10-28-PLAN.md`.
4. Bàn giao engine chi tiết: `docs/handoffs/2026-10-29-ENGINE-HANDOVER.md` (sha sau DOC-1: `1aca7c47…`).

## 1. Việc ngày mai (yêu cầu của user, 2026-10-28)

> "ngày mai sẽ làm thực tế trên film newtecons luôn cho người thật" ·
> "các nhân vật đã có prompt sẵn rồi, cần dùng codex tạo ảnh đầu vào nhân vật rồi tiến hành phân cảnh engine" ·
> thư mục: `production-local\JennieJoyKids-Story\Newtecons-TienDo-KichTinh-30s`

### 1a. Nguồn có sẵn (root đã đọc, đo)

| File trong thư mục trên | Nội dung đo được |
|---|---|
| `NEWTECONS_8_CHARACTERS_BIBLE.json` (sha256 bắt đầu `FABB9E03F38F`) | `characters` = 8 (CHAR_01…CHAR_08). Mỗi nhân vật có `japanese_film_prompt` (prompt tiếng Nhật, chất liệu phim người thật), `wardrobe`, `turnaround_views`, `expressions_matrix`, `face_reference_file`, `comfyui_workflow_file` |
| `KICH_BAN_NEWTECONS_TIEN_DO_30S.json` | khoá `project_metadata`, `character_bible_appearance_locks`, `scenes` |
| `STORYBOARD_NEWTECONS_30S.html`, `production-v2-45s/` | storyboard + kế hoạch 45s cũ (asset-pack-plan r002–r005, `imagegen-char08-v001`) |
| `casting/CHAR_08_Tran_Thao_Mai/` | chỉ CHAR08 có thư mục casting (V007R5 = **ứng viên chờ user duyệt**, không phải canon) |

### 1b. Quyết định của user và nguồn prompt chuẩn (đo 2026-10-28 khuya)

1. **Route (user chốt 2026-10-28, mở rộng):** **Codex làm cả ảnh đầu vào nhân vật LẪN chỉnh nhân vật** (nhận diện/trang phục). **ComfyUI local chỉ benchmark 1–2 ca** (cùng prompt/nhân vật/trang phục) để so sánh và tối ưu — "nếu codex làm tốt thì tiết kiệm được thời gian công đoạn này". Video vẫn ComfyUI local. Mỗi receipt ảnh ghi route + model thật.
   - Engine **không được** gọi thẳng codex-router `/v1/images` (luật cũ còn hiệu lực). Ảnh sinh bên Codex rồi đưa vào engine bằng import có receipt sha256. Engine hiện từ chối provider không phải local (`recipes/images/routes-v001.json`) → **chưa có verb nhận ảnh ngoài**; kiểm `python -I bin/jjv.py images --help` đầu phiên, nếu thiếu thì giao một worker làm verb import (failing test trước).
2. **Prompt chuẩn = bộ casting r005 do GPT tạo** (user xác nhận "đã có tôi thấy chuẩn"). Đo: `production-v2-45s/characters/CHAR_0N/prompts/r005/` có **20 prompt cho mỗi nhân vật, đủ 8 nhân vật** (kèm `character-r005.json`). Prompt r005 đã dẫn ảnh áo chuẩn: `SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png` (sha `55f0a34b…`), `ÁO PHẢN TRONG.png` (`59aba952…`), logo vest trắng `785e1770…`, logo mũ màu `e320eabb…`. → **Không cần đối chiếu lại bible.** Bible `japanese_film_prompt` là bản cũ, đừng dùng để sinh.
3. **Nhân vật mẫu = CHAR_08**: `production-v2-45s/imagegen-char08-v001/` (Image Gen 2, `resolved_model: NOT_EXPOSED_BY_TOOL`; manifest vẫn ghi `user_acceptance: PENDING` — user nói trong chat là chuẩn, chưa ghi vào manifest).
4. **Việc ngày mai: chạy tiếp CHAR_01–CHAR_07 bằng Codex từ prompt r005**, rồi benchmark 1–2 ca trên ComfyUI local. Lưu ý `active-image-requests-160.json` (sha `287E7E836DA9`, 160 dòng = 8×20, tất cả `PLANNED`, `requested_engine openai/gpt-5.4-image-2`) **còn trỏ prompt r003/r004** → dựng hàng đợi mới từ r005, giữ file cũ.
5. **Ảnh mặt tham chiếu:** bible ghi `AI HUMAN FACE.png` nhưng không có trong thư mục film; prompt r005 dẫn ảnh tham chiếu riêng — dùng các ảnh r005 dẫn tới, kiểm sha từng file.

### 1c. Engine chưa biết film này

- Thư mục film **không có** `engine/episode.json` → `jjv` chưa thấy NEWTECONS film. Bước đầu: tạo episode contract (`jjv config contract`, `jjv script ingest` từ `KICH_BAN…json`) rồi `jjv config validate`.
- Domain `domains/newtecons_live_action.json` (đo): 1920×1080 24fps, review 1280×720, độ dài 240–4320 frame, cấm `ClaudeNode`/partner nodes, custom node cho phép `comfyui-krea2edit`, `newtecons_live_preview`, `newtecons_branding`; **`allowed_recipes: []`** ở domain, voice và audio → các stage cần recipe sẽ **từ chối** cho tới khi có recipe NEWTECONS được duyệt. Đây là chặn có chủ đích, không phải lỗi.
- SeedVR2 recipe v003 **chỉ qua kiểm cho JennieJoy cartoon 864×480**. NEWTECONS cần pilot GPU riêng + receipt qualification trước mọi batch.
- Luồng ngày mai: (1) dựng hàng đợi CHAR_01–07 từ prompt r005 → (2) Codex sinh ảnh + chỉnh nhân vật, receipt từng ảnh → (3) benchmark 1–2 ca ComfyUI local cùng prompt, so sánh → (4) user duyệt ảnh → (5) tạo episode engine + `jjv storyboard` phân cảnh → (6) `jjv run episode --dry-run` để thấy các cổng. **Không GPU khi chưa có user cho phép đúng lần chạy đó** (benchmark ComfyUI cũng là GPU → hỏi trước).

## 2. Engine: trạng thái cuối phiên (root đã chạy lại)

| Việc | Kết quả root đo |
|---|---|
| M8-f1: DAG nối verb mới, health trước MỌI bước GPU, 3 sửa CR-M8 (approve cần `--sha256`, receipt cũ bị bỏ, override theo limit), mouth_boxes tuỳ chọn | tests/run + config 84 passed |
| M8-f2: SeedVR2 trong DAG = `segments → plan → adopt → execute` | 85 passed; DAG sha `2989482d6701` |
| SV2-GAP2: verb `seedvr2 adopt` (root đã nối vào `bin/jjv.py`, `--help` exit 0) | seedvr2 250 passed; Gemini critic PASS |
| H3-MB: chỉ báo `MOUTH_BOXES_NOT_DERIVABLE` khi tập có khai `files.mouth_boxes` | 53 passed (tests/h3 + mouth optional) |
| STAMP-2: receipt `boundaries.current` + marker có stamp; publish không đổi gì thì không ghi lại | 79 passed (gộp GUARD-1) |
| GUARD-1: test cấm conftest thứ hai; test từ chối take trên cả tập | (trong 79) |
| M9b-7: Studio gọi `run episode` dry-run + approve, panel review | Studio 720 passed, 1 skipped; `node --check` OK |
| `jjv frozen verify` | RESULT ALL MATCH |
| ep04 dry-run | exit 0, FIRST STOP `voice [gpu-approval]`; 0 file ghi vào ep04 |
| Hash config ep04 | `config_sha256 769d47fb…` không đổi; bất biến là `config_core_sha256 bc062daf…` |
| **Full suite** | **2719 passed, 3 skipped, 609,5 s, exit 0** (root chạy, basetemp trong scratchpad). Lượt này bắt đầu TRƯỚC khi H3-MB và M8-f2 ghi xong; hai việc đó đã được root chạy lại cổng riêng sau khi xong (53 và 85 passed). Đầu phiên nên chạy lại một lượt full suite sạch: `python -B -m pytest tests -q -p no:cacheprovider --basetemp <thư mục NGOÀI production-local, tạo cha trước>` |

Chưa đo trên thật: chưa verb mới nào chạy thật qua orchestrator (chỉ dry-run + FakeRunner), chưa GPU.

### Việc engine còn lại (không chặn NEWTECONS ngày mai)

- CR-M8f1 (DeepSeek): approval ghi sha không đối chiếu lúc ghi (cổng vẫn đối chiếu lúc kiểm) → root hạ **MINOR**; `pre` check không chạy lại khi dùng lại stage → **MAJOR hẹp**. Xếp hàng cho engine/run.
- CR-M8bg5: `deliver init` `_machine_path` chưa chặn phạm vi lúc init (publish chặn lại trước khi ghi) → MINOR; TOCTOU junction → MINOR.
- deliver film-2k / brand / publish dùng `--out` cố định, chạy lại lần 2 bị từ chối cho tới khi dời thư mục cũ (đã ghi trong note DAG).
- M9b-8 UAT Studio; quyết định file trùng `engine/editorial/master_config.py`; thu hẹp fixture autouse docker trong `tests/conftest.py`.
- HASHES.md dòng 8 ghi "6 keys" nhưng liệt kê 7 → sửa con số.
- Thư mục lạc `.agents/skills/studio-video-engine/production-local/engine/staging/M8b-f3` (worker cũ tạo bằng đường dẫn tương đối) → xem rồi dời, đừng xoá mù.

## 3. Chờ user

- ep05 JennieJoyKids: chốt chủ đề (đề xuất *Tidy Up Time*, nháp `staging/ep05-draft/script.json` `7a651a00`) và cho phép GPU pilot M10. **Tạm hoãn** vì ngày mai làm NEWTECONS.
  - Số đo tham khảo: SeedVR2 ep04 = 134 chunk, **385,6 phút GPU (~6,4 h)**, TB 173 s/chunk, max 405 s; phim 132,4 s. Voice / layout / ảnh / H3: **chưa đo**.
- Router (D:\61.SetupAgent): chạy `.runtime\user-scripts\hr12-apply.ps1`, `gemini-accounts-9router.ps1`; tạo key remote-access 9Router (Gemini qua pool đang 401); quyết định ai chạy `hr7-deploy-sessions.ps1`; sửa permission rule gộp sai thành từng rule riêng.

## 3a. Kiến trúc router (D:\61.SetupAgent): plan làm tiếp

Code đã xong, đã nghiệm thu và đã push (`5946a5ed`). Gồm HR-1, HR-3, HR-6, HR-9…HR-19, HR-20…20f (source), HR-7a/7b, HR-13b. Audit tổng vẫn ghi `architecture NOT_ACCEPTED`: muốn accepted thì việc 1 và 4 dưới đây phải chạy được trên thật, rồi qua một lượt UAT đầu cuối.

| # | Việc | Ai | Lệnh / điều kiện |
|---|---|---|---|
| 1 | Gemini qua pool (HR-20 live: 401 "API key required for remote API access") | user tạo key → root | tạo key remote-access trong dashboard 9Router, lưu vào `.env` dưới **tên mới** (không dán vào chat) → root thêm tên vào allow-list `MODEL_ROUTER_LOCAL_9ROUTER_KEY_ENV` → chạy lại PONG qua pool |
| 2 | HR-21: xem 5 tài khoản Gemini | user | `powershell -ExecutionPolicy Bypass -File D:\61.SetupAgent\.runtime\user-scripts\gemini-accounts-9router.ps1` (chỉ đọc) |
| 3 | HR-12: áp mapping vào DB New-API | user (ghi DB cần user cho phép) | `powershell -ExecutionPolicy Bypass -File D:\61.SetupAgent\.runtime\user-scripts\hr12-apply.ps1` → script tự chạy PONG 2 model |
| 4 | HR-7c: bật panel Sessions trên :4400 | user chốt ai chạy | `hr7-deploy-sessions.ps1` đã sẵn, CHƯA chạy |
| 5 | HR-2c failover thường trực · HR-8 đẩy Vault (`--push` ghi đè toàn bộ) | user quyết | root đề xuất hoãn cả hai |
| 6 | 16 alias bị chặn | — | đề xuất giữ |
| 7 | HR-5: dòng OPT-1 trộn hash byte-đĩa và blob git | root | chỉ sửa chữ trong PLAN |
| 8 | Engine tích hợp SetupAgent | root, sau khi có repo | cần repo root cấu hình được (`engine/config/loader.py:29`) trước khi dời |

Thứ tự đề xuất cho 2026-10-29: tạo repo 03 Voice → việc 1, 2, 3 (mỗi việc một lệnh) → PONG Gemini → việc 4 → NEWTECONS CHAR_01–07.

## 3b. Git (đo 2026-10-28 khuya)

- `D:\61.SetupAgent` main = origin/main = `f41033c9` (đã push):
  - `5946a5ed`: router HOME-R28, gồm pool option B, sessions tracking, pong matrix, newapi sync, harness-openspec C03 test fix, skill codex-router + astra-orchestrator.
  - `927b308f` + `f41033c9`: snapshot skill 03 Voice ở `skills-snapshots/jenniejoy-03voice/`. Đây chỉ là bản backup, không phải canonical, và nằm ngoài `.agents/skills` để `sync_skills_all_ide.py` không chép đè adapter. 187 file test được add `-f` vì luật `.gitignore:195 test_*.py`; `.bak`, `.log`, `.mp4` vẫn bị ignore.
- `D:\23.JennieHomeSchool\03 Voice` **chưa có repo git**. User sẽ tạo repo riêng ngày 2026-10-29. Muốn tích hợp hẳn engine vào SetupAgent thì phải sửa trước một chỗ: engine tự tính `REPO_ROOT = SKILL_ROOT.parents[2]` (`engine/config/loader.py:29`) rồi đọc `<REPO_ROOT>/production-local/engine/machine.json`. Đặt engine ở `D:\61.SetupAgent` thì nó tìm `production-local` sai chỗ và ngừng chạy. Cần một repo root cấu hình được (có test) trước khi dời.

## 4. Luật đang hiệu lực (không đổi)

Không GPU khi chưa có user cho phép đúng lần chạy · không partner/cloud node trong graph · không ghi vào ep04 · giữ ep03 Master v005 và mọi asset/receipt NEWTECONS cũ · không in key/token, không đọc `auth.json` · Gemini chỉ làm critic đọc ≤5 file (một lượt đo 2,3M token) · ảnh/output/QA kỹ thuật/duyệt hình/phim hoàn chỉnh là các trạng thái khác nhau.
