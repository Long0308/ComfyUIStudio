# Production case studies — JennieJoyKids & Episode 04 (2026-10-27)

Updated 2026-10-27, Asia/Bangkok. Domain: `jenniejoy_cartoon_3d`, grounded in active *Milk and Mom* (`04-milk-and-mom`) production evidence, audit reports, and technical receipts.

This document records ten durable failure case studies, root causes (marking unconfirmed causes honestly), verified evidence paths, and preventive engineering gates. These lessons govern the operating procedures in the canonical JennieJoy skills and error database (`error-db/`). Updating these procedures constitutes operational error prevention, not model-weight retraining.

Cross-reference:
- [Engine dispatch contract](engine-dispatch-contract.md) — Unified owner/trigger/output/consumer contract across all lanes.
- [Motion engineering lessons](motion-engineering-lessons.md) — Product motion and film grammar adaptations (source: `episode04/technical/source-research-v001/firecrawl-beamnxw.json`).
- [Milestones and errors](milestones-and-errors.md) — Error database JSON schema and incident recording rules.

---

## Case 01 — S01_A Storyboard v014/v015/v016: Incompatible/Missing Edit LoRA and Wrong Live-Action Route

### 1. Context & Symptoms
During S01_A storyboard candidate generation for *Milk and Mom*, three consecutive iterations failed to produce a valid film anchor:
- **v014** (ComfyUI prompt `cd98640f-046e-4e93-b510-17c17d5e60b4`, output SHA `19617eca3150c7222570595c24cc494d93194dfdb29aa85b6dca560490dd3839`): Generated a dark graybox scene with flat horizon. While two cows were behind the fence, the background lacked bright morning daylight, garden foliage, and sky depth. No Alice, Mother, or milkmaid actors were present.
- **v015** (ComfyUI prompt `df78c2c3-69dd-499e-9060-0e1e21a27b4c`, output SHA `1affd2fe0c07d9b8837177fcc45c1036672858a38a8e86c87f6a8b9c5ffc0897`): Added stylized flower and cow textures, but the upper half was a pitch-black void with an unnatural white patch instead of coherent blue morning sky. Alice, Mother, and milkmaid were absent.
- **v016** preparation attempted to fix the sky via a local ComfyUI composite (`S01_A_SKY_COMPOSITE_BLOCKER.json`), but execution was completely blocked: `blocked_missing_required_edit_lora`.

