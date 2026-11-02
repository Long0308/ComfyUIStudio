# Scene 2 / S02 — kịch bản phim

Nguồn: production-request-v8.json. Chưa render; phân cảnh đã bổ sung góc nói với mẹ, trạng thái tay/đạo cụ và nối bối cảnh. Xem SOUND-PLAN.md cho thoại, nhạc, SFX và hậu kỳ.

```json
{
  "id": "S02",
  "start": 10,
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
      "id": "bird",
      "name": "Bird",
      "entity": "Friendly preschool cartoon animal",
      "species": "Small songbird",
      "age": "Healthy adult animal with gentle behavior",
      "body_proportions": "Small rounded body, two wings, two slender legs and short tail",
      "surface": "Muted-blue plumage, warm-cream belly",
      "eyes": "Round dark eyes with tiny white catchlights",
      "brows": "No separate human eyebrows; gentle expression through eyelids",
      "nose_beak": "Tiny ochre beak with two halves",
      "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
      "ears": "Small ear openings covered by feathers; no external pinnae",
      "hair_head": "Rounded feathered head, no human hair",
      "clothes": "No clothes; natural animal surface fully visible",
      "footwear": "No footwear; natural species-appropriate feet",
      "accessories": "No accessories, harness, jewelry or human props",
      "marks_asymmetry": "Cream belly bounded consistently; blue wings and tail; no asymmetrical marks",
      "reference_assets": []
    }
  ],
  "setting": "First half: Inside garden path approaches willow on camera-right; low branch just beyond the family. Gate remains behind the camera. Second half: Same willow branch and tree. Adjacent empty meadow edge and tall opaque divider return ahead. Bird remains visible until physically occluded by opaque trunk; no giraffe appears. Tall opaque divider return beside meadow is already visible here and geometrically covers the whole giraffe silhouette; a thin rail post cannot do so.",
  "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
  "camera": "First half: Rear-left follow slows with family; remain on path-left shoulder. Modest LEFT head glance toward mother may expose left profile. Do not require a frontal face or right cheek; keep parents and toddler visible. Second half: Hold the same left-shoulder camera through speech; track the last forward step on the same side. Do not swing to a new frontal view. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
  "action": "First half: Continue incoming forward stride and stop beneath willow. Toddler notices bird to the right with eyes/head, gently releases RIGHT hand from father and points with that free hand. LEFT hand stays with mother. Feet and torso stay aligned with path. During exact line1.00–3.47 turn head modestly LEFT toward mother, exposing a left partial profile to the rear-left camera; mother watches child then bird. After line look toward bird, without a body pivot or backward step. Second half: Hold original pointing pose through the exact guided spoken line. Bird makes one small hop only after speech; toddler lowers free hand, mother retains other hand. After the bird line, track the family one short step along the path. The solid willow trunk crosses ONLY the small bird/perch sightline through parallax; bird is fully hidden by used119 while the family remains visible. Show empty meadow edge ahead, never reveal giraffe in this segment. Do not obscure the full screen. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
  "dialogue": [
    {
      "id": "S02_L1",
      "speaker": "alice",
      "text": "Look! A little bird.",
      "start": 1.0,
      "end": 3.47,
      "timing_status": "planned"
    },
    {
      "id": "S02_L2",
      "speaker": "alice",
      "text": "Bird. A little bird.",
      "start": 6.0,
      "end": 8.63,
      "timing_status": "planned"
    }
  ],
  "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
  "sfx": [
    {
      "at": 0.45,
      "event": "one soft bird chirp"
    },
    {
      "at": 3.8,
      "event": "tiny branch tap at bird landing"
    },
    {
      "at": 7.7,
      "event": "quiet feather flutter"
    },
    {
      "at": 9.6,
      "event": "soft leaf swish"
    }
  ],
  "subtitle": {
    "language": "en",
    "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
  },
  "repeat_cues": [
    {
      "start": 3.62,
      "end": 4.85,
      "text": "Your turn"
    },
    {
      "start": 8.78,
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
    "previous_scene_id": "S01",
    "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
    "theme": "Gentle English discovery and repetition with family at the zoo.",
    "action_continuation": "Complete current pointing or walking gesture before moving gaze to next discovery.",
    "entry_state": "Family entirely inside on garden path, still facing forward away from same following camera; gate behind, willow tree ahead, hands connected",
    "exit_state": "Family beside willow trunk at adjacent meadow rail, toddler hand lowered; bird and entire perch hidden behind the willow trunk, meadow rail and grass visible ahead but giraffe hidden beyond tall opaque divider return; same camera side and hand contacts."
  },
  "script_tracking": {
    "segment_summary": "First half: Continue incoming forward stride and stop beneath willow. Toddler notices bird to the right with eyes/head, gently releases RIGHT hand from father and points with that free hand. LEFT hand stays with mother. Feet and torso stay aligned with path. During exact line1.00–3.47 turn head modestly LEFT toward mother, exposing a left partial profile to the rear-left camera; mother watches child then bird. After line look toward bird, without a body pivot or backward step. Second half: Hold original pointing pose through the exact guided spoken line. Bird makes one small hop only after speech; toddler lowers free hand, mother retains other hand. After the bird line, track the family one short step along the path. The solid willow trunk crosses ONLY the small bird/perch sightline through parallax; bird is fully hidden by used119 while the family remains visible. Show empty meadow edge ahead, never reveal giraffe in this segment. Do not obscure the full screen. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
    "dialogue_ids": [
      "S02_L1",
      "S02_L2"
    ],
    "status": "ready",
    "review_notes": "Future v8 proposal; source PCM immutable. Only S05_L2 placement changes. No current job edits. Rendering checks pending."
  },
  "subshots": [
    {
      "id": "S02_A",
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
          "id": "bird",
          "name": "Bird",
          "entity": "Friendly preschool cartoon animal",
          "species": "Small songbird",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Small rounded body, two wings, two slender legs and short tail",
          "surface": "Muted-blue plumage, warm-cream belly",
          "eyes": "Round dark eyes with tiny white catchlights",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Tiny ochre beak with two halves",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Small ear openings covered by feathers; no external pinnae",
          "hair_head": "Rounded feathered head, no human hair",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Cream belly bounded consistently; blue wings and tail; no asymmetrical marks",
          "reference_assets": []
        }
      ],
      "setting": "Inside garden path approaches willow on camera-right; low branch just beyond the family. Gate remains behind the camera.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Rear-left follow slows with family; remain on path-left shoulder. Modest LEFT head glance toward mother may expose left profile. Do not require a frontal face or right cheek; keep parents and toddler visible.",
      "action": "Continue incoming forward stride and stop beneath willow. Toddler notices bird to the right with eyes/head, gently releases RIGHT hand from father and points with that free hand. LEFT hand stays with mother. Feet and torso stay aligned with path. During exact line1.00–3.47 turn head modestly LEFT toward mother, exposing a left partial profile to the rear-left camera; mother watches child then bird. After line look toward bird, without a body pivot or backward step.",
      "dialogue": [
        {
          "id": "S02_L1",
          "speaker": "alice",
          "text": "Look! A little bird.",
          "start": 1.0,
          "end": 3.47,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 0.45,
          "event": "one soft bird chirp"
        },
        {
          "at": 3.8,
          "event": "tiny branch tap at bird landing"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.62,
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
        "previous_scene_id": "S01",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family entirely inside on garden path, still facing forward away from same following camera; gate behind, willow tree ahead, hands connected",
        "exit_state": "Family stopped below willow, toddler right hand pointing up, left hand with mother; left partial profile toward mother readable."
      },
      "script_tracking": {
        "segment_summary": "Continue incoming forward stride and stop beneath willow. Toddler notices bird to the right with eyes/head, gently releases RIGHT hand from father and points with that free hand. LEFT hand stays with mother. Feet and torso stay aligned with path. During exact line1.00–3.47 turn head modestly LEFT toward mother, exposing a left partial profile to the rear-left camera; mother watches child then bird. After line look toward bird, without a body pivot or backward step.",
        "dialogue_ids": [
          "S02_L1"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    },
    {
      "id": "S02_B",
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
          "id": "bird",
          "name": "Bird",
          "entity": "Friendly preschool cartoon animal",
          "species": "Small songbird",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Small rounded body, two wings, two slender legs and short tail",
          "surface": "Muted-blue plumage, warm-cream belly",
          "eyes": "Round dark eyes with tiny white catchlights",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Tiny ochre beak with two halves",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Small ear openings covered by feathers; no external pinnae",
          "hair_head": "Rounded feathered head, no human hair",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Cream belly bounded consistently; blue wings and tail; no asymmetrical marks",
          "reference_assets": []
        }
      ],
      "setting": "Same willow branch and tree. Adjacent empty meadow edge and tall opaque divider return ahead. Bird remains visible until physically occluded by opaque trunk; no giraffe appears. Tall opaque divider return beside meadow is already visible here and geometrically covers the whole giraffe silhouette; a thin rail post cannot do so.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Hold the same left-shoulder camera through speech; track the last forward step on the same side. Do not swing to a new frontal view. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Hold original pointing pose through the exact guided spoken line. Bird makes one small hop only after speech; toddler lowers free hand, mother retains other hand. After the bird line, track the family one short step along the path. The solid willow trunk crosses ONLY the small bird/perch sightline through parallax; bird is fully hidden by used119 while the family remains visible. Show empty meadow edge ahead, never reveal giraffe in this segment. Do not obscure the full screen. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
      "dialogue": [
        {
          "id": "S02_L2",
          "speaker": "alice",
          "text": "Bird. A little bird.",
          "start": 1.0,
          "end": 3.63,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 2.7,
          "event": "quiet feather flutter"
        },
        {
          "at": 4.6,
          "event": "soft leaf swish"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.78,
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
        "previous_scene_id": "S01",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family stopped below willow, toddler right hand pointing up, left hand with mother; left partial profile toward mother readable.",
        "exit_state": "Family beside willow trunk at adjacent meadow rail, toddler hand lowered; bird and entire perch hidden behind the willow trunk, meadow rail and grass visible ahead but giraffe hidden beyond tall opaque divider return; same camera side and hand contacts."
      },
      "script_tracking": {
        "segment_summary": "Hold original pointing pose through the exact guided spoken line. Bird makes one small hop only after speech; toddler lowers free hand, mother retains other hand. After the bird line, track the family one short step along the path. The solid willow trunk crosses ONLY the small bird/perch sightline through parallax; bird is fully hidden by used119 while the family remains visible. Show empty meadow edge ahead, never reveal giraffe in this segment. Do not obscure the full screen. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
        "dialogue_ids": [
          "S02_L2"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    }
  ]
}
```
