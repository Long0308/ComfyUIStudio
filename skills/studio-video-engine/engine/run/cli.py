"""CLI glue for ``jjv run episode`` (the orchestrator) and ``jjv run approve`` (a person's gate record).

One JSON document on stdout (the run receipt or the dry-run plan), a short table on stderr.
Exit: 0 every stage in range ran or was reused; 1 refused / stopped at a gate (nothing was submitted);
2/3/4 propagate the exit of the verb that stopped the run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Any

from ..core.errors import EXIT_OK
from . import gates
from . import proof as proof_mod
from .context import load_run_context
from .dag import load_dag, require_domain
from .orchestrator import Run, Runner, default_runner


def register_cli(stages: Any) -> None:
    run = stages.add_parser("run", help="orchestrator: chain the episode stages with stop gates (M8 / Q-6)")
    verbs = run.add_subparsers(dest="verb", required=True)
    episode = verbs.add_parser("episode", help="walk the declared stage DAG; stops at every human/GPU gate; "
                                               "--dry-run prints the plan and runs nothing")
    episode.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    episode.add_argument("--from", dest="from_stage", default=None, metavar="STAGE", help="first stage to run")
    episode.add_argument("--to", dest="to_stage", default=None, metavar="STAGE", help="last stage to run")
    episode.add_argument("--dry-run", action="store_true", help="plan only: every stage, gate, step and reuse "
                                                                "decision; no verb runs; only <run_dir>/plan.json is written")
    episode.add_argument("--approve-gpu", action="store_true", help="the user's explicit approval to spend GPU "
                                                                    "time in THIS run (without it every gpu step stops)")
    episode.add_argument("--gpu-proof", default=None, help="signed GPU proof file (recipes with gpu_authorization: proof "
                                                           "need it; a bare --approve-gpu only requests execution)")
    episode.add_argument("--dag", default=None, help="run recipe (default: the recipes/run/*.json that lists the episode's domain)")
    episode.add_argument("--runs-root", default=None, help="folder of run receipts, ledger and approvals "
                                                           "(default <episode>/engine/runs)")
    episode.add_argument("--run-dir", default=None, help="this run's receipt folder (default <runs-root>/<run id>)")
    episode.add_argument("--stages-root", default=None, help="where stages write (default <episode>/engine/stages)")
    episode.add_argument("--scratch", default=None, help="scratch outside the episode tree (seedvr2 plan)")
    episode.add_argument("--json", action="store_true", help="JSON only: no table on stderr")
    approve = verbs.add_parser("approve", help="record a person's decision for a run gate (music-approval, "
                                               "user-review, publish-approval); write-once, numbered")
    approve.add_argument("--episode", required=True)
    approve.add_argument("--gate", required=True, choices=["music-approval", "user-review", "publish-approval"])
    approve.add_argument("--verdict", default="accept", choices=list(gates.VERDICTS),
                         help="accept | change (user-review: asks for another version) | override (user-review: "
                              "allows a version beyond the limit)")
    approve.add_argument("--by", default=None, help="a LABEL of the person who decided (not a machine name); recipes with "
                                                    "human_proof: required ignore it as authority")
    approve.add_argument("--approval-file", default=None, help="signed human proof file (required by recipes with "
                                                               "human_proof: required)")
    approve.add_argument("--note", required=True, help="what was reviewed and why")
    approve.add_argument("--sha256", default=None, help="sha256 of the reviewed file (required for accept/change: "
                                                        "binds the record to one version)")
    approve.add_argument("--runs-root", default=None, help="default <episode>/engine/runs")
    approve.add_argument("--dag", default=None, help="run recipe whose user-review limit applies to an override")


def review_limit(dag: Any) -> int:
    """The recipe's ``human_gates.user-review.limit`` (an override is allowed only once it is reached)."""
    for stage in dag.stages:
        spec = (stage.human_gates or {}).get("user-review")
        if isinstance(spec, dict):
            return int(spec.get("limit", gates.DEFAULT_REVIEW_LIMIT))
    return gates.DEFAULT_REVIEW_LIMIT


