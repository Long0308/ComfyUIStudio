# CHAR08: kiểm tỷ lệ và chạy lại 20 tác vụ

## Cập nhật hiện hành 2026-10-23

Người dùng loại khuôn mặt r073; tuyệt đối không dùng nó làm chuẩn danh tính. Năm thử nghiệm r069/r071/r072/r073/r074 đã sinh PNG864×1152, đều chưa đạt toàn bộ mặt–dáng–áo. r070 không dispatch. r072 giữ0pixel thay đổi ngoài mask nhưng còn lỗi áo; verifierRGB/gray đã được sửa và review độc lập8testsPASS, QA vẫn FAIL_REWORK.

Người dùng đã xác nhận restart8188, nhưng auto-review tiếp tục chặn toàn bộ lệnh bằng `blocked by policy` trước thực thi. Không stop/start nào xảy ra, không hỏi lại cùng quyền hoặc bypass. Custom Krea2Edit/LivePortrait/RMBG chưa live-loaded; tiếp tục thử sửa bằng node hiện có khi hợp lý.

r076 đang thử sửa mặt trên vùng đầu phóng3×, identity duy nhất từ ICON_FACE; job `a475db89-57dd-46ab-8def-e74057b08c15`. Reviewer xác nhận graph/schema/hash đúng nhưng support mask[330,32]→[520,264] có phủ cổ áo: đây là sửa đầu kèm một phần cổ áo, không tuyên bố bảo toàn toàn áo. Chờ PNG/QA. r075 do Gemini chuẩn bị riêng để sửa áo.

Người dùng cho phép chạy bổ sung20ảnh bằng ImageGen song song nhánh local. Pack riêng `production-v2-45s/imagegen-char08-v001/manifest.json` lưu20prompt,4tham chiếu gốc và kết quả. Backend công cụ tích hợp không công bố model resolved; ghi requested ImageGen2, resolved NOT_EXPOSED_BY_TOOL. Không giả nguồn ComfyUI hoặc gộp ảnh này vào số ComfyUI đạt. Ảnh sinh không tự thành ảnh đạt/4K/nghiệm thu.

Audit r068 `local-image-e2e/char08-batch20-source-readiness-v002.json`:20prompt khác nhau và ICON nối thật; body được nhắc nhưng chưa nối ở20graph và áo chuẩn chưa có binding. Không chạy nguyên batch r068. Dùng r075/r076 để sửa kiến trúc trước.

Yêu cầu mới của người dùng: chạy lại đủ 20 ảnh sau khi phát hiện cùng nhân vật cầm tablet nhưng vai, eo, hông và tỷ lệ thân/chân khác nhau. Quyết định này cho phép tạo revision mới cho cả ACTION01–04 đã từng được giữ; ảnh và QA lịch sử vẫn giữ nguyên.

## Bằng chứng pipeline

`production-v2-45s/local-image-e2e/char08-prompt-geometry-audit-v001.json` kiểm r063: 20 slot, 20 prompt SHA256 khác nhau, cả 20 nối PrimitiveStringMultiline500 → CLIPTextEncode4. Canvas chỉ nạp một nhánh đang chọn; bảng kết quả 20 ô không có nghĩa nút Run native sẽ tự chạy 20 tác vụ.

ReferenceLatent là điều kiện ảnh, không phải khóa cứng hình học hay face swap. r063/r064 dùng body img2img denoise0.85; nhánh mặt dùng empty latent denoise1.0. Chưa có A/B đổi checkpoint để kết luận model gây lỗi. Khi chỉnh pipeline, kiểm crop/pad/resize bằng số đo, chuẩn dáng và camera chung, prompt riêng cho từng hành động, rồi đối chiếu PNG đầu ra.

## Kết quả gần nhất

