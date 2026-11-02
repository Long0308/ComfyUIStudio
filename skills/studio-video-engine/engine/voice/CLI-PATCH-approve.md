> MERGED into SKILL.md 2026-10-28
# CLI-PATCH — `jjv voice approve` (T-E40v, S4)

**`bin/jjv.py` needs NO edit.**  `jjv.py` already dispatches the whole `voice` stage to
`engine.voice.cli.run_voice` (see the `# --- voice stage (T-E40v) ---` blocks in `bin/jjv.py`), and the verbs are
registered by `engine/voice/cli.py::register_cli`, which is inside this builder's scope.  So `approve` (and the new
`plan --script/--extras/--vocabulary-speaker`, `--category end_line|brand_voice`) exist already:

```
jjv voice approve --episode E --out DIR --list
jjv voice approve --episode E --out DIR --job dialogue:S01_A --by "<listener>" --note "<what was heard>" [--sha256 <native sha>]
jjv voice plan    --episode E --out DIR --script SCRIPT.json --cast CAST.json [--extras EXTRAS.json] [--vocabulary-speaker alice]
jjv voice finalize --episode E --out DIR --category all     # writes voice-finalize.json AND voice-bindings.json
```

Exit codes follow the existing convention: Refused = 1 (`E_LISTEN_APPROVAL`, `E_APPROVAL_BY`, `E_APPROVAL_NOTE`,
`E_LANGUAGE`, `E_EFFECT_PRESET`).

## What other stages still have to do (not in this builder's scope)

1. **H3 prepare (comfy stage)** must refuse an un-approved WAV before it writes `preparation.json`:

   ```python
   from engine.voice import approval, receipts
   plan = receipts.load_plan(voice_out)
   approval.require_wav_approved(voice_out, plan, wav_sha256, episode_root)   # Refused E_LISTEN_APPROVAL
   ```

   It resolves the receipt WAV / editorial / base / split segment / split full sha back to its approved native take.
2. **`jjv timing words --dialogue`** and **`jjv audio mix --review-config`** can read `voice-bindings.json`
   directly once its `timeline_bound` is true (script frames, or frames filled by the timing contract).
   `extras[].usage` gives the exact `--extra-wav` / `--brand-voice` arguments (the mix needs `--allow-outside <voice out>`
   when the voice out dir is outside the episode root: `needs_allow_outside`).
3. Optional: `episode.files.script` (episode schema) so `--script` can default; until then pass `--script`.
