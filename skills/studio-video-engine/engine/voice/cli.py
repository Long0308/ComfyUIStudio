"""CLI glue for ``jjv voice plan|synth|reconcile|adopt|approve|finalize`` (parsing + handlers).

One JSON summary on stdout (``ensure_ascii``), the engine exit code as the return value.
Dry run is the default for ``synth``; a POST happens only with ``--execute``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy.client import ComfyClient
from ..config.loader import ResolvedConfig, resolve_episode
from ..core.errors import EngineError, Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from ..seedvr2.seam_media import find_ffmpeg
from . import approval, finalize, receipts, reconcile, synth
from .client import VoiceStudioClient
from .plan import build_plan
from .script_ingest import dialogue_from_script
from .recipe import VoiceSettings, optional_block, voice_settings

CATEGORIES = ("dialogue", "vocabulary", "end_line", "brand_voice", "all")


def _config(ref: str) -> ResolvedConfig:
    """Voice runs BEFORE any clip exists: a ``jjv/shots-skeleton/v1`` shot list is accepted (a real shots.json is
    validated in full, as always)."""
    return resolve_episode(ref, prerender=True)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="voice version directory (receipts, native and final WAVs)")


def register_cli(stages: Any) -> None:
    voice = stages.add_parser("voice", help="voice stage: plan, synth (VoiceStudio, GPU), reconcile, adopt, approve, finalize")
    verbs = voice.add_subparsers(dest="verb", required=True)
    plan = verbs.add_parser("plan", help="jobs from dialogue + cast + recipe (offline, write-once)")
    _common(plan)
    plan.add_argument("--dialogue", default=None, help="jjv/dialogue/v1 file (default episode.files.dialogue)")
    plan.add_argument("--script", default=None, help="the LOCKED film script instead of --dialogue: every spoken shot, "
                      "vocabulary card, end line and brand voice line becomes a job (no hand-made dialogue file)")
    plan.add_argument("--extras", default=None, help="with --script: JSON list of extra lines "
                      "[{kind: end_line|brand_voice, id, speaker, text_tts, target_duration_s}] (added to script.voice_extras)")
    plan.add_argument("--vocabulary-speaker", default=None, help="with --script: speaker of the vocabulary cards")
    plan.add_argument("--cast", default=None, help="jjv/cast/v1 file (default episode.files.cast)")
    plan.add_argument("--recipe", default=None, help="voice recipe id (default episode.voice.recipe or the domain's only one)")
    plan.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    run = verbs.add_parser("synth", help="guarded VoiceStudio POST per job; dry run unless --execute")
    _common(run)
    run.add_argument("--execute", action="store_true", help="really POST (GPU lock + idle queue required)")
    run.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    run.add_argument("--voicestudio-url", default=None, help="overrides machine.voicestudio.url")
    run.add_argument("--category", choices=CATEGORIES, default="all")
    run.add_argument("--lock-timeout-seconds", type=float, default=None)
    rec = verbs.add_parser("reconcile", help="bind unreconciled POSTs via /history; never re-posts")
    _common(rec)
    rec.add_argument("--voicestudio-url", default=None)
    adopt = verbs.add_parser("adopt", help="bind existing native WAVs as takes (no HTTP)")
    _common(adopt)
    adopt.add_argument("--takes", required=True, help="JSON list of {request_id, path, audio_id}")
    appr = verbs.add_parser("approve", help="record a listener's approval of a bound take (bound to its WAV sha256)")
    _common(appr)
    appr.add_argument("--job", default=None, help="request id, e.g. dialogue:S01_A or end_line:mother")
    appr.add_argument("--by", default=None, help="the person who listened (machine names are refused)")
    appr.add_argument("--note", default=None, help="what was heard (required)")
    appr.add_argument("--sha256", default=None, help="the native WAV sha256 the listener heard (checked, optional)")
    appr.add_argument("--list", action="store_true", help="show every job's approval state; write nothing")
    fin = verbs.add_parser("finalize", help="editorial format, speaker transform, the single trim, split")
    _common(fin)
    fin.add_argument("--category", choices=CATEGORIES, default="dialogue")
    fin.add_argument("--ffmpeg", default=None)
    fin.add_argument("--dry-run", action="store_true")
    fin.add_argument("--resample-lineage", action="store_true",
                     help="explicit approved 24k mono -> 48k stereo PCM16 SOXR conversion; record approval lineage")


def _print(summary: dict) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def _input_path(config: ResolvedConfig, explicit: str | None, key: str, flag: str) -> Path:
    if explicit:
        return Path(explicit)
    declared = optional_block(config.episode, "files").get(key)
    if isinstance(declared, str) and declared:
        return Path(config.episode_root) / "engine" / declared
    raise Refused(f"no {key} document: pass {flag} (episode.files.{key} is not declared yet, see CONFIG-PATCH.md)")


def _settings_for_plan(config: ResolvedConfig, out: Path, args: argparse.Namespace) -> VoiceSettings:
    plan = receipts.load_plan(out)
    settings = voice_settings(config, recipe_id=plan["recipe"]["id"],
                              voicestudio_url=getattr(args, "voicestudio_url", None),
                              lock_timeout_seconds=getattr(args, "lock_timeout_seconds", None))
    if settings.recipe.sha256 != plan["recipe"]["sha256"]:
        raise Refused(f"recipe {plan['recipe']['id']!r} changed since the plan was written "
                      f"({plan['recipe']['sha256'][:12]} -> {settings.recipe.sha256[:12]})")
    if plan["config_sha256"] != config.config_sha256:
        raise Refused(f"the resolved config changed since the plan ({plan['config_sha256'][:12]} -> "
                      f"{config.config_sha256[:12]}); re-plan")
    return settings


def _derived(config: ResolvedConfig, args: argparse.Namespace) -> dict:
    """The dialogue document derived from the locked script (+ extras file), with the source recorded."""
    script_path = Path(args.script)
    extras = read_json(Path(args.extras)) if args.extras else None
    if extras is not None and not (isinstance(extras, list) and all(isinstance(r, dict) for r in extras)):
        raise Refused("--extras must be a JSON list of objects")
    document = dialogue_from_script(read_json(script_path), episode_id=config.episode["episode_id"], extras=extras,
                                    vocabulary_speaker=args.vocabulary_speaker)
    source = {"kind": "script", "path": receipts.describe_path(script_path, episode_root=Path(config.episode_root),
                                                                out=Path(args.out)),
              "sha256": sha256_file(script_path),
              **({"extras": {"path": str(args.extras), "sha256": sha256_file(Path(args.extras))}} if args.extras else {})}
    return {"document": document, "source": source}


def run_plan(args: argparse.Namespace) -> int:
    config = _config(args.episode)
    out = Path(args.out)
    settings = voice_settings(config, recipe_id=args.recipe)
    if args.script:
        if args.dialogue:
            raise Refused("--script and --dialogue exclude each other")
        plan = build_plan(config, settings, cast_path=_input_path(config, args.cast, "cast", "--cast"), out=out,
                          derived=_derived(config, args))
    else:
        if args.extras or args.vocabulary_speaker:
            raise Refused("--extras and --vocabulary-speaker belong to --script")
        dialogue_path = _input_path(config, args.dialogue, "dialogue", "--dialogue")
        plan = build_plan(config, settings, dialogue_path=dialogue_path,
                          cast_path=_input_path(config, args.cast, "cast", "--cast"), out=out)
    if args.dry_run:
        _print({"ok": True, "dry_run": True, "written": None, "settings_sources": settings.sources, "plan": plan})
        return 0
    digest = write_json_once(out / receipts.PLAN_FILE, plan, mode="ascii")
    _print({"ok": True, "dry_run": False, "written": str(out / receipts.PLAN_FILE), "plan_sha256": digest,
            "job_count": plan["job_count"], "recipe": plan["recipe"], "settings_sources": settings.sources})
    return 0


def _context(args: argparse.Namespace, *, need_http: bool) -> synth.SynthContext:
    config = _config(args.episode)
    out = Path(args.out)
    settings = _settings_for_plan(config, out, args)
    plan = receipts.load_plan(out)
    voice = None
    if need_http:
        if not settings.voicestudio_url:
            raise Refused("a VoiceStudio URL is required (machine.voicestudio.url or --voicestudio-url)")
        voice = VoiceStudioClient(settings.voicestudio_url, timeout_seconds=settings.http_timeout_seconds)
    queue = (lambda: ComfyClient(settings.comfy_url).get("/queue")) if settings.comfy_url else (lambda: None)
    return synth.SynthContext(settings=settings, out=out, plan=plan, voice=voice, queue_reader=queue,
                              episode_root=Path(config.episode_root))


def run_synth(args: argparse.Namespace) -> int:
    if args.execute and args.dry_run:
        raise Refused("--execute and --dry-run exclude each other")
    context = _context(args, need_http=args.execute)
    if not args.execute:
        _print({"ok": True, "dry_run": True, "message": "POST skipped (dry-run)",
                "jobs": synth.dry_run_rows(context.out, context.plan)})
        return 0
    category = None if args.category == "all" else args.category
    try:
        result = synth.run_synth(context, category=category)
    except EngineError as error:
        _print({"ok": False, "dry_run": False, "error": str(error), "stopped_at": error.evidence.get("stopped_at"),
                "results": error.evidence.get("results", [])})
        return error.exit_code  # Refused only happens before any POST (lock/queue/health), so 1 is honest
    _print({"ok": True, "dry_run": False, **result})
    return 0


def run_reconcile(args: argparse.Namespace) -> int:
    context = _context(args, need_http=True)
    _print({"ok": True, **reconcile.run_reconcile(context)})
    return 0


def run_adopt(args: argparse.Namespace) -> int:
    context = _context(args, need_http=False)
    rows = read_json(Path(args.takes))
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise Refused("--takes must be a JSON list of objects")
    _print({"ok": True, **reconcile.adopt_takes(context, rows)})
    return 0


def run_approve(args: argparse.Namespace) -> int:
    config = _config(args.episode)
    out = Path(args.out)
    plan = receipts.load_plan(out)
    root = Path(config.episode_root)
    if args.list:
        missing = {row["request_id"]: row for row in approval.unapproved(out, plan["jobs"], root)}
        _print({"ok": True, "jobs": [{"request_id": j["request_id"], "class": j["category"],
                                      "approved": j["request_id"] not in missing,
                                      **({"reason": missing[j["request_id"]]["reason"]}
                                         if j["request_id"] in missing else {})} for j in plan["jobs"]]})
        return 0
    jobs = {job["request_id"]: job for job in plan["jobs"]}
    if args.job not in jobs:
        raise Refused(f"--job must be one of the planned request ids: {sorted(jobs)}")
    result = approval.approve(out, jobs[args.job], by=args.by, note=args.note, sha256=args.sha256, episode_root=root)
    _print({"ok": True, **result})
    return 0


def _ffmpeg(explicit: str | None) -> str:
    try:
        return find_ffmpeg(explicit)
    except Refused as error:
        raise Uncertain(str(error)) from error


def run_finalize(args: argparse.Namespace) -> int:
    config = _config(args.episode)
    out = Path(args.out)
    settings = _settings_for_plan(config, out, args)
    context = finalize.FinalizeContext(settings=settings, config=config, out=out, plan=receipts.load_plan(out),
                                       ffmpeg=_ffmpeg(args.ffmpeg), category=args.category,
                                       resample_lineage=getattr(args, "resample_lineage", False))
    if args.dry_run:
        _print({"ok": True, "dry_run": True, **finalize.dry_run(context)})
        return 0
    receipt = finalize.run_finalize(context)
    _print({"ok": True, "dry_run": False, "receipt": str(out / receipts.FINALIZE_FILE),
            "bindings": str(out / receipts.BINDINGS_FILE),
            "mix_handoff": receipt["mix_handoff"],
            "entries": [{"shot": e["shot"], "class": e["class"], "receipt_wav": e["receipt_wav"]["path"],
                         "sha256": e["receipt_wav"]["sha256"], "duration_s": e["receipt_wav"]["duration_s"],
                         "split": None if not e["split"] else [s["label"] for s in e["split"]["segments"]],
                         **({"lineage_checks": e["lineage"]["checks"]} if e.get("lineage") else {})}
                        for e in receipt["entries"]]})
    return 0


def run_voice(args: argparse.Namespace) -> int:
    handlers = {"plan": run_plan, "synth": run_synth, "reconcile": run_reconcile, "adopt": run_adopt,
                "approve": run_approve, "finalize": run_finalize}
    return handlers[args.verb](args)
