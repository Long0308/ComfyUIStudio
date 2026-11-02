"""CLI glue for ``jjv icons build|validate|set`` (T-E44).  One JSON summary on stdout, engine exit codes.

0 ok, 1 a rule failed (nothing written), 2 unreadable input.  CPU only, no network.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..config.loader import find_episode_file
from ..core.errors import Refused
from ..core.io import read_json
from ..seedvr2.seam_media import find_ffmpeg
from . import icons as reg
from . import icons_swap as swap
from .icons_build import build_registry, load_attributes
from .icons_check import validate_registry


def episode_context(ref: str) -> tuple[Path, dict]:
    """(episode root, episode.json) without resolving machine/domain (this stage needs neither)."""
    episode_file = find_episode_file(ref)
    return episode_file.parent.parent, read_json(episode_file)


def declared(episode: dict, root: Path, key: str) -> Path | None:
    """An ``episode.files.<key>`` path (engine-relative like the voice documents), or None."""
    value = (episode.get("files") or {}).get(key)
    return Path(root) / "engine" / value if isinstance(value, str) and value else None


def register_cli(stages: Any) -> None:
    icons = stages.add_parser("icons", help="icon registry: one icon per spoken word, as data (T-E44)")
    verbs = icons.add_subparsers(dest="verb", required=True)
    build = verbs.add_parser("build", help="vocabulary asset manifest + script -> icons.json (version 1)")
    _episode(build)
    build.add_argument("--assets-manifest", required=True, help="vocabulary-vNNN/manifest.json")
    build.add_argument("--script", default=None, help="locked script (default episode.files.script)")
    build.add_argument("--out", required=True, help="registry folder (icons.json + versions/)")
    build.add_argument("--attributes", action="append", default=[], metavar="FILE",
                       help="icon id -> distinguishing attribute ({id: text} or a prompt document); later files win")
    build.add_argument("--allow-shared", action="append", default=[], metavar="ICON_ID",
                       help="mark an icon as an intentional shared icon (otherwise one icon for two words is refused)")
    build.add_argument("--recipe", default=None, help="icons recipe file (default recipes/editorial/icons-v001.json)")
    build.add_argument("--dry-run", action="store_true")
    build.add_argument("--ffmpeg", default=None)
    check = verbs.add_parser("validate", help="the registry gate: coverage, files, sha256, opposite pairs, status")
    _episode(check)
    _registry(check)
    check.add_argument("--script", default=None, help="also check the registry against this script")
    check.add_argument("--require-approved", action="store_true", help="a candidate icon is an error")
    check.add_argument("--recipe", default=None)
    check.add_argument("--ffmpeg", default=None)
    put = verbs.add_parser("set", help="swap one icon image: new registry version + what to re-composite")
    put.add_argument("term", help="icon id, spoken word or card term")
    _episode(put)
    _registry(put)
    put.add_argument("--png", required=True, help="the new icon image (under the episode root)")
    put.add_argument("--attribute", default=None, help="new distinguishing attribute text")
    put.add_argument("--status", choices=("candidate", "approved"), default="candidate")
    put.add_argument("--events", default=None, help="events.json of the current build (icon_events)")
    put.add_argument("--config", default=None, help="review-config.json of the current build (outro cards, cut list)")
    put.add_argument("--segments", default=None, help="segments.json (default: derived from --config)")
    put.add_argument("--recipe", default=None)
    put.add_argument("--dry-run", action="store_true")
    put.add_argument("--ffmpeg", default=None)


def _episode(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")


def _registry(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", default=None, help="icons.json (default episode.files.icon_registry)")


def _registry_path(args: argparse.Namespace, episode: dict, root: Path) -> Path:
    path = Path(args.registry) if args.registry else declared(episode, root, "icon_registry")
    if path is None:
        raise Refused("no registry: pass --registry (episode.files.icon_registry is not declared, see CLI-PATCH-icons-text.md)")
    return path


def _print(summary: dict) -> None:
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))


def run_build(args: argparse.Namespace) -> int:
    root, episode = episode_context(args.episode)
    script_path = Path(args.script) if args.script else declared(episode, root, "script")
    if script_path is None:
        raise Refused("no script: pass --script or declare episode.files.script")
    if not script_path.is_file():
        raise Refused(f"script not found: {script_path}")
    recipe, sha = reg.load_recipe(Path(args.recipe) if args.recipe else None)
    ffmpeg = find_ffmpeg(args.ffmpeg)
    registry = build_registry(
        episode_id=episode["episode_id"], root=root, manifest_path=Path(args.assets_manifest), script_path=script_path,
        recipe=recipe, recipe_sha=sha, ffmpeg=ffmpeg, attributes=load_attributes(*map(Path, args.attributes)),
        allow_shared=tuple(args.allow_shared))
    report = validate_registry(registry, root=root, recipe=recipe, ffmpeg=ffmpeg, script_path=script_path)
    if not report["ok"]:
        _print({"ok": False, "written": None, "errors": report["errors"], "warnings": report["warnings"],
                "pairs": report["pairs"], "summary": report["summary"]})
        return 1
    written = reg.write_registry(Path(args.out), registry, dry_run=args.dry_run)
    _print({"ok": True, "dry_run": args.dry_run, "registry_sha256": registry["sha256"], "outputs": written,
            "warnings": report["warnings"], "pairs": report["pairs"], "summary": report["summary"]})
    return 0


def run_validate(args: argparse.Namespace) -> int:
    root, episode = episode_context(args.episode)
    recipe, _ = reg.load_recipe(Path(args.recipe) if args.recipe else None)
    registry = read_json(_registry_path(args, episode, root))
    script_path = Path(args.script) if args.script else declared(episode, root, "script")
    report = validate_registry(registry, root=root, recipe=recipe, ffmpeg=find_ffmpeg(args.ffmpeg),
                               require_approved=args.require_approved,
                               script_path=script_path if script_path and script_path.is_file() else None)
    _print(report)
    return 0 if report["ok"] else 1


def run_set(args: argparse.Namespace) -> int:
    root, episode = episode_context(args.episode)
    path = _registry_path(args, episode, root)
    recipe, sha = reg.load_recipe(Path(args.recipe) if args.recipe else None)
    registry = reg.load_registry(path)
    old = registry["icons"][swap.resolve_icon_id(registry, args.term)]
    new, change = swap.set_icon(registry, args.term, Path(args.png), root=root, recipe=recipe, recipe_sha=sha,
                                ffmpeg=find_ffmpeg(args.ffmpeg), status=args.status, attribute=args.attribute)
    config, events = swap.read_optional(args.config), swap.read_optional(args.events)
    segments = swap.read_optional(args.segments)
    if segments is None and config is not None:
        segments = swap.segments_from_review_config(config)
    change["recomposite"] = swap.affected(
        old, change["cards"], events=(events or {}).get("icon_events", (config or {}).get("motion", {}).get("icons", [])),
        config=config, segments=segments)
    written = reg.write_registry(path.parent, new, dry_run=args.dry_run)
    _print({"ok": True, "dry_run": args.dry_run, "registry_sha256": new["sha256"], "outputs": written, "change": change})
    return 0


def run_icons(args: argparse.Namespace) -> int:
    return {"build": run_build, "validate": run_validate, "set": run_set}[args.verb](args)
