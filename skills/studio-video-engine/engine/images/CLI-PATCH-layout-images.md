> MERGED into SKILL.md 2026-10-28
# CLI + config patch for `jjv layout` / `jjv images` (Q-2, hybrid image route), for root to apply

I edited none of `bin/jjv.py`, `engine/config/**`, `engine/qa/**`, `engine/editorial/**`, voice, audio, remotion-kit, the schemas,
`production-local/engine/machine.json` or the domain files. New files only:

* `engine/layout/{__init__,context,tool,cast,plan,check,render,cli}.py`
* `engine/images/{__init__,receipts,common,plan,krea2,gui,local,openrouter,codex,pool,adopt,native,compare,approve,imgutil,cli}.py`
* `recipes/images/{routes-v001,krea2-edit-local-v001,openrouter-gpt-image-v001,codex-exec-v001}.json`
* `.agents/skills/comfyui-blender/scripts/bpy_layout_passes_template.py` (new file; `bpy_layout_template.py` untouched)
* `tests/{test_layout_plan_check,test_layout_render,test_images_flow,test_images_local,test_images_openrouter,test_images_codex}.py`,
  `tests/images_fixtures.py`, `tests/fake_codex.py`

## 1. `bin/jjv.py` (applied to a scratch copy and parsed: `jjv layout --help`, `jjv images --help` work; diff below)

```python
# next to the other stage imports, after "end plan stage"
from engine.layout.cli import register_cli as register_layout, run_layout  # noqa: E402
from engine.images.cli import register_cli as register_images, run_images  # noqa: E402
```

in `build_parser`, after `register_plan(stages)`:

```python
    register_layout(stages)
    register_images(stages)
```

in `_dispatch`, before the final `return 2`:

```python
    if args.stage == "layout":
        return run_layout(args)
    if args.stage == "images":
        return run_images(args)
```

`tests/test_images_flow.py::test_layout_and_images_register_next_to_every_existing_jjv_stage_without_a_name_clash` loads the real
`bin/jjv.py` parser and adds the two registrations only if they are not already wired, so it passes before and after the patch.

## 2. Machine config (`machine.schema.json` is closed: add these keys, then `production-local/engine/machine.json`)

```jsonc
"tools":  { "blender_exe": "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" },   // layout render
"images": {
  "codex_bin": null,                       // optional; string path or argv list; default: `codex` on PATH ($CODEX_BIN, --codex-bin)
  "codex_state_path": "<engine>/staging/codex-pool-state.json",   // optional; default <images folder>/codex-pool-state.json
  "codex_accounts": [                      // PATHS and LABELS only. The engine only checks that <codex_home>/auth.json EXISTS
    { "label": "acct1", "codex_home": "C:/Users/Admin/.codex/codex-router/chatgpt-accounts/acct_GnCMJcEABPyyCzU4" },
    { "label": "acct2", "codex_home": "C:/Users/Admin/.codex/codex-router/chatgpt-accounts/acct_gJ_TqCQDX1E4UoXD" },
    { "label": "acct3", "codex_home": "C:/Users/Admin/.codex/codex-router/chatgpt-accounts/acct_-LFRMCyD9iGu8l8m" },
    { "label": "acct4", "codex_home": "C:/Users/Admin/.codex/codex-router/chatgpt-accounts/acct_kuNjf89O0ZvRGKoL" }
  ]
}
```

The four homes above are the pool's four `state: active, paused: false` accounts (read from the router's own pool bookkeeping:
ids/state/paused/priority only; no email or token was copied). Order = sticky preference at first run: acct1 is the router's
currently selected account. `--codex-account LABEL=HOME` (repeatable) overrides the list for one call (used for the live smoke).
Until the keys exist `machine.json` is read WITHOUT schema validation by these two stages, so nothing breaks; the keys are
simply absent. Blender is also found through `--blender` / `$BLENDER` / PATH.

## 3. Domain files (optional, tighten only)

`domains/<id>.json` may gain `"images": {"allowed_providers": [...]}`; it can only narrow the list in
`recipes/images/routes-v001.json` (the domain table lives in that recipe so engine source stays domain-neutral; a domain that is
not listed there has no provider at all). Today: the cartoon domain allows `comfyui-local, openrouter, codex-adopt, codex-exec`;
the live-action domain allows only `comfyui-local` (openrouter / codex-adopt / codex-exec are refused BEFORE any file or network access).
> Superseded 2026-10-30 (task N01, user decision): NEWTECONS uses routes-v002 — comfyui-local + codex-exec + codex-adopt; openrouter still refused. See SKILL.md line 11.

## 4. Verbs, exit codes and what they write

Exit: 0 ok, 1 refused (nothing sent), 2 uncertain, 4 execution failed. Every submit is a NEW take folder (never reused); every
result is a write-once receipt `<out>/<shot>/candidates/<sha12>.receipt.json` (`jjv/image-receipt/v1`) next to the exact PNG.

