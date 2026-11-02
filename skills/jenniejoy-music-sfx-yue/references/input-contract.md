# Input contract — what `jjv audio music|sfx` reads from an episode folder

All paths relative to `production-local/JennieJoyKids-Story/<EPISODE>/`. Nothing else is read; nothing here is written.

| File | Fields used | Used for |
|---|---|---|
| `script/shot-prompt-pack-v00N.json` (latest N) | `shots[].shot_id`, `scene_id`, `scene_title_vi`, `speaker`, `speech_text`, `dialogue_vi`, `target_keywords`, `visual_description`, `timing_contract.editorial_timeline_30fps`; `transitions[].type/is_continuous/justification` | Step 1 mood/setting/energy; Step 2 on-screen actions (one cue per sounding action), rejection of off-screen sounds |
| `editorial/review-hd-v0NN/config/review-config-v0NN.json` (the current cut; ep04 = v013) | `fps`, `main_frames`, `total_frames_with_endlogo`, `outro_start_frame`, `dialogue[].{id,start_frame,end_frame_exclusive,audio.path,audio.sha256,offset_frames,words[].startF/endF}`, `outro_cards[].{term,start_frame,duration_frames,audio.path,audio.sha256}`, `motion.transitions[].{id,boundary,type,start,end_exclusive}`, `motion.icons[].{id,shot,word,frame}`, `motion.ending.{iris,logo_disc,end_logo,end_plate}` | Length target; cue frames; dialogue stem for previews; duck windows |
| `engine/shots.json` | `shots[].wav_binding.path/sha256` | Cross-check that the dialogue WAVs in the review config are the receipt WAVs |
| `audio/mix-plan-v00M/cue-manifest-v00M.json` (previous lane, optional) | `sfx_plan.included_cues[].{cue_id,kind,start_s,gain_db}`, `dialogue_ducking_plan.{speech_duck_db,attack_s,release_s}` | Reuse timings of physical actions already placed; duck contract for previews |
| `editorial/review-hd-v0NN/BRIEF.md` (optional) | free text | Only to learn about pending timeline changes (e.g. outro lengthening) |

Derived values the skill must write into its own README/manifest (so the next run is reproducible):

- `timeline_s = total_frames_with_endlogo / fps`; `bed_min_s = ceil(timeline_s) + 3`.
- `speech_windows[] = {id, start_s, end_s}` for every dialogue line and vocabulary card (from `start_frame` + WAV duration).
- `events = {whip_pans[], icon_pops[], card_starts[], logo_in, end_logo_from, iris}` from `motion.*`.
- `actions[] = {shot, frame_hint, action_text, cue_class}` extracted from `visual_description` (agent judgement; store the sentence).

Not an input: a hand-written brief, the ep03 assets, NEWTECONS anything, `FROZEN-EP04.json`, `technical/**`.
