# jenniejoy_claude_bridge — hybrid "Claude bridge" ComfyUI node

Node class `JJClaudeBridge` (category `JennieJoy/Authoring`). It lets an **authoring / QA graph** ask
Claude a question **without an Anthropic API key** and **without the cloud partner nodes** (they stay
disabled by `--disable-partner-nodes`; `ClaudeNode` stays refused).

It is **not** a render node: it is refused in production graphs (see "Safety").

## Inputs and outputs

| | name | type | notes |
|---|---|---|---|
| in | `prompt` | STRING multiline | required, non-empty |
| in | `system` | STRING multiline | may be empty |
| in | `mode` | `auto` / `cache_only` / `chat` / `router` | default `auto` |
| in | `timeout_s` | INT | default 600 (1..86400); chat wait or gateway HTTP timeout |
| in (opt) | `image` | IMAGE | each frame saved as `images/<pixel-sha256>.png` in the shared folder |
| out | `answer` | STRING | |
| out | `receipt` | STRING | JSON: route, model reported, timestamps, request/response sha256, image hashes |

## Resolution order (deterministic)

1. **Cache first.** Key = sha256 of the canonical JSON of `{schema, system, prompt, image pixel hashes}`.
   `mode` and `timeout_s` are *not* part of the key. A hit returns the stored answer and the stored
   receipt byte for byte (the receipt keeps the original route); nothing is called again.
   `IS_CHANGED` returns the key, so ComfyUI re-runs the node only when the inputs that matter change.
   Cache files are written once and never replaced (`cache/<key>.json`); a corrupt or hash-mismatched
   entry is a loud error, never a silent re-ask.
2. `auto` = cache -> **chat** if the MCP heartbeat is younger than 120 s -> **router** if configured ->
   **loud error** (`NoRouteAvailable`). There is no cloud fallback of any kind. A chat timeout in
   `auto` does *not* fall through to the router (the request stays pending; answer it later and re-run).
3. `cache_only`: a miss is an error. `chat` / `router` force that route.

## Route "chat" (Claude Code chat via MCP, no key)

Shared folder `<shared>/claude-bridge/` (`<shared>` = host `production-local/ComfyUI/user`, seen in the
container as `/opt/ComfyUI/user`; override with `JJ_BRIDGE_SHARED`):

```
inbox/<key>.json    request written by the node       outbox/<key>.json   answer written by the MCP
cache/<key>.json    answer + receipt (deterministic)   images/<sha>.png     input images
heartbeat.json      refreshed ONLY by bridge_wait / bridge_pending / bridge_answer
```

The node writes the request and polls the outbox once a second (the ComfyUI Cancel button interrupts
the wait). The `jenniejoy-comfy` MCP server (`../../mcp/jenniejoy_comfy_mcp.py`) exposes:

* `bridge_pending(request_id?)` - list unanswered requests, or read one in full (read-only);
* `bridge_wait(timeout_s<=100)` - block until something is pending while keeping the heartbeat fresh;
* `bridge_answer(request_id, answer, confirm="ANSWER", model_reported?)` - atomic temp+link write to the
  outbox; refuses unknown ids, already-answered ids, ids that are not 64 lowercase hex characters
  (path traversal), empty answers, and never overwrites.

For the chat route to be usable the Claude Code chat must be "serving" the bridge: call `bridge_wait`
in a loop, then `bridge_pending(request_id)` -> write the answer -> `bridge_answer`. Only those three tools
refresh the heartbeat; any other MCP call (`comfy_status`, `episode_receipts`, ...) does not make the chat
look live, so `auto` never waits for a chat that is not serving the bridge. If the chat is idle for more
than 120 s the heartbeat goes stale and `auto` stops choosing chat.

**Shared-folder split.** The node sees the folder as a container path (default `/opt/ComfyUI/user`), the MCP
as a host path (default `production-local/ComfyUI/user`, or `JJ_BRIDGE_SHARED` in the MCP's own
environment). They must be the same physical folder; a mismatch means requests are never answered.
Setting `JJ_BRIDGE_SHARED` for one side only is the usual way to break this.

