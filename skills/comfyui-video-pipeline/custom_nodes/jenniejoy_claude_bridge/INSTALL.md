# INSTALL (for root, AFTER the running SeedVR2 4K job has finished and the user says OK)

Nothing here has been run. The pack lives only under
`.agents/skills/comfyui-video-pipeline/custom_nodes/jenniejoy_claude_bridge/`. All paths below are relative
to the workspace root `J:\1.JennieHomeSchool\03 Voice`.

## 0. Preconditions (read-only checks)

1. `GET http://127.0.0.1:8188/queue` has no running or pending job, and
   `production-local/JennieJoyKids-Story/04-milk-and-mom/technical/.comfyui-image-submit.lock` does not exist.
   `seedvr2_run_status` (MCP) shows the run finished; the executor PID file's process is gone.
2. User OK to recreate `Comfyui-Studio` (a compose change needs a recreate, which stops the container).
3. Re-run the suites and keep the output: `mcp`, `scripts`, `studio-video-engine`, pack `tests`, pack `staged`.

## 1. Apply the staged guarded-helper change (frozen file, so only after the run)

`scripts/comfy_guarded_submit.py` is listed in `studio-video-engine/FROZEN-EP04.json` (sha256
`752077d372d0eefa904561a641a2ff060b46b8a17f4e5c65181d9b7b2aa886a7`, 30230 bytes when staged). Back up BOTH the
helper and the freeze record first, with their hashes, and verify the backups before overwriting anything.

```powershell
$skill = ".agents\skills\comfyui-video-pipeline"
$engine = ".agents\skills\studio-video-engine"
$rc = "production-local\comfyui-docker\runtime-receipts"
$stamp = Get-Date -Format yyyyMMddHHmmss
New-Item -ItemType Directory -Force $rc | Out-Null

# 1a. the live helper must still be the frozen one
(Get-FileHash "$skill\scripts\comfy_guarded_submit.py" -Algorithm SHA256).Hash   # expect 752077D372D0EEFA904561A641A2FF...
python .agents\skills\studio-video-engine\bin\jjv.py frozen verify               # must exit 0 BEFORE the change

# 1b. back up helper + freeze record, record sha256, verify the copies
$helperBak = "$rc\comfy_guarded_submit-before-jjbridge-$stamp.py"
$frozenBak = "$rc\FROZEN-EP04-before-jjbridge-$stamp.json"
Copy-Item "$skill\scripts\comfy_guarded_submit.py" $helperBak
Copy-Item "$engine\FROZEN-EP04.json" $frozenBak
foreach ($pair in @(@("$skill\scripts\comfy_guarded_submit.py", $helperBak), @("$engine\FROZEN-EP04.json", $frozenBak))) {
  $a = (Get-FileHash $pair[0] -Algorithm SHA256).Hash; $b = (Get-FileHash $pair[1] -Algorithm SHA256).Hash
  if ($a -ne $b) { throw "backup mismatch for $($pair[0])" }
  "$b  $(Split-Path $pair[1] -Leaf)" | Add-Content "$rc\jjbridge-backups-$stamp.sha256"
}

# 1c. the staged copy must be exactly the reviewed one (sha256 reported by the builder), then apply it
$stagedSha = (Get-FileHash "$skill\custom_nodes\jenniejoy_claude_bridge\staged\comfy_guarded_submit.py" -Algorithm SHA256).Hash
if ($stagedSha -ne "83319B12D8CBEEB3911926163F924BE185907F23D9E10B06A95E10996F50B5A2") { throw "staged helper changed: $stagedSha" }
Copy-Item "$skill\custom_nodes\jenniejoy_claude_bridge\staged\comfy_guarded_submit.py" "$skill\scripts\comfy_guarded_submit.py" -Force
# (or patch -p1 < staged\comfy_guarded_submit.diff; the diff paths are workspace-relative)
$env:JJ_HELPER_PATH = (Resolve-Path "$skill\scripts\comfy_guarded_submit.py")
python -m pytest "$skill\custom_nodes\jenniejoy_claude_bridge\staged\test_jjclaudebridge_refusal.py" -q
python -m pytest "$skill\scripts" -q          # the 36 existing helper tests
```

Then update the `comfy_guarded_submit.py` entry of `FROZEN-EP04.json` (new sha256 `83319b12...b5a2` and
30388 bytes, if the staged copy is unchanged) so the freeze guard stays truthful, and re-run
`jjv.py frozen verify` plus the `studio-video-engine` tests.

## 2. Copy the pack into the live custom_nodes (no compose volume change needed)

`production-local/ComfyUI` is bind-mounted read-only at `/opt/ComfyUI`, so a host copy is visible at once.

