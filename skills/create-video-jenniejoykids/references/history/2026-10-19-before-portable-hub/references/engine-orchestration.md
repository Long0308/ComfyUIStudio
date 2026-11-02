> Current incremental editing contract: [scoped rebuilds and auxiliary nodes](incremental-pipeline.md). The Milk corrected1080p direct-output instruction is recorded in [revision v2](milk-revision-v2.md); do not invent approval for the rejected draft.

# Engine ownership and production handoffs

Use motion-reference lessons to improve the project's story, timing and legibility. A product-demo tutorial is design guidance, not a request to replace a preschool cartoon with software footage, a square canvas, 20 seconds or 30 fps. The current zoo film remains 16:9, 24 fps, six scenes and 60 seconds. Other projects declare their own type, audience and delivery in project JSON.

## Ownership

Với luồng Blender/AI đang mở rộng, đọc [local Blender asset bridge](blender-local-ai.md).
Blender sở hữu geometry/modules/rig/Action/camera và render thật; project node
`JennieBlenderRender` tự chạy script trong process riêng. H3 nhận ảnh render làm
reference/guide, không trực tiếp tạo rig Blender. Vật dụng có GLB/BLEND/PNG/recipe
riêng; Remotion có thể dùng render icon qua adapter hậu kỳ mà không sinh lại shot.
Ảnh/reference có thể lấy từ mạng; nơi inference và nguồn TTS/imagegen ghi riêng.

| Owner | Input JSON and assets | Output and acceptance evidence |
| --- | --- | --- |
| GPT Image2 or declared image engine | IMAGE JSON; complete inline cast; approved identity sheets; composition, pose, light and reference bindings | Versioned sheets/keyframes with engine/settings, paths/hashes and review status. Generated lettering is disabled for this film. |
| Native ComfyUI H3 | VIDEO JSON; complete cast again; identity images; accepted preceding editorial frame when continuous; voice guide; installed workflow | Immutable full native AV, workflow/settings/seed, request/job ID and measured media metadata. Inspect acting, actual action result, identity, spatial continuity and speech independently. |
| Saved VoiceStudio Alice | AUDIO JSON exact lines/performance; saved approved profile `8f1145d7`; source WAV | Versioned WAV and line timing/clarity evidence. In `canonical_voicestudio`, the verified track owns editorial dialogue. Apply [voice clarity](voice-clarity.md); never re-clone by default. |
| Hyperframes | EDIT timing plus exact branding/callout content, design tokens, duration and transparent-layer contract | Frame-clocked branding or graphic sequence; export frames/clip plus metadata for the master timeline. It does not own character locomotion or duplicate the master edit. |
| Remotion | EDIT JSON; accepted native picture, approved Hyperframes graphic, captions and separate VO/BGM/SFX stems | Deterministic master composition, 720p review variants and QA artifacts; 1080p only after explicit draft acceptance. |

Choose one owner for each visible or audible layer. H3 creates character acting, contact, gaze, body turns and in-world camera motion. Remotion/Hyperframes own exact typography, titles, captions, learning cues and controlled editorial transforms. A pan over a still or a sliding cutout does not satisfy walking through a gate. Do not duplicate camera motion in both engines without a deliberate combined result.

## Handoff contract

Keep the existing project schema and compiler outputs (`image.json`, `video.json`, `audio.json`, `edit.json`, `project-manifest.json`). Store reference evidence and shot planning in a standalone [motion-plan sidecar](../schemas/motion-plan.schema.json); do not add arbitrary fields to project JSON. Markdown brief/reference documents are readable intake companions, not executable requests. The [creative example](../examples/motion-zoo-entry.json) demonstrates fields rather than an accepted production shot.

Every asset handoff identifies project/scene/segment, owner, source paths/hashes, input artifact version, actual job ID where applicable, settings and status. Carry complete cast descriptions into every IMAGE/VIDEO segment; IDs and sheets never replace them. Preserve planned timing separately from measured timing. Record source dimensions/frame rate/time base/PTS separately from export settings, and document crop/pad/scale and time mapping. An export resolution or conditioning input proves neither native detail nor successful voice preservation.

Validate JSON before submitting. Confirm queue/history before retrying; an existing pending ID is work in progress. Preserve raw outputs and accepted versions. New edits/replacements get new versions and retain provenance. Resource handoff follows [GPU handoff](gpu-handoff.md); do not interrupt an active Comfy job to prepare narration.

## Review stages and continuation

Set per-project `review_stage` in the planning sidecar. For a new request to review a shot plan first, return the brief, reference findings, timecoded shot plan, engine assignments and unresolved evidence; wait for feedback before that plan's implementation. If a different stage was requested, stop at that stage. Record scope, artifact/version and decision; approval of one stage does not imply approval of all later stages.

Preserve existing authorization when introducing this workflow. The current six-scene Comfy production was already authorized. S01_A and S01_B-entry-v2 both generated technically valid MP4s, but the user rejected the entry direction and requested BOTH clips be remade in one dependent Run. The old B prompt's turn-away instruction is superseded; do not reuse or accept it. See [continuous shots](continuous-shots.md). Successful encoding is not story, voice or visual acceptance. The separate mandatory gate remains: render 1280x720 draft, obtain explicit user acceptance of that draft, then enable 1920x1080 final. Historical baseline acceptance cannot satisfy a new draft's gate.

Compare each new scene with its corresponding saved Higgsfield baseline, labelled as a historical baseline. No tutorial `reference.mp4` was attached; do not claim to have measured it. Current opener text is exactly `JennieKidJoys` and `Let's Go to the Zoo!`, lasting 22 frames at 24 fps (0.916667 seconds). This is a current-project setting, not a universal intro duration.

Use [motion direction](motion-direction.md) for evidence and shot grammar and [postproduction QA](postproduction-qa.md) for existing finishing checks. Report pending checks explicitly; an offline validator is not visual, listening or runtime acceptance.
