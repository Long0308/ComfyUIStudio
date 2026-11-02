# Scene 3 / S03 — kịch bản phim

Nguồn: production-request-v8.json. Chưa render; phân cảnh đã bổ sung góc nói với mẹ, trạng thái tay/đạo cụ và nối bối cảnh. Xem SOUND-PLAN.md cho thoại, nhạc, SFX và hậu kỳ.

```json
{
  "id": "S03",
  "start": 20,
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
      "id": "giraffe",
      "name": "Giraffe",
      "entity": "Friendly preschool cartoon animal",
      "species": "Giraffa camelopardalis giraffe",
      "age": "Healthy adult animal with gentle behavior",
      "body_proportions": "Tall long neck, small head, four long legs, two ossicones and one tufted tail",
      "surface": "Warm pale ochre coat with rounded caramel patches",
      "eyes": "Gentle large dark eyes with short lashes",
      "brows": "No separate human eyebrows; gentle expression through eyelids",
      "nose_beak": "Broad cream muzzle, two nostrils above mouth",
      "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
      "ears": "Two leaf-shaped ears beside short ossicones",
      "hair_head": "Short brown mane along back of neck and fur-covered head",
      "clothes": "No clothes; natural animal surface fully visible",
      "footwear": "No footwear; natural species-appropriate feet",
      "accessories": "No accessories, harness, jewelry or human props",
      "marks_asymmetry": "Stable caramel spot layout and dark tail tuft; no wardrobe or decorative marks",
      "reference_assets": []
    }
  ],
  "setting": "First half: Same willow trunk at rear edge fully hides bird; nearby meadow rail and grass ahead. Giraffe initially hidden by tall opaque divider return then revealed through real parallax. No bird reappears. Second half: Same giraffe meadow rail and feeding branch; tall opaque pale divider close to camera separates adjoining tiger bay. Tiger not visible in this segment.",
  "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
  "camera": "First half: Same path-left camera side; gentle continuous track reveals giraffe beside established tall opaque divider. Toddler left head glance toward mother provides partial profile, never right-facing torso rotation or reverse camera angle. Second half: Small upward tilt only to establish tall neck; keep parents and toddler in frame. Settle before words finish, then track one step along same side. End with pale rock divider entering far right. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
  "action": "First half: Carry inherited tall opaque divider return and hidden bird. A small continuous camera translation on path-left side clears the divider enough to reveal giraffe before local1s; do not pop it into view. Family stops, toddler points RIGHT/up, briefly notices giraffe, then speaks exact line with modest LEFT head glance toward mother. Feet/torso stay path-aligned. After speech eyes return to giraffe, which gently inclines its head. Second half: Start from inclined giraffe head. Giraffe slowly extends toward leaves during the exact guided line; tiny upward tilt keeps all family visible, then settles. After tall-giraffe line, lower pointing hand and take at most one small step along rail as camera tracks a short distance. A nearby tall pale divider wall progressively occludes the entire giraffe including neck and feet by used119. Wall covers only habitat sightline; family remains continuously visible. Tiger is still hidden beyond wall return, no tiger appearance here. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. During exact line maintain modest LEFT profile toward mother while pointing RIGHT/up; gaze may return to giraffe after words. Do not demand simultaneous eye contact with mother and giraffe.",
  "dialogue": [
    {
      "id": "S03_L1",
      "speaker": "alice",
      "text": "I see a giraffe.",
      "start": 1.0,
      "end": 3.04,
      "timing_status": "planned"
    },
    {
      "id": "S03_L2",
      "speaker": "alice",
      "text": "A tall giraffe!",
      "start": 6.0,
      "end": 8.21,
      "timing_status": "planned"
    }
  ],
  "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
  "sfx": [
    {
      "at": 0.4,
      "event": "quiet footstep stop"
    },
    {
      "at": 3.8,
      "event": "soft leaf rustle"
    },
    {
      "at": 9.6,
      "event": "gentle woody transition swish"
    }
  ],
  "subtitle": {
    "language": "en",
    "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
  },
  "repeat_cues": [
    {
      "start": 3.19,
      "end": 4.85,
      "text": "Your turn"
    },
    {
      "start": 8.36,
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
    "previous_scene_id": "S02",
    "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
    "theme": "Gentle English discovery and repetition with family at the zoo.",
    "action_continuation": "Complete current pointing or walking gesture before moving gaze to next discovery.",
    "entry_state": "Family beside willow trunk at adjacent meadow rail, toddler hand lowered; bird and entire perch hidden behind the willow trunk, meadow rail and grass visible ahead but giraffe hidden beyond tall opaque divider return; same camera side and hand contacts.",
    "exit_state": "Family at meadow/rock-divider boundary; full giraffe silhouette is hidden behind a tall pale enclosure-divider wall at used119, tiger bay floor visible ahead but tiger behind the wall return; same path-left camera side."
  },
  "script_tracking": {
    "segment_summary": "First half: Carry inherited tall opaque divider return and hidden bird. A small continuous camera translation on path-left side clears the divider enough to reveal giraffe before local1s; do not pop it into view. Family stops, toddler points RIGHT/up, briefly notices giraffe, then speaks exact line with modest LEFT head glance toward mother. Feet/torso stay path-aligned. After speech eyes return to giraffe, which gently inclines its head. Second half: Start from inclined giraffe head. Giraffe slowly extends toward leaves during the exact guided line; tiny upward tilt keeps all family visible, then settles. After tall-giraffe line, lower pointing hand and take at most one small step along rail as camera tracks a short distance. A nearby tall pale divider wall progressively occludes the entire giraffe including neck and feet by used119. Wall covers only habitat sightline; family remains continuously visible. Tiger is still hidden beyond wall return, no tiger appearance here. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. During exact line maintain modest LEFT profile toward mother while pointing RIGHT/up; gaze may return to giraffe after words. Do not demand simultaneous eye contact with mother and giraffe.",
    "dialogue_ids": [
      "S03_L1",
      "S03_L2"
    ],
    "status": "ready",
    "review_notes": "Future v8 proposal; source PCM immutable. Only S05_L2 placement changes. No current job edits. Rendering checks pending."
  },
  "subshots": [
    {
      "id": "S03_A",
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
          "id": "giraffe",
          "name": "Giraffe",
          "entity": "Friendly preschool cartoon animal",
          "species": "Giraffa camelopardalis giraffe",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Tall long neck, small head, four long legs, two ossicones and one tufted tail",
          "surface": "Warm pale ochre coat with rounded caramel patches",
          "eyes": "Gentle large dark eyes with short lashes",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Broad cream muzzle, two nostrils above mouth",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two leaf-shaped ears beside short ossicones",
          "hair_head": "Short brown mane along back of neck and fur-covered head",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable caramel spot layout and dark tail tuft; no wardrobe or decorative marks",
          "reference_assets": []
        }
      ],
      "setting": "Same willow trunk at rear edge fully hides bird; nearby meadow rail and grass ahead. Giraffe initially hidden by tall opaque divider return then revealed through real parallax. No bird reappears.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Same path-left camera side; gentle continuous track reveals giraffe beside established tall opaque divider. Toddler left head glance toward mother provides partial profile, never right-facing torso rotation or reverse camera angle.",
      "action": "Carry inherited tall opaque divider return and hidden bird. A small continuous camera translation on path-left side clears the divider enough to reveal giraffe before local1s; do not pop it into view. Family stops, toddler points RIGHT/up, briefly notices giraffe, then speaks exact line with modest LEFT head glance toward mother. Feet/torso stay path-aligned. After speech eyes return to giraffe, which gently inclines its head.",
      "dialogue": [
        {
          "id": "S03_L1",
          "speaker": "alice",
          "text": "I see a giraffe.",
          "start": 1.0,
          "end": 3.04,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 0.4,
          "event": "quiet footstep stop"
        },
        {
          "at": 3.8,
          "event": "soft leaf rustle"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.19,
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
        "previous_scene_id": "S02",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family beside willow trunk at adjacent meadow rail, toddler hand lowered; bird and entire perch hidden behind the willow trunk, meadow rail and grass visible ahead but giraffe hidden beyond tall opaque divider return; same camera side and hand contacts.",
        "exit_state": "Family planted at meadow rail looking up, toddler pointing right/up, giraffe head inclined; camera on original path-left side."
      },
      "script_tracking": {
        "segment_summary": "Carry inherited tall opaque divider return and hidden bird. A small continuous camera translation on path-left side clears the divider enough to reveal giraffe before local1s; do not pop it into view. Family stops, toddler points RIGHT/up, briefly notices giraffe, then speaks exact line with modest LEFT head glance toward mother. Feet/torso stay path-aligned. After speech eyes return to giraffe, which gently inclines its head.",
        "dialogue_ids": [
          "S03_L1"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    },
    {
      "id": "S03_B",
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
          "id": "giraffe",
          "name": "Giraffe",
          "entity": "Friendly preschool cartoon animal",
          "species": "Giraffa camelopardalis giraffe",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Tall long neck, small head, four long legs, two ossicones and one tufted tail",
          "surface": "Warm pale ochre coat with rounded caramel patches",
          "eyes": "Gentle large dark eyes with short lashes",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Broad cream muzzle, two nostrils above mouth",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two leaf-shaped ears beside short ossicones",
          "hair_head": "Short brown mane along back of neck and fur-covered head",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable caramel spot layout and dark tail tuft; no wardrobe or decorative marks",
          "reference_assets": []
        }
      ],
      "setting": "Same giraffe meadow rail and feeding branch; tall opaque pale divider close to camera separates adjoining tiger bay. Tiger not visible in this segment.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Small upward tilt only to establish tall neck; keep parents and toddler in frame. Settle before words finish, then track one step along same side. End with pale rock divider entering far right. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Start from inclined giraffe head. Giraffe slowly extends toward leaves during the exact guided line; tiny upward tilt keeps all family visible, then settles. After tall-giraffe line, lower pointing hand and take at most one small step along rail as camera tracks a short distance. A nearby tall pale divider wall progressively occludes the entire giraffe including neck and feet by used119. Wall covers only habitat sightline; family remains continuously visible. Tiger is still hidden beyond wall return, no tiger appearance here. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. During exact line maintain modest LEFT profile toward mother while pointing RIGHT/up; gaze may return to giraffe after words. Do not demand simultaneous eye contact with mother and giraffe.",
      "dialogue": [
        {
          "id": "S03_L2",
          "speaker": "alice",
          "text": "A tall giraffe!",
          "start": 1.0,
          "end": 3.21,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 4.6,
          "event": "gentle woody transition swish"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.36,
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
        "previous_scene_id": "S02",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family planted at meadow rail looking up, toddler pointing right/up, giraffe head inclined; camera on original path-left side.",
        "exit_state": "Family at meadow/rock-divider boundary; full giraffe silhouette is hidden behind a tall pale enclosure-divider wall at used119, tiger bay floor visible ahead but tiger behind the wall return; same path-left camera side."
      },
      "script_tracking": {
        "segment_summary": "Start from inclined giraffe head. Giraffe slowly extends toward leaves during the exact guided line; tiny upward tilt keeps all family visible, then settles. After tall-giraffe line, lower pointing hand and take at most one small step along rail as camera tracks a short distance. A nearby tall pale divider wall progressively occludes the entire giraffe including neck and feet by used119. Wall covers only habitat sightline; family remains continuously visible. Tiger is still hidden beyond wall return, no tiger appearance here. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. During exact line maintain modest LEFT profile toward mother while pointing RIGHT/up; gaze may return to giraffe after words. Do not demand simultaneous eye contact with mother and giraffe.",
        "dialogue_ids": [
          "S03_L2"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    }
  ]
}
```
