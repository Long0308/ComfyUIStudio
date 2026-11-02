---
name: jenniejoy-hyperframes
description: "Create or validate JennieJoy Studio HyperFrames graphics and labelled film benchmarks, preserving the standalone component contract with the Remotion Master."
---

Use [production hub](../jenniejoy-production-system/SKILL.md) for overall status, then this skill for motion graphics and visual component engineering under the common [engine dispatch contract](../create-video-jenniejoykids/references/engine-dispatch-contract.md). User authorization to render remains valid; do not add unnecessary approval gates for requested graphics.

## Explicit subskill contract

- **Input Trigger:** Locked screenplay, title art, target vocabulary list (12 terms for *Milk and Mom*), and verified character/brand design assets.
- **Responsible Owner:** The live root/agent ID recorded in the film PLAN, using the `jenniejoy-hyperframes` capability route on port 4040 and local CLI. The skill name is not an agent ID.
- **Concrete Output:** Rendered seek-safe component videos with transparent alpha channel where required, accompanied by exact duration/FPS specifications, SHA256 hashes, and timing manifests.
- **Downstream Result Consumer:** Remotion compositor (`jenniejoy-remotion`), which places components on the delivery timeline at exact frame boundaries.

HyperFrames components run independently on CPU/GPU without holding up video generation. Scaffolding for intros, outros, and keyword cards proceeds concurrently while storyboard images and H3 motion clips are rendered.

## Timeline contract & component specifications

> **Superseding user rules (2026-10-27, ep04 review v012→v014) — these win over the fixed numbers below:** every outro vocabulary card lasts **≥ 90 f (3 s)** with its word WAV at the card start; the JennieJoy logo after the iris is fully visible and **still ≥ 60 f (2 s)**; the film length is DERIVED from these (ep04 v013: 12 × 90 f cards from f2230, main 3314 f + 60 f EndLogo = 112.47 s) — never squeeze cards into a fixed 360 f window; the whole card (title pill, icon, IPA, VI, example) switches together on the card start frame (no icon lag, no double icon); the ending (iris → logo hold → cards → end plate "See you again, baby!" with the Mother line → EndLogo) is a separate segment joined after the main film so changing it never re-renders the main film; each spoken word has its own icon (G-ICON-ART in create-video-jenniejoykids; icons are an overlay registry, swap the image only); components are picture-only layers — audio (words, music, SFX) lives in the mix (`jjv audio mix`, −17 ±1 LUFS per section, gentle non-pumping ducking). HyperFrames components are the graphics LIBRARY layer for the planned Studio "Dựng" editor (T-E46): each component type (intro, card, pill, end plate, iris mask) is selectable by name with params, previewed live, rendered as its own segment.

For active children's production (*Milk and Mom*, `04-milk-and-mom`), HyperFrames components align to the 84-second (2520 delivery frames at 30fps) master timeline:
1. **Title Intro Component:**
   - Duration: Exactly 3.0 seconds = 90 frames at 30fps.
   - Output: Cinematic animated logo, title card, and bright morning sunburst entrance.
2. **Vocabulary Flashcards & Outro Component:**
   - Duration: Exactly 12.0 seconds = 360 frames at 30fps.
   - Content: 12 distinct vocabulary cards (Creamy, Smooth, Liquid, Dairy Cow, Farm, Fresh, Yummy, Warm and Cold, Bones, Yogurt, Cheese, Ice Cream).
   - Layout: Pacing accommodates measured variable card durations (25–46 frames, ~0.83–1.53s) matching trimmed pronunciation WAVs without cutting phonemes. Current calibrated pacing is the review cut `editorial/review-hd-v003` (its `BRIEF.md`): windows re-cut inside the same fixed 360 f, margin against speech >= +2.0 f on all 12 cards (against the whole WAV file it can be -0.5 f), 56 px card header and example text, pill opaque on the WAV start frame with the tile 0-3 f later (pill first); the 25-46 f figures above are the earlier measurement.
3. **Dialogue Keyword Callout Pills:**
   - Dynamic motion pills with bold white text on pink/fuchsia `#FF2E7E` background, designed with deterministic entrances and exits.
4. **Review-cut gate components (2026-10-27):** the JennieJoy end-card logo plate (G-END) and any iris or cloud-wipe alpha mask asset (G-CUT) are HyperFrames components with alpha, hash-bound and placed by Remotion on the brief's frames; see the [Review-cut gates](../create-video-jenniejoykids/SKILL.md#review-cut-gates-user-mandated-2026-10-27) and [jenniejoy-remotion](../jenniejoy-remotion/SKILL.md).

A standalone HyperFrames 5s preview or component render is an isolated asset; it does not constitute a completed full film.

## Domain separation & multi-engine coordination

For NEWTECONS live-action (`newtecons_live_action`), use [its film skill](../create-video-newtecons/SKILL.md) and [local routing](../create-video-newtecons/references/local-comfyui-routing.md): local ComfyUI image/identity/wardrobe/video inference, 45s/24fps master clock, original corporate logos. Do not mix live-action branding with cartoon assets.

For JennieJoy cartoons, read [character-first casting gate](../create-video-jenniejoykids/references/character-casting-gate.md). Use accepted versioned character references and expression/action hashes when Alice or Mother appears in an intro or card. HyperFrames exports graphic components; it does not create character libraries or replace H3 motion acting.

Avoid concurrent heavy GPU inference while executing intensive GPU video rendering; CPU software rendering for motion graphics is supported and preserves CUDA headroom for H3 and SeedVR2.

Updating HyperFrames recipes and contracts refines deterministic graphics generation; it does not constitute model-weight retraining. Read [motion engineering lessons](../create-video-jenniejoykids/references/motion-engineering-lessons.md) for deterministic animation principles and [production case studies](../create-video-jenniejoykids/references/production-case-studies-20261027.md).

## Opus motion engineering (code-driven title and flashcard motion)

Write intros, cards and callout pills as frame-event briefs and review them through the independent critic loop in [opus-motion-engineering](../opus-motion-engineering/SKILL.md). It adds process only; the timeline contract and domain separation above still win.
