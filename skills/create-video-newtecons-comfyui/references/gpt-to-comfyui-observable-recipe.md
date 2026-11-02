# CHAR08 — Học từ kết quả GPT để cải thiện ComfyUI

Ngày kiểm: 2026-10-23. Phạm vi: prompt, ảnh tham chiếu và ảnh đầu ra có thật trên máy. Đây là phân tích để thiết kế thí nghiệm; **không có huấn luyện model/LoRA hoặc GPU job nào do báo cáo này thực hiện**. Tên backend ImageGen thực tế không được tool công bố. Không suy ra kiến trúc, sampler, seed, bước suy luận hay cách huấn luyện nội bộ từ hình ảnh.

## Bằng chứng và giới hạn

- Nguồn: `production-v2-45s/imagegen-char08-v001/manifest.json` và `casting/CHAR_08_Tran_Thao_Mai/prompts.json`. Đã kiểm cả 20 chuỗi prompt khớp nhau và khớp SHA UTF-8 lưu trong prompts.json.
- Đã xem trực tiếp và kiểm SHA bốn ảnh `gpt/v001/images/CHAR_08_FACE_02_WARM_SMILE.png`, `CHAR_08_FACE_04_DECISIVE_COMMAND.png`, `CHAR_08_ACTION_01_FRONT_FULL_BODY.png`, `CHAR_08_ACTION_02_THREE_QUARTER_FULL_BODY.png`.
- Đã xem bốn nguồn: ICON, MASTER, GOC_XOAY và áo `SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png`. ICON/MASTER có nét minh họa và nhiều khung; body sheet có dây đeo, thẻ và tablet. Đây là nguồn gây xung đột với đồng phục/tác vụ mới nếu không phân vai.
- Bốn ảnh GPT được kiểm có kích thước thực **1086×1448**. Chúng chưa phải ảnh native 1536×2048 hoặc 4K. Metadata hiện vẫn `GENERATED_QA_PENDING`.
- GPT v001 dùng **4 file gốc**. Comfy r078 dùng **3 file dẫn xuất đã crop/pad**, bỏ MASTER, khác prompt và cách mã hóa. Vì vậy không được quy toàn bộ chênh lệch cho model. Riêng cặp r078, chỉ khi cả hai hệ thống dùng cùng ba file, thứ tự và chuỗi prompt mới có đối chứng đầu vào; bộ mã hóa bên trong vẫn khác và seed liên nền tảng không tương đương.
- Người phân tích không xác minh được model route của chính subagent; không gắn nhãn “Astra đã xác nhận” chỉ từ tên yêu cầu.

## Điều thật sự đẹp và điều vẫn sai

| Ảnh | Quan sát trực tiếp | Điểm chưa đạt brief |
|---|---|---|
| FACE02 | Nhận ra các đặc điểm kính tròn, tóc rẽ, má và nụ cười từ ICON. Mắt/má/miệng cùng tham gia nụ cười. Ánh sáng dịu; mắt đọc được qua kính; tóc, đường may và vải rõ. | Da vẫn khá mịn, không chứng minh đây là ảnh người thật. Lưới vải thay đổi mật độ biểu kiến theo vùng; cần crop 100% kiểm riêng. |
| FACE04 | Miệng mở theo lời nói, mắt hướng tới người nghe, chân mày vừa phải; biểu cảm khác FACE02 mà vẫn nhận ra cùng nhân vật. Tư thế chỉ tay hỗ trợ hành động. | Thêm tablet và cử chỉ chỉ tay dù brief chỉ yêu cầu chest-up ra lệnh. Vải vùng ngực trông thành ô lớn hơn nguồn áo; không coi là đồng phục chính xác tuyệt đối. |
| ACTION01 | Một người, hai tay buông dễ đọc, toàn thân đủ giày, trọng tâm đứng hợp lý, tương quan đầu/thân/chân thuyết phục trong hình. Áo không có dây/thẻ/ngực in logo lớn. | Brief yêu cầu “neutral confident expression” nhưng ảnh cười rõ. Có mũ bảo hộ và màn hình nền; không đồng nghĩa người đang mặc mũ, nhưng phải kiểm nếu task cấm cả đạo cụ nền. Chưa có đo tỷ lệ đủ để tuyên bố chiều cao cố định. |
| ACTION02 | Góc ba phần tư và tư thế chân tự nhiên, bàn tay cầm tablet có mục đích; tóc/kính/áo tạo tính liên tục với ACTION01. | Brief ghi “natural relaxed arms” nhưng ảnh đưa tablet vào. Chữ N nhìn thấy ở **phía trái ảnh**, trái với ràng buộc “image-right collar tip”. Ống tay gập lên khác ACTION01. Không dùng ảnh này làm ground truth chính xác về áo/tác vụ. |

Kết luận quan sát: độ hấp dẫn đến từ tổng hợp bố cục, tỷ lệ có vẻ tự nhiên, nét mặt rõ, biểu cảm phối hợp và ánh sáng dịu. Chỉ tăng độ nét hay thêm từ “photoreal” không giải quyết các lỗi này. Những quan hệ nhân quả về prompt/reference vẫn là **giả thuyết cần A/B**; chưa có phép ablation chứng minh đóng góp riêng từng ảnh.

