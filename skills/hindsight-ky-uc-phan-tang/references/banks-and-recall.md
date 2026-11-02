# Hindsight reference — measured history and operational detail

## ① Bản đồ vùng — LOCAL, đo `2026-08-23`

`GET http://127.0.0.1:8890/v1/default/banks` ⇒ **8 vùng**:

| Vùng | Vai |
|---|---|
| `long-tong` | 🛰 **ĐÀI KIỂM SOÁT** — chỉ giữ bản đồ hệ thống, **TỔNG CHỈ TRỎ, KHÔNG ÔM** |
| `may-agent-memory` | 📚 **NHÀ CHÍNH** — vault Agent-Memory, 268 tệp · 3.521 fact |
| `may-handover` | 📋 tài liệu bàn giao phiên |
| `may-skill` | 🧩 các `SKILL.md` |
| `may-50-lpopenbim` | 💼 workspace — **để trống có chủ ý** (tập con ~97% của nhà chính) |
| `may-49-hub-trimble` | 💼 workspace — **để trống có chủ ý** |
| `may-59-de01-btl` | 💼 workspace — giữ đúng 3 mẩu đúng chủ đề |
| `long-ca-nhan` | 👤 vùng cá nhân của Long |

⚠ Cờ đỏ *"vùng đốt việc mà giữ 0 fact"* của `kiem_hoc.py` với `may-50` / `may-49`
là **ĐÚNG THIẾT KẾ**, không phải lỗi — hai vùng ấy cố ý trống, tra cứu về nhà chính.

**VPS — 11 vùng** (đếm 23/08, `192.168.26.10:8888`): 1 vùng chung của Khối · 6 vùng
dự án · 3 vùng cá nhân · 1 vùng **RIÊNG TƯ**. 🩸 **Tên và nội dung của chúng KHÔNG
được chép vào bất cứ file nào dưới máy này.**

**Ba nguyên tắc phân tầng:**
1. **TỔNG chỉ trỏ, không ôm** — `long-tong` giữ bản đồ, hỏi sâu thì chỉ sang vùng con.
2. **Tách theo CHỦ SỞ HỮU** — chung · dự án · người · workspace máy.
3. **`document_id` = đường dẫn vault** ⇒ từ mỗi fact mở ngược đúng note gốc.

---

## ② Hai bước, hai giá tiền — NHỚ LẠI thì MIỄN PHÍ

| Bước | Cần gì | Giá |
|---|---|---|
| **retain** (ghi vào) | **LLM rút fact** + embeddings | tốn lượt LLM |
| **recall** (nhớ lại) | **chỉ embeddings** (tìm bằng vector) | **0 lượt gọi LLM** |

Cấu hình đo được trong thùng `sa-memory-hindsight-local`:

```
HINDSIGHT_API_EMBEDDINGS_PROVIDER = local
HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU = true
HINDSIGHT_API_LLM_MODEL   = ag/gemini-3.8-flash-low   # 05/09 (trước 3.7)
HINDSIGHT_API_LLM_BASE_URL = http://token-newapi:3000/v1
```

**Phép đo chứng minh recall không tốn LLM** (chạy thật 23/08) — đếm sổ `logs` của
new-api trước và sau một lượt recall:

```
log new-api TRUOC = 6687
recall 7391 ms · 32 manh · keys=['results', 'entities']
log new-api SAU   = 6687   => chenh 0
```

⇒ **Recall tốn 0 lượt gọi LLM.** Embeddings chạy **local, miễn phí**; chỉ bước
**RÚT FACT** mới cần LLM có tiền. Đây là lý do một vùng có thể *tra cứu thoải mái*
kể cả khi khoá LLM đang âm.

Đường gọi (đúng đường, đã đo):

```bash
# nhớ lại
curl -s -X POST -H 'content-type: application/json' \
  -d '{"query":"<câu hỏi>","limit":5}' \
  http://127.0.0.1:8890/v1/default/banks/<vùng>/memories/recall

# ghi vào
curl -s -X POST -H 'content-type: application/json' -d '{…}' \
  http://127.0.0.1:8890/v1/default/banks/<vùng>/memories
```

🩸 Thiếu đoạn `/memories/` là **`404 Not Found`** — tôi đã gõ nhầm
`…/banks/<vùng>/recall` và ăn đúng 404 trong lượt đo đầu tiên.

---

