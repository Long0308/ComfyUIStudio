# Independent motion code audit

Date: 2026-11-12. Reviewer: independent JavaScript reviewer subagent. Result: **PASS within the reviewed code scope; no remaining actionable findings.**

## Scope and review boundary

Reviewed the final changes in `animation/preview.js` (frame-driven articulated fixtures, mechanical latches, activation trace and S03 placement), `animation/build-assets.cjs` (M07 fixture and projection adjustment), and `animation/verify-assets.cjs` (PNG parser export and direct-execution guard). Read surrounding scene, text-window and playback logic. This is a bounded follow-up to the preceding independent review and fixes.

The package has no supplied Git/PR metadata, package.json, TypeScript configuration or available ESLint executable. PR merge readiness cannot be verified. TypeScript and ESLint checks were unavailable; this JavaScript-only package was checked with Node instead. No production source or generated media was changed by the reviewer. This audit document is the only file written.

## Findings

No CRITICAL, HIGH or MEDIUM defect was found in the final changed scope. The fixture state is computed from the requested frame time using bounded interpolation. It introduces no accumulated simulation state, randomness, timer reads or asynchronous work into frame rendering. M07 is a separate reference-pose asset; the animated fixture is generated procedurally in the preview rather than added to the six assembling parts. The PNG module now exports `png` while its CLI work remains inside `require.main === module`.

## Actual checks

- `node --check animation/preview.js`, `node --check animation/build-assets.cjs` and `node --check animation/verify-assets.cjs`: exit code 0.
- Executed the actual `content.js` and `preview.js` in isolated Node VM contexts for landscape and portrait. DOM and animation-frame scheduling were stubbed; generated SVG markup was measured, not raster pixels.
- Tested 35 proof frames per aspect: `0, 59, 60, 149, 150, 156, 157, 162, 163, 164, 170, 171, 176, 177, 182, 185, 186, 196, 197, 199, 200, 210, 211, 213, 225, 232, 239, 240, 330, 390, 476, 479, 480, 495, 599`. These include fixture arrival, gripping/retraction, lock/activation and scene/window boundaries.
- Captured SHA-256 hashes of generated markup, sought the same frames in reverse order, then repeated frames `185, 163, 200, 185`: **0 mismatches in either aspect**. No full 600-frame rerun was performed for this final bounded change.
- Across those samples: **0 NaN/Infinity values**, **0 missing local image paths**, and **0 T01/T02 title appearances outside [0,60) and [480,600)** in either aspect.
- Current six bundled mechanical part markups exactly match the corresponding source SVG files. This confirms the bundle contains the current projection change.
- Playback regression test, Play -> Pause -> Play before repaint: **1 queued callback, 1 render on that repaint, 1 queued callback afterward**. Restart and Seek each leave **0 callbacks** in both aspects.
- Importing `animation/verify-assets.cjs` exports a function and leaves the existing `evidence/motion-preview-assets.json` byte hash unchanged.
- Called the exported PNG decoder on actual files. `M01-base.png`: 1000 x 800, 654105 transparent pixels, content bounds x=13, y=407, width=878, height=390. `M07-fixture.png`: 1000 x 800, 779542 transparent pixels, content bounds x=16, y=144, width=253, height=537. Both have transparent pixels and content bounds inside the canvas.

The preceding independent follow-up also executed the renderer's failed-required-resource path with mocked browser transport: exit code 1, zero encoder invocations, failure receipt written, no success receipt, browser/server cleanup completed. That result is carried forward; the renderer was outside this final fixture-only change. The earlier required-resource gate, duplicate-playback-loop and premature-title findings were all resolved before this bounded follow-up.

## Audited source hashes

| File | SHA-256 |
| --- | --- |
| `animation/preview.js` | `e98ddcc77e987fbeec80620f7db47ab1ef4c15a7a1cde1008f25cefe0c176229` |
| `animation/build-assets.cjs` | `f101b0ff98606113c8524e5563d300db8c85a8fa9d23b0b00c98b5bac9ba8992` |
| `animation/verify-assets.cjs` | `1e8d76a7ed70d048a14870514b0a9eabb66d0a493e2814165734d78f8b05eb5f` |
| `animation/render.cjs` | `9b052cde15851b2887b60196529eef40c2ea1bb76a760217d89acd1329d56ae6` |
| `animation/content.js` | `f6b80fb69479a9c8ff65376a7a91c0df56b3ea2924b833408d83405fa16fe4c4` |

## Limits

This is source and execution-logic evidence. Markup determinism is not pixel determinism. The PNG measurements establish decoded dimensions, transparency and bounds; they do not establish visual quality or mechanical realism. The audit does not claim rendered headline clearance, physical gripper contact, logo fidelity, similarity to a reference, complete video continuity, codec validity or final export delivery. Independent visual inspection and actual media receipts must support those claims. The active video capture was not opened, controlled or interrupted by this review. Any later source changes require comparison against the hashes above and proportionate re-verification.

Memory preflight used `which_bank` (may-agent-memory), `recall_error_db`, `workspace_facts` and `recall_graph`. Recall confirmed the existing package and source-logo compound; no parallel kit or implementation was created.
