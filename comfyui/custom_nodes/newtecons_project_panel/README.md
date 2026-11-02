# NEWTECONS Project Panel

Staged custom ComfyUI node pack. Five editable gold sections: screenplay/shotlist file selectors, asset-folder selector, run mode and dependent Scene/Shot selectors, aspect/generation/output presets, style and missing-image policy. The panel changes actual serialized node inputs. It does not modify `newtecons_step_ui` or infer approval from its read-only views.

**Status:** code and examples staged; not installed, browser-tested, GPU-tested, or approved for production. No live workflow, queue, historical image, or receipt was changed.

## Install on the host (operator/root, outside the worker sandbox)

1. Copy this folder to `production-local/ComfyUI/custom_nodes/newtecons_project_panel`. Keep `web`, `examples`, `core.py`, `nodes.py`, `routes.py`, and `__init__.py` together. `tests` and `tools` are optional at runtime.
2. Install `requirements.txt` into the **ComfyUI runtime** with `python -m pip install -r /opt/ComfyUI/custom_nodes/newtecons_project_panel/requirements.txt`. For the existing Docker image, add that dependency in its image build; a host pip installation does not install it in the container. NumPy, Pillow, Torch, and aiohttp come from the existing ComfyUI runtime.
3. Add `newtecons_project_panel` to the existing `--whitelist-custom-nodes` list. Preserve `--disable-partner-nodes`, the existing whitelist, and the existing single Comfyui-Studio service. Do not launch a second host ComfyUI.
4. Current `production-local/comfyui-docker/compose.yaml` does **not** mount the Story root. Add this read-only mount and mapping to that service before loading this pack:

   ```yaml
   environment:
     NEWTECONS_PANEL_PROJECT_ROOT: /projects/JennieJoyKids-Story
   volumes:
     - "../JennieJoyKids-Story:/projects/JennieJoyKids-Story:ro"
   ```

   This is a server-operator mapping of the one authorized project root. No widget or HTTP argument can change it. Native Windows uses `J:\1.JennieHomeSchool\03 Voice\production-local\JennieJoyKids-Story` by default. Relative widget paths work on both. Input/output remain the existing writable ComfyUI mounts. Restart/recreate only the existing service using the normal project operating procedure.
5. Reload the browser, add **NEWTECONS / project / NEWTECONS Project Panel**, or import `examples/S02_A-panel.workflow.json`. The old VIDEO dock remains a separate viewer; the new controls are inside the graph node.

## Episode domain and shotlist contract

The first folder below the Story root is an episode. It must have explicit `domain` in `project-panel.json`, `episode.json`, or `engine/episode.json`. If more than one exists, all declarations must agree. The existing NEWTECONS episode has `engine/episode.json` with `newtecons_live_action`.

For discovery of COMBO choices at `/object_info` time, merge this marker into the episode root, preserving existing keys:

```json
{
  "domain": "newtecons_live_action",
  "shotlists": ["panel-example/shots.csv"]
}
```

The per-node Scene/Shot options are refreshed immediately from the selected file by the server route. Runtime validation checks membership against that exact shotlist, even when an imported workflow has a value absent from the initial global combo union. `ALL` selects all scenes for Auto; One shot still requires a specific Shot. Shot IDs are globally unique across scenes.

CSV is UTF-8, with an optional BOM; XLSX reads the active worksheet. Required headers are `scene,shot,duration,prompt,refs`; optional `guide` is the frame-zero image. Headers are case-insensitive; use ASCII IDs such as `SCENE_02` / `S02_A`. `duration` is positive seconds, up to the H3 frame limit. `refs` is a JSON string array or a semicolon-separated list, with at most nine images. Relative refs and guide resolve under Folder Asset. Absolute paths are accepted only inside the configured project root. Prompts remain user-authored; the chosen domain's style is prefixed.

```csv
scene,shot,duration,prompt,refs,guide
SCENE_02,S02_A,4.458333333333333,Adult NEWTECONS engineer speaking,face.png;body.png;shirt.png,guide.png
```

