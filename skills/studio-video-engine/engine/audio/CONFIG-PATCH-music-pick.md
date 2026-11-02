# CONFIG-PATCH: music pick / brand voice keys (for root / the config builder)

Schemas are frozen until the tails plan has run; until then every key below is read through `optional_block` with the
default in the right-hand column, so nothing is re-hashed and `config validate` is unchanged.

| File | Key | Meaning | Fallback today |
|---|---|---|---|
| `schemas/episode.schema.json` (`audio` block, closed) | `brand_voice`: `{"enum": ["intro", "film", "none"]}` | where the brand voice sits: inside the brand intro (film mix has none), in the film mix, nowhere | absent = `intro`; **an episode.json that names the key is rejected by the closed schema until this lands** |
| `domains/jenniejoy_cartoon_3d.json` `audio.allowed_recipes` | add `"audio/music-pick-v001"` | for symmetry with the other recipes; `music pick` checks the recipe's own `domain` and does NOT read this list | not needed |
| `schemas/machine.schema.json` | none new | the Demucs interpreter for the `no_vocals` strip is the FIRST word of `machine.audio.vocal_gate.command` (already set on this machine); `--demucs-python` overrides | as is |
| `recipes/audio/music-pick-v001.json` | new file (family `audio-music-pick`, validated by `musicpick.load_pick_recipe`, not by `recipe_schema.py`) | scoring weights, thresholds, instrument vocabulary, ACE-Step graph + model pins, vocal-step settings, registry schema id and id prefix | n/a |
| library root | `--library` flag | default `<episodes folder>/_library` (sibling of the episode folders) | as is |

`config_core_sha256` is unaffected (no machine/domain/episode/recipe-family key is added by this builder).
