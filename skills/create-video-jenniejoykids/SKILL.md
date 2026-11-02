---
name: create-video-jenniejoykids
description: "Hệ thống sản xuất phim hoạt hình JennieJoyKids E2E phối hợp song song các engine chuyên môn hoạt động như subagent: kịch bản & phân cảnh prompt, 3D không gian (comfyui-blender), giọng nói đa ngôn ngữ (jenniejoy-voice-comfyui), motion H3 & upscale SeedVR2 (comfyui-video-pipeline), đồ họa hoạt họa (hyperframes-animation), hậu kỳ timeline & phụ đề kinetic (jenniejoy-remotion) và quản lý tiến độ webapp (jenniejoy-studio-webapp). Tự động lên task, khóa nhân vật, sinh storyboard và dựng master không đợi nhắc."
---

**Last updated:** 2026-10-27. Domain: `jenniejoy_cartoon_3d`. Unified under [engine dispatch contract](references/engine-dispatch-contract.md).

**Status 2026-10-28 (night):** ep04 shipped; the cartoon path now runs through `jjv run episode` (dry run on ep04 exits 0, first stop `voice` [gpu-approval]); ep05 waits for the topic choice and GPU approval. The verb table below is dated 2026-10-27 and its "no verb yet" rows are superseded by the studio-video-engine verb index.

Use [production system](../jenniejoy-production-system/SKILL.md) for compact status, engine routing and recovery. Read only the stage references needed below. Historical entrypoints are preserved under `references/history/2026-10-19-before-portable-hub/`; their old hardware, voice and gate claims do not override current evidence.

## jjv verbs per stage (S0-S14, state 2026-10-27)

Source: `production-local/engine/ENGINE-PLAN.md` stage table and `production-local/engine/specs/ENGINE-AUDIT-2026-10-27.md` section 1. "no verb yet" means the stage still runs by hand. Engine skill: [studio-video-engine](../studio-video-engine/SKILL.md).

| Stage | jjv verb today | Note |
|---|---|---|
| S0 Config | `jjv config validate --episode E` | ep04 ok; DELIVERY-CONTRACT not hashed or checked |
| S1 Script ingest | no verb yet | script, dialogue, cast by hand |
| S2 Storyboard / continuity | no verb yet | `scene_layout.py continuity` not wired to boundaries.json |
| S3 Images / anchors | no verb yet | `jjv comfy submit` takes raw graphs only |
| S4 Voice | `jjv voice plan / synth / reconcile / adopt / finalize` | `synth --execute` never run against real VoiceStudio |
| S5 H3 motion | no verb yet | hand prepare script + ep04 guarded submit helper |
| S6 Word timing | `jjv timing words`, `jjv qa words` | wired |
| S7 Editorial build-config | `jjv editorial build-config` | wired; presets CLI not wired |
| S8 Review render | no verb yet | kit only: `node remotion-kit/render.cjs` |
| S9 QA | `jjv qa av`, `jjv qa words`, `jjv qa review` | `qa transitions`, `qa review-gates` not built |
| S10 User review | no verb yet | Studio UI; Studio never calls jjv |
| S11 4K SeedVR2 | `jjv seedvr2 plan / execute / seam-blend` | no tails verb |
| S12 Master 4K + 2K | no verb yet | mux only: `jjv audio mix --remux` |
| S13 Publish | no verb yet | ep04-specific scripts |
| S14 ep05 bootstrap | no verb yet | blocked by S1, S3, S5, S8, S12, S13 |
| A Audio | `jjv audio music / sfx / mix` | `music` and `sfx` submit: fake ComfyUI tests only |

## Phạm vi bắt buộc — JennieJoy là phim hoạt hình 3D

