# H3 temporal-guide timing diagnosis

This is a read-only source/artifact investigation. No model, workflow, config,
queue, GPU or media changes were made. Only this note was written. V13's rejected
motion and the separate seed-only v14 trial do not establish the cause of v9's
different exposure/ghosting defect.

## Finding

The v9 B clip guide is legal under the installed AddGuide implementation, but
its temporal token phase differs from the target's phase. Its shifted short/long
token cadence correlates exactly with the reported17-frame exposure pulses.
This supports a controlled aligned-guide investigation; it does **not** prove
an offset bug, a forbidden offset, or that temporal alignment alone fixes B.
The guide also contains independently identified bad-source ghosts and a
spatial/gait mismatch, which must be resolved before reusing it.

For dense guidance, the strongest source-supported starting arrangement is one
clean full native-length rear-facing motion batch at frame0, whose actual first
image matches the accepted predecessor boundary and whose entire spatial/gait
continuation is coherent. At this shot's native124-frame length, that is124
guide frames at0. No clean complete B guide meeting that contract has been
established in the inspected assets.

## Actual v9 configuration and receipts

Inspected `shots/S01-paired-entry-v9/config.json`,
`workflow/workflow-api.json`, `workflow/workflow-provenance.json`,
`motion-guides/manifest.json`, `qa/S01-paired-v9/B-independent/REVIEW.md`,
and the exposure/error evidence already saved for this take.

| Segment | Native/editorial | Conditioning chain in actual built graph |
| --- | --- | --- |
| A |124/120| AddGuide9 still0, then AddGuide103 clip124 at0 |
| B |124/120| AddGuide1009 actual A-used119 at0 →1101 still8 →1105 clip90 at24 →1107 still119 |

B's clip spans nominal pixel indices24..113 inclusive. Its other single-image
anchors0,8,119 do **not** directly overlap that span. Therefore “overlapping B
guide clips” is not an accurate description of these particular configured
pixel spans. A does have two conditions at0; direction passed in A, which also
argues against claiming every duplicated anchor automatically fails.

B's clip was made from original v7 B source frames60..119, visually retimed to90
frames at24fps. A's124-frame clip came from v7 A54..119, retimed visually only.
Their audio was not connected. The shared canonical VoiceStudio WAV remained
separate editorial audio. The guide manifest reports native864×480 FFV1 inputs
with actual frame counts124 and90; filenames alone are not this evidence.

## Verified native API behavior and exact limits

`ComfyUI/comfy_extras/nodes_minimax_h3.py:37–54` defines:

```text
target frame count = smallest n >= max(5, requested length), n mod17 ==5
video latent T     =2 when n<=5; otherwise ((n-5)//17)*5+2
FPS                =24
```

Thus5,22,39,56,73,90,107,124,141,... are valid native clip lengths.
For this project124 frames yield37 video latents;90 guide frames yield27.
Ten logical seconds typically need native243 frames, while fifteen logical
seconds need362. Native node length input is5..3600 and snaps upward; the input
maximum is not a promise that every resulting long duration was trained. Its
tooltip identifies approximately124..362 as trained range. The packaged
production builder separately limits logical shots to15 seconds/360 editorial
frames. These are distinct UI, rounding and production-policy limits.

`MiniMaxH3AddGuide`, lines166–240, actually does the following:

- The schema permits integer `frame_idx` from−9999 to9999. Nonnegative values
  are pixel-frame indices. Negative values resolve against **native** frame
  count: with124 frames,−1 means123, not editorial119.
- An image batch shorter than5 is reduced to **one** frame; batches of2–4 do
  not provide2–4 temporal anchors.
- A batch of5 or more is shortened, not extended, until its count mod17 is5.
  For example120 input guide frames become107;124 and90 remain unchanged.
- It requires resolved start>=0 and start+effective guide length<=native frame
  count. A90-frame guide in124 frames can start anywhere0..34;24 is legal.
  A124-frame guide in124 frames fits only at0.
- It resizes/cover-crops guide images to target geometry, encodes that guide
  independently through VAE, then appends a keyframe conditioning entry. It
  does not snap starts to17, inspect source quality/FPS, reconcile overlapping
  geometry, de-duplicate anchors, or blend contradictory conditions.
- Every guide uses the original target AV latent for dimensions/count. Chaining
  AddGuide changes conditioning, not the sampler's target latent.

Consequently **“frame_idx must be divisible by17” is not an installed API
requirement**. Phase-aligned starts are an experimental choice justified by the
representation below, not a source-enforced rule or guaranteed repair.

## Verified phase math

`comfy/ldm/minimax/model.py:30–31,95–102` defines
`FRAME_PER_TOKEN=(1,4,4,4,4)` and `FRAME_RESCALE=5/3`.
`_video_t_grid` uses the exclusive cumulative sum of those spans.
`PackedLayout`, lines354–399, places each guide's video grid at
`target_origin + (5/3)*resolved_frame_index`; each independently encoded clip
starts its own1,4,4,4,4 pattern at that offset. All numbers below are pixel-frame
coordinate equivalents before the common5/3 scale, not measured VAE receptive
fields or a claim that one latent copies exactly those source pixels.

```text
Target124,37 latent starts:
0,1,5,9,13,17,18,22,26,30,34,35,39,43,47,51,52,56,60,
64,68,69,73,77,81,85,86,90,94,98,102,103,107,111,115,119,120

Guide90,27 latent starts, shifted to24:
24,25,29,33,37,41,42,46,50,54,58,59,63,67,71,75,76,
80,84,88,92,93,97,101,105,109,110
```

