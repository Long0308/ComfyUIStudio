"""CLI glue for ``jjv plan explain`` (see CLI-PATCH.md for the two lines ``bin/jjv.py`` needs)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import report
from .api import plan_explain
from .graph import TARGETS


def add_explain_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--old", required=True, help="directory of the OLD inputs (config/review-config*.json, RECEIPT.json "
                                                       "or plan-inputs.json)")
    parser.add_argument("--new", required=True, help="directory of the NEW inputs")
    parser.add_argument("--target", choices=TARGETS, default="review",
                        help="review (1080p segments + mux), master (4K) or all; default review")
    parser.add_argument("--costs", default=None, help="cost table (default recipes/plan/costs-v001.json)")
    parser.add_argument("--policy", default=None, help="slice policy (default recipes/plan/policy-v001.json)")
    parser.add_argument("--episode", default=None, help="episode.json path, episode root or slug: annotate the plan with "
                                                        "the episode's Studio feedback notes (editorial/review-feedback/"
                                                        "feedback-v1.jsonl); notes never change what re-renders")
    parser.add_argument("--feedback", default=None, help="explicit feedback JSONL inside the episode root "
                                                         "(requires --episode)")
    parser.add_argument("--json-out", default=None, help="also write the JSON here (a new file; never overwritten)")
    parser.add_argument("--verbose", action="store_true", help="table lists every node, not only the changed ones")
    parser.add_argument("--no-table", action="store_true", help="JSON only (no human table on stderr)")


def register_cli(stages: Any) -> None:
    """Register the ``plan`` stage and its ``explain`` verb on the main parser."""
    plan = stages.add_parser("plan", help="incremental planner (explain only; never runs anything)")
    verbs = plan.add_subparsers(dest="verb", required=True)
    add_explain_arguments(verbs.add_parser("explain", help="what does OLD -> NEW re-render, and what does it cost"))


def run_plan(args: argparse.Namespace) -> int:
    """JSON on stdout, the human table on stderr; exit 0 computed (GPU jobs are only listed), 1 refused, 2 unreadable."""
    doc = plan_explain(args.old, args.new, costs_path=args.costs, policy_path=args.policy, target=args.target,
                       episode=args.episode, feedback=args.feedback)
    text = json.dumps(doc, indent=2, ensure_ascii=True)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as stream:      # exclusive create: an existing file is never replaced
            stream.write(text + "\n")
    print(text)
    if not args.no_table:
        print(report.table(doc, verbose=args.verbose), file=sys.stderr)
        if "feedback" in doc:
            print(report.feedback_table(doc["feedback"]), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Standalone entry (``python engine/plan/__main__.py explain ...``): the same exit-code contract as ``jjv``."""
    from ..core.errors import EngineError, exit_code_for
    parser = argparse.ArgumentParser(prog="jjv-plan", description=__doc__)
    verbs = parser.add_subparsers(dest="verb", required=True)
    add_explain_arguments(verbs.add_parser("explain"))
    args = parser.parse_args(argv)
    try:
        return run_plan(args)
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except FileExistsError as error:
        print(json.dumps({"ok": False, "error": f"refusing to overwrite {error.filename}"}, indent=2))
        return 1
