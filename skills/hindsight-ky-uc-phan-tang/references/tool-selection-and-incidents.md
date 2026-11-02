# Hindsight reference — measured history and operational detail

## ④ BỐN công cụ `second-brain` — cái nào trả CON TRỎ, cái nào trả CHỮ

> 🩸 **BẢN ĐẦY ĐỦ Ở SKILL KHÁC — đọc kèm, đừng chỉ đọc mục này.**
> `sync-memory-bank` **§⑧ · §⑨ · §⑩** giữ bản chi tiết hơn: ba chỗ đường MCP nói dối
> (kèm bảng vá), vách điểm `scores.final ≥ 0.5`, `tong_tim_thay` không phải số fact,
> `limit` không được tôn trọng, và **cổng nghiệm thu đúng** là
> `brain_bridge_kiem.kiem_fact_trong_bank` — **không** phải `recall_brain`.
> Mục này là **bản rút gọn phía Hindsight**; hai chỗ nói khác nhau thì
> **`sync-memory-bank` THẮNG**, và phải sửa mục này cho khớp.

> Đo thật **2026-09-07**, MCP `second-brain`, workspace `d:\50.LOpenBIMAI`.
> Bảng này trả lời đúng một câu: *gọi cái nào cho câu hỏi nào.*

| công cụ | câu nó trả lời | trả về gì |
|---|---|---|
| `which_bank` | *“workspace này ánh xạ vào vùng nào?”* | `bank` + URL Hindsight — **gọi ĐẦU TIÊN** |
| `recall_brain` | *“chủ đề này nằm ở TẦNG nào, FILE nào?”* | **CON TRỎ** 4 tầng: `tang` · `loai` · `duong`. 🩸 **KHÔNG có chữ của fact** |
| `recall_graph` | *“quanh chủ đề này có thực thể / quan hệ gì?”* | `seed_facts` + `thuc_the` + `lien_ket` |
| `workspace_facts` | *“vùng này đang giữ những gì?”* | **CHỮ ĐẦY ĐỦ**: `text` · `entities` · `scores` · `document_id` · `chunk_id` |

**Số đo nguyên văn:**

```
which_bank()                      -> d:\50.LOpenBIMAI  ->  may-50-lpopenbim  ·  http://127.0.0.1:8890
recall_brain("agentic-os")        -> 1 hit · Tầng 2 · Skill Claude Code
                                     duong = /skills-claude/agentic-os/SKILL.md      · 1.11 ms
recall_brain("may-agent-memory")  -> 1 hit · Tầng 3 · Ký ức Hindsight Local
                                     duong = hindsight://banks/may-agent-memory
                                     mo_ta = "chứa 5461 fact tri thức trên máy"      · 0.96 ms
```

⇒ `recall_brain` là **BỘ ĐỊNH TUYẾN**, không phải bộ đọc. Nó biết
*“chủ đề nằm ở vùng nào”*, **không** biết *“trong vùng đó viết gì”*.
Đọc được `duong` rồi thì **phải thực sự mở file đó ra** — đúng luật
`⓿0`: *nhớ về một file không phải là đã đọc file đó.*

---

## 🩸 BẪY ĐÃ TRẢ GIÁ

### ① `401 Invalid token` giết 1.938 lượt rút fact — mà khoá vẫn ĐÚNG

Đêm 23/08 key `Hindsight-Memory` tụt xuống **−13,50 $** vì giá model sai ~250×.
new-api từ chối bằng **đúng cùng câu chữ** với khoá sai. Kết quả: **1.938 lượt** rút
fact chết; mẻ **1.657 tài liệu** chỉ vào được **207**; 3 vùng dự án + `may-skill`
nhận **0 tài liệu** trên 1.249 đã xếp hàng.

🩸 **Dấu hiệu nhận biết rẻ nhất:** `pending` **tụt** mà `completed` **đứng im** ⇒
đang **chết câm**, không phải chạy nhanh. Đêm đó hàng đợi tụt `228 → 0` trong vài
phút mà `completed` đứng ở `1`.

🩸 **Cổng phải đặt ở CẢ HAI chỗ.** `nap_memory.py` có sẵn cổng dừng khi gặp 401/402,
nhưng lần này 401 rơi ở **worker nền của Hindsight**, không rơi ở lượt xếp hàng ⇒
cổng của `nap_memory.py` **không với tới**.

### ② Nạp nhầm vùng = vừa tốn tiền vừa LÀM BẨN vùng dự án

