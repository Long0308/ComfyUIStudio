# Mốc chất lượng CHAR08 và sọc phản quang

Yêu cầu người dùng 2026-10-23: CHAR08 ComfyUI phải đạt chất lượng bộ GPT đã chỉ ra; sọc cam–xám luôn đúng. Dữ liệu gắn hash nằm trong pack `production-v2-45s/local-image-e2e/quality-requirements-v002/`. Đọc `char08-gpt-quality-target.json`, `reflector-geometry-contract.json` và `requirements-160.json` trước revision mới. Đây là tiêu chí và tham chiếu, chưa phải ảnh đã render hay nghiệm thu.

## CHAR08

Lấy PNG GPT gốc, receipt và hash thật làm mốc thị giác; screenshot người dùng chỉ giúp xác định lựa chọn. Bộ nguồn sáu góc và master vẫn dùng để kiểm danh tính. Mốc người dùng thích gồm gương mặt trưởng thành, kính kim loại mảnh, ponytail, thần thái tự nhiên, dáng áo vừa vặn và văn phòng sáng có kiến trúc trụ sở thật. Giữ lưới áo cực nhỏ và logo cổ theo yêu cầu trang phục mới dù mẫu GPT còn thiếu/sai chi tiết đó.

So cùng task bằng ảnh toàn cảnh và vùng mặt ở độ phân giải gốc: nhận dạng, tuổi cảm nhận, mắt/kính, tóc, cấu trúc mặt, da, biểu cảm, dáng người, tay, bố cục và ánh sáng/bối cảnh. Không dùng ảnh neutral cận mặt để chứng minh đã đạt nụ cười, dáng người hay bố cục của mẫu GPT. Mặt nhựa, mặt khác, kính đổi kiểu, crop bó sát làm mất dáng hoặc bối cảnh văn phòng chung chung đều cần sửa. Ảnh local CHAR08 r030 chỉ là prototype, chưa chứng minh ngang mẫu GPT.

Chạy một pilot CHAR08 cùng task với GPT, so trực tiếp và lưu nhận xét gắn hash trước khi batch CHAR08. Với task chưa có baseline, ghi rõ thiếu mẫu cùng task; chỉ dùng các mẫu CHAR08 khác làm mốc ngoại hình. Không đổi tên/copy ảnh GPT thành đầu ra ComfyUI. Nghiệm thu vẫn PENDING.

## Hình học sọc và áo

Nguồn hình học là `wardrobe/v001/originals/ÁO PHẢN QUANG 1.png` (trước) và `ÁO PHẢN QUANG 2.png` (sau), không suy từ áo GPT đã sinh. Chữ bộ phận trên ảnh áo gốc là chữ cũ; phải thay theo hợp đồng chữ hiện hành.

- Mặt trước: dải xám/bạc ngang ngực nằm dưới chữ/logo và trên túi; cụm ở gấu áo có thứ tự từ trên xuống **cam – xám/bạc – cam**. Giữ vị trí thật của túi, mesh và khóa kéo. Không tự thêm ba cụm ngang mặt trước như mặt sau.
- Mặt sau: **ba cụm cam – xám/bạc – cam** ở lưng trên, giữa và gấu, đúng nguồn; giữ logo lưng, khoảng lưới và vị trí mép áo. Không biến chúng thành ba vạch đơn màu.
- Khi xoay/nghiêng: kiểm thứ tự màu, bề rộng tương đối, số cụm, đường nối ở sườn và sự biến dạng theo nếp áo/phối cảnh. Khóa kéo chia thân trước là gián đoạn thật; không vẽ sọc xuyên qua khóa, tay hoặc vật che.
- Kiểm phần nhìn thấy trên chính PNG cuối bằng crop và tọa độ; vùng khuất/cắt khỏi khung ghi `NOT_VISIBLE`, không tự đoán PASS. Ảnh cận mặt không chứng minh toàn bộ gấu/lưng đúng. Muốn dùng làm chuẩn toàn áo phải có ảnh đủ thân trước/sau được kiểm riêng.

Với biểu cảm chỉ sửa mặt, kiểm pixel ảnh cuối ngoài mask bằng ảnh cha đúng hash, đồng thời kiểm ảnh cha có báo cáo hình học sọc phù hợp với phần đang dùng. Pixel giữ nguyên chỉ chứng minh bảo toàn; nếu ảnh cha sai sọc thì con vẫn sai. Với hành động/tư thế mới, cần conditioning/mask trang phục theo nguồn thật và kiểm lại sau render; prompt mô tả đúng không thay bằng chứng ảnh.

Đúng chữ và đúng sọc là các điều kiện độc lập. Chưa đủ bằng chứng thì giữ PENDING/FAIL cho tiêu chí đó, không gộp một PASS chữ thành PASS trang phục. Lưu người kiểm, job/request/graph hash, PNG/crop hash, vùng thấy/khuất và lỗi cụ thể. Video tiếp tục dừng trong goal ảnh.
