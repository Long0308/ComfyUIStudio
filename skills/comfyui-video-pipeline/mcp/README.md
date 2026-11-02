# jenniejoy-comfy MCP

`jenniejoy_comfy_mcp.py` exposes the shared local ComfyUI engine to MCP clients
over newline-delimited JSON-RPC 2.0 on stdio. It uses only the Python standard
library, supports MCP protocol versions `2025-06-18`, `2025-03-26` and
`2024-11-05`, and requires **Python 3.12+**, matching
`.agents/skills/comfyui-video-pipeline/scripts/comfy_guarded_submit.py`.

This is shared engine infrastructure for both domains:

- `jenniejoy_cartoon_3d`: JennieJoyKids cartoon films.
- `newtecons_live_action`: NEWTECONS live-action films.

The domains do not share cast, prompts, anchors or acceptance criteria.

## Tools

| Tool | Access | Purpose |
| --- | --- | --- |
| `comfy_status` | GET only | Container state, `/queue`, `/system_stats` VRAM and argv. It does not touch the helper-owned production submission lock. |
| `comfy_validate_graph` | GET only | Graph SHA-256, API-format check, `/object_info/<class>` lookup, and partner/denied-node report. |
| `comfy_submit_guarded` | Guarded POST | Delegates to the reviewed helper's `submit` path. Requires `confirm: "SUBMIT"` and the exact graph SHA-256. |
| `comfy_job` | Read only | Reads `dispatch-intent.json`, `submitted.json`, `submit-unknown.json`, `submit-rejected.json`, `reconciled.json` and `job.json`; optionally GETs prompt history. |
| `comfy_reconcile` | GET only (network); writes local receipts | Resolves an existing intent by `client_id` through GET `/queue` and GET `/history`; never POSTs. The helper writes `reconcile-report.json` (and `reconciled.json` when found) in the receipt dir, so it is annotated `readOnlyHint: false`, `destructiveHint: false`. |
| `seedvr2_run_status` | Read only | Compares a v004-style plan with receipts, telemetry, failures, ETA, executor PID, `runs/.executor.lock`, and invalid path-like IDs. |
| `episode_receipts` | Read only | Lists contained `job.json` and `preparation.json` receipts with prompt ID, status and output SHA-256. |
| `bridge_pending` | Read only | Claude bridge: list unanswered `JJClaudeBridge` requests from the ComfyUI node, or read one in full by `request_id`. |
| `bridge_wait` | Read only (refreshes the heartbeat file) | Claude bridge: block up to `timeout_s` (max 100 s) until a request is pending, refreshing the heartbeat. Set the client tool timeout above 100 s (the Gemini example below uses 30 s: pass `timeout_s` <= 25 there). |
| `bridge_answer` | Writes one outbox file | Claude bridge: publish the answer for one pending `request_id`. Requires `confirm: "ANSWER"`; atomic, write-once, refuses unknown/answered/malformed ids. Annotated `readOnlyHint: false`, `destructiveHint: false`. |

Every tool returns structured JSON as MCP text content. Read tools carry
`readOnlyHint: true`; `comfy_submit_guarded` carries
`destructiveHint: true`.

## Safety rules

- The default URL is `http://127.0.0.1:8188`.
  `JENNIEJOY_COMFY_URL` may override it only with a loopback host:
  `127.0.0.1`, `localhost` or `::1`.
- There is no environment or CLI lock-path override. The production code always
  uses the helper's `DEFAULT_LOCK_PATH`. Tests monkeypatch the imported helper
  and never acquire the production lock.
- Every supplied graph, receipt, plan and episode path must resolve under
  `J:\1.JennieHomeSchool\03 Voice`.
- Receipt patterns reject `..`, drive letters, leading separators and absolute
  paths. Every glob match is resolved and must remain under both the workspace
  root and the supplied episode directory before it is opened.
- `shot_id` and `chunk_name` must be safe single path components before they are
  joined under `runs/`.
- Only `comfy_submit_guarded` can POST, and only after the exact `SUBMIT`
  confirmation and helper checks for graph hash, denied nodes, shared lock,
  idle queue and exclusive intent.
- `partner_ok` is always false; there is no cloud-partner bypass.
- Never resubmit after an uncertain outcome. Inspect `comfy_job` and run
  `comfy_reconcile`; the helper's outcome-unknown receipt is authoritative.

## Claude bridge (T-E21)

