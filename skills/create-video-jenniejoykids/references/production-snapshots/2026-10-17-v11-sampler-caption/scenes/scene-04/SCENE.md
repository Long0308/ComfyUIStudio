# Scene 4 / S04 — kịch bản phim

Nguồn production-request-v9.json, SHA2563dd21650d1a9c3ab247a2aaf1748672c38d80619aa7676ed4aadecbef7ccb643. Chưa có phân cảnh mới đạt hình. Scene1enginev9 đang chạy từ sourcev8; Scene1 giữ nguyên. Chuyển động, nối cảnh và góc nói phải xem render thực tế.

| Master giây | English dialogue |
| --- | --- |
| 31.00–33.12 | Hello, little tiger! |
| 36.00–38.72 | Tiger. Hello, tiger! |

Xem SOUND-PLAN.md cho nhạc, không gian, bước chân, con vật và đồ vật. Full cast và toàn bộ action/camera bên dưới luôn được giữ trong prompt.

```json
{
  "id": "S04",
  "start": 30,
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
      "id": "tiger",
      "name": "Tiger",
      "entity": "Friendly preschool cartoon animal",
      "species": "Panthera tigris tiger",
      "age": "Healthy adult animal with gentle behavior",
      "body_proportions": "Rounded strong feline body, four padded paws and one long tail",
      "surface": "Muted warm-orange fur, cream muzzle and belly, dark brown stripes",
      "eyes": "Round amber eyes with dark pupils and soft catchlights",
      "brows": "No separate human eyebrows; gentle expression through eyelids",
      "nose_beak": "Small pink triangular feline nose",
      "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
      "ears": "Two rounded dark-backed ears with pale interior",
      "hair_head": "Fur-covered rounded head, short cream cheek ruff",
      "clothes": "No clothes; natural animal surface fully visible",
      "footwear": "No footwear; natural species-appropriate feet",
      "accessories": "No accessories, harness, jewelry or human props",
      "marks_asymmetry": "Stable dark stripes across torso and tail; no extra limbs or decorative marks",
      "reference_assets": []
    }
  ],
  "setting": "First half: Same tall pale divider fully hides giraffe. Its return initially hides tiger until small continuous camera translation reveals secure tiger bay. No giraffe visible. Visitor shelf and bamboo wall edge can appear in distance, panda fully hidden. Second half: Same tiger bay and opaque pale-rock divider. Visitor shelf already within parent arm reach holds matte cream bottle with sage cap and cream snack box with peeled soft banana piece, no logos. Bamboo wall return hides panda entirely.",
  "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
  "camera": "First half: Track minimally along original path-left shoulder; compose family in readable three-quarter side view and tiger beyond rail, maintaining geography established at previous seam. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face. Second half: Small tracking move along same path side after line. Reveal shelf and bamboo by real parallax; all parents and child stay visible. No wipe or full-frame foliage concealment. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
  "action": "First half: Start from identical divider-wall frame. Continue same small camera translation to reveal tiger beyond the wall return before local1s; giraffe remains completely occluded behind wall. Family settles at rail, toddler makes one small friendly wave during the exact guided line. Tiger completes one slow lateral step and plants all paws. Alice uses natural profile mouth phonemes only during the supplied original guide line; keep torso/feet in their declared direction, no frontal reset. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. Second half: Continue gentle toddler wave during the exact guided line; tiger makes small paw adjustment and relaxed tail flick. Parents already stand beside reachable visitor shelf; hands reach only after words. After exact tiger line, parents make the already-prepared short reach toward shelf; camera slides only enough that solid pale-rock divider fully occludes tiger by used119. Bamboo bay edge and visitor shelf stay visible but panda remains hidden by wall return until next segment. Family never passes through divider or animal barrier. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. After speech and while child stands planted between both parents, explicitly release toddler LEFT hand from mother. Father hand has remained free since Scene2. Mother uses LEFT hand to contact bottle body and RIGHT hand prepares cap grip. Father RIGHT hand contacts snack box base; LEFT hand prepares lid. No child handholding during two-handed prop actions.",
  "dialogue": [
    {
      "id": "S04_L1",
      "speaker": "alice",
      "text": "Hello, little tiger!",
      "start": 1.0,
      "end": 3.12,
      "timing_status": "planned"
    },
    {
      "id": "S04_L2",
      "speaker": "alice",
      "text": "Tiger. Hello, tiger!",
      "start": 6.0,
      "end": 8.72,
      "timing_status": "planned"
    }
  ],
  "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
  "sfx": [
    {
      "at": 3.5,
      "event": "very soft breathy tiger chuff, never a loud roar"
    },
    {
      "at": 7.6,
      "event": "faint grass rustle"
    },
    {
      "at": 9.6,
      "event": "quiet foliage swish"
    }
  ],
  "subtitle": {
    "language": "en",
    "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
  },
  "repeat_cues": [
    {
      "start": 3.27,
      "end": 4.85,
      "text": "Your turn"
    },
    {
      "start": 8.87,
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
    "previous_scene_id": "S03",
    "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
    "theme": "Gentle English discovery and repetition with family at the zoo.",
    "action_continuation": "Complete current pointing or walking gesture before moving gaze to next discovery.",
    "entry_state": "Family at meadow/rock-divider boundary; full giraffe silhouette is hidden behind a tall pale enclosure-divider wall at used119, tiger bay floor visible ahead but tiger behind the wall return; same path-left camera side.",
    "exit_state": "Family stopped at visitor shelf beside bamboo recess; child planted between parents with BOTH hands free. Mother LEFT hand contacts cream bottle and RIGHT hand is free at sage cap; father RIGHT hand contacts cream snack box, LEFT hand free at lid. Full tiger hidden behind opaque divider, panda hidden behind bamboo wall return."
  },
  "script_tracking": {
    "segment_summary": "First half: Start from identical divider-wall frame. Continue same small camera translation to reveal tiger beyond the wall return before local1s; giraffe remains completely occluded behind wall. Family settles at rail, toddler makes one small friendly wave during the exact guided line. Tiger completes one slow lateral step and plants all paws. Alice uses natural profile mouth phonemes only during the supplied original guide line; keep torso/feet in their declared direction, no frontal reset. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. Second half: Continue gentle toddler wave during the exact guided line; tiger makes small paw adjustment and relaxed tail flick. Parents already stand beside reachable visitor shelf; hands reach only after words. After exact tiger line, parents make the already-prepared short reach toward shelf; camera slides only enough that solid pale-rock divider fully occludes tiger by used119. Bamboo bay edge and visitor shelf stay visible but panda remains hidden by wall return until next segment. Family never passes through divider or animal barrier. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. After speech and while child stands planted between both parents, explicitly release toddler LEFT hand from mother. Father hand has remained free since Scene2. Mother uses LEFT hand to contact bottle body and RIGHT hand prepares cap grip. Father RIGHT hand contacts snack box base; LEFT hand prepares lid. No child handholding during two-handed prop actions.",
    "dialogue_ids": [
      "S04_L1",
      "S04_L2"
    ],
    "status": "ready",
    "review_notes": "Future v8 proposal; source PCM immutable. Only S05_L2 placement changes. No current job edits. Rendering checks pending."
  },
  "subshots": [
    {
      "id": "S04_A",
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
          "id": "tiger",
          "name": "Tiger",
          "entity": "Friendly preschool cartoon animal",
          "species": "Panthera tigris tiger",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Rounded strong feline body, four padded paws and one long tail",
          "surface": "Muted warm-orange fur, cream muzzle and belly, dark brown stripes",
          "eyes": "Round amber eyes with dark pupils and soft catchlights",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Small pink triangular feline nose",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two rounded dark-backed ears with pale interior",
          "hair_head": "Fur-covered rounded head, short cream cheek ruff",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable dark stripes across torso and tail; no extra limbs or decorative marks",
          "reference_assets": []
        }
      ],
      "setting": "Same tall pale divider fully hides giraffe. Its return initially hides tiger until small continuous camera translation reveals secure tiger bay. No giraffe visible. Visitor shelf and bamboo wall edge can appear in distance, panda fully hidden.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Track minimally along original path-left shoulder; compose family in readable three-quarter side view and tiger beyond rail, maintaining geography established at previous seam. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Start from identical divider-wall frame. Continue same small camera translation to reveal tiger beyond the wall return before local1s; giraffe remains completely occluded behind wall. Family settles at rail, toddler makes one small friendly wave during the exact guided line. Tiger completes one slow lateral step and plants all paws. Alice uses natural profile mouth phonemes only during the supplied original guide line; keep torso/feet in their declared direction, no frontal reset. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
      "dialogue": [
        {
          "id": "S04_L1",
          "speaker": "alice",
          "text": "Hello, little tiger!",
          "start": 1.0,
          "end": 3.12,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 3.5,
          "event": "very soft breathy tiger chuff, never a loud roar"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.27,
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
        "previous_scene_id": "S03",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family at meadow/rock-divider boundary; full giraffe silhouette is hidden behind a tall pale enclosure-divider wall at used119, tiger bay floor visible ahead but tiger behind the wall return; same path-left camera side.",
        "exit_state": "Family planted at tiger rail beside visitor refreshment shelf, toddler wave half lowered, tiger planted facing visitors; bamboo bay wall edge ahead fully hides panda."
      },
      "script_tracking": {
        "segment_summary": "Start from identical divider-wall frame. Continue same small camera translation to reveal tiger beyond the wall return before local1s; giraffe remains completely occluded behind wall. Family settles at rail, toddler makes one small friendly wave during the exact guided line. Tiger completes one slow lateral step and plants all paws. Alice uses natural profile mouth phonemes only during the supplied original guide line; keep torso/feet in their declared direction, no frontal reset. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees.",
        "dialogue_ids": [
          "S04_L1"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    },
    {
      "id": "S04_B",
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
          "id": "tiger",
          "name": "Tiger",
          "entity": "Friendly preschool cartoon animal",
          "species": "Panthera tigris tiger",
          "age": "Healthy adult animal with gentle behavior",
          "body_proportions": "Rounded strong feline body, four padded paws and one long tail",
          "surface": "Muted warm-orange fur, cream muzzle and belly, dark brown stripes",
          "eyes": "Round amber eyes with dark pupils and soft catchlights",
          "brows": "No separate human eyebrows; gentle expression through eyelids",
          "nose_beak": "Small pink triangular feline nose",
          "mouth": "Species-appropriate mouth with rounded interior; natural silent movement",
          "ears": "Two rounded dark-backed ears with pale interior",
          "hair_head": "Fur-covered rounded head, short cream cheek ruff",
          "clothes": "No clothes; natural animal surface fully visible",
          "footwear": "No footwear; natural species-appropriate feet",
          "accessories": "No accessories, harness, jewelry or human props",
          "marks_asymmetry": "Stable dark stripes across torso and tail; no extra limbs or decorative marks",
          "reference_assets": []
        }
      ],
      "setting": "Same tiger bay and opaque pale-rock divider. Visitor shelf already within parent arm reach holds matte cream bottle with sage cap and cream snack box with peeled soft banana piece, no logos. Bamboo wall return hides panda entirely.",
      "lighting": "Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.",
      "camera": "Small tracking move along same path side after line. Reveal shelf and bamboo by real parallax; all parents and child stay visible. No wipe or full-frame foliage concealment. Preserve the path-left camera side. Face visibility comes from a modest LEFT head turn toward mother, not from turning the torso away from the travel axis; never force full frontal face.",
      "action": "Continue gentle toddler wave during the exact guided line; tiger makes small paw adjustment and relaxed tail flick. Parents already stand beside reachable visitor shelf; hands reach only after words. After exact tiger line, parents make the already-prepared short reach toward shelf; camera slides only enough that solid pale-rock divider fully occludes tiger by used119. Bamboo bay edge and visitor shelf stay visible but panda remains hidden by wall return until next segment. Family never passes through divider or animal barrier. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. After speech and while child stands planted between both parents, explicitly release toddler LEFT hand from mother. Father hand has remained free since Scene2. Mother uses LEFT hand to contact bottle body and RIGHT hand prepares cap grip. Father RIGHT hand contacts snack box base; LEFT hand prepares lid. No child handholding during two-handed prop actions.",
      "dialogue": [
        {
          "id": "S04_L2",
          "speaker": "alice",
          "text": "Tiger. Hello, tiger!",
          "start": 1.0,
          "end": 3.72,
          "timing_status": "planned"
        }
      ],
      "music": "Gentle cheerful original pentatonic plucked/marimba-style instrumental, no lyrics, quiet underneath canonical Alice, duck smoothly during all words, stable modest level through transitions.",
      "sfx": [
        {
          "at": 2.5999999999999996,
          "event": "faint grass rustle"
        },
        {
          "at": 4.6,
          "event": "quiet foliage swish"
        }
      ],
      "subtitle": {
        "language": "en",
        "style": "Exact English words, large rounded white type on restrained dark-teal band, lower 18 percent safe."
      },
      "repeat_cues": [
        {
          "start": 3.87,
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
        "previous_scene_id": "S03",
        "setting_layout": "Family together on path or rail; Alice central, Mother left and Father right; animal habitat beyond safe barrier.",
        "theme": "Gentle English discovery and repetition with family at the zoo.",
        "action_continuation": "Use predecessor actual used frame119 as this clip frame0; carry camera, gait, anatomy, environment and props. Proposed exit is a target, not evidence of achieved render.",
        "entry_state": "Family planted at tiger rail beside visitor refreshment shelf, toddler wave half lowered, tiger planted facing visitors; bamboo bay wall edge ahead fully hides panda.",
        "exit_state": "Family stopped at visitor shelf beside bamboo recess; child planted between parents with BOTH hands free. Mother LEFT hand contacts cream bottle and RIGHT hand is free at sage cap; father RIGHT hand contacts cream snack box, LEFT hand free at lid. Full tiger hidden behind opaque divider, panda hidden behind bamboo wall return."
      },
      "script_tracking": {
        "segment_summary": "Continue gentle toddler wave during the exact guided line; tiger makes small paw adjustment and relaxed tail flick. Parents already stand beside reachable visitor shelf; hands reach only after words. After exact tiger line, parents make the already-prepared short reach toward shelf; camera slides only enough that solid pale-rock divider fully occludes tiger by used119. Bamboo bay edge and visitor shelf stay visible but panda remains hidden by wall return until next segment. Family never passes through divider or animal barrier. Speech mouth motion follows only the exact guide. Torso and feet keep path direction; a small LEFT head turn addresses mother while the right pointing arm may still indicate the animal. Parents answer with one silent nod or smile. No swing between multiple addressees. After speech and while child stands planted between both parents, explicitly release toddler LEFT hand from mother. Father hand has remained free since Scene2. Mother uses LEFT hand to contact bottle body and RIGHT hand prepares cap grip. Father RIGHT hand contacts snack box base; LEFT hand prepares lid. No child handholding during two-handed prop actions.",
        "dialogue_ids": [
          "S04_L2"
        ],
        "status": "ready",
        "review_notes": "Future v8 proposal; exact source words. S05_L2 retimed without PCM alteration; guide/canonical timeline rebuild REQUIRED before Scene5 submission. Actual mouth readiness, hands, camera and occlusion remain unverified."
      }
    }
  ]
}
```
