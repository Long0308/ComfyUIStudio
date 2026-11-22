# Workshop AI — Signature Navy, nguồn 05.11.2026

Phong cách Signature Navy nền `#081F3D`, chữ trắng, nhấn đỏ, logo trên plaque trắng và ảnh công trường MEP thật về vật liệu. Đây là một trong bốn phong cách Workshop: Blue–White, Editorial, Signature Navy và Navy–Cyan. Hai khổ dưới đây là hai bố cục của cùng một phong cách.

| Ảnh thật trong gói | Kích thước |
|---|---|
| [Poster dọc](final/Option-02-Signature-Navy-9x16-4K.png) | 2160 × 3840 |
| [Poster ngang](final/Option-02-Signature-Navy-16x9-4K.png) | 3840 × 2160 |
| [Hero MEP](assets/option-02-natural-mep.png) | 1998 × 787 |

<p><img src="final/Option-02-Signature-Navy-9x16-4K.png" alt="Signature Navy dọc" width="270"> <img src="final/Option-02-Signature-Navy-16x9-4K.png" alt="Signature Navy ngang" width="650"></p>

![Hero Signature Navy](assets/option-02-natural-mep.png)

[Prompt as Code](prompt-as-code.json) có đủ tám trường, toàn bộ chuỗi chữ được vẽ, hợp đồng bảo toàn và nguyên văn PHOTO PROMPT B từ [ghi chép lịch sử](../../evidence/legacy-options-design-audit-and-prompts.txt). Prompt hướng dẫn dàn trang được viết khi đóng gói; prompt ảnh được chép từ ghi chép 05.11.2026. Chưa xác minh model, seed và đường dẫn/hash của ảnh tham chiếu nhân dạng dùng trong lần sinh cũ. Không suy những dữ liệu đó từ tên file hoặc prompt.

Các hero/final và bằng chứng lịch sử được sao chép nguyên byte từ visualization workspace `01a1a9ae-ce30-7a70-a1a5-ce36d3649cb1`; không sinh ảnh mới và không sửa logo. [OptionsRenderer.cs](../../scripts/OptionsRenderer.cs) giữ nguyên byte nguồn, dùng chung [PosterRenderer.cs](../../scripts/PosterRenderer.cs), [logo](../../assets/newtecons-original-logo.png), [QR](../../assets/original-workshop-qr.jpg) và [lịch](../../content.json).

Từ thư mục gốc Workshop, chạy bằng Windows PowerShell 5.1 với Roboto Condensed Regular/Bold/Italic và Arial:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\render-options.ps1
```

Lệnh chung dựng cả Editorial và Signature Navy vào `output/options/`, kiểm hash bốn PNG trước khi công bố đầu ra. `final/` là mẫu đối chiếu được theo dõi trong Git. Không chạy wrapper trong phiên đã nạp lớp `PosterRenderer`; wrapper yêu cầu tiến trình PowerShell mới và không ghi lên input.

Khổ dọc dùng giờ ở cột phải; khổ ngang chia ba cột cho Mở đầu, Phần 1 và Phần 2/3. Khổ ngang tách `Minigame:` và `Giải mã công trường AI` thành hai dòng; không đổi nội dung hoặc giờ so với [content.json](../../content.json).

Canvas/chữ được dựng trực tiếp ở 4K. Hero nguồn 1998 × 787 được cover-crop ở tỷ lệ **1.009009009× dọc** và **0.700700701× ngang**. **Khổ dọc có phóng lớn hero khoảng 0.9009%** để lấp vùng 2016 × 690; đây là hành vi lịch sử được bảo toàn và đo công khai. Không nhận ảnh này đáp ứng điều kiện hero ≤1× của biến thể Navy–Cyan. DPI 300 là metadata; hero không phải ảnh sinh native 4K.

[Bằng chứng tái tạo 12.11.2026](../../evidence/options-reproduction-2026-11-12.json) phân biệt đo mới với audit cũ. Bốn PNG tái tạo khớp SHA-256 với bản lịch sử; audit mới có tổng 163 record chiều rộng và 163 record biên canvas cho hai phong cách, không có record lỗi. Các số này không chứng minh mọi va chạm, đọc QR hay độ trung thực logo nhỏ. Ghi chép lịch sử có nhận xét logo/QR riêng; lượt đóng gói này không xác nhận lại các nhận xét ấy. **Logo trên nón/gile vẫn chưa được nghiệm thu độc lập ở kích thước thật.**

Lịch và tên người giữ nguyên snapshot canonical, 08:30–11:00 = 150 phút; bốn chủ đề Phần 2 không có mốc riêng. Đây là lịch từ nguồn người dùng chọn, chưa xác nhận độc lập với ban tổ chức.
