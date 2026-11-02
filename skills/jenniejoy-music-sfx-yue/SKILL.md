---
name: jenniejoy-music-sfx-yue
description: "Script-driven background music (YuE2, local ComfyUI) and SFX cue sheet + clips (Stable Audio 3 small-SFX) for a JennieJoyKids 3D cartoon episode, from script + shot pack + timeline to user-pick files and the hand-off to `jjv audio mix`. Use when an episode needs a new music bed or foley; NEWTECONS live-action is a separate domain."
---

**Written 2026-10-27 from the ep04 "Milk and Mom" run (task T-A10).** Domain: `jenniejoy_cartoon_3d` only.
Engine: local ComfyUI 0.41 in Docker `Comfyui-Studio` (RTX 5080 16 GB, `--disable-partner-nodes`), no cloud node ever.
The engine command `jjv audio music|sfx|mix` (T-E43, `engine/audio/**`, another builder) must run these same steps; see
[engine port](references/engine-port.md). Film-mix standard lives in [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md), not here.

## Library first (user rule 2026-10-27: "nên có kho nhạc nền")

Before generating anything, look in the shared libraries and reuse:
- Music beds: `production-local/JennieJoyKids-Story/_library/music-beds/REGISTRY.json` — every bed there already passed the vocal-free gate; each row has sha, length, loudness, generator and `used_in` (ep04 used NHAC-V2-4). Pick a bed not used by the previous episode; generate new beds (Steps 1–5) only when the library has no fit, then add them to the registry.
- Brand voice: `production-local/JennieJoyKids-Story/_library/brand-voice/` — GIONG-C "Jennie Joy Kids!" (user pick). It plays alone at the start of the brand intro, then the music.
- When a film uses a bed, append the film to its `used_in` (film, mix plan path, gains).

## Contract

- **Input trigger:** locked script, shot pack, transition plan, icon/card/logo events and the current review timeline of one
  episode. No hand-written brief: every prompt is derived from those files ([input contract](references/input-contract.md)).
- **Output:** 3 instrumental bed candidates (48 kHz stereo PCM16, length >= timeline + 3 s, sha256), 30 s dialogue-ducked previews,
  one SFX clip set (48 kHz) with a frame-aligned cue sheet JSON, saved ComfyUI workflows (API + GUI + review GUI with the result
  pinned), receipts (prompt id, VRAM, time), README/manifest with model files, sha256 and licence text, and a Vietnamese pick
  sheet `CHON-AM-THANH.txt` for the user. Nothing is mixed into the film by this skill.
- **Consumers:** the user (picks), `jjv audio mix` / Remotion (bed + cue sheet), Studio publisher (`/api/editorial-audio/register`).

## Models (measured, downloaded, licence)

| Role | File under `production-local/ComfyUI/models/` | Bytes | sha256 | Source |
|---|---|---|---|---|
| Music (LM+DiT+VAE AIO) | `checkpoints/yue2_3b_int8_convrot.safetensors` | 3 960 938 800 | `96fe199377309001ed8cd26a944baeee8cc31a20ba7c36d1d3c0a7e1f4149db6` | Comfy-Org/YuE2 (the file the bundled "YuE2: Text to Music" template uses) |
| SFX (DiT+VAE) | `checkpoints/stable_audio_3_small_sfx.safetensors` | 2 270 384 940 | `ed9cf1b6172f1a8c2921a9560c21109ff3239524563ced9dce6dcdef41e2f515` | Comfy-Org/stable-audio-3 |
| SFX text encoder | `text_encoders/t5gemma_b_b_ul2.safetensors` | 1 187 264 003 | `1e1eba25be8872edb0d3c6335c6658fd6388e7b14b60da6e454e404cfcd8150e` | Comfy-Org/stable-audio-3 |

