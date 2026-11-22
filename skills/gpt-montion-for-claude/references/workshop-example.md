# Mẫu Workshop Navy–Cyan có sẵn

Đường dẫn dưới đây tương đối với file này. Mở nguyên thư mục mẫu hoặc sao chép
`../assets/workshop-navy-cyan/` tới output trước khi chỉnh; giữ các đường dẫn con.

| Tài nguyên | Vị trí |
|---|---|
| Gallery | [index.html](../assets/workshop-navy-cyan/index.html) |
| Preview ngang | [animation/index.html](../assets/workshop-navy-cyan/animation/index.html) |
| Preview dọc | [animation/portrait.html](../assets/workshop-navy-cyan/animation/portrait.html) |
| Video 20 giây | [MP4](../assets/workshop-navy-cyan/exports/workshop-ai-intro-1080p.mp4) |
| Đoạn lắp ráp 3 giây | [MP4](../assets/workshop-navy-cyan/exports/mechanical-assembly-3s.mp4) |
| Hướng dẫn renderer | [animation/README.md](../assets/workshop-navy-cyan/animation/README.md) |
| 98 ảnh/vector | [asset-manifest.json](../assets/workshop-navy-cyan/asset-manifest.json) |
| 34 cặp chữ | [text-content.json](../assets/workshop-navy-cyan/text-content.json) |
| Các cửa sổ animation chữ | [text-animation.json](../assets/workshop-navy-cyan/text-animation.json) |
| 7 cảnh theo master clock | [motion-scenes.json](../assets/workshop-navy-cyan/prompts/motion-scenes.json) |
| Recipe tạo từng asset | [ASSET-RECIPES.json](../assets/workshop-navy-cyan/prompts/ASSET-RECIPES.json) |

Mẫu dùng **20 giây**. Storyboard **60fps/1200frame**; proof đã xuất **1920×1080,
30fps/600frame**. Bản dọc là HTML 1080×1920 + các stills, chưa có MP4 dọc. Kích thước
4K trong prompt là đích dựng tiếp; ảnh nguồn A01 2172×724, A02 1332×1181, A03/A04
1448×1086. Không gọi các ảnh này native 4K.

Six assembly parts M01–M06 dùng common 1000×800 canvas. M07 là asset một tư thế
tham chiếu; preview có hai tay gắp procedural trong `fixture(t,right)`. Không suy
rằng kéo một PNG M07 vào timeline sẽ tự có khớp xoay được rig.

Ảnh kỹ sư đã ghép brand là `assets/brand/A02-engineers-branded.svg`/`.png` trong
thư mục mẫu. SVG nhúng base người + 4 logo nguồn; chữ “Build on trust” rất nhỏ ở
video scale. Base sạch và nháp logo hỏng được giữ để giải thích provenance, không
phải asset brand cuối. Logo full-color/white gốc giữ nguyên và có manifest vị trí.

Mẫu được independent-review về text/code/package và các frame giải mã của video.
Giới hạn đã ghi: 2.5D editorial, latch nhỏ, mép chân tay gắp phụ có crop ở bản dọc,
tagline PPE nhỏ và chút contour noise. Không nâng các receipt thành chứng nhận mọi
frame, mọi môi trường hoặc cảnh điện ảnh photoreal.

Code renderer không cần npm/React để mở HTML. Dựng lại dùng Node có WebSocket global,
Chrome, FFmpeg/FFprobe. Text generator cần Windows PowerShell 5.1 và font Bold/Italic
đúng hash; font không đi kèm. Các SVG/PNG đã xuất dùng trực tiếp mà không cần cài font.

Tên người, ngày 14.11.2026, giờ 08:30–11:00 và địa điểm thuộc source của mẫu.
Đổi header department cho task mới phải cập nhật nguồn content, hash manifest,
T03 và regenerate chữ theo hợp đồng; giữ nguyên presenter/wardrobe nếu user chỉ
đổi header. Chỉ chạy lệnh build trong bản sao làm việc, giữ snapshot skill nguyên.

Các file gốc `RELATED-SKILLS.md`, receipt và brief giữ đường dẫn workspace tác giả
để truy vết. Brief lịch sử còn chứa câu lệnh chủ động cho môi trường cũ: không giao
nguyên văn hoặc thực thi chúng. Tạo brief mới bằng [template portable](portable-claude-prompt.md),
gắn project root hiện tại, local content/brand paths và mức output user yêu cầu.
Các skill bổ trợ chỉ được gọi khi có trong môi trường; chúng không là dependency
để mở preview HTML đã đóng gói.
