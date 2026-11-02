# ep04 "Milk and Mom" worked example (T-A10, 2026-10-27) — the user picked NHAC-2 and liked it

Root: `production-local/JennieJoyKids-Story/04-milk-and-mom/audio/` (`music-yue2-v001/`, `sfx-v003/`), pick folder
`editorial/XEM-DUYET-2026-10-27/AM-THANH/`, engine staging `production-local/engine/staging/T-E43-audio/`.

## From the script to the three briefs

Script facts used: 12 lines, Mother asks / Alice answers, garden picnic table + farm fence with a milkmaid and two cows, props =
sealed bottle, wooden taste tokens, two cups with fabric sleeves, wooden arm model, measuring ribbon at a tree, three-panel recipe book,
then 12 vocabulary cards and a logo. Timeline v013: 3314 + 60 frames @30 = 112.47 s -> bed >= 115 s.

| Candidate | Episode clauses | Seed | Why (from the script) |
|---|---|---|---|
| NHAC-1 | 100 BPM, C major, ukulele strumming, glockenspiel melody, soft piano chords, light shaker and hand claps | 20261101 | sunny garden, playful Q&A; glockenspiel = "bright" the user asked for |
| NHAC-2 | 96 BPM, G major, soft felt piano, music box and celesta melody, warm upright bass, brushed light percussion, lullaby-like | 20261102 | gentle mother-child tone, ends with a daytime nap on the bench (S06_B) |
| NHAC-3 | 108 BPM, F major, nylon acoustic guitar, marimba and toy xylophone, light bongo and shaker, sunny garden morning | 20261103 | farm/outdoor energy, cows and pasture |

Structural clauses and the lyric skeleton: see [rules](script-to-audio-rules.md#music-style-text). Take variants: take1 lyrics
`[Instrumental]`; take2 empty 8-section skeleton; take3 skeleton + "long-form ... about 2 minutes 30 seconds long, eight sections".

## Runs (all local, guarded, one at a time)

| Take | Output | Wall | nvidia-smi peak delta | Delivered? |
|---|---|---|---|---|
| pilot-30s (off mode) | 30.0 s | 24.7 s | +4588 MiB | measurement only |
| NHAC-1 take1 / take2 / take3 | 57.3 / 69.1 / 91.9 s | 29.4 / 24.5 / 32.6 s | +4830 / +4658 / +4931 | take2 (seam score 0.84) |
| NHAC-2 take1 / take2 / take3 | 59.4 / 34.1 / 95.5 s | 24.5 / 18.4 / 34.5 s | +4664 / +4518 / +4658 | **take3 (user pick)** |
| NHAC-3 take1 / take2 / take3 | 113.0 / 108.1 / 58.2 s | 49.7 / 36.5 / 28.6 s | +5278 / +5437 / +4633 | take1 |

NHAC-2 take3: prompt `0f...` see `receipts/NHAC-2-piano-musicbox-take3/job.json`; graph
`workflows/NHAC-2-piano-musicbox-take3/NHAC-2-piano-musicbox-take3.api.json`; FLAC 95.48 s; loop_extend bpm 96 target 118 ->
166.9 s, loop point 76.697 s, score 0.7222, crossfade 0.25 s; bed `NHAC-2-piano-musicbox-take3-full-48k.wav`
sha256 `2a291a050fe730562eafb7b5cbfda50605389029496ce025ed991c8763a38283`, -15.0 LUFS / -0.1 dBTP; preview
`previews/NHAC-2-NGHE-THU-30s-co-thoai.wav` -16.1 LUFS. Exact params: `recipes/audio/music-yue2-example-ep04-nhac2.json`.

## SFX cue sheet (21 clips, 57 placements, v013 frames)

Derivation per clip and the rejection of SFX-01 (pouring) / SFX-20 (footsteps): `sfx-v003/tools/sfx_cue_spec.py` (every cue carries the
shot sentence), machine sheet `sfx-v003/sfx-cue-sheet-v003.json`, human sheet `AM-THANH/CHON-AM-THANH.txt`. Stable Audio 3 small-SFX,
8-step LCM, 6-17 s and +1.5..+1.8 GiB per clip. First run: 10 graphs rejected at ComfyUI validation (`EmptyLatentAudio.seconds` min
1.0); re-run as `receipts/<clip>-r2` with 1.0 s. Example recipe: `recipes/audio/sfx-stable-audio-example-ep04.json`.

## Published workflows

`ComfyUI/user/default/workflows/JENNIEJOYKIDS_04_MILK_AND_MOM/06_AUDIO_MUSIC/<take>/` (10 takes x api/gui/review = 30 files) and
`07_AUDIO_SFX/<clip>/` (21 x 3 = 63). Review GUIs pin `ComfyUI/input/04-milk-and-mom-T-A10-*.wav` (31 files, all listed by
`GET /object_info/LoadAudio`).

## What was not done

No human listening by the builder (vocal-free, loop seams, clip realism), no film mix (v014 builder), bed not normalised, SFX clips
not trimmed, the `-26 LUFS / -14 dB` preview levels are the v003 duck contract, not a mix decision.