Both directions of the domain guard are enforced on screenplay, shotlist, asset folder, refs, and guide. Shared `JennieJoyKids-Story` in the historical directory name never classifies NEWTECONS as cartoon. Missing/conflicting metadata fails closed. Style is enforced: NEWTECONS → Live-action photoreal; JennieJoy → 3D cartoon. This validates declared provenance, not image contents or the truthfulness of a manually edited manifest. Approval of identities, wardrobe, storyboard, and WAV stays with the existing engine; this pack never sets `approved=true`.

## Outputs and H3 wiring

| Slot | Name | Type / consumer |
|---|---|---|
| 0 | prompt | STRING → H3 prompt |
| 1 | ref_image_paths_json | STRING JSON array of **flat staged basenames**, in `<Picture n>` order |
| 2 | duration_s | FLOAT requested/minimum seconds |
| 3 / 4 | width / height | INT → H3 generation canvas |
| 5 | fps | FLOAT → CreateVideo, fixed at native H3 24 |
| 6 | length | INT → H3 frame count, snapped **up** to `17k+5` |
| 7 | receipt_json | STRING → Panel Save + Receipt |
| 8 / 9 | output_width / output_height | INT delivery/upscale targets |
| 10 | guide_image_paths_json | STRING array → Panel Load Reference, index 0 |

`NewteconsPanelH3` is a small adapter to the **installed local** `MiniMaxH3ReferenceToVideo.execute`; it takes the actual prompt, dimensions, length, and reference path outputs, loads zero to nine references, then calls native H3. This avoids stale autogrow ports when a new shot has a different number of references. It adds no cloud nodes or model loaders. With zero refs, it passes no image conditioning, yielding the native T2V path. I2V without any ref/guide is refused. For a T2V shot, remove any connected image guide/reference loader that still expects an index; the selector cannot alter unrelated graph connections.

Generation presets for landscape are 1344×768, 1280×704, and 864×480; portrait swaps them. Other aspects use H3's 32-pixel grid. Delivery dimensions for 16:9 are 1920×1080 and 2560×1440. **Output resolution is a target, not an upscaler:** connect the target outputs into the already qualified upscale stage; this pack's Save node writes the H3 video at its native generated size. No SeedVR2 pilot or qualification is implied.

Every selected input image (including `guide`) is validated and copied to `folder_paths.get_input_directory()` as:

```text
<domain>__<shot>__<sha12>__<basename>
```

No input subdirectory is used. Existing identical files are reused after full SHA-256 verification; mismatched destinations are refused and preserved. The receipt records original paths, source hashes, staged filenames, requested/actual durations, dimensions, style/domain, shotlist/script hashes, and the graph context hash.

## S02_A example

`examples/S02_A-panel.api.json` is an API graph, not an importable canvas document. `examples/S02_A-panel.workflow.json` is its editable canvas form. Both derive from the historical `workflows/H3_MOTION/S02_A-h3-f52be0d7015d-v001.workflow.json`; the source SHA is recorded in canvas metadata. No original workflow is overwritten. Historical source links had inconsistent numeric input slots, so the example rebuilds connections by semantic input names.

Copy the example `script.txt`, `shots.csv`, and `assets` folder into `Newtecons-TienDo-KichTinh-30s/panel-example/`, then supply the selected **approved** images or change the shotlist paths. The four image names are explicit placeholders, with no bundled images. Merge `examples/project-panel.json` into the episode's marker to expose its rows at startup. Select the real screenplay when using the graph for production.

Panel #100 sends prompt, refs, width, height, and length to native H3 adapter #6; #8 loads its separately staged guide; #9 keeps the existing AddGuide structure with the original S02_A `LoadAudio` #7. Models, LoRA, scheduler, seed, AV decode, and 24-fps CreateVideo #17 retain the source settings. #18 is replaced by **Panel Save + Receipt**, consuming video #17 and receipt #100 slot 7. It saves an H.264 MP4 and only then writes a hash-bound completion marker. No WAV is copied, trimmed, regenerated, or approved by this example. The operator must verify #7 against the current H3 preparation receipt before rendering.

