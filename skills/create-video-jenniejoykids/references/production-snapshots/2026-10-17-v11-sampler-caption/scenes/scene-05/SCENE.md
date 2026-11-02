# Scene 5 / S05 — kịch bản phim

Nguồn production-request-v9.json, SHA2563dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643. Chưa có phân cảnh mới đạt hình. Scene1enginev9 đang chạy từ sourcev8; Scene1 giữ nguyên. Chuyển động, nối cảnh và góc nói phải xem render thực tế.

| Master giây | English dialogue |
| --- | --- |
| 41.00–42.99 | Look! A panda. |
| 45.35–48.29 | Panda. A hungry panda. |

Xem SOUND-PLAN.md cho nhạc, không gian, bước chân, con vật và đồ vật. Full cast và toàn bộ action/camera bên dưới luôn được giữ trong prompt.

```json
{
  "id": "S05",
  "start": 40,
  "duration": 10,
  "characters": [
    {
      "id": "alice",
      "name": "Alice",
      "entity": "Human preschool cartoon character",
      "species": "Homo sapiens human",
      "age": "Two-year-old toddler girl",
      "body_proportions": "Small round toddler torso, short limbs and oversized round head",
      "surface": "Warm peach skin, rosy round cheeks with two tiny white highlights",
      "eyes": "Very large dark-brown eyes, near-black pupils, white catchlights and short upper lashes",
      "brows": "Gently arched chestnut eyebrows",
      "nose_beak": "Tiny peach button nose",
      "mouth": "Small mouth, red-pink interior and rounded tongue; flexible speech phonemes",
      "ears": "Small rounded peach ears",
      "hair_head": "Chestnut short wavy bob, side-swept bangs, high side ponytail on anatomical RIGHT",
      "clothes": "Rose-pink A-line dress, short puff sleeves, white two-lobed Peter Pan collar, ONE centered white chest heart, lightly pleated skirt, thin white hem line",
      "footwear": "White frilly ankle socks; rose-pink lace-up sneakers with white laces, white rounded toe caps and white soles",
      "accessories": "One large rose-pink bow at anatomical RIGHT ponytail anchor; no other accessories",
      "marks_asymmetry": "Bow and ponytail on anatomical RIGHT, viewer LEFT in front view; no mirroring",
      "reference_assets": [
        {
          "role": "face_front",
          "path": "assets/references/alice1.jpg",
          "status": "available",
          "scope": "Canonical front-view identity; no assertion of unseen side views"
        },
        {
          "role": "wardrobe",
          "path": "assets/references/alice1.jpg",
          "status": "available",
          "scope": "Canonical puff sleeve dress and sneakers"
        },
        {
          "role": "accessories",
          "path": "assets/references/alice1.jpg",
          "status": "available",
          "scope": "Canonical anatomical right bow"
        },
        {
          "role": "gesture_only",
          "path": "assets/references/alice2.jpg",
          "status": "available",
          "scope": "Expression and gestures only; exclude alternative costumes"
        },
        {
          "role": "family_lineup",
          "path": "assets/references/family-reference-higgsfield.png",
          "status": "available",
          "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
        }
      ]
    },
    {
      "id": "mother",
      "name": "Mother",
      "entity": "Human preschool cartoon character",
      "species": "Homo sapiens human",
      "age": "Adult woman approximately thirty years old",
      "body_proportions": "About twice Alice height, softly rounded adult proportions",
      "surface": "Warm light-peach skin, oval face, softly rounded cheeks",
      "eyes": "Almond dark-brown eyes with small white catchlights",
      "brows": "Gently arched brown eyebrows",
      "nose_beak": "Small rounded peach nose",
      "mouth": "Small curved mouth with flexible silent smiles",
      "ears": "Small rounded ears partly covered by hair",
      "hair_head": "Chestnut shoulder-length hair, left-side part, ends curled inward",
      "clothes": "Muted dusty-teal short-sleeved blouse, plain round neck, straight cream ankle-length trousers",
      "footwear": "Simple off-white flat shoes",
      "accessories": "No glasses, jewelry, hat or handbag",
      "marks_asymmetry": "Left-side hair part remains anatomical left; no distinctive facial marks",
      "reference_assets": [
        {
          "role": "family_lineup",
          "path": "assets/references/family-reference-higgsfield.png",
          "status": "available",
          "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
        }
      ]
    },
    {
      "id": "father",
      "name": "Father",
      "entity": "Human preschool cartoon character",
      "species": "Homo sapiens human",
      "age": "Adult man approximately thirty-two years old",
      "body_proportions": "Adult softly broad shoulders, slightly taller than Mother",
      "surface": "Warm light-peach skin, softly rounded rectangular face, clean-shaven",
      "eyes": "Almond dark-brown eyes with small white catchlights",
      "brows": "Straight dark-brown eyebrows",
      "nose_beak": "Small broad rounded peach nose",
      "mouth": "Small curved mouth with flexible silent smiles",
      "ears": "Rounded ears visible beside short hair",
      "hair_head": "Short neat dark-chestnut hair with fixed anatomical left side part",
      "clothes": "Muted sage-green short-sleeved polo, small folded collar, two cream buttons; straight beige trousers",
      "footwear": "Simple brown low shoes with rounded toes",
      "accessories": "No glasses, facial hair, hat, watch or bag",
      "marks_asymmetry": "Clean-shaven face, fixed anatomical left hair part, no other distinctive marks",
      "reference_assets": [
        {
          "role": "family_lineup",
          "path": "assets/references/family-reference-higgsfield.png",
          "status": "available",
          "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
        }
      ]
    },
    {
      "id": "panda",
      "name": "Panda",
      "entity": "Friendly preschool cartoon animal",
      "species": "Ailuropoda melanoleuca giant panda",
      "age": "Healthy adult animal with gentle behavior",
      "body_proportions": "Round seated bear body, four broad paws, short tail",
      "surface": "Soft warm-white fur with black ears, limbs and shoulder band",
      "eyes": "Dark brown eyes inside stable rounded black eye patches",
      "brows": "No separate human eyebrows; gentle expression through eyelids",
      "nose_beak": "Broad small black bear nose",
      "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
      "ears": "Two rounded black fur-covered external ears",
      "hair_head": "Rounded white fur-covered head without human hair",
      "clothes": "No clothes; natural animal surface fully visible",
      "footwear": "No footwear; natural species-appropriate feet",
      "accessories": "No accessories, harness, jewelry or human props",
      "marks_asymmetry": "Stable black eye patches and shoulder band; natural paws, no extra markings",
      "reference_assets": []
    }
  ],
  "setting": "First half: Same visitor shelf beside bamboo recess. Opaque pale-rock divider hides tiger for whole segment. Bamboo wall return hides seated panda initially, then small parallax reveals it behind secure rail. Bottle, cap and snack box remain continuously visible with parents. Second half: Same bamboo recess and visitor shelf. Open cream bottle/sage cap remain with mother; open cream snack box and soft banana piece remain with father.",
  "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
  "camera": "First half: Hold medium-wide three-quarter side view from same path-left shoulder, showing toddler face, mother supporting bottle, father with box and panda beyond rail. No camera move during sip. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face. Second half: Locked calm medium-wide three-quarter view; mouth, offered bite and panda paws readable, both parents in frame. Same world/camera axis as A. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
  "action": "First half: Start from exact shelf contacts with child hands free. First0–1s camera clears bamboo wall return to reveal panda, mother LEFT hand lifts bottle and father RIGHT hand lifts box. Tiger stays hidden. Toddler delivers exact1.00–2.99 line with modest LEFT head glance toward mother; feet/torso keep axis. Mother RIGHT hand unscrews and retains sage cap during words, quietly. Father LEFT hand opens box lid. Only3.25–4.35 mother supports one small sip using bottle in LEFT hand while cap remains RIGHT hand; child hands stay clear. After sip mouth clears rim; mother lowers bottle, keeping cap. Father holds open box, no food reaches mouth yet. Second half: Start after sip with empty mouth and child hands free. Mother LEFT hand supports bottle while RIGHT hand quietly recaps during0–1s; no accented click under speech. Toddler delivers exact hungry-panda line0.35–3.29 with modest LEFT head glance toward mother, torso/feet unchanged. Panda gently nibbles. Father RIGHT hand supports box; LEFT hand prepares tiny soft banana piece away from mouth before speech ends. Only3.55–3.95 father offers one tiny bite with LEFT hand; child starts gentle closed-mouth chewing, planted. Father withdraws LEFT hand toward box. Allow calm chewing thereafter and across next seam, no accelerated jaw, no speech or walking while chewing. Parents respond silently, without extra waving during prop work.",
  "dialogue": [
    {
      "id": "S05_L1",
      "speaker": "alice",
      "text": "Look! A panda.",
      "start": 1.0,
      "end": 2.99,
      "timing_status": "planned"
    },
    {
      "id": "S05_L2",
      "speaker": "alice",
      "text": "Panda. A hungry panda.",
      "start": 5.35,
      "end": 8.29,
      "timing_status": "planned"
    }
  ],
  "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
  "sfx": [
    {
      "at": 3.8,
      "event": "one soft bamboo crunch synchronized to the bite"
    },
    {
      "at": 8.75,
      "event": "Optional extremely soft banana contact only if visible; no crunchy bite or exaggerated chewing. Keep response pause otherwise quiet; no bamboo swish accent."
    }
  ],
  "subtitle": {
    "language": "en",
    "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
  },
  "repeat_cues": [
    {
      "start": 3.14,
      "end": 4.85,
      "text": "Your turn"
    },
    {
      "start": 8.44,
      "end": 9.85,
      "text": "Your turn"
    }
  ],
  "transition": {
    "intent": "Follow family gaze and travel direction into next story location; motivate any foreground occlusion through actual scene foliage.",
    "camera_continuity": "Carry screen direction, horizon, family spacing and eyelines through the cut; avoid a blanket preset wipe.",
    "duration": 0.3
  },
  "continuity": {
    "previous_scene_id": "S04",
    "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
    "theme": "Gentle English discovery and repetition with family at the zoo.",
    "action_continuation": "Complete current pointing or walking gesture before moving gaze to next discovery.",
    "entry_state": "Family stopped at visitor shelf beside bamboo recess; child planted between parents with BOTH hands free. Mother LEFT hand contacts cream bottle and RIGHT hand is free at sage cap; father RIGHT hand contacts cream snack box, LEFT hand free at lid. Full tiger hidden behind opaque divider, panda hidden behind bamboo wall return.",
    "exit_state": "Family remains planted at bamboo recess; toddler calmly chewing tiny bite with lips closed, both hands free. Mother LEFT hand holds capped bottle, RIGHT hand free. Father RIGHT hand holds snack box, LEFT hand withdraws from bite toward box. Panda remains visible; nearby garden arch is ahead."
  },
  "script_tracking": {
    "segment_summary": "First half: Start from exact shelf contacts with child hands free. First0–1s camera clears bamboo wall return to reveal panda, mother LEFT hand lifts bottle and father RIGHT hand lifts box. Tiger stays hidden. Toddler delivers exact1.00–2.99 line with modest LEFT head glance toward mother; feet/torso keep axis. Mother RIGHT hand unscrews and retains sage cap during words, quietly. Father LEFT hand opens box lid. Only3.25–4.35 mother supports one small sip using bottle in LEFT hand while cap remains RIGHT hand; child hands stay clear. After sip mouth clears rim; mother lowers bottle, keeping cap. Father holds open box, no food reaches mouth yet. Second half: Start after sip with empty mouth and child hands free. Mother LEFT hand supports bottle while RIGHT hand quietly recaps during0–1s; no accented click under speech. Toddler delivers exact hungry-panda line0.35–3.29 with modest LEFT head glance toward mother, torso/feet unchanged. Panda gently nibbles. Father RIGHT hand supports box; LEFT hand prepares tiny soft banana piece away from mouth before speech ends. Only3.55–3.95 father offers one tiny bite with LEFT hand; child starts gentle closed-mouth chewing, planted. Father withdraws LEFT hand toward box. Allow calm chewing thereafter and across next seam, no accelerated jaw, no speech or walking while chewing. Parents respond silently, without extra waving during prop work.",
    "dialogue_ids": [
      "S05_L1",
      "S05_L2"
    ],
    "status": "ready",
    "review_notes": "Future v8 proposal; source PCM immutable. Only S05_L2 placement changes. No current job edits. Rendering checks pending."
  },
  "subshots": [
    {
      "id": "S05_A",
      "start": 0,
      "duration": 5,
      "characters": [
        {
          "id": "alice",
          "name": "Alice",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Two-year-old toddler girl",
          "body_proportions": "Small round toddler torso, short limbs and oversized round head",
          "surface": "Warm peach skin, rosy round cheeks with two tiny white highlights",
          "eyes": "Very large dark-brown eyes, near-black pupils, white catchlights and short upper lashes",
          "brows": "Gently arched chestnut eyebrows",
          "nose_beak": "Tiny peach button nose",
          "mouth": "Small mouth, red-pink interior and rounded tongue; flexible speech phonemes",
          "ears": "Small rounded peach ears",
          "hair_head": "Chestnut short wavy bob, side-swept bangs, high side ponytail on anatomical RIGHT",
          "clothes": "Rose-pink A-line dress, short puff sleeves, white two-lobed Peter Pan collar, ONE centered white chest heart, lightly pleated skirt, thin white hem line",
          "footwear": "White frilly ankle socks; rose-pink lace-up sneakers with white laces, white rounded toe caps and white soles",
          "accessories": "One large rose-pink bow at anatomical RIGHT ponytail anchor; no other accessories",
          "marks_asymmetry": "Bow and ponytail on anatomical RIGHT, viewer LEFT in front view; no mirroring",
          "reference_assets": [
            {
              "role": "face_front",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical front-view identity; no assertion of unseen side views"
            },
            {
              "role": "wardrobe",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical puff sleeve dress and sneakers"
            },
            {
              "role": "accessories",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical anatomical right bow"
            },
            {
              "role": "gesture_only",
              "path": "assets/references/alice2.jpg",
              "status": "available",
              "scope": "Expression and gestures only; exclude alternative costumes"
            },
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "mother",
          "name": "Mother",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Adult woman approximately thirty years old",
          "body_proportions": "About twice Alice height, softly rounded adult proportions",
          "surface": "Warm light-peach skin, oval face, softly rounded cheeks",
          "eyes": "Almond dark-brown eyes with small white catchlights",
          "brows": "Gently arched brown eyebrows",
          "nose_beak": "Small rounded peach nose",
          "mouth": "Small curved mouth with flexible silent smiles",
          "ears": "Small rounded ears partly covered by hair",
          "hair_head": "Chestnut shoulder-length hair, left-side part, ends curled inward",
          "clothes": "Muted dusty-teal short-sleeved blouse, plain round neck, straight cream ankle-length trousers",
          "footwear": "Simple off-white flat shoes",
          "accessories": "No glasses, jewelry, hat or handbag",
          "marks_asymmetry": "Left-side hair part remains anatomical left; no distinctive facial marks",
          "reference_assets": [
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "father",
          "name": "Father",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Adult man approximately thirty-two years old",
          "body_proportions": "Adult softly broad shoulders, slightly taller than Mother",
          "surface": "Warm light-peach skin, softly rounded rectangular face, clean-shaven",
          "eyes": "Almond dark-brown eyes with small white catchlights",
          "brows": "Straight dark-brown eyebrows",
          "nose_beak": "Small broad rounded peach nose",
          "mouth": "Small curved mouth with flexible silent smiles",
          "ears": "Rounded ears visible beside short hair",
          "hair_head": "Short neat dark-chestnut hair with fixed anatomical left side part",
          "clothes": "Muted sage-green short-sleeved polo, small folded collar, two cream buttons; straight beige trousers",
          "footwear": "Simple brown low shoes with rounded toes",
          "accessories": "No glasses, facial hair, hat, watch or bag",
          "marks_asymmetry": "Clean-shaven face, fixed anatomical left hair part, no other distinctive marks",
          "reference_assets": [
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "panda",
          "name": "Panda",
          "entity": "Friendly preschool cartoon animal",
          "species": "Ailuropoda melanoleuca giant panda",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Round seated bear body, four broad paws, short tail",
          "surface": "Soft warm-white fur with black ears, limbs and shoulder band",
          "eyes": "Dark brown eyes inside stable rounded black eye patches",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Broad small black bear nose",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two rounded black fur-covered external ears",
          "hair_head": "Rounded white fur-covered head without human hair",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable black eye patches and shoulder band; natural paws, no extra markings",
          "reference_assets": []
        }
      ],
      "setting": "Same visitor shelf beside bamboo recess. Opaque pale-rock divider hides tiger for whole segment. Bamboo wall return hides seated panda initially, then small parallax reveals it behind secure rail. Bottle, cap and snack box remain continuously visible with parents.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Hold medium-wide three-quarter side view from same path-left shoulder, showing toddler face, mother supporting bottle, father with box and panda beyond rail. No camera move during sip. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Start from exact shelf contacts with child hands free. First0–1s camera clears bamboo wall return to reveal panda, mother LEFT hand lifts bottle and father RIGHT hand lifts box. Tiger stays hidden. Toddler delivers exact1.00–2.99 line with modest LEFT head glance toward mother; feet/torso keep axis. Mother RIGHT hand unscrews and retains sage cap during words, quietly. Father LEFT hand opens box lid. Only3.25–4.35 mother supports one small sip using bottle in LEFT hand while cap remains RIGHT hand; child hands stay clear. After sip mouth clears rim; mother lowers bottle, keeping cap. Father holds open box, no food reaches mouth yet.",
      "dialogue": [
        {
          "id": "S05_L1",
          "speaker": "alice",
          "text": "Look! A panda.",
          "start": 1.0,
          "end": 2.99,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 3.8,
          "event": "one soft bamboo crunch synchronized to the bite"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.14,
          "end": 4.85,
          "text": "Your turn"
        }
      ],
      "transition": {
        "intent": "Follow family gaze and travel direction into next story location; motivate any foreground occlusion through actual scene foliage.",
        "camera_continuity": "Carry screen direction, horizon, family spacing and eyelines through the cut; avoid a blanket preset wipe.",
        "duration": 0.3,
        "kind": "match_on_action"
      },
      "continuity": {
        "previous_scene_id": "S04",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family stopped at visitor shelf beside bamboo recess; child planted between parents with BOTH hands free. Mother LEFT hand contacts cream bottle and RIGHT hand is free at sage cap; father RIGHT hand contacts cream snack box, LEFT hand free at lid. Full tiger hidden behind opaque divider, panda hidden behind bamboo wall return.",
        "exit_state": "Same bamboo recess; toddler mouth clear of bottle after sip, both hands free. Mother LEFT hand holds lowered open cream bottle, RIGHT hand retains sage cap. Father RIGHT hand supports open cream snack box, LEFT hand free. Panda nibbles bamboo."
      },
      "script_tracking": {
        "segment_summary": "Start from exact shelf contacts with child hands free. First0–1s camera clears bamboo wall return to reveal panda, mother LEFT hand lifts bottle and father RIGHT hand lifts box. Tiger stays hidden. Toddler delivers exact1.00–2.99 line with modest LEFT head glance toward mother; feet/torso keep axis. Mother RIGHT hand unscrews and retains sage cap during words, quietly. Father LEFT hand opens box lid. Only3.25–4.35 mother supports one small sip using bottle in LEFT hand while cap remains RIGHT hand; child hands stay clear. After sip mouth clears rim; mother lowers bottle, keeping cap. Father holds open box, no food reaches mouth yet.",
        "dialogue_ids": [
          "S05_L1"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    },
    {
      "id": "S05_B",
      "start": 5,
      "duration": 5,
      "characters": [
        {
          "id": "alice",
          "name": "Alice",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Two-year-old toddler girl",
          "body_proportions": "Small round toddler torso, short limbs and oversized round head",
          "surface": "Warm peach skin, rosy round cheeks with two tiny white highlights",
          "eyes": "Very large dark-brown eyes, near-black pupils, white catchlights and short upper lashes",
          "brows": "Gently arched chestnut eyebrows",
          "nose_beak": "Tiny peach button nose",
          "mouth": "Small mouth, red-pink interior and rounded tongue; flexible speech phonemes",
          "ears": "Small rounded peach ears",
          "hair_head": "Chestnut short wavy bob, side-swept bangs, high side ponytail on anatomical RIGHT",
          "clothes": "Rose-pink A-line dress, short puff sleeves, white two-lobed Peter Pan collar, ONE centered white chest heart, lightly pleated skirt, thin white hem line",
          "footwear": "White frilly ankle socks; rose-pink lace-up sneakers with white laces, white rounded toe caps and white soles",
          "accessories": "One large rose-pink bow at anatomical RIGHT ponytail anchor; no other accessories",
          "marks_asymmetry": "Bow and ponytail on anatomical RIGHT, viewer LEFT in front view; no mirroring",
          "reference_assets": [
            {
              "role": "face_front",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical front-view identity; no assertion of unseen side views"
            },
            {
              "role": "wardrobe",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical puff sleeve dress and sneakers"
            },
            {
              "role": "accessories",
              "path": "assets/references/alice1.jpg",
              "status": "available",
              "scope": "Canonical anatomical right bow"
            },
            {
              "role": "gesture_only",
              "path": "assets/references/alice2.jpg",
              "status": "available",
              "scope": "Expression and gestures only; exclude alternative costumes"
            },
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "mother",
          "name": "Mother",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Adult woman approximately thirty years old",
          "body_proportions": "About twice Alice height, softly rounded adult proportions",
          "surface": "Warm light-peach skin, oval face, softly rounded cheeks",
          "eyes": "Almond dark-brown eyes with small white catchlights",
          "brows": "Gently arched brown eyebrows",
          "nose_beak": "Small rounded peach nose",
          "mouth": "Small curved mouth with flexible silent smiles",
          "ears": "Small rounded ears partly covered by hair",
          "hair_head": "Chestnut shoulder-length hair, left-side part, ends curled inward",
          "clothes": "Muted dusty-teal short-sleeved blouse, plain round neck, straight cream ankle-length trousers",
          "footwear": "Simple off-white flat shoes",
          "accessories": "No glasses, jewelry, hat or handbag",
          "marks_asymmetry": "Left-side hair part remains anatomical left; no distinctive facial marks",
          "reference_assets": [
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "father",
          "name": "Father",
          "entity": "Human preschool cartoon character",
          "species": "Homo sapiens human",
          "age": "Adult man approximately thirty-two years old",
          "body_proportions": "Adult softly broad shoulders, slightly taller than Mother",
          "surface": "Warm light-peach skin, softly rounded rectangular face, clean-shaven",
          "eyes": "Almond dark-brown eyes with small white catchlights",
          "brows": "Straight dark-brown eyebrows",
          "nose_beak": "Small broad rounded peach nose",
          "mouth": "Small curved mouth with flexible silent smiles",
          "ears": "Rounded ears visible beside short hair",
          "hair_head": "Short neat dark-chestnut hair with fixed anatomical left side part",
          "clothes": "Muted sage-green short-sleeved polo, small folded collar, two cream buttons; straight beige trousers",
          "footwear": "Simple brown low shoes with rounded toes",
          "accessories": "No glasses, facial hair, hat, watch or bag",
          "marks_asymmetry": "Clean-shaven face, fixed anatomical left hair part, no other distinctive marks",
          "reference_assets": [
            {
              "role": "family_lineup",
              "path": "assets/references/family-reference-higgsfield.png",
              "status": "available",
              "scope": "Historical shared Alice, Mother and Father lineup; inspect and approve for native H3 use before generation."
            }
          ]
        },
        {
          "id": "panda",
          "name": "Panda",
          "entity": "Friendly preschool cartoon animal",
          "species": "Ailuropoda melanoleuca giant panda",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Round seated bear body, four broad paws, short tail",
          "surface": "Soft warm-white fur with black ears, limbs and shoulder band",
          "eyes": "Dark brown eyes inside stable rounded black eye patches",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Broad small black bear nose",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two rounded black fur-covered external ears",
          "hair_head": "Rounded white fur-covered head without human hair",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable black eye patches and shoulder band; natural paws, no extra markings",
          "reference_assets": []
        }
      ],
      "setting": "Same bamboo recess and visitor shelf. Open cream bottle/sage cap remain with mother; open cream snack box and soft banana piece remain with father.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Locked calm medium-wide three-quarter view; mouth, offered bite and panda paws readable, both parents in frame. Same world/camera axis as A. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Start after sip with empty mouth and child hands free. Mother LEFT hand supports bottle while RIGHT hand quietly recaps during0–1s; no accented click under speech. Toddler delivers exact hungry-panda line0.35–3.29 with modest LEFT head glance toward mother, torso/feet unchanged. Panda gently nibbles. Father RIGHT hand supports box; LEFT hand prepares tiny soft banana piece away from mouth before speech ends. Only3.55–3.95 father offers one tiny bite with LEFT hand; child starts gentle closed-mouth chewing, planted. Father withdraws LEFT hand toward box. Allow calm chewing thereafter and across next seam, no accelerated jaw, no speech or walking while chewing. Parents respond silently, without extra waving during prop work.",
      "dialogue": [
        {
          "id": "S05_L2",
          "speaker": "alice",
          "text": "Panda. A hungry panda.",
          "start": 0.35,
          "end": 3.29,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 3.75,
          "event": "Optional extremely soft banana contact only if visible; no crunchy bite or exaggerated chewing. Keep response pause otherwise quiet; no bamboo swish accent."
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.44,
          "end": 4.85,
          "text": "Your turn"
        }
      ],
      "transition": {
        "intent": "Follow family gaze and travel direction into next story location; motivate any foreground occlusion through actual scene foliage.",
        "camera_continuity": "Carry screen direction, horizon, family spacing and eyelines through the cut; avoid a blanket preset wipe.",
        "duration": 0.3,
        "kind": "motivated_cut"
      },
      "continuity": {
        "previous_scene_id": "S04",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Same bamboo recess; toddler mouth clear of bottle after sip, both hands free. Mother LEFT hand holds lowered open cream bottle, RIGHT hand retains sage cap. Father RIGHT hand supports open cream snack box, LEFT hand free. Panda nibbles bamboo.",
        "exit_state": "Family remains planted at bamboo recess; toddler calmly chewing tiny bite with lips closed, both hands free. Mother LEFT hand holds capped bottle, RIGHT hand free. Father RIGHT hand holds snack box, LEFT hand withdraws from bite toward box. Panda remains visible; nearby garden arch is ahead."
      },
      "script_tracking": {
        "segment_summary": "Start after sip with empty mouth and child hands free. Mother LEFT hand supports bottle while RIGHT hand quietly recaps during0–1s; no accented click under speech. Toddler delivers exact hungry-panda line0.35–3.29 with modest LEFT head glance toward mother, torso/feet unchanged. Panda gently nibbles. Father RIGHT hand supports box; LEFT hand prepares tiny soft banana piece away from mouth before speech ends. Only3.55–3.95 father offers one tiny bite with LEFT hand; child starts gentle closed-mouth chewing, planted. Father withdraws LEFT hand toward box. Allow calm chewing thereafter and across next seam, no accelerated jaw, no speech or walking while chewing. Parents respond silently, without extra waving during prop work.",
        "dialogue_ids": [
          "S05_L2"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    }
  ]
}
```
