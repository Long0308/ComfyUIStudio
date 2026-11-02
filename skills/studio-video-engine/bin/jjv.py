"""jjv: single CLI of the studio video engine (frozen verify, config validate, seedvr2 plan/execute, comfy verbs, qa av, editorial build-config).

Works under ``python -I`` (which drops the script directory from sys.path), so
the skill root is added explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from engine.config.loader import REPO_ROOT, build_config, find_episode_file, resolve_episode  # noqa: E402
from engine.cli_runtime import add_runtime_parsers, run_comfy, run_seedvr2_execute  # noqa: E402
from engine.core.errors import EngineError, exit_code_for  # noqa: E402
from engine.frozen import add_verify_arguments, run_verify  # noqa: E402
from engine.config.cli import register_config_verbs, run_config_contract  # noqa: E402
from engine.seedvr2.plan import build_plan, refuse_output_inside, require_fresh_out, write_plan  # noqa: E402
from engine.seedvr2 import seam_blend_run  # noqa: E402
from engine.seedvr2 import cli_cut  # noqa: E402
from engine.seedvr2 import adopt  # noqa: E402
from engine.seedvr2.cli_cut import add_plan_coverage_args, coverage_inputs  # noqa: E402
from engine.editorial.cli import register_cli as register_editorial, run_build_config  # noqa: E402
from engine.editorial.boundaries_suggest_cli import run_boundaries  # noqa: E402
from engine.editorial.presets_cli import run_presets  # noqa: E402
from engine.editorial.icons_cli import register_cli as register_icons, run_icons  # noqa: E402
from engine.editorial.episode_text_cli import register_cli as register_text, run_text  # noqa: E402
from engine.qa.cli import register_cli as register_qa, run_qa_av  # noqa: E402
from engine.qa.review_cli import run_qa_review  # noqa: E402
from engine.qa.preflight_cli import run_qa_preflight  # noqa: E402
from engine.qa.gate_cli import run_qa_gate  # noqa: E402
from engine.qa.transitions_cli import run_qa_transitions  # noqa: E402
from engine.qa.expression import run_qa_expression  # noqa: E402
# --- voice stage (T-E40v) ---------------------------------------------------------------
from engine.voice.cli import register_cli as register_voice, run_voice  # noqa: E402
# --- end voice stage --------------------------------------------------------------------
# --- audio stage (T-E43) ----------------------------------------------------------------
from engine.audio.cli import register_cli as register_audio, run_audio  # noqa: E402
# --- end audio stage --------------------------------------------------------------------
# --- timing stage (T-E33) ---------------------------------------------------------------
from engine.timing.cli import register_cli as register_timing, run_qa_words, run_timing  # noqa: E402
from engine.editorial.segments_edit_cli import register_cli as register_edit, run_edit  # noqa: E402
# --- end timing stage -------------------------------------------------------------------
# --- plan stage (T-E45 P0) --------------------------------------------------------------
from engine.plan.cli import register_cli as register_plan, run_plan  # noqa: E402
# --- end plan stage ---------------------------------------------------------------------
from engine.layout.cli import register_cli as register_layout, run_layout  # noqa: E402
from engine.images.cli import register_cli as register_images, run_images  # noqa: E402
from engine.ref.cli import register_cli as register_ref, run_ref  # noqa: E402
from engine.script.cli import register_cli as register_script, run_script  # noqa: E402
from engine.storyboard.cli import register_cli as register_storyboard, run_storyboard  # noqa: E402
from engine.deliver.cli import register_cli as register_delivery, run_delivery  # noqa: E402
from engine.h3.cli import register_cli as register_h3, run_h3  # noqa: E402
from engine.video.cli import register_cli as register_video, run_video  # noqa: E402
from engine.health.cli import register_cli as register_health, run_health  # noqa: E402
from engine.bridge.cli import register_cli as register_bridge, run_bridge  # noqa: E402
from engine.core import steplog as steplog_mod  # noqa: E402  (BP-00A: read-only show | verify | plan-resume)
from engine.captions.cli import register_cli as register_captions, run_captions  # noqa: E402
from engine.post.logo.cli import register_cli as register_post, run_post  # noqa: E402
from engine.post.grade.cli import register_cli as register_grade, run_grade  # noqa: E402
from engine.assemble.cli import run_assemble  # noqa: E402
# --- run orchestrator (M8 / Q-6) --------------------------------------------------------
from engine.run.cli import register_cli as register_run, run_run  # noqa: E402
# --- end run orchestrator ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jjv", description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    frozen = stages.add_parser("frozen", help="frozen ep04 file guard")
    verbs = frozen.add_subparsers(dest="verb", required=True)
    add_verify_arguments(verbs.add_parser("verify", help="read-only re-hash; exit 0 only if all match"))
    config = stages.add_parser("config", help="configuration layer")
    config_verbs = config.add_subparsers(dest="verb", required=True)
    validate = config_verbs.add_parser(
        "validate", help="resolve machine/domain/recipe/episode; exit 1 on any violation")
    validate.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    register_config_verbs(config_verbs)
    seedvr2 = stages.add_parser("seedvr2", help="SeedVR2 stage (plan; execute is a dry run unless --execute)")
    seedvr2_verbs = seedvr2.add_subparsers(dest="verb", required=True)
    plan = seedvr2_verbs.add_parser(
        "plan", help="write a plan v2 and API graphs to --out; refuses without a qualified recipe")
    plan.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    plan.add_argument("--out", required=True, help="fresh scratch directory outside the episode tree")
    plan.add_argument("--segments-root", default=None,
                      help="existing segment tree to bind read-only (<shot>/chunks/<chunk>/source-segment.mp4)")
    add_plan_coverage_args(plan)
    seam_blend_run.register_cli(seedvr2_verbs)
    cli_cut.register_cli(seedvr2_verbs)
    adopt.register_cli(seedvr2_verbs)
    add_runtime_parsers(stages, seedvr2_verbs)
    register_qa(stages)
    register_editorial(stages)
    register_edit(stages)
    register_icons(stages)
    register_text(stages)
    # --- voice stage (T-E40v) ---
    register_voice(stages)
    # --- end voice stage ---
    # --- audio stage (T-E43) ---
    register_audio(stages)
    # --- end audio stage ---
    # --- timing stage (T-E33) ---
    register_timing(stages)
    # --- end timing stage ---
    # --- plan stage (T-E45 P0) ---
    register_plan(stages)
    register_layout(stages)
    register_images(stages)
    register_ref(stages)
    # --- end plan stage ---
    register_script(stages)
    register_storyboard(stages)
    register_delivery(stages)
    register_h3(stages)
    register_video(stages)
    register_health(stages)
    register_bridge(stages)
    steplog_mod.register_cli(stages)
    register_captions(stages)
    register_post(stages)
    register_grade(stages)
    # --- run orchestrator (M8 / Q-6) ---
    register_run(stages)
    # --- end run orchestrator ---
    return parser


def run_seedvr2_plan(ref: str, out: str, segments_root: str | None, args: argparse.Namespace | None = None) -> int:
    """Plan one episode; exit 0 planned, 1 refused (no recipe, bad config, protected --out)."""
    config = resolve_episode(ref)
    segments = Path(segments_root) if segments_root else None
    refuse_output_inside(Path(out), [
        Path(config.episode_root), Path(config.machine["comfy"]["root"]), segments,
        REPO_ROOT / "production-local", REPO_ROOT])
    require_fresh_out(Path(out))
    reads, extra_scope = coverage_inputs(args) if args is not None else (None, [])
    result = build_plan(config, repo_root=REPO_ROOT, segments_root=segments, reads=reads, extra_scope=extra_scope)
    written = write_plan(Path(out), result)
    print(json.dumps({"ok": True, "status": result.plan["status"], **written,
                      "config_sha256": config.config_sha256, "totals": result.plan["totals"]}, indent=2))
    return 0


def run_config_validate(ref: str) -> int:
    """Print one JSON summary (resolved config + violations); exit 0 ok, 1 violation."""
    report = build_config(find_episode_file(ref))
    print(json.dumps({
        "ok": report.ok,
        "episode_file": report.episode_file,
        "config_sha256": report.config.config_sha256 if report.config else None,
        "violations": list(report.violations),
        "resolved": report.config.as_dict() if report.config else None,
    }, indent=2, ensure_ascii=True))
    return 0 if report.ok else 1


def run_seedvr2_seam_blend(args: argparse.Namespace) -> int:
    """Verify + plan (dry run) or build one shot's seam-blended mp4; one JSON summary."""
    config = resolve_episode(args.episode)
    summary = seam_blend_run.run_seam_blend(
        config, shot_id=args.shot, out=args.out, mode=args.mode, dry_run=args.dry_run,
        policy_path=args.policy, ffmpeg=args.ffmpeg, threads=args.threads)
    seam_blend_run.emit_json(summary)
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    if args.stage == "frozen" and args.verb == "verify":
        return run_verify(tree=args.tree, episode=args.episode)
    if args.stage == "config" and args.verb == "contract":
        return run_config_contract(args)
    if args.stage == "config" and args.verb == "validate":
        return run_config_validate(args.episode)
    if args.stage == "seedvr2" and args.verb == "plan":
        return run_seedvr2_plan(args.episode, args.out, args.segments_root, args)
    if args.stage == "seedvr2" and args.verb in ("segments", "tails"):
        return cli_cut.run(args)
    if args.stage == "seedvr2" and args.verb == "adopt":
        return adopt.run(args)
    if args.stage == "seedvr2" and args.verb == "execute":
        return run_seedvr2_execute(args)
    if args.stage == "seedvr2" and args.verb == "seam-blend":
        return run_seedvr2_seam_blend(args)
    if args.stage == "comfy":
        return run_comfy(args)
    if args.stage == "qa" and args.verb == "av":
        return run_qa_av(args)
    if args.stage == "qa" and args.verb == "review":
        return run_qa_review(args)
    if args.stage == "qa" and args.verb == "preflight":
        return run_qa_preflight(args)
    if args.stage == "qa" and args.verb == "gate":
        return run_qa_gate(args)
    if args.stage == "qa" and args.verb == "transitions":
        return run_qa_transitions(args)
    if args.stage == "qa" and args.verb == "expression":
        return run_qa_expression(args)
    if args.stage == "editorial" and args.verb == "build-config":
        return run_build_config(args)
    if args.stage == "edit" and args.verb == "assemble":
        return run_assemble(args)
    if args.stage == "edit":
        return run_edit(args)
    if args.stage == "editorial" and args.verb == "presets":
        return run_presets(args)
    if args.stage == "editorial" and args.verb == "boundaries":
        return run_boundaries(args)
    if args.stage == "icons":
        return run_icons(args)
    if args.stage == "text":
        return run_text(args)
    # --- voice stage (T-E40v) ---
    if args.stage == "voice":
        return run_voice(args)
    # --- end voice stage ---
    # --- audio stage (T-E43) ---
    if args.stage == "audio":
        return run_audio(args)
    # --- end audio stage ---
    if args.stage == "captions":
        return run_captions(args)
    if args.stage == "post":
        return run_grade(args) if getattr(args, "verb", None) == "grade" else run_post(args)
    # --- timing stage (T-E33) ---
    if args.stage == "timing":
        return run_timing(args)
    if args.stage == "qa" and args.verb == "words":
        return run_qa_words(args)
    # --- end timing stage ---
    # --- plan stage (T-E45 P0) ---
    if args.stage == "plan" and args.verb == "explain":
        return run_plan(args)
    # --- end plan stage ---
    if args.stage == "layout":
        return run_layout(args)
    if args.stage == "images":
        return run_images(args)
    if args.stage == "ref":
        return run_ref(args)
    if args.stage == "script":
        return run_script(args)
    if args.stage == "storyboard":
        return run_storyboard(args)
    if args.stage in ("deliver", "brand", "publish"):
        return run_delivery(args)
    if args.stage == "h3":
        return run_h3(args)
    if args.stage == "video":
        return run_video(args)
    # --- run orchestrator (M8 / Q-6) ---
    if args.stage == "run":
        return run_run(args)
    # --- end run orchestrator ---
    if args.stage == "health":
        return run_health(args)
    if args.stage == "bridge":
        return run_bridge(args)
    if args.stage == "steplog":
        return steplog_mod.run_cli(args)
    return 2


def _refresh_ui_state(args: argparse.Namespace) -> None:
    """Sau verb stage video/h3/captions: làm mới dữ liệu panel của episode có target (opt-in); kết quả ra stderr, không đổi stdout/exit."""
    from engine.video.ui_refresh import refresh_after

    result = refresh_after(args.stage, getattr(args, "verb", None), getattr(args, "episode", None),
                           getattr(args, "machine", None), bool(getattr(args, "dry_run", False)))
    if result is not None:
        print("ui-state refresh: " + json.dumps(result, ensure_ascii=True), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Never lets a traceback escape: EngineError keeps its exit code, anything else is 2."""
    args = build_parser().parse_args(argv)
    try:
        code = _dispatch(args)
        _refresh_ui_state(args)
        return code
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "interrupted (Ctrl-C); state is whatever the receipts on disk say: "
                                                "reconcile before re-running"}, indent=2))
        return 2
    except Exception as error:  # noqa: BLE001 - the CLI contract is "JSON + exit 2", not a traceback
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
