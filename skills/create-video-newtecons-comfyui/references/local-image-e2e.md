# E2E ảnh NEWTECONS local và so sánh mẫu GPT

Yêu cầu hiện hành: tự chạy pipeline ảnh đến bộ 8 CHAR × 10 biểu cảm + 10 hành động = 160 PNG riêng bằng ComfyUI RTX5080. Tạo và áp dụng trang phục; so sánh đúng task với các ảnh GPT lịch sử có thật; lưu workflow/seed/prompt/ref/model/output hash/job ID và bảng xem. Người dùng nghiệm thu sau; ảnh mới là candidate chờ nghiệm thu, không tự ghi USER_APPROVED.

**Ghi đè mới — chữ thêu chính xác từng ký tự:** dùng `production-local/character-library/newtecons/wardrobe/v001/vest-lettering-contract-v001.json`. Chữ bộ phận bên trái ảnh gile phải đúng 100% từng chữ cái, khoảng cách từ và dấu tiếng Việt theo mapping CHAR. Chuỗi chuẩn NFC: `KHỐI KỸ THUẬT`, `BCH`, `SITE MANAGER`, `PHÒNG THIẾT BỊ`. Prompt phải nêu nguyên chuỗi và cấm thiếu/đổi dấu, thay ký tự, viết tắt, lật gương, chữ trên túi. Không giao diffusion viết chữ cuối: chữ cuối dùng Unicode/font đủ glyph và brand gốc. So từng codepoint của nguồn chữ, rồi kiểm crop ảnh cuối ở độ phân giải lưu: đúng chuỗi nguồn chưa chứng minh chữ trên ảnh rõ/đủ. Bất kỳ ký tự/dấu bị sai, thiếu, khó đọc hoặc không kiểm được đều FAIL/PENDING, không chấm PASS hay tính hoàn tất. R006 hai pilot CHAR03 đã có PNG nhưng **FAIL chữ**, chưa tính ảnh hoàn thành. Sửa bằng nhánh mask/composite, giữ mặt/tư thế ngoài vùng sửa; không tự nghiệm thu vì prompt ghi100%.

## Trạng thái thật và đường dẫn

Pack: `production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/production-v2-45s/`. r005 là 160 prompt sửa áo/cổ/logo, chưa phải ảnh đã sinh. Thư viện trang phục `production-local/character-library/newtecons/wardrobe/v001/`; registry hiện chứa 7 mã, 11 view dự kiến, không chứng minh đã tạo đủ.

ComfyUI local: `http://127.0.0.1:8188`. Người dùng đã cho dừng video: `local-image-route/flux2-klein4b-v001/user-authorized-video-stop.json` và `queue-preserved-snapshot.json` giữ queue/graph cũ. 5 pending đã xóa đúng ID; H3 không nhả GPU sau interrupt nên process riêng của ComfyUI được khởi động lại. Bỏ `--highvram`, dùng chế độ mặc định bản cài và `--reserve-vram 1`. Bản hiện tại không có cờ `--normalvram`. Không dừng VoiceStudio hoặc mọi process Python.

Worker ảnh hiện hành dùng endpoint chuẩn **`http://127.0.0.1:8188`** sau khi người dùng khởi động lại. Đường 8189 chỉ còn trong receipt/snapshot lịch sử; giữ nguyên bằng chứng đã chạy, không sửa endpoint receipt cũ và không mở worker thứ hai. Kiểm `/object_info` thực trước dispatch. Xem [workflow ảnh–video dùng chung](../../comfyui-video-pipeline/references/image-video-linked-workflows.md) cho mô tả đầy đủ, tên node tiếng Việt, prompt Anh, backup và frame carry.

Một route ảnh đã chạy thật: Flux2 Klein4B distilled FP8, Qwen3 4B text encoder CPU, native Klein BF16 VAE. Ba weights có receipt SHA256/revision ở `local-image-route/flux2-klein4b-v001/model-download-receipts.json`. Không cần tải lại hay cài toàn bộ template swap. Bốn graph đầu đã được queue thực và có PNG/receipt/history trong cùng thư mục: shirt, equipment vest, CHAR03 face và action. Job thành công kỹ thuật nhưng vest/character vẫn có lỗi chữ/logo/túi; không nâng lên canon hay batch cùng recipe mà không sửa. Shirt có lưới nhỏ và logo cổ, vẫn cần so với nguồn đúng hash.

V002 thử giữ hình học áo gốc bằng một tham chiếu lớn, xóa chữ/logo trước rồi đặt brand gốc và chữ Việt bằng nhánh local xác định. Custom node `production-local/ComfyUI/custom_nodes/newtecons_branding/` cung cấp Unicode Arial Bold và perspective compositing. Core TextOverlay dùng PIL default font thiếu glyph Việt, đã kiểm Ế/Ị trùng missing glyph. Custom compositor nhận mask 1=visible; LoadImage MASK là 1=transparent, phải InvertMask trước đặt logo. Quad theo vòng chu vi, lồi, không tự cắt; kiểm thử che alpha và giữ nguyên pixel ngoài vùng chỉnh. Chỉ restart Comfy khi queue trống để nạp custom node.

