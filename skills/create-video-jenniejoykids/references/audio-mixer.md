# Measured-cue audio finishing mixer

Run `python scripts/mix_audio.py path/to/audio-mix.json` after the accepted picture
has measured contact/event frames and the saved VoiceStudio words have accepted
timings. This command performs offline audio finishing only. It generates no
speech, music, video, network request or GPU job. Requirements: Python 3.11+,
existing NumPy and an existing FFmpeg executable; it installs nothing.

The canonical voice source is a complete WAV including planned silence, with
duration equal to the edit. The music source must cover the edit. Source files
are mono/stereo integer PCM16/24/32 WAVs, bound by actual SHA256. Every path except
the bare executable name `ffmpeg` resolves relative to the JSON file. Absolute
paths work too. A fully new output directory is mandatory; never reuse a failed
or successful version. Keep the source WAVs and their original provenance.

## Input contract

This structural example requires real paths, hashes and measured frames before
use. Its two words and event are illustrative, not approved zoo timing. Obtain
SFX paths/hashes from the prepared library manifest; rebind the relative paths
when moving that library. The mixer contains no machine-specific asset paths.

```json
{
  "schema_version": "1.0",
  "output_dir": "mix-v2",
  "ffmpeg": "ffmpeg",
  "duration_seconds": 10,
  "fps": 24,
  "sample_rate": 48000,
  "voice": {
    "file": "canonical-voice.wav",
    "sha256": "REPLACE_WITH_ACTUAL_64_HEX_SHA256",
    "gain_db": 0,
    "pan": 0
  },
  "music": {
    "file": "music-original.wav",
    "sha256": "REPLACE_WITH_ACTUAL_64_HEX_SHA256",
    "gain_db": -3,
    "pan": 0
  },
  "speech": [
    {"id": "line-1", "start_seconds": 1.0, "end_seconds": 3.25},
    {"id": "line-2", "start_seconds": 6.0, "end_seconds": 8.32}
  ],
  "speech_guard": {"before_seconds": 0.15, "after_seconds": 0.20},
  "ducking": {
    "music_db": -12,
    "ambience_db": -9,
    "footsteps_db": -12,
    "fade_seconds": 0.06
  },
  "ambience": [{
    "id": "leafy-air",
    "file": "sfx-library/assets/zoo-leafy-air-12s.wav",
    "sha256": "REPLACE_WITH_ACTUAL_64_HEX_SHA256",
    "placement_status": "ambient_no_contact",
    "start_seconds": 0,
    "offset_seconds": 0,
    "duration_seconds": 10,
    "gain_db": -2,
    "pan": 0,
    "loop": false,
    "loop_crossfade_seconds": 0.20
  }],
  "cues": [{
    "id": "observed-shoe-contact-1",
    "category": "footsteps",
    "file": "sfx-library/assets/toddler-step-a.wav",
    "sha256": "REPLACE_WITH_ACTUAL_64_HEX_SHA256",
    "placement_status": "measured",
    "measured_global_frame": 12,
    "transient_seconds": 0.015,
    "offset_seconds": 0,
    "gain_db": -2,
    "pan": 0,
    "speech_policy": "attenuate",
    "evidence": {
      "note": "Replace with actual source frame/PTS/contact review"
    }
  }],
  "mastering": {
    "normalize": true,
    "integrated_lufs": -16,
    "true_peak_db": -1
  }
}
```

All numbers must be finite; booleans do not substitute numbers. Supported duration
is 1–600 seconds, integer delivery fps is 1–120, and duration must fill whole
delivery frames. Target rate is configurable from 8–192 kHz, normally 48 kHz.
Gain is −120 to +24 dB; pan is −1 to +1 with equal-power balance and an unchanged
center. Keep values modest and review the actual mix. These bounds prevent
accidental unbounded jobs; longer projects can be divided into accepted reels.

## Event timing

Every footstep, animal or prop cue requires `placement_status: "measured"` and
an integer `measured_global_frame`. Alternatively supply `measured_local_frame`
and integer `scene_start_global_frame`; their sum is the global event frame.
If both coordinate systems are supplied, they must agree. Null/planned placeholders
are rejected. Evidence is supplied by picture review; setting the JSON field does
not itself prove that a contact was visually inspected.

`transient_seconds` is the measured audible hit within the **original source
WAV**. `offset_seconds` trims the source start without changing speed. Optional
`duration_seconds` selects the source slice. The transient must remain inside
that slice. The mixer places the audible hit on `frame / fps`, quantized to the
nearest output PCM sample. It rejects negative starts and cues whose full selected
slice exceeds the edit; it never silently cuts a decay. `actual-clock.json`
records selected source offset, event frame, hit sample and start/end samples.

