# Blender → ComfyUI storyboard handoff

Use the installed `comfyui-blender` skill (`C:/Users/Admin/.codex/skills/comfyui-blender/SKILL.md`) for shots where prompt text alone cannot fix physical blocking, depth, occlusion, camera or character contacts. Read its `references/animation.md` and `references/local-profile.md` for this machine. This reference defines the JennieJoy film contract; it does not replace the installed skill.

## Before building

1. Read the current shot script, accepted character library bindings and rejected takes. Resolve exactly who appears, their pose, spoken line, props and front-to-back order. Never regenerate a reusable character sheet just to stage a shot.
2. Check live Blender/ComfyUI capabilities, ComfyUI queue and prior prompt IDs before GPU work. Follow the installed skill's MCP and bridge checks when those tools are exposed. If they are not exposed, use a separately launched local Blender CLI and ComfyUI API/file route, recording that route; do not report an MCP or add-on call that did not happen.
3. Save a new episode-owned `.blend` and script version. Keep source images and rejected candidates unchanged.

Shot-to-shot continuity (shared SET, `scene_layout.py continuity A B` to choose the transition type, `placement-text` to repeat identical placement in both H3 prompts): see [comfyui-blender: Shot continuity](../../comfyui-blender/SKILL.md#shot-continuity); it proves planned layout agreement only, the generated frames are still reviewed pixel by pixel.

## Spatial guide and local generation

1. Place characters, props, obstacles and camera in actual 3D coordinates. Render a beauty guide; add depth, line or per-object masks from the same camera, crop and frame only when a matching validated ComfyUI consumer exists. Record pass meaning and dimensions. For *Milk and Mom*, Blender is a layout/control tool only: neither its beauty pass nor its graybox is final storyboard art, regardless of how polished it looks.
2. Inspect the guide PNG itself at full resolution. Verify perspective, overlap, silhouettes, body and prop contact and the shot's hard spatial rules before sending it to ComfyUI.
3. Use only installed and validated local ComfyUI nodes/models. Save editable GUI and API workflows with exact input PNG paths/hashes, model filenames, seed, prompt text and expected sinks. Validate the graph, submit one pilot, store the real prompt ID and output hashes, and reopen its GUI review copy with `LoadImage` showing the actual result. If guidance nodes are unavailable, use separately composited depth layers or stop at a labeled guide; a text-only retry is not proof of topology control.
4. Review the generated pixels again. Record `candidate`, `rejected` or `accepted` with reasons. Promote only an accepted full storyboard image with all required characters and actions; a background plate, graybox or prepared workflow remains a separate state. Match the approved Alice/Mother cinematic 3D cartoon look across every visible actor, cow, prop and environment: coherent daylight and materials, true scene depth, feet/hooves/hands in contact, cast shadows, correct foreground occlusion, adult milkmaid proportions, readable facial acting and no visible cutout seams. Check the actual output, not the prompt or Blender guide.

## From storyboard to animated film

An accepted still frame is an H3 **input**, not a finished shot. Generate the shot with real subject and camera movement, inspect decoded beginning/middle/end plus dialogue windows, and reject static-poster zooms, identity drift, flicker, detached hands, sliding feet, moving listener mouths or cows crossing the fence. Bind the final WAV and shot carry to the video receipt. SeedVR2 may restore detail after the motion and lip/acting pass; it cannot convert a layout guide or bad acting into an animated film. Only reviewed moving clips enter the Remotion master.

## Milk and Mom S01_A physical gate

- Garden side: Alice kneels at screen left; Mother sits at screen right with a sealed bottle in reach. Bind their existing approved identity files and recorded review statuses.
- Barrier: a continuous front fence with visible left and right returns separates family and animals. The full bodies, heads, legs and hooves of exactly two cows remain behind it; no cow intersects or protrudes through a rail or opening.
- Farm side: one adult Dutch milkmaid with her own accepted identity sits on a stool beside side-on Cow A, with both hands milking at the udder and the pail below. Cow B is farther back. The milkmaid cannot be improvised as a child or as Mother.
- Review camera depth, occlusion, lighting, contacts and speaking/listening mouths in the final generated frame. A guide that passes geometry does not certify the generated frame.

Record source script/scene hashes, camera, render settings, references and approval status in an episode-owned receipt. The production workflow and `SaveImage` output remain under the film's workflow/output folders; rejected takes remain labeled and traceable.
