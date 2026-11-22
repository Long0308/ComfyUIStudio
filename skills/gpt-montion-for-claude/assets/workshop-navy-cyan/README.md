# Workshop AI — Navy–Cyan · bộ ảnh và intro lắp ráp

Toàn bộ tài nguyên của lượt làm này nằm trong thư mục này. Mở **[index.html](index.html)** để xem bộ ảnh, các lớp chữ và video. Hai bản xem chuyển động có Play, Pause, Restart và thanh tua riêng:

- [Bản ngang 16:9](animation/index.html).
- [Bản dọc 9:16](animation/portrait.html).
- [Video MP4 ngang](exports/workshop-ai-intro-1080p.mp4), bản xem thử 20 giây, 1920 × 1080, 30 fps. Thông số đo cuối nằm trong `evidence/`.
- [Prompt chính cho Claude](prompts/CLAUDE-MOTION-INTRO.md), [prompt từng cảnh](prompts/SHOT-PROMPTS.md), [storyboard theo frame](prompts/motion-scenes.json).

## Ý tưởng chuyển động

Lấy nhịp lắp giáp Iron Man làm ý tưởng: bộ phận đến đúng trục, căn chỉnh, kẹp giữ, khóa và kích hoạt. Ứng dụng vào bộ MEP của công trường. Giữ phong cách Navy–Cyan của ảnh/canvas đã chọn; giữ mặt, tay và tablet của kỹ sư là ảnh tĩnh, cho các lớp kỹ thuật chuyển động độc lập.

| Giây | Nội dung |
|---|---|
| 0–2 | Hero và WORKSHOP AI đọc được từ frame đầu |
| 2–5 | Kỹ sư và ứng dụng AI thực tế ở công trường |
| 5–8 | Các cụm MEP vào vị trí, căn chỉnh và khóa |
| 8–11 | Dashboard — THÔNG TIN TRONG TẦM TAY |
| 11–13 | Kết nối AI × BIM |
| 13–16 | ỨNG DỤNG AI CÓ TRÁCH NHIỆM |
| 16–20 | Tên workshop, ngày 14.11.2026, 12A NEWTECONS, 08:30 – 11:00 |

Storyboard dùng **60 fps / 1200 frame**. Player và bản MP4 xem thử dùng **30 fps / 600 frame**: cùng thời điểm có `masterFrame = proofFrame × 2`. Bản 4K/60 fps là đích dựng tiếp trong prompt, chưa phải video đã xuất ở lượt này. Video hiện chưa có nhạc hoặc âm thanh.

## Tài nguyên đã tách

| Thư mục | Cách dùng |
|---|---|
| `assets/generated/` | Nền công trường, base kỹ sư, mô hình BIM minh họa, dashboard, ribbon và đường mạng |
| `assets/brand/` | Logo gốc, compound kỹ sư có logo SVG/PNG và JSON vị trí từng logo |
| `assets/mechanical/` | Các cụm cơ khí SVG + PNG cùng hệ tọa độ; chồng đúng gốc, không tự crop mỗi part |
| `assets/text/` | **34 cặp SVG + PNG**, có chữ chính, dòng trình bày, tên dự án và nội dung agenda mở rộng |
| `references/` | Canvas và hai poster gốc, nội dung chương trình, nguồn AI × BIM đã chép nguyên tệp |
| `prompts/` | Prompt ảnh, prompt chuyển động, storyboard và hướng dẫn Claude |
| `animation/` | Mã thực thi preview, dựng part và xuất video; không cần React hoặc cài npm để mở HTML |
| `evidence/` | Đo kích thước/alpha/hash, kiểm tra timeline, typography và review độc lập |

Danh sách máy đọc: [asset-manifest.json](asset-manifest.json). Chữ chuẩn: [text-content.json](text-content.json). Chuyển động chữ: [text-animation.json](text-animation.json).

**Phần chữ cũng là tài nguyên animation.** Các SVG đã chuyển outline bằng font thật, một nhóm nguyên câu `*_RUN_01`, giữ dấu tiếng Việt. Chữ chính in đậm; dòng trình bày dùng Italic thường, cỡ nhỏ hơn. Có thể mask/reveal/translate từng câu. Không tách dấu khỏi chữ hoặc giả rằng các outline này đã có nhóm từng ký tự. Những dòng agenda bổ sung để Claude dựng phần nối tiếp; không nhồi cả chương trình vào intro 20 giây.

