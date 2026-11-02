"""Đăng ký và điều phối ``jjv images library plan|run|lane|status`` (N89-P0). Chỉ THÊM verb: các verb ``images`` cũ không đổi.

``register(verbs)`` trả về subparsers của ``library`` để các verb thư viện khác (view/review, P1) móc vào cùng một chỗ.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..core.errors import EXIT_OK
from . import library_plan, library_register, library_review, library_run, library_view


def _context_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", default=None, help="episode.json path, episode root or slug (the lanes pass it to `images submit`)")
    parser.add_argument("--machine", default=None, help="machine.json (default: production-local/engine/machine.json); read only, never written")
    parser.add_argument("--library-out", default=None, metavar="DIR", help="where takes land: DIR/<batch_id>/tNNN (`submit --library-out`)")
    parser.add_argument("--pool-out", default=None, metavar="DIR",
                        help="the `submit --out` folder (pool state lives there unless machine.images.codex_state_path is set)")
    parser.add_argument("--pool-state", default=None,
                        help="codex pool state file (default: machine.images.codex_state_path, else <pool-out>/codex-pool-state.json)")
    parser.add_argument("--codex-bin", default=None, help="Codex CLI path passed to every lane (default: machine/env/PATH)")
    parser.add_argument("--timeout", type=float, default=None, help="codex exec timeout in seconds per image")


def register(verbs: Any) -> Any:
    library = verbs.add_parser("library", help="character-library automation (N89): plan lanes, run them (one process per lane, "
                                               "resume-safe), status")
    sub = library.add_subparsers(dest="library_verb", required=True)
    plan = sub.add_parser("plan", help="queue -> lanes <acct>, <acct>b, <acct>c... (batches dealt round-robin); refuses cooling accounts")
    plan.add_argument("--queue", required=True, help="queue-<rev>.json (only dispatch_allowed true rows; batch files sit next to it)")
    plan.add_argument("--accounts", required=True, help="comma-separated machine.json codex account labels, e.g. acct3,acct4")
    plan.add_argument("--procs-per-account", type=int, default=1,
                      help=f"lanes per account (1..{library_plan.MAX_PROCS}); a lane variant shares its account's codex_home")
    plan.add_argument("--kinds", default=None, help="comma-separated kinds to keep, e.g. FACE,ACTION (default: every kind)")
    plan.add_argument("--rev", default=None, help="revision label (default: <rev> of queue-<rev>.json)")
    plan.add_argument("--out", required=True, help="PLAN.json (jjv/images-library-plan/v1, write-once)")
    _context_flags(plan)
    run = sub.add_parser("run", help="spawn one `library lane` process per lane (resume-safe: existing valid takes are skipped); "
                                     "writes <plan>.status.json")
    run.add_argument("--plan", required=True)
    run.add_argument("--dry-run", action="store_true", help="list lanes, batches, remaining items and the submit argv; spawn and write nothing")
    run.add_argument("--detach", action="store_true", help="return right after spawning (lanes keep running; follow with `library status`)")
    _context_flags(run)
    run.add_argument("--view-out", default=None, metavar="DIR", help="auto-refresh `library view` into DIR after every batch and at the end")
    run.add_argument("--view-libraries", action="append", default=None, metavar="DIR[,DIR...]", help="libraries oldest -> newest for the refresh")
    run.add_argument("--view-queues", action="append", default=None, metavar="Q[,Q...]", help="queue files for `library view`")
    run.add_argument("--review-out", default=None, metavar="FILE", help="auto-refresh the `library review` HTML (uses --view-libraries)")
    lane = sub.add_parser("lane", help="(internal, spawned by `run`) run ONE lane of a run folder in this process, batch after batch")
    lane.add_argument("--plan", required=True)
    lane.add_argument("--run-dir", required=True)
    lane.add_argument("--lane", required=True)
    status = sub.add_parser("status", help="no network: lane states, per character/kind counts, ETA from measured seconds per image")
    status.add_argument("--plan", required=True)
    status.add_argument("--run-dir", default=None, help="a run folder (default: the newest under <plan>.runs/)")
    status.add_argument("--json", action="store_true", help="JSON only (no table on stderr)")
    library_view.register(sub)
    library_review.register(sub)
    reg = sub.add_parser("register", help="register ONE user-approved external image as a library take (compare + approve + view rebuild)")
    library_register.add_arguments(reg)
    reg.set_defaults(library_func=library_register.run_register)
    return sub


def _split(value: str | None) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def _table(status: dict[str, Any]) -> None:
    lines = [f"{'lane':<10} {'account':<8} {'state':<8} {'images':>6}  reason"]
    for lane in status["lanes"]:
        lines.append(f"{lane['label']:<10} {lane['account']:<8} {lane['state']:<8} {lane['images']:>6}  {lane['reason'] or ''}")
    for char, kinds in sorted(status["characters"].items()):
        lines.append(f"{char}: " + ", ".join(f"{k} {v['done']}/{v['wanted']}" for k, v in sorted(kinds.items())))
    totals, eta = status["totals"], status["eta_seconds"]
    lines.append(f"total {totals['done']}/{totals['wanted']} (remaining {totals['remaining']}), lanes active {status['lanes_active']}, "
                 f"eta {f'{eta / 60:.1f} min' if eta else 'n/a'}")
    print("\n".join(lines), file=sys.stderr)


def run_library(args: argparse.Namespace) -> int:
    verb = args.library_verb
    if getattr(args, "library_func", None) is not None:  # view/review: own output; Refused propagates to jjv main (exit 1)
        return int(args.library_func(args))
    if verb == "plan":
        result = library_plan.build_plan(queue=Path(args.queue), accounts=_split(args.accounts) or [], procs=args.procs_per_account,
                                         out=Path(args.out), machine_path=args.machine, episode=args.episode,
                                         library_out=args.library_out, pool_out=args.pool_out, pool_state=args.pool_state,
                                         kinds=_split(args.kinds), rev=args.rev, codex_bin=args.codex_bin, timeout=args.timeout)
    elif verb == "run":
        plan_path = Path(args.plan)
        plan = library_plan.load_plan(plan_path)
        ctx = library_run.resolve_context(plan, episode=args.episode, machine=args.machine, library_out=args.library_out,
                                          pool_out=args.pool_out, pool_state=args.pool_state, codex_bin=args.codex_bin,
                                          timeout=args.timeout)
        view = library_run.view_config(args.view_out, args.view_libraries, args.view_queues, args.review_out)
        result = (library_run.dry_run(plan_path, plan, ctx) if args.dry_run
                  else library_run.start_run(plan_path, plan, ctx, detach=args.detach, view=view))
    elif verb == "lane":
        result = library_run.run_lane(Path(args.plan), Path(args.run_dir), args.lane)
    else:
        result = library_run.status(Path(args.plan), args.run_dir)
        if not args.json:
            _table(result)
    print(json.dumps({"ok": True, "verb": f"library {verb}", **result}, indent=2))
    return EXIT_OK
