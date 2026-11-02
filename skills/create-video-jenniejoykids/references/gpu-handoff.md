# GPU ownership: VoiceStudio -> ComfyUI -> finishing

Current verified host (2026-10-18): RTX5080 16GB; VoiceStudio
http://127.0.0.1:8080, Studio http://127.0.0.1:5050 and ComfyUI
http://127.0.0.1:8188. Port3900 belongs to the historical desktop default,
not this backend instance. Alice profile8f1145d7 remains unchanged.
See [current role library](voicestudio-role-library.md) for Dad/Mom candidates.
Inspect GET/model/status, GET/model/loaded, GET/jobs?status=running&limit=5 and
GET/batch/jobs?status=running&limit=5. For canonical_voicestudio (the current Alice
project), render canonical WAVs first. For preserve_native, prepare only the
required identity/performance guides before native inference; its accepted full
native VO remains the editorial authority. Preserve complete raw native AV in
both modes. When no active
job or loading/lease exists, inspect the running OpenAPI contract and unload
loaded models with its supported endpoint (verified v0.5.6:
POST/model/unload/tts). Do not assume an old flush route exists. Measure
nvidia-smi free/used and residual backend allocations. Torch allocated/reserved,
Windows processGPU and driverfree are different metrics. Empty model inventory
or HTTP200 does not prove full release.

Wait for busy jobs up to600s,poll10s; report busy without cancellation. Before H3
verify model files, installed native schema, empty queue and pilot memory budget.
After successful pilot, require its measured incremental peak+512MiB headroom.
An OOM/failed pilot never produces an accepted budget. First pilot is explicitly
experimental. Do not kill DWM,browsers,Codex or unrelated processes for memory.

Before switching away from ComfyUI check GET/queue then the installed POST/free
contract (typically unload_models:true,free_memory:true). Re-measure driverfree.
Only use a verified supported idle backend restart if necessary and selected;
never delete Alice profile or change VoiceStudio dependencies. Serialize inference
and finishing to avoid avoidable GPU contention. Record receipts as JSON.

Prior idle VoiceStudio flush returned allocated0.75GiB/reserved1.91GiB;
driverfree4424MiB. Those are historical measurements, not a live resource budget.
