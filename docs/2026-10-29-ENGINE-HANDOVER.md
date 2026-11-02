# Handover 2026-10-29 — Engine wave 2026-10-28 (DRAFT, root finalises after the last workers land)

Status: **DRAFT by M11-DRAFT worker (Sonnet 5.5)**. Every number below is copied from `production-local/engine/WAVE-2026-10-28-PLAN.md` (the "WAVE notes"), `EP05-READINESS.md`, `M8b-e2-MOUTH.md` and `M9b-DESIGN.md` §5. Nothing was re-run by this worker. Items marked `[root to confirm]` must be re-measured by root before this file is final. **Do not start ep05 until the user picks a topic and says go.**

Parent trackers: `production-local/engine/ENGINE-PLAN.md`, `production-local/engine/WAVE-2026-10-28-PLAN.md`. Previous handover (format source): `docs/handoffs/2026-10-27-EP04-SHIPPED-ENGINE-HANDOVER.md`.

## 1. Accepted tonight (milestone → evidence, as recorded in the WAVE notes)
Last full-suite figure recorded in the notes: **2320 passed / 3 skipped / 0 failed** (after M4, ~21:00, on `.agents`). Later milestones record targeted runs only; no later full-suite number is in the notes `[root to confirm with a fresh full run]`.

| Milestone | Evidence recorded (WAVE notes) |
|---|---|
| M1 Q-9 negative controls | full suite 2253 passed / 3 skipped / 0 failed (was 2244 + 4 Q-9 skips); root re-ran targeted 30 passed / 1 skip |
| M2 SKILL merge | SKILL.md 088242…, 25 markers, 5 `--help` exit 0; later SKILL-1 accepted |
| M3 config keys + schemas | 2257 passed / 3 skipped / 0 failed; machine.json ac5598b5…, ep04 episode.json 2da18af3…, config 23da5aac…, test_config_keys 15 passed, frozen verify ALL MATCH |
| M4 Q-2b review workflow | 2320 passed / 3 skipped / 0 failed (+3); token grep 0 |
| M4-f1 / f1c / f1d / f1e | f1: 60 image tests passed, real ep04 manifest unchanged (5e6e9072…); f1c: 64 passed (common.py 09e785ee, native.py cbd72af6); f1d: in the 134-passed run; f1e: workflow_publish.py 502→395 lines, 79 passed |
| M5 deliver / brand / publish | 2317 passed / 3 skipped / 0 failed (+19); bin/jjv.py 0c7973b5…; ep04 2K 3972 f, audio md5 229ffd6f… = shipped; title 128 f; join 3972/3972 framemd5 |
| M6 script / storyboard | 2298 passed / 3 skipped / 0 failed (+41); bin/jjv.py 11584e6a…; CR-M6 (Gemini) PASS; M6-f1 real `scene_layout.py` test, tests/script 42 passed |
| M7 H3 prepare/submit/adopt/accept | tests/h3 17/17; hashes prepare/submit/adopt/accept 57ccf2e9 / fb57bb97 / 21309850 / 8f1d76c1; jjv.py b372deae. CR-M7 (Gemini) FAIL, 2 MAJOR confirmed |
| M7-f1 | 37 passed, ep04 graph shas unchanged, frozen ALL MATCH; CR-M7f1 PASS (Gemini) |
| M8 `jjv run episode` | 143 passed; bin/jjv.py 4FFC3C79; ep04 dry-run health_gate=available, FIRST STOP voice [gpu-approval] |
| M9a Q-8 call-site sweep | h3+M9a+images+cli 134 passed, config validate ok, frozen ALL MATCH; CR-M9a-r2 PASS (Gemini) |
| T-E39 health preflight | live read: Comfyui-Studio, --disable-partner-nodes, 14953 MiB free |
| T-E34 `qa transitions` | 3 negative controls FAIL for the right reason; shipped v015 PASS 28/28 |
| M8b (a)…(g) hand-offs | (c)-f2 boundaries.current receipt; (g2) delivery markers 54 passed; (e) h3 publish-shots 90 passed; (e)-f adopt sha pinned 61 passed; (f) adapter-master ep04 parity 0 diffs; EP05-READINESS.md 38b2c7f7… |
| M9b-design | M9b-DESIGN.md 92f2050f… (8 sub-milestones) |
| M9b-1 bridge | jjv_bridge.py c3e4c9e8…, 94 passed outside the sandbox |
| M9b-2 / 3 / 3f / 2f | M9b-2: jobs+bridge+job_journal 160 passed; M9b-3: studio 155, engine 66; M9b-3f: studio 215 + engine feedback 66 passed |
| Skills R102/R103 | validator ok, 7 roots sha equal 18de3806… |
| HR-14d, HR-12b, HR-16 | harness tests 160; HR-12b 31 passed (CR-HR13 PASS); HR-16 159/159 |

