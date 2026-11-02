# CHAR08 — nguồn, HD trước 4K, review độc lập và thời gian

## Kiểm thực V004 — trạng thái hiện hành 2026-10-25

Phần này thay các snapshot V002/V003 cũ về trạng thái chạy; đọc `production-local/comfyui-docker/PLAN.md` và receipt job cho diễn biến mới nhất.

- Workflow: `ComfyUI/user/default/workflows/NEWTECONS_3_MODELS_V004/CHAR_08_{FLUX1,KREA2,ZIMAGE}_HD_DRAFT_v004.json`.
- Krea2 job `958c69ba-1684-44d6-b0ac-48cc76a6da52`: success,346.126s,HD1536×2048. Astra: môi khép/cười nhẹ PASS; danh tính chính xác/logo UNKNOWN; Stage1 montage FAIL.
- Z-Image job `fbeb31a7-2931-4f9d-8b99-2df9f8dd7b42`: success,333.836s,HD1536×2048. Astra: final FAIL hở răng và hai dấu N; Stage1 montage/thẻ đeo FAIL.
- FLUX1 V004 job `7baab79f-fbab-44ce-b2fd-1e0803aab437`: success334.021s,không có cached nodes. Astra: Stage1 bị crop chân/giày, áo trơn và thẻ ở eo; final còn hé môi/thấy dải răng nhỏ. Một N đúng phía nhưng nét thêu và danh tính UNKNOWN. FinalHD1536×2048, chưa PASS.
- Preview E2E thực sau reload: ComfyUI hydrate graph nên thêm unconnected widget sockets và nhãn localized vào input/output; execution/export bỏ chúng. Fingerprint v2 coi khác graph. Đã sửa v3 để bỏ chính các field UI này, vẫn băm `widgets_values` và socket có link. Native migration chỉ xảy ra sau khi history `success`, API prompt hash, workflow key và graph export cùng khớp; migration đã được lưu bền vững. Krea2 sau reload khôi phục node Save/Preview `9,10,31,32,53,54`; preview ảnh cuối đúng1536×2048. Đã chuyển từng tab Z-Image, FLUX1 và thấy đúng preview image trên Save/Preview canvas. Evidence/hash: [preview browser E2E receipt](../../../../production-local/comfyui-docker/runtime-receipts/CHAR08_V004_PREVIEW_BROWSER_E2E_20261025.json). Hai test logic/lifecycle pass; read-only TS/JS reviews pass.
- Output archive theo nền tảng: `casting/CHAR_08_Tran_Thao_Mai/comfyui/benchmark-three-model-v004/`; mỗi model có 3 PNG hardlink gắn source hash, workflow gốc và receipt. Không tính hardlink là bản render mới.
- Gemini đề xuất Stage1 T2I adapter riêng vì prompt gốc gọi tên sheet/portrait nhưng Stage1 không nạp các file đó; bản gốc20prompts giữ nguyên. Báo cáo vòng đầu bịa FLUX split-panel; sau khi root chỉ ra sai pixel, agent đính chính. Chưa áp dụng prompt adapter/chuyển latent vào Stage2; phải tạo revision mới và ghi rõ prompt khác bản canonical.
- Full20 benchmark và160 ảnh vẫn chưa hoàn tất. Mẫu v004 đều là pilot ACTION03; thời gian toàn graph đã đo, không phải tốc độ standalone của model vì 3 model cùng có pipeline chung. Không có batch hay job nào đang chạy; 4K vẫn mute.
- Timer lấy từ execution_start/execution_success. Khi so tốc độ phải đọc cached_nodes và thời gian nạp model; không xếp hạng bằng tổng thời gian có điều kiện cache khác nhau.
- Stage1 T2I phải được lưu/xem riêng. Stage2 dùng GPT ACTION03 làm latent, áo làm tham chiếu; Stage3 Krea2/BFS head_swap dùng FACE08 cuối chuỗi,ref_boost4. Final là GPT-reference-derived common-module edit; không gọi là thắng benchmark model nền.
- `ref_boost_mask` của node Krea2 hiện cài điều khiển attention trên ảnh tham chiếu cuối, không phải mặt nạ inpaint. `ref_boost=1` không thêm bias. Trigger head_swap và boost4 đã thử, không bảo đảm biểu cảm/nhận dạng.
- Fingerprint journal mới hiện là v3. Current V004 workflow không mang expected fingerprint trong metadata, nên đã kiểm pass. Một graph cũ có expected fingerprint v2 sẽ chưa khớp khi hydrate; mở lại/đoạn legacy migration cần đối chiếu workflow key/hash thật trước khi dùng. Không hạ hàng rào graph identity để cho các workflow cũ hiện ảnh.
- Giữ20prompt gốc và GPT originals. Nếu bổ sung prompt adapter T2I để bỏ chỉ dẫn bố cục sheet, lưu bản/hash riêng và ghi đây là tối ưu prompt, không giả cùng prompt gốc.
- SeedVR2 3072×4096 vẫn mute vì HD chưa đạt đầy đủ. Không upscale bản FAIL/UNKNOWN hoặc tự mở batch20 từ technical success.