### 2. Root Cause Analysis
- **Missing/Task-Incompatible Edit LoRA (`confirmed`):** At the incident snapshot, the graph used `Krea2EditModelPatch` without a required task-compatible V2 edit LoRA immediately after the `UNETLoader`. The installed node documentation supports Identity Edit (`krea2_identity_edit_v2.safetensors`) for person restaging and General Edit (`krea2_general_edit_v2.safetensors`) for instruction-based scene/attribute edits. Neither LoRA is universal for every edit task. A bare Krea2 Turbo edit graph is structurally invalid, and the current fix must also verify the chosen upstream binding and installed hash rather than merely requiring a filename.
- **Cross-Domain Route Contamination (`confirmed`):** The worker attempted to import tools and node patterns designed for photorealistic live-action head/body swapping from the NEWTECONS project (`bfs_body_swap`, `bfs_head_swap`) into the JennieJoy stylized 3D preschool cartoon pipeline. Live-action face/body swappers degrade stylized cartoon geometry and fail to produce cohesive 3D animated aesthetics.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/storyboard-layout-v014/VISUAL-REVIEW.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/storyboard-layout-v015/VISUAL-REVIEW.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/storyboard-layout-v016/S01_A_SKY_COMPOSITE_BLOCKER.json`
- `production-local/ComfyUI/custom_nodes/comfyui-krea2edit/README.md`
- Error DB: `error-db/storyboard-v014-v016-missing-edit-lora-liveaction-leak.json`

### 4. Preventive Gate
- **Preflight Model/LoRA Dependency Gate:** Before queuing any local image-edit graph, select the LoRA compatible with the task (Identity Edit for identity/person restaging; General Edit for instruction-based scene or attribute work), inspect the live node schema, and verify the upstream binding and installed SHA256. If the task-compatible LoRA is missing or mismatched, withhold graph generation and fail closed; never submit a bare or broken graph.
- **Strict Domain Isolation:** Prohibit importing live-action photorealistic swap nodes (`bfs_body_swap`, `bfs_head_swap`) into `jenniejoy_cartoon_3d`. Character identity and wardrobe edits in cartoon 3D must use verified stylized character references, Blender guides, or authorized hybrid cartoon routes.
- **Status:** resolved for graph rejection and domain isolation only; no replacement output is certified by that closure.

---

## Case 02 — S01_A H3 Release Gap Despite Approved Opening Anchor

### 1. Context & Symptoms
The user-approved opening still for S01_A was confirmed and hash-locked:
- File: `storyboard/gpt-opening-v001/S01_A-user-approved-opening.png`
- SHA256: `2113acd0d7a3eb335c64e1e0145998a01d8d4a53624da70628501b7d5b8ab47f`
- Route: Built-in `image_gen` (Branch A), approved for visual cartoon quality.
- H3 864×480 input derivative: SHA `10157c61fc135af65ff616638b186a156c6fd09211e528004f10f70ad9003485`.
- Audio: Mother Mai WAV locked with SHA `5d33ad49807cd680ca28156e13c8863db1e54f788cc3f576957e1b23d93d900f`.

The initial orchestration audit found a planning/record gap after the required S01_A anchor and WAV were ready. It did not include dispatch timestamps that establish a sustained multi-hour delay or prove which prerequisites actually blocked execution. A later H3 job completed successfully in 305.8 seconds and produced a rendered candidate.

### 2. Root Cause Analysis
- **Unnecessary Prerequisite Coupling (`inferred; chronology not verified`):** The orchestration records coupled ready H3 work to independent lanes, including:
  1. The completion of an alternate local ComfyUI image candidate (Branch B) to stage a comparison;
  2. The generation of a complete 24-expression library for all characters;
  3. The implementation of the Python hybrid image coordinator ledger (`hybrid_image_coordinator_v001.py`);
  4. Final background music selection and full-episode audio mix.
  The audit establishes that this coupling was a risk in the board/contract, not that each item delayed dispatch for a measured duration. Timestamp evidence is required before claiming a multi-hour chronology or a confirmed blocking cause.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/storyboard/gpt-opening-v001/ACCEPTANCE.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-v001/PREPARATION-RECEIPT.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/engine-orchestration-audit-v001/AUDIT.md` (Finding P1-02)
- Error DB: `error-db/h3-stalled-waiting-unnecessary-prerequisites-s01a.json`
- Completed H3 history: prompt `71eacbde-2fdb-48c2-b2e9-0b03d0241dd2`, 124 native frames at 864×480/24fps, output SHA `9f05671fcbf308c8521297d8d4fd52f2880145ce38dc7d7883b4a8ce1664eaeb`; rendered candidate, not motion/lip acceptance.

### 4. Preventive Gate
- **Single-Shot Release Rule:** The first complete image anchor to pass hash-bound QA unlocks local H3 motion immediately, provided that shot's receipt WAV (the WAV named in its H3 preparation receipt, `wav.sha256`) is ready.
- **Zero Inter-Shot Blocking:** Never wait for an alternate hybrid comparator, subsequent scene storyboards, whole-cast expression packs, music stems, or full timeline finishing before submitting a ready H3 shot.
- **Status:** resolved for the existence of a completed H3 candidate. The earlier multi-hour chronology and each blocking cause remain unproven without dispatch timestamps.

---

## Case 03 — ComfyUI `SaveImage` Reload Loss and Unproven Studio Preview

### 1. Context & Symptoms
When ComfyUI generates an image or video frame via the standard `SaveImage` node, files are written to `ComfyUI/output/`. However:
- Reloading the saved workflow JSON in the ComfyUI web interface displayed empty output slots or blank default canvases.
- The JennieJoy Studio webapp (`http://127.0.0.1:5050/films.html`) could not display image-job preview thumbnails from workflow definitions alone, causing ambiguity during visual review and false reports that jobs had not completed.

