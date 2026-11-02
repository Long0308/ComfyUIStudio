# ComfyUI literal prompt transport review

Installed frontend **1.55.17**. Read-only source inspection and offline Node VM; no GPU, browser, network request, production queue or server changes.

## Confirmed failure

`formatUtil-grDslll6.js` defines `processDynamicPrompt`. Its first operation strips block/line comments using `/\/\*[\s\S]*?\*\/|\/\/.*/g`; it then interprets braces/pipes as choice blocks. Consequently `https://` becomes `https:` and removes the remainder of a single-line JSON body. `core-xNT6jFNV.js` installs this function as `serializeValue` for widgets marked dynamic. H3's prompt is explicitly marked `dynamicPrompts: true`.

Exact parser extraction SHA256: `1ff08dd2cfdda9fe63ee27c2b4b47213c26bced43f606b53c244898209b7865c`. Extraction covers only that named function, ending before `function isValidUrl`. Full file hashes/paths are in the paired JSON report.

Reproduced the submitted v6r2 queue strings with the **actual installed function**:

| Node | Intended UTF-16 characters | Submitted | Exact reproduced UTF-8 hash match | Full cast/action survived |
|---|---:|---:|---|---|
| 6 | 11229 | 2040 | True | No |
| 1006 | 11397 | 2046 | True | No |

The relevant job is `34e8b8aa-d71b-493d-b2da-1ff9f10e9bc5`; evidence files are `shots/S01-paired-entry-v6/workflow-r2/workflow-gui.json` and `run/queue-submitted.json`. Intended complete cast/action disappeared before inference. Static workflow/schema approval did not cover this UI serialization transformation. Historical v3 retained cast/action because its JSON used multiple lines, although braces were still removed. Historical v4 used a flattened body and also lost cast/action after the URL.

## Reviewed solution

Use concrete server node **PrimitiveStringMultiline**, with raw unchanged prompt in `inputs.value`, linked to H3 `inputs.prompt`. Core node19 remaps to1019 for B. The installed schema has multiline STRING without a dynamic flag; `nodes_primitive.py` returns its value unchanged. The frontend widget constructor does not add the flag implicitly. The dynamic extension therefore never installs a parser on this literal widget. `graphToPrompt` assigns resolved connected input links after its widget-value pass, so the H3 prompt connection wins over any unused H3 widget value.

Do not substitute virtual `PrimitiveNode`, whose input specs can be merged. Setting a widget flag false after creation is insufficient: the extension has already installed its serializer. No JSON escaping, backend patch, restart or global setting change is required.

The builder now preserves all source cast/action/URL/braces/pipe/quote content in the literal node and records the node ID/transport in provenance. Guide chains, original sampler latents, canonical editorial WAV and full native AV routing remain intact.

## Validation and acceptance

**106 tests ran in9.473 seconds: OK, no skips.** COMFYUI_ROOT explicitly pointed to the installed ComfyUI, so the new Node regression exercised the actual formatter/extension and saved widget specs. It demonstrates corruption on the dynamic widget and exact preservation on the literal widget.

Verdict: **APPROVE** the literal transport code. Before accepting any new costly run, inspect the actual submitted graph: H3 prompt links must be19/1019; both literal values must match expected full prompt hashes, including complete cast/action. This is still required after real GUI import; an offline serializer test does not itself prove the next live submission.

## Actual v7 static preflight

APPROVE:58nodes, graph SHA256 `b77e3f030b725a131d6d134e6c9c9a52e689aef416f95dd9a03de2deb2213eea`. Current builder/config reconstruct every execution input; API/GUI match; installed node schema passes; staged assets and metadata Markdown paths exist. Both literal nodes retain complete three-person descriptions and action:19 has11229characters,1019 has11397. All 0/60/119 guides, actual A119→B0 seam, sampler latents,5s canonical editorial WAVs and full native AV sinks remain correct. Details/hashes are in the JSON report. Actual submitted payload and generated movement still require verification.
