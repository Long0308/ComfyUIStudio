# JSON preparation through finishing

Run commands from the installed skill directory or use absolute script paths.
Paths below illustrate a separate project at `C:/film`; replace them with existing
local files. JSON values are inputs, not evidence that assets were reviewed.
Keep generation/submission separate from the offline preparation commands.

## Script and references

Copy examples/zoo-60s.json or expanded-education.json into the project and edit
the subject, full cast, script, timings and engine profile. Never add unrecognized
fields to that core request; use the motion-plan sidecar for shot evidence.

Every request declares an `image_engine`. New production uses
`{"provider":"ComfyUI","execution":"local","model":"<selected checkpoint>",
"profile":"<saved workflow/profile>"}`. An absent image engine fails validation;
the compiler never substitutes GPT Image2. A frozen historical cloud request
must name OpenAI and set `"legacy_opt_in":true` explicitly.

For new human characters, set
`reference_policy.sheet_requirements.plan_mode` to `canonical-12`, use the exact
IDs `01-neutral` through `12-thinking`, and provide the scene-specific pose plan.
The older `legacy-6x4` mode remains available only for historical requests that
explicitly select it.

Before scheduling character work, bind reusable cast to a hash-checked episode
manifest with a top-level `cast_reuse` object. Its `characters` map links the
request ID to the library ID, including `"mother":"mom-alice"`; the validator
checks the cast manifest, canonical PNG, expression manifest and every selected
expression hash. A reuse-only project sets `plan_mode:"reuse-only"` with empty
turnaround/expression/pose arrays. The compiled `character_generation` plan then
excludes those reused request IDs.

Alice and Mother require complete `cast_reuse` mappings in every non-historical
plan, including `canonical-12` projects that also create a new character. Their
identity mappings are fixed (`"alice":"alice"`, `"mother":"mom-alice"`). Compiled
bindings retain `canonical_approval`, each expression's `review_status` and
`user_approval`; a legacy cloud request with explicit `legacy_opt_in` remains the
historical exception.

```powershell
python scripts/validate_request.py C:/film/request.json
python scripts/compile_prompts.py C:/film/request.json --out C:/film/stages
python scripts/validate_motion_plan.py C:/film/motion-plan.json
python scripts/analyze_reference.py C:/film/reference-config.json
```

Reference-config example:

```json
{"source_file":"C:/film/reference.mp4","output_dir":"C:/film/reference-analysis-v1","fps_overview":2,"windows":[{"label":"entrance","start_frame":0,"end_frame":12}],"ffmpeg":"C:/tools/ffmpeg.exe","ffprobe":"C:/tools/ffprobe.exe"}
```

Output directory must be new. Inspect mapped PNGs, then annotate REFERENCE.md;
analyzer output alone proves metadata/extraction, not motion or audio acceptance.
Use assets/production-brief templates for the human-readable plan.

## Native dependent generation

Stage identity images, initial outside-facing-gate image, canonical voice
reference and separate5s guide WAVs in ComfyUI/input. Inventory filenames and
installed node schemas before submission. A minimal paired-config shape is:

```json
{
  "video_manifest":"C:/film/stages/video.json",
  "segments":[
    {"segment_id":"S01_A","reference_images":["family.png","alice.jpg"],"reference_audio":"alice-reference.wav","guide_audio":"A-guide.wav","first_frame":"outside-gate-v3.png","editorial_frames":120,"width":864,"height":480,"steps":20,"seed":4303,"output_prefix":"JennieKidJoys/v3-A"},
    {"segment_id":"S01_B","reference_images":["family.png","alice.jpg"],"reference_audio":"alice-reference.wav","guide_audio":"B-guide.wav","editorial_frames":120,"width":864,"height":480,"steps":20,"seed":4304,"output_prefix":"JennieKidJoys/v3-B"}
  ]
}
```

Add ordered reference_bindings from the single-shot builder example/config to
declare roles and approval honestly. Filename-only examples are unverified.
Manifest IDs must exist with full cast, exact script and adjacent entry/exit
states. Initial first_frame belongs only to A; the builder derives B's frame
guide from A's actual editorial boundary. See continuous-shots.md for policies.

```powershell
python scripts/build_continuous_workflow.py C:/film/paired-config.json --out C:/film/paired-workflow-v3
```

Import the emitted raw GUI map (not the API prompt wrapper), inspect both active
branches and dependency, then one visible Run in Chrome. Check queue/history to
avoid duplicate jobs. Record native and editorial-preview outputs separately.
The emitted H3 prompt is linked from a concrete PrimitiveStringMultiline value
node, not a dynamic text widget. Immediately compare the actual queued literal
value/hash and links with disk; see comfy-prompt-transport.md. Stop on a mismatch
before letting costly sampling continue. Preserve normal frontend-added encoding
defaults as provenance; distinguish them from changed required input values.
Review actual forward gait/threshold/seam/identity/audio before binding an edit.

