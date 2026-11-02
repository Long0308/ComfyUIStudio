# CHAR08 V007R5 — ComfyUI resumed, candidate review pending, 2026-10-26

**Current result:** Docker Engine/`Comfyui-Studio` restarted on user's request. `newtecons_branding` is now in the restricted custom-node whitelist. `/system_stats` healthy on RTX5080, local ComfyUI queue0/0 after jobs.

- V007R1–R3 miss-mouth failure was a coordinate bug, not missing Krea2 inpaint support: source mouth `(538,169)` maps to crop `(313,239)` after Lanczos resize to1536×2048 and crop x448; the old mask center was x259 and edited cheek.
- V007R4 prompt `9ab50adf-8890-4020-9800-4df999449f80` uses the corrected mask, Krea2+BFS head-swap LoRA, and produced a closed-lip raw crop. Its broad collar removal left a soft patch.
- V007R5 ComfyUI composite prompt `30156c02-ede9-4b83-bb47-23da19d4ce49` used R4 mouth crop, original V006 base, tight N cleanup and official N logo perspective overlay; **no diffusion sampler / no cloud**. Full-body1536×2048 SHA `c09dbbdf543512c23e7dbeb7e1bb4ff89f83b871cbcb6603c12a5ef1bdc8de62`; portrait768×1152 SHA `3a150314d355ab4019a6139a6edf6a73c72d9622741b33540ebf40914da28b71`. Exact ComfyUI Lanczos pixel check found0 changes outside mouth/collar masks.
- Gemini3.8Flash performed a scoped visual QA on R5: mouth/no-teeth, identity appearance, fine grid, N and seam all PASS internally. This is **not user acceptance**. Review: `http://127.0.0.1:5050/model-review/newtecons-45s-casting/char08-v007r5.html`.
- Stop before FACE02–10,20/160 batches, SeedVR2 or film integration until user reviews R5. Full wardrobe library, remaining cast images, voice, 45s video and 4K remain incomplete.
- Version clarification: `NEWTECONS_3_MODELS_V005` is an older diagnostic set of FLUX1/Krea2/Z-Image drafts, not a final or approved asset set. The old V006R2 Stage4 portrait job failed QA. R5 has not yet been processed by SeedVR2; no current Stage4 output exists.

## Historical snapshot — three-model benchmark and V006R2, 2026-10-25

## Trạng thái tiếp tục hiện hành — V004, kiểm lại 2026-10-25

Các checkpoint bên dưới là lịch sử; không dùng chúng thay trạng thái đã kiểm mới.

| ID | Owner | Scope / dependency | Acceptance / verify | Status |
|---|---|---|---|---|
| V2 | DeepSeek worker + root UI | `newtecons_live_preview`; actual Krea2 v004 journal/history and browser-exported graph | Native PreviewImage survives reload and remains bound to correct workflow; Node regression tests + browser images | complete: frontend adds unconnected widget sockets and localized port labels that API export omits; fingerprint v3 ignores only those UI-only fields, keeps widget values/connected sockets; Krea2 shown twice after reload; Z-Image and FLUX1 each restored after switching on same 8188 page; all final preview PNGs are 1536×2048 and match workflow prefix |
| F2 | Gemini + root | Installed Krea2 reference implementation + v004 builder | `ref_boost_mask` is reference attention, not inpaint; head_swap prefix + ref_boost4 tested, visual QA separate | source audit complete; Krea2 expression improved, Z-Image expression still FAIL |
| Q2 | Astra + code reviewers | Independent source/PNG checks | Separate runtime success, visual findings and user acceptance | all three reviewed: Krea2 closed-lip expression PASS, identity/logo UNKNOWN; FLUX1 final still shows a fine teeth line (FAIL strict closed-lips), one N count passes but exact embroidery/identity UNKNOWN; Z-Image FAIL teeth + duplicate collar N. All Stage1 FAIL full-body/single-view/wardrobe gate |
| R2 | Root | Native Run, sequential RTX5080 | Per-job history, timers, hashes; HD before 4K | all three HD jobs success: Krea2 346.126s; Z-Image 333.836s; FLUX1 334.021s, no cached nodes; quality acceptance incomplete |
| G3 | Gemini researcher | Read-only Stage1 prompt/graph analysis, no canonical prompt edits | Minimal common T2I adapter proposal, exact graph implications, original20 preserved | corrected proposal received; no graph changes made. Adapter prompt and use of each model's T2I image as Stage2 base still need a separate measured candidate. Keep original20 canonical prompts unchanged |
| V6 | Root + Astra | CHAR08 FACE10 Krea2; approved body/face anchor; 10 distinct canonical face prompts | Keep approved pixels for body/wardrobe; provide both full-body and face outputs; check face, pose, shirt shade/grid and collar N; any4K branch must take an exact saved HD image | FACE01 HD + one 4K portrait executed. Astra FAIL: teeth on neutral prompt, coarse grid, oversized N. User reports face/body differs from reference and asks for face/full-body pair. FACE02–10 not queued; stop after this 4K as requested. |
| MEM | Root | Gaming pause; Docker `Comfyui-Studio` | Queue empty before unload/stop; record free system RAM/VRAM and preserve outputs | `/free` acknowledged; Comfyui-Studio stopped with no jobs queued. RAM 33,825/65,317 MiB free at check. Do not restart until image task resumes. |

