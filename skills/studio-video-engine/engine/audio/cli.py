"""CLI glue for ``jjv audio music|sfx|mix``: one JSON summary on stdout, the engine exit code as return value.

``music submit`` / ``sfx submit`` are dry runs unless ``--execute`` (then the guarded ``engine.comfy`` path:
GPU lock + idle queue + intent + POST, never a second POST).  ``plan``/``cues``/``finalize`` and ``mix`` are
CPU only.  The only HTTP outside ``submit --execute`` is GET ``/object_info`` for the editable GUI graph.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..comfy.client import ComfyClient, ComfyError
from ..comfy.guards import ClassPolicy
from ..comfy.settings import ComfySettings, settings_from_machine
from ..config.loader import ResolvedConfig, resolve_episode
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, write_json_once
from ..seedvr2.seam_media import find_ffmpeg
from . import brief as brief_mod, cuesheet, jobs, mixcli, music, sections as sections_mod, sfx, timeline as timeline_mod, vocalgate
from .recipe import optional_block, resolve_recipe
from . import musicpick_cli  # noqa: E402


OPT_IN_HELP = "opt in to SFX/ambience for this episode (OFF by default on this channel; or episode.audio.sfx.enabled)"


def require_sfx_opt_in(config: ResolvedConfig, args: argparse.Namespace) -> None:
    """SFX/ambience cost GPU time and sit in the film only when the user opted in for the episode."""
    declared = optional_block(optional_block(config.episode, "audio"), "sfx").get("enabled")
    if not (getattr(args, "with_sfx", False) or declared is True):
        raise Refused("SFX/ambience are OFF by default on this channel (only the voice and the music bed): pass --with-sfx "
                      "or set episode.audio.sfx.enabled for this episode; --dry-run needs no opt-in")


def register_cli(stages: Any) -> None:
    audio = stages.add_parser("audio", help="audio stage: music, sfx (ComfyUI, GPU on submit --execute), mix (CPU)")
    families = audio.add_subparsers(dest="verb", required=True)
    music_p = families.add_parser("music", help="plan | submit | finalize")
    msub = music_p.add_subparsers(dest="action", required=True)
    plan = msub.add_parser("plan", help="style brief + film length -> section jobs (write-once)")
    _common(plan)
    plan.add_argument("--review-config", default=None, help="take fps/total_frames from a review config")
    plan.add_argument("--total-frames", type=int, default=None, help="film length in frames (default: review config)")
    plan.add_argument("--shot-pack", default=None, help="shot pack JSON: its action text picks the instrument palette")
    plan.add_argument("--text-field", action="append", default=None, help="shot field with the action text (repeatable)")
    plan.add_argument("--takes", type=int, default=1, help="songs per candidate (seed, seed+1, ...)")
    plan.add_argument("--candidates", type=int, default=1,
                      help="distinct candidates (other instruments, key, tempo) so the user hears a real choice")
    plan.add_argument("--seed", type=int, default=None)
    plan.add_argument("--brief", default=None, help="JSON file with brief keys (bpm, key, instruments) overriding the derived brief")
    for key in music.BRIEF_KEYS:
        plan.add_argument(f"--{key}", default=None, type=float if key == "bpm" else str)
    plan.add_argument("--dry-run", action="store_true")
    for name, text in (("submit", "guarded ComfyUI jobs; dry run unless --execute"), ("finalize", "decode, join, write the stem")):
        sub = msub.add_parser(name, help=text)
        _common(sub, recipe=False)
        _run_flags(sub, name)
    musicpick_cli.register(msub)
    sfx_p = families.add_parser("sfx", help="cues | submit | finalize")
    ssub = sfx_p.add_subparsers(dest="action", required=True)
    cues = ssub.add_parser("cues", help="cue sheet from shot actions + transitions/ending -> plan (write-once)")
    _common(cues)
    cues.add_argument("--review-config", required=True, help="transitions, icons, cards, ending, shot starts")
    cues.add_argument("--total-frames", type=int, default=None, help="film length in frames (default: review config)")
    cues.add_argument("--extra-cues", default=None, help="JSON list of hand-added cues {class, frame, reason}")
    cues.add_argument("--shot-pack", default=None, help="shot pack JSON (shots[] with shot_id + action text)")
    cues.add_argument("--text-field", action="append", default=None, help="shot field with the action text (repeatable)")
    cues.add_argument("--include-optional", action="store_true", help="also footsteps / leaves / ambience cues")
    cues.add_argument("--dry-run", action="store_true")
    cues.add_argument("--with-sfx", action="store_true", help=OPT_IN_HELP)
    for name, text in (("submit", "guarded ComfyUI jobs; dry run unless --execute"), ("finalize", "clip WAVs + placements receipt")):
        sub = ssub.add_parser(name, help=text)
        _common(sub, recipe=False)
        _run_flags(sub, name)
        sub.add_argument("--with-sfx", action="store_true", help=OPT_IN_HELP)
    mix_p = families.add_parser("mix", help="dialogue + music + SFX -> stems, final mix, QA gate, optional mux")
    mixcli.add_arguments(mix_p)


def _common(parser: argparse.ArgumentParser, *, recipe: bool = True) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="version directory (plan, workflows, receipts, outputs)")
    if recipe:
        parser.add_argument("--recipe", default=None, help="audio recipe id (default: the domain's only one)")


def _run_flags(parser: argparse.ArgumentParser, name: str) -> None:
    parser.add_argument("--dry-run", action="store_true")
    if name == "submit":
        parser.add_argument("--execute", action="store_true", help="really POST (GPU lock + idle queue required)")
        parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    else:
        parser.add_argument("--ffmpeg", default=None)
        parser.add_argument("--no-review-gui", action="store_true", help="skip the editable + result-pinned GUI graphs")
        parser.add_argument("--pick", default=None, help="music only: the take whose bed becomes the stem (default: first that passes the vocal gate)")
        parser.add_argument("--vocal-gate-command", default=None,
                            help="music only: JSON argv list of the vocal separator, with {input} and {out_dir} placeholders")


def _print(summary: dict) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def _timeline(config: ResolvedConfig, review_path: str | None, rate: int, frames: int | None) -> tuple[dict, dict | None]:
    review = timeline_mod.load_review_config(review_path)
    return timeline_mod.resolve(config, review, rate, frames), review


def _require_fresh(config: ResolvedConfig, plan: dict) -> None:
    if plan["config_sha256"] != config.config_sha256:
        raise Refused(f"the resolved config changed since the plan ({plan['config_sha256'][:12]} -> "
                      f"{config.config_sha256[:12]}); re-plan in a new folder")


def _brief_overrides(args: argparse.Namespace) -> dict:
    return {key: getattr(args, key) for key in music.BRIEF_KEYS}


def run_music_plan(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    recipe, origin = resolve_recipe(config, "audio-music", args.recipe)
    rate = recipe.data["sample_rate"]
    line, review = _timeline(config, args.review_config, rate, args.total_frames)
    derived, evidence = None, None
    if review is not None:
        texts = sfx.load_shot_texts(Path(args.shot_pack) if args.shot_pack else None,
                                    args.text_field or ["visual_description"], required=False)
        spoken = [r.get("speech_text", "") for r in review.get("dialogue", []) if isinstance(r, dict)]
        derived, evidence = brief_mod.derive(recipe.data, review, timeline_mod.checked_sections(config, sections_mod.derive_sections(review, line)), line["fps"],
                                             config.episode["episode_id"], list(texts.values()) + spoken)
    brief_file = read_json(Path(args.brief)) if args.brief else None
    brief, sources = music.resolve_brief(config, recipe.data, derived=derived, brief_file=brief_file,
                                         overrides=_brief_overrides(args))
    out = Path(args.out)
    plan = music.build_plan(config, recipe, origin, out=out, timeline=line, brief=brief, brief_sources=sources,
                            evidence=evidence, takes=args.takes, seed=args.seed, write=not args.dry_run, candidates=args.candidates)
    if args.dry_run:
        _print({"ok": True, "dry_run": True, "written": None, "plan": plan})
        return 0
    digest = write_json_once(out / music.PLAN_FILE, plan, mode="ascii")
    _print({"ok": True, "dry_run": False, "written": str(out / music.PLAN_FILE), "plan_sha256": digest,
            "jobs": len(plan["jobs"]), "brief": brief, "brief_sources": sources, "bed_target_s": plan["bed_target_s"],
            "timeline": line, "prompt": plan["prompt"]})
    return 0


def _runtime(config: ResolvedConfig, timeout: float) -> tuple[ComfySettings, ComfyClient, ClassPolicy]:
    settings = settings_from_machine(config.machine)
    return settings, ComfyClient(settings.base_url, timeout_seconds=settings.http_timeout_seconds), ClassPolicy.from_domain(config.domain)


def _submit(args: argparse.Namespace, kind: str) -> int:
    config = resolve_episode(args.episode)
    out = Path(args.out)
    plan = music.load_plan(out) if kind == "music" else sfx.load_plan(out)
    _require_fresh(config, plan)
    if kind == "sfx" and args.execute:
        require_sfx_opt_in(config, args)
    family = "audio-music" if kind == "music" else "audio-sfx"
    recipe, _ = resolve_recipe(config, family, plan["recipe"]["id"])
    if recipe.sha256 != plan["recipe"]["sha256"]:
        raise Refused("the recipe changed since the plan was written; re-plan in a new folder")
    settings, client, policy = _runtime(config, args.timeout_seconds)
    if args.execute and args.dry_run:
        raise Refused("--execute and --dry-run exclude each other")
    if not args.execute:
        _print({"ok": True, "dry_run": True, "message": "POST skipped (dry-run)", "jobs": jobs.dry_rows(out, plan, policy)})
        return 0
    ctx = jobs.RunContext(client=client, settings=settings, policy=policy, out=out, timeout_seconds=args.timeout_seconds,
                          emit=lambda m: print(m, file=sys.stderr))
    _print({"ok": True, "dry_run": False, **jobs.run_all(ctx, plan, recipe.data, Path(config.machine["comfy"]["root"]))})
    return 0


def _object_info(settings: ComfySettings):
    client = ComfyClient(settings.base_url, timeout_seconds=15.0)

    def fetch(name: str) -> dict:
        data = client.get(f"/object_info/{name}")
        if not isinstance(data, dict) or name not in data:
            raise ComfyError(f"/object_info/{name} unknown")
        return data[name]
    return fetch


def _finalize(args: argparse.Namespace, kind: str) -> int:
    config = resolve_episode(args.episode)
    out = Path(args.out)
    module = music if kind == "music" else sfx
    plan = module.load_plan(out)
    _require_fresh(config, plan)
    recipe, _ = resolve_recipe(config, "audio-music" if kind == "music" else "audio-sfx", plan["recipe"]["id"])
    rate = recipe.data["sample_rate"]
    settings = settings_from_machine(config.machine)
    if kind == "sfx" and not args.dry_run:
        require_sfx_opt_in(config, args)
    if args.dry_run:
        _print({"ok": True, "dry_run": True, "states": [{"job_id": j["job_id"], "state": jobs.job_state(out, j)} for j in plan["jobs"]]})
        return 0
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
    except Refused as error:
        raise Uncertain(str(error)) from error
    gui_args = {} if args.no_review_gui else {"object_info": _object_info(settings), "input_dir": settings.input_dir}
    if kind == "music":
        gui_args["pick"] = args.pick
        gui_args["vocal_gate"] = vocalgate.resolve(config.machine, recipe.data["vocal_gate"], args.vocal_gate_command)
    receipt = module.finalize(out, plan, recipe, output_root=settings.output_dir, ffmpeg=ffmpeg, rate=rate, **gui_args)
    summary = {"ok": True, "dry_run": False, "receipt": str(out / module.FINALIZE_FILE)}
    if kind == "music":
        gate = receipt["stem"]["vocal_gate"]["status"]
        summary.update(ok=gate not in ("FAIL", "ERROR"), status=receipt["status"], vocal_gate=receipt["stem"]["vocal_gate"],
                       stem={k: v for k, v in receipt["stem"].items() if k != "vocal_gate"}, takes=[{"job_id": t["job_id"], "song_s": t["song_duration_s"],
                       "bed": t["bed"]["duration_s"], "loop": t["loop_extend"].get("loop")} for t in receipt["takes"]])
    else:
        summary.update(clips=[{k: c[k] for k in ("clip_id", "sha256", "duration_s")} for c in receipt["clips"]],
                       placements=len(receipt["placements"]))
    _print(summary)
    return 0 if summary["ok"] else 1


def run_sfx_cues(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    recipe, origin = resolve_recipe(config, "audio-sfx", args.recipe)
    line, review = _timeline(config, args.review_config, recipe.data["sample_rate"], args.total_frames)
    texts = sfx.load_shot_texts(Path(args.shot_pack) if args.shot_pack else None, args.text_field or ["visual_description"])
    extra = read_json(Path(args.extra_cues)) if args.extra_cues else None
    if extra is not None and not isinstance(extra, list):
        raise Refused("--extra-cues must be a JSON list of {class, frame, reason}")
    sheet = cuesheet.derive(recipe.data, review, texts, line, include_optional=args.include_optional, extra=extra)
    out = Path(args.out)
    if not args.dry_run:
        require_sfx_opt_in(config, args)
    plan = sfx.build_plan(config, recipe, origin, out=out, timeline=line, sheet=sheet, write=not args.dry_run,
                          review_config_sha256=jobs.sha256_file(Path(args.review_config)))
    if args.dry_run:
        _print({"ok": True, "dry_run": True, "written": None, "plan": plan})
        return 0
    digest = write_json_once(out / sfx.PLAN_FILE, plan, mode="ascii")
    _print({"ok": True, "dry_run": False, "written": str(out / sfx.PLAN_FILE), "plan_sha256": digest,
            "clips": len(plan["jobs"]), "placements": len(plan["placements"]), "skipped": plan["skipped"],
            "uncovered_shots": plan["uncovered_shots"]})
    return 0


def run_audio(args: argparse.Namespace) -> int:
    if args.verb == "mix":
        summary, code = mixcli.run_mix(args)
        _print(summary)
        return code
    handled = musicpick_cli.run_music_action(args)
    if handled is not None:
        return handled
    kind, action = args.verb, args.action
    if kind == "music" and action == "plan":
        return run_music_plan(args)
    if kind == "sfx" and action == "cues":
        return run_sfx_cues(args)
    if action == "submit":
        return _submit(args, kind)
    return _finalize(args, kind)