Animal and prop cues use `speech_policy: "avoid"`: their selected slice cannot
overlap any declared speech interval plus its consonant guards. Props include
cap, sip, food and wrapper accents. Footsteps may use `attenuate` and are ducked
under guarded speech, or use `avoid` for a speech-free contact. Only actual
continuous non-contact atmosphere belongs in `ambience`; declaring a footstep
or eating event as ambience defeats review and is prohibited.

For the current Scene 5, the proposed sip action is local3.25–4.35 seconds in
subshotA after its line1.00–2.99. SubshotB's original2.94-second second utterance
now occupies0.35–3.29 (master45.35–48.29); its tiny banana bite is proposed at
B3.55–3.95 (scene8.55–8.95/master48.55–48.95). This leaves2.05 seconds before
Scene6 speech at51.00, but swallowing/mouth readiness must still be observed.
The older9.15–9.65 scene-local bite window is superseded for this production.
Do not copy proposed windows into measured cue fields. Measure the
accepted picture first and ensure each selected audible slice fits after the
actual guarded words. Preserve quiet time for the toddler to repeat. Select a
soft tiger chuff **or** mild purr/growl per pause; don't stack into a loud roar.

Non-contact atmosphere needs `placement_status: "ambient_no_contact"`, explicit
timeline start and duration. Short sources require `loop: true` and a positive
crossfade shorter than half the source. The mixer crossfades loop seams and adds
30 ms edge fades to atmosphere. It does not fabricate crowd or animal recordings.
Keep synthesized Foley provenance labelled synthesized.

## Outputs and review

The fresh output directory contains `voice.wav`, `music.wav`, `ambience.wav`,
`footsteps.wav`, `animal.wav`, `props.wav`, `premaster.wav`, `final-mix.wav`,
`actual-clock.json`, `provenance.json` and per-output EBU logs under `qa/`.
Adjust track gain, pan and timing in JSON and render a new version. Stem WAVs use
32-bit float headroom; the final mix is stereo PCM16. Float premaster/stems may
exceed 0 dBFS before mastering; the final cannot clip or exceed its measured
true-peak ceiling (0.1 dB measurement tolerance).

FFmpeg decodes/resamples each source to the requested stereo sample rate. This
is disclosed with original source hashes/formats. It changes neither the saved
WAVs nor the number, order or speed of words. The separate voice stem receives
only its requested amplitude/pan and sample-format/rate conversion. Never feed
native H3 speech beneath the canonical VoiceStudio words. Preserve the complete
native H3 AV source separately.

With `mastering.normalize: true`, two-pass loudnorm measures the premaster and
applies documented mix amplitude/dynamic processing. Without it, only static
overall attenuation is applied when necessary for true-peak headroom; a LUFS
target is then merely informational. Output sample counts are conformed without
time-stretching. Do not describe a normalized master as a bit-exact canonical
WAV archive. The untouched canonical source remains the archive.

Every output receives strict FFmpeg decoding, exact sample-count, finite PCM,
sample-peak and EBU loudness/true-peak checks. Input hashes are rechecked before
publishing provenance; a failed run has no accepted receipt and needs a new
output version. `technical_pass_listening_pending` is not listening acceptance.
Play at normal speed on quiet speakers/headphones; assess clear words, comfortable
animal sounds, contact sync, response pauses and music balance. Short one-shot
or silent stem LUFS can be gated/unavailable; never normalize each SFX to voice
LUFS. Final picture, subtitle and 720p-before-1080p gates remain unchanged.

Focused checks:

```powershell
python -m unittest discover -s tests -p test_audio_mixer.py -v
```

Existing music-original.wav from the zoo's first mix is already speech-ducked.
The mixer's additional ducking is cumulative: choose source/gain accordingly and
listen for pumping or excessively quiet music. Do not assume an unducked source
from the filename. The mixer currently requires at least3dB ducking per bus.

The current commissioning project now has a separately reproduced, unducked
original source at `production-local/audio/music-unducked-v1/`. The isolated
recipe copies only the original note/phrase/bass/pan/envelope/fade operations,
with no voice, Foley, normalization or ducking. Independent code/Python review
reconstructed its entire PCM and WAV with zero differing samples. Source is
60s/stereo24k PCM16, SHA256
`7bcf43d306c8bfe6fee1c61b6393d1c75a90e3590a70d488d48f40b1af59b31a`.
Technical source loudness is−33.23LUFS/−23.37dBTP; listening remains pending.
Prefer this hash-bound source for ONE measured speech-clock ducking pass.
The separate `bed-preview-v2` is a preparatory Alice+music+non-contact-air mix,
not the final film soundtrack: its event cue list is empty. It reached60s,
48kHzstereo,−16LUFS/−1dBTP with strict decoding, while contact Foley, normal-speed
listening and picture/subtitle review still await accepted animation. Never
mark a film's footsteps/animal/props complete merely because a bed preview passes.

The tests construct disposable tone fixtures and run CPU FFmpeg only. They do
not access Alice, the production SFX library, GPU/VoiceStudio or the video queue.
