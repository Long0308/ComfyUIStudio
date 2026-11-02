# guide_clips Python review

**PASS — no actionable correctness or security findings in the bounded guide_clips change.** Reviewed the user-level skill's `scripts/build_comfy_workflow.py`, `scripts/build_continuous_workflow.py` and `tests/test_video_guides.py`. No production workflow, model, runtime or render job was changed or submitted.

## Verified behavior

- `guide_clips` requires an ordered list of exact `{video, frame_idx, frames}` objects. Booleans/non-integers are rejected. Starts must be nonnegative and strictly increasing; counts must be at least 5 and satisfy `frames = 17k + 5`; each span must end within `native_frames`. Image-anchor and clip ordering is validated separately, then merged chronologically. Equal-time clip/image ties resolve deterministically to clip then image.
- Staged clip/image paths reject absolute/rooted/drive/UNC paths, parent traversal with either separator, colons, dynamic percent formatting, control characters and empty/non-string names. Additional read-only checks rejected all 11 tested unsafe variants.
- Each image guide consumes 2 IDs and each clip consumes 4 IDs, starting at 100. The combined budget of 900 keeps every single-shot guide node at or below 999. Core/reference nodes and continuous editorial nodes 50–58 remain disjoint. The maximum 225-clip case reaches 999 and adding another image is rejected.
- Clip conditioning uses `LoadVideo -> GetVideoComponents` image output 0, a contiguous `ImageFromBatch` slice from source frame 0, and `MiniMaxH3AddGuide`. All guide nodes use the original latent while positive conditioning chains forward. Guide clip audio and source FPS outputs are never connected to conditioning or editorial outputs.
- Continuous remapping preserves all guide node/link IDs and provenance. When a later segment lacks a frame-zero guide, its incoming editorial boundary is inserted before the first extra clip/image guide. Native raw video/audio and canonical/native editorial audio selection retain their existing routing.
- Repeated construction of a mixed two-segment graph produced identical graphs, receipts and graph SHA256 without mutating inputs; all remapped links resolved. The tested mixed graph hash was `86f461478b60ff0f83fe98b004440d4946cbcd4c0cd4d90b9a7fb041461f824c`.

Actual staged media FPS and source frame counts remain explicitly **pending source preflight** in receipts. This offline builder review does not certify those media properties or the quality of generated motion.

## Validation

All **37 targeted tests passed**, with no skips:

- `test_video_guides.py`: 6, including the actual saved installed-object schema.
- `test_native_builder.py`: 17 relevant builder regressions.
- `test_continuous_builder.py`: 14 continuity/remapping/audio/schema/CLI regressions.

AST parsing passed for all three reviewed files. Ruff, mypy and Black were attempted but those modules are unavailable in the selected Python runtime. `git diff -- '*.py'` was attempted; the skill directory is not a Git repository. Tests and checks were offline; no Comfy submission, GPU operation, transcription or browser interaction occurred.

## Reviewed source hashes

Root: `C:/Users/Admin/.codex/skills/create-video-jenniejoykids`.

| File | SHA256 |
| --- | --- |
| `scripts/build_comfy_workflow.py` | `00a75f7865303635f0a82dd50eace7cfa0d0079b8ebb306d254c9b6fd02c5513` |
| `scripts/build_continuous_workflow.py` | `aeca10faadb80b8d495cc0cc49449ae809d5db24919dff8dab567d7c09ee79af` |
| `tests/test_video_guides.py` | `95f1a2171834fd7c43407962ab37bff67f79f1a89c3db07c51f0a90aec5b903d` |
