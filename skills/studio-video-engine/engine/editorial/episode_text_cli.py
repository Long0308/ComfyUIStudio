"""CLI glue for ``jjv text build|diff`` (the generated episode-text.json and its parity diff).

0 ok, 1 a rule failed (nothing written), 2 unreadable input.  CPU only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import REPO_ROOT
from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_bytes, write_once
from . import episode_text as text
from . import icons as reg
from .icons_cli import declared, episode_context

OUTPUT_NAME = "episode-text.json"


def register_cli(stages: Any) -> None:
    group = stages.add_parser("text", help="episode text for the kit, generated from the locked script")
    verbs = group.add_subparsers(dest="verb", required=True)
    build = verbs.add_parser("build", help="locked script + icon registry -> episode-text.json (write-once)")
    build.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    build.add_argument("--out", required=True, help="output folder for episode-text.json")
    build.add_argument("--script", default=None, help="locked script (default: the one the shot pack records)")
    build.add_argument("--shot-pack", default=None, help="shot pack (default episode.files.shot_pack); proves the script is locked")
    build.add_argument("--registry", default=None, help="icons.json (default episode.files.icon_registry)")
    build.add_argument("--copy", default=None, help="jjv/episode-copy/v1 file for copy the script does not carry")
    build.add_argument("--music", default=None, help="episode-relative music stem (render parameter)")
    build.add_argument("--ambience", default=None, help="episode-relative ambience stem (render parameter)")
    build.add_argument("--ending-params", default=None, help="JSON object copied to `ending` (disc slide, music tail)")
    build.add_argument("--recipe", default=None, help="episode-text recipe (default recipes/editorial/episode-text-v001.json)")
    build.add_argument("--dry-run", action="store_true")
    diff = verbs.add_parser("diff", help="field-by-field parity of a generated file against a reference file")
    diff.add_argument("--generated", required=True)
    diff.add_argument("--reference", required=True)
    diff.add_argument("--ignore", action="append", default=[], metavar="PATH", help="dotted path to skip, e.g. note")


def _print(summary: dict) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def _script_path(args: argparse.Namespace, pack: dict | None, episode: dict, root: Path) -> Path:
    if args.script:
        return Path(args.script)
    declared = declared(episode, root, "script")
    if declared is not None:
        if not declared.is_file():
            raise Refused(f"episode.files.script not found: {declared}")
        return declared
    recorded = ((pack or {}).get("source_provenance") or {}).get("script_path")
    if not recorded:
        raise Refused("no script: pass --script, set episode.files.script, or use a shot pack that records "
                      "source_provenance.script_path")
    found = REPO_ROOT / recorded
    if not found.is_file():
        raise Refused(f"the shot pack records {recorded}, which does not exist under {REPO_ROOT}")
    return found


def run_build(args: argparse.Namespace) -> int:
    root, episode = episode_context(args.episode)
    pack_path = Path(args.shot_pack) if args.shot_pack else declared(episode, root, "shot_pack")
    pack = read_json(pack_path) if pack_path else None
    registry_path = Path(args.registry) if args.registry else declared(episode, root, "icon_registry")
    if registry_path is None:
        raise Refused("no registry: pass --registry (episode.files.icon_registry is not declared)")
    script_path = _script_path(args, pack, episode, root)
    if pack is not None:
        text.check_locked(script_path, pack)
    recipe, _ = text.load_recipe(Path(args.recipe) if args.recipe else None)
    script, registry = read_json(script_path), reg.load_registry(registry_path)
    ending = read_json(Path(args.ending_params)) if args.ending_params else None
    doc, missing = text.build_text(
        script, registry, recipe, copy=text.load_copy(Path(args.copy) if args.copy else None),
        opening=text.opening_from_pack(pack, root, recipe, required=False) if pack else None,
        music=text.bind_asset(root, args.music, "music stem") if args.music else None,
        ambience=text.bind_asset(root, args.ambience, "ambience stem") if args.ambience else None, ending=ending)
    payload = pretty_json(doc, mode="utf8")
    target = Path(args.out) / OUTPUT_NAME
    if not args.dry_run:
        write_once(target, payload)
    _print({"ok": True, "dry_run": args.dry_run, "output": str(target), "sha256": sha256_bytes(payload),
            "registry_version": registry["version"], "script": script_path.name, "shots": len(doc["shotVi"]),
            "cards": len(doc["cards"]), "missing": missing})
    return 0


def run_diff(args: argparse.Namespace) -> int:
    report = text.diff_documents(read_json(Path(args.generated)), read_json(Path(args.reference)), ignore=tuple(args.ignore))
    _print(report)
    return 0 if report["diff_count"] == 0 else 1


def run_text(args: argparse.Namespace) -> int:
    return {"build": run_build, "diff": run_diff}[args.verb](args)
