> MERGED into SKILL.md 2026-10-28
# CLI-PATCH: timing stage (T-E33), lines root adds

`bin/jjv.py` and `engine/qa/cli.py` belong to other builders and were NOT edited.  `jjv timing words` and `jjv qa words` are
implemented and tested through the registration/handler functions of `engine/timing/cli.py`; these exact lines make them reachable
from `jjv`.  Nothing else changes (`python -I bin/jjv.py ...`).

## 1. `bin/jjv.py`

Imports (next to the other stage imports, after the audio block):

```python
# --- timing stage (T-E33) ---------------------------------------------------------------
from engine.timing.cli import register_cli as register_timing, run_qa_words, run_timing  # noqa: E402
# --- end timing stage -------------------------------------------------------------------
```

`build_parser()` (after `register_audio(stages)` / before `return parser`):

```python
    # --- timing stage (T-E33) ---
    register_timing(stages)
    # --- end timing stage ---
```

`_dispatch()` (before the final `return 2`):

```python
    # --- timing stage (T-E33) ---
    if args.stage == "timing":
        return run_timing(args)
    if args.stage == "qa" and args.verb == "words":
        return run_qa_words(args)
    # --- end timing stage ---
```

(`qa words` can sit anywhere in `_dispatch`; `qa av` is matched on `args.verb == "av"`, so the two do not collide.)

## 2. `engine/qa/cli.py` (the `qa` verb group is created there)

In `register_cli`, right after `verbs = qa.add_subparsers(dest="verb", required=True)`:

```python
    from ..timing.cli import register_qa_words  # T-E33: qa words (Q1)
    register_qa_words(verbs)
```

A second `stages.add_parser("qa")` is NOT possible (argparse refuses a duplicate sub-parser name), which is why the verb is added to the
existing group.  The import is inside the function on purpose: `engine/timing/cli.py` imports `engine/qa/scope.py`.

## 3. Config keys (frozen schemas, applied after the tails run, like the voice/audio stages)

Until then the stage reads them through `engine/timing/recipe.py::optional_block` (absent = default, nothing re-hashed, `config validate` unchanged):

| File | Key | Meaning | Fallback today |
|---|---|---|---|
| `schemas/machine.schema.json` + `machine.json` | `timing` (optional object, closed): `python` (path of the interpreter that has `faster_whisper`), `model_dir` (faster-whisper model folder, or a folder holding `snapshots/*/model.bin`) | the machine's speech-recognition setup | `--python`, `--model`; missing = `Uncertain`, exit 2, nothing faked |
| `schemas/episode.schema.json` | `timing` (optional object): `recipe` (`timing/<id>`) | recipe choice | `--recipe`, else the single `recipes/timing/*.json` whose `domain` equals the episode's |
| `schemas/recipes/timing.schema.json` | `TIMING_RECIPE_SCHEMA` of `engine/timing/recipe.py` | move there when per-family recipe schemas land | the dict in `recipe.py` |

`production-local/engine/machine.json` on this machine would carry (values are machine facts, not engine source):

```json
"timing": {"python": "<repo>/production-local/JennieJoyKids-Story/04-milk-and-mom/editorial/word-timing-v001/.venv/Scripts/python.exe",
           "model_dir": "J:/2.Model-AI-Local/HuggingFace/hub/models--Systran--faster-whisper-small"}
```

Adding any machine key changes `machine_sha256`, which invalidates a bound SeedVR2 plan (see SKILL.md Known gaps): apply after the tails run.

## 4. Usage (once wired; today the same handlers run through `engine.timing.cli`)

```
python -I bin/jjv.py timing words --episode E --dialogue review-config.json [--vocabulary vocab.json] \
    --python <py-with-faster_whisper> --model <model dir> --out DIR          # recognition + onset rule + Q1
python -I bin/jjv.py timing words --episode E --dialogue D.json --recognised WORD-TIMING.json --out DIR   # re-apply the rules
python -I bin/jjv.py qa words --episode E --timing DIR/WORD-TIMING.json [--out receipt.json]               # Q1 alone
```

Exit codes: 0 Q1 PASS; 1 Q1 FAIL or a rule violation (the files of `timing words` are still written: they are the evidence); 2 missing/unreadable
input, recognition not configured, a script word not heard, or a document with no word after a pause (`UNTESTABLE`, never a PASS).
