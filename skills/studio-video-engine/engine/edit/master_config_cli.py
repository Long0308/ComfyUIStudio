"""``jjv edit master-config``: engine build folder + episode contract + 4K receipts -> master-config.json (write-once).

Inputs are data only: the folder ``jjv editorial build-config`` wrote (``review-config.json`` + ``events.json``), the episode
(``--episode``: path, root or slug, resolved to its contract), the SeedVR2 runs folder (``runs/<shot>/shot.json``), an optional seam-variant
file and the tail map.  Exit 0 = written (``master_ready`` true, or ``--preview``), 1 = refused (every missing input named, nothing written),
2 = unreadable input.  Wiring into ``jjv edit`` is in ``CLI-PATCH-master-config.md``; until then the verb runs standalone:

    python -I .agents/skills/studio-video-engine/engine/edit/master_config_cli.py --episode E --build DIR [--runs R] [--tail-map F] ...

CPU only: no GPU, no render.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: `python -I` drops the script directory, so add the skill root and re-enter through the package
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from engine.edit.master_config_cli import main as _main
    raise SystemExit(_main())

from ..core.errors import Refused, Uncertain
from ..core.io import pretty_json, read_json, sha256_file, write_once
from . import master_config as mc

REVIEW_NAME, EVENTS_NAME, OUT_NAME = "review-config.json", "events.json", "master-config.json"
VERB = "master-config"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug (gives the contract: fps, frames, master size)")
    parser.add_argument("--build", required=True, help="folder `jjv editorial build-config` wrote (review-config.json + events.json)")
    parser.add_argument("--runs", help="SeedVR2 plan `runs` folder (runs/<shot>/shot.json attests each final shot core)")
    parser.add_argument("--tail-map", help="MASTER-TAIL-MAP.json of `jjv seedvr2 tails assemble` (the 4K tail cores)")
    parser.add_argument("--variants", help="JSON {shot: {path, sha256, receipt_path, receipt_sha256}} of seam-blend (hf8) variants; relative paths resolve beside it")
    parser.add_argument("--preview", action="store_true", help="bind missing sources to the review clips (master_ready false): stills and ranges only")
    parser.add_argument("--approvals", action="append", default=[], metavar="DIR",
                        help="folder(s) with <shot>/acceptance/*.json user approvals (a final master of a final_gate domain needs them)")
    parser.add_argument("--out", help=f"output file (default <build>/{OUT_NAME}); written once, never overwritten")


def register_verb(verbs) -> None:
    """Add ``master-config`` to the ``edit`` stage's verb sub-parsers (called from ``segments_edit_cli.register_cli``)."""
    add_arguments(verbs.add_parser(VERB, help="engine build + contract + 4K receipts -> master-config.json for the master adapter (CPU)"))


def _problems(build: Path, runs: Path | None, tail_map: Path | None, variants: Path | None) -> list[str]:
    missing = [f"{label} missing: {path}" for label, path in ((REVIEW_NAME, build / REVIEW_NAME), (EVENTS_NAME, build / EVENTS_NAME)) if not path.is_file()]
    for label, path, needed in (("--runs", runs, runs is not None and not runs.is_dir()), ("--tail-map", tail_map, tail_map is not None and not tail_map.is_file()),
                                ("--variants", variants, variants is not None and not variants.is_file())):
        if needed:
            missing.append(f"{label} does not exist: {path}")
    return missing


def apply_final_gate(domain, document: dict, roots) -> dict:
    """Where the domain has ``final_gate``: a final (build_mode master) config needs every bound 4K core approved;
    stamps ``final_gate.status`` so ``edit master-render`` can verify it.  Other domains: the document is unchanged."""
    from ..policy import final_gate
    if not final_gate.enabled(domain):
        return document
    if document.get("build_mode") != "master":
        return {**document, "final_gate": {"status": "preview"}}
    shots = [(str(seg.get("shot")), [seg.get("final_sha256")]) for part in document.get("dialogue") or []
             for seg in part.get("segments") or []]
    rows = final_gate.check_shots(domain, shots, roots, verb="edit master-config")
    return {**document, "final_gate": {"status": "approved", "approvals": rows}}


def produce(config, args: argparse.Namespace) -> dict:
    """The master-config document for an already resolved episode (pure apart from reading the named files)."""
    build, runs = Path(args.build), Path(args.runs) if args.runs else None
    tail_map, variants_file = Path(args.tail_map) if args.tail_map else None, Path(args.variants) if args.variants else None
    review, events = read_json(build / REVIEW_NAME), read_json(build / EVENTS_NAME)
    contract = mc.contract_from_config(config)
    variants = read_json(variants_file) if variants_file else None
    inputs = {"review_config_sha256": sha256_file(build / REVIEW_NAME), "events_sha256": sha256_file(build / EVENTS_NAME),
              "config_sha256": config.config_sha256, "runs": str(runs) if runs else None,
              "tail_map_sha256": sha256_file(tail_map) if tail_map else None, "variants_sha256": sha256_file(variants_file) if variants_file else None}
    document = mc.build_master_config(review, events, contract, episode_root=Path(config.episode_root), runs_dir=runs, tail_map=tail_map, variants=variants,
                                      variants_base=variants_file.parent if variants_file else None, inputs=inputs, preview=args.preview)
    return apply_final_gate(getattr(config, "domain", None), document, getattr(args, "approvals", None) or [])


def _resolve_all(args: argparse.Namespace, resolve):
    """The resolved episode, after naming EVERY missing input at once (build files, named paths and an unresolvable episode)."""
    paths = [Path(item) if item else None for item in (args.runs, args.tail_map, args.variants)]
    missing = _problems(Path(args.build), *paths)
    config = None
    try:
        config = resolve(args.episode)
    except (Refused, Uncertain) as error:
        if not missing and isinstance(error, Uncertain):
            raise
        missing.append(f"episode {args.episode!r} does not resolve: {error}")
    if missing:
        raise Refused("master-config inputs missing: " + "; ".join(missing))
    return config


def run_master_config(args: argparse.Namespace, *, resolve=None) -> int:
    """One JSON summary on stdout.  ``resolve`` is injectable (tests); the default is the engine's episode resolver."""
    try:
        if resolve is None:
            from ..qa.scope import resolve_episode_or_uncertain as resolve
        document = produce(_resolve_all(args, resolve), args)
        out = Path(args.out) if args.out else Path(args.build) / OUT_NAME
        digest = write_once(out, pretty_json(document, mode="utf8"))
    except Uncertain as error:
        print(f"unreadable input: {error}", file=sys.stderr)
        return 2
    except Refused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "master_ready": document["master_ready"], "build_mode": document["build_mode"], "episode_id": document["episode_id"],
                      "out": str(out), "sha256": digest, "missing_shots": document["missing_shots"], "missing_tails": document["missing_tails"]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"jjv edit {VERB}")
    add_arguments(parser)
    return run_master_config(parser.parse_args(sys.argv[1:] if argv is None else argv))
