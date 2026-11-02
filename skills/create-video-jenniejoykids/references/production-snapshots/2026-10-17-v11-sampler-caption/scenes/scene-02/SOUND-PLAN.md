# Scene 2 — âm thanh và hậu kỳ

Nguồnproduction-request-v9.json SHA2563dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643; kế hoạch, chưa mix/nghe duyệt.

Alice chỉ chim và nói hai câu tiếng Anh; mẹ nhìn theo ngón tay, ba mỉm cười gật đầu. Một tiếng chim ngắn khi chim cử động mỏ, lá rung nhẹ. Để khoảng trống bé đọc theo, tránh tiếng chim đè phụ âm.

```json
{
  "schema_version": "1.0",
  "scene_id": "S02",
  "name": "Scene 2",
  "global_interval_seconds": [
    10,
    20
  ],
  "fps": 24,
  "status": "planned_not_mixed_or_listening_accepted",
  "location": "Willow tree and bird",
  "voice": {
    "profile_id": "8f1145d7",
    "authority": "canonical_voicestudio",
    "source": "D:\\23.JennieHomeSchool\\03 Voice\\production-local\\audio\\canonical-v2\\alice-canonical-60s.wav",
    "notes": "Exact English words; slow clear consonants; no extra dialogue; separate eating/drinking from speech"
  },
  "ambience": "Soft nearby leaf rustle, quiet open-air zoo bed, friendly small-bird chirps in pauses.",
  "sfx_intent": "Bird chirp/hop/flutter cues align actual perch movement; footsteps settle before looking up. No competing speech.",
  "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
  "tracks": [
    "canonical_voice",
    "music",
    "ambience",
    "footsteps",
    "animal",
    "props"
  ],
  "cue_policy": {
    "footsteps": "Align transient to actual observed contact frame; eventframes pending rendered motion",
    "animal": "Prefer gaps between words; avoid masking first/final consonants",
    "props": "Cue visible contact and audible transient; do not align blindly to file start",
    "measurement": "planned seconds distinct from measured source PTS/local/global frames"
  },
  "mix_choices": {
    "integrated_lufs_target": -16,
    "true_peak_ceiling_db": -1,
    "music_relative_to_voice_db_range": [
      -18,
      -12
    ],
    "status": "creative_choices_require_measured_mix_and_listening"
  },
  "asset_policy": "Record license/source/hash for acquired recordings. Existing synthesized cues are synthesized, not authentic animal recordings. No downloads/substitutions without provenance.",
  "performance_and_foley": "Alice chỉ chim và nói hai câu tiếng Anh; mẹ nhìn theo ngón tay, ba mỉm cười gật đầu. Một tiếng chim ngắn khi chim cử động mỏ, lá rung nhẹ. Để khoảng trống bé đọc theo, tránh tiếng chim đè phụ âm.",
  "source_script": "D:\\23.JennieHomeSchool\\03 Voice\\production-local\\production-request-v9.json",
  "timing_status": "Canonicalv2originalPCMverified; captions-v2prepared; motioncontacts/lipsync/readability/finalducking/listeningpending.",
  "postproduction": {
    "stems": [
      "canonical_voice",
      "music",
      "ambience",
      "footsteps",
      "animal",
      "props"
    ],
    "voice_priority": "Original saved Alice; no duplicated generated speech; clear consonants and natural pace",
    "music": "Cheerful original quiet instrumental, no lyrics; further ducking measured because source music already ducked",
    "animal_style": "Soft non-startling cues, label synthesized sources honestly",
    "lighting_picture": "Stable warm daylight, restrained saturation, no sudden exposure/white-balance changes; match consecutive boundaries",
    "review": "Visual contacts, actual dialogue clock, subtitles, normal-speed listening and loudness/true-peak checks before completion Verify foreground gap budget, actual mouth readiness and explicit hand ownership. Keep mouth sounds subtle; no artificial accelerated chewing."
  },
  "source_script_sha256": "3dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643",
  "source_intent_version": "v9-promoted-planned-not-generated",
  "foreground_gap_budget": "At most one quiet foreground accent per speech-free gap; reserve remaining gap for child imitation. Footstep bed barely audible. Never stack chuff/paw/props accents. Inspect already-ducked music before additional ducking."
}
```
