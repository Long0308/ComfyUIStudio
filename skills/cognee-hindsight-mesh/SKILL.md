---
name: cognee-hindsight-mesh
description: "Tra cứu hai kho Cognee và Hindsight bằng tool/MCP hoặc bridge hiện có. Phân biệt Semantic Graph trích văn bản GLiNER với AST/call graph, kiểm nguồn và hash, giữ riêng bank local và VPS, cung cấp context có xuất xứ cho agent."
---

# 🧠 Cognee-Hindsight Mesh — Hệ Thống Ký Ức 2 Bán Cầu Não

## Checkpoint và tiếp tục phiên

Giữ [task/TODO snapshot và con trỏ chunk chung](../second-brain-harness/references/checkpoint-task-contract.md)
cho mọi IDE; không ingest nguyên transcript/checklist vào graph hay bỏ qua incident hold.

Khi lưu trước compact/final hoặc khôi phục, dùng [prompt checkpoint chung](../second-brain-harness/references/compact-and-resume.md).
Xác định đúng runtime/UUID; đọc lại nội dung/hash từng kho, giữ capsule cục bộ và
checkpoint khôi phục trước đó nếu thiếu bằng chứng. Cloudflare chỉ tham gia khi đường gọi đi qua edge.
Portable entrypoint is `second-brain-harness`; its checkpoint runner reports
Cognee as `held` under PLAN CTX-F12 / HANDOVER R95 until the user changes that decision.

## UAT kiến trúc và capability hiện hành

