# H3 domain qualification

`routes-v001.json` keeps previously qualified domains on `allowed_domains`. A domain under
`qualification_required` must pass its own receipt check, even if it also appears in that list. Its
`receipt.path` is relative to the repository root and `receipt.sha256` is the SHA-256 of the receipt
file's bytes. A missing file, null pin, changed file, invalid contents, or another domain is refused.

The NEWTECONS path in the route is a reserved location, **not evidence that a pilot has run**. It has
no receipt and its pin is deliberately null. After an actual user-authorised local H3 GPU pilot has
passed, the responsible operator can place the real qualification receipt at that path and record its
file hash in the route. The engine never writes or fabricates the qualification itself.

A `jjv/h3-qualification/v1` receipt is a JSON object with these fields:

| Field | Required content |
| --- | --- |
| `schema`, `stage`, `domain`, `status` | `jjv/h3-qualification/v1`, `h3`, the exact domain ID, and `PASS` |
| `pilot.executor`, `pilot.user_authorized` | `comfyui-local` and `true` |
| `pilot.prompt_id` | Non-empty ID of the actual local pilot |
| `pilot.graph_sha256` | SHA-256 of the pilot API graph file bytes |
| `pilot.template_sha256` | SHA-256 of the API template file bytes used for later shots |
| `pilot.allowed_override_ports` | Unique list of `NODE.input` strings the pilot qualification permits in the manifest's `mouth` object |

For a qualified route, prepare checks the template hash, permits media bindings only to matching
`LoadImage.image` and `LoadAudio.audio` inputs, and permits only `filename_prefix` output ports. It
preserves each template prefix below the route's `output_prefix_root`, adding episode, shot, graph
content hash, and output index. The receipt binding is copied to `preparation.json` and checked again
before submit/adopt. The legacy cartoon route retains its existing `h3/...` prefix and receipt shape.

The engine checks the receipt's attested fields and file hashes. It does not independently prove that
the GPU ran, validate the pilot graph file against `pilot.graph_sha256`, or enforce numeric bounds on
values supplied to allowed override ports. Those are matters for the pilot evidence and review; an
allowed port alone must not be interpreted as qualification for arbitrary values.
