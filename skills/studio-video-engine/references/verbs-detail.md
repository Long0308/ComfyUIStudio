# studio-video-engine: verb detail (merged from the builders' notes, 2026-10-28)

`SKILL.md` keeps the verb index, the gates and the rules. This file holds the long usage and the tables that came from the
`CLI-PATCH*.md` / `SKILL-SECTION-*.md` notes (each now starts with "MERGED into SKILL.md 2026-10-28"). Wiring lines in those notes
are already applied: every verb below is reachable through `python -I bin/jjv.py ...` (checked with `--help`, 2026-10-28).
Audio, word timing and the engine side of transition presets stay in [stages.md](stages.md).

Contents: Config contract · Voice (script, approve, bindings) · Music pick/adopt and brand voice · QA preflight / gate / Q1b ·
SeedVR2 segments and tails · Plan explain · Icons and text · Layout and images · Transition suggest/preview/swap ·
Kit: ending segment, segment cache, one-command edits, list-presets, music bed policy, engine adapter, catalog sync · H3 inputs, legacy voice and the acceptance ledger · Boundaries write · Q5 and the audio contract · Receipt stamp · Run, health, qa transitions, h3 publish-shots, deliver init.

## Config contract (`engine/config/cli.py`)

```
jjv config contract --episode E                                   # show contract + whether DELIVERY-CONTRACT.json is current (exit 1 if not)
jjv config contract --episode E --plan  [--inputs F] [--target-seconds T | --min-seconds A --max-seconds B] [--pin logo_hold=70 ...]
jjv config contract --episode E --write [same plan args] [--revision R]    # lock: episode.contract + timeline + DELIVERY-CONTRACT.json
jjv config contract --episode E --write --from-episode            # regenerate only DELIVERY-CONTRACT.json
jjv frozen verify --tree [--episode E]                            # also prints engine_tree_sha256 (engine/** + recipes/** + bin/**)
```
`--plan` prints the section table on stderr, one JSON summary on stdout; a target below the sum of floors (or above what holds and
pauses can reach) exits 1 with `{"ok": false, "refused", "options": [...], "table": [...]}` and writes nothing. `--write` backs up
episode.json and DELIVERY-CONTRACT.json (`.bak-<UTC>`) and restores both if the result does not validate. Inputs:
`episode.files.contract_inputs` (`jjv/contract-inputs/v1`: `intro_frames`, `lines` (default: from shots.json clips + receipt WAVs),
`vocab[{term, wav|wav_s}]`, `end_line{wav|wav_s}`, `pins`, `extra`). Measured: ep04 3444 f validates; a 100 s target is refused with options.

## Voice: script, approve, bindings (`engine/voice/`)

```
jjv voice plan    --episode E --out DIR --script SCRIPT.json --cast CAST.json [--extras EXTRAS.json] [--vocabulary-speaker alice]
jjv voice approve --episode E --out DIR --list
jjv voice approve --episode E --out DIR --job dialogue:S01_A --by "<listener>" --note "<what was heard>" [--sha256 <native sha>]
jjv voice finalize --episode E --out DIR --category all     # writes voice-finalize.json AND voice-bindings.json
```
Refusal codes (exit 1): `E_LISTEN_APPROVAL`, `E_APPROVAL_BY` (empty/machine name), `E_APPROVAL_NOTE`, `E_LANGUAGE`, `E_EFFECT_PRESET`.
Other stages must do: (1) H3 prepare calls `approval.require_wav_approved(voice_out, plan, wav_sha256, episode_root)` before it writes
`preparation.json` (any derived WAV resolves back to its approved native take); (2) `jjv timing words --dialogue` and
`jjv audio mix --review-config` read `voice-bindings.json` once `timeline_bound` is true (`extras[].usage` gives the exact `--extra-wav` /
`--brand-voice` arguments; the mix needs `--allow-outside <voice out>` when that folder is outside the episode root); (3) `--script`
can default from `episode.files.script` once the schema key lands (M3), until then pass it.

## Music pick / adopt and the brand-voice mode (`engine/audio/musicpick*.py`, `library*.py`, `vocalstrip.py`)

```
jjv audio music pick  --episode E --out DIR [--dry-run] [--execute] [--library L] [--generator acestep|yue2] [--takes N]
jjv audio music adopt --episode E --out DIR [--execute] [--take JOB] [--demucs-python PY]
jjv audio mix ... --music-receipt DIR/music-pick.json      # library bed
jjv audio mix ... --music-receipt DIR/music-adopt.json     # generated, gated, registered bed
```
`pick` without `--dry-run` appends the film to the bed's `used_in` (versioned write: `REGISTRY.json.bak-<UTC>` + `revision`);
`--dry-run` reads everything and writes nothing. No fitting bed: `music-plan.json` + `music-pick.json` (`GENERATION_PLANNED`);
`adopt --execute` (or `pick --execute`) runs the GPU jobs through the guarded path, then the Demucs vocal step. Library default
folder `<episodes folder>/_library`.
`episode.audio.brand_voice` = `intro` (default) | `film` | `none`: `intro` and `none` = the FILM mix has no brand voice layer and an
explicit `--brand-voice` is `Refused`; `film` = `--brand-voice` if given, else the library registry pick
(`<library>/brand-voice/REGISTRY.json` `file` + `sha256`, re-verified). `mix --library` selects the library for that pick.

## QA: preflight, gate, Q1b

