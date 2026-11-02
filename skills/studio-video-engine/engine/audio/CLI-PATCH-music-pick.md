> MERGED into SKILL.md 2026-10-28
# CLI-PATCH: `jjv audio music pick|adopt` and the brand-voice flag (lines root adds)

`engine/audio/cli.py` and `engine/audio/mixcli.py` are outside this builder's scope and were NOT edited (`bin/jjv.py` needs no change:
it already calls `register_audio` / `run_audio`). The implementation is `musicpick_cli.py` (+ `musicpick*.py`, `library*.py`,
`vocalstrip.py`). `tests/test_audio_library_cli.py` applies exactly the replacements below to scratch COPIES of the two files
(each anchor must occur once) and runs the verbs through them.

## 1. `engine/audio/cli.py`

```python
# imports, after:  from .recipe import optional_block, resolve_recipe
from . import musicpick_cli  # noqa: E402

# register_cli(), right before:  sfx_p = families.add_parser("sfx", help="cues | submit | finalize")
    musicpick_cli.register(msub)

# run_audio(), right before:  kind, action = args.verb, args.action
    handled = musicpick_cli.run_music_action(args)
    if handled is not None:
        return handled
```

## 2. `engine/audio/mixcli.py` (brand voice: `episode.audio.brand_voice` = `intro` (default) | `film` | `none`)

```python
# imports, after:  from .recipe import optional_block, resolve_recipe
from . import library_brand, musicpick_cli  # noqa: E402

# add_arguments(), right before the --brand-voice argument
    parser.add_argument("--library", default=None, help="library root (default: <episodes folder>/_library); brand voice registry pick")

# _plan_rows(), right before:  brand = None
    choice = library_brand.resolve(config, cli_wav=getattr(args, "brand_voice", None),
                                   cli_sha256=getattr(args, "brand_voice_sha256", None),
                                   library=musicpick_cli.library_dir(config, getattr(args, "library", None)))
    args.brand_voice, args.brand_voice_sha256 = choice.path, choice.sha256

# _plan_rows() return dict: replace  "brand": brand, "sections": rows,  with
"brand": brand, "brand_choice": choice, "sections": rows,
# _describe(): add before the "brand_voice": entry
            "brand_voice_mode": {"mode": plan["brand_choice"].mode, "source": plan["brand_choice"].source},
```

Behaviour: `intro` (default, key absent) = the film mix has NO brand voice layer and `--brand-voice` is `Refused`; `none` = same;
`film` = `--brand-voice` if given, else the library's brand-voice registry pick (file + sha256 re-verified).

## 3. Usage

```
jjv audio music pick  --episode E --out DIR [--dry-run] [--execute] [--library L] [--generator acestep|yue2] [--takes N]
jjv audio music adopt --episode E --out DIR [--execute] [--take JOB] [--demucs-python PY]
jjv audio mix ... --music-receipt DIR/music-pick.json      # library bed
jjv audio mix ... --music-receipt DIR/music-adopt.json     # generated, gated, registered bed
```

`pick` without `--dry-run` appends the film to the bed's `used_in` (versioned write: `REGISTRY.json.bak-<UTC>` + `revision`);
`--dry-run` reads everything and writes nothing. When no bed fits it writes `music-plan.json` + `music-pick.json`
(`GENERATION_PLANNED`); `adopt --execute` (or `pick --execute`) runs the GPU jobs through the guarded path, then the vocal step.