- `production_domain: jenniejoy_cartoon_3d`. JennieJoyKids và *Milk and Mom* là phim hoạt hình 3D điện ảnh cho thiếu nhi, dùng nhân vật cách điệu đồng nhất với ảnh đã duyệt. Alice là bé hoạt hình, Mẹ và cô gái Hà Lan là người lớn trong cùng phong cách hoạt hình.
- Đọc nhân vật, tuổi, tóc, nơ, trang phục và biểu cảm từ thư viện của chính phim. Với Milk and Mom: Alice giữ tóc bob tối, mái bằng, nơ **hồng ở bên phải giải phẫu**, bộ pyjama hồng có tim trắng; Mẹ giữ tóc nâu gợn sóng ngang vai, áo teal, quần kem và giày bệt. Không thay các đặc điểm này bằng mô tả mẫu.
- NEWTECONS là một nhánh **phim người thật** riêng tại [create-video-newtecons-comfyui](../create-video-newtecons-comfyui/SKILL.md). Chỉ chuyển nhánh khi yêu cầu hiện hành của người dùng là NEWTECONS. Tiêu đề/handoff lịch sử không được đổi dự án đang làm.
- Có thể dùng chung ComfyUI, VoiceStudio, SeedVR2, Blender, HyperFrames và Remotion. Prompt, ảnh neo, trang phục, bối cảnh, giọng, workflow tạo hình, receipt và tiêu chí duyệt phải thuộc đúng `film_id`/`production_domain`. Không lấy workflow sửa mặt/đồng phục NEWTECONS làm workflow hoạt hình đã được kiểm chứng; một module dùng chung phải được kiểm đủ model/LoRA và thử bằng ảnh hoạt hình của chính phim.
- Tái sử dụng **engine, nhân vật và giọng đã chọn** của tập Sữa. Kịch bản, diễn xuất, bối cảnh, ảnh neo phân cảnh, clip và Master của Milk and Mom phải là nội dung tập mới; tuyệt đối không sao chép footage/ảnh cảnh phim 03 vào tập 04. Tập 04 diễn ra hoàn toàn ngoài trời (vườn ban mai, rào chuồng bò sữa, cô gái Hà Lan vắt sữa); không đưa cảnh phòng ngủ hay câu chúc ngủ ngon cũ vào phim mới.

---

## 🎬 CINEMATOGRAPHY & PROFESSIONAL FILM GRAMMAR CONTRACT

JennieJoy cartoon production enforces deliberate film grammar and cinematic storytelling, rejecting random AI clips or static camera simulations:

1. **Intentional Camera Framing & Lens Intent:**
   - **Wide Shot (WS / EWS):** Establishing spatial geography, farm paddock boundaries, weather and lighting atmosphere. Used for scene introductions (e.g. S01_A morning garden and fenced pasture).
   - **Medium Shot (MS):** Character interaction, physical blocking, and conversational gestures between Alice and Mother or the milkmaid.
   - **Close-Up (CU / MCU):** Emotional focus, spoken dialogue, and listening reactions. Strict speaker/listener mouth rule: speaker speaks with clear visemes; listener maintains fully closed, smiling lips.
   - **Insert / Macro:** Key educational props and tactile objects (e.g., turning the sealed milk bottle, height measurement ribbon, fresh milk pail).
2. **Shotlist Architectural Declarations:**
   Each shot card must declare:
   - `shot_size`: WS, MS, CU, or Insert.
   - `lens_intent`: Wide (24–28mm equivalent for spatial scale), Normal (35–50mm for natural conversation), Portrait (85mm for intimate emotion).
   - `camera_axis & eyelines`: Maintain the 180° rule across conversation cuts. Alice at screen-left looks screen-right toward Mother; Mother at screen-right looks screen-left toward Alice.
   - `dramatic_motivation`: Why the camera is placed here and what story/learning event it reveals.
   - `incoming & outgoing blocking`: Position, posture, and momentum of characters at cut boundaries.
3. **Lighting Direction & Color Continuity:**
   Maintain consistent sun angle (warm low-angle morning sunlight from screen-right), soft atmospheric bounce, and consistent color grading across all 12 scenes. Shadows must ground all actors and props to their contact surfaces.
4. **Motivated Cuts vs. Continuous Shots:**
   - **Motivated Cut (Angle / Time Change):** Cuts between different camera setups (e.g. WS establishing → CU dialogue) require an intentional cut with a freshly generated, QA-approved anchor image matching the established blocking and lighting.
   - **Continuous Shot (Same Angle / Direct Sequence):** Requires the **exact last USED native frame** of the prior shot as frame 0 of the next shot at unchanged native resolution (e.g. native frame 119 for 120 used frames at 24fps). Never approximate seeks or pretend disparate shots share an identical continuous camera.
