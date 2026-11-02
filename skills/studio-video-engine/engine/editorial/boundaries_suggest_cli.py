"""``editorial boundaries suggest | preview | swap`` (read-only on the episode; outputs go to ``--out``).

Standalone entry points (``bin/jjv.py`` is owned elsewhere; ``CLI-PATCH-transitions.md`` has the wiring lines)::

    python -I .agents/skills/studio-video-engine/engine/editorial/boundaries_suggest_cli.py suggest --episode E --out DIR
    python -I ... preview --episode E --boundary T1310 --presets push,dip,cut --out GALLERY-DIR
    python -I ... swap --episode E --boundaries B --boundary T1310 --preset push --out WORKSPACE

``register(verbs)`` / ``run_boundaries(args)`` expose the same as ``jjv editorial boundaries ...``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __name__ == "__main__":  # python -I drops the script directory: add the skill root explicitly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.config.loader import SKILL_ROOT  # noqa: E402
from engine.config.schema import validate  # noqa: E402
from engine.core.errors import EngineError, Refused, exit_code_for  # noqa: E402
from engine.core.io import pretty_json, read_json, write_once  # noqa: E402
from engine.editorial import boundaries_suggest as bs  # noqa: E402
from engine.editorial import boundaries_suggest_parity as parity  # noqa: E402
from engine.editorial import boundaries_write  # noqa: E402
from engine.qa.scope import resolve_episode_or_uncertain  # noqa: E402

SHOTS_SCHEMA = SKILL_ROOT / "schemas" / "shots.schema.json"
SUGGESTED_NAME = "boundaries-suggested.json"


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--shots", help="shots.json (jjv/shots/v1); default: the episode's own shots")
    parser.add_argument("--boundaries", help="declared boundaries.json (continuity, framing, motivation, tail_clip, graphics)")
    parser.add_argument("--ffmpeg", help="ffmpeg executable (default: PATH)")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH",
                        help="a file or folder outside the episode root that clips may reference; repeatable")


def register(verbs) -> None:
    """Add the ``boundaries`` verb (``suggest`` / ``preview`` / ``swap``) to the ``editorial`` stage."""
    boundaries = verbs.add_parser("boundaries", help="transitions chosen by rule from the shots; preview; swap")
    actions = boundaries.add_subparsers(dest="action", required=True)
    suggest = actions.add_parser("suggest", help="measure framing on the source clips and suggest a preset per boundary")
    _common(suggest)
    suggest.add_argument("--out", required=True, help="folder for boundaries-suggested.json (write-once)")
    suggest.add_argument("--compare-config", help="review config whose motion.transitions are the approved types")
    preview = actions.add_parser("preview", help="render a short window per candidate preset + a contact page")
    _common(preview)
    preview.add_argument("--boundary", required=True, help="frame number or id (T1310)")
    preview.add_argument("--presets", required=True, help="comma list, e.g. push,dip,cut or whip:direction=-1")
    preview.add_argument("--out", required=True, help="gallery folder (clips/, posters/, index.html, preview-record.json)")
    preview.add_argument("--context-frames", type=int, default=24, help="delivery frames shown each side of the cut")
    boundaries_write.register(actions)
    swap = actions.add_parser("swap", help="change one boundary's preset (versioned boundaries.json + segments to redo)")
    _common(swap)
    swap.add_argument("--boundary", required=True, help="frame number or id (T1310)")
    swap.add_argument("--preset", required=True, help="preset name, with options: whip:direction=-1")
    swap.add_argument("--out", required=True, help="workspace folder (versions/, boundaries.json, swap-log.json)")
    swap.add_argument("--motivation", help="written motivation of the new row (default: swap note + the old text)")
    swap.add_argument("--dry-run", action="store_true", help="validate and list the segments; write nothing")


def load_inputs(args: argparse.Namespace) -> tuple:
    """``(config, shots, declared, hashes, declared_path)`` with every file validated before use."""
    config = resolve_episode_or_uncertain(args.episode)
    shots_path = Path(args.shots) if args.shots else None
    shots = config.shots
    if shots_path:
        document = read_json(shots_path)
        errors = validate(document, read_json(SHOTS_SCHEMA), label="shots")
        if errors:
            raise Refused("shots.json is invalid: " + "; ".join(errors))
        shots = document["shots"]
    declared_path = Path(args.boundaries) if args.boundaries else None
    declared = read_json(declared_path) if declared_path else None
    hashes = bs.input_hashes(shots_path, declared_path)
    hashes["shots_sha256"] = hashes["shots_sha256"] or config.sources.get("shots")
    return config, shots, declared, hashes, declared_path


def _context(args: argparse.Namespace, config, shots, declared) -> dict:
    return bs.make_context(config, shots, declared, ffmpeg=args.ffmpeg,
                           allow=tuple(Path(item) for item in args.allow_outside))


def table_text(document: dict) -> str:
    """The suggestion as a plain table (id, ncc, framing, rule, choice, tail, alternatives)."""
    lines = [f"{'id':<7}{'from -> to':<24}{'ncc':>7}  {'framing':<13}{'rule':<22}{'chosen':<13}{'tail':<5} alternatives"]
    for it in document["boundaries"]:
        if it["kind"] != "picture":
            continue
        ncc, chosen = it["measured"]["ncc"], it["chosen"]
        shown = "n/a" if ncc is None else f"{ncc:.3f}"
        lines.append(f"{it['id']:<7}{it['from'] + ' -> ' + it['to']:<24}{shown:>7}  {it['framing']['framing']:<13}"
                     f"{it['rule']:<22}{chosen['type']:<13}{'yes' if chosen['tail']['needed'] else '-':<5} "
                     + ",".join(o["type"] for o in it["alternatives"]))
    return "\n".join(lines)


def run_suggest(args: argparse.Namespace) -> int:
    config, shots, declared, hashes, _ = load_inputs(args)
    document = bs.suggest(config, shots, declared, ctx=_context(args, config, shots, declared), hashes=hashes)
    if args.compare_config:
        document["parity"] = parity.compare(document, Path(args.compare_config))
    target = Path(args.out) / SUGGESTED_NAME
    digest = write_once(target, pretty_json(document, mode="utf8"))
    print(table_text(document), file=sys.stderr)
    print(json.dumps({"ok": True, "out": str(target), "sha256": digest, "summary": document["summary"],
                      "warnings": document["warnings"], "parity": (document.get("parity") or {}).get("picture")},
                     indent=2, ensure_ascii=True))
    return 0


def run_preview(args: argparse.Namespace) -> int:
    from engine.editorial import boundaries_preview as bp  # noqa: PLC0415 - numpy/ffmpeg only when previewing
    from engine.editorial.boundaries_suggest_measure import find_ffmpeg  # noqa: PLC0415
    config, shots, declared, hashes, _ = load_inputs(args)
    ctx = _context(args, config, shots, declared)
    document = bs.suggest(config, shots, declared, ctx=ctx, hashes=hashes)
    wanted = str(args.boundary).strip()
    item = next((it for it in document["boundaries"] if wanted in (it["id"], str(it["frame"]))), None)
    if item is None or item["kind"] != "picture" or item["rule"] == "R1_carry":
        raise Refused(f"boundary {args.boundary!r} is not a picture cut of this episode (a carry takes no transition)")
    a, b = (next(s for s in shots if s["shot"] == item[k]) for k in ("from", "to"))
    hint = (f"jjv editorial boundaries swap --episode {args.episode} --boundaries "
            + (args.boundaries or "<boundaries.json>") + " --out <workspace>")
    record = bp.preview(ctx, item, bp.parse_tokens(args.presets), Path(args.out), find_ffmpeg(args.ffmpeg), a, b,
                        args.context_frames, hint)
    rows = [{**{k: c[k] for k in ("preset", "status", "frames", "render_seconds", "clip", "reason") if k in c},
             "verdict": c["verdict"]["text"]} for c in record["candidates"]]
    print(json.dumps({"ok": True, "gallery": str(Path(args.out) / "index.html"), "boundary": item["id"],
                      "measured_ncc": item["measured"]["ncc"], "rule": item["rule"],
                      "render_seconds_total": record["render_seconds_total"], "candidates": rows},
                     indent=2, ensure_ascii=True))
    return 0


def run_swap(args: argparse.Namespace) -> int:
    from engine.editorial import presets_swap  # noqa: PLC0415
    if not args.boundaries:
        raise Refused("swap needs --boundaries (the declared table to version)")
    config, shots, declared, _hashes, declared_path = load_inputs(args)
    summary = presets_swap.swap(_context(args, config, shots, declared), shots, config, declared_path, Path(args.out),
                                args.boundary, args.preset, motivation=args.motivation, dry_run=args.dry_run)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


def run_boundaries(args: argparse.Namespace) -> int:
    """One JSON document on stdout; exit 0 ok, 1 a rule failed (nothing written), 2 an unreadable input."""
    return {"suggest": run_suggest, "preview": run_preview, "swap": run_swap,
            "write": boundaries_write.run_write}[args.action](args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="boundaries_suggest_cli", description=__doc__.split("\n")[0])
    register(parser.add_subparsers(dest="verb", required=True))
    try:
        return run_boundaries(parser.parse_args(["boundaries", *(argv if argv is not None else sys.argv[1:])]))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return exit_code_for(error)


if __name__ == "__main__":
    sys.exit(main())
