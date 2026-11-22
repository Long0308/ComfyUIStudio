# Màn hình trong cảnh: bản đồ Việt Nam (có Hoàng Sa, Trường Sa) + KPI nháy — ghép màn XANH từng khung

Làm lần đầu ở Cảnh 4 NEWTECONS (16/11/2026, user duyệt). Script: `../scripts/screen_map/`.

## Vì sao không để model ảnh/video vẽ màn hình
- Model ảnh vẽ sai hình chữ S, hay bỏ/đặt lệch **Hoàng Sa, Trường Sa** ⇒ lỗi chủ quyền, không chấp nhận được với phim công ty.
- WAN/H3 vẽ lại chữ và số trên màn hình mỗi khung ⇒ méo; không làm được hiệu ứng nháy có kiểm soát.

## Quy trình
1. Ảnh khung: màn hình TV = **xanh lá phẳng #00FF00**, trọn trong viền, không hắt sáng ra phòng (sửa cục bộ ảnh đã duyệt: TARGET màn hình → CHANGE xanh phẳng → PRESERVE mọi thứ khác).
2. Đất liền: Natural Earth 1:50m admin-0 (public domain, `data/ne_50m_admin_0_countries.geojson`, sha256 3e458fc0…). Hai quần đảo chấm theo toạ độ các đảo thật, **tô cùng màu Việt Nam**, nhãn «QĐ. Hoàng Sa» / «QĐ. Trường Sa» bằng font thật. `render_map.py` bỏ mọi polygon nước khác trong hộp hai quần đảo và in số polygon đã bỏ (đo 16/11: 0).
3. Bố cục theo chỗ người đứng che màn hình: người đứng giữa ⇒ KPI trái, bản đồ phải (`k1`); người ở 1/3 trái khung cận ⇒ KPI giữa-trên, bản đồ phải (`k2`). **Kiểm bằng mắt sau khi ghép: đầu/thân người không được che hai quần đảo** (lần đầu 16/11 thân GĐĐH che mất cả miền Nam lẫn hai quần đảo).
4. Ảnh tĩnh: `python composite_screen.py <shot.png> <out.png> --map <màn.png> [--blur PX]` — khoá nền MỀM + gỡ trộn `F=(I-aK)/(1-a)`; khoá cứng + khử xanh tạo viền xám sáng quanh tóc (đã gặp).
5. Video: Topview WAN/H3 chạy trên khung MÀN XANH (prompt: «the screen shows only a flat uniform bright green picture for the entire clip»), rồi `python video_screen.py <raw.mp4> k1|k2 <out.mp4> [--blur]`: mỗi khung tìm vùng xanh, làm mượt trung vị 9 khung (bám máy đẩy vào), vẽ `render_screen.frame(layout, t)` (đỏ nháy 1,5 Hz), giữ tiếng gốc. Đo 16/11: 0 khung mất xanh; hộp xê dịch ≤14 px (WAN push-in), ≤1 px (H3 khoá máy).
6. Số KPI là số MINH HOẠ (`KPI_*` trong `render_screen.py`) — ghi rõ với user.