This S02_A example uses **One shot**. Its fixed approved WAV makes it unsuitable for unattended multishot reuse. That is explicitly blocked by the Auto button until there are per-shot audio bindings. T2V/non-dialogue Auto graphs use the H3 adapter directly, with no fixed guide or audio nodes. Output resolution targets still require the existing upscale graph.

## Auto: missing shots

The Python selector always chooses the first missing shot in shotlist order within the selected scene. A terminal `NewteconsPanelSaveVideo` must be wired to the same panel's receipt. Successful writes create uniquely named media **and immutable per-render `.receipt.json` files**, plus `ComfyUI/output/newtecons-panel/<render_key>.json` as the replaceable completion index. Completion means the file still exists and its full SHA matches. Deleted, corrupt, moved, or mismatched results are missing again. Historical media and per-render receipts remain intact.

For an eligible graph, choose **Auto: missing shots**, then click **Chạy Auto**. Exactly one panel and saver are required; Auto rejects connected fixed LoadAudio/LoadImage/LoadVideo nodes and changing seeds. It checks for an idle queue, submits one immutable serialized graph, waits for that prompt's successful Save event **and** completion event, then checks for the next missing shot. Stop, errors, edits, and graph switches stop further submissions. A browser refresh ends the in-memory loop; restart it with the button. No renderer runs on import, browsing, dropdown changes, or merely selecting Auto.

The render key binds script/shotlist bytes, source image/guide hashes, generation/delivery settings, and API graph context including model names, seed and other static inputs. Actual model-file bytes are not hashed here; changing a model in place under the same filename requires operator invalidation/requalification in the engine. The completion marker is a technical render record, never an acceptance/approval receipt. If you use another SaveVideo node without the terminal receipt writer, Auto cannot identify that shot as complete. Rendering through this UI uses normal ComfyUI queue APIs; it is not an engine `jjv h3 prepare/submit` receipt or an engine GPU-lock implementation.

## Routes

All are GET, same-origin, CPU-only, and constrained to the server-configured root:

- `/newtecons/panel/browse?kind=script|shotlist|folder&path=...`: folders and extension-filtered names, never arbitrary file content. Parent traversal is unavailable at root. Canonical paths reject symlink/junction escapes.
- `/newtecons/panel/shots?shotlist=...&domain=newtecons_live_action`: normalized rows and Scene list, after domain validation.
- `/newtecons/panel/pending?...`: validates the same panel fields and reports whether a missing shot remains. It does not stage files or queue work; frontend supplies the current graph context hash.

Limits: 16 MiB source shotlist, 64 MiB expanded XLSX, 10,000 rows, 2,000 browser entries, nine refs, 128 MiB per image. Formulas are rejected; CSV/XLSX content is never executed. The server browser remains local to the server's filesystem; there is no upload or arbitrary filesystem endpoint.

## Verification

From the workspace root:

```powershell
python -m pytest docs/specs/.project-panel-node-stage/newtecons_project_panel/tests -q -p no:cacheprovider
node --check docs/specs/.project-panel-node-stage/newtecons_project_panel/web/project_panel.js
python docs/specs/.project-panel-node-stage/newtecons_project_panel/tools/build_examples.py
```

The tests use ordinary writable staging folders because pytest's mode-0700 temp ACL fails on this J: sandbox. Test artifacts are retained under `.project-panel-node-stage/test-workspaces/`. On a host without that restriction, the same command works; `python -m pip install pytest openpyxl Pillow` supplies the CPU test dependencies. The symlink test requires Windows developer mode or link privilege. Syntax/unit checks do not prove ComfyUI browser behavior, installed frontend compatibility, model availability, approved assets, or GPU render success. Perform those checks after installation on the existing instance.
