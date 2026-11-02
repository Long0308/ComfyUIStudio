"""CLI glue for ``jjv qa av`` (parsing lives in ``bin/jjv.py``; this module owns the handler)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..config import rules
from ..core.errors import Refused, Uncertain
from ..core.provenance import stamp
from ..core.io import read_json, sha256_file, write_json_once
from ..seedvr2.seam_media import find_ffmpeg
from . import av
from .scope import resolve_episode_or_uncertain
from .review_cli import register_review
from .preflight_cli import register_preflight
from .gate_cli import register_gate
from .transitions_cli import register_transitions
from .expression import register_cli as register_expression


def register_cli(stages: Any) -> None:
    """Register the ``qa`` stage and its ``av`` verb on the main parser."""
    qa = stages.add_parser("qa", help="QA stages")
    verbs = qa.add_subparsers(dest="verb", required=True)
    from ..timing.cli import register_qa_words  # T-E33: qa words (Q1)
    register_qa_words(verbs)
    parser = verbs.add_parser(
        "av", help="cross-correlate every bound WAV in an export at its configured start (lag ms) "
                   "and optionally compare PCM with a reference export")
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--video", required=True, help="review export .mp4")
    parser.add_argument("--config", required=True, help="review config (engine config or hand-built)")
    parser.add_argument("--reference", default=None, help="reference export for the PCM identity check")
    parser.add_argument("--reference-seconds", type=float, default=None,
                        help="first N seconds compared with the reference (default config.qa.av.reference_seconds)")
    parser.add_argument("--out", default=None, help="write the receipt here (write-once)")
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH",
                        help="a file or folder outside the episode root that may be read (repeatable)")
    parser.add_argument("--json", action="store_true", help="JSON only: no progress table on stderr")
    register_review(verbs)  # T-E36: qa review (Q2-Q5)
    register_preflight(verbs)  # qa preflight: every check that needs no rendered pixels
    register_gate(verbs)       # qa gate: preflight + (after the render) qa review + qa words
    register_transitions(verbs)  # T-E34: qa transitions (full-resolution mid-transition checks)
    register_expression(verbs)  # BP-47: per-take facial-expression checks


def _ffmpeg(explicit: str | None) -> str:
    try:
        return find_ffmpeg(explicit)
    except Refused as error:  # a missing tool is an unavailable input, not a rule violation
        raise Uncertain(str(error)) from error


def _table(receipt: dict) -> str:
    lines = [f"{receipt['verdict']}{' (partial reference window)' if receipt.get('partial') else ''}  tolerance "
             f"{receipt['params']['tolerance_ms']} ms"]
    if receipt.get("binding_source"):
        lines.append(f"  bindings: {receipt['binding_count']} from {receipt['binding_source']}")
    for row in receipt["wav_starts"]:
        lag = "n/a" if row["lag_ms"] is None else f"{row['lag_ms']:+8.2f} ms"
        lines.append(f"  {row['name']:<22} f{row['start_frame']:<5} lag {lag} ncc {row['ncc']} {row['status']} "
                     f"sha {'ok' if row['sha_ok'] else 'MISMATCH'} {'ok' if row['ok'] else 'FAIL'}")
    if receipt["pcm_identity"]:
        pcm = receipt["pcm_identity"]
        lines.append(f"  pcm identity {pcm['seconds']} s: max|diff| {pcm['max_abs']} "
                     f"(allowed {pcm['max_abs_allowed']}) {'ok' if pcm['ok'] else 'FAIL'}")
    return "\n".join(lines)


def run_qa_av(args: argparse.Namespace) -> int:
    """One JSON receipt on stdout; exit 0 PASS, 1 FAIL/PASS_PARTIAL/refused, 2 unreadable input."""
    config = resolve_episode_or_uncertain(args.episode)
    config_path = Path(args.config)
    document = read_json(config_path)
    if not isinstance(document, dict):
        raise Refused(f"{config_path}: review config must be a JSON object")
    main_frames = rules.timeline_frames(config.episode, config.domain)["main_frames"]
    receipt = av.run_av(
        video=Path(args.video), config=document, config_sha256=sha256_file(config_path),
        episode_root=Path(config.episode_root), fps=float(config.domain["frame_rates"]["delivery_fps"]),
        reference=Path(args.reference) if args.reference else None,
        reference_seconds=args.reference_seconds, allow_outside=tuple(Path(i) for i in args.allow_outside),
        ffmpeg=_ffmpeg(args.ffmpeg), main_frames=main_frames)
    receipt = stamp(receipt)  # the printed receipt and the file carry the same engine_tree_sha256 header
    if args.out:
        write_json_once(Path(args.out), receipt, mode="ascii")
    if not args.json:
        print(_table(receipt), file=sys.stderr)
    print(json.dumps(receipt, indent=2, ensure_ascii=True))
    return 0 if receipt["ok"] else 1
