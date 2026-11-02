# Config hashes and engine pin: which stage binds which

## The hashes (all computed by `engine/config/loader.py` + `hashes.py`; `jjv config validate` prints them)

| Hash | Covers | Changes when |
|---|---|---|
| `config_sha256` | machine + domain + recipes + episode (incl. `contract`) + `shots.json` + `mouth-boxes.json` (when named; the body holds `"mouth_boxes": null` otherwise, M8b-e2) + the sha256 of the generated `DELIVERY-CONTRACT.json` | anything below |
| `config_core_sha256` | machine WITHOUT these 7 keys: `voicestudio`, `timing`, `audio` (stage-private tool blocks), `note` (free text), `brand`, `remotion`, `publish` (delivery/tool paths, not render content), `legacy_roots` (where a retired tree lives now); domain; recipes; episode WITHOUT `engine_tree_sha256` | machine facts (comfy, gpu lock, studio, node_modules), any domain value, a recipe, any episode key (title, timeline, contract, audio/voice/timing choices, files) |

Excluded from `config_core_sha256` and why: `voicestudio` / `timing` / `audio` change only when a stage tool's URL, python or model moves (bind them through `stage_machine_sha256`); `note` is free text; `brand` / `remotion` / `publish` are delivery and tool paths (where a brand asset or render tool lives, where output is published); `legacy_roots` maps a retired absolute root (the drive hash-bound receipts/plans still name) to where that tree lives now (`engine/core/paths.py::resolve_data_path`, N41 2026-10-30). None of them changes what a plan renders, so editing one must not read as "config core changed". Source: `engine/config/hashes.py` (`_NOT_CORE_MACHINE`, which is the single list to edit). `engine_tree_sha256` is excluded from the episode for the same kind of reason: it is the code pin, not content.
| `stage_machine_sha256(machine, "voicestudio" \| "timing" \| "audio")` | that one private block | that tool's URL / python / model / separator command |
| `contract.sha256` (inside episode.json) | the contract block without its own sha | sections, totals, vocab count, revision, extra |
| `delivery_contract_sha256` | bytes of `DELIVERY-CONTRACT.json` | regenerated with `jjv config contract --write` |
| `engine_tree_sha256` | `engine/**` + `recipes/**` + `bin/**` code and data (not `__pycache__`, `tests`, `*.md`, `*.tmp`, `*.bak*`, `*~`, dot-files, files that vanish during the walk) | any engine or recipe edit |

Writing `shots.json` / `mouth-boxes.json` after a plan changes `config_sha256` only: `config_core_sha256` is unchanged.
Adding a stage-private machine block (the pending-keys batch) changes `config_sha256` and the block's own hash, not the core.

## Binding table (target; "now" = what the code binds today)

| Stage | Binds (target) | Binds now | Switch |
|---|---|---|---|
| `seedvr2 plan/execute/finalize/seam-blend` | `config_sha256` + `machine_sha256` + `domain_sha256` (they depend on shots and on the whole machine/domain) | same | none |
| `editorial build-config` | `config_sha256` (shots, timeline, contract) | same | none |
| `voice plan/synth/finalize` | `config_core_sha256` (+ `stage_machine_sha256("voicestudio")` if the URL must not change mid-run) | `config_sha256` (`voice/cli.py:82`, `voice/plan.py:169`, `voice/finalize.py:193`) | `config.config_core_sha256` |
| `audio music plan/submit/finalize` | `config_core_sha256` | `config_sha256` (`audio/cli.py:112`, `audio/music.py:112`) | `config.config_core_sha256` |
| `audio sfx cues/...` | `config_core_sha256` + `review_config_sha256` + shot-pack sha | `config_sha256` + review sha (`audio/sfx.py:64`) | core |
| `audio mix` | `config_core_sha256` + `review_config_sha256` + recipe sha | `config_sha256` (`audio/mixcli.py:164`) | core |
| `timing words` | `config_core_sha256` + `dialogue_sha256` | none (dialogue sha only) | add core |
| `qa av` / `qa review` | sha of the review config FILE they judge, + contract total (`rules.timeline_frames`) | file sha only | compare the review config total with the contract |

Rule of thumb: a stage that reads `shots.json` binds `config_sha256`; a stage that reads only the script facts, recipes and
machine tools binds `config_core_sha256`. A receipt always records BOTH fields so either check stays possible.

## Engine pin

* `jjv frozen verify --tree [--episode E]` prints `TREE engine_tree_sha256 <sha> files <n>`; with `--episode`, an episode that pins
  `engine_tree_sha256` must match (exit 1 otherwise). `config validate` refuses an episode whose pin differs from the tree on disk.
  ep04 pins nothing (`null`) while several builders edit the live engine; pin only when an episode is frozen.
* Receipts take the header on request: `write_json_once(..., stamp=True)` / `write_json_atomic(..., stamp=True)` add
  `engine_tree_sha256` + `engine_tree_files` (never replacing a recorded header). Do NOT stamp deterministic artefacts
  (`editorial build-config` outputs): `write_once` is idempotent only for identical bytes, and an engine edit would make a rerun refuse.
* Tests that copy the skill folder use `tests/config_fixtures.py::copy_snapshot` (ignores temp/backup files, skips a file
  deleted mid-copy): the "recipes/qa temp file vanished" race.
