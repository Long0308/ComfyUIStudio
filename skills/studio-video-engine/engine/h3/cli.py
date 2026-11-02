"""CLI glue for ``jjv h3 inputs|prepare|submit|adopt|accept|publish-shots`` (Q-3; ``inputs`` and
``publish-shots`` M8b).  One JSON summary on stdout.

Exit codes follow the engine: 0 ok, 1 refused (nothing was sent), 2 uncertain, 3 timeout, 4 failed.
Only ``submit`` can POST, and only with ``--approve-gpu``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy.client import ComfyClient
from ..comfy.settings import settings_from_machine
from ..core.errors import EXIT_OK, Refused
from ..layout.context import load_context
from . import accept as accept_mod
from . import adopt as adopt_mod
from . import inputs as inputs_mod
from . import prepare as prepare_mod
from . import publish as publish_mod
from . import submit as submit_mod


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="H3 folder: <out>/<shot>/{graph.api.json,preparation.json,...}")
    parser.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--shot", action="append", default=None, help="shot id (repeatable; default: every shot)")


def register_cli(stages: Any) -> None:
    h3 = stages.add_parser("h3", help="H3 motion: inputs, prepare (offline), submit (GPU, --approve-gpu), adopt, "
                                       "accept, publish-shots")
    verbs = h3.add_subparsers(dest="verb", required=True)
    inp = verbs.add_parser("inputs", help="build the jjv/h3-inputs/v1 manifest from image/voice/cast receipts")
    inp.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    inp.add_argument("--out", required=True, help="manifest file to write (write-once)")
    inp.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    inp.add_argument("--spec", required=True, help="jjv/h3-spec/v1: template, ports, face roles, mouth (no shas)")
    inp.add_argument("--images", required=True, help="`jjv images` folder (approvals + native receipts)")
    inp.add_argument("--voice", required=True, help="`jjv voice` folder (finalize + bindings + listen approvals)")
    inp.add_argument("--cast", default=None, help="cast file (default: episode.files.cast)")
    inp.add_argument("--shots", default=None, help="shot list (default: episode.files.shots)")
    inp.add_argument("--map", action="append", default=None, help="ROLE=CHARACTER_ID (repeatable)")
    inp.add_argument("--carry-from", default=None,
                     help="H3 folder whose ACCEPTED takes supply carry-shot anchors (their 'carry' sink output)")
    inp.add_argument("--anchor-dir", default=None,
                     help="anchor-pack folder (<dir>/<shot>/anchor-pack.json): a shot with a pack binds EVERY image from it")
    inp.add_argument("--shotlist", default=None, help="CURRENT shotlist (context per shot) the packs are checked against")
    inp.add_argument("--allow-pending-storyboard", action="store_true",
                     help="PILOT only: bind the pack's first body/face ref as the AddGuide image while the storyboard is pending")
    inp.add_argument("--legacy-cast-faces", action="store_true",
                     help="LEGACY only: a shot with NO anchor pack takes its faces from the cast file; each face must carry a "
                          "current library approval (else refused); the manifest provenance records the legacy use")
    prep = verbs.add_parser("prepare", help="bind hashed anchor/WAV/faces into the template graph; sends nothing")
    _common(prep)
    prep.add_argument("--inputs", required=True, help="jjv/h3-inputs/v1 manifest (shots, ports, hashes)")
    sub = verbs.add_parser("submit", help="guarded, idempotent POST of prepared graphs; refuses without --approve-gpu")
    _common(sub)
    sub.add_argument("--approve-gpu", action="store_true", help="explicit user approval to spend GPU time on this run")
    sub.add_argument("--no-wait", action="store_true", help="POST only; adopt waits later")
    sub.add_argument("--timeout", type=float, default=3600.0, help="per-shot wait seconds")
    ad = verbs.add_parser("adopt", help="pull outputs + receipts, publish the GUI workflow with the result pinned")
    _common(ad)
    ad.add_argument("--timeout", type=float, default=3600.0)
    acc = verbs.add_parser("accept", help="shot acceptance: pick/reject an adopted take with a reason (or --list)")
    _common(acc)
    acc.add_argument("--list", action="store_true", help="show every adopted shot's review state")
    group = acc.add_mutually_exclusive_group()
    group.add_argument("--pick", action="store_true")
    group.add_argument("--reject", action="store_true")
    acc.add_argument("--by", default=None, help="the person who watched the take (not a machine name)")
    acc.add_argument("--reason", default=None)
    acc.add_argument("--sha256", default=None, help="what you say you watched (must equal the adopted take)")
    pub = verbs.add_parser("publish-shots", help="write shots-h3-vNNN.json (jjv/shots/v1) from ACCEPTED takes only")
    pub.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    pub.add_argument("--out", required=True, help="H3 folder holding every listed shot's accepted take")
    pub.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    pub.add_argument("--shots", default=None, help="shot list (default: episode.files.shots); every shot is required")
    pub.add_argument("--dest-dir", default=None, help="folder for shots-h3-vNNN.json (default: next to episode.json)")
    pub.add_argument("--ffprobe", default=None, help="ffprobe binary (default: $FFPROBE or PATH)")


def run_h3(args: argparse.Namespace) -> int:
    ctx = load_context(args.episode, args.machine)
    out = Path(args.out)
    if args.verb == "inputs":
        from ..layout.cast import parse_pairs
        result = inputs_mod.write_inputs(ctx, Path(args.spec), out, images=Path(args.images), voice=Path(args.voice),
                                         cast_file=Path(args.cast) if args.cast else None,
                                         shots_file=Path(args.shots) if args.shots else None,
                                         mapping=parse_pairs(args.map, "--map"),
                                         carry_from=Path(args.carry_from) if args.carry_from else None,
                                         anchor_dir=Path(args.anchor_dir) if args.anchor_dir else None,
                                         shotlist=Path(args.shotlist) if args.shotlist else None,
                                         allow_pending_storyboard=bool(args.allow_pending_storyboard),
                                         legacy_cast_faces=bool(args.legacy_cast_faces))
    elif args.verb == "publish-shots":
        result = publish_mod.publish_shots(ctx, out, dest_dir=Path(args.dest_dir) if args.dest_dir else None,
                                           shots_file=Path(args.shots) if args.shots else None, ffprobe=args.ffprobe)
    elif args.verb == "prepare":
        result = prepare_mod.prepare(ctx, Path(args.inputs), out, shots=args.shot)
    elif args.verb == "submit":
        settings = settings_from_machine(ctx.machine)
        client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
        result = submit_mod.submit(ctx, out, args.shot, settings, client, approve_gpu=args.approve_gpu,
                                   wait=not args.no_wait, wait_timeout=args.timeout)
    elif args.verb == "adopt":
        settings = settings_from_machine(ctx.machine)
        client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
        result = adopt_mod.adopt(ctx, out, args.shot, settings, client, wait_timeout=args.timeout)
    elif args.list:
        result = {"shots": accept_mod.status(out, ctx=ctx), "accepted": accept_mod.accepted_takes(out, args.shot, ctx=ctx)}
    else:
        if not (args.pick or args.reject) or not args.shot or len(args.shot) != 1 or not args.by or args.reason is None:
            raise Refused("accept needs exactly one --shot, --pick or --reject, --by and --reason (or --list)")
        result = accept_mod.decide(out, args.shot[0], "pick" if args.pick else "reject", ctx=ctx, by=args.by,
                                   reason=args.reason, sha256=args.sha256)
    print(json.dumps({"ok": True, "episode_id": ctx.episode_id, "domain": ctx.domain_id, **result}, indent=2))
    return EXIT_OK
