# CONFIG-PATCH — voice stage (T-E40v), to be applied by root AFTER the tails GPU run

Domain, machine and the existing schemas are frozen until the ep04 tails plan has executed
(any edit changes `machine_sha256`/`domain_sha256` and invalidates the bound SeedVR2 plan,
T-E29 §0.2).  Until then the voice stage reads every key below through the optional,
defaulted accessor `engine/voice/recipe.py::optional_block` (absent key = default, nothing
re-hashed; `config validate` for the main episode still reports `c629dce3…`).  The CLI
fallbacks that exist today are listed per key so a live run is possible before the landing.

## 1. `schemas/machine.schema.json` (closed object: add the property)

```json
"voicestudio": {
  "type": "object", "additionalProperties": false, "required": ["url"],
  "properties": {"url": {"type": "string", "pattern": "^https?://"}}
}
```

`production-local/engine/machine.json` gains `"voicestudio": {"url": "http://127.0.0.1:8080"}`
(the value is the one the first batch tool hard-coded; it is config, not engine source).
Today: `--voicestudio-url` on `voice synth|reconcile`; `--execute` refuses without one.

## 2. `schemas/domain.schema.json` (closed object: add an optional block)

```json
"voice": {
  "type": "object", "additionalProperties": false,
  "properties": {
    "allowed_recipes": {"type": "array", "items": {"type": "string", "pattern": "^voice/"}},
    "require_listen_approval": {"type": "boolean"}
  }
}
```

`domains/jenniejoy_cartoon_3d.json` gains
`"voice": {"allowed_recipes": ["voice/omnivoice-en-broadcast-v001"], "require_listen_approval": true}`;
`newtecons_live_action` gains `"voice": {"allowed_recipes": [], "require_listen_approval": true}`
(its own Vietnamese recipe needs a user-authorised pilot first).
Status 2026-10-27: both keys are applied in `domains/*.json` (JennieJoyKids and NEWTECONS:
`require_listen_approval: true`) and `require_listen_approval` is now ENFORCED by `finalize`
(`engine/voice/approval.py`, `jjv voice approve`): no valid approval record bound to the take's native
sha256 = `E_LISTEN_APPROVAL`, nothing written.  `allowed_recipes` absent = no allow-list check beyond
`recipe.domain == episode domain`.

## 3. `schemas/episode.schema.json`

* `files` gains optional `dialogue` and `cast` (strings, relative to `<episode>/engine/`).
  Today: `--dialogue` / `--cast` flags; `voice plan` refuses and names the flag when absent.
* new optional block `voice`: `{"recipe": "voice/<id>", "version": "voice-v001"}`.
  Today: `--recipe`, else the single `recipes/voice/*.json` whose `domain` equals the
  episode domain (two candidates = Refused).

## 3b. New in this round (no new config key; documents and optional recipe keys only)

* Dialogue document (`jjv/dialogue/v1`, a document, not config): optional `extras[]` (end line, brand voice),
  per-line metadata (`subtitle{vi}`, `start_frame`, `duration_frames`, `en_markup`, `target_keywords`, `icon`,
  `emotion`, `language`, `effect_preset`) and document `fps`/`language`.  `jjv voice plan --script F` derives it
  from the locked film script (`engine/voice/script_ingest.py`).  Optional follow-up (not implemented, needs the
  episode schema): `episode.files.script` so `--script` can default like `--dialogue`.
* Voice recipe, two OPTIONAL keys already accepted by `VOICE_RECIPE_SCHEMA` (absent = old behaviour):
  `trim.onset.quiet_burst_db` (number 3..60) and top-level `allowed_effect_presets` (array of strings).
  `recipes/voice/omnivoice-en-broadcast-v001.json` is NOT edited: its sha is bound in every plan/finalize
  receipt.  Recommended for NEW work: `recipes/voice/omnivoice-en-broadcast-v002.json` = v001 plus
  `"quiet_burst_db": 15` in `trim.onset` (measured: it reproduces the hand-made ep04 end-line trim byte for byte,
  `end-line-mother-trim-v001-48k.wav` d250672d...; with the key absent the engine keeps a 0.17 s breath that
  the hand trim cut).  Root decides whether a v002 recipe (and a `domain.voice.allowed_recipes` entry) lands.

## 4. Recipe family schema

`schemas/recipes/voice.schema.json` = the dict `VOICE_RECIPE_SCHEMA` in
`engine/voice/recipe.py` (move it there when the per-family recipe schemas land; the
loader `engine/config/loader.py::_load_recipes` validates every `episode.recipes.*` entry
against `recipe.schema.json`, which is the SeedVR2 shape, so a voice recipe must NOT be
listed under `episode.recipes` until that split exists).

## 5. Two shas (T-E29 §2.2)

Voice receipts bind `config_sha256` (the full one) today because `config_core_sha256` does
not exist.  Consequence: writing `shots.json`/`mouth-boxes.json` for a new episode after the
voice plan would make `voice synth|finalize` refuse with "the resolved config changed; re-plan"
(`engine/voice/cli.py::_settings_for_plan`).  When `config_core_sha256` lands, switch the
plan/finalize receipts and that check to it (one-line change each, field name kept).

## Not implemented on purpose (needs modules owned by other milestones)

* Script-lock approval line: `synth --execute` requires `dialogue.status == "LOCKED"` in the
  dialogue document (the S1 ingest writes it); the approvals JSONL check is U0.
* Voice-listen approval is now enforced by `finalize`; the H3-prepare side is a library call the comfy stage
  (outside this scope) must make: `engine.voice.approval.require_wav_approved(out, plan, wav_sha256,
  episode_root)` (see `CLI-PATCH-approve.md`).
* Budget `used_frames/24`: enforced only when the dialogue row carries `max_duration_s`
  (the timing contract of U1 should fill it); otherwise `budget.checked: false` in the receipt.
* `voice measure` / `voice vocab` verbs: metrics are inside `take.json` and the finalize
  receipt; vocabulary jobs go through the same verbs with `--category vocabulary|all`.