```
jjv qa preflight --config review-config.json [--timing WORD-TIMING.json] [--icons DIR] [--events events.json]
    [--episode E] [--root DIR] [--contract DELIVERY-CONTRACT.json | --expect-frames N]
    [--music-receipt music-finalize.json] [--mix-receipt mix-receipt.json] [--with-sfx] [--allow-ungated-music] [--require-audio]
    [--checks Q1,PACING,TRANSITIONS,ICONS,AUDIO] [--layout-same-framing F,F,...] [--allow-outside P]...
    [--preflight-recipe F] [--review-recipe F] [--timing-recipe timing/<id>] [--ffmpeg P] [--out report.json] [--json]
jjv qa gate --config review-config.json [every flag above] [--video review.mp4 [--mix mix.wav] [--gates Q1B,Q2,Q3,Q4,Q5]
    [--sheets-dir DIR] [--frame-origin N --audio-origin-s S]] [--out report.json]
jjv qa review --config C --video V [--mix M] [--events E] [--gates ...] [--sheets-dir DIR] [--out R] [--expect-frames N] [--root DIR]
    [--recipe F] [--layout-same-framing F,...] [--frame-origin N --audio-origin-s S] [--ffmpeg P] [--json]
```
Reports: `jjv/qa-preflight-report/v1`, `jjv/qa-gate-report/v1`, `jjv/qa-review-report/v1`; summary on stderr, exit 0 PASS / 1 a check FAILs or a
rule is violated / 2 UNCERTAIN (input missing or unreadable). FAIL beats UNCERTAIN. `--timing` defaults to the config's `word_timing.path`
(its `word_timing.sha256` must match the file). With `--episode`, section floors/ceilings come from `domain.delivery.sections.{vocab_card,logo_hold}`
and `delivery.end_card` (they can only RAISE the review-recipe floors) and the frame total from `rules.timeline_frames` when neither
`--expect-frames` nor `--contract` is given. `--root` defaults to the folder above the config that holds `engine/episode.json`.

`qa preflight` = every check that needs NO rendered pixels, run before a render is allowed: Q1 on the word timing (`qa words` detector + negative
control), pacing (`q5_pacing` arithmetic + EVERY card >= 90 f, declared and derived from card start frames; dialogue pieces tile; logo + cards join;
total == contract `master.frames`; every contract section matches), transitions (a white flash / dip / bloom between two picture shots is refused
when the SOURCE clips' boundary frames have NCC >= 0.25, or the config declares `layout_change: false` / `framing: same_framing`; a both-shots type next
to a picture needs `continuity: agree`; unknown type refused), icons (file level of Q2: coverage, sha binding, opposite pairs = different PNGs with
distinct delta E / hue, two words never share one image unless `shared_icon`), audio contract from receipts (music vocal gate PASS, SFX off unless opted
in, brand voice ends 0.2 s before the first word; no receipt = SKIPPED + warning, UNCERTAIN with `--require-audio`). Recipe
`recipes/qa/preflight-v001.json` (floors from `review-gates-v001.json`). `qa gate` = preflight, plus `qa review` (Q1B, Q2-Q5) when `--video` is
given; verdict = roll-up, `render_allowed` = the preflight verdict is PASS. Code `engine/qa/preflight*.py`; tests `tests/test_qa_preflight_*.py`.
**Q1b caption** (`engine/qa/gates/q1b_caption.py`, recipe `recipes/qa/q1b-caption-v001.json`): karaoke on pixels, a gate of `qa review`
(`ALL_GATES = Q1B, Q2, Q3, Q4, Q5`; reported as `"gate": "Q1b"`); it needs the config the export was built from, so to check an export against CORRECTED
timing pass the corrected config (the picture of an older cut then fails on each word that moved). Stand-alone:
`python -I engine/qa/gates/q1b_caption.py --config C --video V [--frame-origin N] [--out R]`.

## SeedVR2: segments, tails, `plan --reads` (`engine/seedvr2/cli_cut.py`, no new config keys)

| Command | What it does | Exit |
|---|---|---|
| `jjv seedvr2 segments --episode E --out DIR [--plan P] [--only SHOT[:IDX],..] [--dry-run] [--no-verify-md5] [--threads N]` | cut `<shot>/chunks/<chunk>/source-segment.mp4` for the plan frame-exactly with the v004 encode; re-hash/re-probe every source; md5 proof of each cut; never overwrite (an existing segment is kept only if its frames equal the source slice); hashed `segments-receipt.json` | 0 ok, 1 refused, 4 cut failed |
| `jjv seedvr2 plan ... --reads F [--tail-map MAP ...]` | before binding any source: every frame the review config reads (dialogue windows + `outgoing_tail`) must be inside each shot's clip or an assembled tail map; else refused naming the ranges | 1 on a gap |
| `jjv seedvr2 tails plan --episode E --reads F [--tail-map MAP ...] --out DIR [--scratch] [--dry-run]` | gaps -> tails plan (`kind: "tails"`): sub-range sources (`source_range`) of the NATIVE clips with leading context, segments cut into `DIR`, plan `DIR/seedvr2-tails-plan-v2.json`; `DIR` must be fresh and INSIDE the episode tree (so `execute --execute` accepts it) unless `--scratch`/`--dry-run` | 0 (also when nothing is missing), 1 |
| `jjv seedvr2 execute --episode E --plan DIR/seedvr2-tails-plan-v2.json [--execute]` | the existing executor, unchanged CLI (accepts `kind: "tails"`) | as before |
| `jjv seedvr2 tails check --episode E --plan P` | per chunk: receipts re-verify + framemd5(core) == framemd5(crop(trim(raw))); per shot: finalized concat has the planned frames | 0 green, 1 red |
| `jjv seedvr2 tails assemble --episode E --plan P --out DIR` | (check re-run, must be green) cut each gap from the shot core losslessly to `DIR/master-tails/*.mp4`, write `DIR/MASTER-TAIL-MAP.json` (`jjv/master-tail-map/v1`) | 0, 1 |

ep05 flow: `plan --reads REVIEW --out P0` (refused -> `tails plan` -> `execute` -> `tails check` -> `tails assemble` -> `plan --reads REVIEW --tail-map MAP`).
Measured on ep04: `plan --reads` without tails exit 1, with `MASTER-TAIL-MAP` exit 0; 134/134 segments byte-identical to the v004 cuts.

## Plan explain (`engine/plan/`)

