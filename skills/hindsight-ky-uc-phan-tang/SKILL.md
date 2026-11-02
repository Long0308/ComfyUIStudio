---
name: hindsight-ky-uc-phan-tang
description: "HAI kho ký ức Hindsight KHÔNG TRỘN — 8 vùng may-* dưới máy (lên GitHub) và 11 vùng NEX/Zalo trên VPS (KHÔNG BAO GIỜ lên GitHub). Dùng khi nạp/tra ký ức, khi chọn vùng để ghi, khi phải chứng minh không rò rỉ trước lúc push, hoặc khi recall trả rỗng. Triggers: hindsight, recall, retain, bank, may-agent-memory, quet_ro_ri, ký ức Zalo, BANK_RIENG_CSV, recall_brain, recall_graph, workspace_facts, which_bank, second-brain, bộ định tuyến."
---

# Hindsight — ký ức phân tầng, hai kho không trộn

## Checkpoint và tiếp tục phiên

Áp dụng [hợp đồng task/TODO + chunk](../second-brain-harness/references/checkpoint-task-contract.md).
Bank giữ fact đã tuyển; task đang mở và restore pointer nằm trong checkpoint/PLAN có nguồn.

Khi lưu trước compact/final hoặc khôi phục, dùng [prompt checkpoint chung](../second-brain-harness/references/compact-and-resume.md).
Xác định đúng runtime/UUID; đọc lại nội dung/hash từng kho, giữ capsule cục bộ và
checkpoint khôi phục trước đó nếu thiếu bằng chứng. Cloudflare chỉ tham gia khi đường gọi đi qua edge.
The portable entrypoint is `second-brain-harness`; the background
`SetupAgent-Context-Checkpoint` task retains only the newest successful native checkpoint.

## UAT kiến trúc và capability hiện hành