Evidence ở `production-local/comfyui-docker/runtime-receipts/`: mỗi job có queued-prompt/history/result-summary; `Q2_V004_REVIEW_20261025.md`, `Q2_ZIMAGE_V004_REVIEW_20261025.md`, `F2_EXPRESSION_FIX_AUDIT.md`, `CHAR08_V004_SHARED_RECIPE.json`. Lesson: tên workflow, prose lock, nguồn ảnh hiện được và tests giả lập không thay execution + PNG QA + browser reload thực.

## V006R2 FACE01 — so ảnh neo, HD và 4K, 2026-10-25

- User anchor `CHAR_08_BODY_POSE_APPROVED_V006_REFERENCE.png`,SHA256 `8a08dbe63c559eb6fb8ddb482dfc214eb41b1f7085e9ab41913ea1998136fcb8`, là chuẩn face/body/áo/dáng. Astra đối chiếu trực tiếp [ảnh FACE01 4K](../../../../production-local/comfyui-docker/runtime-receipts/Q2_KREA2_V006R2_FACE01_4K_REVIEW_20261025.md).
- V6R2 FACE01 HD job `2d71df8f-fb52-4f00-9c22-863d10191d3f` →1536×2048; user request Stage4 job `444e5903-06c8-44fb-b45b-db635f763ac9`→3072×4096. Astra visual FAIL: prompt neutral nhưng lộ răng; caro áo thô/không đều; N to, nét đan sai. Kính/tóc có mặt nhưng identity/logo không đạt chuẩn. User cũng báo mặt/áo khác anchor và muốn thấy cả output mặt lẫn toàn thân.
- V4 giữ mặt/áo tốt hơn vì Stage2 khởi tạo từ GPT-derived body image; V6 thay ảnh latent đó bằng T2I mới, rồi chỉ dùng Krea2 reference conditioning. Reference boost không phải khóa pixel/identity; Krea tự đổi mặt, màu/vân áo và logo.
- 4K canvas route hiện nối Save/Preview stage4 từ ảnh portrait FACE stage3. Workflow có fullbody stage2 Save/Preview HD riêng nhưng không có fullbody4K branch. Đây là lý do chỉ thấy một ảnh trong đầu ra 4K. Screenshot 4K duy nhất không chứng minh đầu ra toàn thân.
- 4K job chạy lại toàn graph upstream vì các stage1–3 vẫn active. File SHA của HD00002 khác HD00001 do PNG metadata/encoding nhưng Astra xác minh ảnh RGB giải mã giống từng byte, 0 khác biệt (`22c6a9ce9dbe3aed72bbfba32fc7a3d23592389e97fc460460fc60c735e6d356`). 4K giữ nguyên các lỗi sẵn có từ HD, không sửa chúng.
- Queue dừng sau FACE01; FACE02–FACE10 chưa gửi. V006R2 4K không được chấp nhận. Khi tiếp tục, tạo riêng hai Save/Preview đầu ra (portrait-face và fullbody), neo trực tiếp vào body/face V4, và Stage4-only phải LoadImage đúng PNG HD đã ghi hash để không chạy lại Stage1–3. Fullbody gốc có thể lưu nguyên bản thay vì vẽ lại glyph N; nếu 4K toàn thân được yêu cầu, đó là nhánh riêng và phải QA riêng.
- Thu dọn phiên game: `/free` được xác nhận, queue0, Comfyui-Studio container tạm dừng. Hệ thống có33.8GiB RAM tự do lúc kiểm; container cần được khởi động lại để mở8188 khi người dùng resume.

