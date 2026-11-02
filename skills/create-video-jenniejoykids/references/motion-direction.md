# Reference evidence and motion direction

## Inspect before describing

Identify the actual source file, hash, provenance and review scope. A tutorial's prose, its example values and a saved historical baseline are different sources. With no attached tutorial video, mark its visual measurements unknown. A saved Higgsfield movie can support a baseline comparison after inspection, never measurements attributed to the missing tutorial.

Probe source width/height, frame rate, time base and duration. Start with a labelled 2-fps overview/contact sheet to locate beats. Then inspect consecutive original frames around each cut, entrance, attention shift, action result and hold; use actual presentation timestamps (PTS), especially for variable-frame-rate media. Overview sampling cannot resolve exact transition duration, motion curves or audio sync. Keep source frame indices/PTS distinct from 24-fps export indices; record the mapping and rounding policy rather than assuming one-to-one frames.

Each observation declares its evidence status:

| Status | Meaning |
| --- | --- |
| `measured` | Reproducible value from identified source frames, metadata, waveform or font/layout measurement, with method and evidence. |
| `visual_estimate` | Human estimate from inspected media; retain uncertainty and inspected interval. |
| `creative_choice` | Proposed timing, scale, easing or design for the new film; never attribute it to the reference. |
| `unknown` | Unavailable or inadequate evidence; leave value null and list needed frames/PTS or other inspection required. |

Bounding boxes use original source pixels: top-left origin, x right, y down; record x/y/width/height plus source dimensions and frame/PTS. Identify whether the box includes shadow/outline. Export/screenshot coordinates require an explicit transform. Distinguish a subject's box from the camera viewport. Do not infer speed, font identity, easing/spring parameters or millisecond precision from a single still. Record `needed_frames` for unresolved motion, including interval and purpose.

The JSON sidecar's `motion` object requires concrete numeric values when present.
For unresolved motion, omit that object, put evidence status `unknown` in the
event description/source event and list `needed_frames`; never insert invented
zero boxes or null into required numeric fields. Markdown evidence tables can
use null for an unknown measurement. Native acting without a graphic transform
need not fabricate a bounding-box animation or easing curve.

## Shot grammar

Plan each shot as **starting state -> attention/gaze -> action -> visible result -> reading/repeat hold -> cut**. Give every beat an owner, planned interval, intended attention target and observable completion criterion. Preserve a clear causal order: Alice looks toward the giraffe, points, the giraffe bends into view, the name is spoken/displayed, then the child receives a quiet repeat pause. Do not label the result before the viewer can identify its subject.

Track exact dialogue IDs/words, full cast, location/layout, entry and exit poses/gaze/screen direction, camera axis, props, lighting and reference versions. Match the next first frame to the preceding accepted **editorial** last frame; record MP4 hash, frame index/PTS and extracted-image hash. Unused native tail frames are not the cut boundary. Maintain identity while allowing expressions, blinks and phonemes. Crossing the zoo gate means all intended bodies visibly pass between pillars onto the inside path; sideways motion in front of it fails.

Keep one dominant attention change at a time. Use anticipation, action and settle for readable native acting; allow natural secondary motion without competing with the learning target. Cuts follow resolved actions, eyelines or explicit changes of place/time. Preserve action direction and camera axis; use an establishing move when changing them. Choose durations from actual clear speech, the intended child's viewing/repeat time and the observed movement, not a tutorial's preset shot length.

## Deterministic graphics

Evaluate every graphic from frame index and declared fps. Frame zero is the first frame; a duration of N frames has last visible index N-1. Keep exclusive event end boundaries distinct from last visible frames. Remotion Sequence children receive local frame time; add the sequence offset only when converting to the master clock. Use frame-derived interpolation/springs and a fixed recorded seed for randomness. Do not depend on wall-clock CSS animations, timers, unseeded randomness or render order. Hyperframes exports must match this clock when conformed to Remotion. Record spring/easing choices as creative choices unless measured; test overshoot and settling against the shot's hold. Preserve the working pinned Remotion template; these direction rules do not authorize dependency upgrades.

Keep transform responsibilities explicit: layout establishes position; entrance animation controls its offset/opacity; emphasis is a separate deliberate beat. Avoid transform collisions. Optional blur belongs only to a brief entrance or transition and returns to zero before a reading hold. No continuous blur, restless bounce or scale drift on captions. Layer graphics below essential faces/mouths and keep subtitle contrast and safe areas stable.

Load the actual intended fonts before measuring text. Test the longest real caption/title in its actual weight, line breaks and container, then inspect the 720p export at phone viewing size. Record overflow, line wrapping, occlusion and readability findings; substitute fonts require remeasurement. Do not solve long copy with an arbitrarily tiny font. Change layout or timing while preserving exact approved words. The current two-line Hyperframes opener uses the exact strings and 22-frame duration in [postproduction QA](postproduction-qa.md); review its readability rather than silently extending it over the first speech.

## Audio follows the visible event

Separate dialogue, music and SFX stems. Place an SFX by its audible transient, not its file start: record the transient's offset inside the asset and align that point with the observed visual event on the master timeline. Preserve pre-roll/decay or document trimming; review adjacent-frame timing and listen at normal speed. Avoid decorating every motion with a sound or masking initial/final consonants. Ducking is subordinate to clear narration and should not pump.

Canonical VoiceStudio Alice remains the authority in the current audio mode. A generated guide does not certify H3 diction. Compare the original verified WAV on the same picture, retain raw native AV, and apply [voice clarity](voice-clarity.md) before replacing or regenerating any line. Align captions/lip sync to accepted measured speech; never stretch words merely to meet planned motion timing.

Review representative start/action/result/hold/cut frames plus normal-speed playback. Technical probes establish media facts; human review establishes intelligible speech, understandable actions, pleasant motion and readable text. Keep those outcomes separate and honor the configured stage review and mandatory 720p-before-1080p gate.