### 2. Root Cause Analysis
- **ComfyUI Graph Architecture Limitation (`confirmed`):** In ComfyUI, `SaveImage` nodes perform file export during execution but do not retain an in-graph persistent buffer across UI reloads or server restarts. When a user opens a saved workflow, ComfyUI renders nodes from the JSON graph definition; without an explicit image loader node pointing to the output file, no image is rendered in the UI.
- **Missing Preview Ingestion Protocol (`confirmed`):** Studio API and external review tools require a supported registration and stable served media. Directly referencing `output/` files is not portable delivery. A companion ComfyUI review workflow and a Studio registration are separate systems; neither proves the other, and workflow JSON alone cannot establish that `/films.html` was updated.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/attach_comfy_result_preview.py`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/studio-publish-v001/catalog-with-preview.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/workflows/COMFY-JOBS-v003.json`
- Error DB: `error-db/comfyui-saveimage-reload-preview-loss.json`

### 4. Preventive Gate
- **Persistent Preview Pinning Protocol:** For every local ComfyUI image-generation job, maintain the original `SaveImage` in the production API graph. Resolve the helper under the active episode, not a root-level universal path, and record its result.
- **Four Independent Proofs:** Save (1) the Comfy GUI workflow import/reopen result, (2) supported Studio registration with truthful runtime ID or null, (3) HTTP media/hash and job/artifact readback, and (4) reopened `/films.html` display/playback. A `LoadImage` node alone is not a Studio preview assertion.
- **Status:** open until the four proof classes are captured for the target assets.

---

## Case 04 — S01_A Fence and Barn Spatial Geometry Failure & Scoped Blender Guide

### 1. Context & Symptoms
In *Milk and Mom* Scene S01_A (the outdoor morning garden and dairy enclosure):
- **v003 composite** showed three cows (script specifies exactly two), with animal legs and heads intersecting fence rails. The family garden and cattle corridor overlapped in an ambiguous depth plane, and Alice was depicted standing with an open mouth during Mother's dialogue.
- **v006** (prompt `fe34d87a-59af-454f-ac2e-efd509f3a93d`, output SHA `9c6854e5325a56f6710ef6b78609c73d4e79dbcb7da68a432e884658b9edf511`): Generated two cows and receding side fences, but failed to render a continuous front barrier, placing picnic furniture in the animal pen.
- **v007** (prompt `0c7be0b1-b098-4026-87d3-b296b5ebc195`, output SHA `1396f2fd8dacfdb1793a560ee90a49d106b526b209d110ed6547b06f22cf1e27`): Rendered two cows standing in front of the fence line on the family side.

### 2. Root Cause Analysis
- **Text-Only Diffusion Spatial Failure (`confirmed`):** Text prompts alone ("exactly two cows", "fully behind a closed front fence", "family garden completely separated from cows") cannot control spatial depth, enclosure topology, or contact geometry in modern diffusion models. Repeated re-prompting with identical or slightly modified text consistently produced barrier penetrations.
- **Lack of Rigid 3D Constraint (`confirmed`):** The models lacked an explicit geometric guide defining camera height, vanishing points, enclosure planes, and occlusion boundaries.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/concept/S01_A-CINEMATIC-BLOCKING-v004.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/storyboard-layout-v012/S01_A-CLOSED-PADDOCK-layout-v012.png` (SHA `9a2dea1d9e57f00f5921b75065487e71e37761b553442011c136a179b68e4b19`)
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/build_s01a_layout_v012.py`
- Error DB: `error-db/spatial-blocking-fence-cow-geometry-failure.json`

