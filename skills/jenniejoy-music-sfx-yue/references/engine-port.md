# Engine wiring — `jjv audio music | sfx | mix` (T-E43, `engine/audio/**`, owned by another builder)

Do not edit engine code from this skill. The engine must call the same graph builders and the same guarded dispatch, and read the
same input contract, so that an ep05 run needs no hand-written prompt.

## Functions to port (source: `04-milk-and-mom/audio/music-yue2-v001/tools/`, `04-milk-and-mom/audio/sfx-v003/tools/`)

| Function / script | Port as | Notes |
|---|---|---|
| `comfy_audio_graphs.yue2_music_graph(ckpt, style, lyrics, seed, max_duration, filename_prefix, abc_planning, mode, steps, sampler, scheduler, tiled_decode, tile_size, overlap)` | `engine/audio/graphs.py` | Official template chain; keep node ids 1-8 (templates in `engine/staging/T-E43-audio/recipes/audio/*.json` use them as slot paths) |
| `comfy_audio_graphs.sa3_sfx_graph(ckpt, clip_name, prompt, negative, seed, seconds, filename_prefix, steps, cfg, sampler, scheduler)` | same | `seconds >= 1.0` guard before submit |
| `comfy_audio_graphs.api_to_gui(api, title, extra, columns, colors)` | `engine/comfy/gui.py` | Generic API->GUI via `/object_info` (widgets vs links, seed `fixed`, LoadAudio/SaveAudio extra widgets) |
| `comfy_audio_graphs.attach_audio_result(gui, input_name, status, prompt_id, audio_sha256, lufs)` | same | Pin a **WAV** copied into `ComfyUI/input`; verify the name is in `/object_info/LoadAudio` options |
| `run_comfy_audio_job.py` (check -> submit -> wait + nvidia-smi monitor + docker log excerpt) | `engine/audio/dispatch.py` | Thin wrapper over `comfy_guarded_submit.py`; never POST directly |
| `build_candidates.py` (CANDIDATES x TAKE variants) | `jjv audio music --episode <EP>` | Inputs from the input contract; three candidates, >= 3 takes each, longest natural take wins |
| `loop_extend.py` (`best_loop`, `refine_zero_phase`, crossfade) | `engine/audio/loop_extend.py` | bpm from the style text; write `.loop.json`; raise when no loop point after the intro |
| `finish_candidate.py` (bed WAV, ebur128, dialogue stem + duck envelope preview, review GUI, hard-links, MUSIC-STATUS) | `engine/audio/finish.py` | Dialogue stem from the review config; duck -14 dB / 0.14 s / 0.28 s |
| `sfx_cue_spec.py` (Cue/Placement dataclasses) + `build_sfx_graphs.py` | `jjv audio sfx --episode <EP>` | The cue list itself is derived per episode (rules table); dataclasses and frame rules are reusable |
| `finish_sfx.py` (soxr 48 k, ebur128, review GUI, cue-sheet JSON, hard-links) | `engine/audio/finish_sfx.py` | `-r2` receipt-dir fallback when a first run was rejected |
| `publish_and_manifest.py` (both lanes) | `jjv audio publish` | Byte-identical copies into `06_AUDIO_MUSIC/`, `07_AUDIO_SFX/`; refuse to overwrite different content; `CHON-AM-THANH.txt` |

## Templates with slots (already in `engine/staging/T-E43-audio/recipes/audio/`)

- `music-yue2-3b-int8-v001.json` — slots `<STYLE> <LYRICS> <SEED> <MAX_DURATION> <OUTPUT_PREFIX>` at the listed node paths.
- `sfx-stable-audio-3-small-v001.json` — slots `<PROMPT> <NEGATIVE> <SECONDS> <SEED> <OUTPUT_PREFIX>`.
- `music-yue2-example-ep04-nhac2.json`, `sfx-stable-audio-example-ep04.json` — worked examples (not defaults).

## Hand-off contracts

`jjv audio music` -> user pick -> `jjv audio mix`: `{bed_wav, bed_wav_sha256, bed_duration_s, timeline_s, loop_extension{loop_point_s, crossfade_s}, bed_loudness{integrated_lufs,true_peak_dbfs}}`; mix must assert `bed_duration_s >= timeline_s + 3`.

`jjv audio sfx` -> `jjv audio mix`: cue rows `{cue_id, file, file_sha256, action_on_screen, shot, frame, time_s, duration_s, gain_db, pan, optional, note}` + `clips[]` `{prompt, negative, seed, prompt_id, native_sample_rate, wav_48k_sha256}`; mix trims sub-second cues, applies the film standard and the user's optional-cue decisions, then registers chosen files with the Studio (`/api/editorial-audio/register`, layer music/sfx — a Studio change, not done yet).

GPU rule unchanged: TTS, H3, SeedVR2, music and SFX share one RTX 5080 — serial under `technical/.comfyui-image-submit.lock`.
