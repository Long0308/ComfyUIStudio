# FL2VA v12 prompt diagnosis — read-only

## Finding and confidence

The v12 outcome is a successful technical render and a rejected motion take. Root reviewed all120 editorial frames and reported parents beginning a frontal turn at5–13, toddler at13–20, a front close-up around30–68, then a rear view again around78–119. These ranges are the root's visual observations, not a new independent frame measurement. This note does not establish why the model chose that motion.

One controlled next experiment is justified: replace only the runtime literal prompt19 with a training-style prose projection of the same shot and every full physical character description. Remove operational/reference-sheet metadata from runtime text, retaining the complete immutable source JSON and all artifact provenance. This is one prompt-presentation/projection treatment, not a claim that JSON punctuation alone causes the problem.

## Measured local evidence

- Actual job: `17047713-25b5-4aae-9d64-754401b24b65`. Its saved `actual-queue.json` node19 equals the saved workflow literal exactly; queued-integrity confirms the required configured inputs as well. The earlier dynamic-prompt frontend corruption is not present in this job.
- Literal19: 13,280 Unicode characters,1,658 whitespace-separated words, SHA256 `18c29ac160135f449ce206bd90cff531d933f0a1c7a71f1e358f43d486868d27`.
- A local vocabulary-only `transformers.Qwen2Tokenizer` count gives3,038 text tokens, with the installed qwen25 vocabulary/merges plus H3 extra tokens. No encoder/checkpoint was loaded. This is a text-only tokenizer count, not a measured full multimodal embedding length or model attention trace.
- Action/camera/setting already precede the full JSON cast. Therefore merely moving an existing camera sentence to the front would not test the central remaining difference.
- Actual graph27 nodes: native FL2VA I2V6 receives first8 and last20, positive6:0 goes to10, joint AV6:1 goes to14, seed4341, res_multistep/simple20,864×480,124native frames. Editorial120 preserves incoming first image and original canonical Alice WAV7→58→56; full native AV15/16→17→18 stays separate. Last-image conditioning is at native123, not used119.

## Installed source evidence

1. `ComfyUI/comfy_extras/nodes_minimax_h3.py:116–162`: `MiniMaxH3ImageToVideo.execute` resizes first/last, passes their images with the literal prompt to `clip.tokenize(prompt, images=images)`, calls `clip.encode_from_tokens_scheduled(tokens)`, and adds encoded keyframes at0 and frame_count−1. It has no camera trajectory, enhancement, JSON interpretation, or negative-prompt socket. Two endpoint keyframes do not specify the entire intervening path.
2. `ComfyUI/comfy/text_encoders/minimax.py:1–18,106–118,148–202`: H3 uses raw non-chat-templated text and explicit image blocks, then unnormalized Qwen3-VL hidden states after LM layer50. In FL2VA the actual `<Picture1>`/`<Picture2>` vision blocks precede prompt text. `add_text` calls tokenization with `disable_weights=True`; multiple token batches raise an explicit length error. There is no prompt rewrite/generate call in this path. Layer50 truncation is transformer depth, not a finding that prompt words were truncated.
3. `ComfyUI/comfy/text_encoders/qwen3vl.py:147–152`: the inherited SDTokenizer uses `max_length=99999999`, no start/end tokens and no padding to max length. `sd1_clip.py:572–675` tokenizes/batches rather than silently dropping the tail. Source does not support a77-token CLIP cutoff diagnosis here. A tokenizer_data override could change limits in principle; no such override or truncation evidence was measured in this job. Successful execution alone is not an attention-quality guarantee.
4. `ComfyUI/comfy/model_base.py:2215–2266` preprocesses the cross-attention embeddings and carries keyframes/token tags into the H3 payload. `comfy/ldm/minimax/model.py:354–399,647–731` builds the packed layout and consumes the full context length. These inspected paths expose image/audio conditioning and sigma/augmentation internals, not an explicit camera-lock mechanism. No camera enhancer was found in the actual native I2V→TE→model path. This statement is limited to the inspected installed path, not every third-party node or future H3 version.
5. Saved official `video_minimax_h3_i2v.json` / `_continuation.json` provide prose and human-readable timeline prompting. They do not prove prose performs better on this family shot, but establish a legitimate comparison format. Do not copy the unrelated vaporwave scene or its four-step setting.