`jjv plan explain --old DIR --new DIR [--target review|master|all] [--json-out FILE] [--verbose]`: what does OLD -> NEW re-render, and what does it cost.
It never runs, queues or posts anything (tests block sockets and Popen); exit 0 also when GPU jobs are listed; a missing directory exit 1; an existing
`--json-out` is exit 2 through `jjv` (exclusive create; the standalone `python -I engine/plan/__main__.py explain ...` gives 1). `DIR` = one version of the
inputs: `plan-inputs.json` (`jjv/plan-inputs/v1`; optional `config`, `mix_plan`, `mix_wav_sha256`, `render_record`, `segments`, `pins`, `gpu_cores`) or the
review-hd layout (`config/review-config*.json`, `RECEIPT.json`, `render-record-picture-*.json`, `mix-plan*.json`); two candidates for one file is `Refused`.
`gpu_cores.<shot>` = free-form leaves of the shot's GPU job plus `core_receipt` (a receipt whose text holds the new core sha: then that GPU job is NOT
needed). Policy `recipes/plan/policy-v001.json`, costs `recipes/plan/costs-v001.json` (each number tagged measured / derived / unmeasured). Output
`jjv/plan-explain/v1` (`headline`, `summary`, `rows[]` with node, status, why, leaves, action_code, action, est_seconds, requires_approval) + a stderr table.
Measured: v014 -> v015 = 19/36 segments, GPU none, audio reuse. Run it before every re-run (ENGINE-PLAN section E).

Feedback annotation (`jjv plan explain --old DIR --new DIR --episode E [--feedback F]`, code `engine/plan/api.py`, `annotate.py`, `feedback.py`): adds an additive `feedback` block (`jjv/plan-feedback/v1`) read from `editorial/review-feedback/feedback-v1.jsonl` by default, or from `--feedback F` (must be inside the episode root; an explicit missing file is refused). Each note carries its binding (current or stale against its receipt/artifact sha), its related nodes and any unmapped or unresolved items. Notes never change `rows`, the segment list or any re-render decision. Correction to the shorter wording: without `--episode` the output is unchanged; WITH `--episode` and no feedback file the document still gets the `feedback` block, with `present: false` and no notes, so it is not byte-identical to the no-episode output.

## Icons and text (`engine/editorial/icons*.py`, `episode_text*.py`)

```
jjv icons build    --episode E --assets-manifest assets3d/vocabulary-vNNN/manifest.json --script SCRIPT.json [--attributes F]... [--allow-shared ICON_ID] --out DIR [--dry-run]
jjv icons validate --episode E --registry DIR/icons.json [--script SCRIPT.json] [--require-approved]
jjv icons set TERM --episode E --registry DIR/icons.json --png NEW.png [--attribute T] [--status approved] [--events events.json] [--config review-config.json] [--segments segments.json]
jjv text build     --episode E --out DIR --registry DIR/icons.json [--shot-pack P | --script S] [--copy F] [--music REL] [--ambience REL] [--ending-params F]
jjv text diff      --generated A --reference B [--ignore PATH]
```
Exit 0 ok, 1 a rule failed (nothing written), 2 unreadable input. `--require-approved` is the production gate: a candidate icon (parent visual review
pending, as all 14 ep04 icons are today) is then an error. Recipes `recipes/editorial/icons-v001.json`, `episode-text-v001.json`. Measured: ep04 v002 icon
set FAILS the shared warm/cold rule; an icon swap lists 2 of 35 segments. Pending consumer migration (not done; `build.py`, `captions.py`, `sources.py`,
`boundaries.schema.json` still read icon file names): they must read the registry (`icons.load_registry`, `icons_check.validate_registry`, `icon_for_card`),
word timing should name icon IDs, `boundaries.json` `icons` block becomes `registry` + hold/fade/pop/lead frames (ep04 data change: point it at
`technical/icons-registry-v001/icons.json`), and the hand-written kit `episode-text.json` is retired in favour of `jjv text build` output. Until the schema
key `episode.files.icon_registry` / `script` lands every verb takes `--registry` / `--script`.

## Layout and images (`engine/layout/`, `engine/images/`, hybrid route)

Exit 0 ok, 1 refused (nothing sent), 2 uncertain, 4 execution failed. Every submit is a NEW take folder; every result a write-once receipt
`<out>/<shot>/candidates/<sha12>.receipt.json` (`jjv/image-receipt/v1`) next to the exact PNG. `--dry-run` (submit) prepares and saves graph / request /
prompt+argv and sends nothing.

