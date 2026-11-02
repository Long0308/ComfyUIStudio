# Scene 1 — âm thanh và hậu kỳ

Nguồn kịch bản: production-request-v8.json, SHA256 7f05ccbc0d5af2e69b3b4b66e3398e1ea2fa19ba84d5fd05010736c5a556c68e. Đây là kế hoạch, chưa phải mix đã duyệt nghe.

Giọng Alice kể ngoài hình, gọi ba mẹ theo hai câu đã khóa; ba mẹ đáp bằng ánh mắt/cử chỉ. Tiếng giày bé nhẹ hơn giày ba mẹ, không chèn tiếng cửa đóng khi cổng đã mở. Không gian ngoài cổng chuyển dần sang lá cây và chim ở xa.

At most one quiet foreground accent per speech-free gap; reserve remaining gap for child imitation. Footstep bed barely audible. Never stack chuff/paw/props accents. Inspect already-ducked music before additional ducking.

```json
{
  "schema_version": "1.0",
  "scene_id": "S01",
  "name": "Scene 1",
  "global_interval_seconds": [
    0,
    10
  ],
  "fps": 24,
  "status": "planned_not_mixed_or_listening_accepted",
  "location": "Outdoor zoo entrance",
  "voice": {
    "profile_id": "8f1145d7",
    "authority": "canonical_voicestudio",
    "source": "D:\\23.JennieHomeSchool\\03 Voice\\production-local\\audio\\canonical-v2\\alice-canonical-60s.wav",
    "notes": "Exact English words; slow clear consonants; no extra dialogue; separate eating/drinking from speech"
  },
  "ambience": "Soft leafy park air and distant visitors without intelligible speech; transition to inner garden as gate passes behind.",
  "sfx_intent": "Footsteps: toddler light sneaker taps, parents softer shoe steps, aligned only to observed foot contacts. Subtle cloth movement and gate-space air; no fictional gate slam.",
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
  "performance_and_foley": "Giọng Alice kể ngoài hình, gọi ba mẹ theo hai câu đã khóa; ba mẹ đáp bằng ánh mắt/cử chỉ. Tiếng giày bé nhẹ hơn giày ba mẹ, không chèn tiếng cửa đóng khi cổng đã mở. Không gian ngoài cổng chuyển dần sang lá cây và chim ở xa.",
  "source_script": "D:\\23.JennieHomeSchool\\03 Voice\\production-local\\production-request-v8.json",
  "timing_status": "Planned motion; canonical-v2 originalPCM and S05_Bguide rebuilt/independently verified; finalcaptions/mixducking/contactcues/listeningpending.",
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
  "source_script_sha256": "7f05ccbc0d5af2e69b3b4b66e3398e1ea2fa19ba84d5fd05010736c5a556c68e",
  "source_intent_version": "v8-promoted-planned-not-generated",
  "foreground_gap_budget": "At most one quiet foreground accent per speech-free gap; reserve remaining gap for child imitation. Footstep bed barely audible. Never stack chuff/paw/props accents. Inspect already-ducked music before additional ducking."
}
```