Yêu cầu người dùng ngày 2026-10-25, áp dụng cho Flux1 Turbo, Krea2 Turbo và Z-Image Turbo. Đây là hợp đồng chạy; không phải tuyên bố ba model đã đạt.

## Nguồn cho mẫu tiếp theo

Root: `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/casting/CHAR_08_Tran_Thao_Mai/`.

- Mặt/biểu cảm: `gpt/v001/images/CHAR_08_FACE_08_DETERMINATION.png`. Quan sát trực tiếp: môi khép, nụ cười nhẹ, kính tròn mảnh, tóc buộc đuôi ngựa; không suy biểu cảm cau giận từ tên file.
- Dáng: `gpt/v001/images/CHAR_08_ACTION_03_WALK_INSPECTION.png`. Toàn thân bước về phía máy ảnh, hai tay trống, quần navy và giày đen mũi nhọn. Không thêm tablet/tài liệu.
- Trang phục: `references/SHIRT_APPROVED_FINE_GRID_COLLAR_LOGO_REFERENCE.png`; ảnh dẫn xuất phải giữ lineage/hash. Lưới xanh-trắng rất mịn, dấu N nhỏ theo mẫu ở cổ bên phải ảnh. Logo trong ảnh mặt GPT không tự thay thế chuẩn áo gốc.
- Pilot `CHAR_08_PILOT_FULL_CLEAN_V2.png` giữ làm lịch sử; không âm thầm thay nguồn mặt mới người dùng vừa chỉ định.

Đủ 20 PNG trong `gpt/v001/images/` chỉ chứng minh có file. Ghép từng ảnh với prompt ID/hash; kiểm nội dung riêng. Không dùng ảnh người dùng đã loại làm donor. Khi dùng GPT làm nguồn xử lý, ghi rõ reference-assisted; không gọi là so sánh độc lập cùng đầu vào hoặc training model.

## Kết nối thực và provenance

Graph Krea2 đầu tiên (job `ff0d3b81-6870-4b3e-a90a-e43b00f0b789`) đã render nhưng không đạt. Stage3 dùng CLIPTextEncode và thiếu reference method; không được dùng làm recipe đã khóa mặt. Krea2 mặc định `default_ref_method=None`; kiểm mã nguồn và schema runtime thay vì tin tên node.

Recipe sửa đang cần chạy kiểm: TextEncodeQwenImageEditPlus nhận ảnh cảnh và mặt theo thứ tự; ReferenceLatent theo cùng thứ tự; FluxKontextMultiReferenceLatentMethod=`index`. Không đồng thời thêm latent qua VAE của encoder và thêm lại explicit ReferenceLatent. Có conditioning đúng vẫn không bảo đảm giống mặt; phải xem PNG.

Giữ đường T2I thật cho benchmark model nền. Nhánh dùng ảnh GPT trực tiếp làm thân rồi sửa mặt phải ghi là reference-guided edit, không đổi nhãn thành T2I. Lưu đầu ra từng bước để phân biệt lỗi model nền với lỗi module sửa chung.

## Điểm dừng review

Run bản nháp: tạo/sửa → SaveImage + PreviewImage HD. 1152×1536 là bản chẩn đoán nhanh, chưa đạt chuẩn HD giao 1536×2048 trong hợp đồng sản xuất. Người dùng phải thấy rõ bản nháp trước upscale.

GUI mặc định vô hiệu hóa toàn bộ nhánh SeedVR2 bằng mode=2. API draft không chứa node upscale/output 4K; mode GUI không tự bảo vệ API gửi trực tiếp. Sau PASS cho đúng hash ảnh mới được upscale. Giữ seed và nguồn không đổi hoặc nạp chính PNG HD đã duyệt, tránh tái tạo ảnh khác khi chạy nhánh 4K. Đích 3072×4096, kiểm lại kích thước PNG và chất lượng sau upscale.

## Review độc lập