| Verb | CPU/GPU | Writes |
|---|---|---|
| `layout plan --episode E --out L [--cast F --map ROLE=ID --allow-unbound]` | CPU | `L/set.json`, `L/briefs/<cut shot>.brief.json` (`provenance.jjv_scaffold.filled=false`), `L/layout-plan.json` |
| `layout check --layout L [--allow-draft]` | CPU | `storyboard-check.json`, `continuity-plan.json`, `placement/<shot>.txt`; exit 1 for a scaffold/draft/invalid brief or an incomparable pair; a continuity MISMATCH is reported with its allowed transitions, not an error |
| `layout render (--layout L \| --brief B --out O) --shot S --passes beauty,depth,mask` | beauty: GPU lock + free-VRAM gate; depth/mask: CPU | `render/<shot>/rNNN/` guide PNG, 16-bit depth, `-mask-id.png`, `-passes.json`, `.blend`, `render-receipt.json` |
| `images plan --episode E --out I [--layout L] [--shot ..] [--guide S=PNG] [--placement S=TXT] [--ref S:ROLE=PATH]` | CPU | `I/images-plan.json` |
| `images submit --provider comfyui-local --pilot [--task general\|identity --seed N]` | GPU | take `local/tNNN/` + candidate receipt; refused without `--pilot` while the recipe is `unqualified` |
| `images submit --provider openrouter --spend-ok [--budget-usd X]` | network, paid | take `openrouter/tNNN/` + receipt; `OPENROUTER_API_KEY` from the environment only; HTTP 401/402/403/429 write `I/openrouter-STOP.json` and every later call is refused until a human removes it |
| `images submit --provider codex-exec [--codex-account L=H ..] [--account LABEL] [--timeout S] [--n N \| --prompt-batch FILE]` | network (the user's ChatGPT login) | take `codex-exec/tNNN/` + receipt (account LABEL, failovers, Codex session id when printed) + `I/codex-pool-state.json`. `--n N` (1..10, default 1; codex-exec only, other providers refuse N>1; not with `--take`) makes N takes in turn, each its own folder + receipt, and returns `{n, takes[]}`; `--dry-run` plans N take folders and sends nothing. **Lanes (N20):** `--account LABEL` pins the call to that pool account (no failover to others; unknown label = Refused); the job lock is per label (`<state stem>.<label>.lock`, waits timeout+120 s), so Sol and Astra on `acct1`/`acct2` run at the same time and one label queues; pool state is changed only through `pool.update_state` (short `<state stem>.lock`, re-read inside). **Batch (N23):** `--prompt-batch FILE` = JSON array of 1..10 `{prompt_id, prompt_text, ref_images:[{path, role, sha256?}]}` (the N27 `image-batches/batch-XX-*.json` shape; batch_id = file stem); validated before any folder (>10, empty prompt_text, duplicate prompt_id, missing/changed ref = Refused); each item = own take (`claim_take`), prompt.txt = item text + the plan placement lines, `-i` = plan guide + the ITEM's refs, receipt has `prompt_id`, `batch_id`; mid-batch failure lists `completed_takes`; `--dry-run` creates nothing on disk (N25: no take folder, no prompt.txt; planned names continue after the existing takes). Ref sentences follow the role: plan cast refs and batch roles `identity*` = identity reference, any other batch role (`wardrobe_only`, logos...) = used only for what the role names. **Library mode (N23-fix):** `--prompt-batch FILE --library-out DIR` (no `--shot`, no images-plan) is for character-library images: no guide, no placement, `-i` = the item refs only, so Image 1 is the first ref and the engine's role lines and the brief's `ImageN:` lines both use that numbering (a brief line that disagrees with ref N of `ref_images` is Refused); takes go to `DIR/<batch_id>/tNNN` with a `jjv/library-image-receipt/v1` receipt (batch_id, prompt_id, prompt_sha256, prompt_text_sha256, ref hashes, no token). Shot mode REFUSES a brief that numbers its own `ImageN:` (the guide would be Image 1). Batch refs must be absolute .png/.jpg/.webp paths under the repo or `machine.images.batch_ref_roots` and never under a codex home; `prompt_text` sha256 must equal `prompt_sha256` (item field or sibling `queue-*.json`). **Library review (N50):** `images compare|approve --library-out DIR (--prompt-id ID | --character CHAR_01)` (no `--shot`; not with it) reviews `jjv/library-image-receipt/v1` takes of one prompt_id (or every prompt_id `CHAR_01_*`) across ALL batches/lanes/accounts: compare writes `DIR/_review/<key>/compare-<digest>.png|json` (refs row + one cell per take with its account label) and `checklist.json` (items `identity, wardrobe_r005, logo, real_skin`, from routes recipe `compare.library_checklist`; reviewed entries are never overwritten); approve needs a take of that key (>= 8 hex), every item `pass`, `--reviewer`, `--scope`, and writes write-once `approvals/approval-vNNN.json` (`jjv/library-image-approval/v1`, binds take sha + receipt sha + ref hashes); an approval is stale (None, no older one revived) when the image, the receipt or any reference changes. No `native` for library images (native = the 864x480 H3 anchor of a SHOT image). **Adopt (N25):** for a domain whose routes row has `provenance_required: true` (live action) `images adopt` is Refused unless `--requested-model` is given and `--source-path` is an EXISTING file that, links resolved, is under `<codex_home>/generated_images` of an account in machine.json and has the same sha256 as `--file` (receipt `source_sha256`) (a ComfyUI image cannot be adopted as GPT); cartoon keeps the old behaviour (default model "GPT Image Gen 2", path optional). Review-workflow publication is serialised per episode (`.jjv-publish.lock`). **Locks (N20-fix):** the label, pool-state and publish locks are the images engine's own (`engine/images/lease.py`, JSON body pid+host+time, NOT the ComfyUI lock): a lock whose pid is dead (same host) or older than its maximum age is reclaimed and logged to `<lock>.reclaim.log`; a live holder is waited for, then Refused with `codex image label lock <label> held by pid N ... since ...`; no lock = no take folder left behind; cooling is re-read after the label lock; `mark_good` runs only after the receipt exists. Not with `--n`, `--take`, `--prompt-file`. Give each lane a DIFFERENT shot: take numbers are picked per shot folder, two lanes on one shot can collide on the take folder |
| `images adopt --route codex-builtin --file PNG --prompt-file P (--refs-from-plan \| --ref ROLE=PATH)` | CPU | candidate receipt (`resolved_model` and `runtime_id` null) |
| `images compare --shot S [--sha ..]` | CPU | `compare/compare-<digest>.png` + `.json`, `compare/checklist.json` (re-runs never overwrite a reviewed entry) |
| `images approve --shot S --sha X --reviewer R --scope T` | CPU | `approvals/approval-vNNN.json`; needs a `pass` for all six checklist items for that exact sha |
| `images native --shot S --sha X [--center-crop --allow-unapproved]` | CPU | `native/<shot>-native864-<sha12>.png` + receipt (needs a current approval unless `--allow-unapproved`) |

Providers: `comfyui-local` (Krea2 edit, pilot-gated), `openrouter` (paid), `codex-adopt` (hand-made, hash-bound), `codex-exec` (GPT OAuth through
`codex exec`, account pool; the engine reads PATHS and LABELS only and checks `<codex_home>/auth.json` exists, never a token). A PNG without a receipt is
not an anchor; approvals bind a sha and go stale if the bytes change. Domain table lives in `recipes/images/routes-v002.json` (v001 kept; a domain may narrow it with
`images.allowed_providers`): the cartoon domain allows `comfyui-local, openrouter, codex-adopt, codex-exec`; the live-action domain allows
`comfyui-local, codex-adopt, codex-exec` since 2026-10-30 (user decision: hybrid, compare, user picks) and refuses `openrouter` BEFORE any file or network access. Layout passes come from CPU ray casts, so depth/mask need no GPU. Pending machine
keys (M3): `tools.blender_exe`, `images.codex_bin`, `images.codex_state_path`, `images.codex_accounts` (labels + homes only); until then the two stages read
`machine.json` without schema validation, and Blender is found via `--blender` / `$BLENDER` / PATH, accounts via `--codex-account LABEL=HOME`.

## Transitions: suggest / preview / swap (`engine/editorial/boundaries_suggest*.py`, `presets_swap.py`)

```
jjv editorial presets list | show NAME                  # 33 presets, 30 ready; `push`/`dip`/`flash` resolve to cut_push / dip_white / dip_white
jjv editorial presets --episode E --boundaries B [--boundary T1010] [--word-timing W] [--allow-outside P]   # tail feasibility table
jjv editorial boundaries suggest --episode E --boundaries B --out DIR [--shots shots.json] [--compare-config review-config.json]
jjv editorial boundaries preview --episode E --boundaries B --boundary T1310 --presets push,dip,cut --out GALLERY [--context-frames 24]
jjv editorial boundaries swap    --episode E --boundaries B --boundary T1310 --preset push --out WORKSPACE [--dry-run]
```
Rule in one paragraph: `suggest` measures, on the source clips, the Q3 normalised correlation of the LAST editorial frame of the outgoing shot against the
FIRST frame of the incoming one: `ncc >= 0.35` (Q3 same-framing) or `0.25 <= ncc < 0.35` (near-same, calibrated on the approved v015 cut) -> hard cut + push-in
(`cut_push`, 1.04 -> 1.00 over 12 f), alternatives only `cut` (plus the dissolve family when same-framing AND continuity `agree`); `ncc < 0.25` -> dip / light /
camera family, `whip` when a move is declared (`g_bridge` or a motion word in the motivation), else `dip_white` (needs 1 native tail frame; no handle -> falls back to
`whip` and says so); shots.json carries -> `none`. Output `boundaries-suggested.json` (write-once). `preview` renders 24 f each side per candidate with a PROXY
compositor (numpy + ffmpeg, CPU only, labelled; a tail preset without a handle gets a card with the reason, no clip). `swap` is data: `versions/boundaries-vNNN.json` +
`boundaries.json` + `swap-log.json` in a workspace, never the declared table, and lists the segments to re-composite.
Limits: the preview is a proxy (final look = `remotion-kit/tools/gallery.cjs --config <kit-config> --boundary T1310 --only cut_push,dip_white,cut`); graphic boundaries
(intro, cards, end plate, outro) are structural and kept as declared (intro bloom synthesized when no row); `LAYOUT_CHANGE_NCC_MAX = 0.25` and the motion-word list are calibrated
on one episode (7 cuts): re-measure on the next episode. `engine/editorial/segments.py` writes `segments.json` (`jjv/segments/v1`) with `build-config`: the film's cut list (kinds
`intro shot_span transition logo_hold card plate ending`), covering `[0,total)` exactly, no cut inside any effect window, `join_frame` (iris endings) = `logo_disc.in + 3`,
byte-identical on rebuild.

