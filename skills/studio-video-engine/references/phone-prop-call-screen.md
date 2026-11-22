# Đạo cụ điện thoại: màn hình cuộc gọi đến có TÊN người gọi (user 16/11/2026)

Dùng khi cảnh cần thấy rõ chữ trên màn hình điện thoại (tên người gọi, tin nhắn…). **Model video (WAN/H3) và model ảnh KHÔNG viết đúng chữ tiếng Việt** ⇒ chữ luôn dựng bằng font thật rồi GHÉP vào ảnh/clip; không bao giờ để model vẽ chữ.

Bản chạy được: Cảnh 3 NEWTECONS `docs/media-stage/S03-CALL-SPLIT-V001/` (`prop/`, `video/SH1B_*`, `video/SH1C_*`, TRACKING.md).
Script: `../scripts/phone_prop/` (bản sao từ cảnh 3; tên file đầu vào đang cố định — sửa hằng số đầu file).

## Luật user
1. **Màn hình = CLONE 100% ảnh mẫu user gửi, chỉ đổi tên/số.** («kiểm tra phải clone ảnh 100% đổi tên thôi»). Không tự vẽ giao diện khác. Ảnh mẫu iOS tiếng Việt: `scripts/phone_prop/REF_IOS_INCOMING_CALL_VI.png` (VN Mobifone 13:55, «Nhắc tôi», «Tin nhắn», «trượt để trả lời»).
2. Tên người gọi theo user, vd **«NEW - Anh Nam GĐDA»** (NEW = danh bạ NEWTECONS). Không giữ số điện thoại của ảnh mẫu.
3. Trình tự cảnh gọi: chuông iPhone reo (SFX) → máy áp sát màn hình hiện tên → cầm máy, **trượt để trả lời** → áp tai «A lô» → chia đôi màn hình đối thoại.

## Quy trình (đã đo, cảnh 3)
| Bước | Cách | Công cụ |
|---|---|---|
| ① Màn hình | inpaint xoá số (mask nét trắng ở dải 60–140 px), viết tên Segoe UI Light trắng, cỡ = 1,38 × chiều cao chữ số gốc, chừa lề ≥ 35 px mỗi bên | `clone_call_screen.py` |
| ② Ảnh điện thoại trên bàn | Codex image, neo ảnh shot trước làm `set`; màn hình để trống hoặc UI bất kỳ (sẽ phủ kín) | jjv images |
| ③ Ghép lên bàn | warp phối cảnh 4 góc (đo tay trên ảnh), bo góc r=40, **KHÔNG trộn lại ảnh màn hình cũ** (lộ nút đỏ/xanh cũ) — chỉ thêm vệt sáng kính chéo | `composite_screen.py` |
| ④ Clip 1B | ffmpeg `zoompan` đẩy vào 1,00→1,09 + rung (jitter 3 px, nửa chu kỳ mỗi 12 khung) + tiếng chuông cắt từ clip WAN chuông | ffmpeg |
| ⑤ Ảnh tay cầm máy | Codex image: màn hình **phẳng xanh #00FF00** (phông xanh) ⇒ tự tìm 4 góc (inRange HSV 40–85 → convexHull → minAreaRect) và **ngón tay đè lên màn hình tự nhiên** (alpha = vùng xanh) | jjv images |
| ⑥ Clip 1C trượt để trả lời | mỗi khung: tách nút trắng, inpaint nền + chữ «trượt để trả lời», nút chạy trái→phải (ease 0,7–1,15 s), chữ mờ dần; warp vào quad; chuông tắt lúc trượt xong | `green_phone_slide.py` + ffmpeg |

## Bẫy đã gặp
- Warp `INTER_LANCZOS4` ra giá trị <0/>255 → ép `uint8` bị **tràn ⇒ viền đỏ/tím quanh chữ**. Luôn `np.clip` trước khi ghi.
- Inpaint chỉ lỗ nút trượt thì chữ «trượt để trả lời» còn lại khi nút đã chạy → phải inpaint cả nét chữ (mask nét tối trên nền thanh sáng).
- Lớp "phản chiếu kính" lấy từ ảnh gốc mang theo giao diện cũ → bỏ, dùng vệt sáng tổng hợp.
- Chia đôi màn hình: crop rộng phải chẵn (638+4+638=1280) nếu không concat báo lệch kích thước.