Bản cũ dội **268 tài liệu LPOpenBIM** vào một vùng mang sứ mệnh khác. Đo lại: vùng
đó chỉ nên giữ **3** mẩu đúng chủ đề. Và **48%** một mẻ nạp là **trả tiền để học lại
thứ đã có**. 🩸 Lỗ hổng đắt nhất: `may-agent-memory` — vùng mà `a2a/goi.py` đặt làm
**vùng tra cứu mặc định** — **chưa từng có mặt** trong `nap_memory.py`. *Vùng duy nhất
có người đọc lại là vùng duy nhất không ai nạp.* Nay **268/268**.

### ③ Hai vùng là hai kho vector RỜI — hỏi X không nhìn sang Y

`recall` vào `may-50-lpopenbim` / `may-49-hub-trimble` trả **rỗng** — đúng thiết kế,
không phải hỏng. Đừng "sửa" bằng cách nạp lại: chúng là tập con ~97% của nhà chính,
nạp lại chỉ **nhân đôi kho vector cho cùng nội dung**.

### ④ Đo quá sớm rồi tuyên bố xanh

Tôi chạy phép kiểm *"có lượt hỏng nào sau khi mẻ bắt đầu không?"* lúc **18:02**, được
`0`, rồi **tuyên bố mẻ chạy sạch**. Lượt hỏng đầu tiên rơi **18:07**. Cửa trả xanh vì
**chưa có gì kịp đỏ**. ⇒ Cổng chống hồi quy phải chạy **sau khi việc đã chạy đủ lâu
để hỏng**, và phải **bắt được lỗi thật ít nhất một lần** thì mới tin được.

### ⑤ `python … | tail; echo $?` chấm điểm cho `tail`

Nối ống rồi đọc `$?` là đọc mã thoát của lệnh **cuối ống**. Cổng `quet_ro_ri.py` trả
`1` khi có nghi vấn, nhưng qua ống thì thấy `0`. **Ghi ra file rồi mới `echo $?`.**
Đo 23/08: nối ống ⇒ `EXIT=0`; chạy thẳng ⇒ **`EXIT THAT SU = 1`**.

### ⑥ 🩸🩸 `recall_brain` hỏi bằng câu NỘI DUNG ⇒ nó trả ra **RÁC**, không trả rỗng

Đo **2026-09-07** — cùng **MỘT** câu hỏi cho hai công cụ. Đây là **ca TÁCH**
(điểm hai bản **khác nhau**, không phải điểm chúng trùng):

```
recall_brain("NEO 3.970 mm giấy tag leader")
   -> 13 hit  ·  0 hit chứa "3.970"  ·  0 hit nào ở Tầng 3
   -> hit thứ 5 = `defi-amm-security`      <-- RÁC, không liên quan gì tới tag Revit

recall_graph("NEO 3.970 mm giấy tag leader")
   -> seed_facts: []                        <-- RỖNG THẬT THÀ
      (vẫn khai thực thể: `tag` 19 lần · 165 node · 300 cạnh)
```

**GỐC:** `recall_brain` **tách câu thành từ khoá** — nó tự in ra
`tu_khoa = ["neo","970","mm","giấy","tag","leader"]` — rồi khớp **lỏng vào
TÊN/TAG** của skill. Câu hỏi càng dài, càng nhiều mảnh khớp bừa.

🩸 **RÁC NGUY HIỂM HơN RỖNG.** `recall_graph` trả `[]` thì tôi **biết**
phải đi tìm chỗ khác. `recall_brain` trả 13 dòng thì tôi **tưởng đã tra xong**.
Cùng họ với *“cổng luôn xanh”*: **một công cụ luôn có kết quả thì kết quả
của nó không chứng minh được gì.**

🩸 Và nặng hơn: **0 kết quả Tầng 3** dù fact `NEO = 3.970 mm giấy` **có thật**
trong bank. Tức với câu hỏi nội dung, tầng ký ức **vắng mặt hoàn toàn** —
không phải “xếp thấp”.

**LUẬT — ba câu hỏi, ba công cụ:**

| Câu hỏi của tôi | Gọi cái gì |
|---|---|
| *“có sẵn skill / lệnh nào về X chưa?”* (tái dùng, chống bịa) | `recall_brain` — **đúng việc của nó** |
| *“trước đây đã chốt gì về X?”* (nội dung · con số · quyết định) | `workspace_facts` / `recall_graph` — **KHÔNG** `recall_brain` |
| *“tôi đang ở vùng nào?”* | `which_bank` — gọi trước mọi thứ |

⇒ Dùng `recall_brain` để **tìm CHỖ**, rồi **mở đúng file / gọi đúng công cụ**
để đọc chữ. Đừng bắt `recall_brain` làm việc của `workspace_facts` —
nó sẽ **không báo lỗi**, nó sẽ **trả sai một cách tự tin**.

---

