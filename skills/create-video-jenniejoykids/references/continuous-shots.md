# Continuous action across generation segments

## Current film rule: Milk and Mom, episode 04

The scene number is editorial, not a continuity reset. Mother and Alice appear across the S01 and S02 boundary in the same outdoor garden/farm geography; the milkmaid remains a distinct silent adult on the farm side of the fence. Plan S01_B to settle into a wider view with Mother/Alice still on the garden side and the milking station in the established direction. For S01_B → S02_A, use S01_B's accepted last **USED** PNG as S02_A frame 0 at identical native dimensions, then continue the camera/action toward the milkmaid. The actual carry path, source clip hash, frame index/PTS, ComfyUI node binding and next prompt ID stay pending until those clips exist. The same rule is the default for other adjacent same-place, same-time pairs that retain the actors. A deliberate new camera angle/time jump requires a declared motivated cut plus explicit prior exit/new entry blocking, actor positions, eyelines, wardrobe and prop state; it cannot silently drop or teleport a visible person.

Every new shot repeats the complete descriptions and source image hashes of **all** visible characters, including a silent listener, and states which mouth may move for the current WAV. A carry image supplements this full prompt; it never replaces the cast description. Check the last frames of the first clip and first frames of the next in motion, including both characters and fence/animal geography. Keep episode 03 Milk footage and anchors out of episode 04.

Measured episode-03 recipe to reuse **as a method only**: `03-drinking-milk/assets/S01_A-frame119-d9f9477340fc.png` has SHA256 `da401e6a56360f9555a3ad5301d93f40f7e96541f995329640b5d3178777c3e5`, identical to the `LoadImage` file `03-drinking-milk_S01_B_da401e6a5636.png` feeding frame 0 in `workflows/S01_B.api.json`. Likewise `assets/S01_B-frame119-8f01c38706d2.png` has SHA256 `0c516146dbac6dfbeeddd9e68b57f597b436e9a0c894b7fb5ba0929802ade5de`, identical to `LoadImage` file `03-drinking-milk_S02_A_0c516146dbac.png` in `workflows/S02_A.api.json`. This verifies the graph input chain, including a numbered-scene boundary; decoded seam/action quality still needs visual review. Episode 04 must create its **own** carry PNGs from its accepted clips, never load the episode-03 files.

## Historical zoo implementation (reuse the measured mechanics, not the cast)

For the zoo film, the user's rule was binding: the last USED image of N
becomes the first image/input of N+1. Apply this throughout continuous action.
For other films an intentional change of time/place may use a declared cut;
never pass an unexplained reset off as continuous movement.

## Space and acting

Before generation, record an outside region, gate/threshold plane, inside region,
character order, camera side/axis and travel direction. A family entering the zoo
starts outside, faces the open gate ahead, passes between its pillars and keeps
moving down the interior path. Camera follows on the same side of the axis.
The gate moves behind the family; no turn-around, backward walking, mirrored
screen direction or reappearance outside. Include grounded alternating steps,
body weight, gaze and hand contact. Camera zoom on a still is not this action.

Repeat the entire cast description in every segment even when faces are turned
away: age, proportions, face, hair/asymmetry, full clothes, shoes and accessories.
Rear-view hidden features stay latent identity facts; do not draw a chest heart
onto a dress back. Identity sheets and previous frames supplement those facts.

## Scene Transitions, Axis Reversals, and the No-180°-Turnaround Rule

When transitioning from a rear-view traveling shot (e.g., entering the zoo gate in Scene 1) to a stationary interactive scene (e.g., discovering the blue bird in Scene 2), **NEVER command the AI generator to execute a continuous 180° body turnaround within a single shot**.

Because 2D diffusion flow-matching models (MiniMax H3) lack 3D skeletal rigs and 360° cel turnaround comprehension, forcing an in-shot 180° reversal causes the model to morph facial textures onto the back of the head (the second-12 neck-twist defect).

Instead, apply classical cinematic animation grammar:
1. **Cinematic Cut**: Cut from the rear-view departure (Scene 1B) directly to a new 3/4 frontal tableau (Scene 2A).
2. **Pre-Positioned Frame 0**: Frame 0 of the new scene depicts the family already standing under the willow tree in an anatomically sound 3/4 frontal perspective.
3. **Local Action Focus**: The generative model is tasked only with upward eye gaze, pointing arm elevation, and shared discovery gestures—guaranteeing 100% natural posture and zero anatomical morphing.

## One Run, dependent native clips

Use `scripts/build_continuous_workflow.py config.json --out NEW_DIRECTORY`.
Config is JSON: `video_manifest` path and 1..100 ordered `segments`, each the existing
single-shot builder config plus `editorial_frames`. Supply full expanded VIDEO
items, adjacent times/states, equal dimensions, unique prefixes and guide WAVs
in canonical mode. A staged `first_frame` belongs only to the first segment.

