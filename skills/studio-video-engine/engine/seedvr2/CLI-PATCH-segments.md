> MERGED into SKILL.md 2026-10-28
# CLI-PATCH: `jjv seedvr2 segments`, `jjv seedvr2 tails`, `jjv seedvr2 plan --reads/--tail-map`

For root to apply to `bin/jjv.py` (the builder did not touch it). The text below was applied to a COPY of the
current `bin/jjv.py` (scratch, `SKILL_ROOT` pointed at the real skill) and exercised on ep04: `plan --reads` exit 1 /
exit 0, `segments --dry-run`, `tails plan --dry-run`, `tails --help`. All handler code is in
`engine/seedvr2/cli_cut.py`; `jjv.py` only wires it. New config keys needed: **none**.

## 1. imports (after `from engine.seedvr2 import seam_blend_run  # noqa: E402`)
```python
from engine.seedvr2 import cli_cut  # noqa: E402
from engine.seedvr2.cli_cut import add_plan_coverage_args, coverage_inputs  # noqa: E402
```

## 2. `build_parser()`
After `plan.add_argument("--segments-root", ...)`:
```python
    add_plan_coverage_args(plan)
```
After `seam_blend_run.register_cli(seedvr2_verbs)`:
```python
    cli_cut.register_cli(seedvr2_verbs)
```

## 3. `run_seedvr2_plan` (new optional `args`, old callers keep working)
```python
def run_seedvr2_plan(ref: str, out: str, segments_root: str | None, args: argparse.Namespace | None = None) -> int:
    ...
    reads, extra_scope = coverage_inputs(args) if args is not None else (None, [])
    result = build_plan(config, repo_root=REPO_ROOT, segments_root=segments, reads=reads, extra_scope=extra_scope)
```
and in `_dispatch`: `return run_seedvr2_plan(args.episode, args.out, args.segments_root, args)`.

## 4. `_dispatch` (next to the `seam-blend` branch)
```python
    if args.stage == "seedvr2" and args.verb in ("segments", "tails"):
        return cli_cut.run(args)
```

## Verbs
| Command | What it does | Exit |
|---|---|---|
| `jjv seedvr2 segments --episode E --out DIR [--plan P] [--only SHOT[:IDX],..] [--dry-run] [--no-verify-md5] [--threads N]` | cut `<shot>/chunks/<chunk>/source-segment.mp4` for the plan (default: the plan built from the config) frame-exactly with the v004 encode; re-hash/re-probe every source; md5 proof of each cut; never overwrite (an existing segment is kept only if its frames equal the source slice); hashed `segments-receipt.json` | 0 ok, 1 refused, 4 cut failed |
| `jjv seedvr2 plan ... --reads F [--tail-map MAP ...]` | before binding any source: every frame the review config reads (dialogue windows + `outgoing_tail`) must be inside each shot's clip or an assembled tail map; else refused naming the ranges | 1 on a gap |
| `jjv seedvr2 tails plan --episode E --reads F [--tail-map MAP ...] --out DIR [--scratch] [--dry-run]` | gaps -> tails plan (`kind: "tails"`): sub-range sources of the NATIVE clips with leading context, segments cut into `DIR`, plan `DIR/seedvr2-tails-plan-v2.json`; `DIR` must be fresh and INSIDE the episode tree (so `execute --execute` accepts it) unless `--scratch`/`--dry-run` | 0 (also when nothing is missing), 1 |
| `jjv seedvr2 execute --episode E --plan DIR/seedvr2-tails-plan-v2.json [--execute]` | the EXISTING executor, unchanged CLI (accepts `kind: "tails"`) | as before |
| `jjv seedvr2 tails check --episode E --plan P` | per chunk: receipts re-verify + framemd5(core) == framemd5(crop(trim(raw))); per shot: finalized concat has the planned frames | 0 green, 1 red |
| `jjv seedvr2 tails assemble --episode E --plan P --out DIR` | (check re-run, must be green) cut each gap from the shot core losslessly to `DIR/master-tails/*.mp4` and write `DIR/MASTER-TAIL-MAP.json` (`jjv/master-tail-map/v1`, ep04 keys) | 0, 1 |

## Suggested SKILL.md lines (root decides)
- verb table: add `seedvr2 segments`, `seedvr2 tails plan|check|assemble`, `seedvr2 plan --reads/--tail-map` (rows above).
- replace gap (1) in "Gaps found by the ep04 tail-restoration plan" (SKILL.md:231): `segments` cuts them; tails plans take a frame sub-range natively (`source_range`).
- ep05 flow: `plan --reads REVIEW --out P0` (refused -> `tails plan` -> execute -> `tails check` -> `tails assemble` -> `plan --reads REVIEW --tail-map MAP`).
