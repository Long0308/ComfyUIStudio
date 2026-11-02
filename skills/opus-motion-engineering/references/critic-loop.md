# Critic loop, correction format and render/probe commands

Back to [SKILL.md](../SKILL.md). Process source: [beamnxw, Motion Engineering with Opus 5.5](https://x.com/beamnxw/status/2108616740846420354). Brief and event table: [brief-template.md](brief-template.md). Remotion composition and mix rules: [jenniejoy-remotion](../../jenniejoy-remotion/SKILL.md).

## 1. Correction format (four fields, always)

Every correction the critic sends has exactly these four fields. A correction without a frame/location is rejected by the builder.

```text
C1
location:  {composition id} {global f N | scene S local f M}   (always label fps and local/global)
observed:  {what is wrong, as measured or seen; not "feels off"}
change:    {the specific edit: value A -> value B, which constant, which file}
keep:      {what must stay exactly the same}
```

Example (JennieJoy, 30 fps):

```text
C1
location:  Cards, scene W03 local f 8 (global f 2210 @30fps)
observed:  VI caption "Chất lỏng" touches the bottom edge of the picture card; gap 0 px (chưa đo exact: read from still)
change:    caption top offset 24 -> 56 px in cardLayout.ts (CAPTION_TOP); do not change pill size
keep:      pill position, entrance spring, hold length 36 f, WAV W03 start frame
```

Rules for the critic:
- **At most 5 corrections per pass.** Order them: missing information / unreadable text, then timing, then visual detail. If there are more than 5 problems, send the 5 most important and re-review after the repair.
- Review with the brief, the stills and the extracted frame ranges, **in a separate session** with clean context; never the builder's conversation.
- End with a **binary verdict**: `PASS` or `FAIL`. No "mostly good". Name the scope of the verdict (stills only / frames a-b / full export at normal speed). Stills never prove motion, lip timing or rhythm.
- The critic edits nothing. If the critic disagrees with the brief, it says so as a correction against the brief, not as a code change.

## 2. Repair loop (stays local)

```text
critic: <=5 corrections (4 fields)  ->  root accepts/rejects each
   ->  builder applies ONLY accepted edits (one constants block, minimal diff)
   ->  render the touched frames (still or --frames range), plus the two neighbouring boundaries
   ->  critic (new or same clean session) re-reviews those frames
   ->  FAIL: next single biggest gap     PASS: next stage
```

- Root re-runs the gate itself; a builder claiming "fixed" is not evidence.
- The loop ends when the gate is green, not after a fixed number of rounds. If the budget or the user stops it, report the real state.
- After any local edit, inspect **both** neighbouring boundaries before watching the assembled film.
- If the brief changes (copy, font, asset), re-render the landing frame first (the longest-copy check), then replay the entrance.

## 3. Remotion partial renders

Entry file and composition ids depend on the project (the existing template is `../../create-video-jenniejoykids/assets/remotion-template/`; confirm its entry and ids before use). Replace `{entry}` and `{CompId}`.

```powershell
# one frame (still). Frame numbers are 0-based and refer to the composition clock (30 fps for JennieJoy)
npx remotion still {entry} {CompId} out/still-open.png   --frame=0
npx remotion still {entry} {CompId} out/still-result.png --frame=240
npx remotion still {entry} {CompId} out/still-close.png  --frame=419

# a range around a scene boundary (inclusive range; 2 s at 30 fps = 60 frames)
npx remotion render {entry} {CompId} out/boundary-intro-cards.mp4 --frames=60-119

# the approved full render, only after picture + sound passes are accepted
npx remotion render {entry} {CompId} out/{name}-Master.mp4
```

Label scene-local versus global: a local frame 30 in a Sequence that starts at global 120 is global 150. Convert before running `--frame`/`--frames`, because these flags use the composition clock.

## 4. ffmpeg: reference analysis (only when a reference video exists)

```powershell
# overview: 2 images per second, width 960, aspect preserved
ffmpeg -i reference.mp4 -vf "fps=2,scale=960:-1" frames/ref_%04d.png

# consecutive source frames around one event: start 6.2 s, 0.6 s long, at source rate (no fps filter)
ffmpeg -ss 6.2 -t 0.6 -i reference.mp4 -vf "scale=960:-1" frames/event-6p2_%03d.png
```

Label every extracted frame with the reference's own fps and timestamp (a half-second move is 15 f at 30 fps but 30 f at 60 fps). Check key positions against the extracted images; model spatial estimates are approximate.

## 5. ffmpeg / ffprobe: export check (Delivery verifier)

```powershell
# video stream facts
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,nb_frames,duration -of default=noprint_wrappers=1 out/{name}-Master.mp4

# exact decoded frame count (slower; use when nb_frames is N/A)
ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=nb_read_frames -of default=noprint_wrappers=1 out/{name}-Master.mp4

# audio stream present, sample rate, channels
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,duration -of default=noprint_wrappers=1 out/{name}-Master.mp4

# integrity + hash receipt
ffmpeg -v error -i out/{name}-Master.mp4 -f null -
Get-FileHash out/{name}-Master.mp4 -Algorithm SHA256
```

Expected values come from the brief, not from memory:

| Film | width x height | r_frame_rate | frames | duration |
|---|---|---|---|---|
| JennieJoy master (current contract) | 3840x2160 | 30/1 | 2520 | 84.0 s |
| JennieJoy component (e.g. intro / cards) | per brief | 30/1 | 90 / 360 | 3.0 s / 12.0 s |
| NEWTECONS | per film manifest | per manifest (24 fps stated in current skills) | per manifest | per manifest |

A probe mismatch is a FAIL even if the video looks right. A matching probe is necessary, not sufficient: the verifier must also **watch the export at normal speed**, following the first message, the main action and the ending, with sound, and write what was watched (scope of the verdict).

## 6. Delivery record (save beside the export)

`BRIEF.md` (final) · event table with frames · scene boundary table · audio cue list · the three approved stills · critic corrections and verdicts (with session/route actually used) · `ffprobe` output · SHA256 · watch note (who, what scope, normal speed Y/N). Without these the export is a candidate, not an accepted Master.

## 7. Review-cut critic: watch motion, not stills (user-mandated 2026-10-27)

Applies to every JennieJoy review cut or master (gates G-CAP, G-ICON, G-CUT, G-BRIDGE, G-END, G-MOTION in [create-video-jenniejoykids](../../create-video-jenniejoykids/SKILL.md); error DB: [review-cut-v003-user-fail-motion-transitions-ending.json](../../create-video-jenniejoykids/error-db/review-cut-v003-user-fail-motion-transitions-ending.json)). The v003 cut passed a stills-only critic and was then rejected by the user at normal speed, so stills alone can never produce `PASS` for these gates.

The critic (clean session, never the builder) must:

1. **Watch a moving partial render around EVERY row of the boundary table**: boundary frame `B` at 30 fps, render `--frames=(B-30)-(B+30)` (1 s each side, 61 frames inclusive; convert local to global first, see section 3). Coverage is checked against the brief's G-CUT table: a boundary without a watched render is an unreviewed boundary, and the verdict must say so. Judge the transition as designed (type, frames, placement), the carry/cut continuity, and that no hard cut is unmotivated.
2. **Watch every G-BRIDGE location change** and confirm the character's movement to the new place is on screen (or the declared motivated transition is visible).
3. **Watch the ending as moving frames**: the last 3 s (`--frames=2430-2519` for a 2520 f master) plus the first and last decoded logo frames; confirm the ending beat and the logo on the final frame.
4. **Check G-CAP and G-ICON timing against the word-timing JSON, not by feel.** For each caption line and icon event in a sample that includes the first and last line and every target term: read `startF` from the JSON, extract frames at `startF-3`, `startF` and `startF+3` from the partial render (for example `ffmpeg -i part.mp4 -vf "select=eq(n\,K)" -vframes 1 out.png`, with `K` the frame index inside that render), and confirm the active word highlight and the icon pop sit within the brief's tolerance (starting value 3 f, `chưa đo`). Also confirm each spoken target term has an icon event and that the caption moves word by word, not whole line.
5. **Confirm G-MOTION**: each technique listed in the brief is visible at its named frames.
6. Write the verdict with its **scope**: boundaries watched (ids), ending watched, lines sampled, speed (normal Y/N), sound (with/without). Use the usual four-field corrections; the `location` of a boundary correction may be the boundary id plus global frame.

The critic only reports. After any fix, re-render the touched boundary window and its two neighbouring boundaries, then re-review. The honest quality label (native upscale versus 4K master) is checked in the RECEIPT as part of G-END/delivery, not left to the user to discover.

## Lesson 2026-10-27: dY curves cannot see double exposure

Two critic passes (v004, v005) passed the f1010 cross-dissolve on smooth mean-|dY| curves while root saw two mothers and two girls at f1014 in v006. A smooth luma curve says nothing about content overlap. For every dissolve/blend frame, the critic must view the mid-transition frames at full resolution and answer explicitly: "does any character or prop appear twice?" — a yes fails the boundary regardless of dY (error-db `review-v005-dissolve-double-exposure-and-logo-hides-word`).
