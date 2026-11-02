"""CLI handlers for ``jjv seedvr2 segments`` and ``jjv seedvr2 tails plan|check|assemble`` (+ the plan coverage flags).

``bin/jjv.py`` only has to call ``register_cli(seedvr2_verbs)``, route ``verb in ("segments", "tails")`` to ``run``
and, for ``plan``, ``add_plan_coverage_args`` / ``coverage_inputs`` (see CLI-PATCH-segments.md).  Every handler prints
one JSON summary on stdout and returns the exit code: 0 ok, 1 refused (nothing was sent: a plan is never a POST),
2 uncertain, 4 failed (via ``EngineError`` in ``main``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import REPO_ROOT, require_recipe, resolve_episode
from ..core.errors import Refused
from .coverage import Read, load_reads, load_tail_map
from .execplan import load_exec_plan
from .plan import require_fresh_out
from .segments import run_segments
from .tails import plan_tails
from .tails_assemble import assemble_tail_masters, check_tails_run


def _print(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def add_plan_coverage_args(plan_parser: argparse.ArgumentParser) -> None:
    """``plan --reads F [--tail-map F ...]``: refuse before binding when the timeline reads uncovered frames."""
    plan_parser.add_argument("--reads", default=None,
                             help="review config (dialogue + outgoing tails) or jjv/timeline-reads/v1 document: "
                                  "plan refuses when a frame it reads is outside the restored scope")
    plan_parser.add_argument("--tail-map", action="append", default=[],
                             help="assembled MASTER-TAIL-MAP.json whose tail clips count as restored (repeatable)")


def coverage_inputs(args: argparse.Namespace) -> tuple[list[Read] | None, list[tuple[str, int, int]]]:
    """``(reads or None, extra scope)`` from ``--reads`` / ``--tail-map``."""
    tail_maps = list(getattr(args, "tail_map", None) or [])
    if not getattr(args, "reads", None):
        if tail_maps:
            raise Refused("--tail-map needs --reads (the frames to be covered)")
        return None, []
    reads, _ = load_reads(Path(args.reads))
    extra = [r for path in tail_maps for r in load_tail_map(Path(path))]
    return reads, extra


def register_cli(seedvr2_verbs: Any) -> None:
    seg = seedvr2_verbs.add_parser("segments", help="cut the source segments a plan needs (frame-exact, hashed)")
    seg.add_argument("--episode", required=True)
    seg.add_argument("--out", required=True, help="segments root (<shot>/chunks/<chunk>/source-segment.mp4)")
    seg.add_argument("--plan", default=None, help="plan v2 / tails plan to cut for (default: plan built from config)")
    seg.add_argument("--only", default=None, help="comma-separated SHOT or SHOT:INDEX")
    seg.add_argument("--dry-run", action="store_true", help="verify sources and list the cuts; write nothing")
    seg.add_argument("--no-verify-md5", action="store_true", help="skip the frame-md5 proof of each cut")
    seg.add_argument("--threads", type=int, default=None, help="ffmpeg -threads")
    tails = seedvr2_verbs.add_parser("tails", help="restore the frames the timeline reads outside the main plan")
    verbs = tails.add_subparsers(dest="tails_verb", required=True)
    plan = verbs.add_parser("plan", help="gaps -> tails plan: cut sub-range sources, bind, write the plan")
    plan.add_argument("--episode", required=True)
    plan.add_argument("--reads", required=True, help="review config or jjv/timeline-reads/v1 document")
    plan.add_argument("--tail-map", action="append", default=[], help="tail map already assembled (repeatable)")
    plan.add_argument("--out", required=True, help="fresh folder INSIDE the episode tree (execute needs that)")
    plan.add_argument("--scratch", action="store_true", help="allow --out outside the episode tree (not executable)")
    plan.add_argument("--dry-run", action="store_true", help="show the gaps and ranges; cut and write nothing")
    plan.add_argument("--no-verify-md5", action="store_true")
    plan.add_argument("--threads", type=int, default=None)
    for name, text in (("check", "acceptance A of a finished tails run (CPU)"),
                       ("assemble", "cut the tail masters + MASTER-TAIL-MAP.json (needs check green)")):
        p = verbs.add_parser(name, help=text)
        p.add_argument("--episode", required=True)
        p.add_argument("--plan", required=True, help="the tails plan written by 'tails plan'")
        if name == "assemble":
            p.add_argument("--out", required=True, help="folder for master-tails/ and MASTER-TAIL-MAP.json")


def _check_out(out: Path, config: Any, *, inside_episode: bool) -> None:
    resolved, episode = out.resolve(), Path(config.episode_root).resolve()
    comfy = Path(config.machine["comfy"]["root"]).resolve()
    if resolved == comfy or comfy in resolved.parents:
        raise Refused(f"--out {resolved} is inside the ComfyUI tree")
    if resolved == episode or resolved in episode.parents:
        raise Refused(f"--out {resolved} is the episode folder or above it")
    if inside_episode and episode not in resolved.parents:
        raise Refused(f"--out {resolved} is outside the episode tree {episode}: 'execute --execute' keeps its run "
                      "receipts beside the plan and refuses a plan folder outside it (use --scratch for a dry copy)")
    if inside_episode and (episode / "engine") in [resolved, *resolved.parents]:
        raise Refused(f"--out {resolved} is inside the episode config folder")


def run(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    if args.verb == "segments":
        out = Path(args.out)
        _check_out(out, config, inside_episode=False)
        _print(run_segments(config, repo_root=REPO_ROOT, out_root=out, plan_path=Path(args.plan) if args.plan else None,
                            only=args.only, verify_md5=not args.no_verify_md5, dry_run=args.dry_run,
                            threads=args.threads))
        return 0
    if args.tails_verb == "plan":
        reads, _ = load_reads(Path(args.reads))
        extra = [r for path in args.tail_map for r in load_tail_map(Path(path))]
        out = Path(args.out)
        _check_out(out, config, inside_episode=not (args.scratch or args.dry_run))
        require_fresh_out(out)
        _print(plan_tails(config, repo_root=REPO_ROOT, reads=reads, out=out, extra_scope=extra,
                          dry_run=args.dry_run, threads=args.threads, verify_md5=not args.no_verify_md5))
        return 0
    plan = load_exec_plan(Path(args.plan), config, require_recipe(config, "seedvr2"))
    if args.tails_verb == "check":
        report = check_tails_run(plan)
        _print({"ok": report["all_pass"], **report})
        return 0 if report["all_pass"] else 1
    _print(assemble_tail_masters(plan, Path(args.out)))
    return 0
