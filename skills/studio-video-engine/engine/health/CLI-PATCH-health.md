# CLI patch for `jjv health preflight` (T-E39), for root to apply into `bin/jjv.py`

Worker: Fable 5.1 (astra worker), 2026-10-28. Status at hand-over: **in_review** (root re-runs the gate).

I edited none of `bin/jjv.py`, `engine/h3/**`, `engine/comfy/**`, `engine/cli_runtime.py`, `engine/audio/cli.py`, the schemas,
recipes, domain files or `production-local/engine/machine.json`.

* New: `engine/health/{__init__,docker_facts,comfy_facts,fixture,preflight,cli}.py`, `tests/test_health_preflight.py`,
  `tests/test_health_preflight_wiring.py`, this note.
* Touched (1 import + 1 call line each; backups with before/after sha256 under
  `production-local/engine/staging/T-E39/backup/`): `engine/images/local.py`, `engine/seedvr2/execute.py`, `engine/audio/jobs.py`.
* Touched, grey area (not in my file list, flagged in the report): `tests/conftest.py` gains ONE autouse fixture (see 5).

## 1. `bin/jjv.py` (three lines)

```python
# imports, after:  from engine.h3.cli import register_cli as register_h3, run_h3  # noqa: E402
from engine.health.cli import register_cli as register_health, run_health  # noqa: E402
```

in `build_parser`, after `register_h3(stages)`:

```python
    register_health(stages)
```

in `_dispatch`, before the final `return 2`:

```python
    if args.stage == "health":
        return run_health(args)
```

`tests/test_health_preflight.py::test_health_registers_next_to_every_existing_jjv_stage_without_a_name_clash` loads the real
`bin/jjv.py` parser and adds the registration only if it is not wired yet, so it passes before and after the patch.

## 2. Verb

```
jjv health preflight (--episode E | --base-url U --container C) [--graph GRAPH.api.json] [--min-free-vram-mib N]
                     [--fixture FIXTURE.json] [--timeout S]
```

Read-only: `docker version`, `docker inspect --format ... <container>`, `GET /system_stats`, `GET /queue`,
`GET /object_info/<class>` per class of `--graph`. It never POSTs, interrupts, frees memory, starts, stops or restarts anything.
Exit 0 ready / 1 not ready (nothing was queued) / 2 an input is unreadable (episode, fixture, graph; `bin/jjv.py main` maps
`Uncertain`/`ConfigViolation` to 2). One JSON document on stdout, schema `jjv/health-preflight/v1`:

| key | meaning |
|---|---|
| `ready` | every check `ok` |
| `queued` | always `false` (the verb can not queue) |
| `mode` | `live` or `dry` (`--fixture`) |
| `checks[]` | `docker_engine`, `container_identity` (name == machine config, running, restart policy `unless-stopped`, launched with `--disable-partner-nodes`), `comfy_http` (`/system_stats` answers; when it reports `argv`, that argv must carry the flag too), `queue_idle` (running + pending from `/queue`), `vram_free` (min `vram_free` over devices vs `--min-free-vram-mib`), `required_nodes` (every graph class known to `/object_info`, none a partner/API node). Each failed check carries `detail.problem` and `next_step` (addressed to the operator); a check whose prerequisite failed is `skipped: true` and counts as failed |
| `failed`, `problems` | names / one line per failed check |

`--fixture` is the dry form (`jjv/health-fixture/v1`, shape documented in `engine/health/fixture.py`): the same collection and
evaluation code runs with the document standing in for docker and ComfyUI (no subprocess, no HTTP).

## 3. Where the execute paths call it now (`engine.health.preflight.require_ready`, `Refused` exit 1 before any intent)

| path | call site | VRAM minimum |
|---|---|---|
| `images submit --provider comfyui-local` (real submit only; `--dry-run` never reaches it) | `engine/images/local.py` `submit`, right before `_live_preflight` | recipe `min_free_vram_mib` (krea2: 10240) |
| `seedvr2 execute --execute` (every fresh dispatch, incl. a LOST re-dispatch; resume of COMPLETED chunks makes no request) | `engine/seedvr2/execute.py` `process_chunk`, right before `dispatch(...)`, AFTER `job.json` is written `PREPARED` (exactly where the old idle-queue refusal fired, so `mark_failure` records `FAILED / prior PREPARED` and `--resume` re-dispatches cleanly; placing it earlier made `tests/test_seedvr2_resume.py::test_resume_of_a_pre_post_failure_redispatches_cleanly` exit 2, measured) | `recipe.get("min_free_vram_mib", 0)` (the seedvr2 recipe has no key yet: 0 = report only) |
| `audio music/sfx submit --execute` (READY jobs only; PENDING/COMPLETED never reach it) | `engine/audio/jobs.py` `run_job`, right before `cmd_submit` | `0` (audio recipes have no key yet) |

