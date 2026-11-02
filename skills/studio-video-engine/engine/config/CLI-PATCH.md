> MERGED into SKILL.md 2026-10-28
# CLI-PATCH: `jjv config contract` and `jjv frozen verify --tree` (lines root adds to `bin/jjv.py`)

`bin/jjv.py` was outside this builder's file scope and was NOT edited. `engine/config/cli.py` and `engine/frozen.py` carry
the implementation; these lines make it reachable. They were applied to a scratch COPY and exercised (see the handback).

## 1. Imports (next to `from engine.frozen import run_verify`)

```python
from engine.frozen import add_verify_arguments, run_verify  # noqa: E402   (replaces the run_verify import)
from engine.config.cli import register_config_verbs, run_config_contract  # noqa: E402
```

## 2. `build_parser()`

```python
    add_verify_arguments(verbs.add_parser("verify", help="read-only re-hash; exit 0 only if all match"))
    ...
    # right after the `validate` sub-parser is defined:
    register_config_verbs(config_verbs)
```

## 3. `_dispatch()`

```python
    if args.stage == "frozen" and args.verb == "verify":
        return run_verify(tree=args.tree, episode=args.episode)
    if args.stage == "config" and args.verb == "contract":
        return run_config_contract(args)
```

## 4. Usage

```
jjv config contract --episode E                                   # show contract + whether DELIVERY-CONTRACT.json is current (exit 1 if not)
jjv config contract --episode E --plan  [--inputs F] [--target-seconds T | --min-seconds A --max-seconds B] [--pin logo_hold=70 ...]
jjv config contract --episode E --write [same plan args] [--revision R]    # lock: episode.contract + timeline + DELIVERY-CONTRACT.json
jjv config contract --episode E --write --from-episode            # regenerate only DELIVERY-CONTRACT.json
jjv frozen verify --tree [--episode E]
```

`--plan` prints the section table on stderr and one JSON summary on stdout; a target below the sum of floors (or above what
holds and pauses can reach) exits 1 with `{"ok": false, "refused", "options": [...], "table": [...]}` and writes nothing.
`--write` backs up episode.json and DELIVERY-CONTRACT.json (`.bak-<UTC>`) and restores both if the result does not validate.
Inputs: `episode.files.contract_inputs` (schema `jjv/contract-inputs/v1`: `intro_frames`, `lines` (default: from shots.json clips +
receipt WAVs), `vocab[{term, wav|wav_s}]`, `end_line{wav|wav_s}`, `pins`, `extra`).
