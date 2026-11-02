# Script tracking, transition and finishing gates

Before generation write a chronological script ledger for every segment/sub-shot:
line IDs/exact English words,speaker,planned local/global clock,complete cast,
location/layout/props,learning target,entry pose/gaze/direction,action beats,
exit pose/gaze/direction,camera axis/height/lens,lighting/palette,reference versions,
voice file,transition motivation,next-segment match and readiness status. Missing
readiness or unexplained discontinuity blocks submission. Keep theme and subject
coherent; explicit narrative time/location changes are allowed with an establishing
shot. Track planned/submitted/rendered/reviewed/accepted statuses and actual job IDs.

Transitions follow story beats: look toward bird -> eyeline cut; walking past a
tree -> foreground occlusion; giraffe bends -> match on pointing; shared path
direction -> motivated follow-pan; family wave -> gentle closing hold. Preserve
screen direction and180degree camera axis unless an establishing move explains
the change. Favor short clean cuts/match actions, slow natural easing and visual
handles. No arbitrary whip pans/flashes, rapid zooms or wipe over every scene.
Do not shorten60s when adding overlapping effects; keep dialogue and captions
clear, effect layers below captions, and never occlude eyes/mouths during speech.

Choose per-line subtitle placement only after actual rendered-frame inspection.
If bottom captions cover feet/contact, use edit-settings `caption_positions`
to map that dialogue ID to `top`, `top-left` or `bottom`; unlisted lines retain the original
bottom layout. Inspect and record start/middle/end frames and any crossing
before accepting the change: the top position must not cover faces, hands or
the named animal. `top` stays horizontally centered; `top-left` uses a left and
top68×delivery-scale inset. All three positions use the existing vertical inset; no
voice, caption words, timing, frame rate or source media changes accompany this
override. Review a fresh720p preview; do not edit or relabel a prior accepted one.

Current user correction: opening display text is exactly `JennieKidJoys` and
`Let's Go to the Zoo!`. The skill/package name and historical baseline retain
their original spelling. Add branding with Hyperframes and English subtitles
with Remotion after native animation, keeping all generated image-text disabled.
The local pilot opener uses22frames at24fps (0.916667s), before1s dialogue; do not
silently round this to24frames or overlap speech. See assets/hyperframes-opening/.
Future episodes may reserve a longer explicitly planned opening interval.

The zoo-entry beat requires actual bodies crossing the opening BETWEEN the gate
pillars, camera movement revealing the inner path, and all three family members
remaining visible. A side-step in front of a stationary gate does not pass this
story-action check. Verify the exit/entry frame match, grounded steps, turns and
spatial geometry before accepting the second subshot for an editorial draft.

Reference sheets lock geometry/outfit but allow acting. Inspect identity in start,
middle,end and turns; compare anatomical bow side, one heart, collar, eyes, hands,
foot contact, parent proportions, animal limbs, stable props and spatial layout.
Review at normal speed as well as sampled frames for flicker/warping/skating.

Lighting: consistent soft warm daylight,key direction,fill/shadow softness,white
balance and restrained palette. Record exposure/contrast decisions per scene.
Automated signalstats can flag saturation/exposure jumps, blackdetect/freeze
can flag suspicious frames; these do not certify pleasant lighting or acting.
Don't grade skin/pink to neon; do not apply HDR metadata to an SDR export.

Audio: use the selected engine.audio_mode. In canonical_voicestudio (the current
Alice project), canonical original Alice WAV is authoritative; no duplicate
generated voice beneath it. In preserve_native, accepted native generated VO is
authoritative and stays fully in the edit after voice-identity, exact-word,
timing and listening review; do not replace it with the canonical guide.
Preserve complete raw native AV as immutable sources in both modes.
Align captions/phonemes to actual accepted VO onset,leave response pauses,
clear age-appropriate English pronunciation,short friendly animal calls. Separate
VO/BGM/SFX stems; sidechain music under words without pumping; inspect transitions
for clicks/gaps. Suggested configurable mix targets:-16LUFS integrated,-1dBTP
ceiling,VO intelligibility ahead of music (typically music12–18dB lower). Targets
are production choices,not universal loudness law. Listen on speakers and quiet
headphones. ASR checks words,not voice identity; one VAD miss needs reinspection.

Apply voice-clarity.md and retain per-line AUDIO QA JSON. The first local H3 Alice
pilot's generated voice was reported unclear by the user; it is not accepted audio.
For this canonical_voicestudio project, compare the saved original VoiceStudio
WAV on the same picture before regenerating affected lines. Clear diction notes
must be repeated in segment prompts; they are not evidence of successful diction.
Do not spend another video generation merely to replace an unclear soundtrack.

Draft delivery1280x720 at24fps first,with English subtitle and voiced variants.
Record user acceptance including approved preview hash/time; only then render
1920x1080 final. Existing historical1080p movie is not acceptance of a new draft.
Render both variants from the same mix; SRT uses measured final words and timing.

scripts/media_qa.py consumes JSON and produces technical JSON evidence: probe,
strict decode,ebur128,signalstats,black/freeze detection. Missing audio/video,
wrong dimensions/framecount/duration or decode errors fail technical checks.
Visual continuity,voice identity,lip sync,subtitle safe area and listening checks
remain pending unless actually reviewed. Overall acceptance needs both technical
and observed artistic checks; do not label pending as passed.

For reusable Foley/source preparation read [SFX lessons](sfx-source-lessons.md).
Source peak-energy windows are not automatically audible event onsets. Measure
picture contact and select the matching transient before final placement; keep
planned windows and unknown event frames distinct from accepted movie cues.