The three `bridge_*` tools serve the authoring-only `JJClaudeBridge` ComfyUI node
(`../custom_nodes/jenniejoy_claude_bridge/`, see its README). Logic lives in that pack's
`bridge_core.py`, loaded lazily by path, so a missing pack only disables these tools.
Only `bridge_wait`, `bridge_pending` and `bridge_answer` refresh `<shared>/claude-bridge/heartbeat.json`, so the
node can tell a chat is serving the bridge (other tool calls deliberately do not); `<shared>` is `JJ_BRIDGE_SHARED` or `production-local/ComfyUI/user`. Writes are limited
to that folder (heartbeat, outbox answers) and never touch ComfyUI, the submit lock or any graph. The test
`conftest.py` points `JJ_BRIDGE_SHARED` at a temp folder so tests never write into the live folder.

## Shared submission lock

Per ADR-2 in
`production-local/JennieJoyKids-Story/04-milk-and-mom/technical/engine-plan-r27/ENGINE-GENERALIZATION-PLAN.md`,
the machine-wide lock currently lives at:

`production-local/JennieJoyKids-Story/04-milk-and-mom/technical/.comfyui-image-submit.lock`

NEWTECONS submissions use the same lock. The lock location is machine-wide, not
an episode-04-only policy. Moving it requires an idle-GPU switch-over and
migration of every dispatcher.

`seedvr2_run_status` accepts an explicit `plan_path`, but when omitted it
defaults to the ep04 production plan
(`technical/seedvr2-production-v004/PRODUCTION-PLAN.json`). That default is
documentation, not an implied authorization to submit or to reuse the
JennieJoy recipe for NEWTECONS.

## Submission lifetime

`comfy_submit_guarded` does not block the stdio loop waiting for a GPU job. It
passes `hold_timeout=0.0` to the reviewed helper: the helper retains the
O_EXCL lock for its idle-queue check, intent creation and POST, writes
`submitted.json`, and then returns the real `prompt_id`. Long-running execution
is monitored separately with `comfy_job`, `comfy_reconcile`, queue/history GETs,
and executor receipts. The empty-queue-under-lock gate remains in force.

## Client registration

Use the absolute server path and **`python -I`**. Do not set
`PYTHONIOENCODING`; the server configures stdin/stdout as UTF-8 itself.

### Claude Code project `.mcp.json`

```json
{
  "mcpServers": {
    "jenniejoy-comfy": {
      "type": "stdio",
      "command": "python",
      "args": [
        "-I",
        "J:\\1.JennieHomeSchool\\03 Voice\\.agents\\skills\\comfyui-video-pipeline\\mcp\\jenniejoy_comfy_mcp.py"
      ],
      "env": {
        "JENNIEJOY_COMFY_URL": "http://127.0.0.1:8188"
      }
    }
  }
}
```

### Claude Code CLI

Run from the workspace root:

```powershell
claude mcp add --transport stdio --scope project jenniejoy-comfy -- python -I "J:\1.JennieHomeSchool\03 Voice\.agents\skills\comfyui-video-pipeline\mcp\jenniejoy_comfy_mcp.py"
```

### Codex `config.toml`

```toml
[mcp_servers.jenniejoy-comfy]
command = "python"
args = ["-I", "J:\\1.JennieHomeSchool\\03 Voice\\.agents\\skills\\comfyui-video-pipeline\\mcp\\jenniejoy_comfy_mcp.py"]

[mcp_servers.jenniejoy-comfy.env]
JENNIEJOY_COMFY_URL = "http://127.0.0.1:8188"
```

### Gemini CLI settings

```json
{
  "mcpServers": {
    "jenniejoy-comfy": {
      "command": "python",
      "args": [
        "-I",
        "J:\\1.JennieHomeSchool\\03 Voice\\.agents\\skills\\comfyui-video-pipeline\\mcp\\jenniejoy_comfy_mcp.py"
      ],
      "env": {
        "JENNIEJOY_COMFY_URL": "http://127.0.0.1:8188"
      },
      "timeout": 30000,
      "trust": false
    }
  }
}
```

## Verification

The regression suite launches the server exactly as registered with
`python -I jenniejoy_comfy_mcp.py`, with no `PYTHONIOENCODING`. It uses a fake
GET/POST counter and does not contact port 8188:

```powershell
python -m pytest production-local/JennieJoyKids-Story/04-milk-and-mom/technical/mcp-build-r27/staged-v2/mcp/test_jenniejoy_comfy_mcp.py -q -p no:cacheprovider --basetemp production-local/JennieJoyKids-Story/04-milk-and-mom/technical/mcp-build-r27/pytest-v2
```

The live smoke is GET-only and records the exact JSON-RPC transcript at
`production-local/JennieJoyKids-Story/04-milk-and-mom/technical/mcp-build-r27/live-smoke-v2.json`.