Builder không tự nghiệm thu. Reviewer khác xem file đầu ra cùng ảnh gốc: mặt/kính/tóc, biểu cảm, dáng/tỷ lệ/tay/chân, vải áo, vị trí/hình N và độ tự nhiên. Ghi PASS/FAIL/UNKNOWN từng tiêu chí, bằng chứng nhìn thấy và lỗi lớn nhất; chữ/logo quá nhỏ để đọc là UNKNOWN. Không suy quốc tịch từ ảnh; kiểm nhân vật theo brief và mẫu đã chọn. Không bịa phần trăm giống GPT.

## Timer và so sánh

Mỗi run lưu prompt ID/hash, nguồn/hash, API+GUI đã thực thi, job ID, model/LoRA, seed, resolution, output hash, queue/dispatch/start/end và thời lượng. Dùng history cho execution total; WebSocket/log theo node cho từng bước nếu thu được. Thiếu dữ liệu ghi null, không ước lượng thành số đo.

Tách T2I từng model, sửa áo, sửa mặt, upscale. Ghi cache nodes, lần nạp model, warm/cold/unknown và lỗi/retry. Ba model chạy cuốn chiếu trên cùng GPU; không so tổng khác số bước/resolution rồi kết luận model nhanh hơn. Chỉ sau đủ mẫu cùng cấu hình mới lập xếp hạng tốc độ và chất lượng.

## Hai phép kiểm khác nhau

Benchmark 20 ảnh phải dùng nguyên văn từng prompt trong `prompts.json`, đúng prompt ID/hash của GPT. Không thay bằng20 seed của một prompt. Prompt kỹ thuật sửa mặt/áo là cấu hình adapter riêng, phải lưu minh bạch và dùng chung giữa ba route. Thay prompt nội dung thì tạo revision chung mới và không gọi là cùng prompt với GPTv001. Mẫu kết hợp FACE08 + ACTION03 để kiểm module tham chiếu không tính vào20 ảnh benchmark.

## Bằng chứng chạy mới và giới hạn

Job `800eb9ac-64b8-4b81-8421-f83234a67e81` thực thi thành công trên8188, history ghi **158.032 giây**, không có node được cache. API/GUI thực thi và sự kiện WebSocket lưu ở `comfyui/three-models-v001/krea2/runs/hd-fabf1d5a084f42bbba422bf18a19ef09/` dưới thư mục nhân vật. PNG `CHAR_08_KREA2_HD_V003_FACE08_ACTION03_REVIEW_00001_.png` là1152×1536. Đây là sửa ảnh có tham chiếu, không phải T2I benchmark.

Review Astra độc lập: **FAIL biểu cảm** (vẫn hở răng theo ACTION03, FACE08 môi khép); dáng phù hợp; vải áo gần mẫu về hình thức; logo **UNKNOWN** vì quá nhỏ để nghiệm thu. Không upscale hoặc gọi PASS. Sửa tiếp cần xem crop mặt đủ lớn và bảo toàn cổ áo/dáng.

Job API dùng client_id riêng không tự đồng bộ executed event lên canvas khác. Nhìn History có ảnh không chứng minh PreviewImage trên canvas đã nhận ảnh. Cổng giao nhận phải kiểm bằng UI thật: ảnh từng bước, đúng job/graph, mở lại workflow; snapshot LoadImage có nhãn rõ chỉ là fallback xem lịch sử, không thay nhánh sinh ảnh. Đồng bộ live đang sửa, chưa có bằng chứng E2E tại checkpoint này.

## Canvas preview repair — kiểm tra thực tế 2026-10-25

Lỗi trong ảnh người dùng gửi là `Image does not exist` tại PreviewImage vì journal giữ file `ComfyUI_temp_*` kiểu `temp`; kiểm tra HEAD trên8188 cho thấy Preview32 và Preview54 trả404 sau khi container restart, trong khi SaveImage31/53 trả200. Root đã cập nhật journal hiện tại trỏ Preview32→ảnh output bền vững của Save31 và Preview54→ảnh output bền vững của Save53, ghi rõ `display_source_nodes` và giữ nguyên history thực thi. Đây là đồng bộ hiển thị cùng ảnh đã lưu, không chạy inference mới.