## Công thức có thể dùng lại

1. **Một hồ sơ nhân vật bất biến + một đoạn tác vụ riêng cho mỗi ảnh.** Giữ tên Trần Thảo Mai, tuổi 25, kỹ sư BIM 3D/digital construction progress-control, đặc điểm khuôn mặt, kính, tóc và bộ đồng phục. Gắn một hành động, một biểu cảm, một khung hình rõ ràng. Lưu đủ 20 prompt khác nhau, ID/seed/hash/source và output tương ứng. Một workflow dùng lại được không có nghĩa một prompt tạo đúng 20 biểu cảm.
2. **Phân vai bằng cả ảnh thực và văn bản.** ICON là nhận dạng; MASTER chỉ bổ sung khi thí nghiệm cho thấy lợi ích; một người trong GOC_XOAY là tỷ lệ cơ thể; ảnh áo là vải/cổ/mark. Tên file trong prompt không tự nạp ảnh. LoadImage phải đi tới encoder ảnh/VAE/reference conditioning rồi sampler. Lưu thứ tự ảnh và hash; không dùng ảnh mặt đã loại làm nhận dạng.
3. **Giảm nhiễu tham chiếu bằng crop có kiểm.** ICON có các khung nhỏ và caption; body sheet có sáu người. Crop một mặt/một thân, fit giữ tỷ lệ rồi pad, ghi tọa độ và scale. Không stretch. Đây là một biến thí nghiệm vì crop/pad cũng thay đổi tỷ lệ diện tích mặt trong ảnh mà encoder nhìn thấy. Đừng coi tăng megapixel là tăng trọng số nhận dạng: hai khái niệm khác nhau.
4. **Tách khung chân dung và toàn thân.** Chân dung dành đủ pixel cho mắt, môi và đường nét; toàn thân phải có cả hai giày, khoảng trống đỉnh đầu và sàn, góc máy nhất quán. So tỷ lệ đầu/thân, vai/đầu, eo/hông và thân/chân trong những ảnh cùng góc/camera; không suy chiều cao thật từ pixel ở hai phối cảnh khác nhau.
5. **Viết biểu cảm theo cơ mặt và mục đích.** Warm smile: má nâng, khóe miệng nâng, mí dưới tham gia, lộ răng trên vừa phải, chân mày thả lỏng. Command: mắt tập trung, chân mày hạ nhẹ, miệng mở giữa một âm, hàm có lực vừa phải. Neutral: môi khép, má nghỉ, không còn nụ cười. Khi sửa biểu cảm, mask chỉ miệng có thể để má/mắt vẫn cười; cần vùng liên tục đủ cho cơ mặt nhưng tránh đổi toàn danh tính.
6. **Thiết lập cơ thể thật bằng hình học/ảnh chuẩn, không chỉ lời hứa.** ReferenceLatent và prompt “preserve proportions” chưa khóa xương. Với ảnh chỉ đổi mặt, compositing ngoài mask có thể kiểm 0 pixel đổi. Với ảnh đổi tư thế, đo tỷ lệ và kiểm khớp/trọng tâm; nếu dùng pose/depth phải xác minh node/model tương thích trước, không dựng graph giả.
7. **Đồng phục là lượt kiểm riêng.** Nhìn crop 100% của cổ, ngực và tay áo; giữ mật độ lưới theo thang vật thể và phối cảnh, không chỉ màu xanh. Kiểm mark N theo bên cơ thể và góc máy đã quy định, tránh lật ảnh. Với chữ NEWTECONS hoặc chữ dài, prompt không đảm bảo 100% ký tự: dùng asset chuẩn/cách áp lên áo có kiểm và kiểm từng ký tự ở final. Ảnh đẹp không được tự vượt gate này.
8. **Da và ánh sáng vừa đủ.** Bắt đầu bằng “soft neutral daylight, natural pores and subtle tonal variation”; tránh chồng hàng loạt từ “coarse pores / hypertexture / mature” làm già mặt. Quan sát bóng dưới cằm, phản xạ kính, tiếp xúc giày–sàn, nếp vải và tay; không dùng sharpen/upscale để che lỗi nhận dạng.
9. **HD trước, 4K sau gate.** Chỉ upscale ứng viên đã đạt mặt/tác vụ/tỷ lệ/áo. Ghi native size và upscale size riêng. SeedVR2 có thể thay chi tiết nên final vẫn phải kiểm lại mặt, vải và mark. Không gọi upscaled 4K là ảnh native 4K.

## Ma trận thí nghiệm — chưa chạy

Baseline local được đề xuất: Krea2 Turbo đúng runtime, CFG1, Euler/simple, không LoRA cho tạo ảnh mới, seed cố định `202610780801`, một output/task. Lưu version graph và hash model. Khi thử graph masked edit dùng một baseline riêng với ảnh init/mask cố định; không so trực tiếp như đổi một biến với text-to-image.

