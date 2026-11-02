> MERGED into SKILL.md 2026-10-28
## Transition presets, ending segment, segment build (T-E42 + T-E45 P2) - index for the root merge

Merge the parts below into `studio-video-engine/SKILL.md` in this order (SKILL.md itself was not edited by the builders).

| Part | File |
|---|---|
| Engine: preset catalog, boundary rows, ending params, derived timeline (logo hold, end card, plate placement, disc layout) | `studio-video-engine/SKILL-SECTION-T-E42-engine.md` |
| Kit: catalog sync, renderers, validation, warnings | `remotion-kit/SKILL-SECTION-T-E42-kit.md` |
| Kit: feasibility, `--list-presets`, `composite_only`, music bed, engine adapter | `remotion-kit/SKILL-SECTION-T-E42-kit-records.md` |
| Kit: the ending as its own joined segment | `remotion-kit/SKILL-SECTION-T-E42-kit-ending.md` |
| Engine: `segments.json` (`jjv/segments/v1`) | `studio-video-engine/SKILL-SECTION-T-E45-P2-engine.md` |
| Kit: segment cache, node keys, incremental build | `remotion-kit/SKILL-SECTION-T-E45-P2-kit.md` |
| Kit + CLI: `edit-render`, hash cache, `jjv edit` verbs | `remotion-kit/SKILL-SECTION-T-E45-edit.md`, `engine/editorial/CLI-PATCH-edit.md` |

**Principle (one paragraph).** A transition is a compositing layer applied after the shot videos exist. Changing one preset in `boundaries.json` (one field) then `jjv editorial build-config`, the adapter and a kit render never re-renders a shot (no H3, no SeedVR2). A preset that plays the outgoing tail is feasible only when the existing hash-bound handle holds `ceil(4N/5)` native frames beyond the editorial cut (the engine `check_tail` rule); otherwise validation refuses, naming the boundary and the missing frames, and no GPU work is requested. `render.cjs --list-presets` shows the per-boundary table; every render record lists the shot source hashes and, with `--previous-record`, states `composite-only: no shot source changed`.

**Ending as its own segment.** The segment plan covers `[0,total)` exactly. The main segment owns the iris (it is a mask over the last shot picture, i.e. it depends on shot video) and ends at the first frame with no shot video (`logo_disc.in + 3`); the ending segment (logo hold, vocabulary cards, plate, EndLogo) is vector + fonts + logo only, so re-rendering it never decodes or needs any shot clip (in the master it needs no restored 4K core). Segments are silent closed-GOP h264 with identical codec parameters and are joined by stream copy; the audio is one mix rendered once (not cut at the join: 1600 samples per frame, join sample `J*1600`) and muxed. The join record proves framemd5(film) == concat of the segment framemd5 for every frame, pts continuity, decode clean and the audio join; a re-render of the ending alone reproduces the joined film byte for byte (same sha256).

**Correction to the ending section.** Review clips are mounted with `<OffthreadVideo muted>`: clip audio is NOT mixed into the film (the earlier note that the clips carry audible audio that the full render plays was wrong; Fork J proved the mix PCM is identical with loud-audio clips).

**Known gaps (not done).** No 4K segment film was rendered (master keys, plans and `--explain` are tested, 10 ending frames at 4K were rendered through the segment path). Captions and icons are part of the shot-span slice, so a caption fix re-renders the segment(s) of the shot that shows it (1 segment, 160 f, 27.9 s wall in the measured case) rather than an overlay over a cached picture segment. The engine `plateStyle` / EndLogo fade numbers come from `episode-text.json`, not from the engine record.