The refusal message keeps the substrings the older guards used (`free VRAM ...`, `ComfyUI queue is busy (running=R, pending=P)`,
`partner/API node`), so the existing images/audio tests see the same words. Evidence: `{"stage": "health_preflight", "report": {...}}`
(the seedvr2 `stopped.stage` reads `health_preflight`).

## 4. TODO for M7 / M8 (H3; not edited by me)

`engine/h3/submit.py` `submit()`, inside the per-shot loop, currently:

```python
        report, ready = commands.cmd_check(client, settings, ps=ps)
        if not ready:
            raise Refused(...)
```

Replace (or precede) with the shared gate, keeping `commands.cmd_check` only if its lock-sentinel check is still wanted:

```python
from ..health.preflight import require_ready
...
        require_ready(client, settings, graph=graph, min_free_vram_mib=0)  # T-E39; add an H3 route minimum when routes-v001 carries one
```

`tests/h3/**` get the healthy container from the `tests/conftest.py` autouse fixture (5); a test that wants a sick container
monkeypatches `engine.health.docker_facts.default_runner` (pattern: `tests/test_health_preflight_wiring.py::bad_container_runner`).

## 5. Test harness (one autouse fixture in the top `tests/conftest.py`; no second conftest)

`engine.health.docker_facts.default_runner` delegates to `engine.comfy.docker_probe.default_runner` at call time, so without any
fixture the existing tripwire turns every health probe into "docker engine unreachable" (refused, never the real CLI). The new
autouse fixture `_health_preflight_sees_a_healthy_fake_container` replaces the health runner with a fixture-backed one that
answers ANY container name as healthy (running, `unless-stopped`, `--disable-partner-nodes`), so the images/audio/seedvr2 submit
tests keep posting against their fake ComfyUI. `tests/test_health_preflight_wiring.py` proves both halves (healthy default, and
that `_real_default_runner` still hits the tripwire).

## 6. Follow-ups (not done; out of this task's scope)

* `engine/comfy/commands.cmd_check` (`jjv comfy check`) still runs its own three checks via `docker ps`; it could delegate to
  `run_preflight` so the verb and the gate can not drift.
* Per-recipe VRAM minimum keys: `recipes/seedvr2/*.json` and `recipes/audio/*.json` (schema change, M3); the call sites already read
  `min_free_vram_mib` when present. `recipes/h3/routes-v001.json` likewise.
* `engine/images/local._live_preflight` still re-reads VRAM and object_info after the gate (harmless duplicate GETs, kept to leave
  that file a two-line diff).

## 7. SKILL text for root to merge (studio-video-engine SKILL.md)

* Verb index row: `| health | `health preflight (--episode E \| --base-url U --container C) [--graph F] [--min-free-vram-mib N] [--fixture F]` (read-only docker + ComfyUI gate; exit 0 ready / 1 not ready, nothing queued) |`
* M4 runtime table row: `| `engine/health/{docker_facts,comfy_facts,fixture,preflight,cli}.py` | T-E39 engine-level health preflight: `docker version`/`inspect` (name, running, `unless-stopped`, `--disable-partner-nodes`), `/system_stats` (HTTP up, argv flag, free VRAM vs recipe minimum), `/queue` idle, `/object_info` per graph class (missing custom node named, partner refused). `require_ready` is called by images local submit, seedvr2 execute and audio submit before any intent; H3 TODO (M7/M8). Dry form from a `jjv/health-fixture/v1` document. Never starts/stops/restarts/interrupts anything. |`
* Rules: the health gate is READ-ONLY; when it refuses, the operator fixes docker/ComfyUI by hand (the engine never restarts the
  container, never frees VRAM, never interrupts the queue).
