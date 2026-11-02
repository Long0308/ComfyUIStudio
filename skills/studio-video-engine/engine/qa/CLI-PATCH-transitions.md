# CLI patch for `jjv qa transitions` (T-E34), for root / Fable (M8) to apply

`engine/qa/cli.py` already registers the verb (`register_transitions(verbs)`), so `jjv qa transitions --help` parses.
`bin/jjv.py` (not mine) needs the dispatch, otherwise the verb falls through to "no handler":

```python
from engine.qa.transitions_cli import run_qa_transitions  # noqa: E402     # next to the other engine.qa imports
...
    if args.stage == "qa" and args.verb == "transitions":                    # in _dispatch, after the qa gate branch
        return run_qa_transitions(args)
```

Until then it runs standalone with the same flags: `python -I engine/qa/transitions_cli.py --episode E --video V --boundaries B [--timing T] [--out DIR]`.
Exit 0 PASS / 1 a check FAILs or a rule is violated / 2 UNCERTAIN or unreadable input. Receipt `DIR/transitions-receipt.json`
(`jjv/qa-transitions-receipt/v1`, provenance-stamped) + `DIR/sheets/tr-*.png` (native resolution, one per boundary).
`--boundaries` = `boundaries.json` or a review config; `--frame-origin N` for a clip; `--layout-same-framing F,F`.
