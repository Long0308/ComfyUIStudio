# Native local ComfyUI H3 profile

Primary sources:
- https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native
- https://huggingface.co/Comfy-Org/MiniMax-H3
- https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_r2v.json
- https://github.com/comfy-org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py

Exact files/hashes: h3-model-selection.json. Use Ref2VA pruned INT8 + Qwen3VL32B
NVFP4 AWQ + videoVAE INT8 + audioVAE FP32. FL2VA is a separate family; do not
download it by default. Official12GB/480p guidance is community-verified, not a
benchmark of this particular desktop. Four files total40,073,842,159bytes.

Native node MiniMaxH3ReferenceToVideo accepts clip,vae,audio_vae,prompt,width,
height,length,ref_image_size and dynamic ref_images/ref_audios slots. The official
template leaves ref_audios.ref_audio_0 unconnected. With native speech enabled,
the packaged builder connects LoadAudio to it AND audioVAE to audio_vae. Explicit
visual-only voiceover mode omits speech conditioning, while canonical WAV stays
available for editorial. Tags <Picture1>/<Audio1> must follow
actual input order (with spaces as <Picture 1>, <Audio 1>).
MiniMaxH3AddGuide can anchor image/audio at frame_idx in versions supporting it;
verify /object_info rather than assuming reference conditioning preserves WAVs.
The builder's optional `first_frame` input accepts a staged Comfy input-relative
image filename. For a continuous second subshot, extract the preceding accepted
shot's final EDITED frame: frame119 for a5s/24fps cut, rather than unused native
tail frame123. Keep the original identity-image references and full descriptions
as well as this pose/location guide. Record the source MP4 hash, frame index and
staged image hash. A first-frame guide helps continuity but does not prove the
requested movement occurred; inspect the full threshold crossing at normal speed.
Select editorial audio by engine.audio_mode. The current Alice project uses
canonical_voicestudio: original VoiceStudio VO remains authoritative in editing;
exclude duplicate generated speech from its editorial mix. In preserve_native
mode, accepted native generated VO is authoritative and remains fully in the
edit after identity, words, timing and listening review; do not replace it with
the canonical guide. Both modes preserve complete raw native video/audio as
immutable sources. Generated ambience in canonical mode requires dialogue-free
isolation/listening review; otherwise use separate approved SFX/music stems.

Builder: scripts/build_comfy_workflow.py consumes a JSON config and emits native
API prompt + provenance; dry-run only. Validate installed /object_info/model file
names before queueing. No paid API classes. Do not resubmit a pending prompt ID.
Source-derived graph validation is not installed-runtime or GPU acceptance.
The API payload omits client_id: a fabricated websocket ID hides progress from
the local UI. Preserve ComfyUI broadcast progress; do not invent a client ID.

Text encoder placement: config `text_encoder_device` accepts `default` (the
default, letting ComfyUI manage GPU/offload placement) or explicit `cpu` for
diagnostics. The selected value is recorded in workflow provenance. Do not force
CPU for the Qwen32B encoder during normal commissioning; CPU-only linear work
was observed to stall the pilot with low GPU utilization. Automatic placement
still requires measured memory/time review on this desktop.

Isolate CUDA13.0 PyTorch from VoiceStudioCUDA12.8. Pilot864x480,124frames,24fps,
20steps,res_multistep,beta,refsize match,seed recorded,turbo off,batch1,offload.
864x480 is model-aligned~16:9; preserve geometry through small padding to16:9 in
editing. Trim124to120 only after confirming speech fits. 10s needs243frames.
Use two5s sub-shots per10s logical scene if memory requires, with full descriptions
in both. Draft1280x720 first; final1920x1080 only after user acceptance. A1080p
upscale is not native1080p inference. Record peakGPU/RAM,time,model/version/hashes.

## Observed Windows commissioning lessons

Stage loader assets directly in ComfyUI/input with unique filenames, such as JennieJoyKids_alice1.jpg and JennieJoyKids_S01_A-guide.wav. Current LoadAudio/LoadImage dropdowns enumerate top-level files; valid subfolder paths may execute through the API but the frontend can flag four invalid selections. Refresh the node inventory and import the corrected uniquely named workflow.

Observed H3 sampling hit Win32 error1450 / HostBuffer.read_file_slice failed with default disk-backed asynchronous/pinned offloading. An officially reported workaround for similar RTX5070 hardware is --disable-async-offload --disable-pinned-memory; this run also selected --disable-fast-disk. Verify actual sampling/decode before calling it solved. Source: https://github.com/Comfy-Org/ComfyUI/issues/15337. Keep resource/driver errors separate from workflow validation errors.

API submissions with an arbitrary client_id can route progress to a nonexistent websocket client. Omit client_id for shared local progress or bind an actual authorized UI client; inspect queue/history/logs for authoritative status. Never call the GUI percent an elapsed-time estimate.

