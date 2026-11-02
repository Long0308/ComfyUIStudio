"""``jjv qa gate``: the single gate the pipeline calls = preflight + (after the render) qa review + qa words.

Before the render (no ``--video``): the preflight alone; ``render_allowed`` says whether a render may start.
After the render (``--video``): the preflight AND ``qa review`` (Q2-Q5 on the pixels) run, and the verdict is the
roll-up (FAIL beats UNCERTAIN beats PASS; exit 0 / 1 / 2 like ``qa review``).  ``qa words`` is the Q1 detector the
preflight already runs on the same timing (``timing.gate.check_document``): it is reported once, as the ``words`` stage,
not run twice.  See ``CLI-PATCH-preflight.md``.  Also runnable on its own: ``python -I engine/qa/gate_cli.py --config C``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.errors import EngineError, exit_code_for  # noqa: E402
from engine.core.provenance import stamp  # noqa: E402
from engine.core.io import write_json_atomic  # noqa: E402
from engine.qa import preflight, preflight_cli, review  # noqa: E402
from engine.qa.gates import FAIL, PASS, UNCERTAIN, roll_up  # noqa: E402

REPORT_SCHEMA = "jjv/qa-gate-report/v1"
EXIT = {PASS: 0, FAIL: 1, UNCERTAIN: 2}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    preflight_cli.add_arguments(parser)
    parser.add_argument("--video", default=None, help="review export .mp4: given = the post-render stage (qa review) runs too")
    parser.add_argument("--mix", default=None, help="mix WAV to measure loudness on (default: the video's audio)")
    parser.add_argument("--gates", default="Q2,Q3,Q4,Q5", help="comma list of qa review gates to run after the render")
    parser.add_argument("--sheets-dir", default=None, help="folder for the Q4 contact sheets (default: a new temp folder)")
    parser.add_argument("--frame-origin", type=int, default=0, help="global frame number of the file's first frame (clips)")
    parser.add_argument("--audio-origin-s", type=float, default=0.0, help="global second of the audio's first sample (clips)")
    parser.add_argument("--out", default=None, help="write the combined report here (overwritten)")
    parser.add_argument("--json", action="store_true", help="JSON only: no summary on stderr")


def register_gate(verbs: Any) -> None:
    """Add the ``gate`` verb to the ``qa`` sub-parsers (call from ``engine/qa/cli.py register_cli``)."""
    parser = verbs.add_parser("gate", help="the single QA gate: preflight, and after the render also qa review + qa words")
    add_arguments(parser)


def _review(args: argparse.Namespace, inputs: dict, pre_report: dict) -> dict:
    expect = inputs["expect_frames"]
    if expect is None:
        expect = pre_report["gates"].get("PACING", {}).get("contract_frames")
    return review.run_review(
        config=inputs["config"], video=Path(args.video), ffmpeg=inputs["ffmpeg"], recipe=inputs["recipe"],
        recipe_sha256=inputs["recipe_sha256"], config_sha256=inputs["config_sha256"], root=inputs["root"],
        mix=Path(args.mix) if args.mix else None, events=inputs["events"],
        gates=tuple(g.strip().upper() for g in args.gates.split(",") if g.strip()),
        sheets_dir=Path(args.sheets_dir) if args.sheets_dir else None, origin=args.frame_origin,
        audio_origin_s=args.audio_origin_s, expect_frames=expect, layout_non_change=inputs["declared_same_framing"])


def run_gate(args: argparse.Namespace) -> dict:
    inputs = preflight_cli.prepare(args)
    pre_report = preflight.run_preflight(**inputs)
    review_report = _review(args, inputs, pre_report) if args.video else None
    words = pre_report["gates"].get("Q1")
    stages = {"preflight": pre_report["verdict"], "review": review_report["verdict"] if review_report else "NOT_RUN",
              "words": words["status"] if words else "NOT_RUN"}
    verdict = roll_up([pre_report["verdict"]] + ([review_report["verdict"]] if review_report else []))
    return {"schema": REPORT_SCHEMA, "verdict": verdict, "ok": verdict == PASS, "exit_code": EXIT[verdict],
            "mode": "post-render" if review_report else "pre-render",
            "render_allowed": pre_report["render_allowed"], "stages": stages,
            "words": words, "preflight": pre_report, "review": review_report}


def summary(report: dict) -> str:
    lines = [f"GATE {report['verdict']}  (exit {report['exit_code']})  {report['mode']}  stages {report['stages']}"]
    lines.append(preflight_cli.summary(report["preflight"]))
    if report["review"]:
        for name, gate in report["review"]["gates"].items():
            lines.append(f"  review {name}: {gate['status']}")
            lines += [f"      - {text}" for text in gate.get("failures", [])[:12]]
    return "\n".join(lines)


def run_qa_gate(args: argparse.Namespace) -> int:
    """One JSON report on stdout; exit 0 PASS, 1 FAIL/rule violation, 2 uncertain/unreadable."""
    report = run_gate(args)
    report = stamp(report)  # the printed report and the file carry the same engine_tree_sha256 header
    if args.out:
        write_json_atomic(Path(args.out), report, mode="ascii")
    if not args.json:
        print(summary(report), file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return report["exit_code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-gate", description=__doc__)
    add_arguments(parser)
    try:
        return run_qa_gate(parser.parse_args(argv))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except Exception as error:  # noqa: BLE001 - the CLI contract is "JSON + exit 2", not a traceback
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