**Clock.** The heartbeat stores a unix timestamp that the node reads inside the container. Host and Docker
Desktop VM clocks are assumed to agree. A heartbeat more than 5 s in the future is treated as not live
(skew can never make a dead chat look alive), but skew the other way can make a live chat look stale.

**Link safety.** Every path is checked against the `claude-bridge` root (not a sub-folder): symlinks,
junctions and any reparse point inside that tree (the root included) are refused, and every resolved path
must stay inside the resolved root. Known limits: the check-then-open sequence is best effort (a process
running as the same user can still swap a folder between the check and the open, so this stops accidents and
misconfiguration, not a hostile same-user process); and ANY reparse attribute is refused, including benign ones
such as OneDrive/cloud placeholders, so keep `claude-bridge` out of synced folders (the default
`production-local/ComfyUI/user` is fine). Files are fsync'd and published atomically (hard-link publish; on a
filesystem without hard links an exclusive create, which readers retry on unreadable JSON).

## Route "router" (your own gateway, quota-controlled token)

OpenAI-compatible call to New-API (`:3300`) or 9Router (`:20128`) through `host.docker.internal`. Plain
`http` is accepted only for `localhost`, `127.0.0.1`, `::1` and `host.docker.internal`; any other host needs
`https`. Redirects are never followed, environment proxies are ignored and responses over 4 MiB are
refused, so the token can only reach the configured host. `timeout_s` is both the socket timeout and a TOTAL deadline
for the whole call (a gateway trickling bytes is cut off at `timeout_s`; the abandoned request thread ends on
its own socket timeout).
Configuration comes only from the container environment (an env file you fill; never in git, never
logged, never written to cache/receipts, redacted from error messages):

| variable | example |
|---|---|
| `JJ_BRIDGE_BASE_URL` | `http://host.docker.internal:3300` (a trailing `/v1` is accepted) |
| `JJ_BRIDGE_MODEL` | model name your role token is allowed to use |
| `JJ_BRIDGE_TOKEN` | your New-API / 9Router role token (NOT an Anthropic key) |
| `JJ_BRIDGE_API` | optional: `chat` (default, `/v1/chat/completions`) or `responses` (`/v1/responses`) |

Gateway facts measured 2026-10-27 (status only, no key): New-API `GET /v1/models` -> 401 JSON
`{"error":{...,"type":"new_api_error"}}`; 9Router `GET /v1/models` -> 401
`{"error":"API key required for remote API access"}` (requests arriving through
`host.docker.internal` count as remote, so a token is mandatory); both reachable from inside
`Comfyui-Studio`. Both also answer 401 on an unauthenticated `POST /v1/chat/completions` and `POST /v1/responses`;
the 401 comes before routing, so which of the two shapes a given upstream model accepts is **not
verified** until a real token is used (see INSTALL.md smoke test). Per earlier notes the codex-router
exposes only `/v1/responses`: use `JJ_BRIDGE_API=responses` for it. `stream` is sent as `false`.

## Safety

* Authoring/QA graphs only. `JJClaudeBridge` is in `forbidden_node_classes` of both domains
  (`studio-video-engine/domains/*.json`, enforced by `engine/config/rules.py`), in the engine's
  always-refused list, and (after root applies `staged/`) in the guarded submit helper's hard deny
  list, which `--partner-ok` cannot override. It must also stay out of every domain's
  `allowed_custom_nodes`.
* Answers are not reproducible by re-asking; they are reproducible by the cache. Treat an authoring
  answer as a recorded input (copy it into a prompt/graph as a literal) before it influences a render.
* The shared folder is trusted input: ids are validated, paths are resolved and checked to stay inside
  `claude-bridge/`, but anyone who can write the folder can answer a request.

## Tests

```
python -m pytest custom_nodes/jenniejoy_claude_bridge/tests            # core, node, router, simulation
python custom_nodes/jenniejoy_claude_bridge/tests/simulate_end_to_end.py  # scripted host simulation
python -m pytest ../mcp                                                # MCP side
python -m pytest custom_nodes/jenniejoy_claude_bridge/staged           # staged helper refusal
```

Install steps (for after the running 4K job): `INSTALL.md`.
