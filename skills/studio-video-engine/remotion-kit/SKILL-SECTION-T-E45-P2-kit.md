> MERGED into SKILL.md 2026-10-28
## Incremental composite by segment (T-E45 P2, kit side) - for root to merge into SKILL.md

Principle (U1, U4, U5): a change to an effect, a caption, an icon, a card, the ending or the music is a **compositing-layer change**. The
film is a list of segments; each segment is rendered once, SILENT, as closed-GOP video and cached under a **node key**; the film is the
stream-copy join of the cached segments plus ONE audio mix with its own key. A one-boundary change re-renders the segments that boundary
touches (and the mix only if audio could change), never the rest, and never a shot video (H3 / SeedVR2).

### Commands (all in `remotion-kit/`, CPU only)

```
node render.cjs --config C --segments-file segments.json --segments-build CACHE --explain            # keys, RENDER / COMPLETE / CORRUPT, why; renders nothing
node render.cjs --config C --segments-file segments.json --segments-build CACHE --out film.mp4       # renders stale segments (child --segment runs), joins
     [--force-segment ID,ID] [--build-concurrency 1|2] [--mode review|master] [--workdir D] [--browser PATH]
```

`segments.json` is the engine's `jjv/segments/v1` (written by `jjv editorial build-config`); it becomes `config.segments` and is refused when
its `fps` / `total_frames` differ from the config, or by the existing cut rules (no cut inside an iris / dip / both-pictures window).
Outputs: `film.mp4`, `film.mp4.join-record.json` (framemd5 proof, pts, audio join, `from_cache: true`), `film.mp4.segments-run.json` (also
in CACHE): per segment `key`, `status`, `reason`, `render_seconds`, `cache_entry`, plus `rendered`, `reused`, `estimated_seconds_saved`.

### Node key (`lib/segdeps.cjs`, `lib/segcache.cjs`)

`key = sha256(canonical {kind, pins, hash of every slice part})`.

* **Pins** (outside the config): Remotion version, sha256 of the browser exe and of the fonts, gl, mode, scale, the codec parameter set (crf 18
  review / 16 master, `open-gop=0`, bt709), sha256 of the preset catalog, and the sha256 of the video-relevant kit `src/**` (the audio pin
  also covers the audio-only sources `music.jsx`, `music-plan.mjs`, `feasibility.mjs`).
* **Video slice** (`segment_deps`): global leaves (schema, fps, timeline, theme, motion, clock, waivers, review label in review mode),
  the segment range; shots that intersect (WHOLE record); transitions whose effect window (window + tail window + dip schedule) intersects
  (whole resolved row: params, schedule, overlay, tail numbers); icon events whose pop intersects (and the shot each pops on); for the
  outro: strings, a card meta `{count, windows}` and the cards the segment can show (window +- the lead / cross-fade margin); intro block +
  opening + logo for the intro; the ending **disc** block (everything but plate / audio keys) from the first disc frame on, the **plate**
  block (`plateStart, speechEndFrame, plateEn, plateVi`) from the plate start on; and the sha256 (never paths) of exactly the picture /
  tail / icon / opening / logo / card-icon files the segment's frames mount (computed with the compositor's own `pictureMode` / tail
  windows: an ending segment mounts no shot video, so a replaced clip never makes it stale).
* **Audio slice** (narrowed in the edit path, see SKILL-SECTION-T-E45-edit.md): exactly what the one mix reads: stems (sha) + policy, the dialogue WAV of each shot with its
  window, the card WAVs + windows, the end-card tail numbers (legacy music) or the word windows (music bed policy), the mix mode. NOT in it: any picture / tail clip or
  transition row (every clip is `<OffthreadVideo muted>`: proved by a loud-audio-clip test), strings, intro, icons, theme, review label, plate text, caption text.
* A stale reason is the leaf diff against the previous build's slice (`last-run.json`), e.g. `slice changed: range.1, transition:T1010.frames`.

### The cache

