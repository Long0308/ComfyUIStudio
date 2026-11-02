"""CLI của ``jjv video plan|prompt|render|upscale|run|status|accept|anchor-pack|ui-state`` (một JSON trên stdout).

``anchor-pack`` (``anchor_pack``: bộ neo ảnh MỘT shot, chỉ đọc) và ``ui-state`` (``ui_state.main``: dữ liệu panel, chỉ đọc) không
bao giờ chạm GPU; ``ui-state`` giữ nguyên parser riêng nên ``jjv video ui-state --help`` in đúng cờ của nó.

Mã thoát: 0 ok hoặc dừng ở cổng người dùng (``ok: false``, ``gate.user_gate: true``), 1 từ chối / blocked_technical
(không gửi gì), 2 uncertain (RECONCILE), 3 timeout, 4 failed sau POST.  Chỉ ``run`` (không ``--dry-run``), ``render``
và ``upscale`` có ``--gpu-approved`` mới có thể chạm GPU; ``--dry-run`` không ghi gì và không mở kết nối ComfyUI.
``render`` / ``upscale`` (spec §3, CR-VENG) là verb mỏng trên đúng mã của ``run``: cùng cổng, cùng khoá máy, cùng receipt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy import commands
from ..comfy.client import ComfyClient
from ..comfy.docker_probe import DockerProbe
from ..comfy.settings import settings_from_machine
from ..core import steplog
from ..gui_export import cli as gui_export_cli
from ..core.errors import EXIT_OK, EXIT_REFUSED, Refused, Uncertain
from ..core.io import read_json
from ..layout.context import load_context
from . import accept as accept_mod
from . import anchor_pack as anchor_pack_mod
from . import anchor_stage as anchor_stage_mod
from . import plan as plan_mod
from . import render as render_mod
from . import run as run_mod
from . import state as state_mod
from . import status as status_mod
from . import ui_state_cli
from . import verbs as verbs_mod
from . import tiers

HELP = ("per-shot VIDEO pipeline (01 shotlist -> 02 prompt -> 03 H3 render (GPU) -> 04 1080p -> 05 save & next); "
        "one GPU job at a time; every GPU step needs --gpu-approved")
UI_STATE_HELP = "read-only: jjv/video-ui-state/v1 for the ComfyUI video panel (own flags: `jjv video ui-state --help`; never GPU)"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="versioned plan folder: <out>/plan.json, <out>/<shot>/state.json ...")
    parser.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--routes", default=None, help=argparse.SUPPRESS)


def _gpu_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gpu-approved", default=None, metavar="RECEIPT_OR_TOKEN",
                        help=f"the user's explicit approval for THIS run: {run_mod.TOKEN_PREFIX}<text> or an existing "
                             "receipt file (a mistyped path is an error, never an approval); without it every GPU step stops")


def register_cli(stages: Any) -> None:
    video = stages.add_parser("video", help=HELP)
    verbs = video.add_subparsers(dest="verb", required=True)
    gui_export_cli.register(verbs, "video")
    plan = verbs.add_parser("plan", help="01: read the approved shotlist (jjv/script/v1) -> planned state + plan receipt per shot")
    _common(plan)
    plan.add_argument("--shotlist", required=True, help="approved jjv/script/v1 document of this episode/domain")
    plan.add_argument("--upscale-backend", default=None, help="04 backend (default from the domain routes: none)")
    plan.add_argument("--tier", choices=tiers.NAMES, default="preview", help="resolution tier; default 864x480 preview")
    plan.add_argument("--tier-approval", default=None, help="human promotion record: approved preview for fullhd; approved Full HD cut for 2k")
    prompt = verbs.add_parser("prompt", help="02: freeze the prompt revision of every planned shot (CPU; --lanes N)")
    _common(prompt)
    prompt.add_argument("--lanes", type=int, default=1, help="parallel prompt lanes (1..max_lanes); never GPU")
    render = verbs.add_parser("render", help="03 only: render ONE prompted shot through H3 with the same gates as run "
                                             "(--gpu-approved, domain H3 qualification, h3-inputs, machine lock); never POSTs twice")
    _common(render)
    render.add_argument("--shot", required=True)
    render.add_argument("--revision", type=int, required=True, help="must be the shot's current revision")
    render.add_argument("--route", required=True, help="must be this domain's H3 route (routes h3_route, e.g. h3-ref2va)")
    _gpu_flag(render)
    render.add_argument("--resume", action="store_true", help="re-read an existing render receipt; never a re-POST")
    render.add_argument("--timeout", type=float, default=3600.0, help="H3 wait seconds")
    upscale = verbs.add_parser("upscale", help="04 only: 1080p of ONE rendered shot (backend from the domain routes; a GPU "
                                               "backend needs --gpu-approved and runs under the machine lock)")
    _common(upscale)
    upscale.add_argument("--shot", required=True)
    upscale.add_argument("--revision", type=int, default=None, help="optional check against the shot's current revision")
    upscale.add_argument("--source", required=True, help="this shot's native take (must hash to the render receipt)")
    upscale.add_argument("--target", required=True, help="delivery size; must equal the routes upscale.target (e.g. 1920x1080)")
    upscale.add_argument("--backend", required=True, help="one of the routes upscale.backends (none = record pending)")
    _gpu_flag(upscale)
    upscale.add_argument("--resume", action="store_true", help="re-read an existing upscale receipt; never a re-run")
    run = verbs.add_parser("run", help="02..05 in order; stops at every user gate; --dry-run prints the graph inputs per shot")
    _common(run)
    run.add_argument("--completion", action="store_true", help="keep going until a user gate or final review")
    run.add_argument("--lanes", type=int, default=1, help="parallel prompt/QA lanes (1..max_lanes); the GPU runs one job")
    run.add_argument("--dry-run", action="store_true", help="print the exact ComfyUI inputs per shot; write and send nothing")
    _gpu_flag(run)
    run.add_argument("--upscale-backend", default=None, help="04 backend for this run (default: the plan's backend)")
    run.add_argument("--timeout", type=float, default=3600.0, help="per-shot H3 wait seconds")
    status = verbs.add_parser("status", help="read-only: state, revision, receipt chain, gate and next action per shot")
    _common(status)
    status.add_argument("--shot", default=None)
    status.add_argument("--json", action="store_true", help="(always JSON; kept for the spec's flag set)")
    accept = verbs.add_parser("accept", help="05: pick/reject the 1080p take by sha256 (H3 ledger synced), or --final review")
    _common(accept)
    accept.add_argument("--shot", default=None)
    group = accept.add_mutually_exclusive_group()
    group.add_argument("--pick", action="store_true")
    group.add_argument("--reject", action="store_true")
    group.add_argument("--final", action="store_true", help="final review of the whole plan (every shot accepted)")
    accept.add_argument("--sha256", default=None, help="the 1080p take you watched")
    accept.add_argument("--by", default=None, help="the person who watched (not a machine name)")
    accept.add_argument("--reason", default=None)
    accept.add_argument("--note", default=None, help="final review note")
    anchor = verbs.add_parser("anchor-pack", help=anchor_pack_mod.HELP)
    _common(anchor)
    anchor_pack_mod.add_arguments(anchor)
    staging = verbs.add_parser("anchor-stage", help=anchor_stage_mod.HELP)
    _common(staging)
    anchor_stage_mod.add_arguments(staging)
    for command in (render, upscale, run):
        command.add_argument("--tier", choices=tiers.NAMES, default=None, help="assert frozen plan tier (omitted: inherit plan)")
    ui = verbs.add_parser("ui-state", help=UI_STATE_HELP)  # cùng bộ cờ với ``python -m engine.video.ui_state``
    ui_state_cli.add_arguments(ui)


def _handles(ctx: Any) -> render_mod.ComfyHandles:
    settings = settings_from_machine(ctx.machine)
    client = ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds)
    return render_mod.ComfyHandles(settings=settings, client=client, probe=DockerProbe(), ps=commands.docker_ps)


def _render_inputs(ctx: Any, out: Path, shot: str) -> list[tuple[str, Path]]:
    """Hash the receipt chain and actual H3 media, using the same roots as h3.prepare.

    A missing manifest is recorded (a GPU gate may legitimately precede preparation); a successful
    render refuses missing inputs. Missing/malformed state is never silently converted to no inputs.
    """
    if (Path(out) / state_mod.PLAN_FILE).is_file():
        known = [row["shot"] for row in state_mod.read_plan(out)["shots"]]
        if shot not in known:
            raise Refused(f"shot {shot!r} is not in this plan ({known}); nothing was sent")
    receipts = state_mod.read_state(out, shot)["receipts"]
    inputs: list[tuple[str, Path]] = []
    for role in ("plan", "prompt"):
        if role not in receipts:
            if role == "plan":
                raise Uncertain(f"{shot}: missing plan receipt before video render")
            continue  # planned shots reach the verb's existing state refusal
        inputs.append((role, state_mod.ref_path(out, receipts[role])))
    plan = read_json(inputs[0][1])
    if plan.get("tier") in ("fullhd", "2k"):
        document = state_mod.read_plan(out)
        sources = tiers.validate(ctx, document)
        binding = document["resolution"]["approval"]
        return inputs + [("tier_approval", Path(binding["path"])), ("approved_cut", Path(binding["cut"]["path"])),
                         ("approved_source", Path(sources[shot]["path"]))]
    if plan.get("template"):
        inputs.append(("plan_template", state_mod.ref_path(ctx.root, plan["template"])))
    for index, ref in enumerate(plan.get("refs") or []):
        if ref.get("bound"):
            inputs.append((f"plan_ref_{index}", state_mod.ref_path(ctx.root, ref)))
    manifest = render_mod.manifest_path(out)
    inputs.append(("h3_inputs", manifest))
    if not manifest.is_file():
        return inputs
    rows = [row for row in read_json(manifest).get("shots", []) if row.get("shot") == shot]
    if len(rows) != 1:
        raise Uncertain(f"{shot}: H3 manifest needs exactly one shot row, got {len(rows)}")
    row = rows[0]
    for role in ("template", "anchor", "wav"):
        if not isinstance(row.get(role), dict) or not row[role].get("path"):
            raise Uncertain(f"{shot}: H3 manifest has no {role} path")
        inputs.append((role, state_mod.ref_path(ctx.root, row[role])))
    for role in ("faces", "refs"):
        for index, ref in enumerate(row.get(role) or []):
            inputs.append((f"{role}_{index}", state_mod.ref_path(ctx.root, ref)))
    for role in ("storyboard", "anchor_pack", "preparation_receipt"):
        if row.get(role):
            inputs.append((role, state_mod.ref_path(ctx.root, row[role])))
    return inputs


def _render_outputs(step: steplog.Step, out: Path, render_ref: dict[str, Any]) -> None:
    """Register the native take and every adopted output, not just the JSON receipt."""
    receipt_path = state_mod.ref_path(out, render_ref)
    receipt = state_mod.verify_ref(out, render_ref, "render")
    step.output(receipt_path, "render_receipt")
    native = receipt.get("native")
    if not isinstance(native, dict) or not native.get("path"):
        raise Uncertain("render receipt has no native video output")
    outputs = [("native", native)]
    if receipt.get("adopt"):
        adopted = state_mod.verify_ref(out, receipt["adopt"], "adopt")
        step.output(state_mod.ref_path(out, receipt["adopt"]), "adopt_receipt")
        outputs.extend((f"adopt_{item.get('role', index)}", item)
                       for index, item in enumerate(adopted.get("outputs") or []))
    seen: set[Path] = set()
    for role, ref in outputs:
        # h3.adopt stores media paths as filesystem paths (historically CWD-relative),
        # unlike the render/adopt receipt references, which are relative to video out.
        path = Path(ref["path"]).resolve()
        if path in seen:
            continue
        seen.add(path)
        step.output(path, role)
        actual = step.outputs[-1]["sha256"]
        if actual is None or actual != ref.get("sha256"):
            raise Uncertain(f"render output missing or hash mismatch: {path}")


def _verify_resumed_inputs(out: Path, shot: str, ctx: Any) -> None:
    """An old MP4 must retain its original preparation-bound input hashes on resume."""
    render_ref = state_mod.read_state(out, shot)["receipts"].get("render")
    if render_ref is None:
        return  # resume may also continue a shot which has not rendered yet
    receipt = state_mod.verify_ref(out, render_ref, "render")
    if receipt.get("promotion"):
        tiers.validate(ctx, state_mod.read_plan(out))
        return
    if receipt.get("tier") == "preview":
        tiers.verify_preview(receipt["native"])
    for role in ("h3_inputs", "preparation"):
        if role not in receipt:
            raise Uncertain(f"{shot}: resumed render has no original {role} binding")
    state_mod.verify_ref(out, receipt["h3_inputs"], "original H3 inputs")
    preparation = state_mod.verify_ref(out, receipt["preparation"], "original preparation")
    assets = [preparation[role] for role in ("template", "anchor", "wav")]
    assets.extend(preparation.get("faces") or [])
    assets.extend(preparation.get("refs") or [])
    for asset in assets:
        # h3.prepare stores absolute media paths in preparation.json.
        ref = steplog.file_ref(out, Path(asset["path"]), "prepared_input")
        if ref["sha256"] is None or ref["sha256"] != asset.get("sha256"):
            raise Uncertain(f"{shot}: resumed input differs from original preparation: {asset['path']}")


def _render_logged(ctx: Any, out: Path, args: argparse.Namespace, routes: Path | None, comfy: Any) -> dict[str, Any]:
    """``video render`` with one STEPLOG line (BP-00A). The render receipts are written by the verb, unchanged."""
    out = Path(out).resolve()
    document = state_mod.read_plan(out) if (out / state_mod.PLAN_FILE).is_file() else None
    tier_settings = {}
    if document is not None:
        tiers.validate(ctx, document, getattr(args, "tier", None))
        tier_settings = {key: document[key] for key in ("tier", "resolution", "geometry")}
    elif getattr(args, "tier", None) is not None:
        raise Refused("TIER_PLAN_MISSING: an explicit --tier requires a frozen plan.json")
    step_id = f"video.render.{args.shot}.r{int(args.revision):03d}"
    with steplog.logged_step(out, run_id=Path(out).name, step_id=step_id, stage="video.render",
                             inputs=[],
                             settings={**tier_settings,
                                       "route": args.route, "revision": int(args.revision), "resume": args.resume,
                                       "gpu_approved": args.gpu_approved is not None, "timeout": args.timeout},
                             model={"name": args.route}) as step:
        step.inputs.extend(steplog.file_ref(out, path, role)
                           for role, path in _render_inputs(ctx, out, args.shot))
        if document is not None:
            step.inputs.append(steplog.file_ref(out, out / state_mod.PLAN_FILE, "video_plan"))
        if args.resume:
            _verify_resumed_inputs(out, args.shot, ctx)
        result = verbs_mod.render_shot(ctx, out, args.shot, args.revision, args.route, gpu_token=args.gpu_approved,
                                       comfy=comfy, routes_path=routes, resume=args.resume, wait_timeout=args.timeout)
        gate = result.get("gate")
        if gate is not None:
            step.skip("gate: " + json.dumps(gate, ensure_ascii=True, default=str)[:300])
        else:
            render_ref = state_mod.read_state(Path(out), args.shot)["receipts"].get("render")
            if render_ref is None:
                raise Uncertain(f"{args.shot}: the render verb returned without a render receipt")
            if "prompt" not in {item["role"] for item in step.inputs} or any(
                    item["sha256"] is None for item in step.inputs):
                raise Uncertain(f"{args.shot}: successful render has missing input files")
            _render_outputs(step, Path(out), render_ref)
    return result


def run_video(args: argparse.Namespace) -> int:
    if args.verb == "ui-state":  # ui_state_cli in JSON và trả mã thoát riêng (không qua _common/--routes)
        return ui_state_cli.run(args)
    ctx = load_context(args.episode, args.machine)
    if args.verb == "export-gui":
        result = gui_export_cli.run(ctx, args)
        print(json.dumps({"ok": True, **result}, indent=2))
        return EXIT_OK
    out = Path(args.out)
    routes = Path(args.routes) if args.routes else None
    code = EXIT_OK
    if args.verb == "anchor-pack":
        result = anchor_pack_mod.run(ctx, args)
    elif args.verb == "anchor-stage":
        result = anchor_stage_mod.run(ctx, args)
    elif args.verb == "plan":
        # Build and validate before a log context: even logging FAIL can mkdir(out).
        result = plan_mod.plan(ctx, Path(args.shotlist), out, routes_path=routes,
                               upscale_backend=args.upscale_backend, tier=args.tier,
                               tier_approval=Path(args.tier_approval) if args.tier_approval else None)
        with steplog.logged_step(out, run_id=out.name, step_id="video.plan", stage="video.plan",
                                 inputs=[("shotlist", Path(args.shotlist))],
                                 settings={"tier": args.tier}, model={"name": "offline-plan"}) as step:
            step.settings.update(resolution=result["resolution"], geometry=result["geometry"])
            document = state_mod.read_plan(out)
            step.inputs.extend(steplog.file_ref(out, Path(ref), role) for role, ref in (
                ("tier_policy", tiers.POLICY), ("routes", document["routes"]["path"]),
                ("template", document["template"]["path"])))
            if args.tier_approval:
                step.inputs.append(steplog.file_ref(out, Path(args.tier_approval), "tier_approval"))
                sources = tiers.validate(ctx, document)
                step.inputs.append(steplog.file_ref(out, Path(document["resolution"]["approval"]["cut"]["path"]), "approved_cut"))
                step.inputs.extend(steplog.file_ref(out, Path(ref["path"]), "approved_source") for ref in sources.values())
            step.output(out / state_mod.PLAN_FILE, "plan")
            for row in result["shots"]:
                step.output(state_mod.shot_dir(out, row["shot"]) / state_mod.PLAN_RECEIPT_FILE, "shot_plan")
    elif args.verb == "prompt":
        result = run_mod.run(ctx, out, completion=False, lanes=args.lanes, dry_run=False, routes_path=routes,
                             prompt_only=True)
        result = {k: v for k, v in result.items() if k in ("prompts", "shots", "lanes", "run_receipt")}
    elif args.verb == "run":
        tiers.validate(ctx, state_mod.read_plan(out), args.tier)
        comfy = None if args.dry_run or args.gpu_approved is None else _handles(ctx)
        result = run_mod.run(ctx, out, completion=args.completion, lanes=args.lanes, dry_run=args.dry_run,
                             gpu_token=args.gpu_approved, comfy=comfy, routes_path=routes, backend=args.upscale_backend,
                             wait_timeout=args.timeout)
        gate = result.get("gate")
        if gate is not None and not gate.get("user_gate"):
            code = EXIT_REFUSED
    elif args.verb in ("render", "upscale"):
        tiers.validate(ctx, state_mod.read_plan(out), args.tier)
        comfy = None if args.gpu_approved is None else _handles(ctx)  # không phê duyệt ⇒ không mở kết nối ComfyUI
        if args.verb == "render":
            result = _render_logged(ctx, out, args, routes, comfy)
        else:
            result = verbs_mod.upscale_shot(ctx, out, args.shot, Path(args.source), args.target, args.backend,
                                            revision=args.revision, gpu_token=args.gpu_approved, comfy=comfy,
                                            routes_path=routes, resume=args.resume)
        gate = result.get("gate")
        if gate is not None and not gate.get("user_gate"):
            code = EXIT_REFUSED
    elif args.verb == "status":
        result = status_mod.status(ctx, out, args.shot, routes_path=routes)
    elif args.final:
        if not args.by or args.note is None:
            raise Refused("accept --final needs --by and --note")
        result = accept_mod.final_review(ctx, out, by=args.by, note=args.note)
    else:
        if not (args.pick or args.reject) or not args.shot or not args.by or args.reason is None:
            raise Refused("accept needs --shot, --pick or --reject, --sha256, --by and --reason (or --final --by --note)")
        result = accept_mod.decide(ctx, out, args.shot, "pick" if args.pick else "reject", by=args.by,
                                   reason=args.reason, sha256=args.sha256)
    print(json.dumps({"ok": result.get("ok", True), "episode_id": ctx.episode_id, "domain": ctx.domain_id, **result},
                     indent=2))
    return code


__all__ = ["register_cli", "run_video"]
