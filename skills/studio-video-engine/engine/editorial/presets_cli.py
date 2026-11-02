"""``editorial presets``: the transition preset library and what each boundary's tail handle allows.

Read-only: it counts native clip frames (ffprobe) and prints JSON; it never renders, requests GPU work
or writes a file.  Two modes:

* ``list`` / ``show NAME``: the catalog as one row per preset, or one preset in full (frames, window, tail and
  params resolved at their defaults; the names ``push`` / ``dip`` / ``flash`` resolve to their presets);
* no ``--episode``: the catalog (name, category, labels, frames rule, params, tail, safe_for, status);
* ``--episode`` + ``--boundaries``: per boundary its tail handle and, for EVERY ready preset, whether it
  is ``available`` on that handle (``needs_tail_frames`` / ``have_native_frames`` / ``max_frames`` /
  ``reason``) and ``eligible`` by class, continuity and boundary kind.  ``--boundary 1010`` or ``T1010``
  narrows it to one boundary.  ``--word-timing`` is optional (the shot grid is read from shots.json).

Standalone entry points (``bin/jjv.py`` is owned elsewhere)::

    python -I .agents/skills/studio-video-engine/engine/editorial/presets_cli.py --episode <episode> \\
        --boundaries <boundaries.json> [--boundary 1010] [--allow-outside <logo>]
    python -m engine.editorial.presets_cli ...        # from the skill root (without -I)

``register(verbs)`` / ``run_presets(args)`` let ``bin/jjv.py`` expose the same thing as
``jjv editorial presets`` with one import and one dispatch line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.core.errors import EngineError, exit_code_for  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.editorial import build, presets  # noqa: E402
from engine.editorial.boundaries_suggest_parity import normalise  # noqa: E402
from engine.qa.scope import resolve_episode_or_uncertain  # noqa: E402

ALIASES = {"flash": "dip_white"}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", nargs="?", choices=("list", "show"), help="list: one row per preset; show NAME: one in full")
    parser.add_argument("name", nargs="?", help="preset name for show (push, dip, flash are accepted aliases)")
    parser.add_argument("--episode", help="episode.json path, episode root or slug (omit for the catalog only)")
    parser.add_argument("--boundaries", help="boundaries.json of the episode")
    parser.add_argument("--word-timing", help="word timing document (optional)")
    parser.add_argument("--boundary", help="one boundary: its frame number or id (T1010)")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH",
                        help="a file or folder outside the episode root that inputs may reference; repeatable")


def register(verbs) -> None:
    """Add the ``presets`` verb to the ``editorial`` stage's verb parsers."""
    add_arguments(verbs.add_parser("presets", help="transition presets + per-boundary tail feasibility (read-only)"))


def catalog_summary() -> dict:
    out = []
    for name, preset in presets.presets().items():
        out.append({"name": name, "status": preset.status, "category": preset.category, "label": preset.label,
                    "renders_as": preset.renders_as, "shows_both": preset.shows_both,
                    "tail_frames": preset.tail_frames, "frames": preset.frames, "direction": preset.direction,
                    "params": preset.params, "safe_for": preset.safe_for, "legacy": preset.legacy,
                    "when": preset.when})
    return {"schema": presets.catalog()["schema"], "categories": presets.catalog()["categories"], "presets": out}


def list_rows() -> list[dict]:
    return [{"name": n, "status": p.status, "category": p.category, "label": p.label, "renders_as": p.renders_as,
             "frames": presets.default_frames(p), "frames_rule": p.frames, "direction": p.direction,
             "tail_frames": p.tail_frames, "shows_both": p.shows_both, "safe_for": p.safe_for,
             "when": p.when["en"]} for n, p in presets.presets().items()]


def show_preset(name: str) -> dict:
    """One preset in full, with the values a boundary row gets when it only names the preset."""
    key = ALIASES.get(name, normalise(name))
    data = presets.catalog()["presets"].get(key)
    if data is None:
        raise Refused(f"unknown transition preset {name!r}; known: {', '.join(presets.catalog()['presets'])}")
    preset = presets.Preset(key, data)
    out = {"name": key, "asked_as": name, **data}
    if preset.ready:
        frames = presets.default_frames(preset)
        out["defaults"] = {"frames": frames, "params": presets.resolve_params(preset, None),
                           "window_from_cut": list(presets.window(preset, 0, frames, presets.resolve_params(preset, None))),
                           "tail_output_frames": presets.tail_frames(preset, frames),
                           "legal_frames": presets.candidate_frames(preset),
                           "placement": presets.placement_text(preset, 0)}
    return out


def run_presets(args: argparse.Namespace) -> int:
    """One JSON document on stdout; exit 0 ok, 1 a rule failed, 2 an unreadable input."""
    if args.action == "list":
        print(json.dumps({"presets": list_rows()}, indent=2, ensure_ascii=True))
        return 0
    if args.action == "show":
        if not args.name:
            raise Refused("presets show needs a preset name")
        print(json.dumps(show_preset(args.name), indent=2, ensure_ascii=True))
        return 0
    if not args.episode:
        print(json.dumps(catalog_summary(), indent=2, ensure_ascii=True))
        return 0
    if not args.boundaries:
        raise SystemExit("--boundaries is required with --episode")
    config = resolve_episode_or_uncertain(args.episode)
    report = build.feasibility_report(
        config, Path(args.boundaries), Path(args.word_timing) if args.word_timing else None,
        allow_outside=tuple(Path(item) for item in args.allow_outside), only=args.boundary)
    print(json.dumps({"ok": True, **report}, indent=2, ensure_ascii=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="presets_cli", description=__doc__.split("\n")[0])
    add_arguments(parser)
    try:
        return run_presets(parser.parse_args(argv))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)


if __name__ == "__main__":
    sys.exit(main())