Download on the host (`HF_HUB_OFFLINE=1` inside the container), verify sha256 from the HF tree API (`lfs.oid`) before renaming
`.part`, keep D: >= 20 GB free. Write the inventory file BEFORE downloading (`model-inventory.json`).
Licence: YuE2 weights **CC BY-NC 4.0 + "individual creator permission"** (GitHub `MODEL_LICENSE` 2026-09-16: individual
creators may generate and monetise outputs; "commercial use by companies" needs a separate licence; the HF card only says
cc-by-nc-4.0). Stable Audio 3: **Stability AI Community License** (free below US$1M/yr, register for commercial use, show
"Powered by Stability AI"). Whether JennieJoyKids is an individual creator or a company is a user/legal decision; record it, never assume.
No YuE2 fp8 repack exists; int8_convrot is the official quantised build and `CheckpointLoaderSimple` has no `weight_dtype`.

## Step 1. Script -> music brief (per episode, no free-form brief)

Read `script/shot-prompt-pack-v00N.json` (`shots[].speech_text`, `scene_title_vi`, `visual_description`, `target_keywords`) and the
review config (`dialogue[]`, `outro_cards[]`, `motion.ending`, `main_frames`, `total_frames_with_endlogo`). Derive, and write down
with the sentence of the script that caused it ([rules table](references/script-to-audio-rules.md)):

1. **Audience + setting** -> instrument family and register (preschool 2-4 y, sunny garden/farm -> ukulele, glockenspiel, felt piano,
   music box, nylon guitar, marimba, soft hand percussion; never brass hits, drums with impact, synth drops).
2. **Energy per act:** intro (title, 3 s), dialogue acts (question/answer pairs: steady, gentle), discovery beats (tokens, cups,
   bones, recipe book: light lift), outro vocabulary cards (warm, even), logo/end (settle, no sting). The bed is one continuous
   piece; the mix (not this skill) ducks it under speech (-14 dB) and fades it at the end card.
3. **Tempo and key:** 90-112 BPM, major key. Pick three distinct instrument sets for the three candidates (ep04: C/100 ukulele-glock,
   G/96 piano-musicbox, F/108 guitar-marimba) so the user hears a real choice, not three seeds of one idea.
4. **Length target:** `total_frames_with_endlogo / fps + 3 s` (ep04: 3374/30 + 3 = 115.5 -> 115 s floor).

