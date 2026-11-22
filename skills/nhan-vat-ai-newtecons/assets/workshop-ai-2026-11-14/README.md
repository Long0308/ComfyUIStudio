# Workshop AI NEWTECONS — 4 ảnh, 4 prompt và hai poster 4K

**Chọn trong [4 style Workshop AI](styles/README.md): Blue–White, Editorial, Signature Navy, Navy–Cyan.** Mỗi style có đủ ảnh dọc/ngang, prompt và mã dựng. Xem [quy tắc logo công ty, tên khối thay đổi và Build on trust](branding/README.md) trước khi làm bản mới. [Audit logo chi tiết](evidence/logo-audit-2026-11-12.md) ghi rõ lỗi/giới hạn còn tồn tại; không hiểu các kiểm kỹ thuật trước đó là PASS cho mọi chi tiết logo.

Bộ sản xuất đã chọn cho Workshop AI ngày **14.11.2026**, gồm hai poster xanh–trắng, ảnh kỹ sư tại công trường MEP và ảnh tham chiếu BIM. Các file trong `assets/` là bản người dùng chọn, được chép nguyên byte. Hai tên có hậu tố `v2` trùng SHA-256 với hai file cuối không có hậu tố `v2` đã được audit.

Ngày sự kiện trong tên thư mục là **14.11.2026**; bản nguồn được audit ngày **05.11.2026**, gói hướng dẫn được hoàn thiện ngày **12.11.2026**. Giữ riêng ngày sự kiện, ngày tạo ảnh và ngày kiểm chứng khi tái sử dụng bộ này.

