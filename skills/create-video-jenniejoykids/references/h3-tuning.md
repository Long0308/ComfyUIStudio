# H3 step count and measured speed

Current hardware is RTX5080/16GB, installed and measured2026-10-18; see
[GPU handoff](gpu-handoff.md) and [current state](../../jenniejoy-production-system/references/current-state.md).
On2026-10-17 the prior card was RTX5070/12227MiB. Measurements below belong to
that historical card unless specifically labelled otherwise; do not use them
as5080 timings or a current VRAM limit.
Model file bytes do not equal inference VRAM; weights, text encoder, VAE,
activations, frame count and offload all affect it. Do not promise BF16 fits16GB
or extrapolate exact5080 seconds/step from this5070.

The commissioned historical profile is Ref2VA pruned INT8, Qwen32B NVFP4 AWQ,
videoVAE INT8, audioVAE FP32, native864x480/124frames/24fps,
res_multistep+beta,20steps. The current official Ref2VA template instead uses
res_multistep+simple,20steps. That difference is now an explicit controlled
v11 trial, not evidence that the scheduler caused previous failures.
Two observed successful native5.167s runs took438.23s and454.19s end to end.
They are operational measurements, not accepted animation quality. File size
MB/step is not a speed unit; record seconds/step and seconds/job, pixels, frames,
sampler/scheduler, model/LoRA hashes and warm/cold load status.

Builder configuration accepts optional `scheduler:"beta"` or
`scheduler:"simple"`; omission retains the historical `beta` graph and receipt.
Continuous workflows honor this setting per segment through the same builder.
Null, non-string and other values fail validation. The separate FL2VA adapter
still requires explicit `simple`. Inspect the actual queued scheduler; this
configuration fix does not establish motion quality or faster generation.

| Profile | Steps | Use and acceptance |
| --- | --- | --- |
| Reference continuity | 20 base | Official base recommendation with simple scheduler; actual doorway acceptance remains pending. Increase to25 only if a controlled comparison justifies it. |
| Simple draft experiment | 16 base | Optional matched-seed comparison against20, not a proven optimum. Reject if identity, direction or anatomy deteriorates. |
| Turbo experiment | 4 with matching Ref2VA Turbo LoRA | Separate versioned profile; verify installed artifact/hash and required sampler/scheduler. Never simulate Turbo by reducing base steps alone. |

Official Comfy guidance says simple shots may hold at12–16steps, reference-heavy
shots benefit from base20 (25 if reference still drifts), and Ref2VA Turbo uses4
with its LoRA. FL2VA's8-step Turbo belongs to a different model family. Short
schedules can weaken pose/face conditioning and speech/timbre; final canonical
VoiceStudio audio helps diction but cannot repair picture drift. The pasted
6-step anecdote does not establish the best local setting.

Choose the fastest profile that passes a controlled shot review. Keep initial
image, seed, prompt, duration, resolution and guide assets fixed; change only the
sampling profile. Measure wall time, sampling time, VRAM/RAM and output metadata;
inspect full identity, forward action, seam, limbs, camera and lip sync. Do not
claim every detail becomes accurate at a particular step count. Fix a reversed
prompt/world layout before spending extra steps.

Sources checked2026-10-17:
- https://docs.comfy.org/tutorials/video/minimax/minimax-h3 (step count and sampler)
- https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native (Ref2VA versus FL2VA)
- https://github.com/ModelTC/Minimax-H3-Turbo (matching distilled checkpoints)

Current Turbo preparation remains research-only, not downloaded, benchmarked or
accepted. Keep runtime versions and VoiceStudio isolated. Restart Comfy only when
runtime changes require it and after queue idle; documentation updates alone do
not require restart. A successful HTTP response is not a successful new render.


## Official schedule reconciliation

On2026-10-17 Firecrawl retrieved the official guide and model card. The actual
Ref2VA JSON was also saved locally with SHA256
afeea99e9fd5a1456df348e0573e289c1243f2f28546fc95c1c963f808d61ddb,
showing BasicScheduler["simple",20,1] and res_multistep. Historical builder
default beta remains in frozen graph evidence; never silently rewrite an old
run as simple. Scene1Bv11 keeps seed4341,20steps, full prompt, anchors and
native/editorial routes identical to v10; only scheduler and output prefixes
change. The graph patch and actual queued values are recorded. Its motion
result is pending; do not call this a verified quality fix.

The official first/last-frame variant uses the FL2VA checkpoint and
MiniMaxH3ImageToVideo, while Ref2VA uses MiniMaxH3ReferenceToVideo. They are
distinct task families. A possible FL2VA continuation test needs its own pinned
checkpoint, graph, resource preflight and actual picture review; no file name
or template availability establishes local quality or speed.


Trial result: Scene1Bv11simple encoded in304.771s but still cut to frontal
toddler closeups and reset to the rear view. Therefore scheduler alignment is
not a verified camera/continuity fix. Do not keep repeating that first/last-only
Ref2VA setup. The next continuation experiment uses native H3 FL2VA/I2V with a
separately pinned checkpoint; its download and runtime quality remain pending.
