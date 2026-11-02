# studio-video-engine: stage details

Moved out of `SKILL.md` on 2026-10-27 (audit gap 6: merge the SKILL-SECTION files). The text below is copied
verbatim from the named source file. `SKILL.md` keeps the short version and the conflict markers. The source
SKILL-SECTION files were left in place; they are now duplicates and may be deleted by root.

Contents: Audio (T-E43) · Word timing (T-E33) · Transition presets and ending (T-E42, engine side) · `jjv qa review` usage (T-E36).


---

## Audio

Source: `engine/audio/SKILL-SECTION-audio.md`

### Audio stage: `jjv audio music|sfx|mix` (T-E43, replaces the "Planned: audio stage" section)

`engine/audio/*.py` (each file <= 400 lines, no domain/episode literal; `tests/test_audio_cli.py` pins both) + `recipes/audio/*.json`.
Procedure and input contract: skill `jenniejoy-music-sfx-yue` (`references/input-contract.md`). Everything a recipe says is data; nothing here
names a model file, style word, cue class, loudness number or episode.

| Verb | CPU/GPU | What it does |
|---|---|---|
| `music plan --episode E --out DIR [--review-config F --shot-pack F --total-frames N --brief F --bpm --key --instruments --takes T --candidates K --seed N --recipe ID] [--dry-run]` | CPU | Film length (`--total-frames` > review config `total_frames_with_endlogo` > `total_frames` > episode timeline; never squeezed). Brief = recipe default < **derived from the script** (`brief.py`: words/second of `dialogue[].speech_text` per section -> energy calm/gentle/lively -> tempo from `derivation.tempo`; episode id -> major key from `derivation.keys`; shot text keywords -> instrument palette; every table is recipe data) < `episode.audio.music.brief` < `--brief` < flags. Style text = the recipe's fixed structural/safety wording + `{bpm} BPM, {key}, {instruments}`; lyrics = the empty section skeleton. One job per candidate x take (`music-cNN-tNN`, seed `base + 100*candidate + take`); candidates differ in instruments, key and tempo. `music-plan.json` + `workflows/<job>.api.json` write-once (file bytes = the first episode's graph format, so the NHAC-2 graph reproduces to file sha `7cbf2a54...`). |
| `music submit [--execute] [--timeout-seconds N]` | GPU | Dry run unless `--execute` (no HTTP). Per job, serially, through `engine.comfy` (no second client): saved graph == plan sha, machine EXECUTOR lock absent, models size+sha256 verified once (`Refused` on any difference), `cmd_submit` (node-class guards, GPU lock, idle queue, intent, POST), `cmd_wait` (history bound to graph + client id), `job.json`. A COMPLETED job is REUSED; post evidence without COMPLETED is resumed (wait / reconcile by GET), NEVER re-POSTed; an intent with no trace is Uncertain (exit 2); a FAILED job stays failed (new folder). |
| `music finalize [--pick TAKE --no-review-gui --vocal-gate-command JSON --ffmpeg P]` | CPU (+ GET `/object_info`) | FLAC -> 48 kHz PCM16 (ffmpeg), then `loopext.extend` (port of the first episode's `loop_extend.py`): bar-aligned loop point by RMS-envelope correlation + zero-phase refine, 0.25 s equal-power crossfade, natural ending kept, to `ceil(film s) + target_extra_s (3)`. Beds under `beds/`, `music-finalize.json` (models path/bytes/sha, licence id + text sha + the sentence relied on, prompt, seam list, `stem` = picked bed, editable GUI + result-pinned review GUI when ComfyUI answers). Reproduces the first episode's NHAC-2 bed to <= 1 LSB (rounding; the original truncates). **Vocal-free gate** (`vocalgate.py`): an external separator (Demucs-style, measured like the audio lane's `vocal_gate.py`: LUFS(vocals) - LUFS(bed) <= -35 AND no 1 s vocal window above -40 dBFS RMS) from `machine.audio.vocal_gate.command` or `--vocal-gate-command` (JSON argv with `{input}` / `{out_dir}`; it must leave `vocals.wav`) runs on every bed; the vocal stem relative to the bed (RMS dB) must be <= `recipe.vocal_gate.limit_db` (-35, a recipe may only tighten); numbers, command, stem sha in the receipt per take; stem = `--pick`, else the first take that PASSes, else the first take (status `VOCAL_GATE_FAIL`, exit 1). No command = `NOT_RUN` (status `VOCAL_GATE_NOT_RUN`): `mix --music-receipt` REFUSES any receipt that is not PASS unless `--allow-ungated-music` (recorded). |
| `sfx cues --episode E --out DIR --review-config F --shot-pack F [--text-field F]... [--include-optional] [--extra-cues F] [--total-frames N] [--with-sfx] [--dry-run]` | CPU | Cue sheet derived from the script, no hand-written prompt: keyword classes over the shot action text (a negation word in the 40 characters before the match rejects the cue: "No pouring" never yields a pour), repeat classes (`repeat_gap_s`), span classes (loop over the shot), plus events from the review config (icon pops, outro cards, `whip` transitions at `start - 1`, anchors such as the logo reveal). Optional classes need `--include-optional`; `--extra-cues` adds hand cues (`{class, frame, reason}`, kept as `MANUAL:` in the receipt); `uncovered_shots` lists shots with no cue (library gaps are reported, never invented). One clip per class in use (stable seed per class, seconds >= 1.0 as ComfyUI requires), `sfx-plan.json`. |
| `sfx submit` / `sfx finalize` `[--with-sfx]` | GPU / CPU | **SFX/ambience are OFF by default on this channel** ("bo am thanh sfx tap am di, chua lai giong noi"): cues (write), `submit --execute` and `finalize` refuse without `--with-sfx` or `episode.audio.sfx.enabled`; `--dry-run` needs none. As music. Finalize: soxr 48 kHz, trim silence (-50 dBFS), peak -3 dBFS, 10 ms/50 ms fades, `clips/<id>-48k.wav`, `sfx-finalize.json` (clips + placements with source sha). |
| `mix --episode E --out DIR --review-config F (--music-receipt F \| --music-wav F [--music-sha256]) [--with-sfx --sfx-receipt F \| --sfx-stem F] [--allow-ungated-music] [--brand-voice F --brand-voice-start-s 0.15 --brand-voice-db 0 --brand-voice-sha256 H] [--extra-wav 'name|path|sha256|frame[|class]']... [--windows F --sections F --total-frames N --recipe ID --allow-outside P] [--dry-run] [--remux PICTURE --remux-out FILM]` | CPU | **The only place a film gets its audio.** Dialogue/vocabulary WAVs from the review config bindings (`engine.qa.bindings`), each hashed against its receipt sha, placed integer-sample-exact at `start_frame*rate/fps` (the `dialogue-stem.wav` is written exact; overlapping audible WAVs, other rate/channels, a WAV past the end: `Refused`); the only gain on speech is ONE recorded scalar per speech CLASS bus (`speech_buses` in the receipt: dialogue, vocabulary, end_line, any `--extra-wav` class; solved in -3...+3 dB or pinned by the recipe; samples and relative timing inside a class stay exact). SFX inputs without `--with-sfx` are `Refused`; off = a silent sfx stem. Duck windows = the span of each WAV where speech is (RMS gate) or `--windows`. **Brand voice layer** (`--brand-voice`, as `editorial/audio-mix-v016/build_mix_v016.py`): the WAV is placed sample-exact at 0.15 s as its own stem (sha recorded separately, `brand-voice-stem.wav`), it plays ALONE, the music bed starts when it ends (0.5 s sin^2 fade-in), `Refused` if it runs into the first speech window - 0.2 s; its section `brand_voice` (0 -> voice end) is measured alone. `--extra-wav` adds one more receipt WAV (e.g. a late end line, class `end_line`) as its own speech class. Music bed (recipe: story -6.0 dB, outro sections -4.5 dB, i.e. 3 dB under the v014 bed): loop -> gain -> duck -> fades (same order as the first episode's builder) -> per-section recipe gain. SFX: placement with gain/pan, physical-action cues moved off speech (`avoid_speech_s`), duck. Sections from the timeline. Writes `dialogue/music/sfx-stem.wav`, `final-mix.wav`, `mix-receipt.json` (inputs, stem shas, duck windows, per-section LUFS/true peak, gains, iterations, pumping, verdict). `--remux`: video stream COPY under the final mix; the video PACKET stream (payload md5 per packet + timing) of the picture and of the film must be identical or the output is deleted and the mux is `Refused`; a failing mix is never muxed; the audio may not outrun the picture; receipt records picture sha, mix sha, stem shas. |

**Film-mix standard** (user rules 2026-10-27 + root decisions; `recipes/audio/mix-cinema-v001.json`; limits in `engine/audio/limits.py` that a recipe may only TIGHTEN, else `Refused`; solver `bedsolve.py`, gate `mixgate.py`). Sections get a role: `brand_voice` (alone), `speech` (a speech window overlaps: dialogue, outro cards, end plate), `bed_only`. Section loudness is always ebur128 INTEGRATED over the whole section, bed included (what the listener hears).
- **Speech sections** and the whole film: -17 +-1 LUFS. Each speech class has ONE bus scalar (`speech_buses`: `solve` within [-3, +3] dB, or `fixed` = pinned by an approved hand mix, [-6, +3]); the solver sets each solve class so the sections it appears in land in the band (`choose_gain`: most sections in band, then smallest miss, then nearest the target). It never lifts the bed. When no bus can do more, a still-loud section gets its bed lowered, only if the bed adds >= 0.3 LU to its speech.
- **Bed**: gain = the RECIPE gain (`music.gain_db` story, `music.section_gains_db` per section name; cinema limits -6.0 / -4.5 or quieter), only ever LOWERED (`bed_gain_max_db` <= 0; gate "above its recipe gain"); a section too short to measure keeps its recipe gain; steps between adjacent sections <= 3 dB (the HIGHER one is lowered, never a raise) over a >= 1 s ramp centred on the seam. Duck -6...-8 dB, attack 0.1-0.2 s, release 0.5-1.0 s, windows closer than 1.5 s merged (hold).
- **Pumping** (duck depth, not music dynamics): for each merged speech window >= 1.0 s, depth = bed RMS in the 0.5 s gaps just outside its ramps minus bed RMS inside the window; the swing of that depth between consecutive windows of the same section must be <= 3 dB (receipt `pumping.depths`).
- **Bed-only sections**: -22 +-3 LUFS and >= 3 LU under their quietest neighbouring speech section; shorter than 3 s (`bed_only.min_s`) unmeasured, not invented. **Brand voice** alone: -16 +-1.5. The 2 LU jump limit applies between adjacent SPEECH sections only.
- true peak <= -1 dBTP; speech WAV samples exact. Out of range -> `verdict: FAIL`, exit 1, stems and receipt still written; the failure names a pinned/limited bus ("dialogue bus pinned at 0.0 dB", "... already at its floor -3.0 dB"). **Channel rules in the recipe:** SFX/ambience OFF unless opted in per episode, vocal-free music gate. `recipes/audio/mix-legacy-v004-parity.json` is a historical-stem reproducer (`UNGATED`); **`recipes/audio/mix-cinema-ep04-final-v001.json`** is the first episode's approved final hand mix as an episode recipe (buses pinned, bed -9.0 / -6.5, never a default: name it with `--recipe`).

**Parity (measured, CPU):** `mix --recipe audio/mix-legacy-v004-parity --total-frames 3314` on the first episode reproduces `milk-mom-music-stem-v004-candidate.wav` byte for byte (sha `23342446...`), the 24 duck windows equal `cue-manifest-v004.json`, an existing SFX stem passes through unchanged; `--remux` on `review-hd-v013`'s mp4 keeps all 3374 video packets (payload and timing sha identical). SFX: derived (class, shot) pairs equal the accepted `sfx-v003` list for 14 of its 16 non-optional cue entries (milking x2, bottle rotate, slosh, token set/place/slide, sleeve x2, hinge, ribbon, book, whoosh, icon sparkles 19/19, card sparkles 12/12, logo chime incl. the end logo); SFX-01 (pour: S01_A says "No pouring") and SFX-20 (footsteps: nobody walks) are rejected; the moo (S02_B) and the leaves (x3) are lane judgement the shot text does not carry, and so are the optional cup clinks (`--extra-cues`). Frames differ from the hand-picked ones by up to 55 frames (default class offset from the shot start vs a cue placed before the first word).
**Parity with the approved final hand mix (ep04, CPU, `--recipe audio/mix-cinema-ep04-final-v001`, review-hd-v015 config, late end line `--extra-wav ...|3322|end_line`, bed `_library/music-beds/NHAC-V2-4-...` (sha fef8bd53...), brand voice `_library/brand-voice/GIONG-C-...` (sha d21eda38..., start 0.15 s), 3444 f):** measured on the engine's final mix at the hand mix's own windows vs `editorial/audio-mix-v016/mix-plan-v016-final-giongC-nhacV2-4.json`: intro 0-3 s -16.8 / -16.8, dialogue 0-72 s -17.2 / -17.2, logo hold -27.2 / -27.4, cards -17.6 / -17.6, plate+end line -17.9 / -17.8, whole -17.4 / -17.4, true peak -1.9 / -1.9 (all within 0.2 LU; the music starts at 1.802 s like the hand mix). The engine's own gate on that mix: **PASS** (brand voice alone -15.9, dialogue -17.2, cards -17.6, end plate -17.9, whole -17.4, bed steps 2.5 dB, bed-only intro/hold under 3 s unmeasured). Same inputs with the solving default recipe are a user decision, not parity.
**Tests:** `tests/test_audio_{recipes,music,sfx,mixgate,trim_steps,optin_vocal,brand_voice,mix_run,cli,parity_ep04}.py` + `audio_fixtures.py` (fake ComfyUI from `fake_comfy.py`, tiny stand-in model files, synthetic stems; ffmpeg-dependent tests skip without ffmpeg; the parity file skips without the first episode's files).

---

## Word timing

Source: `engine/timing/SKILL-SECTION-timing.md`

### Word timing: `jjv timing words`, `jjv qa words` (T-E33) -- section for SKILL.md, root merges it

`engine/timing/{recipe,sound,onset,firstword,q1,gate,recognise,whisper_worker,dialogue,words,wavs,run,cli}.py`, recipe
`recipes/timing/words-onset-v001.json` (every threshold; `document_schema` names the layout the editorial stage reads).  CPU only; no
GPU, no ComfyUI, no network.  Wiring lines: `engine/timing/CLI-PATCH.md`.

Pipeline (`timing words --episode E --dialogue F --out DIR`): (1) recognition: `whisper_worker.py` runs with `python -I` in the
machine's recognition Python (`machine.timing.python` / `--python`) and model (`machine.timing.model_dir` / `--model`); a missing
interpreter, model or package is `Uncertain` (exit 2) with the reason; the script text stays authoritative and a script word that
was not heard makes the line `Uncertain` (no estimated time); the line's last word ends where its speech ends (end of the last RMS
run; the recognised end stays in `raw_whisper_end_s`). (2) onset rule on EVERY word, a port of the verified hand-run v003/v004 tools:
line-first word = first sustained speech run (breath/click burst skipped, unvoiced pre-roll fused with speech -> first voiced
window); every word: start in silence (< floor) -> rising edge of the first sustained voiced run (rule A); start on sound but a
pause (0.05 s within 0.20 s of the start, 0.10 s within 0.40 s) precedes the word's sound -> edge after the pause (rule B,
repeated, shift capped at 0.60 s); never earlier, never later than end - 2 f, ends kept; a stop closure inside a word ('liquid',
about 0.08 s) does NOT move. (3) Q1 gate (below). Outputs, write-once, no timestamp: `WORD-TIMING.json` (same layout as v003/v004),
`WORD-TIMING-QA.json` (every word's audit row, line-first rows, Q1 rows + negative control), `timing-receipt.json` (input/output
shas, recipe sha, source).  `--recognised WORD-TIMING.json` skips step 1 and re-applies the rules (ends kept).

`jjv qa words --episode E --timing F [--out R]` (Q1): per word an independent detector (10 ms windows, silence < -55 dBFS for
>= 0.06 s starting <= 0.40 s after the word start, edge at -45 dBFS) gives the audible onset after a pause; FAIL if any word is lit
> 0 f early or > 2 f late; words with no pause before them are `n/a`.  PASS also needs the built-in NEGATIVE CONTROL: one passing
word shifted 5 f earlier must be flagged (recorded in the receipt); a gate that cannot show that is FAIL; no word after a pause =
`UNTESTABLE` (exit 2).  Every WAV is hash-bound to its declared sha256 (`Refused` on mismatch; outside the episode root needs
`--allow-outside`).

Exit codes: 0 PASS; 1 Q1 FAIL / rule violation (files still written); 2 missing or unreadable input, recognition not configured,
unheard script word, UNTESTABLE.

Parity (measured, `tests/test_timing_parity_ep04.py`): from the recognised word times of the first episode (fixture
`engine/timing/fixtures/parity-words-v003-to-v004.json`, WAVs read in place) the engine reproduces the hand-run v004: 108/108
words, 4 fields each, 0 differences; 25 moved words with the same old/new frames; the per-word audit rows and the 108 Q1 rows
equal the hand-run QA file. Opt-in live check (`JJV_TIMING_PYTHON`, `JJV_TIMING_MODEL`): faster-whisper from scratch on the 12
WAVs gives the same 108 start frames and the same 25 new frames (the hand-run chain differs only in last-word ends by <= 1 f,
S06_B's segment boundary by 7 f).

**Recipes (root decisions 2026-10-27):** `timing/words-onset-v003` is the domain default (`default_for_domain`); `v001` and `v002` stay selectable with
`--recipe` (v002 lost its default flag, nothing else).  Rules A/B and the line-first rule are identical in all three; only Q1 differs.
v002: pause >= 0.10 s (a stop closure is not a pause), onset = first window of a sustained VOICED run (>= 0.03 s above -35 dBFS), late 3-6 f WARN, > 6 f FAIL.
v003 = v002 with onset_voiced_dbfs -42 (the rule lights at the -45 dBFS consonant edge; -35 calls the consonant early) and max_early_frames 1 (33 ms is below what
a viewer sees); early > 1 f FAIL; late 1-2 f PASS, 3-6 f `WARN-late` (listed in `summary.warn_words` and the receipt `warnings`, does not block), > 6 f FAIL.
Negative controls (all must be flagged, else FAIL): a passing word shifted 5 f earlier AND one shifted 2 f earlier (`negative_control.controls`).
Measured on the hand-run v004 reference: v001 FAIL (1 early 'liquid', 5 late); v002 FAIL (5 early at -1 f); v003 PASS (33 tested, 30 pass, 0 early, 0 late,
3 WARN: `S01_B:and` +3, `S06_B:and` +3 and +4).  Pinned in `tests/test_timing_{v002,v003}.py` / `test_timing_parity_ep04.py`.

Tests: `tests/test_timing_{rules,q1,recognise,run,cli,parity_ep04,v002,v003,modules}.py` (synthetic-WAV cases: silence start, pause inside the first
0.4 s, the 'liquid' closure, caps, shift limit, burst before speech, unvoiced pre-roll; Q1 per-word limits, negative control, UNTESTABLE;
worker with a fake model; refusals; CLI handlers; the parity gate proven red by tampering a threshold; size/neutrality/no-network).

---

## Transition presets

Source: `SKILL-SECTION-T-E42-engine.md`

## Transition presets + ending as parameters (T-E42, engine side)

(Replacement/addition text for `studio-video-engine/SKILL.md`; the root merges it. The remotion-kit side is written by the kit owners.)

**Rule (user, 2026-10-27):** a transition is a *preset chosen by name per boundary*. Changing an effect = edit one field in
`boundaries.json`, then `jjv editorial build-config` and the remotion-kit render. No code edit. Effects are a **compositing layer
applied after the shot videos exist**: choosing or changing one never re-renders shot video (no H3, no SeedVR2, no GPU).
Shots are re-rendered only when the picture itself is broken or characters/props are laid out wrong.

### Where things live

| What | File |
|---|---|
| The catalog (ONE source of truth, ~33 presets / 30 ready, categories, EN+VI labels, params with bounds) | `schemas/transition-presets.json` (generated by the T-E42 generator, do not hand-edit) |
| Loader + validators (frames / direction / params / tail / window / placement) | `engine/editorial/presets.py` |
| Row rules, tail rule, `feasibility`, record builder | `engine/editorial/transitions.py` |
| Frame filling, row checks, feasibility table | `engine/editorial/boundaries.py` |
| Derived timeline | `engine/editorial/derive.py`, `end_card.py` (ending params), `timeline.py` (`totals=`) |
| Read-only presets CLI | `engine/editorial/presets_cli.py` |
| Schema (type enum = ready presets, regenerated from the catalog; a test asserts equality) | `schemas/boundaries.schema.json` |

### The boundary row

```json
{"from_shot": "S03_B", "to_shot": "S04_A", "class": "cut", "type": "crossfade", "continuity": "agree",
 "framing": "new_framing", "frames": 8, "direction": 0, "params": {"curve": "out"},
 "motivation": "…", "tail_clip": "clips/motion-v005/S03_B-native.mp4"}
```

* `type` = a ready preset name. `frame` (optional) = where `to_shot` starts; omitted it is read from the timeline, written it must equal it.
* `frames` optional: omitted = the preset default; written = must satisfy the preset rule (`fixed`, or `min..max`, `even`).
* `direction` optional (0): required to be -1/+1 only where the preset says `required` (whip, pan_motivated, push_slide, wipe_linear, wipe, cloud, card_slide).
* `params` optional: defaults are filled and recorded; an unknown, mistyped or out-of-range param is refused naming the preset and the key. `iris.disc_fade_frames` is required.
* `framing`: `same_framing` | `new_framing` (optional). `same_framing` + any *visible* preset between two pictures (everything except `cut`, `cut_push`, `none`) is a **build warning**, not a refusal: "same seat/angle: use cut_push, flash or camera move only when angle/scene changes".
* `class: cut` + `type: cut` is a designed hard cut (frames 0). `class: cut` + `none` is refused. `class: carry` must be `none` (a carry may use nothing else).
* A **planned** preset (`glitch`, `ripple`, `grid_dissolve`) is refused with "preset 'x' is planned, not implemented".

Rules that hold for every preset (all `Refused`): written motivation; `shows_both` presets are refused when a picture shot is on either side unless continuity is `agree`
(no two Alices); presets with `safe_for` graphic only (`card_slide`, `plate_in`) are refused between two picture shots, picture-only presets between two graphics (a `cut`/`none` is
always fine); preset tail rule below.

### Legacy alias

`type: dip_white, frames: 9` (the production ep04 table) resolves to preset **`dip_white_legacy`** (the first build's 9-row schedule, peak at B+3) and the build returns a
warning: *"legacy 9-frame dip_white … write type dip_white_legacy to keep it explicitly; drop frames (or write dip_white) for the approved 8-row schedule"*. The record keeps
`type: "dip_white"` (`preset: "dip_white_legacy"`), so v008 parity is unchanged. `dip_white` with 8 frames or no `frames` is the approved 8-row schedule (peak at B+1, ONE tail frame).
Any other frame count on `dip_white` is refused ("the dip_white schedule is 8 frames … legacy dip_white_legacy schedule is 9 frames").

### No silent GPU

Presets with a tail (`tail_frames` = `all` | `half` | `schedule`) run on the outgoing clip's native TAIL frames: they need `ceil(0.8 x N)` native frames beyond what the editorial
cut uses, and the last native index used `ceil((delivery_frames + N - 1) x native_fps / delivery_fps)` must exist. If the handle is missing or short the build is **Refused**,
naming the boundary and the missing frames, ending: *"no GPU work is requested; choose a preset without a tail or restore the tail separately"*. The build never asks for new shot video.

`transitions.feasibility(row, outgoing, clip, probe, delivery_fps, native_fps)` returns, for EVERY ready preset, `{available, frames, needs_tail_frames, have_native_frames, max_frames, reason}`
with the same rule (`max_frames` = largest legal frame count that fits). `have_native_frames` is the native tail available beyond the editorial cut (null without a handle).
Boundaries without `tail_clip` offer only the `tail_frames: none` presets (`none`, `cut`, `cut_push`, `whip`, `pan_motivated`, `iris`, `bloom`, `card_slide`, `plate_in`);
`card_flip_3d` needs half its frames as tail and the dip family needs its `out_tail` rows (1 frame, 3 for the legacy schedule).

Real ep04 handles (measured): T1010 has 7 native tail frames -> `tail_frames: all` presets up to 8 frames; T1310 13 -> up to 16; T1610 15 -> up to 18.

### CLI

`python -I .agents/skills/studio-video-engine/engine/editorial/presets_cli.py` prints the catalog. With `--episode E --boundaries B [--boundary 1010|T1010] [--allow-outside LOGO]` it prints per boundary
the tail handle and, for every ready preset, `available` (tail) and `eligible` (+ `eligible_reason`: class, continuity, boundary kind). Read-only; `--word-timing` optional.
*(`bin/jjv.py` is owned by another task, so the verb is a module for now. To expose it as `jjv editorial presets`: in `engine/editorial/cli.py::register_cli` call
`presets_cli.register(verbs)` and in `bin/jjv.py::_dispatch` add `if args.stage == "editorial" and args.verb == "presets": return presets_cli.run_presets(args)`.)*

### Record shape (events.json `transitions[]` and config `motion.transitions[]`)

Common: `id, boundary, from, to, class, type, preset, renders_as, frames, direction, continuity, shows_both, motivation, params, placement, start, end_exclusive`, plus `framing` / `g_bridge`
when declared, `outgoing_tail` when the preset needs a tail (`tail_output_frames` = the preset's tail count).

* **dip family** (`dip_white`, `dip_white_legacy`, `dip_black`, `light_leak`, `film_burn`; `renders_as: "dip_white"`): adds `schedule[]` (`{t, shot: out|out_tail|none|in, white}`), `overlay`
  (`{kind: colour, colour}` | `{kind: leak}` | `{kind: burn}`), `incoming_hidden_frames`, and `white_colour` for colour overlays (`#FFF8EC` dip_white, `#000000` dip_black). Window = `B + min(t) .. B + max(t) + 1`.
* **push / overlay family** (`push_slide`, `zoom_*`, `iris_circle/diamond`, `clock_wipe`, `wipe_linear`, `blinds`, `crossfade`, `blur_crossfade`, `focus_pull`, `cloud`, `bubble`): `params` resolved, window `B .. B + frames`, `outgoing_tail.tail_output_frames = frames`.
* **cut_push**: `frames` (default 12), `params {scale_from, ease}`, window `B .. B + frames`, no tail. **cut**: `frames 0`, `params {}`, window `B .. B`.
* `whip` family keeps `out_frames`/`in_frames`; `iris` keeps its layout numbers (`iris_close_f`, `logo_in_f`, …) at top level as before.

### Ending as parameters (`boundaries.json` `ending`, all optional)

* `derive_timeline: true` -> `cards[]` may omit `start_frame`/`duration_frames`; boundary rows into cards/`END_PLATE`/`ENDLOGO` may omit `frame`; `ending.end_plate.start` may be omitted.
  The derived timeline is, in order (all recorded in `ending.derived_timeline`):
  1. **`logo_hold_frames`** (>= 60, default 60) = the STILL LOGO between the dialogue end and card 1. Card 1 starts at `dialogue_end + logo_hold_frames` (ep04: 2160 + 70 = f2230, the hand-built v013).
     The `OUTRO` boundary row (last shot -> `OUTRO`) stays on the dialogue end; cards follow back to back.
  2. Card length = `max(card_min_frames, ceil(wav_seconds x fps))` (integer arithmetic), `card_min_frames` >= 90 (default 90 = 3 s).
  3. **End plate**: `end_plate.placement` = `card_end` (default when derived) -> the plate starts on the first frame after the last card window (never before the measured speech end) and the main film ends
     `end_plate.frames_after_card_window` (>= 1, default 4) frames later; `speech_end` -> the earlier rule: plate start = `ceil(last card start + measured speech end)` inside the last card window, main film ends with the cards.
     A declared `end_plate.start` must equal the placement rule (`placement` also exists without `derive_timeline`; its default there is `speech_end`).
  4. **`end_card_frames`** (>= 60, default = the episode timeline's `end_card_frames`) = the end card (EndLogo) after the main film. `total = main_frames + end_card_frames`.
  5. **Logo disc and iris follow the outro start** (`outro = dialogue_end + logo_hold_frames`): `ending.logo_disc.fade_start = outro`; `ending.logo_disc_layout.slide_start = outro - 8`, `slide_end = outro - 1`
     (a written layout wins when `slide_start <= slide_end < outro`); the iris row gets `params.hold_frames = logo_hold_frames`, `params.disc_fade_start_f = outro` and, when missing, `iris_close_f` / `logo_in_f` from `ending.iris.closed` / `ending.logo_disc.in`.
     The iris window is `[B - frames, B + hold_frames + disc_fade_frames)`: ep04 hold 70 gives f2116 .. f2236 (iris, logo still f2156-2221, step aside f2222-2229, shrink f2230-2235). `hold_frames` is an optional iris param, absent = the old window.
  6. A written value that contradicts a derived one (`start_frame`, `duration_frames`, `logo_disc.fade_start`, `params.disc_fade_start_f`, `params.hold_frames`) is **refused** naming the derived number: leave it out.
  Switching `derive_timeline` on for an ending that was written for the old timeline therefore needs `logo_disc.fade_start`, `params.disc_fade_start_f` and the old `slide_start`/`slide_end` removed.
* **Caveat:** the derived timeline is an EDITORIAL property only. `engine/config`, `domains/` and the episode contract are NOT touched: a derived main film longer than the master, an end card above
  `end_card.frames_max`, or a total above the episode total each produce a build **warning** ("derived main film N frames exceeds …"). The master render needs the contract extended first.
  Without `derive_timeline` behaviour is byte-identical to before (ep04 parity unchanged).
* `music_bed` (validated, passed through to `events.ending` and `config.motion.ending`): `extend` (`loop_phrase_crossfade` | `none`), `loop_start_s`/`loop_end_s` (required for the loop; end > start), `crossfade_frames`,
  `duck_db` (> 0), `duck_attack_frames`, `duck_release_frames`, `duck_under` (`words`). `logo_disc_layout` (object of numbers: `slide_start`, `slide_end`, `slide_x`, `pill_left_x`, `disc_in`, …): passed through as data (`slide_start`/`slide_end` are derived when `derive_timeline` leaves them out).
  The engine validates and carries these; the kit consumes them.

### Switching an effect (the whole job)

1. Open `boundaries.json`, change the boundary's `type` (and `frames`/`params`/`direction` only if you want non-default).
2. `python -I .agents/skills/studio-video-engine/engine/editorial/presets_cli.py --episode <E> --boundaries <B> --boundary <frame>` shows what the handle allows (optional).
3. `jjv editorial build-config …` (refuses with the reason if a rule or the tail does not fit), then the remotion-kit render. Never a shot re-render.

---

## jjv qa review: usage

Source: `engine/qa/CLI-PATCH-review.md`, section Usage. The wiring steps in that file are already applied: `python -I bin/jjv.py qa review --help` prints the verb (checked 2026-10-27). The "Text for SKILL.md" part is in `SKILL.md`, not here.

## Usage

```
python -I bin/jjv.py qa review --config <review-config.json> --video <review.mp4> [--mix <mix.wav>] [--events events.json]
    [--gates Q2,Q3,Q4,Q5] [--sheets-dir DIR] [--out report.json] [--expect-frames N] [--root DIR] [--recipe F]
    [--layout-same-framing F,F,...] [--frame-origin N --audio-origin-s S]  (clips) [--ffmpeg P] [--json]
```
Until the patch is applied the same handler runs standalone: `python -I engine/qa/review_cli.py <same flags>`.
One JSON report on stdout (`jjv/qa-review-report/v1`), summary on stderr, exit 0 PASS / 1 a gate FAIL (or a rule
violation: bad config, loosened threshold, unknown gate) / 2 UNCERTAIN (a gate could not decide, or an input is missing).
FAIL beats UNCERTAIN. Relative paths in the config resolve against `--root` (default: the config's folder).