Rendered V004 jobs: Krea2 `958c69ba-1684-44d6-b0ac-48cc76a6da52` (346.126s), Z-Image `fbeb31a7-2931-4f9d-8b99-2df9f8dd7b42` (333.836s), FLUX1 `7baab79f-fbab-44ce-b2fd-1e0803aab437` (334.021s; cached_nodes empty). Final HD is1536x2048. Their final images are GPT-ACTION03-derived Klein/Krea2 edits, not independent base-model T2I. Stage1 files are the separate T2I outputs. Full20 benchmark, 4K acceptance and160-image goal remain incomplete. Preview-after-reload E2E passed; evidence `runtime-receipts/CHAR08_V004_PREVIEW_BROWSER_E2E_20261025.json`. Current browser-exported reload diagnostic: `C:/Users/Admin/Downloads/CHAR_08_KREA2_V004_RUNTIME_RELOAD_DIAG.json`.

V005 adapters were diagnostic and produced a face/garment that drifted from the user's near-approved image. V006R2 added the user's approved body/face anchor and ten canonical FACE workflows, then ran FACE01 on RTX5080. HD job `2d71df8f-fb52-4f00-9c22-863d10191d3f` succeeded in314.595s at1536×2048. Requested 4K job `444e5903-06c8-44ce-b2ac-48cc76a6da13` succeeded in332.703s at3072×4096. Astra reviewed both as FAIL (visible teeth, coarse grid, oversized interlocked N). A full-body Stage2 output exists separately at1536×2048; the 4K branch is connected only to the cropped FACE image. The 4K Run re-executed upstream. PNG SHA differs from HD00001 due to metadata/encoding, but Astra verified decoded RGB byte-for-byte identical (0 differences). Record that the graph reran; don't claim stage4-only execution or full-body4K output.

User compared the approved full-body anchor (SHA `8a08dbe63c559eb6fb8ddb482dfc214eb41b1f7085e9ab41913ea1998136fcb8`) with Krea2 V006R2 FACE01 and rejected the drift: brighter fine grid/small collar N in anchor versus muted coarse grid/oversized wrong N and tooth-visible neutral output. V4 started from an existing GPT-derived full-body latent; V006R2 started Stage2 from a fresh T2I latent and only supplied the approved image as conditioning. Krea2 reference weighting did not enforce an exact face/garment lock. The Stage4 chain is connected only to the cropped face branch; a full-body Stage2 HD file exists, but no full-body 4K. Astra checked HD00001/HD00002: PNG hashes differ but decoded RGB pixels are identical, so the visible errors predate SeedVR2. The user asked us to stop after this one Stage4 test; FACE02–10 were not submitted.

Gaming pause: queue running0/pending0 at check. `/free` returned; RTX VRAM was already mostly free. Docker `Comfyui-Studio` is now stopped; system RAM was about33.8 GiB free at the last measurement. To resume, start `Comfyui-Studio`; endpoint8188 will be available after health check.

Confirmed FLUX v003 job `59b288fa-cffb-48a2-901c-1ba78057e8e2` succeeded. HD `CHAR_08_FLUX1_V003_HD_DRAFT_REVIEW_00001_.png` is 1536x2048. Independent visual review FAIL (teeth/smile vs FACE08 closed lips); identity/logo UNKNOWN. Krea2/Z-Image v003 and full20 benchmark not rendered. 4K remains muted. Root verified queue empty and Docker healthy at resume. Preview pan/zoom fingerprint source fix exists, but browser restoration remains unverified.

