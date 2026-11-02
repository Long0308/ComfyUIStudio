# BRIEF.md template — JennieJoyKids (3D cartoon), with NEWTECONS variant

Copy to the episode's own folder as `BRIEF.md` and replace every `{...}`. Process source: [beamnxw, Motion Engineering with Opus 5.5](https://x.com/beamnxw/status/2108616740846420354) (five decisions in the brief, shots written as frame events). Roles and gates: [SKILL.md](../SKILL.md). The numbers below are **starting values from the existing JennieJoy contract** ([jenniejoy-remotion](../../jenniejoy-remotion/SKILL.md), [jenniejoy-hyperframes](../../jenniejoy-hyperframes/SKILL.md)); anything marked `chưa đo` has not been measured and must be confirmed in the first preview.

---

```markdown
# BRIEF — {film_id} / {component name}   (v{NNN})

film_id: {04-milk-and-mom}            production_domain: jenniejoy_cartoon_3d
owner (live agent ID from PLAN): {id}  reviewer (separate session): {id}
fps: 30            master: 3840x2160            2K film: 2560x1440 = lanczos downscale of the finished 4K Master (downscale: PLAN T-V10; lanczos: `editorial/master-4k-v001/DOWNSCALE-2K.md`); no separate 2K SeedVR2 run
duration: {seconds} s = {frames} f   (JennieJoy full master: 84 s = 2520 f; intro 90 f; dialogue 2070 f; outro/cards 360 f)

## D1. Purpose  (one sentence: what must the child understand or see?)
{e.g. "Show 12 vocabulary words, one at a time, each with its picture, its EN word, its VI meaning."}

## D2. Copy and assets  (exact strings; longest version listed)
| id | EN | VI | picture asset (path + SHA256) | audio WAV (path + SHA256 + trimmed duration f) |
|----|----|----|-------------------------------|-----------------------------------------------|
| W01 | Creamy | {VI} | {path} | {path}  ({n} f) |
Longest EN: "{...}"   Longest VI: "{...}"   -> layout MUST be checked with these two.

## D3. Style tokens  (hex / px / seconds, not adjectives)
- Keyword pill: bold white text on pink/fuchsia `#FF2E7E`, radius {px}, padding {px}
- Font family + weight (EN): {font}, {weight}.  Font (VI, with diacritics): {font}  -> check diacritics in the RENDERED still
- Captions: bilingual, EN line on top, VI line below; max {2} lines each; safe margin {px}
- Palette: {tokens from the film's own style guide}; no assets from NEWTECONS
- Banned: {e.g. particle bursts, glow, strobing flashes, text under 48 px at 3840x2160 (chưa đo for child legibility)}

## D4. Motion rules
- Driven ONLY by `useCurrentFrame()` + `interpolate`/`spring`; no CSS transitions; seeded randomness (seed = {int})
- Entrance spring: duration {f} f, damping {n}, stiffness {n}, overshoot {clamp true/false}
- Supporting label delay after headline: {3} f
- Reading hold counted from the first frame where the word is LEGIBLE: {n} f (min); VO word must be fully inside the hold
- Constants live together in `{file}.ts` (offset, destination, duration, spring)

## D5. Boundaries and sound
- Scene IN state / OUT state per scene (position, scale, highlighted field) — see table below
- Stems: dialogue / music / SFX separate. Music ducked -14..-18 dB under dialogue
- Dialogue trimming is done ONCE upstream; do not trim again in Remotion

## EVENT TABLE  (seconds -> frames at 30 fps; local = inside the Sequence, global = on the master)
| event | scene | local f | global f | subject | behaviour | destination / state | hold (f) | sound cue |
|-------|-------|--------:|---------:|---------|-----------|---------------------|---------:|-----------|
| E01 | intro | 0   | 0   | logo plate | scale 0.30 -> 1.00 + fade in | centre, final position {x,y} | 30 | none (silence) |
| E02 | intro | 18  | 18  | title text | slide up, settle | below logo | 45 | soft whoosh, peak on f {n} |
| E10 | card W01 | 0 | {G} | picture card | enter from {side} | centre | — | pop on card land |
| E11 | card W01 | 8 | {G+8} | EN word pill | appears after card settles | {pos} | {25..46} | WAV W01 starts f {n} |
| E12 | card W01 | {n} | {G+n} | VI caption | fade in | under pill | until card end | none |

## SCENE BOUNDARY TABLE
| scene | IN state | OUT state | overlap with next (f) |
|-------|----------|-----------|-----------------------|
| intro | black | logo plate + title, final layout | 0 |
| cards | {state} | {state} | {n} |

## THREE-STILLS GATE  (render before any motion polish)
- opening  : `npx remotion still {entry} {CompId} out/still-open.png  --frame=0`
- result   : `... out/still-result.png --frame={result frame}`
- closing  : `... out/still-close.png --frame={last frame}`
Checks: main text readable (longest EN + longest VI) · result visible · nothing cropped/overlapping · closing has room.

## AUDIO CUE LIST  (every cue sits on an event frame; fps labelled)
| event | frame @30fps | file | offset into clip (ms) | gain (dB) | stem |
|-------|-------------:|------|----------------------:|----------:|------|

## REVIEW-CUT GATE SECTIONS  (mandatory for any review cut or master; gates G-CAP..G-MOTION in create-video-jenniejoykids/SKILL.md)
quality_label: {exactly the on-screen label, e.g. "REVIEW 1080p · native upscaled"}   source_note: {e.g. "review cut, native 864x480 H3 clips upscaled to 1920x1080, NOT the 4K SeedVR2 master"}   (written into RECEIPT.json, file name, Studio registration; on-screen label "REVIEW 1080p · native upscaled"; "4K" only for 3840x2160 from the SeedVR2 master; gate G-LABEL; ffprobe 1920x1080 for a 1080p label, RECEIPT.quality_label equals the on-screen label)

### G-CAP. Word-level caption timing + karaoke style
- Timing source: {path to word-timing JSON + SHA256}; aligner/ASR actually used: {name, observed}; one JSON per dialogue line, each bound to that shot's receipt WAV SHA256 {sha}
- Units: start/end frame @30 fps, GLOBAL; WAV start frame on the master {n}; offset corrections are made in the JSON build, never by moving the WAV
- Karaoke style (hex / px / frames): unspoken {colour, opacity}, active word {colour, scale, underline}, spoken {colour}; keyword pill `#FF2E7E` kept; EN line top, VI line below follows the same line window
- Line window: appears {n} f before its first word, leaves {n} f after its last word; tolerance highlight-vs-JSON {3} f (chưa đo)

### G-ICON. Keyword icon events  (one row per spoken target vocabulary term; every term needs a row)
Target terms = the 12 vocabulary terms with the spellings of `vocabulary_icons[].term` in the word-timing JSON (creamy, smooth, liquid, dairy cows, farm, fresh, yummy, warm-cold, bones, yogurt, cheese, ice cream; icon files include dairy-cow.png, warm-cold.png for the warm and cold words, ice-cream.png; list also in jenniejoy-hyperframes SKILL) plus any term listed here in D2. Pop frame = the word's `start_frame` (= entry `start_frame` + round(`start_s` x 30)) from `editorial/word-timing-v001/WORD-TIMING-v001.json`; if `raw_whisper_start_s` is not null and differs from the calibrated `start_s` by more than 0.3 s, use entry `start_frame` + round(`raw_whisper_start_s` x 30).
| id | word | line/shot | icon file (path + SHA256) | frame @30 global (= word startF + lead) | motion (spring duration/damping/stiffness, overshoot, sparkle f) | hold (f) | exit | position (safe area, clear of mouth) |
|----|------|-----------|---------------------------|-------------------------------------------:|-------------------------------------------------------------------|---------:|------|---------------------------------------|

### G-CUT. Scene-boundary transition table  (one row per scene/shot boundary; no row = fail)
| boundary | from -> to | boundary frame @30 global | class carry/cut | tail handle frames available (outgoing, hash-bound) | transition type (iris / cloud wipe / whip-pan / virtual camera / dissolve / motivated hard cut) | frames | placement (centred / ends on / starts on boundary) | motivation if hard cut |
|----------|------------|-------------------------:|-----------------|-----------------------------------------------------:|-------------------------------------------------------------------------------------------------|-------:|---------------------------------------------------|------------------------|
Timeline stays {2520} f; audio start frames unchanged; partial-render window per boundary = B-30 .. B+30 @30 fps.

### G-BRIDGE. Location-change action bridges
| boundary | location A -> location B | bridge: action shot (clip path + SHA256, frames) OR declared motivated transition (type, frames) | critic evidence |
|----------|--------------------------|--------------------------------------------------------------------------------------------------|-----------------|

### G-END. Ending beat + logo frames
- Ending beat: {what the last story image is, e.g. iris-out on the closing image}  frames {a}-{b} @30 global
- Logo: {path + SHA256}  frames {c}-{d}; hold {n} f; last frame = logo: {yes/no}
- Budget: fits inside the {2520} f master, or PLAN-declared budget change: {none / ref}; music/SFX tail: {cue ids}

### G-MOTION. Technique map  (awesome-opus5-5-videos; link, do not copy prompt bodies)
| technique | inspired_by (slug, handle, post link) | where applied (frames / boundary id) | our adaptation (numbers) |
|-----------|----------------------------------------|---------------------------------------|---------------------------|
An empty table fails the gate. Technique picks: [awesome-opus55-prompt-index.md](awesome-opus55-prompt-index.md).

## ACCEPTANCE
- [ ] 3 stills approved by a reviewer in a SEPARATE session (<= 5 corrections, 4-field format)
- [ ] Both neighbouring boundaries checked after every local edit
- [ ] Export is the approved render; `ffprobe` shows {3840x2160, 30/1, {frames} f}; watched at normal speed
- [ ] Review-cut gates G-CAP, G-ICON, G-CUT, G-BRIDGE, G-END, G-MOTION each PASS from a critic who WATCHED moving partial renders (every boundary B-30..B+30, the ending, caption/icon timing vs the word-timing JSON); `quality_label` written
- [ ] Brief + event table + cue list + SHA256 saved next to the export
Receipt is not acceptance: the PASS must come from a critic who is not the builder.
```

---

## NEWTECONS variant note (`newtecons_live_action`)

Use the same five decisions and event table, with these changes. Do not carry any JennieJoy value over unless it is restated here.

- **Scope:** overlays only (title card, lower-third, logo sting, caption plate) placed on footage that local ComfyUI produces. This skill never generates character footage; follow [create-video-newtecons-comfyui](../../create-video-newtecons-comfyui/SKILL.md) and [local routing](../../create-video-newtecons/references/local-comfyui-routing.md).
- **Clock:** take fps, duration and resolution from the NEWTECONS film manifest. The existing skills state 45 s / 24 fps / 1080 frames for the live-action film; confirm in the manifest before writing frame numbers, and label every frame `@24fps`.
- **Brand:** original corporate logos and the NEWTECONS palette/type from its brand registry (not recorded in this skill: `chưa đo`/unconfirmed). No pink `#FF2E7E` pill, no cartoon vocabulary cards.
- **Captions:** Vietnamese cast and audience; add EN only if the manifest asks.
- **Gates:** the NEWTECONS user-review gates (wardrobe, candidate pending review) live in the NEWTECONS skill and still apply; an overlay PASS does not approve any underlying footage.
- **Review-cut gate sections (added 2026-10-27, written for the cartoon domain):** the G-CAP, G-ICON and G-BRIDGE sections are JennieJoy-specific (karaoke vocabulary captions, icons, cartoon bridges). Only the G-CUT boundary table and the G-END ending-beat table are domain-neutral in form; if used for NEWTECONS, label frames `@24fps`, use the NEWTECONS logo and brand tokens, and do not carry the pink pill or cartoon icons over.