### 4. Preventive Gate
- **Deterministic 3D Spatial Layout Gate:** When a shot involves physical enclosures, animal containment, or exact prop contact, generate a deterministic Blender 3D layout guide before image generation.
- **Five-Plane Depth Verification:** Verify five distinct planes in the resulting frame:
  1. *Near foreground:* garden framing foliage.
  2. *Acting plane:* Alice kneeling screen-left on cushion, Mother seated screen-right on bench, sealed bottle in reach.
  3. *Barrier plane:* continuous front fence with posts and left/right returns (closed gate).
  4. *Farm plane:* Cow A side-on under open shelter beside seated adult Dutch milkmaid with stool and pail; Cow B grazing deeper in paddock.
  5. *Far plane:* receding pasture, restrained red barn, and tree line with consistent perspective.
- Reject any image where animals cross the barrier plane, regardless of prompt phrasing.

The Blender guide resolves the guide-geometry problem only. It does not validate a final diffusion frame, actor identity, cartoon styling or H3 motion. Keep those acceptance states separate. Status: resolved for guide geometry only.

---

## Case 05 — SeedVR2 7B 2K Full-Clip Container OOM; 4K Pilot Prepared but Not Run (history; superseded 2026-10-27 R27 by the v003 qualified pilot)

### 1. Context & Symptoms
During the 2K upscale pilot for a technical-only copied clip on 2026-10-26 (prompt `669e3b2e-8be0-48d7-a83c-09e7988ff3b2`):
- The `Comfyui-Studio` Docker container abruptly crashed and stopped running.
- Docker container inspection revealed: `OOMKilled: true`, exit code 1, after consuming the entire container memory limit of 30,064,777,216 bytes (30 GB).
- The full 124-frame clip could not be processed in that 2K graph. No 4K execution was observed, so the receipts do not prove a 4K failure.

### 2. Root Cause Analysis
- **Unbounded Full-Clip Memory Demand (`confirmed for the observed 2K job; exact allocation cause not isolated`):** Feeding all 124 frames through the observed 2K graph exhausted the 30 GB container limit. The receipt proves container death at that memory ceiling; it does not prove the same limit for 4K or establish a single allocation-based root cause.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/PLAN.md` (lines 61, 200–201)
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/upscale-pilot-v001/workflow-preparation-manifest-v001.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/upscale-pilot-v002/README.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/seedvr2-production-v001/README.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/seedvr2-production-v001/pilot/2160p/S01_A/PREPARATION-RECEIPT.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/upscale_seedvr2_chunked.py`
- Error DB: `error-db/seedvr2-2k-fullclip-container-oom-30gb.json`