Khi skill này tham gia luồng agent tại SetupAgent, đọc [cổng UAT chung](../astra-orchestrator/references/task-tracking.md#architecture-uat-and-capability-refresh).
Trạng thái lấy từ PLAN/audit và goal host hiện tại; checkpoint có ngày chỉ chứng
minh revision đã đo. Kiểm riêng nguồn/mirror/budget, tool-hook đã chạy, model nhận
context, nghiệm thu task và readback từng kho. Không nạp toàn catalog vào capsule.


## Mốc goal/UAT R15k · 08/10/2026

[Checkpoint canonical](D:/61.SetupAgent/docs/AUDIT-2026-10-08-agent-architecture-e2e.md)
và [PLAN hiện có](D:/61.SetupAgent/docs/PLAN-2026-10-03-agent-live.md) giữ trạng thái hiện hành:
Goal state phải đọc từ host; checkpoint R15k là lịch sử. R15h storage đã verified cho SHA00720f33;revision mới phải có Hindsight document/hash đúng hiện tại. Không dùng queued hoặc snapshot cũ làm bằng chứng mới.
Receipt skill/memory phải khớp SHA hiện tại;sync file không chứng minh model đọc.


## Runtime và Live · 08/10/2026

Đọc [audit hiện tại](D:/61.SetupAgent/docs/AUDIT-2026-10-08-agent-architecture-e2e.md)
và PLAN LIVE-B01–B09 trước các số đo lịch sử ở references. Codex dùng cổng recall
mềm; UUID/runtime của CLI là caller-declared, chưa chứng minh IDE hoặc model đã
đọc context. Chọn model, hàng đợi và neon không chứng minh workflow tự động.

Recall bốn tầng đã từng hoàn tất ở r4 (20,280s, Hindsight6/Cognee10). Hai phép đo
mới r5/r6 thoát4: Hindsight6, Cognee unavailable sau30,159s/55,017s. Giữ cả FAIL
và PASS lịch sử; không báo engine hiện tại sẵn sàng dựa vào PASS cũ. DSH, VS Code,
Antigravity và Claude Code phải có receipt của chính runtime và UUID, không mượn
proof Codex. Quá24h là snapshot cũ; SHA chỉ xác nhận revision nguồn.

## ⓿ 🩸🩸 LUẬT SỐ MỘT — CẤM KÉO KÝ ỨC ZALO XUỐNG MÁY

| | 🖥 LOCAL (`bim02`) | ☁ VPS |
|---|---|---|
| Cổng | `127.0.0.1:8890` (API) · `:9999` (Control Plane) | `192.168.26.10:8888` · `:9999` |
| Chứa gì | **8 vùng `may-*` / `long-*`** — HANDOVER, skill, agent-memory, workspace | **11 vùng NEX** — hội thoại Zalo, ảnh công trường |
| Lên GitHub | **CÓ** (repo này) | **KHÔNG BAO GIỜ** |
| Chiều chảy | máy ⇢ chỉ skill / ngữ cảnh ổ C | VPS ⇠ **một chiều, KHÔNG kéo xuống** |

Kéo xuống là **sớm muộn nó theo `git push` ra GitHub** — y hệt việc để lộ `.env`.

**Ba lớp chặn:**

1. **Không có script kéo về.** Không tồn tại lệnh nào đồng bộ vùng VPS xuống máy.
2. **Cổng rò rỉ soi theo NỘI DUNG, không theo đường dẫn** — `python hoc/quet_ro_ri.py`.
3. **Vùng riêng tư khoá bằng mật khẩu**, khai trong `.env` → `BANK_RIENG_CSV`.

🩸 Bí mật **đã từng lọt vào chính README** (một uid Zalo + một số điện thoại) và
phải gỡ ra, thay bằng `«uid ẩn»`. Cổng phải chạy **trước mỗi lần push**, không phải
"khi nào nhớ".

---


## Quy trình dùng mỗi lượt

1. Đọc luật gốc §0b tại `C:/Users/philong.pham/.claude/rules/cach-lam-viec.md`.
   Gọi `which_bank` trước; workspace `D:/61.SetupAgent` chọn `may-agent-memory`.
   Không nạp lại các bank may-50/may-49 chỉ vì recall rỗng: lịch sử chúng là tập con.
2. Quét `recall_error_db`, tra nội dung Hindsight rồi Cognee engine thật trước sửa.
   Dùng agent Opus để diễn giải ký ức. Recall trả cùng skill/route/tool thì mở và
   dùng hoặc mở rộng nguồn đó. Error DB không match không có nghĩa bank rỗng.
3. Chọn đúng công cụ: `recall_brain` tìm CON TRỎ skill/file/bank; phải mở nguồn
   mà nó trỏ tới. Câu hỏi về quyết định/con số dùng `workspace_facts` hoặc
   `recall_graph`, không coi hit tên/tag của `recall_brain` là nội dung fact.
4. CLI bốn tầng phải đặt `--four-layers` đầu tiên: `recall.py --four-layers
   "<đối tượng>" --runtime <runtime> --session-id <UUID> --no-cache --receipt <file>`.
   Receipt Live ở `.runtime/memory-recall/<runtime>/<uuid>.json` chỉ giữ metadata.
   Timeout ghi unavailable, không dựng fact, không reset hoặc tăng timeout mù.
5. Xong việc đáng nhớ, chỉ retain fact chọn lọc/knowledge/preferences đã duyệt.
   HTTP202/queued chưa phải lưu bền: kiểm Hindsight đúng document/hash hoặc neo,
   Cognee đọc lại ở PID khác và SHA nguồn không đổi. Không nạp raw recall log,
   transcript hay suy luận tạm vào graph. Không xóa ký ức để làm cổng xanh.

`sync-memory-bank` §⑧·⑨·⑩ là nguồn chính về chọn tool và cổng
`brain_bridge_kiem.kiem_fact_trong_bank`; khi references lệch thì nguồn chính
thắng và phải cập nhật reference. Recall chỉ tìm thấy fact không đủ nghiệm thu retain.

## Đọc chi tiết khi cần

- Bản đồ LOCAL/VPS và đường API recall/retain: [references/banks-and-recall.md](references/banks-and-recall.md).
- Cổng `hoc/quet_ro_ri.py`, dấu hiệu và miễn trừ: [references/leakage-gate.md](references/leakage-gate.md).
- Tool con trỏ/nội dung, bẫy401/quota, bank rỗng, exit code: [references/tool-selection-and-incidents.md](references/tool-selection-and-incidents.md).
- Cổng nghiệm thu, retain/LLM/fallback và các skill nguồn: [references/acceptance-and-retain.md](references/acceptance-and-retain.md).
- Checkpoint trước khi tách, bảo toàn nguyên văn: [references/runtime-checkpoint-08oct.md](references/runtime-checkpoint-08oct.md).

Các số bank, fact, giá, model và cổng màu trong references là số đo có ngày,
không phải readiness hiện tại. Các lệnh restart lịch sử không tự cấp quyền chạy
trong một audit. Trước push chạy cổng rò rỉ trực tiếp và kiểm exit code thật,
không nối ống lấy exit code của lệnh cuối. Không kéo nội dung/tên bank VPS về Git.

## Mốc Nghiệm Thu & Cập Nhật Phân Tầng · R91 (16/10/2026)

1. **Bank `may-agent-memory` và `may-61-setupagent` (Local BIM-02 :8890):**
   - Đã ghi nhận mốc nghiệm thu máy con **BIM05**: cài đặt thành công 8/9 Provider PASS qua Cloudflare Tunnel (`https://api.lpopenbim.cloud/v1`).
   - Khắc phục triệt để lỗi LiteLLM exit code 103 bằng việc chốt cứng 107 thư viện (`requirements/python.txt`) qua `uv`.
   - Triệt tiêu popup UAC Domain Sandbox bằng `[windows] sandbox = "unelevated"`.
2. **Nguyên tắc Phân Tầng Ký Ức & Quản Trị Đa Máy:**
   - **Máy con (BIM03, BIM04, BIM05, Laptop):** Chỉ là client tiêu thụ qua New-API (`:3300`) và Tailscale/Cloudflare. **Không có quyền truy cập vào 9Router (`:20128`)** hoặc Master Key.
   - **Bảo toàn dữ liệu cá nhân:** Quá trình `update.cmd` trên các máy tuyệt đối không ghi đè `.env`, `chatgpt-account-pool.json` hay các Token đăng nhập ChatGPT cục bộ.
3. **Bài học Sửa lỗi Xung đột Tài khoản Pool:**
   - Khi thêm tài khoản ChatGPT vào pool, mỗi danh tính (email + accountId) chỉ được xuất hiện đúng 1 lần. Bản ghi trùng lặp sẽ kích hoạt chốt chặn an toàn `The ChatGPT account identity is registered more than once`, làm kẹt hàng đợi và timeout. Sửa bằng cách dọn sạch ID trùng trong `chatgpt-account-pool.json`.