| ID | Biến duy nhất trong một cặp | Các mức thử | Câu hỏi cần giải đáp |
|---|---|---|---|
| E01 | Cách chuẩn bị cùng bộ nguồn | Sheet gốc / crop một người rồi pad cùng kích thước | Có bớt tablet/dây đeo/collage và giữ mặt tốt hơn không? Định danh nguồn giữ nguyên; số file phải tương ứng trong mỗi cặp. |
| E02 | Bổ sung MASTER | ICON+body+shirt / cùng ba ảnh + MASTER | MASTER hỗ trợ nhiều góc hay làm lẫn nụ cười/phụ kiện? Chỉ thực hiện khi node encoding hỗ trợ bốn ảnh thực. |
| E03 | Thứ tự tham chiếu | body→face→shirt / face→body→shirt | Thứ tự ảnh có ảnh hưởng? Sửa đồng thời binding index trong prompt để role không sai; ghi đây là thử đóng gói/binding. |
| E04 | Độ dài đoạn nhận dạng | Mô tả gọn đầy đủ / đoạn dài r078 | Cùng task/ref/seed, prompt dài có làm yếu ràng buộc hành động không? Không thay adjective về tuổi/da trong cùng cặp. |
| E05 | Đoạn biểu cảm | “warm smile/neutral” ngắn / mô tả phối hợp mắt-má-miệng | Biểu cảm khác nhau rõ hơn mà không đổi danh tính? Ưu tiên NEUTRAL_FOCUS, WARM_SMILE, DECISIVE_COMMAND. |
| E06 | Số bước native | 8 / 12 | Có tăng chi tiết/tuân thủ hay chỉ tăng thời gian? Giữ CFG1, model, noise seed, resolution và toàn bộ inputs. |
| E07 | Denoise trong masked expression | 0.35 / 0.50 / 0.65 | Mức nào bỏ được nụ cười nhưng không đổi mặt? Giữ cùng init, mask, seed và sampler; đo preservation ngoài mask. |
| E08 | Phạm vi mask biểu cảm | Mày+miệng rời / oval mặt liên tục có bảo vệ viền | Có hết mâu thuẫn mắt cười–miệng nghiêm? Denoise cố định; kiểm kính/jaw/tuổi. |
| E09 | Đoạn chất da | “natural pores, soft daylight” / mô tả chi tiết hơn có kiểm | Có giảm mịn giả mà không tăng tuổi/nếp nhăn? Giữ tuổi25 và không thêm từ “mature”. |
| E10 | Hoàn thiện đồng phục | Kết quả trực tiếp / một lượt sửa áo bằng asset chuẩn, giữ ngoài mask | Có đạt lưới/mark mà không đổi đầu–tay–thân? Đây là so pipeline hai giai đoạn, không phải đổi model. |

Không chạy toàn bộ tổ hợp. Chọn một cặp từ E01/E05 trước; dùng 4 task đã xem làm bộ kiểm tối thiểu, bổ sung neutral vì nó khó thoát nụ cười nguồn. Mỗi cặp giữ seed cố định. Sau khi chọn cấu hình, xác nhận bằng hai seed phụ khác và một tư thế chưa dùng khi chọn. Đổi resolution làm thay lưới noise: không gọi đó là cùng noise dù seed số giống nhau. Nếu 3MP×3refs hết VRAM, ghi kết quả thất bại; không âm thầm giảm size trong một nhánh rồi gọi là đối chứng tương đương.

## Phiếu QA và dữ liệu học

- Ghi rõ task requested/observed; thêm prop, sai biểu cảm, logo lật, tay áo đổi là lỗi riêng, không cộng điểm “đẹp” để che.
- Face: đối chiếu ICON, biểu cảm, kính/tóc; đánh giá đa người nếu cần và lưu verdict người dùng. Không tuyên bố danh tính 100% bằng cảm giác hay embedding đơn lẻ.
- Body: landmark/camera/pose cùng hệ quy chiếu; ảnh trước–sau sửa mặt cần 0 RGB pixel đổi ngoài mask. Pose mới phải qua kiểm hình học độc lập.
- Garment: crop cổ/ngực/tay ở độ phân giải gốc, mark đúng vị trí, không thẻ/dây, lưới mịn; không dùng OCR thành công như bằng chứng tất cả nét logo đúng.
- Các ảnh GPT hiện là **ứng viên tham khảo**. Chỉ ảnh qua từng gate mới đưa vào bộ chuẩn. Không tự lấy toàn20ảnh làm nhãn huấn luyện. Báo cáo này chuyển quan sát thành recipe/prompt/QA; nếu sau này huấn luyện identity LoRA, phải lập task riêng với dataset đã chọn, caption, train/validation split và cấu hình model tương thích. Không huấn luyện trong lần phân tích này.

Danh sách evidence có SHA, bốn prompt nguyên văn và ma trận dạng máy đọc được nằm trong `gpt-to-comfyui-observable-recipe.json` cùng thư mục.
