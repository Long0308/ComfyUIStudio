# Hindsight reference — measured history and operational detail

## ③ Cổng chặn rò rỉ — `python hoc/quet_ro_ri.py`

```bash
python hoc/quet_ro_ri.py            # quét file ĐANG THEO DÕI bởi git
python hoc/quet_ro_ri.py --tat-ca   # quét cả file chưa theo dõi
# mã thoát khác 0 khi có nghi vấn
```

**Vì sao cần cổng máy chứ không dựa vào trí nhớ:** `.gitignore` chặn theo **ĐƯỜNG
DẪN**, còn rò rỉ xảy ra theo **NỘI DUNG**. Một đoạn hội thoại dán nhầm vào file
`.md` nằm ngoài mọi đường dẫn bị chặn thì `.gitignore` **không thấy gì cả**.

**Cổng soi 6 dấu hiệu**, mỗi dấu hiệu kèm **lời tố cáo riêng** — vì
🩸 *"con số một mình KHÔNG phải cổng chặn"*: uid buồng riêng · id nhóm/uid dạng
18–20 chữ số · tên nhóm dự án · tên nhóm riêng tư · số điện thoại Việt Nam · tên
vùng riêng tư.

### 🩸 Chỗ khó nhất: HÀNG RÀO khác RÒ RỈ

Câu *"CẤM ĐỤNG vùng «riêng tư»"* là thứ ta **MUỐN** có trong code — nó **chính là
hàng rào**. Cổng ngây thơ sẽ kêu ở mọi hàng rào, và **cổng kêu ở chỗ đúng thì người
ta thôi đọc nó**.

Luật đã cài: tên vùng kín nằm trong **tầm `TAM_CAM = 120` ký tự** quanh một từ thuộc
`TU_CAM` (`CẤM · riêng tư · loại bỏ · không đụng · blocklist · off-limits …`)
⇒ **bỏ qua**. Vẫn tố cáo nếu tên ấy **đứng một mình giữa nội dung** — đó mới là rò
rỉ thật. Thêm một danh sách `MIEN` **ngắn** cho các file *bản chất là luật cấm*
(chính `quet_ro_ri.py`, `README.md`, `hoc/loc.py`, test chứng minh luật loại trừ…).
Danh sách `MIEN` **phải NGẮN và phải xét lại mỗi lần thêm**.

---

