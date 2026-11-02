"""CLI glue: ``jjv captions build|burn``. CPU only: no GPU, no ComfyUI, no network, no recognition."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from ..core.errors import EngineError, Refused, exit_code_for
from ..core.io import read_json, sha256_bytes, sha256_file, write_json_once, write_once
from ..seedvr2.seam_media import find_ffmpeg
from . import ass as ass_mod
from . import burn as burn_mod
from .split import check_split
from .gate import require_timing

BUILD_SCHEMA = "jjv/captions-build-receipt/v1"


def register_cli(stages: Any) -> None:
    captions = stages.add_parser("captions", help="karaoke ASS + SRT from WORD-TIMING.json, and burn (CPU only)")
    verbs = captions.add_subparsers(dest="verb", required=True)
    build = verbs.add_parser("build", help="WORD-TIMING.json -> <stem>.ass + <stem>.srt + receipt (write-once)")
    build.add_argument("--episode", required=True)
    build.add_argument("--timing-receipt", default=None)
    build.add_argument("--timing", required=True, help="WORD-TIMING.json")
    build.add_argument("--out", required=True, help="output stem (writes STEM.ass, STEM.srt, STEM.captions-receipt.json)")
    build.add_argument("--highlight", default=ass_mod.DEFAULT_HIGHLIGHT, help="RRGGBB of the lit word (default 0B4FD9)")
    build.add_argument("--title", default=None, help="ASS Script Info title (production: pass the shot, e.g. '<EP> S02_A karaoke review')")
    build.add_argument("--title-suffix", default="", help="optional text appended to the title (provenance)")
    build.add_argument("--layout", default=None, help="saved cue layout JSON; refused with GENERATOR_SPLIT_MISMATCH if it "
                                                      "differs from the generator split")
    burn = verbs.add_parser("burn", help="CPU ASS burn; copy approved audio, explicit AAC candidate for silent picture")
    burn.add_argument("--episode", required=True)
    burn.add_argument("--timing", required=True)
    burn.add_argument("--timing-receipt", default=None)
    burn.add_argument("--subtitles", required=True, help="selected captions build receipt (v1 bridge, not subtitles/v2)")
    burn.add_argument("--font", required=True, help="exact font file inside fontsdir; hash recorded, glyph approval still pending")
    burn.add_argument("--audio-receipt", default=None, help="PASS audio mix receipt binding the existing video to its final WAV")
    burn.add_argument("--h3-preparation", default=None,
                      help="H3 preparation.json; its wav.sha256 must equal --wav (required by domain captions policy when declared)")
    burn.add_argument("--allow-aac-from-wav", action="store_true", help="explicit silent-picture candidate exception; never final-ready")
    burn.add_argument("--ffprobe", default=None)
    burn.add_argument("--video", required=True)
    burn.add_argument("--ass", required=True)
    burn.add_argument("--wav", required=True)
    burn.add_argument("--out", required=True, help="output mp4 (write-once)")
    burn.add_argument("--fontsdir", default=None, help="fonts folder (default: <ass folder>/fonts)")
    burn.add_argument("--fps", type=int, default=24)
    burn.add_argument("--ffmpeg", default=None)


def run_build(args: argparse.Namespace) -> dict:
    timing_path = Path(args.timing)
    _, timing, timing_binding = require_timing(args.episode, timing_path,
                                              Path(args.timing_receipt) if args.timing_receipt else None)
    cues = ass_mod.words_to_cues(timing)
    if not cues:
        raise Refused("WORD-TIMING has no words: nothing to build")
    if args.layout:
        check_split(cues, read_json(Path(args.layout)))
    kwargs: dict[str, Any] = {"highlight": args.highlight}
    if args.title is not None:
        kwargs["title"] = args.title
    if args.title_suffix:
        kwargs["title_suffix"] = args.title_suffix
    ass_bytes = ass_mod.cues_to_ass(cues, **kwargs).encode("utf-8")
    srt_bytes = ass_mod.cues_to_srt(cues).encode("utf-8")
    stem = Path(args.out)
    ass_path, srt_path = stem.with_name(stem.name + ".ass"), stem.with_name(stem.name + ".srt")
    receipt_path = stem.with_name(stem.name + ".captions-receipt.json")
    write_once(ass_path, ass_bytes)
    write_once(srt_path, srt_bytes)
    receipt = {
        "schema": BUILD_SCHEMA,
        "inputs": {"timing": timing_binding},
        "outputs": {"ass": {"path": str(ass_path), "sha256": sha256_bytes(ass_bytes)},
                    "srt": {"path": str(srt_path), "sha256": sha256_bytes(srt_bytes)}},
        "generator": {"module": "engine/captions/ass.py", "sha256": sha256_file(Path(ass_mod.__file__))},
        "highlight": "#" + args.highlight.removeprefix("#").upper(),
        "title_source": "explicit" if args.title is not None else "default",
        "cue_count": len(cues),
    }
    write_json_once(receipt_path, receipt, mode="utf8")
    return receipt


def run_captions(args: argparse.Namespace) -> int:
    try:
        if args.verb == "build":
            summary = run_build(args)
        else:
            ass = Path(args.ass)
            summary = burn_mod.burn(video=Path(args.video), ass=ass, wav=Path(args.wav), out=Path(args.out),
                                    fontsdir=Path(args.fontsdir) if args.fontsdir else ass.parent / "fonts",
                                    ffmpeg=find_ffmpeg(args.ffmpeg), fps=args.fps, episode=args.episode,
                                    timing=Path(args.timing),
                                    timing_receipt=Path(args.timing_receipt) if args.timing_receipt else None,
                                    subtitles=Path(args.subtitles), font=Path(args.font),
                                    audio_receipt=Path(args.audio_receipt) if args.audio_receipt else None,
                                    allow_aac_from_wav=args.allow_aac_from_wav,
                                    h3_preparation=Path(args.h3_preparation) if args.h3_preparation else None,
                                    ffprobe=args.ffprobe)
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return exit_code_for(error)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=1))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Stand-alone entry (tests): same parser as ``jjv captions``."""
    parser = argparse.ArgumentParser(prog="captions")
    stages = parser.add_subparsers(dest="stage", required=True)
    register_cli(stages)
    return run_captions(parser.parse_args(["captions", *(argv if argv is not None else sys.argv[1:])]))