### 4. Preventive Gate
- **Prepared Bounded Architecture:** Treat core32/context4/max40 as a planning ceiling that can reduce memory demand. It is not a proven runtime limit and cannot certify no OOM. Superseded 2026-10-27 R27: core32/context4/max40 is history; the qualified recipe is tile768/overlap64/internal17/raw21 (v003 `technical/seedvr2-production-v003/pilot-interior21-internal17/S01_A/qualification-v003.json`, prompt `43f87ebe…`; see [comfyui-video-pipeline SeedVR2 section](../../comfyui-video-pipeline/SKILL.md#seedvr2-7b-bounded-4k-restoration)).
- **Measured 4K Pilot First:** The final 3840×2160 Master is mandatory; 2K review is optional (superseded 2026-10-27, PLAN T-V10). Before a batch, run a short pilot at the actual chosen 4K processing size/settings. The current episode-owned 2160p candidate is 16 frames total (12 core + 4 trailing context), status `PREPARED_NOT_RENDERED`, with no prompt ID or output. Superseded 2026-10-27 R27: that 16-frame candidate was never rendered; it is replaced by the v003 21-frame internal17 pilot (PASS, technical only) and the `seedvr2-production-v004` plan (14 shots, 134 chunks, `PREPARED_NOT_RENDERED`).
- **Memory and Media Evidence:** Record peak host/container RAM, GPU VRAM, prompt/history status, output decode, exact frame count and seam review. Keep the earlier 2K failure and technical-only provenance intact.
- **Sequential Execution & Recombination:** Process chunks serially under `.comfyui-image-submit.lock`, trim context frames, concatenate core frames, and keep source audio separate until decode/seam checks pass.
- **Status:** open. The 2K full-clip OOM is observed; the 16-frame 4K pilot is prepared but not rendered. Superseded 2026-10-27 R27: the v003 21-frame internal17 pilot passed technically (`technical/seedvr2-production-v003/pilot-interior21-internal17/S01_A/qualification-v003.json`); the v004 production plan is `PREPARED_NOT_RENDERED` (14 shots, 134 chunks); no full-film seams are checked or accepted.

---

## Case 06 — Audio-Only Trim Risk vs. Video Timing & Exact Last USED Native Frame Endpoint

### 1. Context & Symptoms
During initial postproduction assembly of S01_A:
- H3 generated 124 native frames at 24fps (5.1667 seconds).
- The preparation script selected 120 used frames (5.0 seconds) and designated frame 119 as the carry frame for S01_B.
- The Remotion finishing script (`editorial/finishing-v001/src/index.jsx`) started `OffthreadVideo` at source time 0, but applied a leading silence trim to the dialogue audio using `startFrom=trim_start_frames`.
- Concurrently, caption manifest v001 allocated 140 delivery frames at 30fps (4.6667 seconds), conflicting with root's 5.0-second editorial cut.

### 2. Root Cause Analysis
- **Unpaired Audio Trimming (`confirmed integration risk; no affected final export observed`):** Trimming leading silence inside the compositor while playing video from source frame 0 advances speech relative to picture. The source review established the risk; it did not observe severe desynchronization in a completed export.
- **Endpoint Truncation Mismatch (`confirmed`):** Shortening a shot from 5.0 seconds (120 frames at 24fps) to 4.6667 seconds in the timeline while carrying native frame 119 into the next shot causes a temporal jump, discarding 8 frames (0.3333s) of visual action that the audience never saw.
- **Frame Rate Conversion Neglect (`confirmed`):** Failing to establish a mathematical mapping between native generation FPS (24fps) and delivery timeline FPS (30fps) caused rounding errors in frame interval calculations.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/engine-orchestration-audit-v001/AUDIT.md` (Finding P0-01)
- `production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/finishing-v001/src/index.jsx`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/prepare_finishing_v001.py`
- Error DB: `error-db/audio-video-trim-desync-carry-endpoint-mismatch.json`

### 4. Preventive Gate
- **Single Upstream WAV Trim Rule:** Each shot has exactly one dialogue WAV: the WAV named in that shot's H3 preparation receipt (`technical/motion-v00N/<SHOT>/preparation.json` → `wav.sha256`; S01_A: `technical/hybrid-v001/job.json` → `wav_sha256`), whose SHA256 the H3 job receipt must record identically (the receipt WAV), bound identically (same file, same start offset) to H3 audio conditioning and Remotion subtitle/soundtrack lanes. If silence is trimmed, perform it ONCE before H3 motion generation so the receipt records the trimmed file; a trim made after H3 is a different file and must never replace the receipt WAV (R27, episode04 S01_A: untrimmed `5d33ad49…`, see `technical/audio-binding-r27/S01_A-WAV-BINDING-DECISION.json`).
- **Paired AV Manifest:** Store native FPS (24), used native frame interval, picture start offset, delivery FPS (30), delivery frame count, and carry frame index in a single per-shot manifest.
- **Exact Last USED Frame Carry:** In continuous shots, the frame carried into the subsequent shot must be the exact last USED native frame (e.g., frame 119 for a 120-frame shot), corresponding strictly to the visual exit point.
- **Acceptance Scope:** A validated scoped shot preview can be recorded separately, but full-timeline AV resolution remains open until the actual export is rendered and reviewed.
- **Status:** open.

---

## Case 07 — Missing Production Lane Ownership: Music, SFX/Foley, Postproduction & Studio App Publishing

### 1. Context & Symptoms
At the MAM-AUDIT-STUDIO milestone:
- The project PLAN listed unowned lanes, stale task statuses, and interrupted child tasks marked as active.
- Music and SFX were grouped under a generic audio category without separate stems, ducking rules, or licensing verification.
- A finishing scaffold already existed. The audit did not establish that Remotion/HyperFrames waited for every clip; delay causes require timestamped evidence.
- The JennieJoy Studio catalog actually contained one genuine completed H3 job and seven indexed image jobs; its artifact list was empty. This corrected count separates “jobs exist” from “reviewable delivery artifacts are published.”

### 2. Root Cause Analysis
- **Missing Lane Accountability (`observed`):** The PLAN had missing/stale ownership assignments. Whether this caused specific editorial delays is an inference, not demonstrated chronology.
- **Scheduling Delay (`inferred/unverified`):** Pausing independent CPU/cloud lanes while the GPU was idle is a possible explanation, but the cited audit does not prove that timeline. Preserve the verified ownership and publication gaps separately.
- **File Creation Mistaken for Delivery (`confirmed`):** Saving a file to disk without registering its genuine job ID, preview URL, and SHA256 hash in Studio webapp left assets invisible to reviewers.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/engine-orchestration-audit-v001/AUDIT.md` (Findings P1-02 & P1-05)
- `production-local/JennieJoyKids-Story/04-milk-and-mom/audio/sfx-v001/README.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/finishing-v001/README.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/studio-publish-v001/catalog-readback.json`
- Error DB: `error-db/production-lane-orphan-unowned-finishing-delivery.json`

### 4. Preventive Gate
- **Mandatory Complete Lane Assignment:** Before expensive GPU inference begins, assign an explicit owner and task ID to every lane: Director/Prompts, Character Librarian, Spatial Layout (Blender), Hybrid Storyboard, Voice, Subtitles, Background Music, SFX/Foley, H3 Motion, SeedVR2 Upscale, HyperFrames Graphics, Remotion Master, Studio Publisher, and Independent QA.
- **Stems Separation & Ducking:** Music and SFX must be separate stems. Music is ducked under speech; SFX/Foley peaks are synchronized to visual contact points.
- **Continuous Studio Publishing:** The publisher registers each real Comfy job ID and then separately records Studio registration, HTTP media/hash readback and reopened UI display/playback. Reuse and imagegen artifacts may truthfully use a null runtime ID. File existence, a workflow JSON, or a job count alone is not delivery.
- **Status:** open. Explicit lane assignment is fixed, but reviewable delivery remains incomplete.

---

## Case 08 — Hybrid Coordinator Unknown Outcome Duplicate Retries & Receipt Validation Gaps

### 1. Context & Symptoms
During automated hybrid image coordinator dispatch testing:
- A network timeout or unresolved HTTP response (`status: unknown`, `error: HTTP timeout; remote job may still run`) was passed to the `fail` command. The coordinator marked the attempt as failed, unlocking an automatic duplicate retry attempt (B-002).
- An unrelated, failed dispatch receipt from a different film/shot was passed with a generated UUID; the coordinator accepted the receipt and recorded the attempt as queued with `kind: real_dispatch_receipt`.
- Registering a shot and later attempting to adopt an existing approved image returned `changed: false`, leaving H3 handoff blocked in `waiting`.

### 2. Root Cause Analysis
- **Unverified Failure Assumption (`confirmed`):** `tools/hybrid_image_coordinator_v001.py` treated any non-zero failure report as a confirmed terminal failure, disregarding that an upstream job may still be executing on the server.
- **Syntax-Only Receipt Validation (`confirmed`):** The coordinator validated only UUID format, omitting checks for matching `film_id`, `shot_id`, `branch`, `route`, or successful server submission response.
- **Idempotency Gate Ordering Flaw (`confirmed`):** In registration, the unchanged-return check ran before processing `--existing-output` and `--approval` flags.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-coordinator-v001/PYTHON-REVIEW.md` (HIGH & MEDIUM findings)
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-coordinator-v001/PYTHON-REVIEW-HASHES.json`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/hybrid_image_coordinator_v001.py`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-coordinator-v001/FOLLOWUP-REVIEW.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-coordinator-v001/FOLLOWUP-REVIEW-HASHES.json`
- Error DB: `error-db/hybrid-coordinator-unknown-outcome-duplicate-retry.json`

### 4. Preventive Gate
- **Terminal Failure Verification Gate:** Never treat an unresolved or timeout outcome as a terminal failure. Keep the attempt in `in-flight` state and require root to reconcile the live ComfyUI queue/history or verify non-execution before unlocking a retry.
- **Strict Semantic Receipt Validation:** Validate that all dispatch receipts match the current `film_id`, `shot_id`, `branch`, `route`, and registered workflow SHA256, and confirm an HTTP success response before recording a job as `queued`.
- **Adoption Processing Precedence:** Process and validate existing-output adoption before returning idempotent registration status.
- **Scoped Closure:** Bind the fixed coordinator closure to reviewed source SHA `b5805c45337141e313d35c47301f4842a5a85409d0382cc44c8781ec91f046ae` and the `FOLLOWUP-REVIEW.md` result of 16/16 tests. Retain its medium findings and the single-writer restriction; the review did not certify a distributed lock or act as a live remote-job verifier.
- **Status:** resolved for the two prior HIGH findings at the reviewed source hash; medium findings and the single-writer restriction remain.

---

## Case 09 — Finishing Pipeline Premature Placeholder Unlock & 1080p Resolution Hardcoding

### 1. Context & Symptoms
During independent code review of the Remotion finishing pipeline (`technical/finishing-review-v001/REVIEW.md`):
- **Premature Full Render Unlock (H1):** `full_timeline_ready` in `prepare_finishing_v001.py` evaluated four timing/source flags but did not verify the presence or validity of real video clips for all dialogue slots. A timeline could unlock while 11 shots remained `null`, resulting in Remotion rendering eleven "H3 PENDING" placeholder slots.
- **1080p Hardcoding (H2):** Composition dimensions, coordinate spaces, render scripts (`render.cjs`), and assertions were strictly hardcoded to 1920×1080, providing no route to deliver the requested 4K 3840×2160 Master or 2K 2560×1440 review render.
- **Audio Truncation via `endAt` (H3):** `<Audio endAt={shot.audio.trim_end_frames}>` calculated end boundaries using `round(full_duration_s * 30)`, shaving off 3.3ms to 13.3ms of dialogue audio (e.g. S06_B lost 13.333ms).
- **Missing Linter (H4):** Reused `jenniejoy-zoo-film` lacked `eslint-plugin-react-hooks` configuration.

### 2. Root Cause Analysis
- **Boolean Flag Trust without Asset Verification (`confirmed`):** The readiness gate checked whether metadata flags were boolean `true` rather than verifying that 12 real, valid, hash-checked MP4 clips existed in the source manifest.
- **Fixed-Resolution Coordinate Space (`confirmed`):** Layout and SVG elements lacked a resolution multiplier or responsive scaling, causing half-scale rendering if dimensions were manually doubled.
- **Frame-Rounding Boundary Inaccuracy (`confirmed`):** Applying `round()` to audio durations on frame boundaries created fractional frame loss.

### 3. Verified Evidence Paths
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/finishing-review-v001/REVIEW.md`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/finishing-v001/src/index.jsx`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/finishing-v001/render.cjs`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/tools/prepare_finishing_v001.py`
- Error DB: `error-db/finishing-pipeline-placeholder-unlock-and-1080p-hardcode.json`

### 4. Status & Preventive Gate
- **Status:** `open` (builder changes reported in a concurrent branch; no current fix has independent verification; full-film Master remains blocked).
- **Mandatory Asset Manifest Gate:** Pre-render gate must inspect the real media manifest and require all 12 clips to exist, decode successfully, and match expected hashes before full render unlocks.
- **Dual Delivery Profiles:** Explicitly support 3840×2160 (Master) and 2560×1440 (Review) profiles with a 2× coordinate space scaler.
- **Zero-Trim Audio Playback:** Dialogue WAVs play at source offset zero without `endAt` truncation.

The existing 15-second intro/outro preview remains a candidate only. A skill rule or reported code change is not evidence that the builder defect is resolved.

---

## Case 10 — H3 v003 Spatial Restaging, Foreground Drift and Continuous-Cut Semantics

### 1. Observed Symptoms
Actual v003 contact sheets show failures in the sampled motion:
- **S02_A:** after the opening sample, Cow A and the milkmaid enlarge and occupy the family-side foreground; the front fence stops separating the planes and the shelter shifts relative to the family.
- **S03_A:** the milkmaid appears from the right carrying a large metal pail, joins the family grouping and changes scale/depth as the camera reframes; the intended distant milking station is no longer preserved.
- **S05_A:** the background scale becomes excessive and the framing shifts into a large cow/worker close-up.
- **S04_A:** the sampled contact sheet is materially better and was not rejected by this review, but that sample is not a full motion, lip or final acceptance.

### 2. Cause Status
- **S02_A semantic prompt conflict is observed:** the writeup asks for a continuous camera extension from S01_B, prominent milking/udder detail and a fixed new camera angle in the same shot. A carry-style transition and a motivated cut to a new angle describe different editorial semantics and must not be combined silently.
- **S03_A creative-direction conflict is observed:** a dolly and preservation of the incoming composition compete, while long production notes can dominate the small token gesture that should drive performance.
- **Standalone-reference salience is a hypothesis:** the integrated scene plus three large standalone identity images plausibly increases milkmaid foreground salience, but no isolated A/B test has established that cause.
- **The shorter-prompt fix is not proven:** v004's approximately 1,600-character prompt, single integrated-scene reference and image-only end guide are a bounded trial. About 1,600 characters is not a correctness threshold.

### 3. Verified Evidence
- `production-local/JennieJoyKids-Story/04-milk-and-mom/clips/motion-v003/S02_A-contact.jpg` — SHA256 `c2f475e82f23b24594edf07bfb2bc1daa8b20be24b0b919f503f3aeca1ac9cde`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/clips/motion-v003/S03_A-contact.jpg` — SHA256 `9cc9354e3443e1b775eda2a9696c36b6c3d1d6a4586bfeb47e53ffc84604f4a6`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/clips/motion-v003/S05_A-contact.jpg` — SHA256 `d1342169c1ac7834bf2b477fac6a68e13389817ff15d9f029e4b7864e1ce943b`
- `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/motion-qa-v004/REPORT.md` — independent v004 graph/carry review; permits one S02_A pilot only.
- S02_A v004 job receipt records queued prompt `e5807445-bc27-4269-99d6-71111098ec64`.
- Error DB: `error-db/h3-v003-spatial-restaging-and-carry-semantics.json`

### 4. Preventive Gates
- **Keep Model Prose for Visible Acting:** Put concise cast appearance, spatial placement, props, speaker/listener state and the one required performance in the model prompt. Keep paths, hashes, receipts, proposal IDs and long production metadata in the manifest and receipt.
- **One Transition Semantics per Shot:** Record `carry` or `motivated_cut` explicitly. A carry uses the exact accepted last USED frame. A new angle uses a motivated cut and must not also promise continuous camera extension.
- **Endpoint Guides Are Not Masks:** `MiniMaxH3AddGuide.frame_idx` is a frame index and the image-only guide appends conditioning at that endpoint. It is not a pixel lock, background mask or proof that intervening frames remain stable. For the inspected 141-frame graphs, use the actual endpoint index: 127 for 128 used frames and 139 for 140 used frames.
- **Visible Output QA Before Carry:** Inspect early, middle, late and decoded-end frames plus a normal-speed pass. Reject fence crossings, family-side restaging, abrupt depth/scale changes, missing educational action or prop/identity drift before any carry or upscale.
- **Pilot Gate:** Superseded 2026-10-27 R27: the S02_A v004 pilot was rendered and has a sampled visual pass (sampled-visual-usable candidate, `technical/motion-qa-v005/INDEPENDENT-MOTION-QA-v005.json`); full-speed AV acceptance is still open. A passing frame or workflow hash does not guarantee motion fidelity.
