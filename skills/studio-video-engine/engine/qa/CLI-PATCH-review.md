> MERGED into SKILL.md 2026-10-28
# CLI patch for `jjv qa review` (T-E36/T-E34), for root to apply

I did not edit `bin/jjv.py` (another builder needs it) nor `engine/qa/cli.py` (outside my scope). Two edits, verified by
applying them textually in memory and running `jjv qa review ...` (see "Verified" below).

## 1. `engine/qa/cli.py`

Import, next to the other imports:

```python
from .review_cli import register_review
```

At the END of `register_cli(stages)` (after the `parser.add_argument("--json", ...)` line of the `av` verb), add:

```python
    register_review(verbs)
```

## 2. `bin/jjv.py`

Import, next to `from engine.qa.cli import register_cli as register_qa, run_qa_av  # noqa: E402`:

```python
from engine.qa.review_cli import run_qa_review  # noqa: E402
```

In `_dispatch`, directly after the `qa av` branch:

```python
    if args.stage == "qa" and args.verb == "review":
        return run_qa_review(args)
```

(The module docstring list of verbs may gain `qa review`.)

## Usage

```
python -I bin/jjv.py qa review --config <review-config.json> --video <review.mp4> [--mix <mix.wav>] [--events events.json]
    [--gates Q2,Q3,Q4,Q5] [--sheets-dir DIR] [--out report.json] [--expect-frames N] [--root DIR] [--recipe F]
    [--layout-same-framing F,F,...] [--frame-origin N --audio-origin-s S]  (clips) [--ffmpeg P] [--json]
```
Until the patch is applied the same handler runs standalone: `python -I engine/qa/review_cli.py <same flags>`.
One JSON report on stdout (`jjv/qa-review-report/v1`), summary on stderr, exit 0 PASS / 1 a gate FAIL (or a rule
violation: bad config, loosened threshold, unknown gate) / 2 UNCERTAIN (a gate could not decide, or an input is missing).
FAIL beats UNCERTAIN. Relative paths in the config resolve against `--root` (default: the config's folder).

## Text for SKILL.md (root, replaces the "Not yet implemented: `qa transitions`, `qa review-gates`" sentence)

`jjv qa review` (T-E36): Q2 icons (coverage within +-3 f of the anchor word, hash binding, opposite pairs differ: icon-file
mean colour delta E + hue, and the tile rendered at pop+9 f), Q3 flash scan (per-frame luma spike only at flash/dip/whip/bloom
boundaries; a white flash only where the framing really changes; luma step at cuts), Q4 transition ghost (a full-resolution
contact sheet PNG per transition window + double-exposure proxy for picture pairs), Q5 pacing (logo still >= 60 f, cards >= 90 f,
tiling, total frames, ffprobe facts, measured still, ebur128 per section -17 +-1 LUFS / <= -1 dBTP / <= 2 LU between sections).
Thresholds: `recipes/qa/review-gates-v001.json`; a config `qa.review` block may only tighten. Code `engine/qa/review*.py`,
`engine/qa/gates/`; tests `tests/test_qa_review_*.py` (clips cut from the real ep04 exports; whole films with `JJV_QA_REVIEW_FULL=1`).
Q1 (word-sync onset) is not part of it.
