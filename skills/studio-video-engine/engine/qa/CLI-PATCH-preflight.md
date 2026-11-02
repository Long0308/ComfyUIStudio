> MERGED into SKILL.md 2026-10-28
# CLI patch for `jjv qa preflight` and `jjv qa gate`, for root to apply

I did not edit `bin/jjv.py` nor `engine/qa/cli.py` (other builders / outside my scope). Both verbs run today through their
own entry points (`python -I engine/qa/preflight_cli.py ...`, `python -I engine/qa/gate_cli.py ...`); these lines make them
reachable from `jjv`. Nothing else changes.

## 1. `engine/qa/cli.py`

Imports, next to `from .review_cli import register_review`:

```python
from .preflight_cli import register_preflight
from .gate_cli import register_gate
```

At the END of `register_cli(stages)`, after `register_review(verbs)`:

```python
    register_preflight(verbs)  # qa preflight: every check that needs no rendered pixels
    register_gate(verbs)       # qa gate: preflight + (after the render) qa review + qa words
```

## 2. `bin/jjv.py`

Import, next to `from engine.qa.review_cli import run_qa_review  # noqa: E402`:

```python
from engine.qa.preflight_cli import run_qa_preflight  # noqa: E402
from engine.qa.gate_cli import run_qa_gate  # noqa: E402
```

In `_dispatch`, directly after the `qa review` branch:

```python
    if args.stage == "qa" and args.verb == "preflight":
        return run_qa_preflight(args)
    if args.stage == "qa" and args.verb == "gate":
        return run_qa_gate(args)
```

(Module docstring verb list may gain `qa preflight`, `qa gate`.) `run_qa_*` raise `EngineError` for a malformed config / bad
recipe; `jjv`'s existing top-level handler turns that into JSON + exit 1/2, same as `qa review`.

## Usage

```
jjv qa preflight --config review-config.json [--timing WORD-TIMING.json] [--icons DIR] [--events events.json]
    [--episode E] [--root DIR] [--contract DELIVERY-CONTRACT.json | --expect-frames N]
    [--music-receipt music-finalize.json] [--mix-receipt mix-receipt.json] [--with-sfx] [--allow-ungated-music] [--require-audio]
    [--checks Q1,PACING,TRANSITIONS,ICONS,AUDIO] [--layout-same-framing F,F,...] [--allow-outside P]...
    [--preflight-recipe F] [--review-recipe F] [--timing-recipe timing/<id>] [--ffmpeg P] [--out report.json] [--json]

jjv qa gate --config review-config.json [every flag above] [--video review.mp4 [--mix mix.wav] [--gates Q2,Q3,Q4,Q5]
    [--sheets-dir DIR] [--frame-origin N --audio-origin-s S]] [--out report.json]
```
One JSON report on stdout (`jjv/qa-preflight-report/v1`, `jjv/qa-gate-report/v1`), summary on stderr, exit 0 PASS / 1 a check
FAILs (or a rule is violated) / 2 UNCERTAIN (an input is missing or unreadable). FAIL beats UNCERTAIN. `--timing` defaults to the
config's `word_timing.path` (and its `word_timing.sha256` must match the file), With `--episode`, the section floors/ceilings come from `domain.delivery.sections.{vocab_card,logo_hold}` and `delivery.end_card` (they can only RAISE the review-recipe floors) and the frame total from `rules.timeline_frames` (the episode contract) when neither `--expect-frames` nor `--contract` is given. `--root` defaults to the folder above the config that holds
`engine/episode.json`.

## Text for SKILL.md (root; add after the `jjv qa review` paragraph)

`jjv qa preflight` (audit gap 5): every check that needs NO rendered pixels, run before a render is allowed. Q1 on the word timing
(`timing.gate.check_document`, the `qa words` detector + negative control; the timing must hash to the config's `word_timing.sha256`),
pacing (`q5_pacing` arithmetic + EVERY card >= 90 f, declared AND derived from the card start frames, the review-recipe floor always
applies; dialogue pieces tile; logo + cards join; total == `--contract` `master.frames`; every contract section matches), transitions
(a white flash / dip / bloom between two picture shots is refused when the SOURCE clips' boundary frames have NCC >= 0.25, or the
config declares `layout_change: false` / `framing: same_framing`; a both-shots type next to a picture needs `continuity: agree`;
unknown type refused), icons (file level of Q2: anchor/card coverage, sha binding, opposite pairs = different PNGs with distinct
delta E / hue, two words never share one image unless `shared_icon`), audio contract (from receipts: music vocal gate PASS, SFX off
unless opted in, brand voice ends 0.2 s before the first word; no receipt = SKIPPED + warning, UNCERTAIN with `--require-audio`).
Recipe `recipes/qa/preflight-v001.json` (floors and icon thresholds come from `review-gates-v001.json`). Code `engine/qa/preflight*.py`;
tests `tests/test_qa_preflight_*.py`. `jjv qa gate` = the preflight, and with `--video` also `qa review` (Q2-Q5); `qa words` is the
preflight's Q1, reported once as the `words` stage. Verdict = roll-up; `render_allowed` = the preflight verdict is PASS.