`CACHE/composite.segment/<key>/{segment.mp4, segment.mp4.render-record.json, record.json}` and `CACHE/audio.mix/<key>/{mix.wav, ...}`. An entry
is stored whole or not at all (temp folder, then rename). **COMPLETE** = same key, bytes match the record: never re-rendered. **CORRUPT** =
the bytes or the render record no longer match: `--explain` shows it and the build **refuses, names the segment, writes no film**
(`--force-segment ID` re-renders it); the join re-verifies sha256 + framemd5 of every segment anyway. If the kit source changes while a
child renders, the build stops instead of storing an entry under a key it was not rendered with. Joining cached segments rendered under
earlier plans uses `joinSegments({cache: true, expectedTotal})`: plan sha / total of a record are not compared (the key identifies a
segment); contiguity, identical stream parameters, framemd5 column equality, pts continuity, frame count, decode and the audio join are.

### Proof on the first episode (derived v013 build: 3374 f, 49 engine segments, review mode, CPU, scratch cache)

| step | segments rendered | audio mix | CPU time (wall) |
|---|---:|---|---:|
| cold build -> film A | 49 of 49 (541 s of segment renders) | rendered 50 s | 630 s (join 39 s); `H_film == H_seg` 3374/3374 |
| one boundary: a `cut_push` 12 -> 10 frames (boundaries.json -> build-config -> adapter -> kit config) | 2 (its transition segment and the shot segment after it: stale `range.1, transition:<id>.frames` / `range.0`) | rendered (transition rows are in the audio slice: conservative) | 108 s; ~518 s of cached render reused |
| only the music stem file changed | **0** | rendered | 99 s; the video frames digest equals film A |
| one card string (`cards[5].vi`) | 5 (the card's own segment, the transitions on both sides and the two neighbouring card segments: the lead-in and the cross-fade) | cached | 90 s |
| plate text (`ending.plateEn`) | 2 (the plate transition segment and the ending segment) | cached | 59 s |
| a flipped byte in a cached segment | build REFUSED (`segment cache refused: <id> ... sha256 ... differs from its record`), no film | | `--force-segment` re-rendered 1, film = byte-identical to the build before the corruption |

Pixel parity: for 6 segment first / last frames (f1010, f1021, f1022, f2145, f2230, f3314) the PNG a cached segment renders is byte-identical to
the same frame of the full-film PNG sequence; the joined film is within 33.7-40.8 dB PSNR of the lossless frames at both sides of 6 cuts (the
h264 crf 18 loss; the control level for two encodes of one picture is 39-42 dB; no seam). A 4K (scale 2) ending range of 10 frames renders through the
segment path (13 s, 3840x2160, no shot video staged).

### The property test (spec 3.3 gate)

`tests/round14-p2-property.test.mjs`: for 5 segment kinds (intro, shot span, transition, cards, ending) of a synthetic episode with every
leaf kind, every config leaf outside the segment's slice is mutated (greedily, all at once; a mutation is kept only if the config and the
sources still validate and the key is unchanged) and the first / middle / last frame must be BYTE-IDENTICAL (~110 leaves per segment). Non-vacuity: leaves the compositor reads
(`theme.mint`, `strings.cardsHeader`, `intro.kicker`, `ending.plateEn`) change pixels AND the key. **Mutants killed**: a slice function that drops
`global.theme` -> `theme.mint, theme.pink` named; drops `strings` -> `strings.cardsHeader`; drops `ending.plate` -> `ending.plateStart, plateEn, plateVi`.
The same check on the real first-episode config (209 leaf classes, 1548 leaves, 8 segments incl. intro / transition / card / iris / logo hold /
ending, ~1000 leaves mutated per segment): 8 of 8 byte-identical.

### Limits (stated)

* Audio: the mix is rendered once per audio key (~45 s CPU, no video) and only when its slice changed (R15-A3: property test over every config leaf, two killed mutants).
* The cards slice includes the lead-in and cross-fade margin, so a card string also stales its two neighbour segments.
* Master mode: keys, pins and `--explain` are tested (mode / scale / crf in the key; master keys differ from review keys); no 4K film was rendered.
  A master build needs the receipt-bound master config; the master adapter output for the old hand-built timeline fails the current dip rule without its waivers.
* Property test is greedy-batch (all outside-slice leaves at once, bisected on a failure): it proves "no single offender" only up to cancellation.