## Hyperframes, VoiceStudio and Remotion

Render the project's exact branding with the installed Hyperframes runtime;
assets/hyperframes-opening is this zoo's22frame24fps example with local fonts
and GSAP. Preserve its render-inputs and receipt. New copy/duration requires
font/layout/normal-speed review. Do not copy the old tutorial's square30fps spec.

Reuse the saved approved VoiceStudio profile for exact lines. Keep canonical VO,
BGM and SFX stems plus versioned timing/mix JSON; inspect clarity, transients and
ducking. The current finishing binder takes an already reviewed full canonical
mix. It does not synthesize voices, music or SFX. Preserve raw native AV separately.
Build that mix from [measured-cue audio JSON](audio-mixer.md) using
`python scripts/mix_audio.py C:/film/audio-mix.json`; reject unknown contactframes,
verify actual transient/source offsets and keep all stems adjustable.

Create edit-settings.json after visual/audio review. The false fields below
intentionally block prepare_edit until the actual clips are reviewed; do not
change them merely to make validation pass.

```json
{
  "production_request":"C:/film/request.json",
  "project_dir":"C:/film/edit-v3",
  "fps":24,
  "accepted_clips":[
    {"segment_id":"S01_A","file":"C:/film/A-editorial-preview.mp4","engine":"native_h3","accepted":false,"review_scope":"pending motion/seam/identity review"},
    {"segment_id":"S01_B","file":"C:/film/B-editorial-preview.mp4","engine":"native_h3","accepted":false,"review_scope":"pending motion/seam/identity review"}
  ],
  "canonical_mix":"C:/film/audio/final-mix.wav",
  "brand_events":[{"file":"C:/film/brand/opening.mp4","start":0,"end":0.9166666666666666}],
  "runtime":{"node":"C:/Program Files/nodejs/node.exe","renderer_cli":"C:/film/remotion-runtime/node_modules/@remotion/cli/remotion-cli.js","ffmpeg":"C:/tools/ffmpeg.exe","ffprobe":"C:/tools/ffprobe.exe"},
  "comfy_url":"http://127.0.0.1:8188",
  "port":3044
}
```

Require exactly one reviewed clip per compiled segment, filling request duration.
For a10s pilot use a valid10s project request with two subshots, not a60s request
and only two bound files. Preserve full script separately. project_dir must not
already contain a prepared edit. Runtime paths must be existing absolute files.
The binder copies the portable template and emits finish-config, source-binding,
filmJSON and SRT; it neither renders nor approves final1080p.

After inspecting rendered frames, optional edit setting
`"caption_positions":{"S01_L1":"top"}` moves only that dialogue line to the
top center; `"top-left"` selects the upper-left safe inset, and `"bottom"`
explicitly selects the existing bottom placement. Unknown
dialogue IDs and other values fail validation. Absent/empty mappings preserve
all old positions and omit line.position. Inspect the actual speech start,
middle and end frames for feet, hands, faces and bird/animal visibility before
choosing a position; record frame numbers and occlusion evidence. A top caption
may cover a face or learning subject. Words, timing, audio and SRT are unchanged;
SRT does not carry the Remotion placement override.

```powershell
python scripts/prepare_edit.py C:/film/edit-settings.json
Set-Location C:/film/edit-v3
npm ci
npm run typecheck
npm run lint
npm run test:config
python C:/Users/Admin/.codex/skills/create-video-jenniejoykids/scripts/finish_ui.py C:/film/edit-v3/finish-config.json
```

Open http://127.0.0.1:3044 and choose the720p draft action. Wait for its real
output; inspect opening/action/result/hold/cut stills and boundary playback.
Only explicit user acceptance of that preview permits the1080p action. The
finisher hashes sources/code and invalidates approval when they change. A fresh
720p draft cannot inherit approval from a historical film.

## Technical and observed QA

```json
{"file":"C:/film/edit-v3/renders/JennieJoyKids-720p-English.mp4","expected":{"width":1280,"height":720,"fps":24,"frames":240,"duration":10},"ffmpeg":"C:/tools/ffmpeg.exe","ffprobe":"C:/tools/ffprobe.exe"}
```

```powershell
python scripts/media_qa.py C:/film/qa-config.json --out C:/film/qa-report.json
```

Use actual duration/frame count for the requested render. Technical-pass still
leaves identity, readable text, story continuity, voice identity, pronunciation,
lip sync and listening pending. Record up to5 frame-specific repairs with scoped
changes, then rerender affected frames and neighboring transitions. Keep the
approved render, source hashes, full native AV, workflow, JSON and QA together.
