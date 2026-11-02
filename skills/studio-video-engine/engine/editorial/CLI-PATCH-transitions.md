> MERGED into SKILL.md 2026-10-28
# CLI patch: transitions by rule (T-E42 follow-up)

Tóm tắt: các lệnh `presets list|show` và `boundaries suggest|preview|swap` đã chạy độc lập (module); file này là chỗ
root nối vào `jjv` (hai file thuộc builder khác: `bin/jjv.py`, `engine/editorial/cli.py`). Hai dòng nối + hai dòng dispatch.

## What was added (all under `engine/editorial/`, each < 400 lines)

| File | Role |
|---|---|
| `boundaries_suggest_rules.py` | the user rule as pure functions (zones, allowed presets, choice order, motion cue, direction) |
| `boundaries_suggest_measure.py` | one-frame-per-side NCC on the SOURCE clips (the Q3 function; threshold read from `recipes/qa/review-gates-v001.json`) |
| `boundaries_suggest.py` | builds `boundaries-suggested.json` (per boundary: ncc, rule, choice, alternatives, tail handle) |
| `boundaries_suggest_parity.py` | `--compare-config`: suggestion vs an approved review config's `motion.transitions` |
| `boundaries_preview.py` / `_fx.py` / `_html.py` | `preview`: short window per candidate, 1080p, CPU only (numpy + ffmpeg proxy), contact page |
| `presets_swap.py` | `swap`: versioned `boundaries.json` + segments to re-composite |
| `boundaries_suggest_cli.py` | argparse glue: `register(verbs)`, `run_boundaries(args)`, standalone `main` |
| `presets_cli.py` (extended) | `presets list`, `presets show NAME` (old flags unchanged) |

## Wiring (exact lines)

### 1. `engine/editorial/cli.py`

Change the import line

```python
from . import build
```

to

```python
from . import boundaries_suggest_cli, build, presets_cli
```

and, at the end of `register_cli(stages)` (after the `build-config` parser block, same indentation as `verbs = ...`), add:

```python
    presets_cli.register(verbs)
    boundaries_suggest_cli.register(verbs)
```

### 2. `bin/jjv.py`

Next to the other editorial import

```python
from engine.editorial.cli import register_cli as register_editorial, run_build_config  # noqa: E402
```

add

```python
from engine.editorial.boundaries_suggest_cli import run_boundaries  # noqa: E402
from engine.editorial.presets_cli import run_presets  # noqa: E402
```

and in `_dispatch`, right after the `build-config` branch

```python
    if args.stage == "editorial" and args.verb == "build-config":
        return run_build_config(args)
```

add

```python
    if args.stage == "editorial" and args.verb == "presets":
        return run_presets(args)
    if args.stage == "editorial" and args.verb == "boundaries":
        return run_boundaries(args)
```

(`run_*` raise `EngineError`; `jjv.main` already turns it into JSON + exit code, so no extra try block.)

## Commands after wiring

```text
jjv editorial presets list                              # 33 presets, 30 ready, one JSON row each
jjv editorial presets show push                         # push / dip / flash resolve to cut_push / dip_white / dip_white
jjv editorial presets --episode E --boundaries B        # unchanged: tail feasibility table (old behaviour)

jjv editorial boundaries suggest --episode E --boundaries B --out DIR [--shots shots.json] [--compare-config review-config.json]
jjv editorial boundaries preview --episode E --boundaries B --boundary T1310 --presets push,dip,cut --out GALLERY [--context-frames 24]
jjv editorial boundaries swap    --episode E --boundaries B --boundary T1310 --preset push --out WORKSPACE [--dry-run]
```

Until it is wired the same verbs run as `python -I .agents/skills/studio-video-engine/engine/editorial/boundaries_suggest_cli.py
<suggest|preview|swap> ...` and `python -I .../presets_cli.py list|show NAME`. Exit codes follow the engine contract
(0 ok, 1 a rule refused, 2 unreadable input).

## Rule in one paragraph (for SKILL.md, section "Transition presets")

`boundaries suggest` measures, on the source clips, the Q3 normalised correlation of the LAST editorial frame of the outgoing shot
against the FIRST frame of the incoming one and applies the user rule: `ncc >= 0.35` (the Q3 same-framing number) or `0.25 <= ncc < 0.35`
(near-same, calibrated on the approved v015 cut) -> hard cut + push-in (`cut_push`, 1.04 -> 1.00 over 12 f), alternatives only `cut`
(plus the dissolve family when measured same-framing AND continuity `agree`); `ncc < 0.25` -> dip / light / camera family, `whip` when a
move is declared (`g_bridge` or a motion word in the motivation), else `dip_white` (needs 1 native tail frame; with no handle it
falls back to a `whip` and says so); shots.json carries -> `none`. Output: `boundaries-suggested.json` (write-once) with
`boundaries[]` (measured, framing, rule, chosen, alternatives with `tail{needed, native_frames_needed, native_index_range,
available, reason}`) and `rows[]` in `boundaries.json` row shape (every picture row passes `transitions.check_row`).
`preview` renders only 24 f each side per candidate (proxy compositor, labelled as such; a preset the rule does not allow is still
rendered when asked and carries the verdict; a tail preset without a handle gets a card with the reason and no clip: no GPU, ever).
`swap` is data: it writes `versions/boundaries-vNNN.json` + `boundaries.json` (latest) + `swap-log.json` in a workspace folder, never the
declared table, and lists the segments (engine cut planner, before vs after) that must be re-composited.

## Limits (say them before relying on it)

* The preview is a PROXY (simple pixel maths, same window / tail / params as the catalog). The kit renderer is the final look; for
  that use `remotion-kit/tools/gallery.cjs --config <kit-config> --boundary T1310 --only cut_push,dip_white,cut`, which needs a kit config
  (built from a valid `build-config`, which the current reference episode table cannot produce: its cards and iris are still on the
  2520 f timeline).
* Graphic boundaries (intro, cards, end plate, outro) are structural: kept as declared (`R7_graphic_keep`); only the intro bloom is
  synthesized (`R8_intro_bloom`) when no row is declared. Their frames are NOT re-derived (`ending.derive_timeline` owns that).
* `LAYOUT_CHANGE_NCC_MAX = 0.25` and the motion-word list are calibrated on one episode (7 cuts). Re-measure on the next episode.
* The segment list of `swap` comes from the picture part of the timeline (shot spans + effect windows); graphic segments are never
  touched by a picture swap. The kit still computes the real dependency-slice hash.
