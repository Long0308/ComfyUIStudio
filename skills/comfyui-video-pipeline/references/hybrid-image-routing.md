# JennieJoy parallel hybrid image routing

**Last updated:** 2026-10-27 (Asia/Bangkok). **Domain:** `jenniejoy_cartoon_3d` only.

Use this contract for the user's authorized JennieJoy image creation/editing and storyboard work. It does not change NEWTECONS live-action permissions or its local ComfyUI default. Read the [film skill](../../create-video-jenniejoykids/SKILL.md) and [per-shot orchestration](../../create-video-jenniejoykids/references/parallel-e2e-orchestration.md) for cast, WAV, continuity and downstream motion requirements.

## Two independent branches, one heavy CUDA owner

| Branch | Actual engine | Dispatch and provenance |
|---|---|---|
| A — native cloud image | Built-in `image_gen` tool | Dispatch through the tool outside the local ComfyUI prompt. Save the edit/generation prompt, exact reference paths/hashes, returned output and SHA256, tool evidence and requested/observed model separately. If the tool does not expose its exact model, `observed_model` is `null` / unknown. |
| A — optional partner alternative | Installed ComfyUI cloud image partner node | Use only after its auth and billing are verified. Save the real API/GUI graph, selected model input, prompt ID, response/output hash and available provider evidence. A node's installation or display label does not verify access, billing or a completed request. |
| B — independent local image | Local ComfyUI models on RTX 5080 | Save an editable local API/GUI graph, actual model/LoRA roles and hashes, seed, inputs, prompt ID, output SHA and pixel QA. Build B from the same accepted cast, brief and spatial inputs; do not quietly make it a GPT-derived edit or use A's output as an independent comparator. Label any intentionally derived diagnostic as derived. |

When the shot has no accepted image, dispatch A and B concurrently where resources permit. Native A/cloud and CPU preparation can run while B owns CUDA. One local ComfyUI queue processes its prompts sequentially: submitting two prompts, or saving two branches inside one graph, does not establish simultaneous inference. A partner prompt sharing that queue may also serialize; report actual start/end times before claiming overlap.

Root owns the single heavy CUDA schedule across local images, H3, SeedVR2, VoiceStudio GPU work and GPU encoding. Check `/queue`, `/history`, existing receipts, output hashes and live GPU occupancy before submission/retry. Do not interrupt an unrelated owner. Keep preparation, queue wait, inference and review durations separate.

The **first hash-bound QA-accepted complete image** may advance to local H3 as soon as that shot's exact final WAV and other inputs are ready. Do not wait for the alternate image branch, later storyboards or the whole expression library. Output arrival order alone never selects a winner. If B is already using CUDA, finish/reconcile that bounded job and hand over the GPU; do not claim H3 runs concurrently on the same heavy CUDA slot. An unstarted optional B retry must not hold a ready H3 shot.

If an accepted image already exists, reuse its verified bytes and acceptance scope. Do not regenerate it just to stage a two-branch race. An alternate local diagnostic can continue independently without becoming a new prerequisite or silently replacing the accepted anchor.

## Real installed cloud nodes

These are observations of local `http://127.0.0.1:8188/object_info`, captured in the [node catalogue receipt](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-skill-v001/live-node-catalogue.json). Recheck the live schema before building a new graph.

| API `class_type` | Observed display name | Meaning |
|---|---|---|
| `OpenAIGPTImage1` | `OpenAI GPT Image 2` | Image output. Its optional `model` combo includes `gpt-image-2` (observed default), `gpt-image-1.5` and `gpt-image-1`. The class suffix `1` does not mean the selected model is Image 1. Record the actual queued model input. |
| `OpenAIGPTImageNodeV2` | `OpenAI GPT Image 2.5` | Image output with a dynamic model schema, including observed `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`, `gpt-image-2`, `gpt-image-1.5`, `gpt-image-1` keys. Do not alias this class to `OpenAIGPTImage1` or assume its display name identifies the selected model. |
| `OpenAIChatNode` | `OpenAI ChatGPT` | `STRING` output for chat/text. It is not an image-generation node. |
| `LoadImage` | `Load Image` | Real local PNG import with `IMAGE`/`MASK` output. It proves file ingestion, not cloud inference. |

The image partner schemas expose Comfy auth inputs. **Partner auth and billing are unverified in this handoff; no partner image submission or successful partner run is claimed.** This does not revoke the user's existing native built-in image authorization or add a new user approval pause for that route. A requested or queued model value records configuration; distinguish it from a provider-confirmed resolved model.

## Native imagegen → real ComfyUI import