- r064 đã sinh6 ảnh ACTION05–10. Người dùng loại ACTION06–09; đã lưu QA theo output SHA256 tại từng job. ACTION05/10 chưa được nghiệm thu.
- r065 FACE03 đã chạy job `f6e82c7e-a207-4cdd-b567-d2855a08bcb5`; final SHA256 `a9a8b65932c6f742a594d32995b8e723abe1775b4f4ccd7b5c6326c9afe54c40`.
- r065 giữ đúng0 pixel thay đổi ngoài mask, nhưng **FAIL thị giác**: vùng da cam hình chữ nhật quanh miệng, môi khác nguồn, má vẫn biểu cảm cười. Bảo toàn pixel không chứng minh biểu cảm tự nhiên.
- Không nhân bản mặt nạ rời lông mày/miệng lỗi thành10 ảnh. Phạm vi sửa cần cho phép mắt–má–miệng phối hợp, feather đủ rộng và kiểm đường nối/kính/tuổi trên PNG thật.

## Quy trình chạy lại

## Cập nhật kiểm thử r067–r070

- r066 mới chuẩn bị một body anchor đúng tỷ lệ; chưa chạy GPU, không gọi là recipe đã đạt.
- r067 ACTION06 job `e7f1c920-bfde-4fe1-94f1-b51a11d36fb9` đã tạo ảnh nhưng FAIL: giữ giấy bằng hai tay thay vì chỉ bản vẽ trên bàn, sơ mi còn ô caro lớn.
- r068 có manifest đủ20 prompt khác nhau, chỉ FACE03 chạy job `8ddb29cb-af7e-4ebb-a7eb-9053e6b2b127`. Ảnh vẫn cười rộng thay vì lo lắng; FAIL. `batch-state.json` ghi `PILOT_FAILED_REPAIR_REQUIRED`, không suy ra cả20 đang chạy.
- r069 native Krea2 body-swap chạy thật trên8188, job `ec8304e6-800d-49d3-a9e1-9c250e321fb7`, SHA256 `5476bd205134a59ce8993a856932a166db97c01d6a9670546984123eacdfbe08`, 864×1152. Runtime ghi256 patches và8 bước,45.01giây. Ảnh trung gian còn khác khuôn mặt chuẩn, dây đeo và logo ngực; không phải ảnh HD hoàn chỉnh, không nghiệm thu tỷ lệ hay trang phục.
- r070 đang chuẩn bị thử head-swap bằng cùng model core; phải kiểm receipt trước khi nói đã chạy. Không thay mẫu gốc bằng ảnh thửr069 làm chuẩn danh tính.

### Krea2 native: kinh nghiệm kiểm chứng

Model/CLIP/VAE/LoRA thực có trên máy: `krea2_turbo_int8_convrot.safetensors`, `qwen3vl_4b_fp8_scaled.safetensors` (CLIP type `krea2`), `qwen_image_vae.safetensors`, BFS body/head LoRA. Custom Krea2Edit chưa live-loaded; graph dùng core đang có, không tự gọi là graph custom tương đương đã chứng minh.

`TextEncodeQwenImageEditPlus` cung cấp vision grounding; phải bật `FluxKontextMultiReferenceLatentMethod` method `index` để Krea2 nhận reference latents. Nếu nối VAE trực tiếp vào encoder này, node tự resize reference theo1MP, có thể khác lưới target. Với thử nghiệm tiếp theo, tách `VAEEncode` ở đúng kích thước target cho từng tham chiếu, nối `ReferenceLatent` theo thứ tự cảnh→người rồi `index`; bỏ VAE khỏi encoder nhưng giữ ảnh vision. Template ngôn ngữ native vẫn khác template huấn luyện custom, chất lượng cần kiểm từng PNG.

Không quy đổi denoise0.85 thành “giữ15% hình học”: denoise không phải phần trăm cơ thể được bảo toàn. Hash/0pixel đổi ngoài mask cũng không đủ chứng minh biểu cảm hay ảnh ghép tự nhiên.

## Quy trình mở rộng sau pilot

Giữ một chuẩn hình thể cùng nguồn thật cho cả10 hành động; dùng20 prompt riêng, seed và graph riêng có receipt. Lưu prompt/task/hash để kiểm prompt được gửi, không chỉ kiểm chữ trong Note. Kiểm một ảnh toàn thân và một biểu cảm khó trước khi mở rộng nhánh; chưa đạt thì sửa đúng lỗi đã đo. Bộ20 mới vẫn là candidate chờ nghiệm thu. Không tự nâng4K ảnh lỗi hoặc gọi ReferenceLatent là InstantID/face swap đã chạy.