| Verb | CPU/GPU | Writes |
|---|---|---|
| `layout plan --episode E --out L [--cast F --map ROLE=ID --allow-unbound]` | CPU | `L/set.json`, `L/briefs/<cut shot>.brief.json` (status from the domain row, `provenance.jjv_scaffold.filled=false`), `L/layout-plan.json` (shas of cast refs and of the shared tool) |
| `layout check --layout L [--allow-draft]` | CPU | `storyboard-check.json`, `continuity-plan.json`, `placement/<shot>.txt`; exit 1 for a scaffold/draft/invalid brief or an incomparable pair; a continuity MISMATCH is reported with its allowed transitions, not an error |
| `layout render (--layout L \| --brief B --out O) --shot S --passes beauty,depth,mask` | beauty: GPU lock + free-VRAM gate; depth/mask: CPU | `render/<shot>/rNNN/` guide PNG, `-depth.png` (16-bit), `-depth-raw.npy`, `-mask-id.png`, `-mask-<id>.png`, `-passes.json`, `.blend`, `render-receipt.json` |
| `images plan --episode E --out I [--layout L] [--shot ..] [--guide S=PNG] [--placement S=TXT] [--ref S:ROLE=PATH]` | CPU | `I/images-plan.json` |
| `images submit --provider comfyui-local --pilot [--task general\|identity --seed N]` | GPU | take `local/tNNN/` (prompt, cast sheet, `graph.api.json`, `graph.gui.json`, `graph.review.gui.json`, `comfy/` dispatch receipts) + candidate receipt. Refused without `--pilot` while the recipe is `unqualified` |
| `images submit --provider openrouter --spend-ok [--budget-usd X]` | network, paid | take `openrouter/tNNN/` (`request.json`, `intent.json`, `response-meta.json`, `output.png`, or `failure.json`/`unknown.json`) + candidate receipt; `OPENROUTER_API_KEY` from the environment only; HTTP 401/402/403/429 write `I/openrouter-STOP.json` and every later call is refused until a human removes it |
| `images submit --provider codex-exec [--codex-account L=H ..] [--timeout S]` | network (the user's ChatGPT login) | take `codex-exec/tNNN/` + candidate receipt (account LABEL, every failover, runtime id = Codex session id when printed) + `I/codex-pool-state.json` |
| `images adopt --route codex-builtin --file PNG --prompt-file P (--refs-from-plan \| --ref ROLE=PATH)` | CPU | candidate receipt (`resolved_model` and `runtime_id` null) |
| `images compare --shot S [--sha ..]` | CPU | `compare/compare-<digest>.png` + `.json`, `compare/checklist.json` (reviewer fills `pass`/`fail`; re-runs never overwrite a reviewed entry) |
| `images approve --shot S --sha X --reviewer R --scope T` | CPU | `approvals/approval-vNNN.json`; needs a `pass` for all six items for that exact sha |
| `images native --shot S --sha X [--center-crop --allow-unapproved]` | CPU | `native/<shot>-native864-<sha12>.png` + receipt (needs a current approval unless `--allow-unapproved`) |

`--dry-run` (submit) prepares and saves the graph / request / prompt+argv and sends nothing. `--machine` is a hidden test hook.

## 5. Skill text for root to merge (studio-video-engine SKILL.md)

* Image routes: `comfyui-local` (Krea2 edit, pilot-gated), `openrouter` (paid, `--spend-ok`), `codex-adopt` (hand-made, hash-bound),
  `codex-exec` (GPT OAuth through `codex exec`, account pool, no token ever read). A PNG without a receipt is not an anchor:
  `compare`, `approve` and `native` refuse a sha that has none. Approvals bind a sha and go stale if the bytes change.
* NEWTECONS (live action) is local-only: the other three providers are refused by the routes recipe.
> Superseded 2026-10-30 (task N01, user decision): NEWTECONS uses routes-v002 — comfyui-local + codex-exec + codex-adopt; openrouter still refused. See SKILL.md line 11.
* Layout passes come from CPU ray casts (`scene.ray_cast`), not from a render engine, so they exist on a machine whose Workbench
  has no pass output and need no GPU; the beauty guide still needs the lock and free VRAM.

## 6. Interplay to know about

* `engine_tree_sha256` covers `engine/**` and `recipes/**`: adding these files changes it. Episodes pin it as `null` today.
* `tests/test_config_hardening.py::test_engine_source_is_neutral_except_the_named_frozen_guard` forbids the strings `jenniejoy`,
  `newtecons`, `04-milk-and-mom`, `ep04` in `engine/**.py`; the new code obeys it (domain names live only in the routes recipe).
  That test is red before this patch because of `audio/library.py`, `audio/vocalstrip.py`, `qa/preflight_audio.py`, `voice/approval.py`.