V004 published as three new files, preserving v003. Python reviewer and independent general reviewer verified links, mode, actual widget order, FACE08-last binding and hashes. Types added after Python review; syntax passes. Q2 Astra explicitly confirmed final image is a GPT-reference-derived common Klein/Krea2 edit, not a clean FLUX1-only benchmark; Stage1 T2I must be compared separately. FACE08 target is slight closed-lip smile, not anger/no-smile. V004 currently tests this recipe, not accepted quality. DeepSeek V2 first returned an approach without code; root reopened implementation with required saved changes/tests. No completion claimed for that first report.

| ID | Chủ trì | Công việc | Điều kiện hoàn tất | Trạng thái |
|---|---|---|---|---|
| D1 | Root | Docker GPU, volume dữ liệu, nghỉ giải phóng model | 8188 healthy, GPU RTX5080, start/stop, dữ liệu giữ nguyên | Đang làm |
| W1 | Astra | Flux1 + Turbo, mặt/áo, SeedVR2 | GUI/API có đường xử lý thực, prompt chung, note Việt | Đang làm |
| W2 | Sol | Krea2 Turbo, mặt/áo, SeedVR2 | GUI/API có đường xử lý thực, prompt chung, note Việt | Đang làm |
| W3 | Sol | Z-Image Turbo, mặt/áo, SeedVR2 | GUI/API có đường xử lý thực, prompt chung, note Việt | Đang làm |
| R1 | Root | Chạy ba mẫu tuần tự trên GPU | History success và PNG 3072x4096, receipt/hash | Chưa chạy |
| V1 | Root | Xem ảnh, mở workflow trên8188 | Đúng source, hiển thị ảnh, ghi QA thực, người dùng review | Chưa làm |

Chỉ ảnh tạo từ nhánh T2I thực mới gọi là T2I; ảnh cuối có thêm Krea2 sửa tham chiếu và SeedVR2 phải ghi đủ nguồn. Không gọi ảnh đã sinh là đạt danh tính/logo trước khi kiểm.

## Kiểm lại 2026-10-25 — ưu tiên mới

- D1: Docker 8188 đã trả API; không đồng nghĩa toàn Studio đã tích hợp.
- R1: Krea2 job ff0d3b81-6870-4b3e-a90a-e43b00f0b789 success runtime nhưng FAIL mặt/logo; PNG cuối 2304×3072 không đạt đích 4K.
- FIX-01 / Astra: đã nhận audit; root xác minh thiếu reference method trong graph và mặc định Krea2 None. Recipe sửa chưa có QA PASS.
- FIX-02 / Gemini: đã ghi ba GUI v002, root xác minh 11 node upscale đều mode2, đích3072×4096, preview HD riêng. Đây là sửa GUI, chưa sửa conditioning mặt.
- FIX-03 / DeepSeek: đang chuẩn bị graph mới lấy FACE08_DETERMINATION + ACTION03_WALK_INSPECTION + áo gốc; chỉ chạy HD để duyệt.
- BENCH-01 / Gemini: kiểm kê20 GPT và liên kết prompt; root bắt lỗi mô tả ACTION03 cầm tablet, đã yêu cầu sửa vì hai tay thật đều trống.
- REVIEW-01 / root + reviewer độc lập: kiểm từng output/hash, log timer từng model và module chung, không tự lên4K hoặc tuyên bố giống100%.

Các việc gom cache/model và tích hợp Studio/VoiceStudio/HyperFrames/Remotion còn mở, không được ghi hoàn tất từ trạng thái ComfyUI healthy.


## V1 Canvas preview repair — 2026-10-25

- Root khôi phục journal hiện tại: Preview32→Save31, Preview54→Save53 (cùng tensor ảnh, output lưu bền vững).
- UI Chrome reload và kiểm thấy ảnh trong native node54; URL ảnh output HTTP200. Bằng chứng: live-preview-fixed-20261025.png và live-preview-dom-evidence-20261025.json.
- Ảnh thực còn FAIL biểu cảm; logo UNKNOWN; không bật4K.
- DeepSeek đang hoàn thiện mapping tự động ở timed runner cho job sau; Astra độc lập sẽ review code và bằng chứng sau khi cập nhật.
- V1 chưa complete cho đến khi runner cập nhật journal tương lai và UI mở lại đúng ảnh sau reload.


## V1 runner mapping implementation — 2026-10-25