M9b-4 / M9b-5 / STAMP-1 / M8b(c) were dispatched ~23:35; the later note (~00:30) records STAMP-1 and M8b(c) accepted. M9b-4 and M9b-5 acceptance: not recorded in the notes `[root to confirm]`.

## 2. In flight at the time of writing `[root to update]`
- Fable #2: M8-f1 (DAG wiring; also makes `files.mouth_boxes` optional per M8b-e2 decision (c); the DAG neutrality red is `engine/run/dag.py:156`).
- Studio M9b-4 (Sonnet #2, plan explain consumes notes), M9b-5 (Astra, production route migration); M9b-6 onward not started per the notes.
- CR-TE39 follow-up: narrow the autouse healthy-docker fixture in `tests/conftest.py` (conftest shadow risk).
- HR-20f (Sol): TOCTOU follow-up of CR-HR20d; pool Gemini 401 (9Router "API key required for remote API access") — root testing `KHOA_9ROUTER_KEY2`.
- Critic lanes (Gemini / Luna / DeepSeek) per rolling dispatch. Status per lane: in flight, unknown to this worker.

## 3. What blocks the ep05 pilot (in order)
1. **User topic choice.** Options in EP05-READINESS §B: 1 Tidy Up Time (recommended, 1 set), 2 Fruit Salad Friends, 3 Rainy Day Puddles. No `05-*` folder exists. Candidate script `staging/ep05-draft/script.json` 7a651a00… (ingest 0 → 3444 f; storyboard check 0; 2 negative controls fail correctly). The script must declare `continuity.{setting_id, camera_id, seat_id}` per shot.
2. **Mouth-boxes optional landing.** `files.mouth_boxes` is required by schema/loader/rules (`schemas/episode.schema.json:70-73`, `engine/config/loader.py:152-155`) but no engine verb reads it, so every new episode fails `resolve_episode` before voice. Decision (c): make it optional (design `M8b-e2-MOUTH.md` 44000104…). The invariant is `config_core_sha256` = `bc062daf…`: per `engine/config/HASHES.md`, it covers the machine WITHOUT the `voicestudio`, `timing`, `audio`, `note`, `brand`, `remotion` and `publish` keys, and "machine facts ... any domain value, a recipe, any episode key" change it. The full `config_sha256` of ep04 is now `769d47fbc41e675ddf6f6a908450b475ce772e892237cc8958dfdcf1f3f3b7f5`. HASHES.md gives its "Changes when" as "anything below" (machine, domain, recipes, episode, shots, mouth-boxes, contract), so it moves when machine keys change. Only `config_core_sha256` must not move.
3. **M8-f1 DAG wiring** (Fable #2, includes item 2).
4. **Studio M9b-7 / M9b-8.** M9b-7 needs the accepted M8 contract (fake M8 argv, pause/resume, no legacy bypass); M9b-8 is the fixture-only Playwright UAT (design §5). M9b-6 (review page) precedes them.
5. **GPU OK from the user + VRAM floors measured in M10.** Floors for seedvr2/audio recipes are 0 today (**chưa đo**). Not live-proven until the pilot: real ComfyUI music/sfx/images submit, Demucs FAIL path on a singing bed, full VoiceStudio batch, Remotion master via the kit, GPU tails, `h3 submit`.

Other gaps from EP05-READINESS §D: layout brief geometry is hand-filled; `machine.timing` python/model for live `timing words`; ep05 needs a new `episode.json` (no `episode init` verb — check whether M8-f1 adds one `[root to confirm]`); pin `engine_tree_sha256` at the start.

## 4. User-gated items (wait for the user)
- **HR-12 apply script** (guarded SQL channels+abilities, like HR-10; PONG check of `custom/oauth-gpt-6-astra` after).
- **Gemini accounts script.**
- **9Router remote-access key for the pool** (pool Gemini 401 from 9Router itself).
- **HR-2c gateway failover** and **HR-8 Vault push**: deferred.
- **Sessions UI deploy script** (HR-7b follows HR-7a Sessions API).
- M10 GPU pilot; the 17 blocked `oauth-cursor` / `oauth-gpt-5-5` aliases (retire or keep); NEWTECONS generation stays blocked (needs its own GPU pilot and qualification receipt).
- Permission rules: the auto-mode classifier denied a rules edit; the user adds rules via `/permissions`.

## 5. Rules learned tonight
- **Rolling dispatch: scan ALL lanes** each turn (R102 §8.6); never leave a lane idle (Gemini/DeepSeek went idle once at ~23:05). On quota/capacity signals rotate model automatically (§8.8; e.g. Gemini stalled at the 15-min cap → retry once with a smaller capsule, then DeepSeek).
- **Gemini = read-only critic with a budget**: ≤ 5 files, ≤ 20 tool calls, no full suite, `--basetemp` inside the workspace. CR-M7 used 4.17 M tokens, CR-M6 21.3 M tokens; the time cap does not cap tokens. Prefer Luna for long audits.
- **PONG checks use a unique token per probe** (R102 notes) so a cached or stale reply is not read as a pass.
- **basetemp outside `production-local`** (full suite and Studio tests: Python 3.14 tmp_path DACL errors and sandbox temp denials are artefacts; run outside the Codex sandbox).
- **No second `conftest.py`**: new options/fixtures go into the top `tests/conftest.py`; helpers in uniquely named modules (M6/M5 shadow incident, apply gate rolled back).
- Run the FULL suite from the engine root before reporting; the worker's "pass" is not accepted until root or a different verifier re-runs it.
- Codex sandbox makes `.agents\` read-only → Codex builds (HYBRID staging → Claude apply) only when Codex is the builder; in Claude Code the Claude family builds directly.
- GPT workers: use a per-account `CODEX_HOME` when the global account is out of credits; check `GET :4310/api/setup/accounts` first.
- Receipt rule: `receipt tracker-SHA binding`, at-capacity and nested-codex EPERM lessons go to the error-db at M11 (listed in the plan).

## 6. Commands to resume
Workspace `D:\23.JennieHomeSchool\03 Voice`; engine root `.agents\skills\studio-video-engine`.

```powershell
cd "D:\23.JennieHomeSchool\03 Voice\.agents\skills\studio-video-engine"

# frozen verify (expect: RESULT ALL MATCH)
python bin/jjv.py frozen verify

# config check on the shipped episode
python bin/jjv.py config validate --episode 04-milk-and-mom

# full suite; basetemp OUTSIDE production-local (scratch dir of your choice)
python -B -m pytest -q -p no:cacheprovider --basetemp "$env:TEMP\jjv-full-basetemp"

# orchestrator dry run (writes only <run_dir>/plan.json; stops at the first gate)
python bin/jjv.py run episode --episode <id> --dry-run
```

Expected on ep04 dry run (WAVE note ~00:30): `health_gate=available`, FIRST STOP `voice [gpu-approval]`. `<id>` for the shipped episode is `04-milk-and-mom`; ep05 has no id until the user picks a topic.

Notes: the invocation form `python bin/jjv.py …` versus an installed `jjv` entry point is not confirmed in the notes (the SKILL verb index writes `jjv …`) `[root to confirm]`. The last full-suite figure in the notes was run in the `.agents` tree outside the sandbox.

## 7. WHERE I GUESSED
- Resume commands are assembled from the SKILL verb index and the plan's "from `.agents/skills/studio-video-engine`" wording, not executed here.
- Which of M9b-4 / M9b-5 are accepted is unknown; I listed them as in flight.
- The `$env:TEMP` basetemp path is my example; the rule only requires it to be outside `production-local`.
- Gemini-accounts script, Sessions UI deploy script and the 9Router key are named only as the root's task listed them; the plan notes give no file names for the first two.
