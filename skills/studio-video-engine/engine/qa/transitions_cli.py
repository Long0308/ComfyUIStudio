"""CLI glue of ``jjv qa transitions`` (T-E34).  See ``CLI-PATCH-transitions.md`` for the lines root adds to ``bin/jjv.py``.
Also runnable on its own: ``python -I engine/qa/transitions_cli.py --episode E --video V --boundaries B``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.errors import EngineError, Refused, Uncertain, exit_code_for  # noqa: E402
from engine.core.io import read_json, sha256_file, write_json_atomic  # noqa: E402
from engine.core.provenance import stamp  # noqa: E402
from engine.qa import review_media, review_recipe, transitions_load, transitions_run  # noqa: E402
from engine.qa.scope import resolve_episode_or_uncertain  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402

SCHEMA = "jjv/qa-transitions-receipt/v1"
RECEIPT_FILE = "transitions-receipt.json"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug (delivery fps)")
    parser.add_argument("--video", required=True, help="review export .mp4 (whole film, or a clip with --frame-origin)")
    parser.add_argument("--boundaries", required=True,
                        help="boundaries.json (jjv/boundaries/v1) or a review config with motion.transitions")
    parser.add_argument("--timing", default=None, help="WORD-TIMING.json: first spoken frame of the line after a dip "
                                                       "(default: the review config's own dialogue words)")
    parser.add_argument("--out", default=None, help="folder for sheets/*.png and transitions-receipt.json (default: a new temp folder)")
    parser.add_argument("--recipe", default=None, help="qa recipe JSON (default recipes/qa/review-gates-v001.json)")
    parser.add_argument("--frame-origin", type=int, default=0, help="global frame number of the file's first frame (clips)")
    parser.add_argument("--layout-same-framing", default=None, metavar="F,F,...",
                        help="boundary frames declared NOT to change layout (a visible transition there FAILs)")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--json", action="store_true", help="JSON only: no summary on stderr")


def register_transitions(verbs: Any) -> None:
    """Add the ``transitions`` verb to the ``qa`` sub-parsers (called from ``engine/qa/cli.py register_cli``)."""
    add_arguments(verbs.add_parser("transitions", help="full-resolution mid-transition checks: ghost, dip peak vs first "
                                                       "spoken frame, same seat = cut/cut_push, contact sheets"))


def _frames(text: str | None) -> frozenset[int]:
    try:
        return frozenset(int(t) for t in (text or "").split(",") if t.strip())
    except ValueError as error:
        raise Refused(f"--layout-same-framing must be a comma list of integer frames: {error}") from error


def _summary(receipt: dict) -> str:
    lines = [f"TRANSITIONS {receipt['verdict']}  (exit {receipt['exit_code']})  {receipt['counts']['judged']} judged, "
             f"{receipt['counts']['skipped']} skipped"]
    for row in receipt["rows"]:
        lines.append(f"  {row['id']:<7} {row['type']:<10} {row['status']}")
        lines += [f"      - {text}" for text in row["reasons"]]
    return "\n".join(lines)


def run_qa_transitions(args: argparse.Namespace) -> int:
    """One JSON receipt on stdout; exit 0 PASS, 1 a check FAILs (or a rule is violated), 2 uncertain/unreadable."""
    episode = resolve_episode_or_uncertain(args.episode)
    fps = float(episode.domain["frame_rates"]["delivery_fps"])
    recipe, recipe_sha = review_recipe.load_recipe(Path(args.recipe) if args.recipe else None)
    boundaries_path, video, timing_path = Path(args.boundaries), Path(args.video), Path(args.timing) if args.timing else None
    document = read_json(boundaries_path)
    rows, kind, recipe = transitions_load.load_rows(document, recipe)
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
    except Refused as error:
        raise Uncertain(str(error)) from error
    info = review_media.probe(video, review_media.find_ffprobe(ffmpeg))
    if abs(float(info.fps) - fps) > 0.01:
        raise Refused(f"{video.name} is {float(info.fps):g} fps but the episode delivers {fps:g} fps")
    timing = read_json(timing_path) if timing_path else None
    config_doc = document if kind == "review-config" else None
    declared = _frames(args.layout_same_framing) | frozenset(
        (((document.get("qa") or {}).get("review") or {}).get("layout_change_boundaries") or []) if config_doc else [])
    out_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="jjv-qa-transitions-"))
    gate = transitions_run.run_transitions(
        rows=rows, recipe=recipe, video=video, ffmpeg=ffmpeg, native=(info.width, info.height), origin=args.frame_origin,
        spoken=transitions_load.spoken_index(timing, config_doc, fps), declared=declared, out_dir=out_dir)
    code = {"PASS": 0, "FAIL": 1}.get(gate["status"], 2)
    receipt = stamp({
        "schema": SCHEMA, "verdict": gate["status"], "ok": code == 0, "exit_code": code, "fps": fps, "frame_origin": args.frame_origin,
        "video": {"name": video.name, "sha256": sha256_file(video), "width": info.width, "height": info.height, "frames": info.frames},
        "boundaries": {"name": boundaries_path.name, "sha256": sha256_file(boundaries_path), "kind": kind},
        "timing": {"name": timing_path.name, "sha256": sha256_file(timing_path)} if timing_path else None,
        "recipe": {"id": recipe.get("id"), "sha256": recipe_sha}, **gate})
    write_json_atomic(out_dir / RECEIPT_FILE, receipt, mode="ascii")
    if not args.json:
        print(_summary(receipt), file=sys.stderr)
        print(f"  receipt + sheets: {out_dir}", file=sys.stderr)
    print(json.dumps(receipt, indent=2, ensure_ascii=True))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-transitions", description=__doc__)
    add_arguments(parser)
    try:
        return run_qa_transitions(parser.parse_args(argv))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except Exception as error:  # noqa: BLE001 - the CLI contract is "JSON + exit 2", not a traceback
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
