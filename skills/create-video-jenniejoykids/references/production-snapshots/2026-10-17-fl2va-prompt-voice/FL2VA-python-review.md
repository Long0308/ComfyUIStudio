# Independent Python review — native H3 FL2VA adapter

**PASS — Approve for the reviewed offline adapter and graph.** No remaining critical, high or medium findings.

Reviewed `scripts/build_fl2va_workflow.py`, `tests/test_fl2va_builder.py` and `references/comfy-fl2va.md`, plus the specifically authorized saved v12 config, workflow, preflight and object-schema JSON. Existing Ref2VA builders retain their prior reviewed hashes and behavior.

## Actual verification

- **9/9 focused FL2VA tests pass** in 0.605 seconds.
- **137/137 full Python tests pass** in 10.317 seconds, zero failures/errors/skips.
- The actual saved **27-node S01_B v12** API wrapper, GUI graph and provenance reproduce exactly from its config, manifest and supplied local `installed-object-info-live-v12.json` snapshot.
- The final transformed graph passes that schema validator. The transient Ref2VA graph is not incorrectly presented as the schema-validated final result.
- Input config, manifest items and schema remain unmutated. Blocking file opens and subprocess execution during graph construction succeeds: no source PNG, VO, model, script or external process is read/run by the builder.
- Independent prompt probes preserve the complete inline cast, literal braces/pipes, URLs, quotes and backslashes through STRING19 → I2V6. Source dialogue remains in the receipt and is removed from the native visual-only payload; only consumed first/last keyframe bindings are emitted.
- **18 independent malformed CLI cases** fail nonzero, without traceback or an output directory: malformed/root-type config and manifest JSON, invalid schema root types/missing node, invalid engine shapes and path traversal.
- A valid CLI run emits matching wrapper/GUI JSON. A second run refuses the existing directory and leaves **all three** prior output files byte-identical.
- General duration, native dimensions, steps and seed limits remain delegated to the existing reviewed core; the focused suite checks a second size/duration and derived indices.
- AST parsing and in-memory compilation pass. New public entry points have annotations; heterogeneous JSON remains a gradual typing boundary. Ruff, mypy, pylint, Black and Bandit are unavailable, so their checks are not claimed.

The initially missing entry-point annotations and malformed schema-root handling were corrected before this final review. Explicit engine/cast/scope validation now reports normal input errors, and Windows relative keyframe/reference spellings normalize consistently without mutating sources.

Tests used isolated ComfyUI Python 3.12.14 with `-Xutf8 -B`, workspace cwd, `COMFYUI_ROOT=production-local/ComfyUI`, bytecode writes disabled and Node/FFmpeg on PATH. Focused command: `-m unittest test_fl2va_builder -v`. Full command: `-m unittest discover -s C:/Users/Admin/.codex/skills/create-video-jenniejoykids/tests -p test_*.py -q`.

## Actual v12 graph contracts

The adapter accepts one continuation, root carry=true, staged first/explicit-last PNGs, canonical VoiceStudio editorial audio, voiceover with native speech disabled, and explicit simple scheduler. Extra guides and unconsumed image references are rejected.

| Contract | Verified result |
| --- | --- |
| Native engine | FL2VA checkpoint; MiniMaxH3ImageToVideo6; first image8 / last image20 only |
| Conditioning/latent | Positive6:0 → BasicGuider10; joint latent6:1 → Sampler14 |
| Sampling | simple / res_multistep, steps20, seed4341, 864×480 |
| Native A/V | complete 124-frame decoded batch15 and generated audio16 → native CreateVideo17 → SaveVideo18 |
| Editorial carry | accepted incoming image8 + generated frames1..119 via ImageBatch52, 120 frames total |
| Canonical editorial audio | original guide WAV7 → trim58, start0/duration5 → editorial CreateVideo56 |
| Actual next boundary | editorial actual frame119 → ImageFromBatch51 → boundary-end SaveImage55 |
| Supplied last keyframe | conditions native frame123; never substituted for actual used frame119 |

No redundant AddGuide, Ref2VA node, clip guide, unused reference-image chain, native speech-reference audio or sibling generation remains in the final graph. The graph SHA256 is `4dd2421785d3907c34a78814a14506eeac3cd660d02f0b4e2fa85ab6379cc8e1`.

The receipt explicitly distinguishes last native condition123 from actual used119 and derives both from configured durations; it keeps submission and runtime benchmark pending.

The supplied `preflight.json` separately records 864×480 PNG dimension checks and external model verification matching declared SHA256 `e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a` and 20,970,379,616 bytes. This reviewer read only that metadata and did not open, hash or load the model or PNGs. The builder's model-artifact verification field correctly remains pending because artifact verification is external to graph construction.

## Reviewed identities

| File | SHA256 |
| --- | --- |
| build_fl2va_workflow.py | `3a7397296d2e6a7dfc67ba4947d19537ed22544ede0b815386c56a169a1b6944` |
| test_fl2va_builder.py | `6dfd7f97af926eb57b98b72d1e4cff900de58ed4095a3241f4f2d326ded45645` |
| comfy-fl2va.md | `ebc0747a9a53bb452512a9a450ad5db7043818dbb31162ad6c2453f9b99dc8dd` |
| build_comfy_workflow.py | `f3516da0c650f9717db33ea0df3c88a90b60474193271d38527312f4b33d6ad5` |
| build_continuous_workflow.py | `ba590c8cbad4ca543dacca26f2d9e5242bc3613a7909ccafaea8cf2e38721149` |
| config.json | `07a5a36d57b36d62566f138bab6a4d51f69b994f16e60920e76f9738094fe40f` |
| video.json | `178284b20b30a2dc558a901ee4785b786e30f6402d4cbc5b1e51a5c3cccdf99b` |
| installed-object-info-live-v12.json | `339491471b7a56b20cf284b6d9fc410cb22b6b27d2f5f9ea46119cf140602c81` |
| workflow-api.json | `42c941339efc867d153fa52cb71b5830263808fbd1983d7752741b30bf7fb757` |
| workflow-gui.json | `d90598b2c350f590c59141e1e14b98addf316dc0a53dcbd3582adef77d7c102f` |
| workflow-provenance.json | `2f4be7f12881b89ad6cf9d635443fa57281e748b097887aba9ab091a39e8ca65` |
| preflight.json | `60a05f5cd47835fbd10f47d19edf67fea764f0a39579bb31192e305995a55158` |

Git diff was attempted, but the skill directory is not a Git repository. Source inspection, prior builder hashes and exact artifact reconstruction supplied the review evidence.

The reviewer changed no implementation, config, existing workflow, live project or production artifact. Only this report was added. Tests use temporary synthetic fixtures and mocked local HTTP fixtures; no actual VO, model file, production server, GPU, queue, inference or render was accessed. Schema validation proves graph compatibility with the supplied snapshot and does not prove model loading, generated motion, listening quality or visual acceptance.
