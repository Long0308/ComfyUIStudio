# Thư viện hiệu ứng LP — lấy hiệu ứng cho phim JennieJoy

Thư viện hiệu ứng HyperFrames dựng từ phim intro Workshop AI V8f. Nó nằm ở kho **61.SetupAgent**, không nằm trong repo JennieJoy. Skill gốc của nó là `hyperframes-hieu-ung-lp`, đã cài cấp user cho mọi IDE; đọc skill đó trước khi viết hiệu ứng `lp-*` mới. Trang này chỉ ghi cách JennieJoy lấy hiệu ứng ra dùng.

## Ở đâu

| Thứ | Máy nhà | Máy công ty |
|---|---|---|
| Thư mục phim + thư viện | `L:\61.SetupAgent\revit-live-demo-20261110\INTRO-HYPERFRAMES_v8f_20261115` | `D:\61.SetupAgent\…` cùng đường dẫn |
| Hiệu ứng `lp-*` (14 cái) | `…\thu-vien-hieu-ung\compositions\lp-*.html` | như bên trái |
| Trang xem toàn bộ (711 thẻ có video) | http://127.0.0.1:4401/ | như bên trái |

Mở trang: `powershell -ExecutionPolicy Bypass -File mo-thu-vien.ps1` trong thư mục phim (tắt: thêm `-Dung`). Cần Node 22+, Python 3.11+, ffmpeg. Trước đó `git pull --ff-only origin main` trong `61.SetupAgent`. Mở bằng Chrome/Edge, không mở trong VS Code. 396 video xem trước nằm trên GitHub Releases, nên cần mạng; 315 video còn lại ở trong máy.

Đo ở máy nhà 15/11/2026, commit `eda63eae`: 711/711 thẻ có video, phát thử 60/60 video trong máy + 396/396 video GitHub đều chạy.

## 14 hiệu ứng `lp-*`

`lp-bi-rap-chu` (bi ráp chữ) · `lp-bien-neon` · `lp-chu-dap` (chữ đập) · `lp-cu-dap` (cú đập sóng xung kích) · `lp-cua-chop` (cửa chớp) · `lp-den-roi` (đèn rọi) · `lp-ken-burns` · `lp-khung-phim` · `lp-nen-hud` · `lp-so-dem` (số đếm) · `lp-so-lon` · `lp-the-chip` · `lp-vu-tru` · `lp-zoom-nhip` (zoom theo nhịp).
Ngoài ra có 448 khối kho HyperFrames đã cài sẵn (chép bằng `--ca-kho`).

## Lấy hiệu ứng sang một dự án HyperFrames JennieJoy

```powershell
cd L:\61.SetupAgent\revit-live-demo-20261110\INTRO-HYPERFRAMES_v8f_20261115
python -I -X utf8 tools/chep_hieu_ung.py "<thư mục dự án HyperFrames JennieJoy>"            # 14 lp-* + font + ảnh mẫu
python -I -X utf8 tools/chep_hieu_ung.py "<thư mục dự án HyperFrames JennieJoy>" --ca-kho   # thêm 448 khối kho
```

- Dự án đích phải có `index.html` (dự án HyperFrames), nếu không công cụ báo lỗi và không chép.
- Không ghi đè tệp đã có, trừ `lp-*.html` luôn được cập nhật bản mới. Muốn giữ một hiệu ứng đã sửa riêng cho JennieJoy thì đổi tên nó (ví dụ `jj-…`), đừng sửa thẳng `lp-*.html`.
- Đặt vào timeline:

```html
<div id="x1" style="z-index:3" data-composition-id="lp-cu-dap" data-composition-src="compositions/lp-cu-dap.html"
     data-start="12.0" data-duration="1.2" data-track-index="3" data-track-kind="graphics" data-width="1920" data-height="1080"
     data-variable-values='{"mau":"vang","x":960,"y":470}'></div>
```

## Luật khi dùng cho JennieJoy

1. **Hợp đồng timeline của skill này vẫn thắng**: 30 fps, thẻ từ vựng ≥ 90 f, logo cuối ≥ 60 f, đổi cả thẻ cùng một khung. Hiệu ứng `lp-*` chỉ là lớp hình; tiếng (SFX, nhạc) nằm trong bản mix `jjv audio mix`, không lấy tiếng của phim intro V8f.
2. **Chỉ lấy hiệu ứng, không lấy nội dung phim Workshop.** Không mang chữ, số liệu, logo NEWTECONS/LPOpenBIM, ảnh công trường hay giọng của phim intro V8f vào phim trẻ em. Đổi chữ, màu sang bộ màu JennieJoy (pill hồng `#FF2E7E`, chữ trắng đậm).
3. **Phong cách trẻ em:** ưu tiên hiệu ứng nhẹ (`lp-bi-rap-chu`, `lp-so-dem`, `lp-ken-burns`, `lp-cua-chop`, `lp-zoom-nhip`). Hiệu ứng mạnh (`lp-cu-dap`, `lp-nen-hud`, `lp-vu-tru`, `lp-bien-neon`) phải giảm cường độ, chớp sáng và rung trước khi dùng; không để nháy nhanh liên tục.
4. **Giấy phép:** `lp-*` là mã của dự án; khối kho HyperFrames là Apache-2.0 (vài khối MIT/OFL-1.1). Tránh nguồn ngoài react-bits (Commons Clause), lygia (Prosperity), hydra (AGPL) — danh sách ở `thu-vien-hieu-ung/xem/nguon-ngoai.js`.
5. **Mỗi lần lấy hiệu ứng:** ghi tên hiệu ứng, commit `61.SetupAgent` đang dùng và SHA256 của tệp đã chép vào manifest thành phần, như mọi component HyperFrames khác.
6. Không thấy ổ `L:`/`D:` hoặc thư mục phim ⇒ báo thiếu kho `61.SetupAgent`, không tự viết lại hiệu ứng từ trí nhớ.
