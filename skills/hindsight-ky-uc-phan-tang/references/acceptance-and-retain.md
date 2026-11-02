# Hindsight reference — measured history and operational detail

## ✅ CỔNG NGHIỆM THU

```bash
# 1. Hai kho đều sống, và ĐÚNG SỐ VÙNG
curl -s http://127.0.0.1:8890/v1/default/banks | python -c "import sys,json;print(len(json.load(sys.stdin)))"
#    ĐẠT: 8
curl -s -m 8 http://192.168.26.10:8888/v1/default/banks | python -c "import sys,json;print(len(json.load(sys.stdin)))"
#    ĐẠT: 11   (không với tới ⇒ ghi "không với tới", KHÔNG ghi 0 và KHÔNG ghi "hỏng")

# 2. 🩸 CỔNG RÒ RỈ — chạy TRƯỚC MỖI LẦN PUSH. Đừng nối ống.
python hoc/quet_ro_ri.py > /tmp/rr.txt 2>&1; echo "EXIT = $?"
#    ĐẠT: EXIT = 0  và  file /tmp/rr.txt có dòng "✅ Không thấy dấu hiệu ký ức Zalo nào"

# 3. Recall KHÔNG tốn LLM — đếm sổ new-api trước/sau
#    ĐẠT: total của /api/log/ KHÔNG đổi qua một lượt recall

# 4. Không vùng nào của VPS bị nhắc tên trong repo
python hoc/quet_ro_ri.py --tat-ca > /tmp/rr2.txt 2>&1; echo "EXIT = $?"
#    ĐẠT: EXIT = 0

# 5. 🩸 `recall_brain` VẪN LÀ BỘ ĐỊNH TUYẾN, không phải bộ đọc — ca TÁCH còn tách không
#    MCP: recall_brain("NEO 3.970 mm giấy tag leader")
#    ĐẠT: CÓ hit  NHƯNG  0 hit chứa "3.970"  và  0 hit ở Tầng 3
#         ⇒ chứng minh nó KHÔNG đọc nội dung (đo 07/09: 13 hit, 0 chứa số)
#    🩸 CỔNG TỰ HỦY: nếu một ngày nó CÓ trả nội dung thì luật ⑥ HẾT HIỆU LỰC —
#         phải đo lại và sửa skill, ĐỪNG giữ nguyên câu cũ.
```

🩸 **Trạng thái cổng lúc viết skill này (23/08): ĐỎ** — `quet_ro_ri.py` tố cáo
**1 file** (`kien-truc/index.html.bak-7tang`, một bản sao lưu `.bak-*` có uid dạng
buồng riêng). Đây là **nợ có thật, chưa xử**, không phải cổng kêu oan. Phải dọn
trước lần push kế.

---

## 🩸 LLM CỦA HINDSIGHT — retain hỏng ÂM THẦM (đo 24/08/2026)

Retain (rút fact) gọi LLM. Trên VPS nó cấu hình trong **`dung_hindsight.sh`** (docker run
`-e HINDSIGHT_API_LLM_*`), KHÔNG phải compose. Hai bug đã trả giá, làm **mọi ghi ký ức
(day_nex · học đêm · đồng bộ) hỏng mà cron vẫn `last_status ok`**:

1. **402 Insufficient Balance** — trỏ thẳng `api.deepseek.com` bằng key HẾT TIỀN.
2. **"Provider returned no choices"** — đổi sang modelapi.vn nhưng **thiếu `/v1`**:
   `https://modelapi.vn/chat/completions` trả **HTML TRANG WEB**. Base ĐÚNG =
   **`https://modelapi.vn/v1`**. Kèm bẫy model SUY LUẬN: `deepseek-v4-flash` để `content`
   RỖNG và nhồi `reasoning_content` khi max_tokens nhỏ — nhưng lượt extraction thật của
   Hindsight cấp đủ token nên `retain ok, ~3181 token`.

FIX: sửa base+key trong `dung_hindsight.sh` → `docker rm -f hindsight` →
`bash dung_hindsight.sh <key>` (script đòi key làm **$1**). Đo lại retain phải `ok:True`.

🩸 **Hindsight KHÔNG có fallback LLM native** (không env FALLBACK/RETRY). Đơn tuyến ⇒
mất tiền/đứt tuyến là mất ký ức. Anh Long chốt: **"phải có fallback + BÁO ĐỘNG, mất
memory âm thầm là NGU."**

## ✅ GIẢI (24/08) — LiteLLM PROXY + BÁO ĐỘNG (đã dựng trên VPS)
**LiteLLM proxy** = container nhỏ (`litellm-nex`, `ghcr.io/berriai/litellm`) đứng TRƯỚC LLM,
phơi 1 endpoint OpenAI-compat và TỰ TỤT BẬC khi tuyến chính hỏng. Config
`/home/ubuntu/litellm/config.yaml`: nhiều deployment CÙNG tên `retain` = chuỗi fallback.
```
Hindsight ─► litellm-nex:4000/v1 (docker net `nex-net`) ─► ① modelapi.vn/v1 ($71) → ② openrouter nemotron:free
```
- Hindsight + litellm-nex phải **CÙNG network `nex-net`** ⇒ gọi theo TÊN `http://litellm-nex:4000/v1`.
  KHÔNG dùng 172.17.0.1 (hindsight không tới). Sửa base trong `dung_hindsight.sh` + thêm `--network nex-net`.
- `HINDSIGHT_API_LLM_MODEL=retain` (tên model trong litellm), key bất kỳ (litellm không đặt master_key).
- Đo: retain qua proxy **ok 3054 token**. Thêm tầng Command Code/OpenAI ⇒ thêm deployment `retain`
  vào config (Hermes cấp URL/token sau).
- **BÁO ĐỘNG** khi hỏng HẾT: `ky_uc._bao_su_co_ky_uc(bank,ly_do)` → DM Long (outbox) + webhook Hermes
  (`nex-loi`) + sổ `loi_he_thong`, cooldown 30'/bank. Verified: alert tới Zalo thật của Long.

## Liên quan

- `sync-memory-bank` — 🩸 **§⑧·⑨·⑩ là NGUỒN CHÍNH** về chọn công cụ `second-brain`
  (`recall_brain` vs `recall_graph` vs `workspace_facts`) và về cổng nghiệm thu
  `kiem_fact_trong_bank`. Mục `④`/`⑥` ở trên là bản rút gọn — lệch thì bên đó thắng.
- `ha-tang-61-setupagent` — cổng, thùng, profile compose của cả hai kho.
- `newapi-ngan-hang-quota` — vì sao khoá LLM của Hindsight tụt âm.
- `nex-hermes-zalo` — dashboard :9120 = nex-hermes.service (không phải hermes-gateway).
- `hoc/README.md` · `hoc/KIEM_HOC.md` — sổ đo của lớp `hoc/`.
