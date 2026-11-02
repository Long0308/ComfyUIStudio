> MERGED into SKILL.md 2026-10-28
## remotion-kit: feasibility, composite-only records, music bed, engine adapter (T-E42, kit side)

(Replacement/addition text for `studio-video-engine/SKILL.md`; the root merges it next to `SKILL-SECTION-T-E42-engine.md`.)

**Effects are a compositing layer, so changing one never re-renders shot video.** A transition preset only recombines pictures that already exist: a preset that plays the outgoing clip's native tail needs `ceil(4N/5)` native frames beyond what the editorial cut uses (and its last index inside the file), exactly the engine's `check_tail` rule (`lib/tailcheck.cjs` `tailFits`, proven against the engine on a 33,120-case grid). Where the bound clip has the frames the preset is available; where it does not, the build is refused with the missing frames and "no GPU work is requested" — it is never turned into a re-render. The kit therefore (1) lists per boundary what the handles allow, (2) refuses a chosen tail preset with a missing or short handle before any bundling, and (3) writes into every render record whether any shot source changed.

### `render.cjs --list-presets`

```
node render.cjs --config kit-config.json --list-presets [--boundary T1010|1010] [--mode review|master] [--master-config MASTER.json] [--catalog F]
```

Prints JSON and exits: no bundling, no browser, no staging; only `--config` is needed. Per boundary: `current {type, preset, frames}`, `tail {startFrom, editorialFrames, fileFrames, nativeFps, haveNativeFrames}` (null = no handle), and for every ready preset `{available, needsTailFrames, haveNativeFrames, maxFrames, reason, whyNot}` (`whyNot` is the engine's refusal text, `maxFrames` the largest legal frame count that fits). The table agrees with `engine/editorial/presets_cli.py` on every preset (test `4j`). `--mode master` reads the config as the MASTER kit config (its 4K tails); giving `--master-config` in review mode adds `master_covers` / `master_why_not` per preset, because a preset available in review can be unavailable in master. Pure logic: `src/feasibility.mjs` (`presetAvailability`, `tailHandleIssues`). Real handles of the first episode: T1010 7 native tail frames (tail presets up to 8 frames), T1310 13 (16), T1610 15 (18); a boundary without a tail clip offers only the `tail_frames: none` presets plus nothing else.

`render.cjs` calls `tailHandleIssues(config)` right after `validateConfig` for every run (full, range, stills, `--check-only`): `D1 (dip_white_legacy): tail handle too short: missing 2 native tail frame(s) (...); no GPU work is requested; choose a preset without a tail or restore the tail separately`. `validate.mjs` is not changed by this; the handle numbers come from `transitions[].tail` (`startFrom`, `editorialFrames`, `fileFrames`, optional `nativeFps`; else measured on the bound file by ffprobe, else derived from the editorial cut).

### Render records: `shot_sources` and `composite_only`

Every render record (full, `--range`, `--png-seq`, stills) carries `shot_sources` (sha256 of every picture clip, tail clip and dialogue WAV that was staged; key = role + staged label) and `shot_sources_sha256`. With `--previous-record PATH` (any earlier record; one from before this field is read through its `staged_inputs`) it also carries:

```
composite_only: {value, scope: "all"|"partial", previous: {path, sha256, output_sha256, config_sha256}, unchanged: n, changed: [{key, previous, current}], statement}
```

`statement` reads `composite-only: no shot source changed vs <previous record sha12> (<path>)` only when every shot source hash is identical; otherwise `NOT composite-only: n shot source(s) changed vs ...: <keys>`. A source that appeared or vanished counts as a change. A `--stage-needed` run compares only the sources it staged and says so (`n of m previous sources compared: partial staging`). The statement is also printed to stderr. Use it as the proof that an effect change touched no shot video.

### Music bed policy (`ending.music_bed`)

The engine declares `{extend: loop_phrase_crossfade|none, loop_start_s, loop_end_s, crossfade_frames, duck_db, duck_attack_frames, duck_release_frames, duck_under: words}`; the kit config carries it as `config.music = {stemSeconds, bed}` (or `config.ending.musicBed` + `config.music.stemSeconds`). `src/music-plan.mjs` (pure) plans it from the total film frames, the stem length and the word windows (dialogue words plus card windows, merged): `{segments: [{from, durationInFrames, startFromFrame, fadeIn, fadeOut}], duck(frame) -> gain, uncovered}`. A film that fits in the stem is one segment. Otherwise the first segment plays the stem up to `loop_end`, every later one starts `crossfade_frames` earlier at `loop_start - crossfade_frames`, so at the join the old pass is exactly at `loop_end` and the new one exactly at `loop_start`; the crossfade is linear in / linear out and sums to 1 on every overlap frame; the last segment ends with the film on a fade-out of `crossfade_frames`. Ducking is `duck_db` under every word window with a linear-in-dB attack before and release after. `extend: none` plays the stem once as before and reports `uncovered` frames. `src/music.jsx` renders the plan with Remotion `<Audio>` segments; `film.jsx` mounts it only when `selectMusicMode(config) === 'plan'` (a policy exists). Without a policy the stem and the end-card tail play exactly as before (parity untouched); with one the plan covers the whole film including the end card, so the legacy end-card tail is not mounted. The stem must be UNDUCKED: a stem with dialogue ducking baked in would be ducked twice and would loop its baked windows.

### Engine adapter: `episodes/ep04/adapter-engine.cjs`

```
node adapter-engine.cjs --review-config review-config.json --events events.json --receipt build-summary.json --episode-root DIR --episode-text FILE [--allow-outside PATH]... --out kit-config.json
```

Maps what `jjv editorial build-config` writes to the kit config, so a change made only in `boundaries.json` + ending params (a swapped preset, `derive_timeline`, `music_bed`, `logo_disc_layout`) reaches the film with no adapter edit. The build is bound exactly like the first-episode adapter (`loadBuild` + the unforgeable BOUND token + the engine build summary receipt; `--episode-root` resolves the word-timing path). Carried from the engine records: preset `type`/`preset`/`renders_as`/`params`/`schedule`/`overlay`, tail numbers (`verifiedFrames` = `outgoing_tail.tail_output_frames`, plus the probed `nativeFps`), cards with start/frames from the engine config (derived timeline included), ending (iris, disc layout from `ending.logo_disc_layout`, plate and `speech_end_frame`, music bed). Not in the engine records, so read from the episode text file (`jjk-remotion-kit/episode-text/v1`, the first episode's is `episodes/ep04/episode-text.json`): intro and strings, Vietnamese captions per shot, card ipa/vi/example/icon, opening image, music/ambience stems, `ending.tailFromSeconds`, the disc layout when boundaries declare none, `captionLines`. A missing key is refused naming it. Every path is episode-relative, refused when it leaves the episode root unless named by `--allow-outside`, and hash-verified (an asset without a recorded sha256 is hashed and listed in `provenance.unbound_assets`). The result validates with `collectIssues` and passes `render.cjs --check-only`; on the real episode a derived timeline (cards 90 frames, 3240 main + 60 end card = 3300 frames) was checked end to end.
