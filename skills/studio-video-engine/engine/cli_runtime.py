"""CLI handlers for the runtime verbs: ``seedvr2 execute|finalize`` and ``comfy check|submit|wait|reconcile``.

``bin/jjv.py`` only parses arguments; everything that resolves config and builds clients lives
here.  Every handler prints one JSON summary on stdout (progress goes to stderr) and returns
the engine exit code (0 ok, 1 refused/nothing sent, 2 error/uncertain, 3 timeout, 4 failed).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .comfy import commands
from .comfy.client import ComfyClient
from .comfy.guards import ClassPolicy
from .comfy.settings import ComfySettings, settings_from_machine
from .comfy.telemetry import TelemetrySampler
from .config.loader import REPO_ROOT, ResolvedConfig, require_recipe, resolve_episode
from .core.errors import Refused
from .core.paths import require_inside
from .seedvr2.execplan import load_exec_plan, select_tasks
from .seedvr2.execute import Executor


def _print(summary: dict[str, Any]) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def _settings(config: ResolvedConfig, args: argparse.Namespace) -> ComfySettings:
    return settings_from_machine(config.machine).with_overrides(
        lock_timeout_seconds=getattr(args, "lock_timeout_seconds", None),
        poll_seconds=getattr(args, "poll_seconds", None),
        history_timeout_seconds=getattr(args, "history_timeout_seconds", None))


def _executor(args: argparse.Namespace) -> tuple[Executor, list]:
    config = resolve_episode(args.episode)
    recipe = require_recipe(config, "seedvr2")  # a domain without a qualified recipe refuses here
    settings = _settings(config, args)
    segments = Path(args.segments_root) if getattr(args, "segments_root", None) else None
    plan = load_exec_plan(Path(args.plan), config, recipe, segments_root=segments)
    if args.execute:
        if not str(config.machine.get("gpu_lock_path") or "").strip():
            raise Refused("--execute requires machine.gpu_lock_path")
        require_inside(plan.root, Path(config.episode_root), "plan folder (run receipts live beside the plan)")
    sampler = None if args.no_telemetry or not args.execute else (
        lambda path: TelemetrySampler(container=settings.container, samples_path=path))
    executor = Executor(config=config, recipe=recipe, plan=plan, settings=settings, repo_root=REPO_ROOT,
                        sampler_factory=sampler)
    return executor, select_tasks(plan.tasks, only=args.only, max_chunks=args.max_chunks)


def require_final_for_execute(executor: Any, tasks: list, args: argparse.Namespace) -> None:
    """Final gate for a real SeedVR2 run: where the domain declares ``final_gate``, every plan shot's source take
    needs a user-approval receipt bound to its sha256 (``--approvals DIR``).  Other domains: no-op."""
    from .policy import final_gate
    domain = getattr(executor.config, "domain", None)
    if not final_gate.enabled(domain):
        return
    shots = {}
    for task in tasks:
        shots[task.shot["shot_id"]] = [task.shot.get("source_sha256")]
    final_gate.check_shots(domain, sorted(shots.items()), getattr(args, "approvals", None) or [], verb="seedvr2 execute")


def run_seedvr2_execute(args: argparse.Namespace) -> int:
    executor, tasks = _executor(args)
    if args.execute:
        require_final_for_execute(executor, tasks, args)
    if not args.execute:
        rows = executor.dry_run(tasks)
        _print({"ok": True, "dry_run": True, "message": "POST skipped (dry-run)",
                "planned_chunks": len(rows), "chunks": rows, "plan_sha256": executor.plan.sha256})
        return 0
    result = executor.run(tasks, resume=args.resume, break_stale_lock=args.break_stale_lock)
    _print({"ok": result["exit_code"] == 0, "dry_run": False, "plan_sha256": executor.plan.sha256, **result})
    return result["exit_code"]




def run_watchdog_clear(args: argparse.Namespace) -> int:
    """``comfy watchdog clear``: operator-only latch archive (needs --confirm == --run-id)."""
    from .comfy import run_watchdog
    try:
        archive = run_watchdog.cli_clear_latch(
            runs_root=Path(args.runs_root), run_id=args.run_id, confirm=args.confirm, reason=args.reason,
            runner_stopped=args.runner_stopped, watchdog_stopped=args.watchdog_stopped,
            ownership_reconciled=args.ownership_reconciled, operator=args.operator)
    except (run_watchdog.ClearRefused, run_watchdog.LatchReadError, OSError) as error:
        _print({"ok": False, "refused": True, "error": str(error)})
        return 1
    _print({"ok": True, "archived_to": str(archive), "receipt": str(archive) + ".operator.json"})
    return 0


def run_comfy(args: argparse.Namespace) -> int:
    if args.verb == "watchdog":
        return run_watchdog_clear(args)
    config = resolve_episode(args.episode)
    settings = _settings(config, args)
    client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
    if args.verb == "check":
        report, ok = commands.cmd_check(client, settings, min_vram_free_mib=args.min_vram_free_mib)
        _print(report)
        return 0 if ok else 1
    if args.verb == "submit":
        policy = ClassPolicy.from_domain(config.domain)
        _print({"ok": True, **commands.cmd_submit(
            client, settings, policy, graph_path=Path(args.graph), receipt_dir=Path(args.receipt_dir),
            expect_sha=args.expect_sha)})
        return 0
    if args.verb == "wait":
        _print({"ok": True, **commands.cmd_wait(client, settings, receipt_dir=Path(args.receipt_dir),
                                                  timeout_seconds=args.timeout)})
        return 0
    report, code = commands.cmd_reconcile(client, settings, receipt_dir=Path(args.receipt_dir))
    _print({"ok": code == 0, **report})
    return code


def _register_watchdog(verbs: Any) -> None:
    wd = verbs.add_parser("watchdog", help="terminal-latch operator verbs")
    wd_verbs = wd.add_subparsers(dest="watchdog_verb", required=True)
    clear = wd_verbs.add_parser("clear", help="archive a run's terminal latch (operator only; nothing deleted)")
    clear.add_argument("--run-id", required=True)
    clear.add_argument("--confirm", required=True, help="must equal --run-id")
    clear.add_argument("--reason", required=True)
    clear.add_argument("--runs-root", required=True, help="pilot runs root (engine stays domain-neutral: no built-in path)")
    clear.add_argument("--operator", default=None, help="default: the OS user")
    for flag in ("runner-stopped", "watchdog-stopped", "ownership-reconciled"):
        clear.add_argument("--" + flag, action="store_true", help="operator attests this is true (required)")


def add_runtime_parsers(stages: Any, seedvr2_verbs: Any) -> None:
    """Register ``seedvr2 execute`` and the ``comfy`` stage on the main parser."""
    ex = seedvr2_verbs.add_parser("execute", help="serial chunk execution; DRY RUN unless --execute")
    ex.add_argument("--episode", required=True)
    ex.add_argument("--plan", required=True, help="plan v2 path (graphs relative to its folder)")
    ex.add_argument("--segments-root", default=None, help="folder holding <shot>/chunks/<chunk>/source-segment.mp4 "
                                                          "(default: the plan folder)")
    ex.add_argument("--execute", action="store_true", help="enable ComfyUI POST (default is a dry run)")
    ex.add_argument("--only", default=None, help="comma-separated SHOT or SHOT:INDEX")
    ex.add_argument("--max-chunks", type=int, default=None)
    ex.add_argument("--resume", action="store_true", help="verify COMPLETED, reconcile intents; never resubmit")
    ex.add_argument("--break-stale-lock", action="store_true",
                    help="take over a STALE run lock (its PID is dead); a live holder is never broken")
    ex.add_argument("--no-telemetry", action="store_true")
    ex.add_argument("--approvals", action="append", default=[], metavar="DIR",
                    help="folder(s) with <shot>/acceptance/*.json user approvals (needed only where the domain has final_gate)")
    ex.add_argument("--history-timeout-seconds", type=float, default=None)
    ex.add_argument("--poll-seconds", type=float, default=None)
    ex.add_argument("--lock-timeout-seconds", type=float, default=None)
    comfy = stages.add_parser("comfy", help="guarded ComfyUI verbs")
    verbs = comfy.add_subparsers(dest="verb", required=True)
    for name, text in (("check", "readiness (read-only)"), ("submit", "guarded POST"),
                       ("wait", "poll history, write job.json"), ("reconcile", "find an intent's prompt")):
        p = verbs.add_parser(name, help=text)
        p.add_argument("--episode", required=True, help="supplies machine + domain policy")
        p.add_argument("--poll-seconds", type=float, default=None)
        p.add_argument("--lock-timeout-seconds", type=float, default=None)
        if name == "check":
            p.add_argument("--min-vram-free-mib", type=int, default=0)
        else:
            p.add_argument("--receipt-dir", required=(name != "check"))
        if name == "submit":
            p.add_argument("--graph", required=True)
            p.add_argument("--expect-sha", default=None)
        if name == "wait":
            p.add_argument("--timeout", type=float, default=3600.0)
    _register_watchdog(verbs)
