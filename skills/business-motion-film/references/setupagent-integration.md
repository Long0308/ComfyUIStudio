# SetupAgent integration (03 Oct 2026)

Upstream: https://github.com/echris6/motion-video-kit
Pinned revision: 255562b04b1e5ecaa4ba98e5c9aa191d5ba7f6fa.

This skill owns motion design and independent quality review. It complements
`../../remotion-video-creation/SKILL.md` (renderer and frame timing); the Stitch
walkthrough skill named `remotion` has a separate scope. Do not duplicate video
renderers, modify runtime hooks or start external automation during integration.

Root selects the skill from the existing catalog. Worker builds the composition.
An independent reviewer checks real output. This is an ownership policy; it is
not proof that every IDE automatically loaded or executed the skill.

Example source: `D:/61.SetupAgent/tools/architecture-video/`.
Existing tracker: `D:/61.SetupAgent/docs/PLAN-2026-10-03-agent-live.md`.
Serve artifacts on the existing local setup page. Label snapshots and distinguish
explanatory motion from observed traffic. Do not portray a missing service as live.

For Remotion, use the current frame as the clock. HTML/GSAP examples from upstream
must be adapted; do not insert free-running CSS or requestAnimationFrame motion.
Use short English captions and plain Vietnamese translations. Full ASD-STE100
dictionary conformance is a separate check; a sentence-length test is not enough.
