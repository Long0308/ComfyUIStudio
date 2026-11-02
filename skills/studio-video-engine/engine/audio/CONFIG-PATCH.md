# CONFIG-PATCH: audio stage (T-E43), for root to apply after the tails run

Machine, domain and episode schemas are frozen until the ep04 tails plan has executed (any edit changes `machine_sha256`/`domain_sha256`).
Until then the audio stage reads every key below through `engine/audio/recipe.py::optional_block`: absent key = default, nothing re-hashed,
`config validate` stays `c629dce3...`.  Today's fallbacks are in the right-hand column.

| File | Key | Meaning | Fallback today |
|---|---|---|---|
| `schemas/episode.schema.json` | `audio` (optional object, closed): `music {recipe, brief{bpm, key, instruments}}`, `sfx {recipe}`, `mix {recipe}` | per-episode recipe choice and a brief override | `--recipe`, `--brief`, `--bpm --key --instruments`; else the single recipe of the family for the domain (`mix`: the single `cinema` one) |
| `schemas/domain.schema.json` | `audio` (optional object): `allowed_recipes[]` (`^audio/`) | recipes a domain may use | none: every recipe whose `domain` equals the episode domain |
| `domains/jenniejoy_cartoon_3d.json` | `"audio": {"allowed_recipes": ["audio/music-yue2-int8-v001", "audio/sfx-stable-audio-3-small-v001", "audio/mix-cinema-v001"]}` | the legacy parity recipe stays OFF the list on purpose | as above |
| `domains/newtecons_live_action.json` | `"audio": {"allowed_recipes": []}` | no recipe qualified for live action yet (the engine already refuses: no `audio-*` recipe has that domain) | refused |
| `schemas/recipes/audio-*.schema.json` | `MUSIC_SCHEMA`, `SFX_SCHEMA`, `MIX_SCHEMA` of `engine/audio/recipe_schema.py` | move there when per-family recipe schemas land | the dicts in `recipe_schema.py` |
| `episode.json` | `files.review_config`, `files.shot_pack` (relative to `<episode>/engine/`) | the script-driven inputs | `--review-config`, `--shot-pack` flags (required for `sfx cues`/`mix`) |
| `schemas/machine.schema.json` + `machine.json` | `audio` (optional object): `vocal_gate {command: [argv with {input} and {out_dir}]}` | the external source separator (Demucs-style, must leave `vocals.wav`) of the music vocal-free gate; the limit (-35 dB) lives in the music recipe | `--vocal-gate-command` (JSON argv); without either the gate is `NOT_RUN` and `mix --music-receipt` refuses the bed |
| `schemas/episode.schema.json` | `audio.sfx.enabled` (boolean) | per-episode SFX/ambience opt-in (OFF by default on this channel) | `--with-sfx` on `sfx cues|submit|finalize` and `mix` |
| `machine.json` | no other key | ComfyUI url/root/output_dir/container and `gpu_lock_path` are reused as they are | `settings_from_machine` |

Notes
* `--total-frames` exists because the hand-built ep04 v013 config names two lengths (`total_frames` 3314 = main film, `total_frames_with_endlogo` 3374 = picture file); the default is the larger one (the picture), the parity run passes 3314.
* Plans/receipts bind `config_sha256` (like the voice stage); `submit`/`finalize` refuse a plan whose resolved config changed, so write `shots.json`/`mouth-boxes.json` BEFORE `music plan`/`sfx cues`, or switch the check to `config_core_sha256` when it exists.
* Licence: the music recipe records the YuE2 creator-permission sentence and the sha of the saved licence text; whether the channel is an "individual creator" is the user's call, the engine only records it.