Khi skill này tham gia luồng agent tại SetupAgent, đọc [cổng UAT chung](../astra-orchestrator/references/task-tracking.md#architecture-uat-and-capability-refresh).
Trạng thái lấy từ PLAN/audit và goal host hiện tại; checkpoint có ngày chỉ chứng
minh revision đã đo. Kiểm riêng nguồn/mirror/budget, tool-hook đã chạy, model nhận
context, nghiệm thu task và readback từng kho. Không nạp toàn catalog vào capsule.


> Trạng thái canonical: goal state: read current host · architecture NOT_ACCEPTED · productionAccepted=false.
> Đọc `D:/61.SetupAgent/docs/PLAN-2026-10-03-agent-live.md` và `D:/61.SetupAgent/docs/AUDIT-2026-10-08-agent-architecture-e2e.md`
> trước mọi mốc lịch sử; narrative R15k–R26 giữ nguyên văn ở
> [dated checkpoints](references/dated-checkpoints.md).

## Recovery and compact gates · R49

Read canonical PLAN/audit and [tracking gates](../astra-orchestrator/references/task-tracking.md).
Preserve main/WAL/shadow and expected hashes;test recovery on copies. Reuse
cognee_runtime.engine_lock at the SAME canonical path as writers;another lock
or an open handle does not exclude writers. Decode all WAL records against
version-matched native source. Checksums/byte coverage are not logical equality;
resynchronization/attested scopes stay evidence-only. Refuse unknown types.

Native0.19 diagnosis:r40-wal-source-acceptance.json in the canonical audit
directory verifies writer/reader growth discards accumulated prefix. A checksum
may attest an already corrupted length. Repair BOTH helpers before large-entry
native replay;review shadow/checkpointer semantics. Never use
throwOnWalReplayFailure=false as recovery:the native failure branch deletes
shadow/frozen WAL. Reader runtime and lossless recovery need separate proof.
Independent frozen-copy recovery is scoped:shared-main reader agreement
and matching shadow pages do not supply a full precrash oracle or authorize
production promotion. Copy availability and current service recall are distinct.

Promotion requires completeness BEFORE mutation,actual writer fence,backup,
no-clobber quarantine/rollback,full logical equality and independent-PID stored
source/hash readback. No synthetic relations. Exit3221226505 is0xC0000409;
exact crash cause needs evidence. Missing proof keeps the gate failed.
Compact/resume saves task/source checkpoint;keep pending Cognee separate from
verified Hindsight/Obsidian. Retry exact manifests;normal restore pointer stays
unchanged on partial persistence. Fresh OS200 does not fix cached MCP401.

Query-entry gate:a child/alternate CLI or direct query path must enforce the
reviewed owned isolated environment BEFORE import or search.
A measured env-boolean bypass proved R46_QUERY_EXECUTE=1 plus any existing
COGNEE_ENV_FILE reaches cognee.search while INDEPENDENT_REVIEW_ACCEPTED is False,
with no ownership token,no process registry,no scratch allocation and no
canonical engine lock,even against PRODUCTION roots. So:no real query before a
fresh independent review of the corrected source;a declared
MAX_QUERY_TIMEOUT_SEC is not enforcement,measure the kill;a receipt field is not
a WAL-consistency proof,use SQLite Online Backup not file existence;and a
name-only write-token scan is a tripwire,not proof.
Catalog/model/metadata/neon does not prove an automated workflow;skill/memory
retention is not model weight training and is not API or neon acceptance.

Copy-query isolation is a separate saved-source gate. Allocate an exclusive
scratch child with a plain bounded prefix,token and process registry binding.
Containment checks must precede creation,not follow it. Inspect marker and every
descendant for links/junctions before chmod/delete;cleanup cannot touch foreign
targets. Existing siblings are never owned. Refuse unknown/changed ownership.
Snapshot SQLite through backup including committed WAL;relocate stored paths.
Set isolated COGNEE_ENV_FILE before import in a scrubbed subprocess;do not import
the canonical runtime that forces production env/lock. Review bounded adapter
before real query. Fixture PASS cannot establish service availability or restore.

## ⓿ Tổng Quan 2 Bán Cầu Ký Ức

```
┌────────────────────────────────────────┐       ┌────────────────────────────────────────┐
│      BÁN CẦU TRÁI (COGNEE GRAPH)       │       │      BÁN CẦU PHẢI (HINDSIGHT BRAIN)    │
│  (Semantic Structural Knowledge Engine)│       │       (Episodic Experiential Memory)   │
├────────────────────────────────────────┤       ├────────────────────────────────────────┤
│ • Mô hình ECL: Extract ➔ Cognify ➔ Load│       │ • Cổng Local :8890 (8 bank may-*)      │
│ • Nodes: Class, Tool, Service, Model   │  API  │ • Cổng VPS :8888 (11 bank NEX KKT)     │
│ • Edges: DEPENDS_ON, CALLS, MAPS_TO    │ ◄───► │ • Quyết định kiến trúc & bài học lỗi   │
│ • Pydantic Schema định kiểu chặt chẽ   │ CẦU NỐI│ • Context Capsule tối đa 5 fact [ĐO]   │
│ • GraphRAG truy vấn quan hệ đa bước    │       │ • Ngăn ngừa rò rỉ vùng Zalo ra GitHub  │
└────────────────────────────────────────┘       └────────────────────────────────────────┘
```

---

## ① Hai Kho Không Trộn — Quy Tắc An Toàn Dữ Liệu
Tuân thủ nghiêm ngặt skill `hindsight-ky-uc-phan-tang`:
1. **Local BIM02 (`127.0.0.1:8890`):**
   - Lưu trữ tri thức mã nguồn C# Revit CAD (`LP/`), công cụ Cloudflare Edge, và tài liệu repo.
   - Đi lên GitHub qua repo này.
   - Bank đích: `may-agent-memory`.
2. **VPS NEX (`192.168.26.10:8888`):**
   - Lưu trữ sơ đồ quan hệ dịch vụ NEX, luồng Webhook Zalo và dự án công trường.
   - **TUYỆT ĐỐI KHÔNG KÉO VỀ MÁY LOCAL ĐỂ TRÁNH LỌT VÀO GIT.**
   - Bank đích: `kkt` hoặc `da-kkt-*`.

---

## ② Cách Sử Dụng Cầu Nối `tools/cognee_hindsight_bridge.py`

> 🩸 **ĐÍNH CHÍNH 2026-10-03 (có số đo).** Hai mô tả cũ ở mục này SAI SỰ THẬT và đã
> được sửa. Bằng chứng: `docs/agent-cognee-evidence-2026-10-03.json`.
> 1. Bản cũ ghi *"đẩy thành 25 Fact"*. Đo thật: CLI trần ghi **39 fact, trong đó 16
>    fact là BỊA** — sinh ra từ danh sách gõ tay khi thiếu `LP/`. Con số 25 chưa bao
>    giờ đúng.
> 2. Bản cũ ghi cờ `--vps` đẩy lên `:8888` bank `kkt`. Đo thật: `brain_bridge.retain_fact`
>    **hardcode `HINDSIGHT_LOCAL_URL`** (`brain_bridge.py::retain_fact`), nên dữ liệu dán nhãn VPS
>    rơi vào bank **LOCAL**. Cờ này **đã bị vô hiệu, thoát mã 2**.
>
> **Quan trọng:** cầu nối này là **TEXT-SCAN thuần Python, KHÔNG gọi engine Cognee.**
> Muốn dùng engine Cognee thật, xem mục ②b. Đừng lẫn hai thứ.

### 1. Quét đồ thị phụ thuộc (CHỈ ĐỌC — mặc định không ghi):
```powershell
python tools/cognee_hindsight_bridge.py --lp-dir <đường_dẫn_LP_thật>
```
* Quét chuỗi trong file `.cs` để suy quan hệ phụ thuộc `LP/Lib/`, `Wpf.Ui`.
* **Thiếu thư mục nguồn ⇒ ném `SourceMissingError`, 0 fact.** Không có nhánh rơi về
  danh sách gõ tay. Muốn ghi phải nêu rõ `--sync` kèm nguồn quét thật.
* Nhãn bộ sinh là `bridge-textscan`, **không phải** `cognee`.

### 2. Topology NEX — khai tay, KHÔNG được sync:
* Topology NEX trong mã nguồn mang `confidence=declared` (hằng số người gõ, chưa đối
  soát hệ thật) và **bị chặn đồng bộ**. Cờ `--vps` đã vô hiệu (xem đính chính trên).

---

## ②b Engine Cognee THẬT — `tools/cognee-runtime/cognee_runtime.py`

Đây mới là bán cầu trái chạy engine thật: **cognee 1.6.2**, Python 3.12.12, lưu bền
xuống đĩa, **không cần khoá API** (fastembed CPU + GLiNER cục bộ).

```powershell
$py = "tools\cognee-runtime\.venv\Scripts\python.exe"
& $py tools\cognee-runtime\cognee_runtime.py probe      # khai báo engine + đường dẫn kho
& $py tools\cognee-runtime\cognee_runtime.py readback   # chạy ở TIẾN TRÌNH KHÁC
```

🩸 **BẪY SỐ 1 — rò khoá workspace.** `cognee/__init__.py` gọi `load_env_file()` ngay lúc
import, và nạp bằng `dotenv.load_dotenv(override=True)`: **file `.env` THẮNG biến môi
trường đặt sẵn.** Đo thật 08:36:20Z, khi chưa chặn, log ghi nguyên văn
*"Loaded settings from D:\61.SetupAgent\\.env"* — tức file khoá của cả workspace bị kéo
vào tiến trình Cognee. Cách chặn duy nhất: đặt `COGNEE_ENV_FILE` trỏ file riêng
**TRƯỚC** khi `import cognee`. Đặt sau là vô tác dụng.

🩸 **BẪY SỐ 2 — kho rơi vào site-packages.** Mặc định kho nằm trong
`.venv/Lib/site-packages/cognee/.cognee_system/databases`, **mất khi cài lại gói**. Đã
trỏ về `.runtime/cognee` (SQLite + Kuzu + LanceDB).

🩸 **BẪY SỐ 3 — tên gói trích thực thể.** Runtime không khoá cần **`gliner2` + `torch`**,
KHÔNG phải gói tên `gliner`. Dò nhầm tên sẽ tưởng bản cài hỏng.

**Số đo 2026-10-03** (từ engine đang chạy, không phải số gõ sẵn): 88 node / 285 cạnh;
nạp 4 nguồn có `sourcePath + sha256`; truy vấn `CHUNKS` + `CHUNKS_LEXICAL` trả đúng
file nguồn; tiến trình mới (PID khác) đọc lại **cùng 8 ID, cùng 88/285** ⇒ dữ liệu nằm
trên đĩa thật.

⚠️ **Đồ thị này KHÔNG phải AST.** Nó do GLiNER trích từ **văn bản** của các gói nguồn.
Không phân tích cú pháp C#/Python. Đọc 88 node mà tưởng là call-graph là hiểu sai.

### Nguồn kiểm chứng hiện hành

`tests/kiem_thu_cognee_bridge.py` của chỉ dẫn cũ hiện không có trong workspace;
không gọi đường dẫn đó hoặc dùng số 17/17 lịch sử làm kết quả hiện tại.
Các nguồn kiểm thử liên quan đang có: `tests/test_cognee_fixed_source_readback.py`
và `tests/test_cognee_runtime_lock.py`. Chúng có phạm vi riêng; không thay thế
readback graph ở PID độc lập hay xác nhận nguồn/hash hiện hành.
Trước chạy, kiểm dependency, review và incident gate trong PLAN/Astra. Khi hold
còn hiệu lực, chỉ inspect nguồn và receipt cũ; không retry engine. Các số đo
2026-10-03 ở trên vẫn là bằng chứng lịch sử đúng revision đó.

---

## ③ Ứng Dụng Trong Luồng Code Cùng `astra-orchestrator`

Trước khi `worker` sửa một file C# hoặc cấu hình hệ thống:
1. **Pha Tra Cứu (Explorer):** Đọc engine Cognee và nguồn thật; text-scan chỉ hỗ trợ tìm chuỗi, không chứng minh AST/call graph:
   - *"Tool này đang phụ thuộc vào những module nào?"*
   - *"Hàm này nếu sửa có ảnh hưởng đến tool nào khác trong `LP/` không?"*
2. **Pha Đối Soát (Reviewer):** Tra cứu Hindsight để kiểm tra bài học quá khứ:
   - *"Trước đây hàm này đã từng gặp sự cố gì? (Bẫy Flat Table, bẫy VRAM, bẫy Token Clipping?)"*
3. **Pha Thỏa Thuận (Dots Consensus):** Cả 3 vai thống nhất dựa trên **Đồ thị của Cognee** và **Bài học của Hindsight** trước khi tiến hành ghi mã.

---

## ④ Cập Nhật Nghiệm Thu & Bài Học Kiến Trúc · R91 (16/10/2026)

### 1. Nghiệm thu E2E Máy con BIM05 (anh.tranhuynh)
* **Kết quả đo thực tế:** 8/9 Provider PASS qua Cloudflare Tunnel Edge (`api.lpopenbim.cloud/v1`).
  - OpenCode Go (DeepSeek v4.1, GLM 5.3): PASS (5.7s).
  - Google Antigravity (Gemini 3.8 Flash High): PASS (6.8s).
  - Claude Code (Opus 5.5): PASS (4.0s).
  - Command Code (GPT-5.6), xKiro (Mistral), OpenRouter: PASS.
  - ChatGPT Account Pool: PASS (1.9s).
  - Riêng Antigravity Opus 5.5 fail 429 do rate-limit tài khoản Google cá nhân.
* **Bài học phân tầng Token:** Máy con (BIM03, BIM05, Laptop) là Client tiêu thụ, chỉ nhận 9 token riêng biệt (`ROUTER-BIM05-*`) kéo từ Cloudflare KV Vault. **Tuyệt đối không cấp Master Key Admin của 9Router hay New-API cho máy con**.

### 2. Sự cố Rò rỉ RAM Electron & Kẹt Hàng đợi (App Server Request Expired)
* **Hiện tượng:** 18 tiến trình `ChatGPT.exe` và `codex.exe` ngốn tới **5.34 GB RAM** sau phiên dài (441 subagents, 345k tokens), hàng đợi IPC bị khóa bởi các tiến trình con bị interrupt $\rightarrow$ văng lỗi `App server request expired while queued`.
* **Cách khắc phục chuẩn hóa:** Chạy `powershell -ExecutionPolicy Bypass -File "D:\61.SetupAgent\_restore_and_restart_codex.ps1"`. Đóng sạch 18 tiến trình, giải phóng $90\%$ RAM (còn $\approx 500\text{ MB}$), đồng bộ 7 Projects tiếng Việt vào `state_5.sqlite` và mở lại app Codex mượt mà.

### 3. Sửa lỗi Treo Widget Tài khoản trên `:4400`
* **Nguyên nhân:** Xung đột tài khoản trùng lặp `codex.v3@newtecons.vn` trong pool (`acct_JH5...` trùng `acct_kuN...`) làm ném lỗi `registered more than once` $\rightarrow$ gây timeout và treo widget ở dòng `Đang đọc tài khoản… --`.
* **Khắc phục:** Loại bỏ bản ghi trùng trong `chatgpt-account-pool.json`; sửa `server/index.mjs` đọc ưu tiên `account.identity.email`; bổ sung fallback chọn tài khoản đầu tiên trong `dash-tab.js`.

### 4. Lưu vết Hindsight (`:8890`)
* Đã lưu toàn bộ bài học và mốc nghiệm thu vào 2 bank:
  - `may-agent-memory` (Bank tri thức kỹ thuật & Cloudflare của BIM-02).
  - `may-61-setupagent` (Bank quản trị hệ sinh thái SetupAgent).
