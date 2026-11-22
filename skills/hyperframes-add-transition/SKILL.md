---
name: hyperframes-add-transition
description: Chọn và chèn chuyển cảnh giữa hai clip trong HyperFrames (app desktop có nút "Add a transition", web Studio không có), dùng thư viện lp-* của người dùng, luật chọn theo bối cảnh và tối đa 2 lần mỗi hiệu ứng.
---

# Chèn chuyển cảnh trong HyperFrames

## Chọn chuyển cảnh trước (luật của người dùng)
| Giữa hai shot | Chọn | Tránh |
|---|---|---|
| Cùng nhân vật, cùng bối cảnh, máy liền (ảnh cuối = ảnh đầu) | không hiệu ứng, nối liền | mọi loé sáng (che mất nhân vật bay tới) |
| Cùng bối cảnh, đổi góc | cắt thẳng + đẩy nhẹ ~4 % | loé trắng |
| Cùng mạch bay, đổi địa điểm | shot nối tốc độ cao (xuyên mây, xuyên nước, lia nhanh) | cắt cứng |
| Đổi hẳn bối cảnh / chủ đề | chuyển cảnh đồ hoạ: `lp-cua-chop`, `lp-cu-dap`, Cross Warp Morph, Beat Freeze Cut… | hoà tan khi vật thể lệch vị trí (hai bản chồng nhau) |
| Vào phần kỹ thuật (mặt cắt, mặt bằng) | Code Slice Hero, `lp-nen-hud`, nét wire | lửa, nước |

**Một hiệu ứng tối đa 2 lần mỗi phim.** Trước khi chèn, đếm cột `chuyen_canh` / `hieu_ung` trong SHOT_LIST (hoặc chạy `tao_du_an_phim.py kiem`); lần thứ 3 đổi sang hiệu ứng khác cùng ý nghĩa.

## Cách chèn
1. **App HyperFrames (desktop):** rê chuột vào chỗ nối hai clip trên timeline → nút xanh **Add a transition** → chọn trong danh sách (52 khối của HeyGen). Agent trong app (Claude Code theo gói Claude của người dùng) cũng làm được bằng lời.
2. **Web Studio (`hyperframes preview`)**: không có nút này (đã kiểm 0.9.51 và 0.9.65); dùng tab **Catalog → Transitions** rồi kéo vào track và chỉnh giờ, hoặc nhờ agent sửa `index.html`.
3. **Hiệu ứng `lp-*` của người dùng** (trang xem `http://127.0.0.1:4401`, nguồn `D:\61.SetupAgent\revit-live-demo-20261110\INTRO-HYPERFRAMES_v8f_20261115\thu-vien-hieu-ung\compositions\lp-*.html`):
   - Chép vào project: `python -I -X utf8 tools/chep_hieu_ung.py "<project>"` (không `--ca-kho` để danh sách Compositions không rối), hoặc
   - Đóng gói registry: `python make_lp_registry.py <compositions> <thư mục registry>` → `registry.json` + `blocks/<tên>/registry-item.json` (tag `transition` cho khối có chữ "chuyển cảnh" trong chú thích). Trỏ `"registry"` trong `hyperframes.json` tới đó để thử hiện trong nút Add a transition — **chưa kiểm app nhận registry trên máy**; thử 1 khối trước, ghi kết quả vào `README_TRANSITION.md`; đổi registry có thể ẩn 52 khối HeyGen.
   - Chèn tay (luôn chạy được): `<div data-composition-id="lp-cua-chop" data-composition-src="compositions/lp-cua-chop.html" data-start="<điểm cắt − 0,2>" data-duration="0.6" data-track-index="<track riêng>" data-width="<khổ phim>" data-height="<khổ phim>" data-variable-values='{"mau":"vang"}'></div>` — `lp-cua-chop` cắt cảnh ở giây 0,2 của khối; hiệu ứng `lp-*` dựng cho 1920×1080, phim 1280×720 phải đặt đúng `data-width/height`.
4. Tiếng của chuyển cảnh lấy từ thư mục SFX của phim, đặt trên track SFX, cũng tối đa 2 lần cho một tệp.

## Kiểm
Render đoạn ±1 s quanh mỗi chỗ nối, xem khung: không hai bản nhân vật/vật thể chồng nhau, không khung trắng lạc, cú chính của hiệu ứng trùng điểm cắt; cập nhật SHOT_LIST và bảng kiểm hiệu ứng.