Style text = structural clauses (keep) + episode clauses (change). Lyrics = the empty section skeleton. Exact strings:
[rules](references/script-to-audio-rules.md#music-style-text).

## Step 2. Shot pack + timeline -> SFX cue sheet (automatic, with one rejection rule)

For every shot, list each **visible** action that makes a sound in `visual_description` (rotate bottle, tilt bottle, hand-milking into a
metal pail, tokens set/slide, fabric sleeve on cup, wooden hinge, ribbon, book unfold, cow standing/grazing). One cue per action,
frame from the review config: before the line's first word when the action precedes speech (`dialogue[].words[0].startF`), or the v003
cue-manifest time when that lane had already placed the same physical action. Then add the structural events from the config:
whoosh only on `motion.transitions[].type == "whip"` (the motivated pan; others optional), a sparkle pop on every `motion.icons[].frame`,
a card sparkle on each `outro_cards[].start_frame`, a chime at the logo reveal (`motion.ending.logo_disc.in` + full-logo frame) and
at `end_logo.from_frame`, leaves at the garden shots, an optional ambience loop.
**Rejection rule:** a sound whose action is not on screen is generated for the library at most and marked `placed=false` with the
reason (ep04 SFX-01 "milk pour into glass": every shot forbids pouring; SFX-20 footsteps: nobody walks on screen). Cues that
contradict an earlier editorial direction (ep04 "no synthetic card stings") are kept but marked `optional` for the user.
Cue classes, prompt patterns, durations (>= 1.0 s: ComfyUI minimum), loudness and gains: [rules](references/script-to-audio-rules.md#sfx).

## Step 3. Generate (one guarded submit per graph)

- Music graph (official template chain): `CheckpointLoaderSimple` -> `YuE2GenerateABC` (mode full, 8192 tokens, T 0.7, top_p 0.9,
  top_k 30, rep 1.005, window 100) -> `YuE2GenerateMusic` (abc linked, T 1.0, top_p 0.95, top_k 100, rep 1.2, `max_duration` 150)
  -> `ConditioningZeroOut` negative -> `EmptyYuE2LatentAudio` (seconds linked from the Music node) -> `KSampler` 32 steps, cfg 1.0,
  `dpm_2`, `sgm_uniform` -> `VAEDecodeAudioTiled` 512/64 -> `SaveAudio` FLAC 48 kHz. One seed for all three stages.
- SFX graph (official SA3 template chain minus the Qwen reprompt): `CheckpointLoaderSimple` + `CLIPLoader(type=stable_audio)` ->
  `CLIPTextEncode` positive/negative -> `EmptyLatentAudio(seconds)` -> `KSampler` 8 steps, cfg 1.0, `lcm`, `simple` -> `VAEDecodeAudio`
  (44.1 kHz) -> `SaveAudio` FLAC.
- Builders: `04-milk-and-mom/audio/music-yue2-v001/tools/comfy_audio_graphs.py` (`yue2_music_graph`, `sa3_sfx_graph`, `api_to_gui`,
  `attach_audio_result`). Dispatch: `tools/run_comfy_audio_job.py` = `comfy_guarded_submit.py check -> submit -> wait` under the shared
  lock `technical/.comfyui-image-submit.lock` with an nvidia-smi monitor; receipts `dispatch-intent/submitted/job/vram.json` +
  `comfy-log-excerpt.txt`. Queue must be idle; one job at a time; never raw `POST /prompt`.
- **Pilot first:** 30 s music in `off` mode (no ABC) to measure VRAM/time before any long run; write `receipts/PILOT-STATUS.json`.
- **Measured on the 16 GB RTX 5080 (ep04):** pilot 24.7 s, peak +4.6 GiB over the desktop baseline (3.4 GiB); nine full takes 18-50 s
  each, +4.5 to +5.4 GiB (max 11.4 GiB total used); SFX 6-17 s per clip, +1.5 to +1.8 GiB. No `--lowvram`, no ACE-Step fallback needed.
- **Takes and seeds:** YuE2's ABC planner decides the song length and ignores `max_duration` as a target: with cap 150 the nine takes
  ended naturally at 34-113 s. Run >= 3 takes per candidate with the same seed family and three lyric/style variants (ep04: take1
  `[Instrumental]`, take2 empty 8-section skeleton, take3 skeleton + "about 2 minutes 30 seconds long, eight sections"), keep the
  longest natural-ending take per candidate (ep04: NHAC-1 take2 69 s, NHAC-2 take3 95 s, NHAC-3 take1 113 s). Mode `off` runs to
  the cap but ends abruptly; not used for beds.

## Step 4. Post (CPU, numpy/ffmpeg only)

1. Length: `tools/loop_extend.py --bpm <style BPM> --target-s <timeline+3>`: envelope-correlation search for the bar-aligned point in
   the second half that best matches the post-intro reference (4 bars), waveform refine +/-50 ms, 0.25 s equal-power crossfade, natural
   ending kept; writes `<out>.loop.json` (loop point, score; ep04 scores 0.72-0.84). Seams are unheard until a critic listens.
2. 48 kHz PCM16 beds (`*-raw-48k.wav` take, `*-full-48k.wav` bed); SFX 44.1 -> 48 kHz with ffmpeg `aresample=soxr:precision=28`.
3. Loudness: ffmpeg `ebur128=peak=true` (integrated LUFS, LRA, true peak) on every bed, preview and clip. Beds stay at raw YuE2 level
   (ep04 NHAC-1 peaked +0.1 dBTP): the mix attenuates; do not normalise here.
4. Preview: dialogue stem built from the review config (dialogue + vocabulary WAVs at their `start_frame`, unity) + music at -26 LUFS,
   ducked -14 dB inside each speech window (attack 0.14 s, release 0.28 s, the v003 duck contract), 30 s window from 3 s, 0.5 s fades.
5. Review GUI: copy the 48 kHz **WAV** (not FLAC: the container's `mimetypes` has no `.flac`, so `LoadAudio` hides it) into
   `ComfyUI/input/04-milk-and-mom-T-A10-<label>-<sha12>.wav`, add a `LoadAudio` node titled `KET QUA <status> | job <id8> | SHA <12>`,
   save `*.review.gui.json`; verify the pinned name is in `GET /object_info/LoadAudio` options.

## Step 5. Publish for the user pick

- Episode folders (new only): `audio/music-yue2-v00N/` (`README.md`, `manifest.json`, `model-inventory.json`, `licenses/`,
  `workflows/<take>/{api,gui,review.gui}.json + prompt.txt`, `receipts/`, beds, `previews/`) and `audio/sfx-v00N/` (same +
  `clips/`, `sfx-cue-sheet-v00N.json`, `tools/sfx_cue_spec.py`).
- ComfyUI copies, byte-identical, never overwriting: `ComfyUI/user/default/workflows/JENNIEJOYKIDS_<EP>/06_AUDIO_MUSIC/<take>/` and
  `07_AUDIO_SFX/<clip>/`; confirm with `GET /userdata?dir=workflows/...&recurse=true`.
- Pick folder: hard-links (`os.link`, same volume) into `editorial/XEM-DUYET-<date>/AM-THANH/`: `NHAC-n-nhac-nen-full.wav`,
  `NHAC-n-NGHE-THU-30s-co-thoai.wav` (<= 30 MB), `SFX-nn-<slug>.wav`, plus `CHON-AM-THANH.txt` (per file: what it is, where it sits
  mm:ss, length, LUFS, loop seam note, "KHONG DAT" reason) — format in [rules](references/script-to-audio-rules.md#pick-sheet).
- Status files root reads early: `receipts/PILOT-STATUS.json`, `receipts/MUSIC-STATUS.json` (per candidate as it lands).

## Step 6. Hand-off to `jjv audio mix`

Bed: `bed_wav`, `bed_wav_sha256`, `bed_duration_s >= timeline_s + 3`, `bed_loudness`, `loop_extension` (seam position) from
`manifest.json`/`MUSIC-STATUS.json`. SFX: every row of `sfx-cue-sheet-v00N.json` -> `cues[]`: `cue_id, file, file_sha256, shot,
frame, time_s, duration_s, gain_db, pan, optional, note` (+ `clips[]` with prompt, seed, prompt_id, native rate). The mix applies the
film-mix standard (−17 ±1 LUFS per section, true peak <= −1 dBTP, duck **−6…−8 dB**, attack 0.1–0.2 s, release 0.5–1 s, merged
windows; the older −12…−18 dB duck is superseded, it pumped in ep04 v013 — the −14 dB in this skill's previews is only the v003
preview contract, not a mix value), the end-card fade and the user's optional-cue decisions, then registers the chosen bed/SFX with
the Studio. This skill never edits `editorial/**`, `technical/**`, existing audio folders or FROZEN files.

## Coordination with VoiceStudio ([jenniejoy-voice-studio](../jenniejoy-voice-studio/SKILL.md))

Both skills read the same locked script + shot pack + timeline. VoiceStudio owns speech; this skill owns music and SFX; `jjv audio
mix` combines them. What this skill takes from VoiceStudio, per line and per vocabulary card: the **receipt WAV** (the WAV named in the
shot's H3 preparation receipt), its sha256, start frame and sample count (ep04: `review-config-v013.json` `dialogue[].audio`,
`outro_cards[].audio`, cross-checked against `engine/shots.json`). Used for: (a) **speech-free windows** — no SFX cue may start on a
spoken word (`words[].startF..endF`); cues sit before the first word, between words the sentence names, or in the gaps (ep04 cue
frames were chosen that way; the engine must assert it); (b) **music energy around dialogue density** — dense Q/A acts get the steady
groove, the card outro and logo get the even warm tail, the bed never stingers a line; (c) **the preview stem and the hand-off** — the
dialogue stem for previews is built from those receipt WAVs at unity and sample-exact, and the same list goes to the mix. Speech WAVs
are never trimmed, re-timed or re-generated here. A spoken line added late (ep04 "See you again, baby!") is a VoiceStudio job with its
own receipt WAV; then the mix is rebuilt and the film remuxed — the picture is not re-rendered and this skill's beds/cues stay valid
as long as their timeline frames do. GPU: TTS and music/SFX are serialised under the same lock.

## Errors met in ep04 (fixed; error-db entries under create-video-jenniejoykids/error-db/)

- `yue2-abc-planner-ends-song-before-max-duration` — cap is not a target; take strategy + loop_extend.
- `comfyui-empty-latent-audio-min-1s-rejected-sfx-cues` — 10 graphs rejected at validation (0.6-0.9 s); re-run `-r2` with 1.0 s, old
  receipts kept.
- `comfyui-loadaudio-combo-hides-flac-pins` — review GUIs pinned FLAC were invisible; pin WAV, verify via `/object_info`.
- `loop-extend-slice-length-off-by-one-hang` — envelope slices by integer division differed by one frame, search broke on the first
  step, the extension loop spun forever on an empty segment; fixed with a fixed frame count + guard. Killing it with a command-line
  substring match also killed the sibling shells: match on the python process only.

## Worked example (user liked it, not a default style): ep04 NHAC-2

`production-local/engine/staging/T-E43-audio/recipes/audio/music-yue2-example-ep04-nhac2.json` (exact graph, seed 20261102, params,
loop seam 76.70 s, measured VRAM/time) and `sfx-stable-audio-example-ep04.json` (21 clips, prompts, seeds, cue classes). Narrative with
paths: [ep04 worked example](references/ep04-worked-example.md). Template with slots the engine fills: `music-yue2-3b-int8-v001.json`,
`sfx-stable-audio-3-small-v001.json` (same folder).

## Vocal-free gate (mandatory for every bed; added T-A11, 2026-10-27)

"Instrumental" is a measured property. YuE2 3B int8 sang in 9/9 ep04 beds: NHAC-1/2/3 (v001) and 6/6 new takes, with
`[Instrumental]`, an empty section skeleton, and "no vocals, no singing, no humming, no choir, no human voice" in the style —
Demucs vocal stem only 1.2–4.1 dB below the full bed, whisper transcribed 131–177 s of invented English per bed
(error-db `yue2-instrumental-prompt-still-sings`). Procedure ([details](references/vocal-gate-and-brand-voice.md)):
1. Separate with Demucs htdemucs (`production-local/engine/tools/demucs-venv`, CPU, ~1 min per 2 min of audio; weights
   adefossez/HTDemucs `955717e8.safetensors` sha256 `d9fa1413…576dd`). Never inside the ComfyUI container.
2. Gate (`music-yue2-v002/tools/vocal_gate.py`): PASS only if `LUFS(vocals) − LUFS(bed) ≤ −35 dB` AND no 1 s window of the
   vocal stem is above −40 dBFS; stems come out at 44.1 kHz and are resampled to the bed rate first. A jingle region is exempt and
   reported separately (`--region-start-s`).
3. If a take fails but the music is right, the deliverable is the `no_vocals` stem (48 kHz soxr), loop-extended, then separated
   and gated AGAIN; report the separation residue (`tools/residue_check.py`: energy of original − no_vocals in vocal-free
   windows; ep04: −32…−37 dB mean, worst window −17 dB).
4. **Generator choice by evidence:** ACE-Step 1.5 turbo (native nodes `TextEncodeAceStepAudio1.5` + `EmptyAceStep1.5LatentAudio`,
   tags starting "instrumental, no vocals", lyrics `[Instrumental]`, bpm/keyscale set, 8 steps euler/simple cfg 1, shift 3)
   produced a 120 s bed that passed the gate raw (vocal −57.5 dB rel., 0 windows) in 40.6 s at +6.8 GiB. Models
   (`Comfy-Org/ACE-Step-1.5`, Apache-2.0): `diffusion_models/acestep_v1.5_turbo.safetensors` 4 787 825 604 B `3f6e0797…422d7`,
   `text_encoders/qwen_0.6b_ace15.safetensors` 1 191 588 248 B `fd4590c8…6aa7a7`, `text_encoders/qwen_1.7b_ace15.safetensors`
   3 708 523 360 B `ed63e924…ebd710`, `vae/ace_1.5_vae.safetensors` 337 431 732 B `6de92e3a…bb2bbb`. Prefer ACE-Step for beds;
   keep YuE2 only for sung material or when its texture is wanted (then Demucs + gate). Loudness: ACE raw output is hot
   (−11.5 LUFS, +1.0 dBTP): lower the bed so true peak ≤ −1 dBTP and record the gain.

## Brand sonic logo (voice-only readings; user rules 2026-10-27)

Deliverable = 3–4 **voice-only** readings of the brand line, separate from the bed; the film mix plays the voice alone at 0 s and
starts the bed when the voice ends (0.5 s fade-in), first dialogue at 3.0 s ⇒ reading ≤ 1.8 s. ep04 words: "Jennie Joy Kids!"
in English; melody described by the user as Vietnamese tones over four syllables "Jén↗ nì↘ Joy→ Kít↗" (Jen up, nie ≥ 4 st lower,
Joy mid, Kids up-crisp), cheerful, **moderate pitch** (mean F0 within +2 st of Alice's dialogue mean, ep04 ≈ 306 Hz; no
"very high" presets).
1. Takes: local VoiceStudio `POST /generate` (multipart; `instruct` only accepts taxonomy tokens — `child, high pitch` /
   `child, moderate pitch`; the WAV comes back as the response body, 24 kHz mono, `x-audio-id` header; outputs are watermarked).
   Zero-shot with `ref_audio` + `ref_text` = Alice's happiest approved ep04 line ("It tastes creamy, fresh, and yummy!") gave
   clearly livelier takes than the stored profile; text with "!!", speed 1.1–1.2, 2–3 seeds per variant. Optional source: a YuE2
   sung tag separated with Demucs (ep04: unintelligible, "I need your kids!", offered only as a labelled extra).
2. Sculpt (`music-yue2-v002/jingle/make_readings.py`): split syllables at ASR word boundaries ("Jennie" halved), per-syllable
   pitch with ffmpeg `rubberband` (duration preserved; ep04 A: +1.5/−2/0/+1.5 st, B: +2.5/−3.5/+0.5/+3), 15 ms crossfades,
   one silence trim (60 ms tail fade so "Kids" ends crisp), tempo-fit to ≤ 1.8 s, 48 kHz stereo, +2 dB @ 4 kHz,
   two-pass loudnorm −16 LUFS / −1 dBTP. Chorus = 3 takes layered (0/14/26 ms, ±0.2 st). A −3 st "nie" made whisper hear
   "Jimmy": keep the dip ≤ 2 st on the first syllable.
3. Measure (`tools/analyze_voice.py`, VoiceStudio venv has faster-whisper): ASR must read "Jennie/Jenny Joy('s)/Joyce Kids";
   F0 mean vs Alice; per-syllable medians (autocorrelation, 120–520 Hz, periodicity ≥ 0.65 — on a 1.6 s clip "Kids" often has
   < 3 voiced frames, so the contour numbers are indicative; the ear decides); spectral centroid as a brightness proxy.
4. Publish `editorial/XEM-DUYET-<date>/THUONG-HIEU/GIONG-A..D.wav` (hard links) + `CHON-THUONG-HIEU.txt` (route, voices,
   length, LUFS, ASR text, contour) and a status JSON for root; previews that join voice + bed are named `PREVIEW-GIONG-A+<bed>…`.
   Receipts: `jingle/voice-takes/voice-takes-receipt.json` (profile, text, ref, seed, speed, sha), `readings/readings-receipt.json`.

Updating this skill records a verified procedure; it is not model-weight retraining.
