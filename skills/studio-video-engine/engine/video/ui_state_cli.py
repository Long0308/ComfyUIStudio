"""Cờ + mã thoát của ``ui-state`` (``jjv/video-ui-state/v1``, xem ``ui_state``) — dùng chung cho ``python -m engine.video.ui_state``
và verb ``jjv video ui-state`` (``cli.py`` gọi ``add_arguments`` rồi ``run``).  Chỉ đọc, không GPU; in MỘT JSON (ASCII-safe).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..core.errors import EngineError, Refused, exit_code_for
from ..layout.context import load_context
from . import anchor_pack_ui
from .ui_state import build, upsert_index, write

DESCRIPTION = "jjv/video-ui-state/v1 for the ComfyUI video panel (read-only; no GPU)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--shotlist", required=True, help="jjv/script/v1 or jjv/shotlist-draft/v1 of this episode")
    parser.add_argument("--out", required=True, help="target JSON (written atomically)")
    parser.add_argument("--video-out", default=None, help="jjv video plan folder (state.json per shot)")
    parser.add_argument("--h3-dir", action="append", default=[], help="folder holding <SHOT>/ receipt dirs; repeatable, first wins on ties")
    parser.add_argument("--receipts", action="append", default=[], metavar="SHOT=DIR", help="explicit receipt dir of one shot")
    parser.add_argument("--shots-doc", default=None, help="jjv/shots/v1 editorial doc (default: episode.files.shots)")
    parser.add_argument("--wardrobe", default=None, help="jjv/wardrobe-presets/v1 of this domain; a shot without site/office context is refused, never guessed")
    parser.add_argument("--anchor-dir", default=None, help=f"folder holding <SHOT>/{anchor_pack_ui.PACK_FILE} (jjv/shot-anchor-pack/v1)")
    parser.add_argument("--index", default=None, help="index.json to upsert next to the data files")
    parser.add_argument("--label", default=None, help="human label of this episode in index.json")
    parser.add_argument("--pipeline-config", default=None, help="JSON of the per-shot 10-stage pipeline sources (evidence/voice_out/...); omitted = no `pipeline` key")
    parser.add_argument("--machine", default=None, help=argparse.SUPPRESS)


def run(args: argparse.Namespace) -> int:
    """Chạy với Namespace đã parse; mọi ``EngineError`` ⇒ JSON ``ok: false`` + mã thoát của lỗi, không traceback."""
    opt = lambda value: Path(value) if value else None  # noqa: E731
    try:
        if any("=" not in item or not item.partition("=")[2] for item in args.receipts):
            raise Refused(f"--receipts needs SHOT=DIR, got {args.receipts}")
        explicit = {item.partition("=")[0]: Path(item.partition("=")[2]) for item in args.receipts}
        ctx = load_context(args.episode, args.machine)
        document = build(ctx, shotlist=Path(args.shotlist), video_out=opt(args.video_out), h3_dirs=[Path(d) for d in args.h3_dir],
                         receipts=explicit, shots_doc=opt(args.shots_doc), wardrobe=opt(args.wardrobe), anchor_dir=opt(args.anchor_dir),
                         pipeline=json.loads(Path(args.pipeline_config).read_text(encoding="utf-8")) if args.pipeline_config else None)
        digest = write(document, Path(args.out))
        if args.index:
            upsert_index(Path(args.index), episode=ctx.episode_id, domain=ctx.domain_id, file=Path(args.out).name, label=args.label)
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}))  # ASCII-safe: console có thể là cp1252
        return exit_code_for(error)
    print(json.dumps({"ok": True, "episode": ctx.episode_id, "domain": ctx.domain_id, "out": args.out, "sha256": digest,
                      "counts": document["counts"], "problems": sum(len(s["problems"]) for s in document["shots"]) + len(document["problems"]),
                      "first_shot": document["shots"][0]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    add_arguments(parser)
    return run(parser.parse_args(argv))


__all__ = ["DESCRIPTION", "add_arguments", "run", "main"]
