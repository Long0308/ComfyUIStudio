# CLI-PATCH: `jjv seedvr2 adopt` (SV2-GAP2, closes ENGINE gap 2 of SeedVR2)

For root to apply to `bin/jjv.py` (the builder did not touch it, `engine/run/**`, `engine/health/**` or any
config). All handler code is in `engine/seedvr2/adopt.py`; `jjv.py` only wires it. New config keys: **none**.
Exercised without `bin/jjv.py`: `tests/test_seedvr2_adopt.py` drives `adopt.register_cli` + `adopt.run` through a
local argparse and then runs the REAL `jjv seedvr2 execute --execute` (fake ComfyUI) on the adopted plan.

## 1. import (after `from engine.seedvr2 import cli_cut  # noqa: E402`)
```python
from engine.seedvr2 import adopt  # noqa: E402
```

## 2. `build_parser()` (after `cli_cut.register_cli(seedvr2_verbs)`)
```python
    adopt.register_cli(seedvr2_verbs)
```

## 3. `_dispatch` (next to the `segments`/`tails` branch)
```python
    if args.stage == "seedvr2" and args.verb == "adopt":
        return adopt.run(args)
```

Nothing else changes: `run_seedvr2_plan` keeps calling `refuse_output_inside(...)` with the same list; the
precision fix lives inside that function (`engine/seedvr2/plan.py`, see below).

## Verb
| Command | What it does | Exit |
|---|---|---|
| `jjv seedvr2 adopt --episode E --plan DIR_or_FILE [--segments-root SEG] [--into DIR]` | loads the scratch plan exactly as `execute` would (`load_exec_plan`: identity, status `PLANNED_NOT_RENDERED`, recipe-derived windows), proves every API graph (canonical sha == plan, == pilot except the two ports) and every bound segment (sha256 == plan) BEFORE writing anything, then copies plan + graphs + segments into `--into` with no-overwrite writes and records `ADOPT.json` (`jjv/seedvr2-adopt/v1`: sha256 + size of every adopted file, plan sha, source folder, segments root; no timestamp). Default `--into`: `<episode root>/engine/stages/seedvr2/<plan stem>-<plan sha12>` (the orchestrator's stage folder). `--into` must be inside the episode root, not the root itself or its `engine/` folder, and not inside/equal/above the Comfy tree, the segments root or the scratch folder; a non-empty `--into` without `ADOPT.json` is refused. Re-adopting identical bytes is a no-op (`already_adopted: true`, every file re-verified); any drift is refused (`refusing to overwrite`). Prints `plan_path` to hand to `execute`. CPU only, no ComfyUI, scratch folder read-only. | 0 ok, 1 refused (no recipe / foreign or pending plan / bad graph, segment, destination), 2 unreadable JSON |

Flow (ep05): `segments --out SEG` -> `plan --segments-root SEG --out SCRATCH [--reads ...]` -> review -> `adopt --plan SCRATCH --segments-root SEG` -> `execute --plan <printed plan_path> [--execute]`. A tails plan (`seedvr2-tails-plan-v2.json`) adopts the same way (its segments are in its folder).

## Protected-tree check made precise (`engine/seedvr2/plan.py`, no CLI change)
`refuse_output_inside(out, protected, *, containers=None, label="--out")`: the repo root and the episodes root
(`<repo>/production-local`, the folder `loader.find_episode_file` searches) are *containers*: refused only when
`--out` IS one or sits ABOVE one. Inside a container only the precise trees of the list (episode root, Comfy root,
segments root) and any *episode tree* (a folder holding `engine/episode.json`) are refused. Result: a scratch
folder under `production-local/engine/staging/` (pytest `--basetemp`, `jjv run --scratch`) is accepted,
`production-local/<film>/<other episode>/...` is still refused, `production-local` itself and the repo root still
are. The three CLI tests that failed with `--basetemp` inside staging pass now (plan 2, hardening 1).

## Suggested follow-ups (root / Fable #2 decide; not done here)
- `recipes/run/episode-dag-v001.json` stage `seedvr2`: replace the `known_gap` work-around with steps
  `plan --out {scratch}/seedvr2-plan ...` -> `adopt --plan {scratch}/seedvr2-plan --into {stage:seedvr2}/plan`
  -> `execute --plan {stage:seedvr2}/plan/seedvr2-plan-v2.json --execute`; receipts
  `{stage:seedvr2}/plan/ADOPT.json`, `{stage:seedvr2}/plan/runs/run-state.json`. NOTE the DAG's `plan` step has no
  `--segments-root`, so its plan is `PLANNED_SEGMENTS_PENDING` and both `adopt` and `execute` refuse it: a
  `segments --out` step (and `plan --segments-root`) is still missing from the DAG.
- SKILL.md: verb table row for `seedvr2 adopt`; mark ENGINE gap (2) RESOLVED; the "Known gaps" line about
  `--out` (`production-local` / repo root) now reads "may not be inside the episode tree, Comfy root or segments
  root, may not be `production-local`/the repo root or above them, and may not sit in another episode tree".
- `engine/seedvr2/execute.py` `Executor.graph_for` now delegates to `execplan.verify_task_graph` (one definition
  of "graph is bound", shared with adopt); behaviour unchanged, covered by the executor/resume/runtime tests.
