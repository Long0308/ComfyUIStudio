# Independent guide_clips review

Verdict: PASS for offline graph construction. No blocking correctness finding within the guide_clips addition. This does not certify actual media inputs, runtime memory use, or generated motion.

## Evidence

- Read both builders and focused tests. Inspected installed `production-local/installed-object-info.json` plus actual `ComfyUI/comfy_extras/nodes_minimax_h3.py:166–240` implementation.
- Ran `python -m unittest discover -s C:/Users/Admin/.codex/skills/create-video-jenniejoykids/tests -p test_video_guides.py -v` from project workspace: 6 tests passed, zero skips, 0.074 seconds. Installed-schema test executed and passed.
- Native schema supports IMAGE batches through MiniMaxH3AddGuide, returns only CONDITIONING, accepts valid clip lengths17k+5. Builder matches this constraint and rejects invalid index/count/type/path/order shapes.
- Clip wiring is LoadVideo→GetVideoComponents output0→ImageFromBatch(0,count)→AddGuide.image. Audio output1 and fps output2 are unconnected. Video guide audio cannot enter conditioning or editorial outputs through these new wires. Canonical editorial audio remains original guide WAV; native generated audio remains preserved separately.
- Every AddGuide receives original ReferenceToVideo latent output1. Final sampler latent remains that original AV latent. AddGuide CONDITIONING is never misused as latent.
- Image/clip guides are sorted by frame index; ties deterministically order clip before image. Existing frame-zero guide precedes extras. Combined allocation begins100 and is capped at999; continuous segment ID stride1000 remains safe.
- For clip-only B with no preexisting frame-zero guide, continuous builder inserts node1009 with A boundary node51 (used119 for120-frame edit) as image; earliest extra guide1103 is rewired to1009 positive, then sampler conditioning follows last guide. Thus A119 dependency is upstream of B clip guide, not bypassed. Editorial frame0 also uses A119, native B remains unmodified.
- Receipt remapping covers video/components/frame-slice/guide IDs and records first extra guide plus complete conditioning order.

## Limitations requiring production preflight

1. Actual clip frame count and24fps are deliberately not verified by this offline builder. Receipt labels preflight pending. Probe every staged source before submission: a short batch can become a shorter native guide, and wrong fps changes temporal semantics because fps output is intentionally unused. Do not treat schema pass as source-media pass.
2. GetVideoComponents can decode complete source video before slicing; unnecessarily long/high-resolution sources may consume substantial host memory. Stage tightly bounded clips and check dimensions.
3. Overlapping clip/image guides are allowed. Simultaneous frame-zero incoming image and clip conditioning may conflict if the clip begins in a different pose; node ordering does not guarantee model precedence or correct movement. Review source start against A119 and generated consecutive seam frames.
4. Tests are graph/schema assertions, not GPU inference or audio playback. No running workflow was submitted, interrupted or changed for this review.

## Reviewed file hashes

- `C:\Users\Admin\.codex\skills\create-video-jenniejoykids\scripts\build_comfy_workflow.py` SHA256 `00a75f7865303635f0a82dd50eace7cfa0d0079b8ebb306d254c9b6fd02c5513`

- `C:\Users\Admin\.codex\skills\create-video-jenniejoykids\scripts\build_continuous_workflow.py` SHA256 `aeca10faadb80b8d495cc0cc49449ae809d5db24919dff8dab567d7c09ee79af`

- `C:\Users\Admin\.codex\skills\create-video-jenniejoykids\tests\test_video_guides.py` SHA256 `95f1a2171834fd7c43407962ab37bff67f79f1a89c3db07c51f0a90aec5b903d`