1. Reuse accepted cast/wardrobe hashes and a saved Blender layout if the shot needs it. For an edit, inspect the supplied image and bind the actual references to the native image tool. Preserve the complete prompt and reference mapping.
2. Save the returned native PNG in the episode's versioned storyboard directory. Keep its original tool-output path, copy hash and route evidence. Never invent a local ComfyUI prompt ID for this tool call.
3. Review the complete frame's pixels: coherent cinematic 3D cartoon style, cast identity/age/clothes, closed silent mouths, hands/contact/shadows, topology and occlusion. For S01_A the two cows stay fully behind the continuous front fence and returns. A background or graybox is not a full-cast anchor.
4. Import the exact accepted PNG into ComfyUI's input storage, verify the imported SHA equals the accepted SHA, and bind the actual filename through `LoadImage` in the editable H3 graph. Preserve any resize/crop as a separately hashed derivative with its source mapping.
5. Publish a versioned GUI review/import graph and verify the actual image after reopening. For locally generated/partner-generated images, preserve the source graph's `SaveImage`; native imagegen has an external tool receipt plus a real `LoadImage` import. Do not add a fake cloud node or claim a disconnected partner node generated that imported image.

Image acceptance covers the still only. H3 motion, speaking/listening mouths, native AV, final-WAV alignment, continuity and final film acceptance require their own real output/hash reviews.

## Repeated local failures and provenance

After **two consecutive local pilots/errors with the same defect**, stop automatic local retry. Independently inspect the task recipe, source graph, installed node schema, model/LoRA role and hash, mask coordinates, image/latent bindings and actual queued prompt. Record the two failure IDs/output hashes and reviewer findings before another local attempt. Use the already authorized GPT support in parallel with the diagnosis; do not let a local retry loop hold independent CPU/cloud lanes or a ready accepted anchor.

Keep each branch's receipt separate: `film_id`, `shot_id`, revision, branch/route, creator/actual agent model if exposed, requested model, observed/resolved model or `null` with evidence, prompt text/hash, reference path/hash/role, workflow/API/GUI paths and hashes, local prompt/provider job ID only when real, timestamps, output path/SHA, review verdict/reviewer/acceptance scope and next consumer. Never copy a requested model into the observed field merely because a name was requested.

| State | Minimum evidence |
|---|---|
| `prepared` | Saved script/graph/contract; no inference is implied and `prompt_id`/`job_id` is `null`. |
| `queued` | Actual submission/readback and real prompt/job ID. |
| `rendered_candidate` | Actual media bytes and SHA; QA still pending. |
| `rejected` | Output/error evidence and explicit defect; retain historic bytes and receipt. |
| `accepted_image` | Pixel review bound to that exact image SHA and a recorded scope. |
| `h3_ready` | Accepted imported image, exact final WAV and required cast/shot inputs bound to the saved H3 graph; no motion output is implied. |
| `accepted_shot` | Real generated clip/hash with required visual, listening, lip and continuity review. |

## Milk and Mom S01_A: reuse approved A

The [native image acceptance](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/storyboard/gpt-opening-v001/ACCEPTANCE.json) records the user's approved opening still:

- File: [S01_A-user-approved-opening.png](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/storyboard/gpt-opening-v001/S01_A-user-approved-opening.png).
- SHA256: `2113acd0d7a3eb335c64e1e0145998a01d8d4a53624da70628501b7d5b8ab47f` (rechecked while writing this reference).
- Actual route: built-in `image_gen`; requested model `GPT Image Gen 2`; resolved model `null` because the tool exposed only image/path evidence.
- Accepted scope: opening still visual quality. Motion and lip sync remain unverified. Reuse this A for H3; do not rerender A or wait for B.

The [H3 preparation tool](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/tools/prepare_hybrid_h3_s01a_v001.py) has saved the [API graph](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/workflows/hybrid-v001/S01_A_HYBRID_A.api.json), [GUI graph](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/workflows/hybrid-v001/S01_A_HYBRID_A.workflow.json) and [preparation receipt](../../../../production-local/JennieJoyKids-Story/04-milk-and-mom/technical/hybrid-v001/PREPARATION-RECEIPT.json). At this documentation checkpoint the receipt says `READY_FOR_ROOT_GPU_SCHEDULING`, `gpu_submitted: false`, `cloud_called: false`, `b_branch_executed: false`. The H3 image is a separately recorded 864×480 derivative SHA `10157c61fc135af65ff616638b186a156c6fd09211e528004f10f70ad9003485` of the approved source; do not confuse those hashes. The Mother WAV is bound by SHA `5d33ad49807cd680ca28156e13c8863db1e54f788cc3f576957e1b23d93d900f`.

The coordinator implementation is assigned to `tools/hybrid_image_coordinator_v001.py` with episode receipts under `technical/hybrid-coordinator-v001/`; those paths are still being prepared by its owner at this checkpoint and are not evidence of a run. Read current receipts before acting: documentation, a tool script and a saved workflow are not proof that A, B or H3 executed. H3's prepared A handoff does not depend on completion of B or the coordinator implementation.

Related contracts: [GPU handoff](../../create-video-jenniejoykids/references/gpu-handoff.md), [native H3](../../create-video-jenniejoykids/references/comfy-h3.md), [Blender spatial handoff](../../create-video-jenniejoykids/references/blender-storyboard-control.md), [continuity](../../create-video-jenniejoykids/references/continuous-shots.md).