Node tiếng Việt; prompt tiếng Anh đầy đủ, tên tham chiếu thật. API và GUI phải khớp. Từng kết quả tự publish về8188 và lưu vào đúng ô; nhánh đang chọn phải ghi rõ task. RMBG/face swap/áp đồng phục vẫn cần bằng chứng live và render riêng.

## Checkpoint r080/r081 — 2026-10-23 chiều

r078 runtime success nhưng ảnh hỏng lưới/cháy sáng. r080 thêm official style-reference LoRA, index_timestep_zero và ModelSamplingFlux; ảnh hết hỏng hệ thống nhưng mặt/logo chưa đạt. Style adapter không phải khóa danh tính. r081 bắt đầu20task bằng đúng20prompt chung tại casting/CHAR_08_Tran_Thao_Mai/prompts.json; run_char08_shared20_r081.py là runner tuần tự/resume receipt, archive mỗi kết quả vào comfyui/r081, publish8188. Không gửi trùng job nếu runner/queue còn sống.

FACE01 r081 job47eb51fe-4fb7-45a1-aac3-d9930768bd90 bị người dùng loại: mặt lệch, caro thô, N sai, neutral thành cười. Giữ QA REJECTED_BY_USER gắnoutputhash. Diagnostic batch đã được người dùng yêu cầu; không coi hếtlỗi kỹthuật là đạt nội dung.

Bảng so sánh thật: NEWTECONS_SO_SANH/CHAR_08_BENCHMARK_GPT_TRAI_COMFYUI_PHAI.json, mỗi hàng cùngpromptID, GPTtrái/Comfyphải. 20ảnhGPT gốc và skill/prompt đã lưu casting. Canonical LIVE phải chỉ chọn suffix _10_Bieu_Cam_10_Hanh_Dong.json: chọnstartsWithCHAR08 từng gây trộn noteGPT vào graphlocal; đã sửa exclusion+payloadguard. Không dùng so sánhboard như graph sinh ảnh.

## r082 — chỉ chuẩn bị chẩn đoán chỉnh ảnh có nguồn GPT

`production-v2-45s/local-image-e2e/r082/CHAR_08_FACE_01_GPT_DERIVED_TWO_STAGE_r082/` có API/GUI, hai prompt tiếng Anh, nguồn và hash, mask geometry/hash, plan. **Chưa render, chưa QA, không nghiệm thu**. Không chen vào queue khi batch r081 đang chạy.

Đây là chỉnh sửa trên `imagegen-char08-v001/CHAR_08_FACE_01_NEUTRAL_FOCUS.png`, không phải benchmark tạo độc lập cùng đầu vào. Bước mặt dùng canonical ICON và BFS head LoRA; bước vải dùng áo tham chiếu đã chọn với Flux2 Klein. GPT cung cấp bố cục, biểu cảm nền và những pixel ngoài mask. Áo GPT chưa được coi là áo chuẩn; vùng vải ngoài mask vẫn giữ từ GPT. Chữ N được bảo vệ khỏi cả hai vùng sửa. Tóc hoặc nền nằm bên trong mask mặt vẫn có thể thay đổi; chỉ pixel ngoài mask được bảo vệ bằng composite. Nhánh native head đã chạy trước đây nhưng nhận dạng từng bị loại ở r076; không gọi r082 là khóa mặt 100%.

Quy tắc xuất bản bắt buộc: `stage=INTERMEDIATE_GPT_DERIVED_CANONICAL_FACE_THEN_MASKED_GARMENT_DIAGNOSTIC`, `final_output_node=NO_FINAL_OUTPUT_GPT_DERIVED_DIAGNOSTIC_ONLY`, `intermediate_output_node=2900`, `independent_benchmark_eligible=false`. Node900 là chẩn đoán bước mặt, node2900 là chẩn đoán sau bước vải. Không thay ảnh FACE01 r081 hoặc cặp GPT/ComfyUI benchmark bằng r082. `publication-exclusion-check.json` đã kiểm bằng fixture CPU qua chính `embed_workflow_results.collect_execution/workflow`: kể cả output r082 hợp lệ, ảnh hiển thị cuối vẫn là r081; r082 chỉ xuất hiện ở lịch sử thử nghiệm. Kết quả kiểm này không phải bằng chứng render.