Quy trình này mở rộng [nhan-vat-ai-newtecons](https://github.com/Long0308/setupagent/blob/main/.agents/skills/nhan-vat-ai-newtecons/SKILL.md) và [tao-anh-prompt-as-code](https://github.com/Long0308/setupagent/blob/main/.agents/skills/tao-anh-prompt-as-code/SKILL.md). **Phương pháp thực tế: ảnh riêng + logo/QR gốc + chữ và bố cục dựng bằng font thật trên canvas cuối.** Đây là công thức tái tạo có kiểm chứng, không phải lời hứa rằng một prompt sinh ảnh duy nhất sẽ viết đúng toàn bộ lịch tiếng Việt.

> Bản nguồn hai skill nằm tại `setupagent/.agents/skills/`; mỗi skill có một snapshot của gói này tại `assets/workshop-ai-2026-11-14/`, gồm cả ảnh và source. Liên kết hai skill dùng GitHub để giữ đúng khi gói được chép sang vị trí khác.

## Bốn ảnh và bốn prompt

| # | Ảnh đã chọn | Prompt tương ứng | Vai trò và kích thước thật |
|---|---|---|---|
| 01 | [Poster dọc v2](assets/Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png) | [01-portrait-9x16.json](prompts/01-portrait-9x16.json) | Poster 9:16, **2160 × 3840** |
| 02 | [Poster ngang v2](assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png) | [02-landscape-16x9.json](prompts/02-landscape-16x9.json) | Banner 16:9, **3840 × 2160** |
| 03 | [ChatGPT Image Nov 5, 2026, 11_10_50 AM.png](assets/ChatGPT%20Image%20Nov%205,%202026,%2011_10_50%20AM.png) | [03-natural-mep-hero.json](prompts/03-natural-mep-hero.json) | Ảnh MEP được chọn, **1998 × 787** |
| 04 | [workshopaiv4-character-detail.png](assets/workshopaiv4-character-detail.png) | [04-bim-character-reference.json](prompts/04-bim-character-reference.json) | Ảnh BIM tham chiếu cũ, **2160 × 804** |

<p><img src="assets/Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png" alt="Poster dọc 9:16" width="300"> <img src="assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png" alt="Poster ngang 16:9" width="700"></p>

![Ảnh MEP tự nhiên đã chọn](assets/ChatGPT%20Image%20Nov%205,%202026,%2011_10_50%20AM.png)

![Ảnh BIM tham chiếu cũ](assets/workshopaiv4-character-detail.png)

Prompt 01/02 là **chỉ dẫn cho quy trình dàn trang**, đi kèm toàn bộ `text_content` chính xác. Prompt 03/04 là **công thức tái tạo được viết lại từ ảnh**, không được nhận là nguyên văn prompt lịch sử, seed hay model đã sinh ảnh. Lượt đóng gói này không sinh lại ảnh nhân vật.

## Biến thể phong cách navy–cyan

[Bộ navy–cyan ngày 12.11.2026](styles/navy-cyan-2026-11-12/README.md) đáp ứng yêu cầu phong cách bổ sung của người dùng, có ảnh, prompt, renderer và bằng chứng riêng. Bốn ảnh/bốn prompt ở bảng trên vẫn là bộ xanh–trắng gốc. Không áp dụng hash hoặc kết quả audit của hai poster gốc để nghiệm thu biến thể mới.

## Chạy lại hai poster

Yêu cầu: Windows, **Windows PowerShell 5.1** (`powershell.exe`) và các font **Roboto Condensed Regular, Bold, Italic**. Font không được đóng gói lại; [dấu vân tay font trên máy đã nghiệm thu](evidence/font-reference-hashes.json) giúp đối chiếu môi trường. Phiên bản font khác có thể làm đổi độ rộng chữ hoặc hash ảnh. Script dừng nếu thiếu font, không âm thầm thay bằng font khác.

Dấu vân tay font là thông tin tham chiếu để đối chiếu thủ công; verifier không kiểm hash file font. Cổng hash PNG cuối vẫn phát hiện đầu ra khác bản đã chọn.

Từ thư mục chứa README này:

```powershell
# Dựng mới từ ảnh nguồn + logo + QR, rồi kiểm tra:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -Render

# Chỉ kiểm các file đã có, không nhận là vừa dựng lại:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Kết quả nằm trong `output/`: hai PNG đúng tên v2 và `layout-audit.json`. `assets/` là mẫu đối chiếu bất biến. Thư mục `output/` bị loại khỏi Git. `render.ps1` dùng lại [PosterRenderer.cs](scripts/PosterRenderer.cs), không đổi thuật toán hay bố cục của bản đã duyệt. Không chạy trực tiếp bằng PowerShell 7: môi trường đã gặp lỗi thiếu `System.Drawing.Common` ở runtime đó.

[content.json](content.json) là snapshot kiểm tra lịch; chuỗi được vẽ nằm trong renderer. Hai prompt poster chứa bản sao chính xác của các chuỗi audit để phát hiện drift. Khi có chương trình mới, sửa có chủ đích nội dung renderer và các snapshot, sau đó nghiệm thu lại; JSON không phải API tự động đổi lịch của renderer này.

## Cách dùng prompt ảnh nhân vật

1. Mở prompt 03 hoặc 04 và đọc `input_roles`, `change_contract`, `negative`, `acceptance`.
2. Đính kèm **đúng file thật** mà `input_roles` chỉ định. Không nhắc tên ảnh mặt/logo không có trong payload. Trường `prompt` là đoạn dùng để gửi công cụ sinh/sửa ảnh; tám trường nguyên tử giải thích và khóa các quyết định thị giác.
3. Với bản đang được chọn, dùng nguyên ảnh 03. Khi người dùng muốn ảnh mới, tạo ảnh riêng trước; lưu prompt nguyên văn, tool/model nếu công cụ trả về, danh sách ảnh đầu vào và kích thước ảnh thực tế. Không suy backend từ tên file ChatGPT.
4. Audit mặt, bàn tay, vật liệu, chữ trên nón/áo ở kích thước thật. Các câu “identity lock” là yêu cầu, không chứng minh kết quả giữ mặt đúng. Logo bị méo phải sửa từ asset gốc theo bề mặt/nếp vải, rồi audit lại.
5. Thay hero trong một phiên bản bố cục mới và kiểm lại. Gói cố định này dùng hash để khóa ảnh đã duyệt; ảnh mới cần manifest/reference mới, không tắt cổng hash để nhận nhầm là bản cũ.

Hai ảnh hero là dải ảnh ngang, **không phải hai poster 4K**. Nếu cần hero mới 16:9, dựng thêm không gian quanh người để giữ trọn nón và tay rồi chọn vùng ảnh cho poster; không kéo giãn dải ảnh cũ thành 16:9 hoặc 9:16.

## Typography, bố cục và điểm nhấn

Font chính là **Roboto Condensed**. Dùng chữ đậm để phân cấp, dòng người trình bày/dự án/văn phòng nhỏ hơn và **Italic không Bold**. “14 / 12 / 10” là ví dụ quan hệ cỡ chữ, không phải cỡ pixel cho ảnh 4K. Bản đã chọn dùng các số đo sau:

| Thành phần | Dọc 2160 × 3840 | Ngang 3840 × 2160 |
|---|---:|---:|
| Tên chương trình | 128 px Bold | TIMELINE 159 px; WORKSHOP AI 179 px Bold |
| Nhãn MỞ ĐẦU / PHẦN 1, 2, 3 | 72 px Bold | 72 px Bold |
| Năm tiêu đề bài Phần 1 | 58 px Bold | 67 px Bold |
| Người trình bày + dự án Phần 1 | 44 px Italic | 50 px Italic |
| Khung giờ Phần 1 | 48 px Bold | 50 px Bold |
| Người trình bày Phần 2 | 48 px Italic | 38 px Italic |

Năm tiêu đề Phần 1 có cùng cỡ trong mỗi khổ và mỗi tiêu đề nằm **một dòng**. Dòng người trình bày cũng nằm một dòng. Renderer đo chiều rộng và dừng nếu chữ tràn; vẫn phải xem ảnh để phát hiện cắt dấu, đè dòng hoặc lệch thị giác. “Nét mảnh” ở đây là kiểu nghiêng không đậm của bản đã duyệt, không phải xác nhận dùng font weight 300.

- **Khổ dọc:** ảnh trên cùng `(0,0,2160,804)`; nội dung chạy từ trên xuống; lề nội dung 72 px. QR đặt dưới Phần 3 tại `(914,3507,332,332)`.
- **Khổ ngang:** ảnh ở `(1810,0,2030,755)` với mảng trắng chéo; đầu trái là logo và tiêu đề. Mở đầu + Phần 1 ở cột trái; Phần 2 + Phần 3 ở cột phải. QR tại `(3100,1850,277,277)`.
- **Full frame:** xuất đúng khung cuối, không viền đen, không kéo méo và không cắt chữ/nón/QR. Lề trắng bên trong là thành phần của bố cục.
- Nền `#FFFFFF`, chữ navy `#0A2540`, điểm nhấn `#0B4FD9`, panel nhạt `#E2F0FF`, metadata `#224674`. Điểm nhấn đến từ ảnh người làm việc, tương phản cỡ chữ và đường chéo xanh.
- Chỉ giữ ký hiệu thời gian, đường nối và nút timeline có công dụng. Không thêm robot, chip, tia sáng, mạch điện hay icon cho mọi dòng.

## Logo, nón, áo và chất liệu

Header là **[logo NEWTECONS gốc] | {header_department_text}**, mặc định **KHỐI CƠ ĐIỆN**. Tên khối là lớp chữ riêng để đổi sang khối khác, không đổi artwork công ty hoặc nội dung đơn vị của diễn giả. Wordmark đã nằm trong logo; không gõ thêm một chữ NEWTECONS đứng cạnh. Chữ NEWTECONS ở địa điểm `12A NEWTECONS` và trên nón thuộc các ngữ cảnh khác, không phải lỗi trùng header. Biến này là hợp đồng thiết kế; renderer lưu trữ chưa có API tự thay tên khối. Quy trình dựng vector từng glyph khi cần, dòng xanh và chính tả **Build on trust** nằm ở [branding](branding/README.md).

Ảnh MEP có đúng một nam và một nữ, đội nón trắng, mặc sơ mi caro ô vuông trắng–xanh và gile navy. Kiểm riêng hình N đỏ, chữ NEWTECONS xanh, độ nét của từng nón; giữ phối cảnh và bóng bề mặt. Vải phải còn thớ/carô, da có cấu trúc tự nhiên, kim loại giữ phản xạ thật; tránh halo do sharpen, da nhựa và mặt bị nhòe.

Khi tạo nhân vật mới, dùng quy định PPE đã có trong skill: logo trắng đúng vị trí ngực, không in logo lên túi; chữ đơn vị theo biến được yêu cầu. Khi tái hiện ảnh 03/04 đã được chọn, **giữ trang phục và vị trí thương hiệu thực tế của ảnh**, không tự thêm `KHỐI KỸ THUẬT` vào ảnh nguồn. Đây là khác biệt giữa giữ ảnh đã duyệt và tạo bộ nhận diện mới.

Quy định màu xanh–trắng áp dụng cho đồ họa poster. Dải phản quang cam và màu thương hiệu vốn có trên PPE vẫn giữ đúng ảnh gốc. Ảnh 04 có logo lớn và hiệu ứng BIM riêng: đó là tham chiếu cũ, không tự đưa glow/wordmark lớn ấy vào hai poster MEP đang chọn.

## Lịch và cấp cha–con

| Cấp cha | Khoảng thời gian | Mục con | Thời lượng |
|---|---|---|---:|
| Mở đầu | 08:30–08:55 | Võ Thanh Cang 08:30–08:40; Minigame 08:40–08:55 | 25 phút |
| Phần 1 | 08:55–10:15 | 5 bài: 15 + 15 + 15 + 15 + 20 phút | 80 phút |
| Phần 2 | 10:15–10:50 | 4 chủ đề dưới cùng diễn giả Trương Quang Vinh | 35 phút |
| Phần 3 | 10:50–11:00 | Tổng kết; QR bên dưới | 10 phút |

**9 khoảng chương trình tiếp nối, tổng 150 phút.** Có 7 mục con được cấp giờ riêng (2 mở đầu + 5 Phần 1), cộng 2 khoảng Phần 2/3. Bốn chủ đề Phần 2 không có giờ riêng trong nguồn: không tự bịa bốn mốc. Toàn bộ tiêu đề, tên người và dự án có trong [content.json](content.json) và hai prompt poster. Đây là lịch giữ từ mẫu người dùng chọn, không phải xác nhận độc lập với ban tổ chức.

## Chữ tiếng Việt và QR

Từ đúng là **“trong tầm tay”**: `tầm` = `U+0074 U+1EA7 U+006D`. Chữ **ầ** có mũ và dấu huyền; **ằ** là dấu trên ă, không đúng từ này. Kiểm chuỗi Unicode là một lớp; phải xem cả nét chữ đã raster ở crop 1:1. Xem [crop “tầm tay”](evidence/portrait-tam-tay.png), [chi tiết nón](evidence/portrait-helmet-detail.png) và [Phần 1 ngang](evidence/landscape-part1.png).

Kiểm từng tên: Trần Dương Hồng Quân; Nguyễn Văn Hải; Nguyễn Đình Thiệu; Nguyễn Thanh Hoàng; Phạm Phi Long & Ngô Ngọc Sơn; Trương Quang Vinh. Giữ chính tả dự án/văn phòng theo nguồn, gồm `Bason`, `The One Sài Gòn`, `P.CNTT`, `Khối Kỹ Thuật` và `AI HST`.

QR dùng pixel gốc, không dùng mô hình ảnh vẽ lại. Renderer lấy vùng `(100,0,800,800)` của ảnh QR nguồn, giữ nền trắng và dùng nearest-neighbor. Đích đã đọc từ QR nguồn và hai poster là **https://q.me-qr.com/k3x1m00q**. Kiểm giải mã final PNG; việc thấy hình vuông giống QR không chứng minh quét được. Script `verify.ps1` báo riêng **QR decoding: not run**; xem lệnh kiểm QR và bằng chứng tại [evidence/README.md](evidence/README.md).

## Độ nét, 4K và nén

Hai canvas và lớp chữ được dựng trực tiếp ở **2160 × 3840 / 3840 × 2160**. Ảnh MEP nguồn là **1998 × 787**; ảnh đó được fit/crop trong vùng hero. Không gọi phần ảnh này là ảnh chụp/sinh nguyên bản 4K. Dòng DPI 300 chỉ là metadata in ấn, không thêm pixel hoặc chi tiết.

Xuất **PNG lossless**. Không lưu JPEG nhiều lần, không upscale toàn poster thấp nét để sửa chữ, không dùng sharpen mạnh để tạo cảm giác nét giả. Bản cũ từng được phóng từ khoảng 941 × 1672 lên 2160 × 3840: kích thước tăng nhưng dấu chữ lỗi và ảnh mờ vẫn còn. Nếu tối ưu dung lượng PNG, phải so pixel sau giải mã; hash file có thể đổi do metadata/nén và cần ghi nhận phiên bản mới. Không giảm độ phân giải hoặc số màu chỉ để có file nhỏ.

## Phạm vi kiểm chứng và sửa lỗi

`verify.ps1 -Render` kiểm 6 asset bằng kích thước/byte/hash, 4 JSON prompt đủ tám trường, lịch cha–con tiếp nối, **38 + 39 = 77** record chữ chính xác, chiều rộng chữ và hash hai ảnh vừa dựng với bản đã chọn. Môi trường nghiệm thu đã tái tạo **byte-identical** hai PNG. Điều này không chứng minh một model sinh ảnh khác sẽ tạo lại mặt hay nón y hệt.

Audit độc lập tiếp tục xem crop chữ, nón, logo, tay, điểm giao ảnh–chữ và QR. Nếu sửa, chọn đúng phần lỗi rồi chạy lại cổng: chữ → sửa chuỗi/font/layout; logo → dùng logo gốc theo bề mặt; ảnh mềm → tạo ảnh nguồn mới; timeline → sửa nội dung chính thức rồi dàn lại. Không dùng ảnh đã bị lỗi làm nền cho nhiều vòng sinh tiếp.

Nguồn và mã băm: [assets-manifest.json](assets-manifest.json). Kết quả đo, giới hạn kiểm tra và lệnh QR: [evidence](evidence/README.md). Các asset thương hiệu trong bộ này là tham chiếu do người dùng cung cấp; bộ prompt không thay đổi quyền đối với logo/ảnh gốc.