## Cause candidates, not proven causes

- **Competing semantics in administrative JSON.** Entire JSON is encoded as text, not executed as a schema. Current runtime includes reference_policy sheet instructions for turnaround front/left/right, expressions and run/jump/laugh/cry poses; historical front-face asset roles; library URLs; approval-status/scoping notes; and delivery/script metadata. Such tokens may compete with a single rear-following action. The source tells us these words are present in conditioning; it does not tell us their causal attention weight.
- **Identity detail versus view selection.** The mandatory full facial descriptions, the chest-heart design and frontal-reference wording may increase frontal-display pressure in a model with a character-presentation prior. Keep all anatomical/wardrobe values. In the proposed prose, explicitly distinguish permanent identity facts from currently visible rear surfaces. Do not delete eyes/nose/mouth to solve motion.
- **Endpoint-only motion remains underconstrained.** First and last are rear views but the model can still choose a front-facing excursion in between. There is no hard camera path in this graph. Shared seed/prompt priors could explain repeated detours, but this has not been separated from prompt semantics or model behavior.
- **Long/duplicated conditioning is plausible interference, not a truncation finding.** There are repeated action/setting constraints, negative phrases and nonvisual metadata. Source gives no evidence that hidden late text was cut off. “No turn” has no formal negative-control meaning in BasicGuider's positive-only conditioning.

## Exactly one next experiment

Create a new v13 artifact by changing only node19 data to the prose below, plus new output prefixes needed to preserve prior outputs. Keep every model/hash, FL2VA task, first/last PNG byte, literal STRING transport, seed4341, simple20, res_multistep, dimensions,124native/120editorial frames, canonical audio7, full native outputs, hard carry and all media/trim wiring unchanged. Do not add controls, change seed/steps, or synthesize/reclone/retime Alice in this test.

The original VIDEO JSON, full character registry and references remain immutable provenance. Runtime prose retains all15 physical fields per character exactly: entity, species, age, body_proportions, surface, eyes, brows, nose_beak, mouth, ears, hair_head, clothes, footwear, accessories, marks_asymmetry. Names label these complete descriptions only. Omit library URLs, reference-policy sheet-generation tasks, historical image paths, approval/source metadata and pipeline/timeline field names from runtime conditioning. Keep the intended setting, lighting and forward walk. Compare this whole projection treatment; a result cannot identify whether length, phrasing, JSON syntax or removed metadata was individually responsible.

### Proposed literal19 — plan only