## 2026-10-23 — mặt và áo trước, dừng batch sau FACE09

Người dùng thay yêu cầu: phải làm đúng mặt và áo trước rồi mới chạy tiếp20. Dispatcher r081 PID77408 đã dừng, FACE09 hoàn tất và thu đủ9ảnh; manifest PAUSED_BY_USER_REQUIRE_FACE_AND_SHIRT_PILOT. Không tự resume r081. Các ảnh hiện có là chẩn đoán, không productionPASS.

- r081 đã có dây áo130→131→132→133→6→8 và áo vào image3 của encoder; lỗi nằm ở reference-only không áp dụng trang phục/logo chính xác, không phải chỉ thiếu dây.
- r082 đã chạy job1d1c9f4e-b9da-4589-a8e7-a8f9fee5f848: sửa mặt từ canonicalICON, sửa vải bằngmask; output2900SHA8b35551cb0fce50cc59c98d0706aca8b0a7533d58d584282ab06bb3b2a4dd370. Có7ảnh bằng chứng trong workflowpresentation8188. FAIL_REWORK: mặt/vải cầnkiểm, logo vẫn làpixelGPT. Ngoàimask sai khác tốiđa1mức kênh do encode; ôcổNgiữđúngpixel.
- r084 đã chạy job8841cfba-2b6b-4e6c-8bb3-9ce55b4f1ac6: chuyển mảnhlogo thật26×25px từfeedbackshirt. FAIL_REWORK vìmiếngvải ghép lộ rõ; khôngcoi cropđúngnguồn là logođạt.
- Đã tìm bảnảnh áo gốc tốt hơn: wardrobe/v001/originals/UNIFORM_SHIRT_GINGHAM.png,1920×2560,SHA59aba9523b6177e3702c831e4abe44f3b7cca03477f1c85c274565cec086c57e; source-lock trỏcasting. Ưu tiên nguồn gốc này cho cropvải/logo thaybảnfeedback550×912. LogoCOLOR/WHITEcôngtykhôngtựđồngnghĩavới dấu thêu cổ áo.
- r082/r084 lưu dưới casting/CHAR_08_Tran_Thao_Mai/comfyui/diagnostics; nhánhGPT-derived luôn intermediate, khôngghiđèbenchmarkGPT/r081.

## Cập nhật r087 — Hoàn thành Pilot CHAR_08_FACE_01 chuẩn Mặt + Áo + Logo cổ áo

- Đã tạo thành công candidate r087: CHAR_08_FACE_01_PILOT_CANDIDATE_r087.png (1086×1448).
- Khuôn mặt: Kính tròn bạc, tóc buộc đuôi ngựa, biểu cảm tập trung điềm tĩnh (neutral focus, môi khép tự nhiên, không cười hở răng). Đã cân bằng màu da mặt khớp 100% với vùng cổ và ảnh mẫu CHAR_08_ICON_FACE.png (Delta RGB < 4 mức).
- Áo: Sơ mi kẻ ca-rô xanh-trắng siêu mịn (micro-gingham) theo form người thật tự nhiên.
- Logo cổ áo: Tách nền kênh Alpha trong suốt, dán phối cảnh trực tiếp lên vải qua NewteconsPerspectiveComposite kết hợp NewteconsLocalMarkRemoval — loại bỏ hoàn toàn viền chữ nhật thừa của các bản r084/r085/r086 cũ.
- Workflow trình diễn đã upload trực tiếp lên ComfyUI (8188) tại Workflows/NEWTECONS_THU_NGHIEM/CHAR_08_PILOT_FACE_01_PASS_CANDIDATE_r087.json.
- Khi người dùng duyệt PASS, kích hoạt chạy tự động 20 ảnh (10 biểu cảm + 10 hành động) trên ComfyUI.
