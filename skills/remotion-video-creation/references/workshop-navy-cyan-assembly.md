# Workshop Navy–Cyan: renderer and frame contract

This skill owns deterministic renderer implementation; [business-motion-film workflow](../../business-motion-film/references/workshop-navy-cyan-assembly.md) owns story and independent creative review. Reuse an existing renderer where appropriate.

- Master storyboard 20s / 60fps / 1200frames, rendered frames0–1199; scenes [0,120),[120,300),[300,480),[480,660),[660,780),[780,960),[960,1200). Do not add transition overlap to total duration.
- A20s/30fps/600frame1920×1080 proof is separate. Same time: masterFrame=proofFrame×2. Confirm actual fps/duration/frame count/dimensions with ffprobe; never describe proof as completed 4K60 master.
- All transforms, masks, opacity, activation and connectors are pure frame functions. Remotion uses useCurrentFrame/useVideoConfig with clamping; an HTML proof needs deterministic seek and state recomputation. No CSS animation/transition, random without seed or accumulated physics.
- T01/T02 display windows [0,120) and [960,1200), readable at frame0; closing entrance begins at960 and settles by990. T04 continuous across S02/S03, hold144–462. T05 entry780–804, hold804–942. End metadata hold990–1199. Bind artwork by actual manifest ID/path.
- Existing SVGs contain one whole-phrase *_RUN_01. Reveal the group by mask or regenerate native Unicode using verified local font/shaping before word stagger. Never split Vietnamese combining marks or claim per-word outlines exist.
- Use native M01–M06 parts for independent assembly; A03 raster is a material reference, not real 3D geometry. Clean A02 needs its branded compound/source artwork, checked per helmet/vest.
- Package fonts/images locally; wait for readiness. Reflow portrait instead of cropping a landscape film. Measure content bounds/alpha and maximum scale, record upscale honestly; 4K canvas is not native source detail.
- Test repeated seeks in differing orders by actual pixels/hashes. Inspect transitions and 1:1 crops. Source scan alone is not determinism proof; builder cannot replace independent critic review.

Known asset package: `D:/61.SetupAgent/revit-live-demo-20261110/pttx/workshop-ai-intro-navy-cyan/`.
Repository-relative path: `revit-live-demo-20261110/pttx/workshop-ai-intro-navy-cyan/`.
[Repository location](https://github.com/Long0308/setupagent/tree/main/revit-live-demo-20261110/pttx/workshop-ai-intro-navy-cyan) is an intended Git location, not a push receipt.
Existing Workshop canon: `awesome-gpt-image-2/AI-Newteons/workshop-ai-2026-11-14/`.
Keep this task's asset kit at the user-selected destination; do not copy another full poster snapshot into skills. Read its `prompts/CLAUDE-MOTION-INTRO.md`, `prompts/motion-scenes.json`, `text-content.json`, `text-animation.json`, and `references/REFERENCE-STATUS.md` before editing.