```text
One continuous medium-wide rear-following shot in original preschool 2D animation. Soft restrained rose pink, dusty teal, sage, warm cream and pale sky blue; clean warm-dark-brown outlines, softly painted garden scenery. The camera follows the family from behind at a steady distance and height. The three backs remain visible throughout the shot; facial identity stays anatomically consistent even while the facial features are occluded by this rear view. Keep the full figures and grounded feet readable.

<Picture 1> is the starting family pose and gate-threshold layout. <Picture 2> is the intended final rear-facing garden arrangement. Mother stays screen-left, the two-year-old toddler stays in the middle, Father stays screen-right. Both parents maintain their existing hand contacts with the toddler. The family looks and walks toward the willow tree ahead. Their alternating legs, knees and elbows move independently; their bodies translate forward along the path, with subtle secondary hair and fabric motion.

From 0 to 2.5 seconds, follow their continuous forward stride through the open space between the cream gate pillars. The pillars move beside and behind the following camera as the family reaches the inner garden path. From 2.5 to 5 seconds, maintain the same rear-following composition and steady inward travel toward the willow, low wooden rails and restrained flower beds. The visible destination stays ahead; the outside plaza remains behind the following camera.

Character identity details below are anatomical and wardrobe facts; only the surfaces naturally visible in the continuous rear view appear on screen. Preserve every detail without changing the rear-facing performance.

Alice — Human preschool cartoon character; Homo sapiens human; Two-year-old toddler girl; Small round toddler torso, short limbs and oversized round head; Warm peach skin, rosy round cheeks with two tiny white highlights; Very large dark-brown eyes, near-black pupils, white catchlights and short upper lashes; Gently arched chestnut eyebrows; Tiny peach button nose; Small mouth, red-pink interior and rounded tongue; flexible speech phonemes; Small rounded peach ears; Chestnut short wavy bob, side-swept bangs, high side ponytail on anatomical RIGHT; Rose-pink A-line dress, short puff sleeves, white two-lobed Peter Pan collar, ONE centered white chest heart, lightly pleated skirt, thin white hem line; White frilly ankle socks; rose-pink lace-up sneakers with white laces, white rounded toe caps and white soles; One large rose-pink bow at anatomical RIGHT ponytail anchor; no other accessories; Bow and ponytail on anatomical RIGHT, viewer LEFT in front view; no mirroring.

Mother — Human preschool cartoon character; Homo sapiens human; Adult woman approximately thirty years old; About twice Alice height, softly rounded adult proportions; Warm light-peach skin, oval face, softly rounded cheeks; Almond dark-brown eyes with small white catchlights; Gently arched brown eyebrows; Small rounded peach nose; Small curved mouth with flexible silent smiles; Small rounded ears partly covered by hair; Chestnut shoulder-length hair, left-side part, ends curled inward; Muted dusty-teal short-sleeved blouse, plain round neck, straight cream ankle-length trousers; Simple off-white flat shoes; No glasses, jewelry, hat or handbag; Left-side hair part remains anatomical left; no distinctive facial marks.

Father — Human preschool cartoon character; Homo sapiens human; Adult man approximately thirty-two years old; Adult softly broad shoulders, slightly taller than Mother; Warm light-peach skin, softly rounded rectangular face, clean-shaven; Almond dark-brown eyes with small white catchlights; Straight dark-brown eyebrows; Small broad rounded peach nose; Small curved mouth with flexible silent smiles; Rounded ears visible beside short hair; Short neat dark-chestnut hair with fixed anatomical left side part; Muted sage-green short-sleeved polo, small folded collar, two cream buttons; straight beige trousers; Simple brown low shoes with rounded toes; No glasses, facial hair, hat, watch or bag; Clean-shaven face, fixed anatomical left hair part, no other distinctive marks.

Soft warm morning daylight; broad key from upper screen-left, gentle cream bounce fill, no hard rim or colored neon light. Stable white balance and exposure on peach skin and muted rose/dusty-teal/sage clothes; pale sky and restrained greens. Same light direction across cuts.

Quiet garden ambience and very soft foliage swish. The family continues the quiet, nonverbal walk.
```

### Review and stopping rule

Before Run, assert every original value in the15 listed physical fields for all3 cast members occurs verbatim in proposed19; verify the source character JSON bytes and canonical Alice bytes remain unchanged. A graph diff must show only19 and versioned output prefixes changed. Inspect actual queued19 SHA after visible Run.

Review every editorial frame0–119 at normal speed and consecutive frame windows, especially5–20,30–68 and78–119. Pass requires continuous rear-facing forward translation, stable rear medium-wide camera, grounded motion, intact hands/identity, correct doorway crossing and no front close-up. Also check lighting/pulses and the actual used119 boundary. Report first offending frame if rejected. Only if the picture passes should accepted canonical Alice be heard with the picture; this experiment does not assess or replace her timbre.

If v13 also detours, record failure without claiming this JSON hypothesis proven. Keep both complete native takes and the source for further diagnosis; do not silently change several sampling/control variables in the same comparison.

## Scope

Only this diagnostic note was written. No workflow/source/config/media edits, queue calls, GPU operations, encoder/model loads or renders were performed. Vocabulary tokenization used local files only. Proposed motion text is a creative test, not measured output or a production acceptance claim.
