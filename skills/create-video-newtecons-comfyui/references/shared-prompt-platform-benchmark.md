# Cấu trúc benchmark CHAR08: prompt chung, dữ liệu nền tảng riêng

Yêu cầu người dùng 2026-10-23: lưu trong `casting/CHAR_08_Tran_Thao_Mai/`, một bộ `prompts.json` gồm 20 prompt đầy đủ bằng tiếng Anh. Không duy trì hai bộ prompt chỉnh riêng cho GPT và ComfyUI.

```text
CHAR_08_Tran_Thao_Mai/
  prompts.json
  references/
  gpt/v001/images/
  gpt/v001/manifest.json
  comfyui/<revision>/images/
  comfyui/<revision>/manifest.json
  comfyui/<revision>/workflows/
  comfyui/diagnostics/
  analysis/
  skills/creation-snapshot-v001/
  benchmark.json
```

Ghép kết quả bằng `prompt_id` và kiểm `prompt_sha256`. Manifest từng nền tảng lưu nguồn công cụ/model được công bố, ảnh tham chiếu thực tế và thứ tự/hash, seed, graph GUI/API, job ID, kích thước thật, ảnh/hash, thời gian, QA. Không giả seed/job/model nếu công cụ không cung cấp. Prompt trong payload/graph đã chạy là bằng chứng bất biến, không phải bản prompt thứ hai để chỉnh tay. Khi sửa prompt, tạo phiên bản chung mới và chạy lại cả hai bên nếu cần benchmark cùng prompt.

GPT v001 đã có20 ảnh riêng, kích thước thực 1086×1448 hoặc1086×1449. Người dùng khen chất lượng và chọn làm mốc thị giác; điều đó không tự duyệt logo, hành động hay độ phân giải từng ảnh. Chưa phải4K. Ảnh gốc/cũ không xóa hoặc thay nguồn.

GPT v001 dùng4 ảnh gốc; batch local r079 dự kiến dùng3 ảnh dẫn xuất. Vì vậy có thể so cùng prompt nhưng không gọi là thí nghiệm cùng mọi đầu vào. Cặp riêng r078 dùng cùng prompt/3file/thứ tự để kiểm cấu hình. r078 đã chạy thành công về runtime nhưng FAIL thị giác nghiêm trọng (cháy sáng, lưới, bóng người và vật thể thừa); không dùng làm mẫu đạt hoặc nhân bản cấu hình lỗi.

Người dùng cho phép cả batch chẩn đoán để đánh giá; không dùng quy tắc pilot-only cũ để chặn batch có mục đích đo chất lượng. Lỗi thực thi hoặc hỏng ảnh có hệ thống phải được sửa. Video vẫn dừng. Chỉ xuất4K sau kiểm ảnh mặt, vóc dáng, diễn xuất, bàn tay, đồng phục và chữ/logo.

Phân tích Astra chỉ suy ra từ prompt, nguồn, graph và kết quả nhìn thấy. Không tuyên bố biết mô hình/chuỗi suy luận nội bộ của Image Gen. Lưu bài học và tối ưu workflow không phải huấn luyện trọng số; huấn luyện LoRA phải có dataset được kiểm, cấu hình train, checkpoint và kiểm holdout riêng. Không lấy toàn bộ ảnh GPT chưa kiểm làm ground truth.

Phân tích có ảnh/hash và ma trận thử nghiệm: [học từ ảnh GPT để cải thiện ComfyUI](gpt-to-comfyui-observable-recipe.md).