5. **Atmosphere, Music & SFX Synchronization:**
   - Dialogue, music, and SFX/Foley reside in separate stems.
   - Background music is dynamically ducked (-14 dB to -18 dB) beneath spoken dialogue.
   - Spot Foley (milk pouring, bottle cap turning, cow chewing) peaks are frame-synchronized to visual contact events, not blindly aligned to audio clip starts.
6. **Preserve Approved Cast:**
   Never regenerate approved core cast (Alice `production-local/character-library/alice/` and Mother `production-local/character-library/mother/`). Reuse verified identity hashes; create only genuinely missing character assets (such as the Dutch milkmaid).
7. **Pragmatic Realism:**
   This contract establishes reusable, disciplined cinematic engineering for AI animation; it does not claim Hollywood perfection or deny the generative nature of AI tools.

---

## ⚡ PARALLEL HYBRID — GPT IMAGES & LOCAL COMFYUI

For authorized JennieJoy image creation/editing, start two independent branches concurrently where resources permit:
- **Branch A (Native Cloud Image):** Built-in `image_gen` requested for this route as GPT Image Gen 2. Record `requested_model` and keep `resolved_model` null when the provider does not expose it. Record a runtime/tool ID when returned and null when absent. Dispatch occurs outside the local ComfyUI queue. Save edit prompt, reference hashes, returned output and SHA256. Cloud inference does not consume RTX 5080 CUDA memory.
- **Branch B (Independent Local ComfyUI):** Pure local ComfyUI workflows on RTX 5080.
- **Single Heavy CUDA Owner:** VoiceStudio, ComfyUI H3, and SeedVR2 7B share one GPU. Sequential scheduling is mandatory; check `/queue` and `/history` before submission.
- **Immediate H3 Unlock:** The **first hash-bound QA-accepted complete image** unlocks local H3 motion immediately once that shot's receipt WAV (the WAV named in its H3 preparation receipt, `wav.sha256`) is ready. Do not wait for the alternate branch, later storyboards, full expression packs, or music mix (see Case 02 in [production case studies](references/production-case-studies-20261027.md)).
- *Milk and Mom S01_A:* Already has approved A SHA `2113acd0d7a3eb335c64e1e0145998a01d8d4a53624da70628501b7d5b8ab47f`; reuse this verified hash directly.

JennieJoy hybrid authorization persists across sessions; no new permission question is needed for the already authorized built-in image tool. After two consecutive local pilots/errors with the same defect, independently review source graph, model/LoRA roles, masks, reference binding and queued prompts before any further local retry, and use authorized hybrid support. For every image artifact, record the requested image model separately from the observed/resolved model; leave the latter null when the provider or reuse path does not expose it. Runtime/imagegen IDs may also be null with truthful external-tool or reuse provenance. Read the [real graph and provenance contract](../comfyui-video-pipeline/references/hybrid-image-routing.md). NEWTECONS keeps its separate live-action permissions and local-only default.

---

## 🔄 UNIFIED EVENT-DRIVEN ENGINE DISPATCH CONTRACT

All subskills adhere to [engine-dispatch-contract.md](references/engine-dispatch-contract.md) as the single operational contract. Do not create a competing tracker. Root handles overall PLAN, GPU queue scheduling, App publication and handoff reconciliation and may perform authorized media submissions or publication while retaining the single heavy-GPU owner. Named children execute only their assigned scope. The PLAN must bind each lane to a concrete live root/agent ID; skill names are routes, not owners.

Every production lane has an explicit trigger, responsible owner, concrete output, and downstream consumer:

