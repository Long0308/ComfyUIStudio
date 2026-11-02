"""CLI glue for ``jjv images plan|submit|adopt|native|compare|approve`` (Q-2).  One JSON summary on stdout.

Exit codes follow the engine: 0 ok, 1 refused (nothing was sent), 2 uncertain/unreadable, 4 execution failed.
Real routes are refused unless their own authorisation flag is given (--pilot, --spend-ok); --dry-run prepares
graphs/requests/prompts and sends nothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy.client import ComfyClient
from ..comfy.settings import settings_from_machine
from ..core import steplog
from ..gui_export import cli as gui_export_cli
from ..core.errors import EXIT_OK, Refused
from ..core.io import read_json
from ..layout.context import default_provider, load_context, require_provider
from . import adopt as adopt_mod
from . import approve as approve_mod
from . import codex as codex_mod
from . import compare as compare_mod
from . import library as library_mod
from . import library_cli
from . import local as local_mod
from . import native as native_mod
from . import openrouter as openrouter_mod
from . import plan as plan_mod
from . import prompt_route
from . import pool
from . import workflow_publish

PROVIDERS = ("comfyui-local", "openrouter", "codex-adopt", "codex-exec")


def _common(parser: argparse.ArgumentParser, shot: bool = True) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="images folder (holds images-plan.json and every receipt)")
    parser.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    if shot:
        parser.add_argument("--shot", required=True)


def _publish_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--allow-foreign-manifest", action="store_true",
                        help="append to an episode manifest whose schema this publisher did not write (existing entries untouched)")


def _review_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--shot", default=None, help="shot mode: the shot to review (not with --library-out)")
    parser.add_argument("--library-out", default=None, metavar="DIR",
                        help="library mode: the folder `submit --library-out` wrote; review ONE --prompt-id or a whole --character")
    parser.add_argument("--prompt-id", default=None, help="library mode: one prompt_id (all its takes, every lane)")
    parser.add_argument("--character", default=None, help="library mode: every prompt_id starting with <CHARACTER>_")


def _review_mode(args: argparse.Namespace) -> bool:
    """True = library mode. The two modes are exclusive and each needs its own selector (Refused, nothing written)."""
    if args.library_out is not None:
        if args.shot is not None:
            raise Refused("--library-out has no shot: drop --shot (library images are not tied to a shot or a plan)")
        if (args.prompt_id is None) == (args.character is None):
            raise Refused("--library-out needs exactly one of --prompt-id or --character")
        return True
    if args.prompt_id is not None or args.character is not None:
        raise Refused("--prompt-id/--character need --library-out")
    if args.shot is None:
        raise Refused("--shot is required (or --library-out DIR with --prompt-id/--character for character-library images)")
    return False


def register_cli(stages: Any) -> None:
    images = stages.add_parser("images", help="storyboard images: plan, submit (4 providers), adopt, native, compare, approve")
    verbs = images.add_subparsers(dest="verb", required=True)
    gui_export_cli.register(verbs, "image")
    plan = verbs.add_parser("plan", help="per shot: guide sha, placement sha, cast refs, providers")
    _common(plan, shot=False)
    plan.add_argument("--layout", default=None, help="layout folder (cast refs, placement text, rendered guides)")
    plan.add_argument("--shot", action="append", default=[], help="shot to plan (repeatable; default: every cut shot of --layout)")
    plan.add_argument("--guide", action="append", default=[], metavar="SHOT=PNG")
    plan.add_argument("--placement", action="append", default=[], metavar="SHOT=TXT")
    plan.add_argument("--ref", action="append", default=[], metavar="SHOT:ROLE=PATH", help="extra reference image")
    plan.add_argument("--provider", action="append", default=None, choices=PROVIDERS, help="limit the providers listed")
    plan.add_argument("--codex-account", action="append", default=None, metavar="LABEL=CODEX_HOME")
    sub = verbs.add_parser("submit", help="make an image: comfyui-local | openrouter | codex-exec (codex-adopt uses `adopt`)")
    _common(sub, shot=False)
    sub.add_argument("--shot", default=None, help="the shot to make an image for (not with --library-out)")
    sub.add_argument("--provider", default=None, choices=PROVIDERS,
                     help="default: the first allowed provider in the domain's preferred_order (routes recipe)")
    sub.add_argument("--prompt-file", default=None)
    sub.add_argument("--prompt-batch", default=None, metavar="FILE",
                     help=f"codex-exec only: JSON array of <= {codex_mod.MAX_N} {{prompt_id, prompt_text, ref_images}}; one take per "
                          "item (own prompt + refs + receipt). Not with --n/--take/--prompt-file")
    sub.add_argument("--take", default=None)
    sub.add_argument("--library-out", default=None, metavar="DIR",
                     help="codex-exec --prompt-batch only: LIBRARY mode for character images (no shot, no plan, no guide: Image 1 is "
                          "the first ref); takes go to DIR/<batch>/tNNN. Not with --shot")
    sub.add_argument("--n", type=int, default=1, metavar="N",
                     help=f"codex-exec only: make N takes in one call, one folder + receipt each (1..{codex_mod.MAX_N}, default 1)")
    sub.add_argument("--dry-run", action="store_true", help="prepare and save everything, send nothing")
    sub.add_argument("--task", choices=("general", "identity"), default=None, help="comfyui-local edit LoRA")
    sub.add_argument("--seed", type=int, default=None)
    sub.add_argument("--pilot", action="store_true", help="comfyui-local: a user-authorised GPU pilot (recipe is unqualified)")
    sub.add_argument("--spend-ok", action="store_true", help="openrouter: I accept that this call costs money")
    sub.add_argument("--budget-usd", type=float, default=None)
    sub.add_argument("--endpoint", default=None, help=argparse.SUPPRESS)
    sub.add_argument("--codex-bin", default=None)
    sub.add_argument("--codex-account", action="append", default=None, metavar="LABEL=CODEX_HOME")
    sub.add_argument("--account", default=None, metavar="LABEL",
                     help="codex-exec: pin this call (one lane) to the pool account LABEL; other labels run in parallel")
    sub.add_argument("--pool-state", default=None, help="codex account pool state file (default: <out>/codex-pool-state.json)")
    sub.add_argument("--timeout", type=float, default=None, help="codex exec timeout in seconds")
    _publish_flag(sub)
    ad = verbs.add_parser("adopt", help="register an image made by hand in a Codex session")
    _common(ad)
    ad.add_argument("--file", required=True)
    ad.add_argument("--route", required=True, help="codex-builtin")
    ad.add_argument("--prompt-file", required=True)
    ad.add_argument("--requested-model", default=None)
    ad.add_argument("--ref", action="append", default=[], metavar="ROLE=PATH")
    ad.add_argument("--refs-from-plan", action="store_true")
    ad.add_argument("--source-path", default=None, help="where the tool wrote it (e.g. .../generated_images/<id>/exec-<id>.png)")
    ad.add_argument("--tool-evidence", default=None)
    _publish_flag(ad)
    nat = verbs.add_parser("native", help="864x480 copy of a candidate for H3")
    _common(nat)
    nat.add_argument("--sha", required=True)
    nat.add_argument("--center-crop", action="store_true")
    nat.add_argument("--allow-unapproved", action="store_true")
    _publish_flag(nat)
    cmp_ = verbs.add_parser("compare", help="guide | candidates | overlay | refs sheet + checklist (--library-out: character-library takes)")
    _common(cmp_, shot=False)
    _review_target(cmp_)
    cmp_.add_argument("--sha", action="append", default=None, help="limit to these candidates (default: all)")
    app = verbs.add_parser("approve", help="bind a pick to a candidate sha (every checklist item must be pass)")
    _common(app, shot=False)
    _review_target(app)
    app.add_argument("--sha", required=True)
    app.add_argument("--reviewer", required=True)
    app.add_argument("--scope", required=True)
    app.add_argument("--checklist", default=None)
    prompt_route.register(verbs)  # IMGRT-1: `images route list`, `images prompt new|confirm` (additive)
    library_cli.register(verbs)  # N89-P0: `images library plan|run|lane|status` (additive; the verbs above are unchanged)


def run_images(args: argparse.Namespace) -> int:
    if args.verb == "library":  # N89-P0: no episode context of its own (plan/run carry --episode for the lanes)
        return library_cli.run_library(args)
    if args.verb in ("route", "prompt"):  # IMGRT-1: own context handling (`prompt confirm` has no episode)
        return prompt_route.run(args)
    ctx = load_context(args.episode, args.machine)
    if args.verb == "export-gui":
        result = gui_export_cli.run(ctx, args)
        print(json.dumps({"ok": True, **result}, indent=2))
        return EXIT_OK
    with workflow_publish.allow_foreign_manifest(bool(getattr(args, "allow_foreign_manifest", False))):
        result = _run_verb(ctx, args)
    print(json.dumps({"ok": True, "episode_id": ctx.episode_id, "domain": ctx.domain_id, **result}, indent=2))
    return EXIT_OK


def _run_verb(ctx: Any, args: argparse.Namespace) -> dict[str, Any]:
    out = Path(args.out)
    verb = args.verb
    if verb == "plan":
        accounts = pool.accounts_from(ctx.machine, args.codex_account)
        result = plan_mod.build_images_plan(ctx, out, layout_dir=Path(args.layout) if args.layout else None,
                                            shots=args.shot, guides=args.guide, placements=args.placement,
                                            extra_refs=args.ref, providers=args.provider, accounts=accounts)
    elif verb == "submit":
        result = _submit(ctx, out, args)
    elif verb == "adopt":
        row = adopt_mod.adopt(ctx, out, args.shot, Path(args.file), route=args.route, prompt_file=Path(args.prompt_file),
                              requested_model=args.requested_model, refs=args.ref, refs_from_plan=args.refs_from_plan,
                              source_path=args.source_path, tool_evidence=args.tool_evidence)
        result = _candidate_summary(row)
    elif verb == "native":
        row = native_mod.make_native(ctx, out, args.shot, args.sha, center_crop=args.center_crop,
                                     allow_unapproved=args.allow_unapproved)
        result = {"native": row["native"], "anchor_approved": row["anchor_approved"], "receipt": row["receipt_path"],
                  "workflow": row.get("review_workflow"), "reused": row["reused"]}
    elif verb == "compare":
        if _review_mode(args):
            result = library_mod.compare(ctx, Path(args.library_out), prompt_id=args.prompt_id, character=args.character)
        else:
            result = compare_mod.compare(ctx, out, args.shot, args.sha)
    else:
        if _review_mode(args):
            result = library_mod.approve(ctx, Path(args.library_out), args.sha, prompt_id=args.prompt_id,
                                         character=args.character, reviewer=args.reviewer, scope=args.scope,
                                         checklist=Path(args.checklist) if args.checklist else None)
        else:
            result = approve_mod.approve(ctx, out, args.shot, args.sha, reviewer=args.reviewer, scope=args.scope,
                                         checklist=Path(args.checklist) if args.checklist else None)
    return result


def _candidate_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {"shot": row["shot"], "route": row["route"], "requested_model": row["requested_model"],
            "resolved_model": row["resolved_model"], "runtime_id": row["runtime_id"],
            "prompt_sha256": row["prompt_sha256"], "ref_hashes": [r["sha256"] for r in row["ref_hashes"]],
            "sha256": row["output"]["sha256"], "receipt": row["receipt_path"],
            "workflow": row.get("review_workflow")}


def _comfy_submit_logged(ctx: Any, out: Path, args: argparse.Namespace, prompt: Path, settings: Any, client: Any,
                         queue_item: Any) -> dict[str, Any]:
    """comfyui-local submit with one STEPLOG line (BP-00A). The receipts are written by local.submit, unchanged."""
    take = args.take or "auto"
    with steplog.logged_step(out, run_id=out.name, step_id=f"images.submit.comfyui-local.{args.shot}.{take}",
                             stage="images.submit", inputs=[("prompt", prompt)],
                             settings={"provider": "comfyui-local", "task": args.task, "seed": args.seed,
                                       "take": args.take, "pilot": args.pilot, "dry_run": args.dry_run},
                             model={"name": local_mod.RECIPE_NAME}) as step:
        result = local_mod.submit(ctx, out, args.shot, prompt, settings, client, task=args.task, seed=args.seed,
                                  take=args.take, pilot=args.pilot, dry_run=args.dry_run, queue_item=queue_item)
        step.settings["seed"] = result.get("seed", args.seed)
        if result["dry_run"]:
            step.skip("dry-run: graph and prompt saved, nothing sent")
            step.output(Path(result["graph"]), "graph")
        else:
            receipt = read_json(Path(result["receipt"]))
            step.output(Path(receipt["output"]["path"]), "candidate")
            step.output(Path(result["receipt"]), "receipt")
    return result


def _submit(ctx: Any, out: Path, args: argparse.Namespace) -> dict[str, Any]:
    if args.provider is None:
        args.provider = default_provider(ctx)  # user 2026-10-27: OAuth (codex-exec) first for the cartoon domain
    require_provider(ctx, args.provider)  # domain policy first: a refused provider never reaches its own checks
    if args.n != 1 and args.provider != "codex-exec":
        # N takes per call is a codex-exec batch feature (quota-pooled); comfyui-local is GPU-gated and openrouter is paid
        raise Refused(f"--n is only for --provider codex-exec (got {args.provider}); call submit once per take")
    if args.library_out is not None and args.prompt_batch is None:
        raise Refused("--library-out needs --prompt-batch (library mode is a batch of character images)")
    if args.library_out is not None and args.shot is not None:
        raise Refused("--library-out has no shot: library images are not tied to a shot or an images-plan (drop --shot)")
    if args.library_out is None and args.shot is None:
        raise Refused("--shot is required (or --library-out DIR with --prompt-batch for character images)")
    if args.prompt_batch is not None:
        comfy_queue = args.provider == "comfyui-local" and prompt_route.provenance_required(ctx)  # G4: same queue gate
        if args.provider != "codex-exec" and not comfy_queue:
            raise Refused(f"--prompt-batch is only for --provider codex-exec (got {args.provider})")
        if args.n != 1 or args.take is not None or args.prompt_file is not None:
            raise Refused("--prompt-batch cannot be combined with --n, --take or --prompt-file (the file lists every prompt)")
    elif args.prompt_file is None:
        raise Refused("--prompt-file is required (or --prompt-batch FILE for codex-exec)")
    prompt = Path(args.prompt_file) if args.prompt_file else Path()
    if args.provider == "comfyui-local":
        queue_item = None
        if args.prompt_batch is not None:
            if args.library_out is not None:
                raise Refused("comfyui-local has no --library-out mode")
            queue_item, prompt = prompt_route.comfy_item(ctx, Path(args.prompt_batch), out)
        settings = settings_from_machine(ctx.machine)
        client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
        return _comfy_submit_logged(ctx, out, args, prompt, settings, client, queue_item)
    if args.provider == "openrouter":
        return openrouter_mod.submit(ctx, out, args.shot, prompt, spend_ok=args.spend_ok, dry_run=args.dry_run,
                                     budget_usd=args.budget_usd, endpoint=args.endpoint, take=args.take)
    if args.provider == "codex-exec":
        accounts = pool.accounts_from(ctx.machine, args.codex_account)
        state = Path(args.pool_state or (ctx.machine.get("images") or {}).get("codex_state_path")
                     or out / "codex-pool-state.json")
        if args.library_out is not None:
            library_mod.check_batch_file(Path(args.prompt_batch))  # N50-fix: reserved '_' names + prompt_id characters
            return codex_mod.submit_library_batch(ctx, Path(args.library_out), Path(args.prompt_batch), accounts,
                                                  codex_cmd=codex_mod.find_codex(args.codex_bin, ctx.machine), state_path=state,
                                                  timeout=args.timeout, dry_run=args.dry_run, account=args.account)
        if args.prompt_batch is not None:
            return codex_mod.submit_batch(ctx, out, args.shot, Path(args.prompt_batch), accounts,
                                          codex_cmd=codex_mod.find_codex(args.codex_bin, ctx.machine), state_path=state,
                                          timeout=args.timeout, dry_run=args.dry_run, account=args.account)
        return codex_mod.submit_many(ctx, out, args.shot, prompt, accounts, n=args.n,
                                     codex_cmd=codex_mod.find_codex(args.codex_bin, ctx.machine),
                                     state_path=state, take=args.take, timeout=args.timeout, dry_run=args.dry_run,
                                     account=args.account)
    raise Refused("provider 'codex-adopt' has no submit: use `jjv images adopt` for an image made by hand")