## Kit: ending segment, segment cache, one-command edits

Everything CPU only, in `remotion-kit/`.

**Ending as its own segment** (compositing-only; SILENT closed-GOP video joined by stream copy; audio is one mix never cut at the join):
```
node render.cjs --config C --segments-plan                                           # [{id, kind, start, end_exclusive, frames, shot_video_frames}] + plan sha256
node render.cjs --config C --mode review|master --segment main|ending --out seg.mp4  # the ending stages NO shot video
node render.cjs --config C --mode review|master --audio-only --out mix.wav           # whole-film audio, 48 kHz, once
node tools/join-segments.cjs --segments main.mp4,ending.mp4 --audio mix.wav --out film.mp4 [--overwrite]
node render.cjs --config C --segment ending --within A-B --png-seq DIR               # pixel-parity check
```
The MAIN segment owns the iris (it is a mask over the last shot's picture); the cut is the first frame with no shot video (`ending.discIn + 3`), so a logo-hold /
card / plate change never decodes a shot clip and in the 4K master the ending never waits for a restored core. Join parameters: h264 `yuv420p`, crf 18 review / 16
master, bt709 tags, 30 fps, `-x264-params open-gop=0`, no audio; the join (`ffmpeg -f concat -c:v copy`, bitexact) writes `<film>.join-record.json` and refuses unless every
segment keeps its sha256 + framemd5 list, the records belong to one plan and are contiguous, stream parameters are identical, the film's framemd5 md5 column equals the concatenation of
the segments' columns, pts runs 0..N-1, `nb_read_frames == total` and the film decodes clean; the audio join refuses a mix that is not 48 kHz or differs from the film length by more than
one frame (1600 samples per frame at 30 fps, join sample = J x 1600). `config.segments` (`[{id, kind, start, end_exclusive}]`) is refused when it does not cover the film, repeats an
id, has an empty segment or cuts inside an iris / dip / both-pictures window. Measured on ep04 (historical, pre-3444; not re-run): 3300 frames, `H_film == H_seg` 3300/3300; `ending.mp4` rendered twice has the same sha256.

**Segment cache** (`--segments-file segments.json --segments-build CACHE [--explain] [--out film.mp4] [--force-segment ID,ID] [--build-concurrency 1|2]`): each segment is rendered once,
silent, under a node key = sha256 of {kind, pins (Remotion version, browser exe + fonts sha, gl, mode, scale, codec set, preset catalog sha, video-relevant kit `src/**` sha), the
slice parts the segment can depend on}. A stale reason is the leaf diff against the previous build (`last-run.json`). `COMPLETE` = same key and bytes: never re-rendered. `CORRUPT` =
bytes or record no longer match: the build REFUSES, names the segment, writes no film (`--force-segment ID` re-renders). The audio slice is exactly what the one mix reads (every clip is
`<OffthreadVideo muted>`, so no picture / tail / transition row is audio); a picture-only edit never renders the mix. Measured on ep04 (historical, pre-3444; not re-run: derived 3374 f, 49 segments, 1080p, CPU, concurrency 2; the current master is 3444 f):
cold in-process 243 s (children 497 s, byte-identical), ONE word moved = 1 segment, 27.9 s, framemd5 equal to the cold film outside that segment; one `cut_push` 12 -> 10 f = 2 segments; only the
music file = 0 segments (mix re-rendered); a flipped byte in a cache entry = build refused. `shots[].onsetEvidence` / `speechOnsetF` are validator-only (they do not stale segments).

**One command** `jjv edit review-render | master-render`:
```
jjv edit review-render --cache C (--out film.mp4 | --explain) --episode-root R --episode E/engine/episode.json --boundaries B --word-timing W --episode-text T
    [--allow-outside LOGO]... [--browser CHROME] [--workdir D] [--build-concurrency 1|2] [--build-mode inproc|children]
    [--force-segment ID,ID] [--rehash-all] [--no-hash-cache] [--overwrite] [--segments-file S]
jjv edit master-render --cache C (--out film.mp4 | --explain) --master-config KITMASTER.json (--segments-file S | --episode E --boundaries B --word-timing W --episode-root R) [same optional flags]
```
Steps (command + seconds in `<out>.edit-run.json`): (1) `editorial build-config` into `C/engine/current` (review-config, events, segments, receipt-bound summary); (2) `remotion-kit/lib/adapter-engine.cjs` ->
`C/kit-config.json`; (3) `render.cjs --segments-build` renders only stale segments (one staging, one bundle, one browser), join by stream copy with the framemd5 proof, run record `<out>.segments-run.json`.
`--explain` runs 1-2 and prints the stale table (`RENDER|COMPLETE|CORRUPT`, changed leaf paths), renders nothing. `master-render` does NOT build the master config: pass the receipt-bound
`--master-config` (4K cores, seam blends, tails) from the master adapter; without it the verb refuses by name; master keys include mode / scale 2 / crf 16 / 4K binding shas, so a master segment never reuses
a review entry. Exit 0 built or explained, 1 refused or failed (nothing written to `--out`), 2 usage. Cache layout: `C/engine/current/`, `C/kit-config.json`, `C/segments/composite.segment/<key>/`,
`C/segments/audio.mix/<key>/`, `C/segments/hash-cache.json` (sha256 per {path, size, mtime ns, inode}; `--rehash-all` audits it; a file hashed within 2 s of its last write is not trusted); the cache is
safe to delete (cost: a cold build). Not rendered yet: any 4K segment film.

**Feasibility, records, music bed, adapter, catalog sync**
* `node render.cjs --config C --list-presets [--boundary T1010|1010] [--mode review|master] [--master-config M] [--catalog F]` prints per boundary the tail handle and, for every ready preset,
  `{available, needsTailFrames, haveNativeFrames, maxFrames, reason, whyNot}`; no bundling, no browser. Every run calls `tailHandleIssues`: a chosen tail preset with a short handle is refused with the
  missing frames and "no GPU work is requested". ep04 handles: T1010 7 native tail frames (up to 8), T1310 13 (16), T1610 15 (18).
* Every render record carries `shot_sources` + `shot_sources_sha256`; `--previous-record PATH` adds `composite_only` (`composite-only: no shot source changed vs <sha12>` or `NOT composite-only: n source(s) changed`).
  A `--stage-needed` run compares only what it staged and says so.
* Music bed policy (`ending.music_bed` -> `config.music = {stemSeconds, bed}`): `extend: loop_phrase_crossfade|none`, `loop_start_s`, `loop_end_s`, `crossfade_frames`, `duck_db`, attack / release frames,
  `duck_under: words`; planned by `src/music-plan.mjs`; the stem must be UNDUCKED (a baked-in duck would be applied twice). Without a policy the stem plays as before.
* Engine adapter `remotion-kit/episodes/ep04/adapter-engine.cjs --review-config C --events E --receipt build-summary.json --episode-root DIR --episode-text FILE [--allow-outside P]... --out kit-config.json`:
  maps what `build-config` writes to a kit config (presets, tails, cards, ending, music bed); text not in the engine records (intro, strings, Vietnamese captions, card ipa/vi/example/icon, stems) comes from the
  episode-text file (`jjk-remotion-kit/episode-text/v1`; generated by `jjv text build`); a missing key is refused naming it; every path is episode-relative and hash-verified.
* Catalog sync: `node remotion-kit/tools/sync-catalog.mjs [--check]` writes `src/catalog.generated.mjs` from `schemas/transition-presets.json` (never hand-edit either; `--check` exits 1 on drift; `npm test` runs it).
  Renderers are pure descriptors in `src/catalog-render.mjs` (`cut_push`, `push_slide`, `zoom_through`, `zoom_out`, `iris_circle/diamond`, `clock_wipe`, `blinds`, `blur_crossfade`, `focus_pull`, `crossfade`, `wipe*`, `cloud`,
  `bubble`, `whip`, `pan_motivated`, the dip family, `card_flip_3d`), audited by `auditSeries`. Tests: `catalog-sync`, `presets-validation`, `descriptors`, `render-smoke` (`KIT_SKIP_RENDER_SMOKE=1` skips it).

## H3 inputs, legacy voice and the acceptance ledger (`engine/h3/inputs.py`, `prepare.py`, `accept.py`, `ledger.py`)

```
jjv h3 inputs --episode E --spec SPEC.json --images IMAGES_DIR --voice VOICE_DIR --out MANIFEST.json
              [--cast CAST.json] [--shots SHOTS.json] [--map ROLE=CHARACTER_ID]... [--carry-from H3_DIR]
```
* `--spec` is `jjv/h3-spec/v1`: template path, graph ports, face roles in port order and the explicit widget values (`mouth`). It holds no sha256. `load_spec` refuses a `legacy_voice` key, an unknown top-level key, a foreign `episode_id`, and a `defaults` block outside the graph keys.
* Anchor: the CURRENT image approval of the shot plus the `jjv images native` receipt made from that exact candidate with `anchor_approved: true`. A missing approval or native copy is Refused. A carry shot (no `anchor_shot`) with `--carry-from H3_DIR` takes the `carry` sink output of an ACCEPTED take.
* WAV: the listen-approved voice-finalize WAV, resolved through `voice-bindings.json` in `--voice`. The approval is checked by the same proof `h3 prepare` uses (`E_LISTEN_APPROVAL`).
* Faces: `--map ROLE=CHARACTER_ID` over `episode.cast_roles`; the cast is `--cast` or `episode.files.cast`.
* Every sha256 in the manifest is hashed from the file a receipt names. `--out` is write-once.

Legacy voice:
* `h3 inputs` never writes `legacy_voice`.
* `h3 prepare` accepts `legacy_voice: true` (with a `preparation_receipt` per shot) only when the episode id is in `recipes/h3/routes-v001.json` `legacy_voice_episodes` (today `["04-milk-and-mom"]`) and the receipt is a real H3 preparation receipt of that episode (`_legacy_proof` in `engine/h3/prepare.py`). Any other episode is Refused, naming the routes file.

Acceptance ledger:
* `<episode root>/engine/h3-acceptance-ledger.jsonl`, schema `jjv/h3-acceptance-ledger/v1`, append-only, one line per pick or reject. Each line carries `prev` and `line_sha256` (genesis for the first). A rewritten, dropped or reordered line, or a foreign episode, is Refused.
* A rejection is episode-wide: the ledger is keyed by take sha256, so re-preparing into a new `--out` cannot launder a rejected take. `decide` writes the ledger line BEFORE the per-shot record (a crash may over-reject, never under-reject).
* The accept functions (`decide`, `accepted_takes`, `status`, `require_accepted`) take the layout `Context` as the keyword `ctx`.
* Known limits (module docstring): `--by` is a name check only (no authentication); concurrent writers are not locked.

## Boundaries write (`engine/editorial/boundaries_write.py`)

```
jjv editorial boundaries write --storyboard-check SC.json --boundaries-input BI.json --contract DELIVERY-CONTRACT.json
                               [--suggested SUGG.json] [--media MEDIA.json] --out DIR
```
* Refused unless the storyboard check is `jjv/storyboard-check/v1` with `ok: true` and no pair problems, and it must cover every boundary the table needs. `BI.json` is the `boundaries-input.json` of `script ingest`.
* `--suggested` (`boundaries-suggested.json`, same `episode_id`) replaces the storyboard's choice row by row, keyed by (`from_shot`, `to_shot`).
* `--media` JSON: `cards_audio` as `{term: {path, sha256}}`, plus `icons`, `logo`, `expect_silent`.
* Output in `DIR`: `versions/boundaries-vNNN.json` (write-once; an identical payload reuses the last number, `reused: true`). Complete: also `DIR/boundaries.json` (atomic copy) and `DIR/boundaries.current.json` (stamped receipt, `jjv/boundaries-current/v1`; `load_document` runs `boundaries_current.verify` first and refuses a `boundaries.json` that does not match it, e.g. after a hand edit). Incomplete: `versions/boundaries-draft-vNNN.json` with `schema: jjv/boundaries-draft/v1` and a `pending` list, and NO `boundaries.json`.
* Minimums: the schema `minimum` values (for example `card.duration_frames`, `icons.hold_frames`, `ending.card_min_frames`, `ending.logo_hold_frames`, `ending.end_card_frames`) are sanity 1 only. The real floors come from the domain via `end_card.domain_floor`: `delivery.end_card.frames_min` (end card), `delivery.sections.logo_hold.min` (logo hold), `delivery.sections.vocab_card.min` (card length). A domain that grants no floor for a key refuses that key by name. `end_card.check_params` applies them.

## Q5 and the audio timeline against the contract

* `jjv qa review --episode E`: the episode DELIVERY CONTRACT total and the domain section floors bind Q5. A `--expect-frames` that contradicts the contract is refused (exit 1). Without `--episode`, `--expect-frames` defaults to the config's own total.
* `jjv qa preflight` and `jjv qa gate` take `--contract DELIVERY-CONTRACT.json`: `master.frames` and every section are checked.
* Audio: `engine/audio/timeline.py` raises `ContractMismatch` (a `Refused`, exit 1) when the audio timeline total differs from the contract's `total_frames`, or an audio section's start or kind differs from the contract's sections (`contract_starts`). Callers: `audio music plan` (`checked_sections`), `audio music pick|adopt` and `audio mix` (`resolve`).

## Receipt stamp (`stamp=True`, `engine/core/provenance.py`)

* A receipt written by `write_json_once` or `write_json_atomic` with `stamp=True` carries `engine_tree_sha256` (the sha of `engine/**`, `recipes/**`, `bin/**`, from `provenance.engine_tree_sha256`). The default is no stamp, so artefacts keep their bytes.
* `tests/test_m9a_receipt_stamp.py` runs an AST scan over `audio`, `qa`, `editorial`, `config`, `plan`, `voice`, `timing`, `deliver` and `publish`. Every writer call must stamp, or its first argument must be an entry of `NOT_RECEIPTS` with a reason (plan documents, `voice-bindings.json`, `timing.json`, versioned or live `boundaries.json`, the editable GUI inputs, `title-job.json`). It also refuses a writer passed as a value (invisible to the scan). Last run 2026-10-28: 4 passed.
* Adding an exemption means adding an entry with its reason to `NOT_RECEIPTS`; do not weaken the scan.

## Run, health, qa transitions, h3 publish-shots, deliver init (verified 2026-10-28 with `--help`)

Flags below are copied from `python -I bin/jjv.py <verb> --help`. Exit codes are those the help text states; anything not stated is marked.

### run (`engine/run/`, M8)
```
jjv run episode --episode E [--from STAGE] [--to STAGE] [--dry-run] [--approve-gpu] [--dag DAG] [--runs-root DIR]
                [--run-dir DIR] [--stages-root DIR] [--scratch DIR] [--json]
jjv run approve --episode E --gate {music-approval,user-review,publish-approval} [--verdict {accept,change,override}]
                --by NAME --note TEXT [--sha256 H] [--runs-root DIR]
```
* `--episode` takes an episode.json path, an episode root or a slug. Defaults: `--dag` = `recipes/run/episode-dag-v001.json`, `--runs-root` = `<episode>/engine/runs`, `--stages-root` = `<episode>/engine/stages`.
* `--dry-run` writes only `<run_dir>/plan.json` (schema `jjv/run-plan/v1`) and runs no verb. Measured 2026-10-28 on ep04 with `--run-dir`, `--runs-root`, `--stages-root`, `--scratch` pointed at a scratch folder: process exit 0; JSON `ok: false`, `ran_nothing: true`, `health_gate: available`, `first_stop` = `voice / synth` kind `gpu-approval` (exit_code 1, "nothing was submitted"). `ok` is true only when no stop is planned (`orchestrator.py` `ok: self.stop is None`), so exit 0 and `ok: false` together are normal.
* Stages the dry run reports as blocked: `h3` (`episode.files.h3_inputs` not declared in episode.json) and `master` (`episode.files.master_config` not declared). Both stay blocked until the episode declares them.
* Without `--approve-gpu` every GPU step stops; with it, the run still stops at each human gate. Next step text printed by a stop: "get the user's explicit approval for THIS run, then re-run with --approve-gpu --from voice".
* `run approve`: write-once and numbered; `--verdict` for `user-review` only means `change` (asks for another version) or `override` (allows a version beyond the limit); `--sha256` binds the record to one version; `--by` must be a person, not a machine name. Not measured: an approval written through this verb.

### health preflight (`engine/health/`, T-E39)
```
jjv health preflight [--episode E | --base-url U --container C] [--graph G] [--min-free-vram-mib N] [--fixture F] [--timeout S]
```
* Read-only: docker engine, container identity, ComfyUI HTTP, idle queue, free VRAM, optional graph node classes. Exit 0 ready, 1 not ready, and nothing is queued either way.
* `--fixture` is a dry form that takes a `jjv/health-fixture/v1` document instead of docker and HTTP. `--min-free-vram-mib` defaults to 0 (report only). Not run live in this 2026-10-28 check: docker and HTTP were not probed.

### qa expression (BP-47)
```
jjv qa expression --in TAKE.mp4 [--wav DIALOGUE.wav] [--out RECEIPT.json] [--params FILE] [--ffmpeg P] [--ffprobe P]
```
* One MP4 is one take. The read-only receipt contains the video/WAV/params hashes, dimensions/fps/frame count, detector backend, face-difference energy, blink count and (when WAV is provided) mouth/audio-envelope correlation.
* Optional MediaPipe Face Mesh is preferred for EAR and mouth-opening landmarks; otherwise OpenCV Haar face/eye regions are used. If neither is usable, the centered upper-frame proxy is explicitly marked and forces at least WARN. No optional package or model is installed by this verb.
* PASS requires sufficient non-frozen face-region change. Missing blinks or weak audio correlation are WARN; a strongly negative mouth/audio correlation and a frozen face can FAIL. Params live in `engine/qa/expression-params-v001.json` and remain `?? xu?t, ch?a hi?u ch?nh` until measured and approved. Exit 0 = PASS, 1 = FAIL, 2 = WARN.

### qa transitions (T-E34)
```
jjv qa transitions --episode E --video V --boundaries B [--timing T] [--out DIR] [--recipe F]
                   [--frame-origin N] [--layout-same-framing F,F,...] [--ffmpeg P] [--json]
```
* `--video` is the review export (whole film, or a clip with `--frame-origin`, the global frame of its first frame). `--boundaries` is `boundaries.json` (`jjv/boundaries/v1`) or a review config with `motion.transitions`. `--timing` gives the first spoken frame of the line after a dip (default: the review config's own dialogue words). `--recipe` defaults to `recipes/qa/review-gates-v001.json`.
* `--layout-same-framing` lists boundary frames declared NOT to change layout; a visible transition there FAILs. `--out` is the folder for `sheets/*.png` and `transitions-receipt.json` (default: a new temp folder). Not run in this check.

### h3 publish-shots (M8b e)
```
jjv h3 publish-shots --episode E --out H3DIR [--shots SHOTS] [--dest-dir DIR] [--ffprobe P]
```
* Writes `shots-h3-vNNN.json` (`jjv/shots/v1`) built from ACCEPTED takes only (`h3 accept`). `--out` is the H3 folder that holds every listed shot's accepted take. Every shot in `--shots` (default `episode.files.shots`) is required. `--dest-dir` defaults to the folder next to episode.json. `--ffprobe` defaults to `$FFPROBE` or PATH.

### deliver init (M8b g / g2)
```
jjv deliver init --episode E [--delivery-config F] [--repo-root DIR] [--out DIR]
```
* Writes the delivery config (default `<episode>/engine/delivery.json`, the file to write). `--repo-root` resolves episode slugs. `--out` is a fresh output folder; default from the delivery config.
* A value with no source is written as an explicit marker `{"missing": "MISSING_MACHINE_KEY:<key>"}` or `{"missing": "MISSING_EPISODE_KEY:<key>"}` (`engine/deliver/init.py`). The brand and publish verbs refuse that marker by name (`engine/deliver/common.py`).
