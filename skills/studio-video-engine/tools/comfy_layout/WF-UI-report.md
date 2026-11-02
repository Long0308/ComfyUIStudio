# WF-UI builder report — 2026-10-31

Status: implementation and offline evidence prepared; **root acceptance pending**.
The requested production destination is outside this session's writable root.
The grouped workflow is staged at `tools/comfy_layout/NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json`; it has **not** been installed beside v001.
No attempt was made to bypass the sandbox. Root must create the destination with the command below and rerun the gate outside this sandbox.

Counts: **19 original API nodes + 5 Notes = 24 UI nodes; 25 links; 5 groups**.

## What changed (paths relative to the engine)

- `tools/comfy_layout/api_to_ui.py:45`: deterministic offline conversion using an explicit, audited H3 schema. Keeps source node IDs/order, API literal values and titles; rebuilds both sides of links with validated slot types. Unknown types/inputs and malformed links are refused.
- `tools/comfy_layout/api_to_ui.py:82`: reject missing-widget gaps that would shift later positional values. Linked widgets are excluded from `widgets_values` as requested. RandomNoise uses the explicit UI-only `fixed` seed control.
- `tools/comfy_layout/api_to_ui.py:128`: reverse conversion reads actual UI slots, wires and widget values, without storing an original API payload to fake the round trip.
- `tools/comfy_layout/api_to_ui.py:183`: applies `comfy_groups.layout()` and `check()` using the supplied five-group map, overriding only colors to `#0B4FD9`, `#5B9BF5`, `#9D9BF5`, `#3E8914`, `#134611`. All original group titles, selectors and notes remain intact. Group 04 contains only a Note.
- `tools/comfy_layout/api_to_ui.py:200`: exclusive output creation (`open('x')`); CLI `--check` is read-only.
- `tools/comfy_layout/comfy_groups.py:47`: copied existing grouping implementation. No algorithm changes; UTF-8 BOM/newlines normalized, so file hash differs from the staging source. Every source node field except position is retained by the grouping stage.
- `tools/comfy_layout/h3_schema.json:1`: schema-only extraction from the confirmed `JennieJoyKids-H3-Video-Ready.json` (sizes, port names/types, optional shapes). No template prompt, image/audio path, widget value, wiring or properties was copied. Widget order cross-checked against local `nodes.py`, `nodes_custom_sampler.py`, `nodes_audio.py`, `nodes_minimax_h3.py`, `nodes_video.py`, `nodes_primitive.py`.
- `tools/comfy_layout/NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json:1`: staged editable LiteGraph workflow, version 0.4, exact five titles, Blue Web palette. Blank NEWTECONS anchor/WAV inputs remain blank.
- `tests/test_comfy_layout.py:32`: real v001 round trip, independent endpoint comparison, all IDs preserved, exact group titles/colors, full bounding-box containment, determinism and nonmutation. Other tests cover linked prompt, dynamic codec, seed, invalid schemas/links/maps, exclusive creation, wire tampering, optional-widget gap and saved artifact identity.

## Real command output

Cwd: `J:\1.JennieHomeSchool\03 Voice\.agents\skills\studio-video-engine`.

Artifact creation (exit 0):

```powershell
python -I -B tools/comfy_layout/api_to_ui.py 'J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_H3\NEWTECONS_H3_R2V_LIVE_ACTION_v001.api.json' 'J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_H3\NEWTECONS_H3_R2V_LIVE_ACTION_v002_group-map.json' 'tools/comfy_layout/NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json'
```

```json
{"added_notes": 5, "all_original_fields_except_pos_unchanged": true, "api_round_trip_equal": true, "every_node_inside_exactly_one_group": true, "group_map_sha256": "08bfc5ee6f833d45c595d48225e29d3e278a5ca21604eb4e2b501a5ea50460e8", "groups": 5, "original_nodes": 19, "output_links": 25, "output_nodes": 24, "output_sha256": "8f67d3afb6e7c4e9c7c3c3efbbc5edddcf99e5c1fa69c79e58f73eac2b234d40", "preserved_nodes": 19, "schema_sha256": "0362377a1b119fcd1271867fe348d9069071bd0eccdb50496bee52b7b5f4e207", "source_links": 25, "source_sha256": "4c6a1fda7320503c5991986ec37981f3b921476173cb07df50e4abb568b7e730", "widgets_values_unchanged": true}
```

The identical command with trailing `--check` returned exit 0 and the same JSON after the final code fix. `widgets_values_unchanged` refers to the UI-before-layout versus UI-after-layout comparison; API equivalence is separately checked by `api_round_trip_equal`.

Final test invocation (exit 0):

