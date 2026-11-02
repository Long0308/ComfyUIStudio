> MERGED into SKILL.md 2026-10-28
# Registration of gate `Q1b caption` in `jjv qa review` (for root to apply)

I did not edit `engine/qa/review.py` / `review_cli.py` / `bin/jjv.py` (another builder is active in `bin/jjv.py`, mtime 21:59;
`review.py` was idle since 20:51 but is outside my file scope). The gate is complete and runnable on its own; registration is two
lines in `engine/qa/review.py`:

```python
from .gates import FAIL, PASS, UNCERTAIN, q1b_caption, q2_icons, q3_flash, q4_ghost, q5_loudness, q5_pacing, roll_up   # add q1b_caption
ALL_GATES = ("Q1B", "Q2", "Q3", "Q4", "Q5")                                                                               # add "Q1B"
```

and one entry in the `steps` dict of `run_review` (its own recipe `recipes/qa/q1b-caption-v001.json`, not the review recipe):

```python
"Q1B": lambda: q1b_caption.run_q1b(config, video, ffmpeg=ffmpeg, origin=origin),
```

`--gates Q1B` (the CLI upper-cases names; the gate dict reports `"gate": "Q1b"`). `run_review` already skips the gray decode when only
Q1B is selected. The default of `--gates` in `review_cli.py` may become `Q1B,Q2,Q3,Q4,Q5`. The future `jjv qa gate` can call
`run_q1b(config, video, ffmpeg=..., recipe=None, origin=0)` directly: it returns `{"gate","status","failures","summary","control","words","timing_s"}`.

Stand-alone, today: `python -I engine/qa/gates/q1b_caption.py --config <review-config.json> --video <review.mp4> [--frame-origin N] [--out report.json]`
(exit 0 PASS / 1 FAIL / 2 UNCERTAIN; summary on stderr, JSON on stdout).

To check an export against CORRECTED timing, pass the corrected config (the picture of an older cut then fails on each word that moved).
