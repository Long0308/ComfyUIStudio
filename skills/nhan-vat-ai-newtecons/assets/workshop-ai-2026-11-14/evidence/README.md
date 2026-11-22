# Bằng chứng kiểm tra Workshop AI

Ảnh gốc trong bộ này đã được audit ngày **2026-11-05**; đóng gói và kiểm tra lại ngày **2026-11-12**. Ngày **14.11.2026** là ngày sự kiện trên poster. Quy trình và bốn cặp ảnh/prompt nằm ở [README của bộ sản xuất](../README.md).

## Những gì đã đo

Lượt kiểm độc lập bằng Windows PowerShell 5.1, `scripts/verify.ps1 -Render`, trả **exit code 0** và tạo lại hai poster khớp nguyên byte với asset được chọn. Verifier kiểm 6 asset, 4 prompt JSON, 4 phần lịch và 7 mục con có giờ riêng. Lịch nối tiếp từ 08:30 đến 11:00, tổng 150 phút. Có **38 record chữ dọc + 39 record chữ ngang = 77**, khớp nguyên văn và không tràn chiều rộng theo phép đo GDI+.

| Đầu ra | Kích thước pixel | SHA-256 |
|---|---|---|
| Dọc 9:16 | 2160 × 3840 | `65317558CD0262F386B35FA001D4CEA1A4A3EBE7C255CCD25908CC94AF2DE8F8` |
| Ngang 16:9 | 3840 × 2160 | `9139909D620728C6E02ADF5804B580F9C1BFB8192AF1FE32C9B25BB19D53511E` |

[approved-layout-audit.json](approved-layout-audit.json) giữ tọa độ, font, kích thước vùng chữ và chiều rộng đo được của bản nguồn đã duyệt. Lượt render mới ghi audit vào `output/layout-audit.json`; thư mục `output/` bị loại khỏi Git. Dùng [assets-manifest.json](../assets-manifest.json) để đối chiếu byte/hash/kích thước từng đầu vào.

## Giải mã QR độc lập

Kiểm lại ngày **2026-11-12** bằng **OpenCV 4.12.0**, giải mã trực tiếp ba file đầy đủ với `QRCodeDetector().detectAndDecode`. Cả ba trả cùng đích **https://q.me-qr.com/k3x1m00q**:

| File | Kích thước | Kết quả |
|---|---|---|
| [QR nguồn](../assets/original-workshop-qr.jpg) | 1000 × 1000 | Phát hiện và giải mã đúng đích |
| [Poster dọc](../assets/Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png) | 2160 × 3840 | Phát hiện và giải mã đúng đích |
| [Poster ngang](../assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png) | 3840 × 2160 | Phát hiện và giải mã đúng đích |

Renderer dùng crop `(100,0,800,800)` của QR nguồn và nội suy nearest-neighbor. Phép kiểm trên đọc file PNG cuối, không chỉ đọc lại crop nguồn. Việc giải mã URL không xác nhận nội dung website đích hoặc tình trạng đăng ký sự kiện.

Chạy lại từ thư mục gốc của bộ sản xuất, với môi trường Python đã có `cv2`:

```powershell
@'
import cv2
from pathlib import Path
expected = "https://q.me-qr.com/k3x1m00q"
files = [
    "assets/original-workshop-qr.jpg",
    "assets/Newtecons-Workshop-AI-MEP-FINAL-9x16-4K-v2.png",
    "assets/Newtecons-Workshop-AI-MEP-FINAL-16x9-4K-v2.png",
]
print("OpenCV", cv2.__version__)
for filename in files:
    image = cv2.imread(str(Path(filename)))
    assert image is not None, filename
    value, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    assert points is not None and value == expected, (filename, value)
    print(filename, value)
'@ | python -
```

`verify.ps1` báo **QR decoding: NOT RUN** vì công cụ đó chỉ kiểm bảo toàn asset/hash; kết quả QR ở trên là phép đo riêng bằng OpenCV.

## Kiểm trực quan và giới hạn

- [Crop “tầm tay”](portrait-tam-tay.png): xem dấu mũ và dấu huyền trong **ầ**; chuỗi Unicode đúng là `tầm`, `U+0074 U+1EA7 U+006D`.
- [Chi tiết nón](portrait-helmet-detail.png): xem hình N đỏ, chữ NEWTECONS xanh, độ nét và phối cảnh. Header chỉ dùng wordmark nằm sẵn trong logo gốc; không gõ thêm NEWTECONS cạnh logo.
- [Phần 1 ngang](landscape-part1.png): xem năm tiêu đề đồng cỡ, mỗi tiêu đề một dòng; dòng người trình bày/dự án nghiêng không đậm, nhỏ hơn tiêu đề.
- Chiều cao glyph, dấu bị cắt, chữ đè dòng, lỗi tay/mặt và chất liệu cần xem ảnh 1:1. `Fits` trong audit chỉ chứng minh phép đo **chiều rộng**, không phải OCR hay kiểm va chạm vùng chữ.
- [font-reference-hashes.json](font-reference-hashes.json) chỉ ghi file font của môi trường tham chiếu; verifier không cưỡng chế các hash font này.
- Canvas và chữ được dựng trực tiếp ở 4K; ảnh MEP nguồn **1998 × 787** và ảnh BIM tham chiếu **2160 × 804** không trở thành ảnh sinh nguyên bản 4K nhờ đặt lên canvas lớn.
- Prompt 03/04 được tái dựng từ ảnh đã chọn. Không có bằng chứng về prompt lịch sử nguyên văn, seed hoặc model tạo hai ảnh cũ; không gán các thông số đó từ tên file.

Khi thay ảnh, font, nội dung hoặc bố cục, lưu phiên bản mới, chạy lại verifier và giải mã QR trên bản cuối. Các hash hiện tại chỉ mô tả đúng hai poster xanh–trắng trong bộ gốc; biến thể phong cách có bằng chứng riêng.
