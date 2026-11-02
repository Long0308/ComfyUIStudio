# Native H3 first/last continuation adapter

`scripts/build_fl2va_workflow.py` is a separate offline adapter. Existing Ref2VA
builders and their beta scheduler defaults are unchanged. No installation,
model loading, queue submission or rendering occurs while building a graph.

Use the continuous-root JSON shape with exactly one selected segment and root
`carry_in_first_frame:true`. The segment requires `first_frame` and `last_frame`
as staged lossless PNGs, explicit `scheduler:"simple"`,
`dialogue_presentation:"voiceover"`, `native_speech_conditioning:false`, and the
original canonical `guide_audio` WAV. The expanded VIDEO item must select
`canonical_voicestudio`. The reviewed core's duration/dimension/steps/seed limits
remain in force; this adapter does not restrict all projects to one pilot size.

Nonempty `guide_frames`/`guide_clips` are rejected. Optional `reference_images`
may contain only the actual first/last filenames. Optional ordered
`reference_bindings` must match those entries. Only the first and last images
are connected to I2V and mentioned in the runtime binding preamble; omitted
binding approval defaults to unverified. Full inline character descriptions
remain intact in the literal STRING node19. Canonical dialogue remains in the
source/receipt but is removed from native visual-only speech conditioning.

```json
{
  "video_manifest":"video.json",
  "carry_in_first_frame":true,
  "segments":[{
    "segment_id":"S01_B",
    "first_frame":"accepted-A119.png",
    "last_frame":"target-B119.png",
    "reference_audio":"alice-reference.wav",
    "guide_audio":"alice-original-B.wav",
    "dialogue_presentation":"voiceover",
    "native_speech_conditioning":false,
    "scheduler":"simple",
    "width":864,"height":480,"editorial_frames":120,
    "steps":20,"seed":4341,
    "output_prefix":"Film/Scene-01-B-new"
  }]
}
```

```powershell
python scripts/build_fl2va_workflow.py config.json --out fresh-workflow
```

The graph selects `minimax_h3_fl2va_pruned_int8_convrot.safetensors` and native
`MiniMaxH3ImageToVideo`, with CLIP2, VAE3, literal prompt19, first image8 and last
image20. Positive6:0 goes directly to BasicGuider10. The original joint AV
latent6:1 feeds the sampler; audio VAE4 still decodes generated native audio.
There is no redundant AddGuide and no unused reference-image input chain.

Native output preserves the full generated image batch and audio. Editorial
output uses accepted incoming image8 as exact pre-encode frame0, then generated
frames1 through the last USED index, paired with canonical WAV trimmed only to
the logical duration (superseded 2026-10-27 R27: a trim made after H3 is a different file; the editorial WAV must be the receipt WAV for the shot, or for a `native_speech_conditioning:false` voiceover shot with no receipt WAV, the WAV named and hash-bound in the editorial manifest; see the Single Audio Trim Rule in [comfyui-video-pipeline](../../comfyui-video-pipeline/SKILL.md)). Boundary-start/end PNGs are saved from that editorial
batch. At five seconds/24fps, native124 includes a last condition at frame123;
editorial120 ends at actual generated frame119. **The supplied last PNG is not
the next carry**: use actual saved editorial boundary-end. All indices in the
receipt are derived from the configured logical/native durations.

Before Run, verify both PNGs have exactly the native dimensions without resizing
or cropping. Native I2V stretches mismatched first images and cover-crops last
images internally; conditioning is probabilistic even with matching geometry.
Inspect forward walking, doorway crossing, identity and all consecutive seam
frames in actual output. Neither keyframes nor a pure graph test prove motion.

The selected checkpoint is pinned to SHA256
`e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a`,
20,970,379,616 bytes, from Comfy-Org/MiniMax-H3 revision
`e5eb578a89295337b8ff433a035929ce0279e0b6`.
The builder does not read/hash that large model: artifact verification stays
pending in its receipt. Verify the actual completed file first, then refresh
`/object_info` and supply the fresh snapshot as `installed_object_info` to check
the final transformed graph. Never claim installed schema or model readiness
from a partial download, a stale dropdown, a filename, or synthetic test data.

Primary sources inspected: installed `comfy_extras/nodes_minimax_h3.py`
`MiniMaxH3ImageToVideo.execute` and official Comfy-Org workflow-template
`video_minimax_h3_i2v.json` / `video_minimax_h3_i2v_continuation.json`. The
official template selects simple/res_multistep; step count remains configurable.
Source copies and pinned model metadata for the initial experiment are under
`production-local/observations/H3-official-native-research-v11/` in the production
workspace. They are provenance, not a claim that the local new model has loaded.

Initial runtime trial v12 did load and generate successfully in 297.863 seconds
on the local RTX5070. Native/editorial technical checks pass; the exact incoming
PNG carries into the first editorial frame. The picture was rejected after all
120 used frames were inspected: parents/toddler turn toward the camera, a frontal
closeup occupies frames30–68, then the shot returns rearward. FL2VA by itself did
not fix this previously observed Ref2VA failure. Do not repeat that unchanged
configuration. Prompt-format/salience is an untested hypothesis; code/schema/model
load success does not establish an approved motion method. Preserve the rejected
native AV and review record `error-db/H3-FL2VA-frontal-detour-v12.json`.