H3 INT8 CPU VAE commissioning: checkout e087d8f6cb7c6cdb11b59dc7c9bf17c79f8d877d selected CUDA-only int8_attention despite CPU Q/K/V under --cpu-vae. Sampling completed20steps but VAEDecode failed, so no production MP4 was created by that attempt. The existing upstream qk_norm_scale device fix from PR16485 is separate and already present. The local reviewed patch in assets/comfyui/h3-cpu-vae-device-routing.patch checks actual Q/K/V devices and uses optimized_attention_for_device for CPU fallback; apply only after inspecting the installed source and git apply --check. Do not reapply blindly to later upstream releases. Four focused regression tests passed; they do not establish full model decode performance. See h3-decoder-fix.md for exact limits. Exercise the actual VAE checkpoint alone before repeating expensive sampling, then require a successful MP4 and visual/audio review. A zero-latent decoder diagnostic is never an accepted production scene.

For a user-authorized paired remake, BOTH rows must be active in ONE dependent
Run. Use [continuous shots](continuous-shots.md) and
scripts/build_continuous_workflow.py: the preceding decoded editorial boundary
feeds the next AddGuide directly. Preserve old sources and assign new versioned
prefixes. Disabling the old A row was appropriate only for the superseded B-only
retry, and does not satisfy the new paired remake. Inspect queued outputs and
dependencies; saving/importing a graph is not generation. Actual Run must be
observed, with output MP4/history checked before reporting completion.

Verified browser-import recovery for the paired graph: after refreshing inventory,
the generic cua pressKey Control_L+o did not open a chooser in the observed Chrome
session. A DOM-grounded `#graph-canvas` locator `.press('Control+o')` did; arm the
filechooser event first and set the absolute JSON path. Use the same canvas-scoped
Control+s for Save, then the actual Confirm button. Inspect current DOM first;
do not assume coordinates or stale node indices. This workaround changes no
browser settings. New graph `Scene 1 - Zoo Entry A-B v3` was saved and one actual
Run accepted54nodes/all8native/editorial/PNG sinks; its A motion was later rejected
and B intentionally interrupted. V4 also failed motion; its compact prompt was
subsequently found truncated by frontend serialization. Neither is an accepted scene.

Use [literal prompt transport](comfy-prompt-transport.md): concrete server node
PrimitiveStringMultiline19 feeds H3 prompt, remapped1019 for B. Keep full JSON,
URLs, braces and complete character descriptions in its unchanged value. Do not
put compact JSON directly into the dynamic H3 text widget. After visible Run,
compare actual queued literal values/hashes and prompt links against the source;
stop promptly on a mismatch. Source validation alone cannot catch this failure.

## Contiguous motion guidance

The optional `guide_clips` config accepts staged input-relative silent video files:

```json
{"guide_clips": [{"video": "rear-walk.mkv", "frame_idx": 0, "frames": 124}]}
```

The builder emits LoadVideo → GetVideoComponents(images output0) →
ImageFromBatch(batch_index0,length=frames) → MiniMaxH3AddGuide. It never connects
the clip's audio or substitutes the sampler's original target latent. Valid
guide lengths follow17n+5:5,22,39,56,73,90,107,124... . Probe actual source FPS,
decoded frame count and dimensions before submission; schema validation leaves
those media checks pending. At24fps a90-frame guide starting24 covers24..113;
the source must really contain90 frames. Image and clip guides are ordered by
target frame; overlapping conditioning may conflict and is a deliberate test,
not a guarantee. In dependent shots the incoming previous-used-frame guide at0
must precede the earliest extra guide, including clip-only shots. Preserve the
full guide chain and source hashes in provenance.

Ref2VA supports arbitrary AddGuide nodes according to the official multiframe
workflow; do not claim it lacks that feature. Independent still anchors have
not reliably prevented the entry shot's rear/front/rear reversal. A contiguous
motion batch is a justified experiment, with acceptance pending actual output.
Any guide-only visual retiming must be labelled and must never alter canonical
Alice PCM. Offline114-test suite and independent graph/Python reviews support
the builder, not a claim of successful GPU motion. Sources:
https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe and
https://github.com/Comfy-Org/ComfyUI/pull/15439 .


Measured v9 lesson: full124-frame A guide at0 gave a rear-forward visual pass,
but the90-frame B guide at24 produced repeated pale pulses starting at
25/42/59/76/93/110 and spatial double images near the gate. This is not an
isolated proof of an offset-guide implementation bug. Independent review also
found doubled rails in the v7B source around97..104, so do not stretch that
entire source span as if clean. Reject B; keep full native AV and accepted A.
An exposure-only filter cannot repair spatial doubles. Any retry must declare
its exact source span/anchors/seed changes and pass complete motion review.
See error-db/H3-partial-clipguide-exposure-ghost-v9.json.
