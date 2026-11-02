"""CLI glue of ``jjv qa review`` (see ``CLI-PATCH-review.md`` for the two lines root adds to ``bin/jjv.py`` and
``engine/qa/cli.py``).  Also runnable on its own: ``python -I engine/qa/review_cli.py --config C --video V``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.errors import EngineError, Refused, Uncertain, exit_code_for  # noqa: E402
from engine.core.provenance import stamp  # noqa: E402
from engine.core.io import read_json, sha256_file, write_json_atomic  # noqa: E402
from engine.config import rules  # noqa: E402
from engine.qa import review, review_recipe  # noqa: E402
from engine.qa.preflight_cli import domain_limits  # noqa: E402
from engine.qa.scope import resolve_episode_or_uncertain  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="review config (engine-built or hand-built)")
    parser.add_argument("--video", required=True, help="review export .mp4")
    parser.add_argument("--mix", default=None, help="mix WAV to measure loudness on (default: the video's audio)")
    parser.add_argument("--events", default=None, help="engine events.json (icon_events) instead of the config's own icons")
    parser.add_argument("--root", default=None, help="folder that relative paths in the config are relative to "
                                                     "(default: the config's folder)")
    parser.add_argument("--recipe", default=None, help="qa recipe JSON (default recipes/qa/review-gates-v001.json)")
    parser.add_argument("--gates", default="Q2,Q3,Q4,Q5", help="comma list of gates to run")
    parser.add_argument("--sheets-dir", default=None, help="folder for the Q4 contact sheets (default: a new temp folder)")
    parser.add_argument("--out", default=None, help="write the report here (overwritten)")
    parser.add_argument("--episode", default=None, help="episode.json path, root or slug: the episode DELIVERY CONTRACT total "
                                                        "and the domain section floors bind Q5 (a contradicting --expect-frames is refused)")
    parser.add_argument("--expect-frames", type=int, default=None, help="contract frame count (default: the config's own total)")
    parser.add_argument("--frame-origin", type=int, default=0, help="global frame number of the file's first frame (clips)")
    parser.add_argument("--audio-origin-s", type=float, default=0.0, help="global second of the audio's first sample (clips)")
    parser.add_argument("--layout-same-framing", default=None, metavar="F,F,...",
                        help="boundary frames declared NOT to change layout (tightens Q3)")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--json", action="store_true", help="JSON only: no summary on stderr")


def register_review(verbs: Any) -> None:
    """Add the ``review`` verb to the ``qa`` sub-parsers (call from ``engine/qa/cli.py register_cli``)."""
    add_arguments(verbs.add_parser("review", help="automatic review-cut gates Q2 icons, Q3 flash, Q4 ghost, Q5 pacing/loudness"))


def _frames(text: str | None) -> frozenset[int]:
    try:
        return frozenset(int(t) for t in (text or "").split(",") if t.strip())
    except ValueError as error:
        raise Refused(f"--layout-same-framing must be a comma list of integer frames: {error}") from error


def _summary(report: dict) -> str:
    lines = [f"{report['verdict']}  (exit {report['exit_code']})  {report['timing_s']['total']} s  "
             f"{report['video']['frames']} f {report['video']['width']}x{report['video']['height']}"]
    for name, gate in report["gates"].items():
        lines.append(f"  {name}: {gate['status']}  {timing(report, name)} s")
        lines += [f"      - {text}" for text in gate.get("failures", [])[:12]]
    if report.get("sheets_dir"):
        lines.append(f"  Q4 sheets: {report['sheets_dir']}")
    return "\n".join(lines)


def timing(report: dict, name: str) -> Any:
    return report["timing_s"].get(name, "-")


def run_qa_review(args: argparse.Namespace) -> int:
    """One JSON report on stdout; exit 0 PASS, 1 a gate FAILs (or a rule is violated), 2 uncertain/unreadable."""
    config_path = Path(args.config)
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise Refused(f"{config_path.name}: review config must be a JSON object")
    recipe, recipe_sha = review_recipe.load_recipe(Path(args.recipe) if args.recipe else None)
    events = read_json(Path(args.events)) if args.events else None
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
    except Refused as error:
        raise Uncertain(str(error)) from error
    limits, episode_total = None, None
    if args.episode:
        resolved = resolve_episode_or_uncertain(args.episode)
        limits = domain_limits(resolved.domain)
        episode_total = rules.timeline_frames(resolved.episode, resolved.domain)["total_frames"]
    report = review.run_review(
        config=config, video=Path(args.video), ffmpeg=ffmpeg, recipe=recipe, recipe_sha256=recipe_sha,
        config_sha256=sha256_file(config_path), root=Path(args.root) if args.root else config_path.resolve().parent,
        mix=Path(args.mix) if args.mix else None, events=events,
        gates=tuple(g.strip().upper() for g in args.gates.split(",") if g.strip()),
        sheets_dir=Path(args.sheets_dir) if args.sheets_dir else None, origin=args.frame_origin,
        audio_origin_s=args.audio_origin_s, expect_frames=args.expect_frames,
        layout_non_change=_frames(args.layout_same_framing), limits=limits, episode_total=episode_total)
    report = stamp(report)  # the printed report and the file carry the same engine_tree_sha256 header
    if args.out:
        write_json_atomic(Path(args.out), report, mode="ascii")
    if not args.json:
        print(_summary(report), file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return report["exit_code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-review", description=__doc__)
    add_arguments(parser)
    try:
        return run_qa_review(parser.parse_args(argv))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except Exception as error:  # noqa: BLE001 - the CLI contract is "JSON + exit 2", not a traceback
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