## Trình tự thực thi và bằng chứng E2E

1. Đếm lại PNG/receipt/hash/queue; bảo toàn 35 ảnh nhân vật cũ và ảnh scene. Không retry OpenRouter402. Gemini Flash đã trả503 hai lần; không ghi đã làm review khi route chưa chạy.
2. Tạo/kiểm bộ sơ mi mịn có logo cổ, nón, gile KKT/BCH/SITE MANAGER/PHÒNG THIẾT BỊ trước/sau, suit. Không để model vẽ lại chữ/logo sau khi đã có nguồn gốc. So nguyên hình học mesh/túi/dải cam-bạc với ảnh gốc; cấm logo túi. Mặt sau lấy nguồn thật. Mọi asset có view/ID/hash/QA nội bộ và trạng thái người dùng chưa nghiệm thu.
3. Pilot một sửa áo giữ mặt và một action: dùng master riêng mỗi CHAR, refs quần áo và nội thất thực. Khi chỉ sửa trang phục, bảo toàn mặt/tóc ngoài mask bằng composite pixel có kiểm khác biệt; prompt giữ mặt không phải chứng minh. Với biểu cảm/hành động mới phải kiểm danh tính theo master, không dùng mặt GPT lịch sử lỗi làm chuẩn ưu tiên.
4. Sau pilot nội bộ đủ tốt, lập revision mới có 160 task riêng, nguồn/wardrobe binding rõ. Chạy từng job GPU tuần tự. Mỗi task lưu `workflow.api.json`, `workflow.gui.json`, request thực, prompt_id server, history, PNG thật và SHA256. Helper pack `comfy_workflow.py` xuất hai graph từ schema, từ chối ghi đè khác nội dung. Không đổi tên ảnh r003 thành revision mới.
5. Recovery dựa receipt: đã có prompt_id thì đọc queue/history trước, không submit lại. HTTP timeout/không rõ kết quả thì trạng thái uncertain, dừng dispatch đến khi đối chiếu. Lỗi kỹ thuật có history failure; sửa recipe rồi tạo revision/attempt mới, giữ receipt cũ. Một batch chạy tuần tự không nuốt lỗi hoặc báo đủ khi thiếu PNG.
6. So sánh theo character/kind/index/code sau khi bỏ đúng hậu tố revision. Chỉ dùng baseline PNG có receipt/hash khớp; ghi đúng provenance OpenRouter/built-in backend unknown, không gọi mọi ảnh là GPT Image2. 26 r003 + 1 r002 + 8 legacy là nguồn so sánh lịch sử, không phải 160 ảnh chuẩn. Task thiếu mẫu ghi rõ NO_GPT_BASELINE; không nhân một ảnh mẫu thành 20 ảnh hay tự tạo baseline.
7. Bảng đối chiếu local/GPT phải link ảnh vật lý, receipt/job/hash, trang phục/nhận diện/biểu cảm/hành động và lỗi cần xem. Có tổng số task thực sinh, thiếu, lỗi, QA pending. Nghiệm thu cuối thuộc người dùng; technical pass không nâng USER_APPROVED. Không bắt đầu H3 video trong goal ảnh.

## Đóng goal

Chỉ đóng khi đủ 160 PNG riêng đúng manifest có provenance và áp dụng trang phục, có bộ trang phục/ánh xạ thay thế cho ảnh sai, có kiểm E2E chạy thật và bảng đối chiếu baseline thật, skill đã cập nhật. Đủ prompt, graph hợp schema, job trả success hoặc một pilot có PNG không chứng minh hoàn tất. Kiểm từng điều kiện trên hiện trạng; goal còn active nếu còn hạng mục thiếu. Không yêu cầu người dùng nghiệm thu ngay để hoàn thành phần giao artifact chờ review.

## CLI đã triển khai và kiểm

Chạy từ pack bằng Python của ComfyUI `.venv/Scripts/python.exe`:

```powershell
python -X utf8 run_comfy_local_job.py <new-prepared-job-folder> --endpoint http://127.0.0.1:8188
python -X utf8 build_local_gpt_comparison.py --manifest image-requests-160-r005.json
python -X utf8 -m unittest test_comfy_local_job test_local_wardrobe_plan -v
```