def _line(stage: dict[str, Any]) -> str:
    status = stage.get("status", "?")
    stop = stage.get("would_stop") or stage.get("stop")
    gates_text = ",".join(g["id"] for g in stage.get("gates") or []) or "-"
    counts: dict[str, int] = {}
    for s in stage.get("steps") or []:                      # per-shot steps collapse to one entry with a count
        key = f"{s['id']}{'(gpu)' if s.get('gpu') else ''}{'[' + s['human'] + ']' if s.get('human') else ''}"
        counts[key] = counts.get(key, 0) + 1
    steps_text = ",".join(f"{key}x{n}" if n > 1 else key for key, n in counts.items()) or "-"
    reuse = stage.get("reuse") or {}
    text = f"{stage.get('s', ''):5} {stage['id']:10} {status:14} gates={gates_text} steps={steps_text}"
    if reuse:
        text += f"\n      reuse: {reuse.get('reason')}"
    if stage.get("explain") and stage["explain"].get("status") not in (None, "not-declared"):
        text += f"\n      plan explain: {stage['explain'].get('status')}"
    if stage.get("known_gap"):
        text += f"\n      known gap: {stage['known_gap']}"
    if stop:
        text += f"\n      STOP[{stop['kind']}]: {stop['reason']}\n      next: {stop['next_step']}"
    elif stage.get("reason"):
        text += f"\n      {stage['reason']}"
    return text


def table(receipt: dict[str, Any]) -> str:
    head = (f"RUN {'DRY-RUN (nothing ran)' if receipt['dry_run'] else 'episode'} {receipt['episode_id']} "
            f"[{receipt['domain']}] dag {receipt['dag']['id']} sha {receipt['dag']['sha256'][:12]} "
            f"approve_gpu={receipt['approve_gpu']} health_gate={receipt['health_gate']}")
    lines = [head] + [_line(s) for s in receipt["stages"]]
    first = receipt.get("first_stop")
    lines.append(f"FIRST STOP: {first['stage']} [{first['kind']}] -> {first['next_step']}" if first
                 else "no stop: every stage in range ran or was reused")
    lines.append(f"receipt: {receipt['run_dir']}  exit {receipt['exit_code']}")
    return "\n".join(lines)


def run_run(args: argparse.Namespace, runner: Runner | None = None) -> int:
    if args.verb == "approve":
        ctx = load_run_context(args.episode, runs_root=args.runs_root)
        dag = load_dag(args.dag, domain_id=ctx.domain_id)
        ctx = dataclasses.replace(ctx, proof_required=dag.human_proof == "required")
        proof = proof_mod.load_file(args.approval_file) if args.approval_file else None
        path = gates.record_approval(ctx, args.gate, by=args.by, note=args.note, verdict=args.verdict, sha256=args.sha256,
                                     limit=review_limit(dag), proof=proof)
        print(json.dumps({"ok": True, "gate": args.gate, "verdict": args.verdict, "record": str(path)}, indent=2))
        return EXIT_OK
    ctx = load_run_context(args.episode, runs_root=args.runs_root, run_dir=args.run_dir, stages_root=args.stages_root,
                           scratch=args.scratch, approve_gpu=args.approve_gpu, dry_run=args.dry_run,
                           gpu_proof=args.gpu_proof)
    dag = load_dag(args.dag, domain_id=ctx.domain_id)   # --dag wins; else the recipe that lists the episode's domain
    require_domain(dag, ctx.domain_id)          # before any folder is created or any file read
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    receipt = Run(ctx, dag, from_id=args.from_stage, to_id=args.to_stage, runner=runner or default_runner).execute()
    if not args.json:
        print(table(receipt), file=sys.stderr)
    print(json.dumps(receipt, indent=2, ensure_ascii=True))
    return int(receipt["exit_code"])
