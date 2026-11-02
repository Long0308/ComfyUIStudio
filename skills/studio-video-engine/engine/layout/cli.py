"""CLI glue for ``jjv layout plan|check|render`` (Q-2).  One JSON summary on stdout, engine exit codes.

0 ok, 1 refused / a rule failed, 2 uncertain or unreadable input.  plan/check are CPU only; render runs Blender
headless (beauty needs the GPU lock and free VRAM, depth/mask are CPU).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import DEFAULT_MACHINE_PATH
from ..core.errors import EXIT_OK, EXIT_REFUSED, Refused
from ..core.io import read_json
from . import cast as cast_mod
from . import check as check_mod
from . import plan as plan_mod
from . import render as render_mod
from .context import ROUTES_RECIPE, load_context, load_recipe


def register_cli(stages: Any) -> None:
    layout = stages.add_parser("layout", help="Blender layout briefs, continuity and control passes (Q-2)")
    verbs = layout.add_subparsers(dest="verb", required=True)
    plan = verbs.add_parser("plan", help="set.json + one draft brief per cut shot, cast refs bound by sha256")
    plan.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    plan.add_argument("--out", required=True, help="new layout folder (layout-plan.json, set.json, briefs/)")
    plan.add_argument("--cast", default=None, help="cast manifest ({characters:[{character_id, canonical_png, canonical_sha256}]})")
    plan.add_argument("--map", action="append", default=[], metavar="ROLE=CHARACTER_ID", help="speaker/listener role -> cast id")
    plan.add_argument("--allow-unbound", action="store_true", help="plan even when a role has no cast reference")
    plan.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    check = verbs.add_parser("check", help="validate every brief, continuity for every adjacent pair, placement text")
    check.add_argument("--layout", required=True, help="layout folder written by `layout plan`")
    check.add_argument("--allow-draft", action="store_true", help="accept briefs whose status is still 'draft'")
    render = verbs.add_parser("render", help="headless Blender: beauty guide + depth/mask control passes (one shot)")
    render.add_argument("--layout", default=None, help="layout folder (brief taken from its plan)")
    render.add_argument("--brief", default=None, help="a brief file instead of --layout (read-only input)")
    render.add_argument("--out", default=None, help="output folder (default: --layout)")
    render.add_argument("--shot", required=True)
    render.add_argument("--passes", default="beauty,depth,mask")
    render.add_argument("--take", default=None, help="take folder name (default: next rNNN; never overwritten)")
    render.add_argument("--width", type=int, default=None)
    render.add_argument("--height", type=int, default=None)
    render.add_argument("--blender", default=None)
    render.add_argument("--allow-draft", action="store_true")
    render.add_argument("--machine", default=None, help=argparse.SUPPRESS)


def run_layout(args: argparse.Namespace) -> int:
    return {"plan": _plan, "check": _check, "render": _render}[args.verb](args)


def _plan(args: argparse.Namespace) -> int:
    ctx = load_context(args.episode, args.machine)
    declared_cast = (ctx.episode.get("files") or {}).get("cast")
    cast = Path(args.cast) if args.cast else (
        ctx.episode_file.parent / declared_cast if isinstance(declared_cast, str) and declared_cast else None
    )
    mapping = {**(ctx.episode.get("cast_roles") or {}), **cast_mod.parse_pairs(args.map, "--map")}
    summary = plan_mod.build_plan(ctx, Path(args.out), cast_file=cast, mapping=mapping,
                                  allow_unbound=args.allow_unbound)
    print(json.dumps({"ok": True, "episode_id": ctx.episode_id, "domain": ctx.domain_id, **summary}, indent=2))
    return EXIT_OK


def _check(args: argparse.Namespace) -> int:
    report = check_mod.check_layout(Path(args.layout), allow_draft=args.allow_draft)
    brief = {k: {"ok": v["ok"], "problems": v["problems"]} for k, v in report["briefs"].items()}
    pairs = [{k: p.get(k) for k in ("from", "to", "classification", "same_layout", "allowed_transitions", "comparable")}
             for p in report["pairs"]]
    print(json.dumps({"ok": report["ok"], "briefs": brief, "pairs": pairs,
                      "continuity_mismatches": report["continuity_mismatches"],
                      "incomparable_pairs": report["incomparable_pairs"],
                      "placement": report["placement"]}, indent=2))
    return EXIT_OK if report["ok"] else EXIT_REFUSED


def _render(args: argparse.Namespace) -> int:
    if bool(args.layout) == bool(args.brief):
        raise Refused("give exactly one of --layout and --brief")
    layout = Path(args.layout) if args.layout else None
    out = Path(args.out or args.layout or "")
    if not str(out):
        raise Refused("--out is required with --brief")
    brief = Path(args.brief) if args.brief else check_mod.brief_path(layout, check_mod.load_plan(layout), args.shot)
    machine = _machine(args.machine)
    blender = render_mod.find_blender(args.blender, machine)
    recipe, _ = load_recipe(ROUTES_RECIPE, "jjv/images-routes/v1")
    receipt = render_mod.render_shot(brief, args.shot, out, render_mod.parse_passes(args.passes), blender=blender,
                                     machine=machine, take=args.take, width=args.width, height=args.height,
                                     allow_draft=args.allow_draft, recipe=recipe)
    print(json.dumps({"ok": True, "shot": args.shot, "take": receipt["take"], "receipt": receipt["receipt"],
                      "gpu": receipt["gpu"], "elapsed_seconds": receipt["elapsed_seconds"],
                      "files": [{"name": f["name"], "bytes": f["bytes"]} for f in receipt["files"]]}, indent=2))
    return EXIT_OK


def _machine(path: str | None) -> dict[str, Any]:
    return read_json(Path(path) if path else DEFAULT_MACHINE_PATH)
