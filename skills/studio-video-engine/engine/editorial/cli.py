"""CLI glue for ``jjv editorial build-config``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..qa.scope import resolve_episode_or_uncertain
from . import boundaries_suggest_cli, build, presets_cli


def register_cli(stages: Any) -> None:
    """Register the ``editorial`` stage and its ``build-config`` verb on the main parser."""
    editorial = stages.add_parser("editorial", help="editorial stage")
    verbs = editorial.add_subparsers(dest="verb", required=True)
    parser = verbs.add_parser(
        "build-config", help="boundaries.json + word timing -> review-config.json + events.json (write-once)")
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--boundaries", required=True, help="boundaries.json (schemas/boundaries.schema.json)")
    parser.add_argument("--word-timing", required=True, help="word timing document")
    parser.add_argument("--out", required=True, help="output folder for review-config.json and events.json")
    parser.add_argument("--dry-run", action="store_true", help="validate everything and print hashes; write nothing")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH",
                        help="a file or folder outside the episode root that inputs may reference "
                             "(the shared studio logo); repeatable")
    presets_cli.register(verbs)
    boundaries_suggest_cli.register(verbs)


def run_build_config(args: argparse.Namespace) -> int:
    """One JSON summary on stdout; exit 0 built, 1 a rule failed (nothing written), 2 unreadable input."""
    config = resolve_episode_or_uncertain(args.episode)
    built = build.build_review_config(config, Path(args.boundaries), Path(args.word_timing),
                                      allow_outside=tuple(Path(item) for item in args.allow_outside))
    written = build.write_outputs(built, Path(args.out), dry_run=args.dry_run)
    motion = built.config["motion"]
    print(json.dumps({
        "ok": True, "dry_run": args.dry_run, "episode_id": built.config["episode_id"],
        "boundaries": len(motion["transitions"]), "icon_events": len(motion["icons"]),
        "dialogue_entries": len(built.config["dialogue"]), "wav_bindings": len(built.config["wav_bindings"]),
        "total_frames": built.config["total_frames"], "warnings": built.warnings, "outputs": written,
    }, indent=2, ensure_ascii=True))
    return 0
