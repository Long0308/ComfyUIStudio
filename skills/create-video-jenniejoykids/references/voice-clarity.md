# Voice clarity for children under three

Alice uses the saved VoiceStudio profile8f1145d7 (OmniVoice). The original source and profile remain immutable. User feedback on2026-10-17: H3 S01_A video rendered successfully, but its generated speech was not sufficiently clear. Do not mark this generated soundtrack accepted because a reference WAV or audio guide was connected.

Performance note for every relevant AUDIO/VIDEO JSON segment:

"Use the approved Alice voice identity. Speak the exact English line slowly and naturally for a two-year-old to repeat. Enunciate each complete word, especially initial and final consonants; preserve normal English word stress and intonation. Use a warm close, clean voice with short natural pauses between phrases. Keep the voice steady and intelligible, with no swallowed words, babble, whisper, slurring, exaggerated baby pronunciation, robotic syllable splitting or added speech. Finish the exact line before the response pause. Keep music and animal calls beneath the speaking voice."

For canonical_voicestudio, first compare the original VoiceStudio WAV against the H3-generated voice using the same picture and playback level. Preserve the complete native H3 AV file. Use the original verified VoiceStudio source in the editorial comparison, record the substitution explicitly, and do not mix duplicate H3 speech underneath it. A normal AAC delivery transcode is not a bit-exact WAV archive; preserve the WAV separately.

If the source VoiceStudio WAV is also unclear, regenerate only affected exact lines with the saved approved profile and the clarity note. Do not re-clone or replace Alice's identity or alter VoiceStudio's environment. Serialize GPU ownership: inspect Comfy queue, release its idle models through the supported local free endpoint, then synthesize. Save new versioned WAVs, source/profile/settings hashes and measurements. Listen before replacing any accepted line, recheck mouth timing and captions, and never time-stretch to force words into a shot. Extend/re-plan the segment if clear delivery cannot fit.

Record per-line clarity review in an AUDIO QA JSON artifact, for example:

```json
{
  "segment_id": "S01_A",
  "voice_profile_id": "8f1145d7",
  "exact_text": "Mom, Dad, and me!",
  "performance_note": "Slow natural English, complete consonants, warm steady voice, response pause after the exact line.",
  "native_h3_voice_review": "user_reported_unclear",
  "editorial_voice_source": "canonical_voicestudio",
  "canonical_source_sha256": "RECORD_ACTUAL_HASH",
  "canonical_clarity_review": "pending_listening",
  "exact_words_review": "pending",
  "lip_sync_review": "pending",
  "subtitle_timing_review": "pending",
  "regeneration_required": null,
  "accepted": false
}
```

ASR verifies words, not timbre or comfort. Loudness/EQ cannot repair incorrectly pronounced or missing words. Avoid aggressive denoise, excessive sharpening/sibilance or heavy compression. Keep separate VO/music/SFX stems and duck background12–18dB below speech as a starting mix choice; evaluate quiet speakers and headphones. User listening feedback overrides an automatic pass. Render720p for review; only explicit acceptance enables1080p. Export size does not establish native detail.

In the 2026-10-17 local audit, full-track VAD omitted the initial “Look!” in two
utterances. CPU-only recognition of the unchanged isolated original WAVs with
VAD disabled recovered “Look! A little bird.” and “Look! A panda!” without a
prompt or hotwords. Before replacing a supposedly missing word, inspect the
original line and VAD boundary separately. Preserve the canonical source and
placement clock; ASR word timestamps are estimates, not replacement edit timings.
Project evidence: `audio/asr-cpu-audit-v1/audit.json` and
`audio/asr-cpu-audit-lines-v2/audit.json`. Final listening remains pending.
