# Script ingest and storyboard (M6; integration note for owning skill)

Register `script` and `storyboard` using the sibling staging task's CLI-PATCH.md. No shared CLI file was edited.

```
jjv script ingest --script SCRIPT.json --episode E [--out DIR] [--target-seconds N] [--vocabulary-speaker ROLE]
jjv storyboard plan --episode E [--ingest DIR] [--out STORYBOARD] [--scene-tool SCENE_LAYOUT.py]
jjv storyboard check --episode E [--ingest DIR] [--out STORYBOARD] [--scene-tool SCENE_LAYOUT.py]
```

Default ingest directory: `./derived/<episode_id>/script`; default storyboard directory: `<ingest>/storyboard`.
Use an explicit derived workspace outside the source episode. Source script/episode/reference files are read only.
Schema: `schemas/script.schema.json` (`jjv/script/v1` plus the existing legacy authoring schema identifier).
Schema errors, duplicate ids/terms, unknown/silent speakers, timing contradictions and invalid carries are refused.

Ingest writes `script.json`, `shots.json` (jjv/shots-skeleton/v1), `boundaries-input.json`, `vocabulary.json`,
`cast-bindings.json`, `voice-cast.json` (existing jjv/cast/v1), `dialogue.json` (existing jjv/dialogue/v1),
`contract-inputs.json`, `contract-plan.json`, `DELIVERY-CONTRACT.json` and `ingest-receipt.json`.
The shared budget allocator and contract builder are used; the existing `config contract --plan` reproduces
the emitted contract with the same target/revision. All section boundaries, including graphic cards, are emitted.
No clip/WAV/identity evidence is invented: skeleton clip, WAV and receipt fields are null; declared image hashes
remain unverified. Voice status follows the existing adapter (candidate scripts stay DRAFT).

`duration_s` is the authored schedule / preferred delivery minimum. An infeasible short authored schedule is
expanded to the sum of floors and recorded as `authored_frames` versus `total_frames` in contract-plan.json.
An explicit `--target-seconds` or `script.delivery.target_seconds` is a HARD whole-film target: the existing
BudgetRefused response includes options and section floors and writes nothing. No squeezing or speech stretching.
The domain still owns the policy (cartoon logo >=60 f, each vocabulary card >=90 f). Timing inputs are labelled
AUTHORING ESTIMATES, not measured WAV lengths; rebudget after voice/H3 evidence. An end_line voice extra gets a plate.

Storyboard plan writes one authored brief and placement text per shot plus a content-hashed storyboard-plan.json.
An optional, self-contained `shot.layout_brief` is validated and passed to comfyui-blender `placement-text`;
consecutive geometry briefs use its real `continuity` API (valid MISMATCH exit 1 is a result, not an API failure).
Tool pins include scene layout/continuity/placement/common/set/track modules and their schema. Child Python uses -I -B.
For scripts without geometry, provide `continuity.setting_id`, `camera_id`, `seat_id` or explicit `framing`.
Same setting alone never proves same framing. Missing evidence produces UNKNOWN_FRAMING and check exit 1.
Reused editorial suggestion rules choose cut_push for same framing, dip_white or motivated whip for angle/scene
changes, and forbid both-picture presets without continuity agree. A script carry still needs later H3 evidence.
Check success is authoring-plan consistency only; media/tail feasibility, approvals and render gates still apply.

Outputs are immutable and deterministic (canonical JSON mode ascii; no timestamps). Changed inputs need a new out
directory. `engine.script.parity.compare` reads explicit shots/boundaries/contract reference paths and lists every
changed leaf of shot ids, boundary count/frames/ids, contract frame total and all contract sections.

Integration must not mark a skeleton as production `jjv/shots/v1` or claim full `config validate` before H3/mouth
boxes/receipt bindings exist. Merge this note into the owning skill and sync from the authorised root process.