Bằng chứng E2E: extension được phục vụ tại `/extensions/newtecons_live_preview/live_preview.js`, console ghi `Initialized native store live preview polling`; Chrome đã reload trang ComfyUI và native canvas node54 (`node-body-54`) có ảnh `CHAR_08_KREA2_HD_V003_FACE08_ACTION03_REVIEW_00001_.png`, 1152×1536, `complete=true`, từ URL `/api/view?...&type=output`. Node32 cũng nạp stage output bền vững. Ảnh chụp giao diện: `production-local/comfyui-docker/live-preview-fixed-20261025.png`; DOM evidence: `live-preview-dom-evidence-20261025.json`. Đây chứng minh candidate hiện tại còn mở được sau reload, không chứng minh API runner các job tương lai đã hoàn tất tự động map.

Runner mapping bền vững đã triển khai trong `run_timed_hd.py`; native UI Run giờ ghi prompt ID, output descriptor, trạng thái và timer theo graph fingerprint. Cả hai đường dùng cùng journal display schema, native/API fingerprints riêng. Lý thuyết và lifecycle harness đã PASS; chưa có post-change GPU run.

## Automatic persistent preview mapping in runner — 2026-10-25

DeepSeek completed `production-local/comfyui-docker/run_timed_hd.py`: API PreviewImage nodes are matched to SaveImage nodes using the exact same serialized API `images` connection. The journal hydrates the PreviewImage entry with the persistent output descriptor when available, whether the Save or Preview event arrives first and even if the Preview event is omitted. A temporary preview remains only as fallback until a matching SaveImage output exists. Raw event/history outputs are kept separately, and display provenance identifies the paired node and selected descriptor.

Validation: `py_compile` passed; focused in-memory checks passed for source mapping, Save-only hydration, Preview-first then Save replacement, late Preview update, missing persistent output fallback, and mismatched source isolation. No new inference was submitted. Thus code path has focused functional coverage; no post-change GPU job has yet demonstrated delivery after a fresh inference. Astra has independently reviewed the current static graphs and ledger logic; actual GPU rendering and image QA remain pending.

## Kiểm kê nhánh T2I trong ba graph v002 — 2026-10-25

Đọc ba file GUI đã lưu trong `ComfyUI/user/default/workflows/NEWTECONS_3_MODELS/`: `CHAR_08_FLUX1_4K_MASTER_v002.json`, `CHAR_08_KREA2_4K_MASTER_v002.json`, `CHAR_08_ZIMAGE_4K_MASTER_v002.json`. Cả ba đều có nhánh Text-to-Image đang nối tới output Stage1 (EmptySD3LatentImage + CLIPTextEncode + KSampler + SaveImage/PreviewImage). Nhánh này tiếp tục vào Stage2 thay áo và Stage3 khóa nhận dạng/ảnh HD, mỗi bước có SaveImage và PreviewImage riêng. Toàn bộ nhánh 4K 69/70 đang mute. Vì vậy một lần Run có thể tạo base T2I, ảnh sau áp dụng áo, và bản HD sau tham chiếu; đây là T2I đầu vào cộng edit có tham chiếu ở các bước sau, không được gọi toàn bộ ảnh cuối là pure T2I.

Ba graph dùng khóa riêng `CHAR_08_FLUX1_DEV_TURBO`, `CHAR_08_KREA2_TURBO`, `CHAR_08_ZIMAGE_TURBO`. Native UI ledger dùng graph fingerprint tự tính cho v002 không có recipe_fingerprint; API journal tiếp tục dùng recipe_fingerprint nguyên nghĩa.

Tình trạng model: ba graph v002 đã mở trong Chrome sau hard reload và queue đang rỗng. Chưa có benchmark inference mới. Krea2 diagnostic cũ là FAIL biểu cảm; Flux1 và Z-Image chưa chạy. Người dùng sẽ bấm Run theo thứ tự Flux1, Krea2, Z-Image.

## Graph prep for user-driven 3-model E2E — 2026-10-25

The three saved `v002` GUI workflows are now prepared as one consistent pipeline: Stage1 is true text-to-image using exact shared `CHAR_08_ACTION_03_WALK_INSPECTION` prompt (SHA256 `dc9e1addf5a13b9a5b320222e35a5264a59d19ca541a839dc3cd28bf549ee59b`); Stage1 retains its own Save/Preview output. Stage2 keeps the generated base, loads the actual `CHAR_08_ACTION_03_WALK_INSPECTION.png` pose image and approved shirt image, encodes the pose anchor and chains it with the shirt `ReferenceLatent` into Klein conditioning. Stage3 loads `CHAR_08_FACE_08_DETERMINATION.png` as the identity/expression anchor and writes a separate HD candidate. The full graph keeps the 4K branch in mode=2.

