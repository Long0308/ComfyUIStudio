# Python review — S01_B continuation repair v10

**PASS — Approve for the reviewed offline code and graph.** No critical, high or medium findings.

Reviewed the final `build_continuous_workflow.py` one-segment count change, added carry tests, and the actual `S01-B-repair-v10` config/workflow. This review leaves the earlier metadata/carry review intact.

The functional source change is limited to the accepted segment count **2..100 → 1..100** and its matching error text. Reversing those two literals in memory reproduces the exact previously reviewed SHA256 `5476743943041fbf32f062c67572789d65b4ecbb88aa5158a001d0f6f504d121`. The core builder remains unchanged. AST parsing and in-memory compilation pass.

## Verification

- **7/7 focused carry tests pass** in 0.096 seconds.
- **124/124 full-suite tests pass** in 9.857 seconds, zero failures/errors/skips.
- Two- and three-segment wrappers and provenance are unchanged from the previously reviewed builder, with carry both disabled and enabled.
- Single-segment absent/false carry remains identical and preserves the ordinary initial batch. Empty and over-100 segment counts are rejected.
- Offline reconstruction from the actual repair config and saved manifest/schema reproduces the saved API wrapper, GUI graph and provenance exactly. Config, manifest items and schema are unmutated.
- During graph construction, blocking both `builtins.open` and `Path.open` prevents asset reads; the rebuild still succeeds. No image, script or actual Alice/audio asset was opened by this review.

Tests ran from `D:/23.JennieHomeSchool/03 Voice`, with `production-local/ComfyUI/.venv/Scripts/python.exe -Xutf8 -B`, Python 3.12.14, `COMFYUI_ROOT=production-local/ComfyUI`, bytecode writes disabled and Node/FFmpeg available.

Focused command: `python.exe -Xutf8 -B -m unittest test_cross_job_carry -v`.

Full command: `python.exe -Xutf8 -B -m unittest discover -s C:/Users/Admin/.codex/skills/create-video-jenniejoykids/tests -p test_*.py -q`.

## Actual S01_B graph

The saved graph contains **30 nodes, one sampler, S01_B only**, at global start 5 seconds for a 5-second editorial span. All node IDs are below 1000; output prefixes belong only to `Scene-01-B-v10/S01_B`. Seed is **4341**, steps 20, dimensions 864×480.

| Contract | Verified graph route |
| --- | --- |
| External incoming carry | staged actual A119 PNG → LoadImage 8 → ImageBatch 52 image1 → B editorial frame0 |
| Remaining editorial frames | native B1..B119 → ImageFromBatch 50 → ImageBatch 52 |
| Complete native output | 124-frame native decoded batch 15 plus native generated audio 16 → CreateVideo 17 → SaveVideo 18 |
| Canonical editorial audio | original `JennieJoyKids_S01_B-guide.wav` → LoadAudio 7 → TrimAudioDuration 58, start 0 / duration 5 → CreateVideo 56 |
| Visual guides | incoming image 8 at frame0 → guide 9; planned endpoint image 100 at frame119 → guide 101 → conditioning 10 |

No sibling A generation/output is present. No video clip guide is loaded. Native speech reference/guide conditioning remains disabled; canonical guide audio is reserved for editorial output. The native batch/audio routes are unchanged.

Graph/receipt JSON round trips preserve data. The receipt correctly reports `not_submitted` and an external carry source with no same-graph predecessor. Actual PNG dimension/acceptance checks and output-media quality are outside this bounded review; the existing receipt still labels actual dimensions `pending_before_Run`.

## Reviewed identities

| File | SHA256 |
| --- | --- |
| build_continuous_workflow.py | `ba590c8cbad4ca543dacca26f2d9e5242bc3613a7909ccafaea8cf2e38721149` |
| build_comfy_workflow.py | `f3516da0c650f9717db33ea0df3c88a90b60474193271d38527312f4b33d6ad5` |
| test_cross_job_carry.py | `d3d842e965307919f27ba98268d407a6283f684dd32fdf0bd47e82fadc2a684b` |
| config.json | `82bc72c9466998af9ed8799ab40cca614aaf6e454dd6b89884905517c3151271` |
| video.json | `178284b20b30a2dc558a901ee4785b786e30f6402d4cbc5b1e51a5c3cccdf99b` |
| installed-object-info-live-v3.json | `75de386d263232bb8fef8cd0b5918b751c4b51149e21ed3711f4edfb23cbfd11` |
| workflow-api.json | `2dc69a5390b125fced237aefeda959480edd7bbd7dad36eb35e23841054aca91` |
| workflow-gui.json | `f1a772ef9d7207083f4c92c4b7aed0b93740679c8216fd383a66b1bc1cfce2de` |
| workflow-provenance.json | `e786874b5712da1df3315fd8b1475258f28d5e6f385527b17ebabbe7a4670f34` |

Git diff was attempted; the skill directory is not a Git repository. Exact prior-byte reconstruction establishes the source delta. Ruff, mypy, pylint, Black and Bandit are absent in the isolated environment; their checks are not claimed.

The reviewer changed no source, config, workflow, runtime, queue, GPU or production artifact. Only this review report was added. Full-suite audio tests use temporary synthetic fixtures. No real Comfy submission, inference, actual voice WAV read, listening or final-media acceptance was performed.