```powershell
python -I -B -c "import pytest,sys; sys.exit(pytest.main(['tests/test_comfy_layout.py', '-q', '-p', 'no:cacheprovider', '--basetemp', '.pytest_work_tmp/WF-UI-03']))"
```

```text
...............                                                          [100%]
15 passed in 0.12s
```

Earlier actual diagnostics: initial isolated CLI failed with `ModuleNotFoundError: No module named 'comfy_groups'`; first pytest ended `2 failed, 12 passed in 0.19s` because artifact generation had failed and the test mistakenly expected 27 wires. Fixed isolated sibling loading and corrected the count to the 25 actual source connections. Next run returned `14 passed in 0.24s`. Python review then identified a general optional-widget gap case; added a refusal and regression test, producing the final output above. Historical files were not deleted.

Review: code-reviewer found no substantive issue. Python reviewer verified the optional-widget gap fix and reported no new substantive findings. The schema reviewer on `custom/oauth-anti-gemini-flash-high` completed the bounded review and reported a separate run with `15 passed in 0.13s` (basetemp `.pytest_work_tmp/wf_ui_schema_review`). No frontend/GPU acceptance verdict is asserted by this report.

## Root installation and gate (not executed here)

Run from the engine directory with write access to the production workflow folder:

```powershell
python -I -B tools/comfy_layout/api_to_ui.py 'J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_H3\NEWTECONS_H3_R2V_LIVE_ACTION_v001.api.json' 'J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_H3\NEWTECONS_H3_R2V_LIVE_ACTION_v002_group-map.json' 'J:\1.JennieHomeSchool\03 Voice\production-local\ComfyUI\user\default\workflows\NEWTECONS_H3\NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json'
python -I -B -c "import pytest,sys; sys.exit(pytest.main(['tests/test_comfy_layout.py', '-q', '-p', 'no:cacheprovider', '--basetemp', '.pytest_work_tmp/WF-UI-ROOT-01']))"
```

Choose a fresh basetemp suffix if that root test directory already exists. Converter refuses an existing destination; use `--check` to compare it instead. Expected artifact SHA-256 appears below. The artifact test prefers the production destination if present, otherwise the staged file.

## SHA-256

| Changed file | SHA-256 |
|---|---|
| `tools/comfy_layout/api_to_ui.py` | `875ef6fe69df990d7433b23f3f076a7bbc88b6b9c97c4744f39151d19275e3c2` |
| `tools/comfy_layout/comfy_groups.py` | `7eb3b726e64c4ece065e483d7932f644f4da2718dbe6f3720a880719f3d1a905` |
| `tools/comfy_layout/h3_schema.json` | `0362377a1b119fcd1271867fe348d9069071bd0eccdb50496bee52b7b5f4e207` |
| `tools/comfy_layout/NEWTECONS_H3_R2V_LIVE_ACTION_v002_grouped.json` | `8f67d3afb6e7c4e9c7c3c3efbbc5edddcf99e5c1fa69c79e58f73eac2b234d40` |
| `tests/test_comfy_layout.py` | `974c29316f9fa6d50c2242e2b9a8d7cfbe7322a0215c146a7be89b526063b462` |

This report's own hash is provided in the final response to avoid a self-referential checksum.

## CHỖ NÀO BẠN ĐOÁN — NÓI THẲNG

1. `PrimitiveStringMultiline` size `[520,320]` is an explicit layout estimate; its input/output types come from the local `StringMultiline.define_schema`. Other sizes come from the existing UI workflow. Browser auto-resizing has not been measured.
2. The bundled snapshot covers these H3 node types. It does not introspect a running server and is not a universal converter for arbitrary/custom/dynamic node schemas. Unsupported inputs and positional-widget gaps fail closed.
3. Omitted optional widgets stay omitted to preserve exact API inputs. The real frontend may materialize defaults when loading/saving. The offline reverse converter proves the serialized graph's requested equivalence; it does not prove browser export equivalence.
4. Linked widget removal follows the user's explicit requirement and critic guidance. Actual browser hydration, dynamic codec controls, autogrow UI behavior and rendering remain unverified. No server calls, browser load or GPU job occurred.
5. `fixed` is an explicit UI-only seed policy so opening the file does not intentionally request randomization. This policy was absent from the API and was not copied from JennieJoy content.
6. Source v001 remains a template: blank references/WAV, no upscale, no shotlist parser/log loop. Group labels and saved JSON do not establish a qualified production route or a completed film.
7. The requested Gemini review was delegated to configured role `router_custom_oauth_anti_gemini_flash_high`, route `custom/oauth-anti-gemini-flash-high`. That route alone does not independently certify the backend marketing name "Gemini 3.8".

No commit, deletion, edits to `engine/images/*` or `machine.json`, secret reads, ComfyUI server calls or GPU work were performed.