Each graph has a hash-verified pre-edit backup in `production-local/comfyui-docker/runtime-receipts/graph-backups/`. Node input/output socket types and link types were regenerated from live `/object_info`; all 3 graphs pass schema/link integrity validation (0 mismatches; Flux1 52 nodes/66 links, Krea2 53/65, Z-Image 53/65). Repair receipt/hash manifest is in `production-local/comfyui-docker/runtime-receipts/CHAR08_3MODELS_E2E_REFERENCE_REPAIR_20261025.json`; reproducible repair script is `production-local/comfyui-docker/prepare_char08_v002_e2e.py`.

No GPU inference has been submitted from these updated graph files. Live browser reload and opening of all three updated graphs are now confirmed; the actual three model runs and image review remain pending. The user can press Run sequentially. Do not report the benchmark complete before outputs and QA.


### E2E chuẩn bị ba graph đã hoàn tất — 2026-10-25

- Flux1, Krea2 và Z-Image v002 hiện được mở trong ComfyUI, queue trống. Chrome đã tải lại extension mới; log ghi Native UI run ledger active. Node FACE08/ACTION03/áo hiển thị đúng; Stage1 T2I, Stage2 reference edit, Stage3 HD; 4K muted.
- Runtime UI xác nhận Z-Image CLIPLoader type lumina2; KSampler có seed control 
ixed; output HD 1152×1536. Ba lượt GPU mới chưa chạy; người dùng sẽ bấm Run lần lượt.
- Tests: `test_live_preview_logic.mjs` PASS; `test_live_preview_lifecycle.mjs` PASS; node syntax PASS; 3 workflow graphs validate against live `/object_info` with 0 schema/link errors.
- Graph backup ở production-local/comfyui-docker/runtime-receipts/graph-backups/; receipt ở production-local/comfyui-docker/runtime-receipts/CHAR08_3MODELS_E2E_REFERENCE_REPAIR_20261025.json.

## Final UI preflight and archive state — 2026-10-25

The published v002 graphs were opened in ComfyUI after the browser hard reload. The Flux1 and Krea2 canvases visibly show Stage2 ACTION03/shirt inputs and Stage3 FACE08; the Z-Image graph shows CLIPLoader type `lumina2`. ComfyUI canvas exposes Fixed Value controls for the KSamplers. All three graphs keep HD outputs active and 4K nodes muted; queue shows 0 active. The native-run extension console logs initialization on the reloaded page; both served JS modules return HTTP 200 and match their local SHA256.

All previous duplicate master and diagnostic graph JSONs were moved out of the active `NEWTECONS_3_MODELS` folder into `NEWTECONS_3_MODELS_ARCHIVE_20261025`; the active folder now lists only Flux1, Krea2 and Z-Image v002. This is a reversible archive move. Backups for the repaired three v002 graphs live outside ComfyUI's workflow scan directory at `production-local/comfyui-docker/runtime-receipts/graph-backups/`.

Static verification: three node/link graphs checked against live `/object_info`, 0 socket/link mismatches; shared T2I prompt SHA256 is `dc9e1addf5a13b9a5b320222e35a5264a59d19ca541a839dc3cd28bf549ee59b`; KSampler `fixed` widget is present; all reference files exist in ComfyUI input. `test_live_preview_logic.mjs`, `test_live_preview_lifecycle.mjs`, and Node syntax checks pass. TypeScript reviewer approves the current extension; Astra approves workflow structure and live-journal logic in the reviewed scope.

No new ComfyUI GPU inference has been submitted. The three workflows are open and ready for the user's sequential Run: Flux1 (currently selected), Krea2, then Z-Image. Each run produces the text-only T2I base, its reference-guided garment/pose edit, and a FACE08 HD draft. The E2E uses one shared ACTION03 prompt, not the full set of20 prompts. Image quality, timer comparison across real runs, the 20-image benchmark, and user acceptance remain pending. Keep 4K muted until the user reviews/passes the matching HD result.


