# CLI patch: `jjv edit master-config` (M8b f2), for root to apply

Not edited by the worker: `bin/jjv.py` and `engine/editorial/segments_edit_cli.py` (the module that owns the `edit` stage and its verbs).
New files only: `engine/edit/{__init__,master_config,master_config_cli}.py`, `tests/test_edit_master_config.py`.

## Wiring: two lines in `engine/editorial/segments_edit_cli.py` (no change to `bin/jjv.py`: the `edit` stage is already dispatched to `run_edit`)

In `register_cli`, after the `master` verb is added (end of the function):

```python
    from ..edit.master_config_cli import register_verb as register_master_config
    register_master_config(verbs)
```

In `run_edit`, first line of the body:

```python
    if args.verb == "master-config":
        from ..edit.master_config_cli import run_master_config
        return run_master_config(args)
```

Until then the same verb runs standalone:

```
python -I .agents/skills/studio-video-engine/engine/edit/master_config_cli.py --episode E --build DIR [--runs R] [--tail-map F] [--variants F] [--preview] [--out F]
```

## Verb

```
jjv edit master-config --episode E --build <folder jjv editorial build-config wrote>
    [--runs <SeedVR2 runs folder: runs/<shot>/shot.json>] [--tail-map MASTER-TAIL-MAP.json]
    [--variants variants.json] [--preview] [--out master-config.json]
```

* Reads `<build>/review-config.json` + `events.json`, the episode contract (`episode.contract`, domain `delivery.master`, `frame_rates.native_fps`).
* Final (default): every shot core must have a COMPLETED `shot.json` beside it (hash re-checked), every outgoing tail a tail-map row whose clip hash
  is re-checked; otherwise exit 1 naming each missing input, nothing written. `--preview`: missing sources are bound to the review clip /
  native tail, `master_ready: false`, `build_mode: "preview"` (the adapter then needs `--preview` too).
* Output is write-once (`<build>/master-config.json` by default); a second run with identical bytes is a no-op, a different one is refused.
* Exit: 0 written, 1 refused, 2 unreadable input (episode not resolvable).

Then: `node remotion-kit/lib/adapter-master.cjs --review-config <build>/review-config.json --events <build>/events.json --receipt <build summary.json>
--episode-root R --episode-text T --master-config <build>/master-config.json [--allow-outside LOGO] [--preview] --out kit-master.json`.
The kit carries `mode: "final" | "preview"`; `render.cjs` refuses a `preview` kit for a master render.

## One-line patch OUTSIDE this task's scope (blocks a final master for any new episode)

`remotion-kit/lib/receipts.cjs` knows ONE tail-map schema name (`mam-r27-master-tail-map/v1`, the first episode's). The engine's own
`jjv seedvr2 tails assemble` writes `jjv/master-tail-map/v1` (`engine/seedvr2/tails_assemble.py:32`). `verifyReceipt` therefore refuses an engine
tail map ("neither the tail map nor a COMPLETED receipt"), in the adapter and again in `stage()`. Change

```js
const TAIL_MAP_SCHEMA = 'mam-r27-master-tail-map/v1';
...
} else if (doc.schema === TAIL_MAP_SCHEMA) {
```
to a list `['mam-r27-master-tail-map/v1', 'jjv/master-tail-map/v1']` and `TAIL_MAP_SCHEMAS.includes(doc.schema)` (keep the exported name too).
`remotion-kit/tests/adapter-master.test.mjs` carries a `todo` test that turns green with that change.

## Duplicate to delete

`engine/editorial/master_config.py` (mtime 2026-10-28 21:55, not written by this worker, no test, no importer) is the earlier draft of the same
producer. `engine/edit/master_config.py` is the tested copy (adds: shot receipt must sit beside the core, because the adapter looks for
`shot.json` next to the clip). Root decides whether to delete the editorial one.