- DeepSeek updated 
un_timed_hd.py: PreviewImage and SaveImage are paired by the same API images connection; Preview journal output prefers durable SaveImage descriptor regardless of event order or omitted preview event. Raw outputs and display provenance remain separate.
- Validation: py_compile and focused harness for same-source mapping, save-only, preview-first, late-save replacement, temp fallback and mismatch isolation all PASS.
- No post-change GPU run; do not claim future live E2E complete until a later real job and page reopen succeed. Astra independent review pending.
- Three model benchmark remains incomplete: only Krea2 diagnostic has run; Flux1 and Z-Image no inference yet.


## T2I và E2E người dùng bấm Run — 2026-10-25

- Đã kiểm ba graph GUI v002: T2I Stage1 hoạt động và nối tới Save/Preview; nối tiếp Stage2 áo, Stage3 nhận dạng/HD với output riêng. Nhánh4K mode=2.
- Ba graph keys riêng, nhưng thiếu 
ecipe_fingerprint; live extension hiện yêu cầu trường này. DeepSeek bổ sung native-run event capture, local per-workflow result ledger và fingerprint fallback trước khi người dùng bấm lần lượt.
- ComfyUI /history/<prompt_id> có thể rỗng sau Docker restart; không dùng history làm kho duy nhất. Native run cần lưu output descriptors bền vững kiểu output.
- Hiện chưa hoàn tất E2E mới của ba model. Người dùng sẽ bấm lần lượt sau khi kiểm được event capture, canvas và lưu kết quả.



## Ba workflow chuẩn bị cho user-run E2E — 2026-10-25

- Flux1/Krea2/Z-Image v002 đã được cập nhật: cùng prompt GPT ACTION03 (SHA256 dc9e1addf5a13b9a5b320222e35a5264a59d19ca541a839dc3cd28bf549ee59b) ở T2I Stage1; Stage2 nối thật Action03 pose + áo chuẩn; Stage3 FACE08; output từng stage; 4K vẫn mute.
- Cổng/wire đã đồng bộ live /object_info: 0 mismatch, 0 link sai. Backups .pre-e2e-reference-repair.bak; report CHAR08_3MODELS_E2E_REFERENCE_REPAIR_20261025.json; script prepare_char08_v002_e2e.py.
- Native UI Run ledger đã có logic/test, nhưng cần hard reload browser và xác minh graph hiện tại; chưa có GPU inference mới. User sẽ bấm 3 workflow lần lượt sau khi root mở đúng tab.
- Chỉ Krea2 diagnostic cũ đã chạy; biểu cảm FAIL, logo UNKNOWN. Flux1/Z-Image chưa chạy.



## E2E handoff ready — 2026-10-25

- Chrome hard reload loaded current Newtecons.LivePreview extension; log confirms native UI run ledger. Three v002 workflows are loaded as ComfyUI tabs, Flux1 selected, queue 0 active. No GPU job submitted yet.
- Current tab Run order: Flux1 → Krea2 → Z-Image, sequentially. Each has Stage1 T2I, Stage2 ACTION03+shirt reference edit, Stage3 FACE08 edit+HD preview, Stage4 4K muted. The user performs Run and reviews candidate images.
- Astra static review PASS; TypeScript review PASS on preview/run logic. The model benchmark and visual acceptance remain pending real outputs.
- Backups are in `runtime-receipts/graph-backups`; graph repair receipt is `runtime-receipts/CHAR08_3MODELS_E2E_REFERENCE_REPAIR_20261025.json`.


## UI ready for user-driven E2E — 2026-10-25

- Browser hard reload loaded native-run ledger; three v002 tabs open, Flux1 selected, queue 0 active. No GPU job submitted.
- Active NEWTECONS_3_MODELS folder contains only Flux1/Krea2/Z-Image v002. Older masters/diagnostic graphs are recoverably archived in NEWTECONS_3_MODELS_ARCHIVE_20261025; graph repair backups are outside workflow scan in `runtime-receipts/graph-backups`.
- Final static graph schema/link validation 0 errors, T2I ACTION03 prompt identical SHA, action/face/shirt reference nodes wired, Z-Image lumina2, KSampler fixed widgets, HD active, 4K muted. Unit/lifecycle Node tests and type syntax checks pass.
- User can press Run sequentially Flux1 → Krea2 → Z-Image and review three stages per graph. This is one shared prompt smoke E2E, not full20 benchmark. Image QA and actual benchmark timers remain pending outputs.

