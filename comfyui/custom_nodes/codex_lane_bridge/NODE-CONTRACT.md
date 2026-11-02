# codex_lane_bridge — NODE CONTRACT (stable; wire against this, do not guess)

Pack folder: `production-local/ComfyUI/custom_nodes/codex_lane_bridge/` (whitelisted in
`production-local/comfyui-docker/compose.yaml` `--whitelist-custom-nodes ... codex_lane_bridge`).

## Node

| field | value |
|---|---|
| class_type (API / `NODE_CLASS_MAPPINGS` key) | `CodexOAuthImageLane` |
| display name | `Codex OAuth Image Lane (cloud GPT — not local GPU)` |
| category | `NEWTECONS/codex (cloud GPT)` |
| route | CLOUD GPT image tool through Codex OAuth lanes on the host. **Not local GPU inference.** Each Run spends ChatGPT quota. |

### Inputs (names are stable)

| name | type | required | default | notes |
|---|---|---|---|---|
| `prompt` | STRING (multiline) | yes | `""` | empty → error, nothing sent |
| `count` | INT | yes | 10 | 1..10 (the bridge refuses >10) |
| `episode` | STRING | yes | `Newtecons-TienDo-KichTinh-30s` | episode slug / root / episode.json path as the HOST sees it |
| `kind` | COMBO | yes | `SHOT` | `SHOT FACE ACTION ASSET SET FIX`; FACE/ACTION are locked to 3:4 by the routes recipe: the prompt must say `3:4` exactly once |
| `refs` | IMAGE | optional | — | up to 8 frames of the batch are sent as PNG refs (Image 1 = first ref). **Non-empty `refs` REPLACE the domain wardrobe preset** (explicit override; cannot be combined with `context`) |
| `ref_role` | STRING | optional | `identity` | role written for every ref |
| `timeout_seconds` | INT | optional | 3600 | node gives up waiting (the host job keeps running) |
| `context` | COMBO | optional | `(default)` | wardrobe preset of the host bridge: `cong_truong` (site: shirt + helmet + logos + vest), `van_phong` (office: shirt + colour logo); `(default)` = the domain's `default_context`. Without `refs` EVERY take carries the preset; the bridge refuses the job (HTTP 400) when a member file is missing or its sha256 differs from the registry |
| `company_wardrobe` | IMAGE | optional | — | up to 4 uploaded company-wardrobe frames, ADDED to the preset (role `company_wardrobe`) |
| `scene_ref` | IMAGE | optional | — | first frame is sent as the scene/location ref (role `scene_location`) |
| `prompts` | STRING (multiline) | optional | `""` | ONE PROMPT PER LINE (blank lines dropped, order kept). When non-empty it OVERRIDES `prompt` and `count`: image i is made from line i, `count` = number of lines. >10 lines or blank-only text -> error, nothing sent |

### Outputs