```powershell
robocopy ".agents\skills\comfyui-video-pipeline\custom_nodes\jenniejoy_claude_bridge" `
  "production-local\ComfyUI\custom_nodes\jenniejoy_claude_bridge" /E /XD tests staged __pycache__ .pytest_cache /XF INSTALL.md
```

(The shared folder `production-local/ComfyUI/user/claude-bridge/` is created on first use; `user` is already a
read-write mount, so no extra mount is required. Set `JJ_BRIDGE_SHARED` only to relocate it.)

## 3. Env file for route "router" (user fills; skip if only the chat route is wanted)

```powershell
Copy-Item ".agents\skills\comfyui-video-pipeline\custom_nodes\jenniejoy_claude_bridge\env.example" `
  "production-local\comfyui-docker\jj-bridge.env"
# user edits: JJ_BRIDGE_MODEL, JJ_BRIDGE_TOKEN (role token from New-API/9Router; NOT an Anthropic key)
```

Do NOT set `JJ_BRIDGE_SHARED` in this file unless you also set the matching host path for the MCP: the
node (container path) and the MCP (host path) must point at the SAME folder, otherwise requests are written
where nobody answers. Keep `jj-bridge.env` out of git and out of chat/logs. If the user wants chat-only, leave the token empty:
`auto` then simply never picks the router.

## 4. compose.yaml edit (back it up first)

```powershell
Copy-Item "production-local\comfyui-docker\compose.yaml" `
  "production-local\comfyui-docker\runtime-receipts\compose-before-jjbridge-$(Get-Date -Format yyyyMMddHHmmss).yaml"
```

Edit `production-local/comfyui-docker/compose.yaml`:

* append `"jenniejoy_claude_bridge"` to the `--whitelist-custom-nodes` list (keep every existing entry and
  keep `--disable-partner-nodes` and `--disable-all-custom-nodes`);
* add under the `comfyui` service (Compose >= 2.24; `required: false` keeps it optional):

```yaml
    env_file:
      - path: jj-bridge.env
        required: false
```

## 5. Recreate and verify

```powershell
docker compose -f production-local\comfyui-docker\compose.yaml up -d      # recreates because config changed
# wait for healthy, then:
curl http://127.0.0.1:8188/object_info/JJClaudeBridge     # expect category "JennieJoy/Authoring", output answer+receipt
curl http://127.0.0.1:8188/object_info/ClaudeNode         # still {} (partner nodes stay off)
curl http://127.0.0.1:8188/system_stats                   # argv contains the whitelist entry and --disable-partner-nodes
docker exec Comfyui-Studio printenv JJ_BRIDGE_BASE_URL    # never print JJ_BRIDGE_TOKEN
```

### Rollback (byte-for-byte)

```powershell
# compose + container
Copy-Item <the compose backup from step 4> "production-local\comfyui-docker\compose.yaml" -Force
docker compose -f production-local\comfyui-docker\compose.yaml up -d
Remove-Item -Recurse -Force "production-local\ComfyUI\custom_nodes\jenniejoy_claude_bridge"
# helper + freeze record, from the step 1b backups; verify against the recorded hashes
Copy-Item $helperBak "$skill\scripts\comfy_guarded_submit.py" -Force
Copy-Item $frozenBak "$engine\FROZEN-EP04.json" -Force
Get-Content "$rc\jjbridge-backups-$stamp.sha256"
(Get-FileHash "$skill\scripts\comfy_guarded_submit.py" -Algorithm SHA256).Hash   # must equal 752077D3...
python .agents\skills\studio-video-engine\bin\jjv.py frozen verify               # must exit 0
```

## 6. Smoke test (authoring graph only, never a render graph)

1. Restart the MCP client so it lists the three new tools (`bridge_pending`, `bridge_wait`, `bridge_answer`).
2. Chat route: in ComfyUI (UI) run a graph with `JJ Claude Bridge`, `mode=chat`; in the Claude Code chat loop
   `bridge_wait` -> `bridge_pending(request_id)` -> `bridge_answer(..., confirm="ANSWER")`. Run it again: the
   console says `cache hit` and the answer/receipt are identical.
3. Router route (if configured): `mode=router` with a tiny prompt; check the receipt `route`, `model_reported`,
   `gateway_host`, and that the token appears in no file under `production-local/ComfyUI/user/claude-bridge/`.
   If the gateway rejects the shape, switch `JJ_BRIDGE_API` between `chat` and `responses`.
4. Prove the refusal: `comfy_validate_graph` on a graph containing `JJClaudeBridge` must list it under
   `partner_or_denied_classes`; `comfy_guarded_submit.py submit --partner-ok` must exit 1 and POST nothing.
