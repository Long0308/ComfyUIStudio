"""CLI glue for ``jjv timing words`` and ``jjv qa words`` (parsing here, wiring in ``CLI-PATCH.md``).

``timing words`` is CPU only (faster-whisper in the machine's recognition Python, no GPU, no ComfyUI, no
network).  Exit codes: 0 Q1 PASS, 1 Q1 FAIL / rule violation, 2 unreadable or missing input (including a
missing recognition Python/model, an unpairable script word, a document with nothing to test).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from ..core.provenance import stamp
from ..qa.scope import resolve_episode_or_uncertain
from . import gate, run
from .dialogue import parse_lines, parse_vocabulary
from .recipe import optional_block, resolve_recipe
from .recognise import find_model_dir, subprocess_recognizer
from .wavs import bind_wavs


def _episode_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--recipe", default=None, help="timing/<id> (default: episode.timing.recipe, else the one for the domain)")
    parser.add_argument("--allow-outside", action="append", default=[], metavar="PATH",
                        help="a WAV or folder outside the episode root that may be read (repeatable)")


def register_cli(stages: Any) -> None:
    """Register the ``timing`` stage (verb ``words``)."""
    timing = stages.add_parser("timing", help="word timing: recognition + onset rule on every word + Q1 gate (CPU)")
    verbs = timing.add_subparsers(dest="verb", required=True)
    words = verbs.add_parser("words", help="dialogue + receipt WAVs -> WORD-TIMING.json, QA json, receipt (write-once)")
    _episode_args(words)
    words.add_argument("--dialogue", required=True, help="JSON with dialogue[] rows (an engine review config works)")
    words.add_argument("--vocabulary", default=None, help="JSON list [{term, icon, anchor}] (default: dialogue file's 'vocabulary')")
    words.add_argument("--recognised", default=None, help="existing WORD-TIMING json: skip recognition, re-apply the rules")
    words.add_argument("--python", default=None, help="recognition Python with faster_whisper (default machine.timing.python)")
    words.add_argument("--model", default=None, help="faster-whisper model folder (default machine.timing.model_dir)")
    words.add_argument("--no-first-word-rule", action="store_true", help="skip the line-first rule (tests, re-checks)")
    words.add_argument("--out", default=None, help="output folder (write-once files); required unless --dry-run")
    words.add_argument("--dry-run", action="store_true", help="validate inputs and WAV hashes, check the recognition setup, write nothing")


def register_qa_words(qa_verbs: Any) -> None:
    """Add ``words`` to the existing ``qa`` verb group (see CLI-PATCH.md)."""
    parser = qa_verbs.add_parser("words", help="Q1: every word lights at its audible onset (independent detector + negative control)")
    _episode_args(parser)
    parser.add_argument("--timing", required=True, help="WORD-TIMING json to check")
    parser.add_argument("--out", default=None, help="write the receipt here (write-once)")


def _setup(args: argparse.Namespace):
    config = resolve_episode_or_uncertain(args.episode)
    recipe, origin = resolve_recipe(config, args.recipe)
    fps = float(config.domain["frame_rates"]["delivery_fps"])
    return config, recipe, origin, fps, Path(config.episode_root)


def _recognizer(args: argparse.Namespace, config: Any, recipe: Any):
    machine = optional_block(config.machine, "timing")
    python, model = args.python or machine.get("python"), args.model or machine.get("model_dir")
    if not python or not model:
        raise Uncertain("recognition is not configured: pass --python and --model, or set machine.timing.python / "
                        "machine.timing.model_dir (or supply times with --recognised); nothing was faked")
    rec = recipe.block("recognition")
    return subprocess_recognizer(python, find_model_dir(model), rec, recipe.data["language"])


def run_timing(args: argparse.Namespace) -> int:
    """``timing words``: one JSON summary on stdout."""
    config, recipe, origin, fps, root = _setup(args)
    dialogue_path = Path(args.dialogue)
    document = read_json(dialogue_path)
    lines = parse_lines(document)
    if isinstance(document.get("fps"), (int, float)) and float(document["fps"]) != fps:
        raise Refused(f"dialogue fps {document['fps']} differs from the episode delivery fps {fps}")
    vocabulary = parse_vocabulary(read_json(Path(args.vocabulary)) if args.vocabulary else document.get("vocabulary"))
    supplied = read_json(Path(args.recognised)) if args.recognised else None
    if supplied is not None and not isinstance(supplied, dict):
        raise Refused("--recognised must be a word-timing JSON object")
    recognizer = None if supplied is not None else _recognizer(args, config, recipe)
    allow = tuple(Path(i) for i in args.allow_outside)
    if args.dry_run:
        bound = bind_wavs([line for line in lines if line["speech_text"]], root, allow)
        summary = {"ok": True, "dry_run": True, "lines": len(lines), "wavs_bound": len(bound), "recipe": recipe.recipe_id,
                   "recipe_source": origin, "source": "supplied" if supplied is not None else "recognition"}
        print(json.dumps(summary, indent=2))
        return 0
    if not args.out:
        raise Refused("--out is required unless --dry-run")
    summary = run.run_words(
        episode_id=config.episode["episode_id"], fps=fps, root=root, lines=lines, vocabulary=vocabulary, recipe=recipe,
        recognizer=recognizer, supplied=supplied, out=Path(args.out), allow=allow, dialogue_sha=sha256_file(dialogue_path),
        first_word=not args.no_first_word_rule)
    print(f"timing words: {summary['verdict']}  moved {summary['words_moved']}/{summary['words']}  "
          f"Q1 early {summary['q1']['summary']['early']} late {summary['q1']['summary']['late']} "
          f"warn {summary['q1']['summary']['warn']}  "
          f"control {'detected' if summary['q1']['control_detected'] else 'NOT detected'}", file=sys.stderr)
    print(json.dumps({**summary, "recipe": recipe.recipe_id, "recipe_source": origin}, indent=2))
    return {"PASS": 0, "FAIL": 1}.get(summary["verdict"], 2)


def run_qa_words(args: argparse.Namespace) -> int:
    """``qa words``: Q1 over a finished word-timing document."""
    _config, recipe, _origin, fps, root = _setup(args)
    timing_path = Path(args.timing)
    timing = read_json(timing_path)
    if not isinstance(timing, dict):
        raise Refused(f"{timing_path}: word timing must be a JSON object")
    result, bound = gate.check_document(timing, root, recipe.block("q1"), fps, tuple(Path(i) for i in args.allow_outside))
    receipt = stamp(gate.build_receipt(timing_path, root, recipe.recipe_id, recipe.sha256, result, bound))  # printed and written: one header
    if args.out:
        write_json_once(Path(args.out), receipt, mode="utf8")
    print(f"qa words: {receipt['verdict']}  tested {result['summary']['words_tested']}  early {result['summary']['early']} "
          f"late {result['summary']['late']} warn {result['summary']['warn']}  control {'detected' if result['negative_control']['detected'] else 'NOT detected'}",
          file=sys.stderr)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["ok"] else 1