| Lane / capability route (live owner lives in PLAN) | Input Trigger | Trách nhiệm & Đầu ra (Concrete Output) | Result Consumer |
|---|---|---|---|
| **Đạo diễn / Prompt**<br>`script subagent` | Brief, lứa tuổi (2–4 tuổi), 12 từ vựng | Shot card, mô tả cast/trang phục, camera axis, eyelines, prompt H3, ràng buộc khẩu hình | Storyboard, Voice, Subtitle, H3 lanes |
| **Thư viện nhân vật**<br>`asset subagent` | Script & danh sách cast | Khóa visual identity Alice `production-local/character-library/alice/2026-10-18-v1/canonical-approved-latest.png` SHA `e87d4d0c…` và Mẹ `production-local/character-library/mother/2026-10-18-v1/canonical-production-reference.png` SHA `5f28f442…`; profile `8f1145d7`/`767cedad` là speaker IDs, không phải visual refs | Storyboard & H3 lanes |
| **Bố cục Blender 3D**<br>`blender subagent` | Bối cảnh có rào cản, tiếp xúc, tỷ lệ | File `.blend` + ảnh guide không gian, đo đạc bounds/tiếp xúc, alpha mask phân lớp 5 mặt phẳng | ComfyUI Storyboard lane |
| **Storyboard HYBRID**<br>`image owner + root` | Script + Cast ref + Blender guide | A: native `image_gen`; B: ComfyUI local. File PNG đạt QA, LoadImage review GUI workflow | ComfyUI H3 lane |
| **VoiceStudio**<br>`audio subagent` | Thoại chốt + profile nhân vật | WAV 48kHz stereo PCM16, đo đạc SHA256 + duration; nếu cắt silence thì cắt đúng 1 lần trước H3 để receipt H3 ghi chính file đó | H3 (lip motion), Remotion (subs/mix) |
| **Subtitle / Phụ đề**<br>`editorial subagent` | Lời thoại chốt + final WAV hash | Timing từ khóa in đậm trên pill hồng `#FF2E7E`, bản dịch tiếng Việt, card từ vựng | Remotion compositor |
| **Nhạc nền (Music)**<br>`audio subagent` | Mood, phong cách, thời lượng 84s | File nhạc nền riêng biệt (music stem), loop/fade, kịch bản ducking (-14 dB đến -18 dB) | Remotion compositor |
| **SFX / Foley**<br>`audio subagent` | Hành động & bối cảnh phân cảnh | Ambience stem + spot Foley stem (rót sữa, vắt sữa, bò nhai) đồng bộ theo frame tiếp xúc | Remotion compositor |
| **Motion AI (H3)**<br>`comfyui-video-pipeline` | Ảnh neo đạt QA + WAV receipt (file có SHA256 ghi trong receipt job H3) | Clip MP4 native 24fps (864×480), khẩu hình khớp thoại, file ảnh last USED native frame | SeedVR2 upscale, Remotion |
| **Phục chế SeedVR2 7B**<br>`comfyui-video-pipeline` | Clip H3 đạt chuyển động + short target-resolution memory pilot passed | 4K 3840×2160 bắt buộc; 2K 2560×1440 = lanczos downscale của Master 4K đã hoàn thành (downscale: PLAN T-V10; lanczos: `editorial/master-4k-v001/DOWNSCALE-2K.md`); không có lượt SeedVR2 2K riêng; recipe v003 tile768/internal17/raw21 chỉ đạt chuẩn kỹ thuật cho đúng cấu hình đó (không phải bằng chứng no-OOM cho cấu hình khác; xem [SeedVR2 section](../comfyui-video-pipeline/SKILL.md#seedvr2-7b-bounded-4k-restoration)), phải đo RAM/VRAM/frames/seams | Remotion compositor |
| **Đồ họa HyperFrames**<br>`graphics subagent` | Script, logo, 12 từ vựng | Intro 3s (90f), Outro/cards 12s (360f), component video có alpha channel, timing manifest | Remotion compositor |
| **Dựng Master Remotion**<br>`remotion subagent` | Script/timing known để scaffold; accepted media được thay tăng dần | Timeline 84s (2520 frames 30fps), 4K 3840×2160 Master bắt buộc & 2K 2560×1440 = lanczos downscale của Master 4K đã hoàn thành (downscale: PLAN T-V10; lanczos: `editorial/master-4k-v001/DOWNSCALE-2K.md`); không có lượt SeedVR2 2K riêng | Studio Publisher, Independent QA |
| **Studio Publisher**<br>`root / app subagent` | Hoàn thành từng ranh giới job | Đăng ký film ID `04-milk-and-mom`, runtime ID truthfully nullable, requested/resolved model, URL media và SHA; lưu riêng GUI/Studio/HTTP/UI proofs | Ban đạo diễn, review web UI |
| **Independent QA**<br>`reviewer subagent` | Media xuất bản thực tế | Biên bản kiểm định SHA-bound: hình ảnh, khẩu hình, âm thanh, tính liên tục cuts | Root integrator |

---

## 🛡️ TEN DURABLE LESSONS & PREVENTIVE GATES (EPISODE 04)

All production agents must consult [production-case-studies-20261027.md](references/production-case-studies-20261027.md) and the structured incident records in `error-db/`:

1. **Missing Edit LoRA & Live-Action Node Leak (Case 01):**
   - *Error DB:* `error-db/storyboard-v014-v016-missing-edit-lora-liveaction-leak.json`
   - *Gate:* Preflight one task-compatible V2 LoRA (`krea2_identity_edit_v2.safetensors` for identity restaging or `krea2_general_edit_v2.safetensors` for instruction edits), its upstream binding and installed hash. Strictly isolate `jenniejoy_cartoon_3d` from live-action swap nodes (`bfs_body_swap`, `bfs_head_swap`).
2. **H3 Release Gap Without Proven Delay Chronology (Case 02):**
   - *Error DB:* `error-db/h3-stalled-waiting-unnecessary-prerequisites-s01a.json`
   - *Gate:* First QA-accepted complete image anchor unlocks local H3 motion immediately once that shot's receipt WAV (the WAV named in its H3 preparation receipt, `wav.sha256`) is ready. Never wait for alternate comparators, later storyboards, or full expression packs.
3. **SaveImage Output Reload Preview Loss (Case 03):**
   - *Error DB:* `error-db/comfyui-saveimage-reload-preview-loss.json`
   - *Gate:* Resolve the helper under the active episode and create a paired GUI workflow with a pinned `LoadImage` node. Separately record Comfy GUI import, Studio registration, HTTP media/hash readback and reopened UI inspection. A GUI workflow or `/films.html` promise is not proof that Studio ingested the asset.
4. **Fence & Barn Spatial Geometry Failure (Case 04):**
   - *Error DB:* `error-db/spatial-blocking-fence-cow-geometry-failure.json`
   - *Gate:* Enforce deterministic 3D Blender layout guide defining 5 distinct depth planes (Near foreground, Acting, Barrier, Farm, Far). Text re-prompting alone is prohibited for boundary topology.
5. **SeedVR2 2K Full-Clip Container OOM; 4K 21-Frame Internal17 Pilot Technically Qualified, prompt `43f87ebe…` (Case 05):**
   - *Error DB:* `error-db/seedvr2-2k-fullclip-container-oom-30gb.json`
   - *Gate:* Preserve the observed 2K OOM as the evidence. Use the qualified recipe tile768/overlap64/internal17/raw21 (v003 pilot; technical qualification only, full-film seams unchecked) as defined in the [comfyui-video-pipeline SeedVR2 section](../comfyui-video-pipeline/SKILL.md#seedvr2-7b-bounded-4k-restoration); the former 40-frame planning ceiling is superseded. Record RAM/VRAM/frame count/seams per chunk; the 2K 2560×1440 film = lanczos downscale of the finished 4K Master (downscale: PLAN T-V10; lanczos: `editorial/master-4k-v001/DOWNSCALE-2K.md`), no separate 2K SeedVR2 run.
6. **Audio-Only Trim Desync vs. Video Timing (Case 06):**
   - *Error DB:* `error-db/audio-video-trim-desync-carry-endpoint-mismatch.json`
   - *Gate:* Each shot has exactly one dialogue WAV: the WAV named in that shot's H3 preparation receipt (`technical/motion-v00N/<SHOT>/preparation.json` → `wav.sha256`; S01_A: `technical/hybrid-v001/job.json` → `wav_sha256`), whose SHA256 the H3 job receipt must record identically (the receipt WAV); H3 conditioning and the Remotion mix use that same file and start offset. If silence is trimmed, trim once before H3 so the receipt records the trimmed file; a trim made after H3 is a different file and must never replace the receipt WAV (episode04 S01_A: untrimmed `5d33ad49…`, see `technical/audio-binding-r27/S01_A-WAV-BINDING-DECISION.json`). A shot with no speech conditioning (`native_speech_conditioning:false`, voiceover/nonverbal) has no receipt WAV; its editorial voiceover WAV must be named and hash-bound in the editorial manifest instead. Bind native 24fps video frames, picture offset, delivery 30fps frames, and exact last USED carry frame in a paired AV manifest.
7. **Orphaned Unowned Production Lanes (Case 07):**
   - *Error DB:* `error-db/production-lane-orphan-unowned-finishing-delivery.json`
   - *Gate:* Assign explicit owners to all lanes before GPU runs start. Separate music from SFX with ducking. Scaffolding runs concurrently with video. Continuous publication to Studio `/api/films`.
8. **Hybrid Coordinator Duplicate Retries & Receipt Gaps (Case 08):**
   - *Error DB:* `error-db/hybrid-coordinator-unknown-outcome-duplicate-retry.json`
   - *Gate:* Block unattended retry loops. Preserve timeout/unknown outcomes as in-flight requiring manual reconciliation. Validate semantic receipts (matching film/shot/branch/route/hash) and process adoption before unchanged registration return.
9. **Finishing Placeholder Unlock and Fixed-Resolution Hardcoding (Case 09):**
   - *Error DB:* `error-db/finishing-pipeline-placeholder-unlock-and-1080p-hardcode.json`
   - *Gate:* Keep full render blocked until every real clip/WAV binding, finite duration and exact frame count pass a fresh independent review and runtime gate. Existing 15-second previews remain candidates.
10. **H3 Spatial Restaging and Carry/Cut Prompt Conflict (Case 10):**
   - *Error DB:* `error-db/h3-v003-spatial-restaging-and-carry-semantics.json`
   - *Gate:* Keep production metadata in the receipt, not model prose. Declare `carry` or `motivated_cut`; inspect early/middle/late/decoded-end samples and normal-speed motion before any carry. The v004 shorter-prompt/single-reference route has a sampled visual pass for S02_A (sampled-visual-usable candidate, `technical/motion-qa-v005/INDEPENDENT-MOTION-QA-v005.json`); full-speed AV acceptance is still open.

---

## 📊 KẾT QUẢ ĐẦU RA VÀ ĐỊNH DẠNG MASTER

- **Thời lượng:** Đúng 84 giây = 2520 frames ở 30fps (3s intro = 90f; 69s dialogue = 2070f; 12s outro = 360f).
- **Độ phân giải:** Master 4K 3840×2160 (30fps, H.264/AAC) là bắt buộc; phim 2K 2560×1440 = lanczos downscale của Master 4K đã hoàn thành (downscale: PLAN T-V10; lanczos: `production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/master-4k-v001/DOWNSCALE-2K.md`); không có lượt SeedVR2 2K riêng.
- **Tập tin Master:** Lưu tại `production-local/JennieJoyKids-Story/{film_id}/comfyui-out-render/JennieJoyKids-<episode>-Master-4K-vNNN.mp4`.
- **Đăng ký webapp:** Đăng ký metadata, hash, requested/resolved model, runtime ID khi có (null cho reuse/imagegen nếu không lộ ID) và URL media; kiểm tra riêng Comfy GUI, registration, HTTP/hash và reopened `http://127.0.0.1:5050/films.html`.

Chỉnh sửa nội dung SKILL.md là hoàn thiện quy chuẩn vận hành, hợp đồng điều phối và kiểm soát lỗi thực tế; không phải huấn luyện lại trọng số mô hình AI (model-weight retraining). Đọc [motion engineering lessons](references/motion-engineering-lessons.md) để áp dụng các bài học chuyển động và nhịp điệu điện ảnh.

## Motion engineering cho đồ họa viết bằng code

Title card, flashcard từ vựng, intro/outro và overlay (không phải footage nhân vật; nhân vật vẫn là ComfyUI local): dùng [opus-motion-engineering](../opus-motion-engineering/SKILL.md) cho BRIEF theo frame, cổng 3 ảnh tĩnh và critic độc lập. Chỉ bổ sung quy trình, không đổi hợp đồng điều phối ở trên.

**Blender spatial layout (domain `jenniejoy_cartoon_3d`):** for closed enclosures, animal counts, seated/kneeling planes and camera framing, validate a layout brief and emit the Blender blockout with the shared [comfyui-blender](../comfyui-blender/SKILL.md#domain-routing) skill (`scripts/scene_layout.py`; read its Domain routing and Live ComfyUI bridge status sections first). Blender stays layout/control only for this film; NEWTECONS previz briefs and workflows are never used here.

## Handoff lessons R27 (written immediately at each handoff — user rule 2026-10-27)

User rule: every production error found is written into the skill/error-db right after the handoff that found it, not batched at session end. R27 lessons: 4K restoration scope must come from the final editorial event list incl. transition handles; ffmpeg colour tags on the rawvideo input + framemd5 identity checks; frozen files are never in a builder brief during a run; sandboxed codex subagents never render; memory retains are verified via failed-operation checks; the logo ending is a separate 60 f end card (2580 f total); no cross-dissolve between shots with the same characters in different positions (double exposure — use masked wipes); no overlay may hide a vocabulary word during its pronunciation; no transition frame may show the same character OR prop twice (open masks where both shots agree); continuity: consecutive shots that will share a transition must keep characters and key props in the same place (lock the layout with `comfyui-blender` `scene_layout.py` at storyboard time and repeat the placement in both shots' H3 prompts); every visible change incl. card→end-plate fades must have a row in the transition table. Details: [comfyui-video-pipeline](../comfyui-video-pipeline/SKILL.md#production-lessons-written-at-handoff-r27-2026-10-27), [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md#end-card-and-tail-frames-user-decision-2026-10-27), error-db entries dated 2026-10-27.

Transition-pair continuity tooling (T-E26): for every planned transition pair put both shots on one shared SET and run `python .agents/skills/comfyui-blender/scripts/scene_layout.py continuity <briefA> <briefB>` (AGREE -> any transition; MISMATCH -> bloom/whip/cut only), then paste `placement-text` into both H3 prompts; this proves planned layouts only, the pixel review still decides ([comfyui-blender: Shot continuity](../comfyui-blender/SKILL.md#shot-continuity)).

## Review-cut gates (user-mandated 2026-10-27)

Origin: the user watched `review-hd-v003` at normal speed and rejected it although an independent critic had passed the stills (error DB: [review-cut-v003-user-fail-motion-transitions-ending.json](error-db/review-cut-v003-user-fail-motion-transitions-ending.json)). Stills cannot judge motion, cut rhythm or speech sync. Domain: `jenniejoy_cartoon_3d` only. **A review cut or Master may not be offered to the user until all seven gates below (G-CAP to G-LABEL) are PASS**, each with evidence recorded in the review-cut `RECEIPT.json` (gate id, artifact path/hash, critic ID and route actually used, scope watched). The builder never grades its own gates; the critic must watch moving partial renders ([critic-loop §7](../opus-motion-engineering/references/critic-loop.md)). The briefing sections are in [brief-template](../opus-motion-engineering/references/brief-template.md); the Remotion rules are in [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md). Numeric tolerances below are starting values, `chưa đo` until measured on a real cut.

| Gate | What must exist | How it is verified | Fail example (v003) |
|---|---|---|---|
| **G-CAP** word-level captions | A word-timing JSON per dialogue line, bound to that shot's receipt WAV SHA256 (word, start/end frame @30 fps global, source/aligner recorded). Subtitles show the **running word** (karaoke style), not the whole line at once. | Schema check (every spoken word timed, monotonic, inside the WAV duration) + critic watches a moving partial render of each line and compares the highlight frame with the JSON (start value: within 3 f = 0.1 s). | Whole line appeared at once. |
| **G-ICON** vocabulary icon pop | An icon event list (word, icon file + SHA256, frame, motion params, hold) with one event for **every target vocabulary term spoken in dialogue**. Target terms = the 12 vocabulary terms with the spellings of `vocabulary_icons[].term` in `editorial/word-timing-v001/WORD-TIMING-v001.json` (creamy, smooth, liquid, dairy cows, farm, fresh, yummy, warm-cold, bones, yogurt, cheese, ice cream; icon files include dairy-cow.png, warm-cold.png for the warm and cold words, ice-cream.png; list also in [jenniejoy-hyperframes](../jenniejoy-hyperframes/SKILL.md)) plus any term the episode brief lists. Pop frame = the word's `start_frame` (= entry `start_frame` + round(`start_s` × 30)) from that G-CAP JSON; when `raw_whisper_start_s` is not null and differs from the calibrated `start_s` by more than 0.3 s, use entry `start_frame` + round(`raw_whisper_start_s` × 30). | Coverage check (each spoken target term has an event) + critic watches each pop on a moving render against the JSON (start value: 0 to +3 f after the word start). | No icon pops at all. |
| **G-ICON-ART** icon brief (user rule 2026-10-27) | Write it INTO the icon prompt/brief before any icon is made: ONE icon per spoken word (never one shared image for two words — ep04 used warm-cold.png for both "warm" and "cold"); the icon must show the word's distinguishing attribute at a glance for a 2–4-year-old (warm = steam + warm glow on the ORANGE mug the shot shows; cold = ice cubes + frost + snowflake on the BLUE mug); colours/objects match what is on screen in that shot; opposite pairs (warm/cold, big/small, up/down) must look opposite in colour AND shape. | Pair QA: put the two icons of an opposite pair side by side and at their real on-screen size over the shot frame; a reviewer who does not know the word must name it. | Two words share one icon, or a pair differs only by a small detail (v013: two near-identical grey glasses). |
| **G-CUT** designed boundaries | A boundary table with a row for **every scene/shot boundary**: boundary frame, carry/cut class, tail-handle frames available, transition type + frames, placement. No unmotivated hard cut: a hard cut needs a written motivation. Timeline stays 2520 f and the audio is unchanged. | Critic watches a **moving partial render around each boundary, boundary-1 s to +1 s** (`--frames=(B-30)-(B+30)` @30 fps), not stills; every row of the table is covered. | Hard cuts at f390, f710, f1310 and others. |
| **G-BRIDGE** location-change bridge | For every boundary where a character changes location, either an on-screen action bridge (storyboard shows the movement) or a declared motivated transition. Bridge footage comes from the ComfyUI lane, hash-bound; Remotion never fakes walking from a still. | Location-change list matched against the boundary table + critic watches the bridge on the moving render. | f1495: Alice appears at the tree with no shot of her getting there. |
| **G-END** ending beat + logo | A story-ending beat (for example an iris-out on the closing image) and the JennieJoy logo on the final frames, with start/end frames stated; fits the 2520 f budget unless the PLAN declares a budget change. | Critic watches the final 3 s as a moving render; decoded first and last logo frames are checked; logo file hash-bound. | Story ended ~1:11 with no ending and no logo. |
| **G-MOTION** technique map | A list of which [awesome-opus5-5-videos](../opus-motion-engineering/references/awesome-opus55-prompt-index.md) techniques are applied where (slug, frames/boundary, our adaptation). An empty list fails. | Critic confirms each listed technique is visible at its named frames on a moving render. | Techniques were not visible. |
| **G-LABEL** honest quality label (user complaint 7, picture quality) | `RECEIPT.json` has `quality_label`. A review export made from native 864×480 clips is labelled "REVIEW 1080p · native upscaled" on screen and in the file name. The word "4K" is used only for 3840×2160 output from the SeedVR2 master. | `ffprobe` shows 1920×1080 for a 1080p label (3840×2160 for 4K, 2560×1440 for 2K); `RECEIPT.quality_label` equals the on-screen label; a "4K" name or claim on anything that is not the 3840×2160 SeedVR2 master fails. | The user had to ask what the picture quality was. |

**Honest quality label (mandatory, gate G-LABEL).** Every review cut states its true source and delivery quality in the file name, `RECEIPT.json` (`quality_label`) and Studio registration, with `RECEIPT.quality_label` exactly equal to the on-screen label "REVIEW 1080p · native upscaled" and the longer source description in a separate `source_note` field (e.g. "review cut, native 864x480 H3 clips upscaled to 1920x1080, not the 4K SeedVR2 master"). Never describe an upscaled review cut as 4K or as the Master. When the user asks about picture quality, answer from this label and the measured probe.

A still-only PASS never satisfies G-CAP, G-ICON, G-CUT, G-BRIDGE or G-END. Pending engine support: [studio-video-engine `qa review-gates`](../studio-video-engine/SKILL.md) (documentation only, not implemented).
