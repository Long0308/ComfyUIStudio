> MERGED into SKILL.md 2026-10-28
### Voice stage: `jjv voice` (T-E40v, S4)

`jjv voice plan|synth|reconcile|adopt|approve|finalize --episode E --out DIR ...`.  Port of the first
episode's `build_milk_mom_voice_batch.py` + `build_dialogue_trim.py` + the S06_B split script
into `engine/voice/{recipe,plan,client,synth,reconcile,wavio,trim,split,finalize,receipts,cli}.py`.
No URL, profile id, pitch, language or sample offset is engine source: the recipe
(`recipes/voice/<id>.json`: engine, language, effect preset, wav bits, editorial format,
rubberband options, trim parameters), the cast document (profile ids, per-speaker pitch) and
the dialogue document (text, target durations, split plans) carry them.

| Verb | CPU/GPU | What it does |
|---|---|---|
| `plan --dialogue F --cast F [--recipe ID] [--dry-run]` | CPU | `jjv/dialogue/v1` + `jjv/cast/v1` + recipe -> `voice-plan.json` (write-once, deterministic). Each job: `request{text, profile_id, language, engine, duration, effect_preset, wav_bits}` and `request_sha256` (canonical ascii; equals the first batch's `stable_sha256`: 24/24 parity). Refusals: `E_SPEAKER_PREFIX` (a `Name:` prefix or `[]<>{}` markup in `text_tts`), `E_APPROVED_CAST` (silent character with a line, speaker not in the cast), no voice binding, duplicate ids, episode id mismatch, bad split plan, recipe of another domain, ambiguous recipe. |
| `plan --script F [--extras F] [--vocabulary-speaker S] --cast F` | CPU | The same plan, started from the LOCKED film script (`engine/voice/script_ingest.py`): one job per spoken shot (EN `speech_text` + `speaker` + `duration_s`; the VI `dialogue_vi`, frames, keywords as `meta`), one per vocabulary card, one per `voice_extras`/`--extras` row (end line, brand voice). Speaker -> profile id comes ONLY from the approved cast document. `LOCKED*` script status = LOCKED, anything else DRAFT (`synth --execute` then refuses). A `language` on the script/line must agree with the recipe language (`E_LANGUAGE`); a line `effect_preset` must be the recipe's or in its `allowed_effect_presets` (`E_EFFECT_PRESET`); `emotion` is recorded in `meta` only (VoiceStudio has no emotion field). ep04: the 24 request shas equal the manifest; the 25th job is `end_line:mother` = `2cae6756...`. |
| `synth [--execute] [--voicestudio-url U] [--category C]` | GPU | Dry run by default (no HTTP at all). With `--execute`, per job: state from receipts -> `machine.gpu_lock_path` (`E_GPU_LOCK`, existing sentinel preserved) -> ComfyUI `/queue` idle (`E_QUEUE_BUSY`) -> VoiceStudio `/history` snapshot (`E_VOICESTUDIO_UNHEALTHY`, still Refused: nothing sent) -> write-once `jobs/<id>/intent.json` -> POST `/generate` -> native WAV write-once under `native/` -> `take.json`. Any error after the intent: `unknown.json`, Uncertain exit 2, never re-posted; the next `synth` refuses that job until `reconcile`. 4xx: `rejected.json`, Failed exit 4 (never 1 after a POST). A take whose native WAV still hashes is REUSED. Needs `dialogue.status == LOCKED`. |
| `reconcile [--voicestudio-url U]` | HTTP read | For intent-without-take jobs: `/history` entries new since the intent snapshot with the same text/profile/language. Exactly one -> download, `take.json` (`provenance: reconciled`); none or several -> Uncertain. Never POSTs. |
| `adopt --takes F.json` | CPU | Binds existing native WAVs (`[{request_id, path, audio_id}]`) as takes without HTTP (hashed in place, not copied). Used for the first episode's `audio/voicestudio-batch-v001` natives. |
| `approve --job ID --by NAME --note TEXT [--sha256 H]` or `approve --list` | CPU | Listen approval: write-once `jobs/<id>/approval.json` bound to the native take's sha256 (`E_APPROVAL_BY` for an empty/machine name, `E_APPROVAL_NOTE`, a wrong `--sha256` is refused, a repeat is `ALREADY_APPROVED`). When the domain has `voice.require_listen_approval` (JennieJoyKids and NEWTECONS: true) `finalize` refuses every job without a valid record (`E_LISTEN_APPROVAL`) BEFORE writing any WAV; a record bound to another WAV does not count. H3 prepare calls `approval.require_wav_approved(out, plan, wav_sha256, episode_root)`: any derived WAV (base, editorial, receipt, split segment, split full) resolves back to its approved take. |
| `finalize [--category dialogue\|vocabulary\|end_line\|brand_voice\|all] [--ffmpeg P] [--dry-run]` | CPU | The ONLY trimmer (static test: only `finalize.py` imports `voice/trim.py`). Per take: ffmpeg `anull` to the recipe editorial format (real resample, 48 kHz stereo PCM16) -> speaker transform from the cast (`pitch_semitones != 0` -> `rubberband` formants preserved, `apad,atrim` to the identical sample count, else the base IS the editorial WAV) -> clipped-sample gate -> one trim -> optional sample-exact split -> `voice-finalize.json` (write-once) binding native/base/editorial/receipt/segment shas. Receipt WAVs are used at offset 0. A second finalize over the same `--out` with other trim parameters or recipe, or any differing WAV, is `E_TRIM_ONCE`. |

**Extra line kinds**: dialogue-document `extras[]` rows `{kind: end_line|brand_voice, id, speaker, text_tts, target_duration_s}` are jobs `end_line:<id>` / `brand_voice:<id>` (same lint, cast gates, receipt, approval, single trim). **Voice -> mix hand-off**: every finalize entry carries `class` (dialogue / vocabulary / end_line / brand_voice) and a `mix` block (sha-bound WAV row + usage): dialogue and vocabulary -> review-config `wav_bindings` named `dlg <id>` / `voc <term>` (the mix reads the bus from the name), end line -> `--extra-wav 'name|path|sha|{start_frame}|end_line'`, brand voice -> `--brand-voice F --brand-voice-sha256 H`; a split line enters as ONE `split.full` WAV (the segments are `h3_segments`). The receipt has `mix_handoff.classes`.

**`voice-bindings.json`** (written by `finalize`, write-once, `engine/voice/voice_bindings.py`): subtitle line id -> final receipt WAV in the shape the next stages read: `dialogue[]` `{id, speech_text, dialogue_vi, subtitle, start_frame, duration_frames, end_frame_exclusive, speaker, en_markup?, target_keywords?, audio{path,sha256,offset_frames,duration_seconds}}` + `vocabulary[] {term, icon, anchor}` for `jjv timing words --dialogue`; `wav_bindings[]` + `outro_cards[]` for `jjv audio mix` / `jjv qa`; `extras[]` for the late classes. Frames come from the script when it has them, else `null` placeholders with `timeline_bound: false` and `pending_start_frames` (the readers Refuse a null by name). Measured on ep04 (adopt mode): the 6 Alice lines, the S06_B full 12.5 s WAV and all 12 vocabulary cards are sha-equal to review config v015; the 6 Mother lines carry the pinned engine shas (onset rule).

**Quiet-burst onset (optional recipe key `trim.onset.quiet_burst_db`)**: a short leading run INSIDE a cluster whose peak is >= N dB below the loudest run is a breath, not speech. Needed for the ep04 end line (0.11-0.17 s burst at -36 dBFS, 0.11 s before the words, under `isolated_gap_s`). Off when absent (receipts and parity unchanged); see CONFIG-PATCH 3b.

**Live smoke 2026-10-27** (real VoiceStudio :8080): the first `synth --execute` against the real service worked. Real `/history` rows carry `created_at` (float unix), not the keys the engine looked for: `reconcile.CREATED_KEYS` now includes it. The smoke audio was NOT approved by anyone; its finalize receipts were produced with the requirement relaxed in a harness (see the builder report), never through the CLI.

**Trim** (`engine/voice/trim.py`, parameters from the recipe `trim` block: -40 dBFS RMS over 10 ms
windows of interleaved samples, pre-roll 0.08 s, post-roll 0.10 s, same rounding as
`dialogue-trim-v002`). Onset rule from the word-timing-v003 lesson: speech runs separated by
<= `merge_gap_s` (0.03) are merged; a run >= `min_run_s` (0.15) is speech; a shorter run followed
by a gap >= `isolated_gap_s` (0.5) is a burst and is skipped; a shorter run inside a cluster
counts. The receipt records `onset.naive_first_speech_sample`, the chosen sample, the skipped
bursts and `differs_from_naive`. The offset (end) keeps the last speech window.

**Split** (`engine/voice/split.py`): data on the dialogue row,
`split: {pad_tail_silence, segments: [{label, samples, speech_conditioning}]}`. Segments are
consecutive slices of the EDITORIAL WAV from the trim `start_sample` (so a segment may run
past the trim end into real room tone, as the first episode's S06_B did); only the tail may be
zero-padded and only when `pad_tail_silence`; a segment declared `speech_conditioning: false`
must contain no speech window; the receipt carries a concatenation proof (declared total,
real/padded samples, byte identity of the real part with the source) and marks silent
segments `receipt_wav: false`.

**Parity with the first episode** (measured, CPU only, ffmpeg 9.0 gyan build): `plan` 24/24
`request_sha256`; `finalize` on the 12 native WAVs: the 6 Alice receipt WAVs and the 3 S06_B
segments (240000/280000/80000, proof 600000) are sha-equal to `dialogue-trim-v002`; the 6
Mother WAVs differ ONLY by the onset rule (each starts with a 0.09–0.14 s burst at ~0.10 s
followed by 0.57–0.95 s of silence; with the burst filter off all 12 are sha-equal). The
engine cut starts 0.68–1.08 s later than v002, which is where word-timing-v003 independently
measured the first word (S01_A +23 f, S02_A +33, S03_A +33, S04_A +21, S05_A +24, S06_A +31).
The existing episode keeps its receipt WAVs (receipt-WAV rule); the rule applies to new work.

**Config** (frozen until the tails run): see `engine/voice/CONFIG-PATCH.md` for
`machine.voicestudio.url`, `domain.voice`, `episode.files.{dialogue,cast}`, `episode.voice.recipe`
and the `config_core_sha256` switch. Until then: `--voicestudio-url`, `--dialogue`, `--cast`,
`--recipe`; the resolved `config_sha256` is unchanged.

**Tests**: `tests/fake_voicestudio.py` (modes normal, wav, drop, status:N, truncated, no_id,
duplicate), `tests/wav_fixtures.py`, `tests/test_voice_{plan,synth,trim,finalize}.py`
(finalize tests skip without ffmpeg; the rubberband assertions skip without the filter).
