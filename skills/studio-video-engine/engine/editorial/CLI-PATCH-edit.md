> MERGED into SKILL.md 2026-10-28
# CLI patch: `jjv edit review-render` / `jjv edit master-render` (T-E45 edit path, audit gap 4), for root to apply

I edited none of `bin/jjv.py`. New files only:

| File | Role |
|---|---|
| `engine/editorial/segments_edit_cli.py` | argparse + node command line: `register_cli(stages)`, `run_edit(args)`, standalone `main` |
| `remotion-kit/tools/edit-render.cjs` | the work: build-config -> kit adapter -> segment build -> film + run report |
| `tests/test_editorial_segments_edit_cli.py` | wiring, command line, refusals (6 tests, no render) |

## Wiring (exactly two lines in `bin/jjv.py` + one import line)

Import, next to the other stage imports (after `register_timing`'s import line):

```python
from engine.editorial.segments_edit_cli import register_cli as register_edit, run_edit  # noqa: E402
```

In `build_parser`, after `register_editorial(stages)`:

```python
    register_edit(stages)
```

In `_dispatch`, after the `editorial build-config` branch:

```python
    if args.stage == "edit":
        return run_edit(args)
```

Until then the same thing runs standalone:

```
python -I .agents/skills/studio-video-engine/engine/editorial/segments_edit_cli.py review-render ...
node .agents/skills/studio-video-engine/remotion-kit/tools/edit-render.cjs --mode review ...
```

## Verbs

```
jjv edit review-render --cache C (--out film.mp4 | --explain)
    --episode-root R --episode E/engine/episode.json --boundaries B --word-timing W --episode-text T
    [--allow-outside LOGO]... [--browser CHROME] [--workdir D] [--build-concurrency 1|2] [--build-mode inproc|children]
    [--force-segment ID,ID] [--rehash-all] [--no-hash-cache] [--overwrite] [--segments-file S]

jjv edit master-render --cache C (--out film.mp4 | --explain) --master-config KITMASTER.json
    (--segments-file S | --episode E --boundaries B --word-timing W --episode-root R)  [same optional flags]
```

What `review-render` runs, in order (each step's command and seconds are in `<out>.edit-run.json`):

1. `python -I bin/jjv.py editorial build-config ...` into `C/engine/current` (write-once folder, replaced each run) -> `review-config.json`,
   `events.json`, `segments.json`, and the receipt-bound build summary (`C/engine/summary.json`, the stdout of the verb).
2. `node remotion-kit/lib/adapter-engine.cjs ...` -> `C/kit-config.json` (engine records + `--episode-text`, hash-verified bindings).
3. `node remotion-kit/render.cjs --segments-build C/segments --segments-file C/engine/current/segments.json ...`: node key per segment,
   render only the stale ones (one staging, one bundle, one browser), one audio mix only if its slice changed, join by stream copy with the
   framemd5 proof, run record `<out>.segments-run.json` (per segment: key, status, reason, seconds; `composite_only`; `hash_cache`).

`--explain` runs steps 1-2 and prints the stale table (ids, ranges, `RENDER|COMPLETE|CORRUPT`, the changed leaf paths); renders nothing.

`master-render` does NOT build the master config: the master kit config (4K cores, seam blends and tails bound with receipts) comes from the
master adapter once the master is ready (`remotion-kit/episodes/<episode>/adapter-master-*.cjs`); pass it with `--master-config`. The segment cut
list is the engine's `segments.json` (`--segments-file`, or the engine inputs to build it). Without `--master-config` the verb refuses by name.
Master keys include mode / scale 2 / crf 16 / the 4K bindings' shas, so a master segment never reuses a review entry.

## Exit codes

`0` built (or explained). `1` refused or failed: the message is on stderr, nothing is written to `--out` (a corrupt cached segment, a binding
whose hash changed, a join whose framemd5 column differs, a missing `--master-config`, a step that failed). `2` usage (a missing required flag).

## Cache layout (`--cache C`, safe to delete; deleting it only costs a cold build)

```
C/engine/current/        build-config output of the last run (review-config.json, events.json, segments.json)
C/kit-config.json        adapter output of the last run
C/segments/composite.segment/<key>/{segment.mp4, record.json, ...}   one entry per node key
C/segments/audio.mix/<key>/{mix.wav, ...}
C/segments/hash-cache.json   verified-hash cache: sha256 per {path, size, mtime ns, inode}; --rehash-all audits it
C/segments/last-run.json, segments-run.json
```
