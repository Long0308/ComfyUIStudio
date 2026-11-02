"""CLI glue of ``jjv audio music pick`` and ``jjv audio music adopt`` (wired by CLI-PATCH-music-pick.md).

``pick``: brief from the script -> score the library -> a bed (receipt + ``used_in`` appended, versioned registry write) or,
only when nothing fits, a generation plan.  ``--dry-run`` reads everything and writes NOTHING (no registry, no receipt, no
workflows).  ``--execute`` then runs the generation on the GPU (guarded path) and the vocal step.
``adopt``: after a generation (or with ``--execute`` to run it): gate, ``no_vocals`` on FAIL, re-gate, residue, register.
One JSON summary on stdout; the engine exit code as return value.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path
from typing import Any

from ..config.loader import ResolvedConfig, resolve_episode
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, write_json_once
from ..seedvr2.seam_media import find_ffmpeg
from . import brief as brief_mod, jobs, library, music, musicpick, musicpick_adopt, musicpick_gen, sections as sections_mod
from . import sfx, timeline as timeline_mod, vocalgate, vocalstrip
from .recipe import resolve_recipe

PICK_FILE = "music-pick.json"
PICK_SCHEMA = "jjv/audio-music-pick/v1"
DEFAULT_LIBRARY_DIRNAME = "_library"


def register(msub: Any) -> None:
    """Add ``pick`` and ``adopt`` to the ``audio music`` action sub-parsers."""
    pick = msub.add_parser("pick", help="library first: pick a gated bed for the script's brief; generate only when none fits")
    _common(pick)
    pick.add_argument("--pick-recipe", default=None, help="music pick recipe id (default audio/music-pick-v001)")
    pick.add_argument("--recipe", default=None, help="music recipe id the brief tables come from (default: the domain's only one)")
    pick.add_argument("--review-config", default=None, help="default: episode.files.review_config")
    pick.add_argument("--shot-pack", default=None, help="default: episode.files.shot_pack")
    pick.add_argument("--text-field", action="append", default=None)
    pick.add_argument("--total-frames", type=int, default=None)
    pick.add_argument("--brief", default=None, help="JSON file with brief keys (bpm, key, instruments) overriding the derived brief")
    for key in music.BRIEF_KEYS:
        pick.add_argument(f"--{key}", default=None, type=float if key == "bpm" else str)
    pick.add_argument("--generator", default=None, choices=musicpick_gen.GENERATORS, help="force the generator when none fits")
    pick.add_argument("--takes", type=int, default=None, help="generation takes (default: the generator's)")
    pick.add_argument("--seed", type=int, default=None)
    pick.add_argument("--dry-run", action="store_true", help="read and decide only: no registry write, no receipt, no workflow files")
    pick.add_argument("--execute", action="store_true", help="when none fits: really generate (GPU) and run the vocal step")
    _run_flags(pick)
    adopt = msub.add_parser("adopt", help="vocal step + register: gate, no_vocals on FAIL, re-gate, residue, library")
    _common(adopt)
    adopt.add_argument("--recipe", default=None)
    adopt.add_argument("--pick-recipe", default=None)
    adopt.add_argument("--take", default=None, help="take to adopt (default: the finalize receipt's stem)")
    adopt.add_argument("--execute", action="store_true", help="run the generation jobs that are not COMPLETED yet (GPU)")
    _run_flags(adopt)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help="version folder (pick receipt, plan, workflows, beds, receipts)")
    parser.add_argument("--library", default=None, help=f"library root (default: <episodes folder>/{DEFAULT_LIBRARY_DIRNAME})")


def _run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ffmpeg", default=None)
    parser.add_argument("--vocal-gate-command", default=None, help="JSON argv of the separator ({input}, {out_dir})")
    parser.add_argument("--demucs-python", default=None, help="Demucs venv interpreter (default: first word of the gate command)")
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)


def _print(summary: dict) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def library_dir(config: ResolvedConfig, flag: str | None) -> Path:
    return Path(flag) if flag else Path(config.episode_root).parent / DEFAULT_LIBRARY_DIRNAME


def _episode_file(config: ResolvedConfig, flag: str | None, key: str) -> str | None:
    if flag:
        return flag
    declared = (config.episode.get("files") or {}).get(key)
    return str((Path(config.episode_root) / "engine" / declared).resolve()) if declared else None


def episode_brief(config: ResolvedConfig, base, args: argparse.Namespace) -> tuple[dict, dict, dict, dict | None]:
    """``(timeline, brief, sources, evidence)``: the same derivation ``music plan`` uses (no hand-written prompt)."""
    review = timeline_mod.load_review_config(_episode_file(config, args.review_config, "review_config"))
    line = timeline_mod.resolve(config, review, base.data["sample_rate"], args.total_frames)
    derived, evidence = None, None
    if review is not None:
        pack = _episode_file(config, args.shot_pack, "shot_pack")
        texts = sfx.load_shot_texts(Path(pack) if pack else None, args.text_field or ["visual_description"], required=False)
        spoken = [r.get("speech_text", "") for r in review.get("dialogue", []) if isinstance(r, dict)]
        derived, evidence = brief_mod.derive(base.data, review, timeline_mod.checked_sections(config, sections_mod.derive_sections(review, line)), line["fps"],
                                             config.episode["episode_id"], list(texts.values()) + spoken)
    brief_file = read_json(Path(args.brief)) if args.brief else None
    brief, sources = music.resolve_brief(config, base.data, derived=derived, brief_file=brief_file,
                                         overrides={k: getattr(args, k) for k in music.BRIEF_KEYS})
    return line, brief, sources, evidence


def _table(ranking: list[dict]) -> list[dict]:
    keys = ("id", "fits", "fits_by_content", "eligible", "score", "score_without_own_use", "components", "already_used_by_this_episode",
            "refused_because")
    return [{k: r[k] for k in keys} for r in ranking]


def _ffmpeg(flag: str | None) -> str:
    try:
        return find_ffmpeg(flag)
    except Refused as error:
        raise Uncertain(str(error)) from error


def _generator_models_present(config: ResolvedConfig, recipe) -> str | None:
    try:
        jobs.verify_models(recipe.data, Path(config.machine["comfy"]["root"]), full=False)
    except Refused as error:
        return str(error)
    return None


def choose_generator(config: ResolvedConfig, pick, base, brief: dict, target: float, forced: str | None) -> tuple[str, list[dict]]:
    """The first generator (ACE-Step, then YuE2) whose model files are on disk; the skipped ones are listed with why."""
    skipped = []
    for name in musicpick_gen.generator_order(pick.data, forced):
        problem = _generator_models_present(config, musicpick_gen.derived_recipe(pick, base, name, brief, target))
        if problem is None:
            return name, skipped
        skipped.append({"generator": name, "why": problem})
    raise Refused(f"no generator can run: {skipped}")


def run_pick(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    base, _ = resolve_recipe(config, "audio-music", args.recipe)
    pick_recipe = musicpick.load_pick_recipe(config, args.pick_recipe)
    line, brief, sources, evidence = episode_brief(config, base, args)
    target = float(math.ceil(line["duration_s"]) + base.data["loop_extend"]["target_extra_s"])
    lib_dir, film, out = library_dir(config, args.library), config.episode["film_id"], Path(args.out)
    if args.execute and args.dry_run:
        raise Refused("--execute and --dry-run exclude each other")
    schema = pick_recipe.data["library"]["registry_schema"]
    document, read_sha = library.load_registry(lib_dir, schema)
    decision = musicpick.pick(pick_recipe.data, document, lib_dir=lib_dir, brief=brief, evidence=evidence, target_s=target,
                              film=film, domain_id=config.domain["domain_id"])
    head = {"schema": PICK_SCHEMA, "episode_id": config.episode["episode_id"], "film": film,
            "domain": config.domain["domain_id"], "recipe": {"id": pick_recipe.recipe_id, "sha256": pick_recipe.sha256},
            "brief": brief, "brief_sources": sources, "brief_evidence": evidence, "timeline": line, "bed_target_s": target,
            "library": str(lib_dir), "registry_sha256_read": read_sha, "registry_revision": document.get("revision", 0),
            "previous_film": decision["previous_film"], "wanted": decision["wanted"], "decision": decision["decision"],
            "reason": decision["reason"], "ranking": decision["ranking"]}
    if (out / PICK_FILE).exists() and not args.dry_run:
        raise Refused(f"{out / PICK_FILE} exists (receipts are write-once); use a new --out folder")
    if decision["decision"] == "library":
        return _library_branch(args, head, decision, document, read_sha, lib_dir, pick_recipe, out)
    return _generation_branch(args, config, base, pick_recipe, head, line, brief, sources, evidence, target, out, lib_dir)


def _library_branch(args, head: dict, decision: dict, document: dict, read_sha: str, lib_dir: Path, pick_recipe, out: Path) -> int:
    row = next(b for b in document["beds"] if b["id"] == decision["bed_id"])
    stem = musicpick.library_stem(lib_dir, row)
    summary = {"ok": True, "dry_run": bool(args.dry_run), "decision": "library", "bed_id": row["id"], "reason": head["reason"],
               "previous_film": head["previous_film"], "bed_target_s": head["bed_target_s"], "ranking": _table(head["ranking"])}
    if args.dry_run:
        _print({**summary, "written": None, "registry_would_add_used_in": head["film"] not in musicpick.used_films(row)})
        return 0
    receipt_path = out / PICK_FILE
    entry = musicpick.used_entry(head["film"], receipt=str(receipt_path), brief=head["brief"], reason=head["reason"])
    updated, added = library.with_used_in(document, row["id"], entry)
    written = (library.write_registry(lib_dir, updated, read_sha256=read_sha,
                                      schema=pick_recipe.data["library"]["registry_schema"]) if added else None)
    receipt = {**head, "bed_id": row["id"], "stem": stem, "registry_write": written,
               "used_in_added": added, "status": "LIBRARY_BED_PICKED"}
    write_json_once(receipt_path, receipt, mode="ascii", stamp=True)
    _print({**summary, "written": str(receipt_path), "music_receipt": str(receipt_path), "registry_write": written,
            "used_in_added": added, "stem": {k: v for k, v in stem.items() if k != "vocal_gate"}})
    return 0


def _generation_branch(args, config, base, pick_recipe, head: dict, line, brief, sources, evidence, target, out: Path,
                       lib_dir: Path) -> int:
    generator, skipped = choose_generator(config, pick_recipe, base, brief, target, args.generator)
    spec = pick_recipe.data["generation"].get(generator, {})
    takes = args.takes or int(spec.get("takes", 1))
    plan, recipe = musicpick_gen.build_generation_plan(config, pick_recipe, base, generator, out=out, timeline=line, brief=brief,
                                                       brief_sources=sources, evidence=evidence, takes=takes, seed=args.seed,
                                                       write=not args.dry_run)
    summary = {"ok": True, "dry_run": bool(args.dry_run), "decision": "generate", "generator": generator, "skipped": skipped,
               "reason": head["reason"], "ranking": _table(head["ranking"]), "bed_target_s": target,
               "jobs": [{"job_id": j["job_id"], "seed": j["seed"], "seconds": j["seconds"]} for j in plan["jobs"]],
               "prompt": plan["prompt"]}
    if args.dry_run:
        _print({**summary, "written": None})
        return 0
    plan_sha = write_json_once(out / music.PLAN_FILE, plan, mode="ascii")
    write_json_once(out / PICK_FILE, {**head, "generator": generator, "skipped_generators": skipped, "plan_sha256": plan_sha,
                                      "status": "GENERATION_PLANNED"}, mode="ascii", stamp=True)
    summary.update(written=str(out / music.PLAN_FILE), pick_receipt=str(out / PICK_FILE), plan_sha256=plan_sha,
                   next=f"jjv audio music adopt --episode {args.episode} --out {out} --execute")
    if not args.execute:
        _print(summary)
        return 0
    result = _adopt(args, config, base, pick_recipe, out, lib_dir, plan, recipe)
    _print({**summary, **result})
    return 0 if result["ok"] else 1


def _adopt(args, config: ResolvedConfig, base, pick_recipe, out: Path, lib_dir: Path, plan: dict, recipe) -> dict:
    ffmpeg = _ffmpeg(args.ffmpeg)
    gate = vocalgate.resolve(config.machine, base.data["vocal_gate"], args.vocal_gate_command)
    if gate is None:
        raise Refused("no vocal separator configured: set machine.audio.vocal_gate.command or pass --vocal-gate-command "
                      "(without a gate no bed can enter the library)")
    states = {j["job_id"]: jobs.job_state(out, j) for j in plan["jobs"]}
    if any(s != "COMPLETED" for s in states.values()):
        if not args.execute:
            return {"ok": True, "adopted": False, "job_states": states, "message": "jobs not COMPLETED: re-run with --execute (GPU)"}
        musicpick_gen.execute(config, out, plan, recipe, timeout_seconds=args.timeout_seconds,
                              emit=lambda m: print(m, flush=True))
    finalize_path = out / music.FINALIZE_FILE
    finalized = read_json(finalize_path) if finalize_path.is_file() else musicpick_gen.finalize_generation(
        config, out, plan, recipe, ffmpeg=ffmpeg, gate=gate, vocal_runner=subprocess.run)
    step = pick_recipe.data["vocal_step"]
    settings = vocalstrip.settings_from(step, args.demucs_python, gate.command, ffmpeg)
    receipt = musicpick_adopt.adopt(
        out=out, plan=plan, recipe=recipe, finalized=finalized, lib_dir=lib_dir, film=config.episode["film_id"],
        domain_id=config.domain["domain_id"], spec=step, gate=gate, settings=settings, ffmpeg=ffmpeg,
        take_id=getattr(args, "take", None), id_prefix=pick_recipe.data["library"]["id_prefix"],
        registry_schema=pick_recipe.data["library"]["registry_schema"],
        energy=(plan.get("brief_evidence") or {}).get("overall_energy"))
    registered = receipt["status"] == "BED_REGISTERED"
    return {"ok": registered, "adopted": registered, "adopt_status": receipt["status"], "bed_id": receipt.get("bed_id"),
            "music_receipt": str(out / musicpick_adopt.ADOPT_FILE), "first_gate": receipt["first_gate"],
            "final_gate": receipt.get("final_gate") and {k: receipt["final_gate"].get(k) for k in (
                "status", "vocals_relative_db", "windows_over_limit", "vocals_rms_dbfs")},
            "residue": (receipt.get("strip") or {}).get("residue"), "registry": receipt.get("registry")}


def run_adopt(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    base, _ = resolve_recipe(config, "audio-music", args.recipe)
    pick_recipe = musicpick.load_pick_recipe(config, args.pick_recipe)
    out = Path(args.out)
    plan = music.load_plan(out)
    recipe = musicpick_gen.rebuild(pick_recipe, base, plan)
    result = _adopt(args, config, base, pick_recipe, out, library_dir(config, args.library), plan, recipe)
    _print(result)
    return 0 if result["ok"] else 1


def run_music_action(args: argparse.Namespace) -> int | None:
    """Dispatch hook for ``cli.run_audio``: the exit code for ``pick``/``adopt``, None for any other action."""
    if args.verb == "music" and args.action == "pick":
        return run_pick(args)
    if args.verb == "music" and args.action == "adopt":
        return run_adopt(args)
    return None

