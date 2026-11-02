> MERGED into SKILL.md 2026-10-28
# CLI + consumer patch for `jjv icons` / `jjv text` (T-E44, audit gap 10), for root to apply

I edited none of `bin/jjv.py`, `editorial/build.py`, `captions.py`, `sources.py`, `segments*`, `remotion-kit/`, the schemas
(other builders own them). New files only: `engine/editorial/icons*.py`, `episode_text*.py`, `recipes/editorial/icons-v001.json`,
`recipes/editorial/episode-text-v001.json` (a second recipe: scope extension, see report), tests `test_icons_*.py`,
`test_episode_text_*.py`.

## 1. `bin/jjv.py`

Imports, next to the other stage imports:

```python
from engine.editorial.icons_cli import register_cli as register_icons, run_icons  # noqa: E402
from engine.editorial.episode_text_cli import register_cli as register_text, run_text  # noqa: E402
```

In the parser builder, after `register_editorial(stages)`:

```python
    register_icons(stages)
    register_text(stages)
```

In `_dispatch`, after the `editorial build-config` branch:

```python
    if args.stage == "icons":
        return run_icons(args)
    if args.stage == "text":
        return run_text(args)
```

Verified without this patch by wiring the same `register_cli`/`run_*` pairs into a throw-away argparse parser (the tests do the
same, `tests/test_icons_cli.py`, `tests/test_episode_text_build.py`).

## 2. `schemas/episode.schema.json` (closed `files` object; changes the episode hash, apply after the tails GPU run)

Add two optional keys next to `shot_pack`, both `{"$ref": "#/$defs/engine_relative_json"}`:

```json
"icon_registry": {"$ref": "#/$defs/engine_relative_json"},
"script": {"$ref": "#/$defs/engine_relative_json"}
```

Until then every verb takes `--registry` / `--script` explicitly (the CLI reads `episode.files.icon_registry` and
`episode.files.shot_pack` only when declared; `shot_pack` already exists).

## 3. Consumers that must read the registry instead of file names

### `engine/editorial/build.py`
* **L102** `captions.check_vocabulary_list(timing, document["icons"])` -> compare the word-timing `vocabulary_icons` with
  `registry["icons"]` ids (`icons.load_registry(path)`), not with `document["icons"]["terms"]`.
* **L106** `icon_root = require_scoped(root / document["icons"]["dir"], ...)` -> delete; load the registry once:
  `registry = icons.load_registry(root / document["icons"]["registry"])`.
* **L107-108** `captions.icon_events(..., document["icons"], icon_root, fps, rel, offsets=...)` -> pass `registry`.
  Gate before use: `icons_check.validate_registry(registry, root=root, recipe=icons.load_recipe()[0], ffmpeg=...)` and refuse
  on `ok == False` (build-config then cannot bind one image to two words: E_SHARED_ICON / E_DUP_IMAGE).

### `engine/editorial/captions.py`
* **L86** `declared = {item["icon"]: item["term"] for item in icons["terms"]}` -> `{entry["id"]: entry for entry in registry["icons"].values() if entry["kind"] == "spoken"}`.
* **L92-99** `name = word["vocab_icon"]` / `path = icon_root / name` / `if not path.is_file()` -> `entry = registry["icons"][word["vocab_icon"]]`
  (word timing must name the icon ID `warm`, not `warm.png`; until the word-timing recipe emits ids, accept
  `entry["file"] == vocab_icon` as a transition), `path = root / entry["png"]`.
* **L103-104** `"icon": name, "icon_path": rel(path), "icon_sha256": sha256_file(path)` -> `"icon": entry["file"]`
  (keeps the events schema), `"icon_path": entry["png"]`, `"icon_sha256": entry["sha256"]` (no re-hash at build time; the registry
  gate already hashed it).
* **L110** `uncovered = sorted(set(declared) - ...)` -> `registry["terms"]` spoken icons without an event.
* **L120-128** `check_vocabulary_list` -> same swap as above.

### `engine/editorial/sources.py` L183-184 (`cards`)
The card row gets the card icon from the registry: `row["icon"] = icons.icon_ref(icons.icon_for_card(registry, card["term"]))`
(the hand-built v015 config already carries `outro_cards[].icon{path,sha256}`; the engine-built one does not).

### `schemas/boundaries.schema.json` L268-300 (`icons` block)
Replace `required: ["dir", "terms", ...]` with `["registry", "hold_frames", "fade_frames", "pop_frames", "lead_frames"]`,
`registry` = a `$ref: #/$defs/path` (episode-relative `icons.json`); drop `dir` and `terms`.
`engine/editorial/boundaries.py` `load_document` no longer needs `icons.terms`. ep04 `engine/boundaries.json` L`icons` block still
points at `assets3d/vocabulary-v002/png` with the shared `warm-cold.png` (this is why the engine-built ep04 cut cannot show
warm/cold icons): switching it to `"registry": "../technical/icons-registry-v001/icons.json"` is the data change that
moves the engine build to the v003 set the hand-built v015 cut already uses.

### Remotion kit
* `remotion-kit/episodes/ep04/adapter-engine.cjs` needs NO code change: it reads icons from `review.motion.icons` (events, now
  registry-derived) and `text.cards[term].icon` (now generated). Retire the hand-written
  `remotion-kit/episodes/ep04/episode-text.json` in favour of `jjv text build` output
  (`--episode-text <out>/episode-text.json`), and keep `--allow-outside` for the shared logo as today.
* The generated file has three extra keys the adapter ignores (`title`, `captions`, `endPlate`) and
  `cards.<term>.exampleVi`; `requireText` (adapter L65-90) and `remotion-kit/src/validate.mjs` L348-351 accept them (they only
  check the keys they name).
* A generic kit adapter for ep05 should take `--episode-text` from this verb; nothing in the generated file names ep04.

## 4. Usage

```
jjv icons build    --episode E --assets-manifest assets3d/vocabulary-vNNN/manifest.json --script SCRIPT.json \
                   [--attributes F]... [--allow-shared ICON_ID] --out DIR [--dry-run]
jjv icons validate --episode E --registry DIR/icons.json [--script SCRIPT.json] [--require-approved]
jjv icons set TERM --episode E --registry DIR/icons.json --png NEW.png [--attribute T] [--status approved] \
                   [--events events.json] [--config review-config.json] [--segments segments.json]
jjv text build     --episode E --out DIR --registry DIR/icons.json [--shot-pack P | --script S] [--copy F] \
                   [--music REL] [--ambience REL] [--ending-params F]
jjv text diff      --generated A --reference B [--ignore PATH]
```
Exit 0 ok, 1 a rule failed (nothing written), 2 unreadable input. `--require-approved` is the production gate: a candidate icon
(parent visual review pending, as all 14 ep04 icons are today) is then an error.