When continuing across separate jobs, set ROOT config `carry_in_first_frame:true`
and supply the accepted predecessor's last USED image as a lossless PNG in the
first segment's `first_frame`. This explicitly places that loaded tensor at the
initial editorial frame0, followed by generated images1..N-1; an ordinary image
guide alone is probabilistic. Native full AV stays unchanged. Before Run, probe
the PNG and require its actual width/height to equal native generation exactly.
Do not resize or crop it. The builder records dimension preflight as pending;
schema validation and a filename prove neither actual dimensions nor acceptance.
Absent/false preserves the previous graph behavior. Within a job every later
segment still takes the preceding editorial last image as its authoritative0.
A single segment is supported for an isolated continuation repair: preserve the
accepted preceding clip, supply its actual last-used PNG and enable root carry.
Only that requested continuation is built; no sibling generation is inserted.

The builder shares model loaders, keeps all declared native SaveVideo sinks, extracts
the preceding editorial last image with ImageFromBatch and directly connects it
to the next MiniMaxH3AddGuide at frame0. An image guide is probabilistic; it does
not force exact decoded equality or correct motion. Separate editorial previews
replace the next first image with that exact preceding tensor and retain the
next generated images1..N-1. This enforces the pre-encode boundary, not the rest
of the action. Preserve full unmodified native AV alongside these clearly named
previews. PNG boundary images support verification; H264 lossy encodes may differ.

For 5s/24fps used spans, select frames0..119 from native124-frame output. The
boundary is frame119, NOT unused frame123. Reuse the same chosen cut point in
Comfy guides, editorial clips and Remotion. Never trim a spoken word to fit;
verify original WAV duration and line end first. Retain actual PTS/hash evidence.

Import the raw prompt map in Chrome (the API wrapper is for API consumers).
All declared segment branches are active. Inspect queue/history before one visible Run;
GPU sampling remains serial on the 12GB card. Record job ID and elapsed time.
Do not submit a second job while the first is pending.

## Boundary acceptance

Extract N frames116..119 and N+1 frames0..8, inspect consecutive frames and a
normal-speed surrounding preview. Record seam image hashes, decoded pixel
differences if measured, poses, gait phase, hand contact, lighting, camera and
forward direction. Also inspect the full doorway crossing. Exact seam pixels
cannot certify correct travel, anatomy, identity, acting or clear speech.

The prior S01_B-entry-v2 is USER-REJECTED for wrong perceived direction and must
not enter a new master. Redoing A is necessary to establish an unambiguous
outside→threshold→inside layout. Final titles/subtitles belong to Hyperframes/
Remotion; final voice uses saved canonical Alice. Draft720p first, explicit
acceptance before1080p. Both are delivery sizes when native inference is480p.

Latest observed defect: pairedv3 A encoded successfully but the toddler turned
front and walked backward while parents moved inward. Reject that take; B was
intentionally interrupted. Matching the first/last image and inward world-space
displacement did not establish a forward gait. Evidence: error-db/H3-rear-voice-body-reversal-v3.json.

For a rear-view walking shot, optional builder config `dialogue_presentation`
accepts `voiceover` or default `on_screen`. Voiceover requires an action explicitly
saying `off-screen voiceover`, without says/speaks/audience-turn instructions.
It overrides the generic runtime mouth-performance permission, preserving full
character anatomy descriptions and all native audio. Adapt global voice notes
and the complete action/summary too. It is not enough to prepend voiceover to a
contradictory on-screen prompt. The pairedv4 trial used only the reviewed rear
keyframe as image reference to avoid frontal pose competition. It still turned
the child frontal and was rejected; B was intentionally interrupted. This is a
confirmed failed attempt, not evidence that voiceover wording fixes the gait.
Later learning shots may use on-screen speech and natural profile turns as scripted.

Optional `guide_frames` adds ordered nonzero image anchors, for example
`[{"image":"rear-mid.png","frame_idx":60},{"image":"rear-end.png","frame_idx":119}]`.
Frame0, then60, then119 conditioning must all reach the final guider; each guide
uses the segment's original reference-to-video latent. A next segment without
its own staged first image receives the previous used image before later guides.
Review anchors' geometry and full cast first. Similar key poses do not constitute
animation: require actual alternating gait between them, without morphing or a
static camera push. Mid/end image conditioning remains probabilistic.

For an explicitly nonverbal visual pass, `native_speech_conditioning:false` is
allowed only with `dialogue_presentation:"voiceover"` and canonical VoiceStudio
editorial audio. It removes native voice references, spoken script and audio
guide conditioning while retaining the original canonical WAV for editorial,
full identity/visual descriptions and native AV preservation. Author visual
actions without inserted spoken utterances; a scoped guard detects explicit
quoted/spoken cues without banning shared animal vocabulary such as "Tiger".
Keep source script/dialogue in manifests and provenance. This separation does
not certify correct walking, sound quality or lip sync. Scene1v6 was interrupted
early after actual queue inspection exposed frontend JSON truncation. Scene1v7
uses literal STRING nodes, with both actual queued values verified unchanged;
its motion is still pending. Update acceptance only from real outputs.
