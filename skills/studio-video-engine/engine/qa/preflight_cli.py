"""CLI glue of ``jjv qa preflight`` (see ``CLI-PATCH-preflight.md`` for the lines root adds to ``bin/jjv.py`` and
``engine/qa/cli.py``).  Also runnable on its own: ``python -I engine/qa/preflight_cli.py --config C``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.errors import EngineError, Refused, Uncertain, exit_code_for  # noqa: E402
from engine.config import rules  # noqa: E402
from engine.core.provenance import stamp  # noqa: E402
from engine.core.io import read_json, sha256_file, write_json_atomic  # noqa: E402
from engine.qa import preflight, preflight_recipe, review_recipe  # noqa: E402
from engine.qa.scope import resolve_episode_or_uncertain  # noqa: E402
from engine.seedvr2.seam_media import find_ffmpeg  # noqa: E402
from engine.timing.recipe import load_timing_recipe, resolve_recipe  # noqa: E402


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="review config (engine-built or hand-built)")
    parser.add_argument("--timing", default=None, help="WORD-TIMING.json for Q1 (default: the config's word_timing.path)")
    parser.add_argument("--icons", default=None, help="folder of icon PNGs, the fallback for an event whose icon_path is missing")
    parser.add_argument("--events", default=None, help="engine events.json (icon_events) instead of the config's own icons")
    parser.add_argument("--episode", default=None, help="episode.json path, root or slug: root, fps and timing recipe come from it")
    parser.add_argument("--root", default=None, help="episode root that relative paths are relative to (default: found from "
                                                     "the config, else the config's folder)")
    parser.add_argument("--contract", default=None, help="DELIVERY-CONTRACT.json: master.frames and every section are checked")
    parser.add_argument("--expect-frames", type=int, default=None, help="contract frame count (overrides the config's own)")
    parser.add_argument("--music-receipt", default=None, help="music-finalize.json (vocal-free gate must be PASS)")
    parser.add_argument("--mix-receipt", default=None, help="mix receipt jjv/audio-mix/v1 (music gate, SFX opt-in, brand voice)")
    parser.add_argument("--with-sfx", action="store_true", help="the film opted in to SFX/ambience")
    parser.add_argument("--allow-ungated-music", action="store_true", help="a music bed whose vocal gate is not PASS is a warning")
    parser.add_argument("--require-audio", action="store_true", help="no audio receipt at all is UNCERTAIN instead of SKIPPED")
    parser.add_argument("--checks", default=",".join(preflight.ALL_CHECKS), help="comma list of checks to run")
    parser.add_argument("--layout-same-framing", default=None, metavar="F,F,...",
                        help="boundary frames declared NOT to change layout (a flash there FAILs)")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH", help="a file/folder outside the episode root")
    parser.add_argument("--preflight-recipe", default=None, help="qa preflight recipe JSON (default recipes/qa/preflight-v001.json)")
    parser.add_argument("--review-recipe", default=None, help="qa review recipe JSON (default recipes/qa/review-gates-v001.json)")
    parser.add_argument("--timing-recipe", default=None, help="timing/<id> (default: episode's, else the preflight recipe's)")
    parser.add_argument("--ffmpeg", default=None)


def register_preflight(verbs: Any) -> None:
    """Add the ``preflight`` verb to the ``qa`` sub-parsers (call from ``engine/qa/cli.py register_cli``)."""
    parser = verbs.add_parser("preflight", help="every QA check that needs no rendered pixels (Q1, pacing, transitions, "
                                                "icons, audio contract): run before a render is allowed")
    add_arguments(parser)
    parser.add_argument("--out", default=None, help="write the report here (overwritten)")
    parser.add_argument("--json", action="store_true", help="JSON only: no summary on stderr")


def frames_of(text: str | None) -> frozenset[int]:
    try:
        return frozenset(int(t) for t in (text or "").split(",") if t.strip())
    except ValueError as error:
        raise Refused(f"--layout-same-framing must be a comma list of integer frames: {error}") from error


def find_root(config_path: Path) -> Path:
    """The nearest folder above the config that holds ``engine/episode.json``, else the config's own folder."""
    for folder in Path(config_path).resolve().parents:
        if (folder / "engine" / "episode.json").is_file():
            return folder
    return Path(config_path).resolve().parent