Runner chỉ chạy/resume **một** graph đã lưu và `pilot-plan.json` có tham chiếu/hash thật; không tự chuẩn bị 160 graph hay ngụ ý lệnh pilot đã chạy toàn bộ goal. Có receipt/prompt_id thì đọc history/queue, không gửi trùng. Kiểm hash graph trước POST; nếu job biến mất khỏi queue thì đọc history lần nữa để tránh race completion. Gửi đúng bytes của payload đã lưu, giữ HTTP error body. Graph chỉ dùng node local; path ảnh đầu ra phải nằm trong Comfy output. File ảnh mới có hash, kích thước, receipt/job thật, trạng thái `GENERATED_REVIEW_PENDING`.

`build_local_gpt_comparison.py` xuất bảng tại `http://127.0.0.1:5050/model-review/newtecons-local-vs-gpt/` và manifest JSON. Snapshot khởi tạo: 35 PNG GPT lịch sử hash khớp, tương ứng **32 task duy nhất**; 128 task chưa có baseline cùng task. Chưa có local-index production thì trang ghi đúng 0/160 local, không tính pilot/wardrobe vào 160. Cập nhật `local-image-e2e/local-index.json` bằng output/receipt hợp lệ khi có ảnh production rồi rebuild; script kiểm hash output + prompt_id, không tự nghiệm thu.

## Kiểm chữ cuối đã triển khai — snapshot r007

Đọc [prompt kiểm từng ký tự](final-lettering-qa.vi.md). Pack có `local-image-e2e/lettering-requirements-v001/requirements-160.json` cùng 160 file QA prompt riêng, gắn hash hợp đồng và prompt. 96 task theo manifest r005 mặc gile; các task văn phòng/suit còn lại không tự thêm chữ/gile. Đây là yêu cầu kiểm, không phải 160 ảnh đã sinh.

`verify_final_lettering.py` kiểm request bytes/hash và graph, history/job ID/status/output node/filename, hash PNG và crop đúng từng pixel từ ảnh cuối; xác minh các text node thực nằm trên nhánh tạo ảnh cuối. Không có observation đọc ảnh thật thì luôn PENDING. Observation phải gắn task/PNG/crop hashes và có một hàng cho từng ký tự/khoảng trắng, boolean nhìn rõ thực; sai chữ/dấu/case/khoảng trắng hoặc một ký tự không rõ đều không đạt. Công cụ này không tự chấm nhận diện/diễn xuất hoặc nghiệm thu; `counts_as_completed_production_image` luôn false trong báo cáo chữ riêng.

```powershell
python -X utf8 -m unittest test_final_lettering -v
python -X utf8 verify_final_lettering.py local-image-e2e/r007/CHAR_03_ACTION_09_RADIO_REPORT_r007 --observation local-image-e2e/r007/CHAR_03_ACTION_09_RADIO_REPORT_r007/optical-observation-v001.json --output local-image-e2e/r007/CHAR_03_ACTION_09_RADIO_REPORT_r007/strict-final-lettering-qa-v001.json
```

14 test đã pass, gồm regression job giả/graph khác/crop sai/ảnh đổi/hash observation sai; code-reviewer và Python-reviewer đã kiểm lại sau sửa và APPROVE. Đây là bằng chứng cho validator, không phải 14 lần kiểm chất lượng ảnh đạt.

R008 đã có hai graph offline thử Tahoma Bold và node `NewteconsLocalMarkRemoval`, xóa nét chữ bằng vải lân cận và chỉ lấy alpha logo cổ gốc. Node có 8 test pass, hai reviewer APPROVE cho diagnostic; chưa chạy ảnh thật. Worker8189 vẫn nạp bản node cũ. Lệnh khởi động worker mới8190 bị tool auto-review từ chối (`blocked by policy`); không lặp launch/kill tương đương, không gửi graph thiếu node rồi gọi là E2E. Giữ graph/plan/hash và tìm cách thực thi hợp lệ, kiểm ảnh thật trước batch; snapshot runtime chi tiết trong handoff `2026-10-23-NEWTECONS-STRICT-LETTERING.md`.

Hai task CHAR03 r006 được sửa thành r007 bằng job thật, có PNG cuối node900 và diagnostics riêng. **Cả hai r007 chưa đạt:** ký tự cuối `Ị` có silhouette gần `!`, miếng vá xanh hình chữ nhật và vải cổ dán lộ, hình học dải cam/bạc còn chưa đúng nguồn. Giữ `FAIL_OR_UNREADABLE` / `FAIL_OR_UNVERIFIED`, không batch cùng recipe hoặc cộng vào bộ ảnh hoàn thành. Báo cáo `strict-final-lettering-qa-v001.json` và `outside-mask-preservation-v001.json` nằm trong từng task folder. Ngoài mask, pixel so với baseline Lanczos cùng graph giữ nguyên hoàn toàn (0 pixel khác); điều này không chứng minh nhận diện so với master hoặc trang phục đạt. 265 file lịch sử vẫn giữ nguyên SHA256. Bộ 160 ảnh còn chưa hoàn thành; goal ACTIVE, nghiệm thu người dùng PENDING.