| index | name | type | content |
|---|---|---|---|
| 0 | `images` | IMAGE | batch of every image the job made (resized to the first image's size if sizes differ) |
| 1 | `job_info` | STRING | JSON: job_id, state, made/asked, `ref_set` (`source` preset/override/none, `context`, `refs[]` name+role+sha256+origin attached to every take), per-image `input_relpath`/`sha256`/`account_label`, errors |

With `prompts`, `images` is in line order (01_..10_) and `job_info.items[]` lists per prompt `index, prompt_sha256, prompt_id, lane, status (pending/running/done/failed), output_sha256, receipt`. A lane that fails hands its prompts to the healthy lanes; a prompt no lane could run is `failed` (job `partial`).

A job with 0 images raises (the error text carries the lane errors). A `partial` job returns the images it made.

## Bridge URL and secret

* URL: env `CODEX_BRIDGE_URL`, default `http://host.docker.internal:8797` (Docker Desktop forwards it to the host
  loopback; the bridge binds `127.0.0.1:8797` only).
* Secret: first readable of env `CODEX_BRIDGE_SECRET_FILE`, `/run/codex-bridge/secret` (compose mounts
  `../engine/bridge` there read-only), `bridge.secret` next to `__init__.py`. Sent as `Authorization: Bearer …`;
  never logged. The host file is `production-local/engine/bridge/secret` (folder gitignored by its own `.gitignore`).
* Host side: `python -I .agents/skills/studio-video-engine/bin/jjv.py bridge serve` (accounts allow-list from
  `production-local/engine/bridge/config.json`).

## HTTP routes (for a UI panel)

| route | body | answer |
|---|---|---|
| `GET /v1/health` | — (no secret) | `{ok, routes, accounts}` |
| `POST /v1/images/codex` | `{episode, prompt_text, n<=10, kind, prompt_id?, client_id?, refs?:[{role, png_base64 \| path}] (override), context?, wardrobe_refs?:[...], scene_ref?:{...}}` OR `{episode, prompts:[1..10 strings, each <= 8000 chars], kind, ...}` (not both; `n` ignored) | 202 `{job_id, state, n}` |
| `POST /v1/video/shot` | `{episode, out, verb: run\|render\|status, shot?, revision?, route?, gpu_approved?, dry_run?, timeout?}` | 202 `{job_id, state:"running", pid, argv}`; 409 while another video job runs |
| `GET /v1/jobs/<job_id>` | — | job document: `state` queued/running/done/partial/failed/interrupted, `images[]` or video `exit_code/result/gate` |

Video is **never** a graph node: `jjv video run` submits to this same ComfyUI, so a node waiting on it would deadlock
the executor. A UI panel (page JS) must NOT hold the secret; it calls the same-origin proxy this pack registers on the
ComfyUI server (secret read server-side):

| panel calls (ComfyUI origin) | proxies to |
|---|---|
| `GET /codex_lane/health` | `GET /v1/health` |
| `POST /codex_lane/video/shot` (same JSON body) | `POST /v1/video/shot` |
| `GET /codex_lane/jobs/<job_id>` | `GET /v1/jobs/<job_id>` |

Example: `fetch('/codex_lane/video/shot', {method:'POST', headers:{'Content-Type':'application/json'},
body: JSON.stringify({episode, out, verb:'run', dry_run:true})})` then poll `/codex_lane/jobs/<job_id>` every few
seconds. Without the user's own `gpu_approved` (`token:<text>` or a receipt path) the engine stops at its
`gpu-approval` gate (job `done`, `exit_code` 0, `result.ok:false`, `gate.user_gate:true`): the bridge never invents one.

## Security notes (CR-BRIDGE, 31/10)

* Bind: only `127.0.0.1`, `::1` or `localhost` (anything else, LAN IPs included, is refused before any state exists).
* `--accounts` can only NARROW `config.json`'s allow-list (intersection); `acct1`/`acct2` are refused outright.
* Video `episode`/`out`: `..` parts are refused; paths must resolve inside the workspace root (default `production-local/`; a bare slug is allowed for `episode`).
* `jobs/` folders: chmod 0700 and secret 0600 on POSIX. **Windows: not applied** (`os.chmod` does not change NTFS ACLs); the review measured `Authenticated Users: Modify` inherited on the state folder. Tighten by hand: `icacls <state> /inheritance:r /grant:r %USERNAME%:(OI)(CI)F`.
* **Open item (root's call, NOT applied):** `compose.yaml` mounts the whole `../engine/bridge` folder at `/run/codex-bridge` (`:ro`). Read-only stops writes, not reads: any process or custom node in the ComfyUI container can read `secret` AND `config.json` (and `jobs/`). Proposal: mount only the secret file, e.g. `../engine/bridge/secret:/run/codex-bridge/secret:ro`, and keep `config.json` and `jobs/` host-side (the node needs only the secret; `client.SECRET_FILES` already reads `/run/codex-bridge/secret`).