## Logo và độ nét

- Logo công ty là artwork cố định. `KHỐI CƠ ĐIỆN` là lớp riêng để sau này thay tên khối; không đổi theo nó các tên phòng ban của người trình bày.
- Dùng `assets/brand/A02-engineers-branded.svg` hoặc PNG tương ứng trong cảnh chính. `A02-engineers-tablet.png` là base sạch. Nháp trong `evidence/A02-draft-branding-unverified.png` đã bị loại vì chữ nhỏ trên nón.
- Compound SVG nhúng ảnh người và logo gốc nguyên byte. Nó không biến ảnh raster thành vector. Tọa độ, góc xoay và hash nguồn được lưu trong `brand-placement.json`.
- Dòng đúng là **Build on trust**. Artwork nguồn giữ N, NEWTECONS, ký hiệu đăng ký, đường kẻ và tagline. Ở cỡ nón/áo trong video, tagline rất nhỏ: giữ đúng nguồn không có nghĩa đọc rõ từng chữ ở kích thước đó.
- A01: **2172 × 724**; A02: **1332 × 1181**; A03/A04: **1448 × 1086**. Đây là ảnh tái dựng theo mẫu, không phải tách pixel tuyệt đối và không phải nguồn native 4K. SVG chữ và các part vector có thể render lại theo khổ đích.
- Bộ MEP chuyển động là minh họa editorial 2.5D, giúp đọc rõ cơ chế lắp ráp. Muốn cảnh máy móc photoreal cần hình học/vật liệu/render mới. Không xoay PNG để giả đó là mô hình 3D.

## Kiểm tra đã có

Đọc [audit chữ độc lập](evidence/independent-text-audit.md), [kiểm tra lịch cha/con](evidence/agenda-verification.json), [báo cáo hình ảnh và chuyển động](evidence/INDEPENDENT-REVIEW.md) và receipt render trong `evidence/`. Báo cáo phân biệt kiểm tra source, kiểm tra pixel, chữ đọc được và độ trung thực của logo.

Chuỗi **tầm** dùng `U+0074 U+1EA7 U+006D`; chữ **ầ** là â có dấu huyền. Lịch nguồn có 150 phút, các mục cha nối tiếp; các mục con có giờ của phần mở đầu/phần 1 nằm đúng trong cha. Phần 2 không có giờ riêng cho từng ý trong nguồn nên không tự thêm.

Thư mục tham khảo AI × BIM được người dùng gửi có ba ảnh nội dung, hai logo, ba bản ảnh trùng và một prompt 18 giây. Trong thư mục đó chưa có code dự án hoặc video. Sáu tệp có tên đã chép vào `references/ai-bim-source/`; xem [báo cáo nguồn](references/REFERENCE-STATUS.md).

## Dựng lại và giao cho Claude

Mở nguyên thư mục bằng Claude, đưa `prompts/CLAUDE-MOTION-INTRO.md` cùng yêu cầu cần chỉnh. Giữ manifest và assets bên cạnh nhau. Dùng `animation/README.md` để chạy renderer. Kéo part PNG/SVG và chữ vào Remotion/After Effects nếu cần; giữ common canvas của part để tránh lệch lắp ráp.

Tái tạo chữ cần Windows PowerShell 5.1 và hai file Roboto Condensed Bold/Italic đúng hash đã lưu trong `evidence/text-assets-verification.json`. Font không được đóng gói ở đây. SVG/PNG đã xuất không cần cài font để dùng. Chạy từ thư mục gói:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/render-text.ps1
node scripts/build-brand.cjs
node animation/build-content.cjs
node animation/render.cjs assets
node animation/render.cjs video
node scripts/build-index.cjs
```

Các skill liên quan đã được nối với workflow này trong [RELATED-SKILLS.md](RELATED-SKILLS.md). Bản ZIP bàn giao giữ assets, prompt, code, references và bằng chứng; chuỗi 600 PNG trung gian và profile Chrome tạm không cần gửi kèm. Các tệp poster nguồn được giữ để đối chiếu, không được coi là đã sửa lại logo trong lượt intro này.