def domain_limits(domain: dict) -> dict:
    """Section floors/ceilings the domain grants (``delivery.sections``, ``delivery.end_card``); absent keys are omitted."""
    delivery = domain.get("delivery") or {}
    sections, end = delivery.get("sections") or {}, delivery.get("end_card") or {}
    pairs = {"card_min": (sections.get("vocab_card") or {}).get("min"), "card_max": (sections.get("vocab_card") or {}).get("max"),
             "logo_hold_min": (sections.get("logo_hold") or {}).get("min"), "logo_hold_max": (sections.get("logo_hold") or {}).get("max"),
             "end_card_min": end.get("frames_min"), "end_card_max": end.get("frames_max")}
    return {k: v for k, v in pairs.items() if isinstance(v, int) and not isinstance(v, bool)}


def prepare(args: argparse.Namespace) -> dict:
    """Everything ``run_preflight`` needs from the arguments (shared with ``qa gate``)."""
    config_path = Path(args.config)
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise Refused(f"{config_path.name}: review config must be a JSON object")
    recipe, recipe_sha = review_recipe.load_recipe(Path(args.review_recipe) if args.review_recipe else None)
    pre, pre_sha = preflight_recipe.load_recipe(Path(args.preflight_recipe) if args.preflight_recipe else None)
    root = Path(args.root) if args.root else find_root(config_path)
    limits, episode_total = None, None
    if args.episode:
        episode = resolve_episode_or_uncertain(args.episode)
        limits = domain_limits(episode.domain)
        episode_total = rules.timeline_frames(episode.episode, episode.domain)["total_frames"]
        root = Path(args.root) if args.root else Path(episode.episode_root)
        timing_recipe, _origin = resolve_recipe(episode, args.timing_recipe)
    else:
        timing_recipe = load_timing_recipe(args.timing_recipe or pre["timing"]["recipe_id"])
    try:
        ffmpeg = find_ffmpeg(args.ffmpeg)
    except Refused as error:
        raise Uncertain(str(error)) from error
    contract = read_json(Path(args.contract)) if args.contract else None
    return dict(
        config=config, config_sha256=sha256_file(config_path), root=root, recipe=recipe, recipe_sha256=recipe_sha, pre=pre,
        pre_sha256=pre_sha, timing_recipe=timing_recipe, ffmpeg=ffmpeg, timing=Path(args.timing) if args.timing else None,
        events=read_json(Path(args.events)) if args.events else None, icons_dir=Path(args.icons) if args.icons else None,
        contract=contract, expect_frames=args.expect_frames,
        music_receipt=Path(args.music_receipt) if args.music_receipt else None,
        mix_receipt=Path(args.mix_receipt) if args.mix_receipt else None, with_sfx=args.with_sfx,
        allow_ungated=args.allow_ungated_music, require_audio=args.require_audio,
        allow=tuple(Path(p) for p in args.allow_outside), declared_same_framing=frames_of(args.layout_same_framing),
        checks=tuple(c.strip().upper() for c in args.checks.split(",") if c.strip()), limits=limits, episode_total=episode_total)


def summary(report: dict) -> str:
    lines = [f"PREFLIGHT {report['verdict']}  (exit {report['exit_code']})  render {'ALLOWED' if report['render_allowed'] else 'REFUSED'}"
             f"  {report['timing_s']['total']} s"]
    for name, gate in report["gates"].items():
        lines.append(f"  {name}: {gate['status']}  {report['timing_s'].get(name, '-')} s")
        lines += [f"      - {text}" for text in gate.get("failures", [])[:12]]
    lines += [f"  warning: {text}" for text in report["warnings"]]
    return "\n".join(lines)


def run_qa_preflight(args: argparse.Namespace) -> int:
    """One JSON report on stdout; exit 0 PASS, 1 a check FAILs (or a rule is violated), 2 uncertain/unreadable."""
    report = preflight.run_preflight(**prepare(args))
    report = stamp(report)  # the printed report and the file carry the same engine_tree_sha256 header
    if args.out:
        write_json_atomic(Path(args.out), report, mode="ascii")
    if not args.json:
        print(summary(report), file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return report["exit_code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa-preflight", description=__doc__)
    add_arguments(parser)
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", action="store_true")
    try:
        return run_qa_preflight(parser.parse_args(argv))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)
    except Exception as error:  # noqa: BLE001 - the CLI contract is "JSON + exit 2", not a traceback
        print(json.dumps({"ok": False, "error": f"{type(error).__name__}: {error}"}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