Target starts mod17 are `{0,1,5,9,13}`. Offset24 has residue7, producing guide
residues `{7,8,12,16,3}`. The two sets of token starts have **no intersection**
over this actual shot. Shifting by a multiple of17 preserves the full pattern;
merely picking another arbitrary target token start does not preserve the whole
clip's alternating short/long phase.

Reported pulse onsets are25,42,59,76,93,110. These equal exactly
`24 + 1 + 17*k` for k0..5: the first four-frame token after each short token in
the shifted guide. This arithmetic equality is verified from source and saved
reported onset indices. Exposure measurements/visual onset estimates come from
the prior QA; this investigation did not remeasure pixels or isolate causality.

## VAE temporal behavior supplies another17-frame mechanism

`comfy/ldm/minimax/vae.py:418–455` defaults to temporal downsampling product4,
`clip_length=17`, `token_drop=3`. Derived settings are:

```text
frame_pre_padding =3
tokens_chunk_size =5
token_overlap     =2
frame_overlap     =5
```

`encode_temporal`, lines665–678, independently encodes17-frame source chunks,
repeat-pads a short final chunk, concatenates their latents and drops the final3
tokens. Single-frame encode has a separate one-latent path at793–808.
`decode_temporal`, lines730–790, uses overlapping latent windows, removes
pre-padding and blends5-frame overlap regions. Thus a17-frame cadence is also
native to encode/decode chunking; cadence alone cannot distinguish guide-grid
phase interaction, source conditioning, or VAE behavior.

The guide is conditioning, not a hard local replacement of24..113.
`model.py:159–200` shows the dense attention path with `mask=None`, while
PackedLayout inserts all guide-condition rows into the packed sequence. A
guide's influence is therefore not source-enforced to stop at its nominal
pixel span. This makes out-of-span influence plausible and explains why an
artifact before24 does not by itself exclude the clip as a contributor. It does
not identify which condition caused those earlier ghosts.

## Inherited bad source and geometric incompatibility

The independent v9 B review found doubled source rails/background around v7
B98..101, conservatively excluding97..104. The guide uses the whole60..119
source, so it includes that contaminated interval. Slow stretching, frame
duplication or FFV1 encoding does not remove those double images.

The same review compared accepted A119 at the gate with v7B60 already inside:
gate geometry, family scale/positions and toddler stride phase differ. Adding
that inside-only clip at24 leaves the crucial gate crossing unsupported and
can introduce a competing spatial state. Separate still8 and still119 do not
certify a valid bridge between the states. These saved visual findings are
independent of the token-phase arithmetic. Do not label all B defects a pure
exposure problem or apply blind temporal blends to hide them.

No clean complete B guide was established from the inspected v7 B60..119 or
the canceled cut-up/optical-flow reconstruction. Short visually cleaner spans
60..96 and105..119 remain candidate source material, not an approved continuous
124-frame bridge. The native22-frame60..81 subrange can be a bounded reference,
but does not supply a whole five-second entry action.

## Supported guidance choices

### Preferred dense profile: one coherent full batch at0

Use a new, actually inspected native124-frame,24fps,864×480 rear-facing guide
from the correct gate-threshold pose through the inside path. Its first frame
must be the actual accepted predecessor used119 PNG, with matching gait phase,
hand endpoints and gate geometry. Place the full batch at0. This gives the same
temporal phase as the target throughout and follows the successful A graph's
dense-guide arrangement without assuming A's assets suit B's location.

Use the existing Ref2VA/AddGuide-supported path as an explicitly named dense
profile; do not silently bypass the new FL2VA adapter's first/last-only
contract. Do not assume the FL checkpoint has been tested with dense AddGuide
just because the generic node accepts an AV latent. If retaining a separate
initial still0, its image must match guide frame0 exactly; conflicting duplicate
starts would undermine this comparison. Avoid redundant intermediate stills
that disagree with the same dense guide.

This strategy is supported by installed node wiring and A's observed result.
It is not a guarantee and currently requires a clean B guide that we do not
have. Do not manufacture one by crossfading through a mismatched gate, looping
an incomplete walk, or stretching contaminated v7B60..119.

### Sparse fallback: clean single PNGs at one17-frame phase

The installed API also supports separate one-image anchors at
`0,17,34,51,68,85,102,119`. Each lies at the target's short-token phase. Use only
individually inspected, mutually coherent rear-facing poses/layouts, with0 from
the actual accepted predecessor. No multi-frame clip is present in this
fallback, so it avoids restarting an off-phase dense clip at24. It remains
sparse probabilistic conditioning and cannot guarantee the intermediate walk
or prevent morphing. This17-grid selection is a proposed conservative design,
not an official mandatory schedule or an empirically verified B solution.

Changing24 to17 or34 with the same bad clip would be an alignment experiment,
not a production repair: its spatial start and contaminated frames still fail
the source contract. Never interpret alignment as permission to skip source QA.

## Saved official templates and evidence limits

The saved official `video_minimax_h3_r2v.json`,
`video_minimax_h3_i2v.json` and `video_minimax_h3_i2v_continuation.json` were
inspected recursively; none contains `MiniMaxH3AddGuide`. They establish native
task examples but do not prescribe or validate the particular partial90-at24
schedule. No saved official multiframe example with a contradictory offset
rule was found. The installed AddGuide implementation explicitly supports
arbitrary pixel indices and chained anchors; do not invent an unsupported ban.

No additional downloads, installations, model encodes/decodes, renders or queue
queries were used. Pure Python arithmetic reproduced the grid sets and the
onset correlation. Root should retain rejected complete native AV and the
unchanged original Alice WAV, and test a new guidance profile only after its
actual guide media pass the continuity/geometry/exposure checks. No guide
arrangement in this note is declared accepted film output.
