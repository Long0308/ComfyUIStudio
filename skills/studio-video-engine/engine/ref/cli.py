"""Register ``jjv ref search``, ``jjv ref fetch`` and ``jjv ref stage``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy.settings import settings_from_machine
from ..config.loader import DEFAULT_MACHINE_PATH
from ..core.errors import EXIT_OK, EXIT_REFUSED, Refused
from ..core.io import read_json
from .fetch import fetch_one
from .library import SUPPORTED_TYPES, default_library_root, search_entries
from .stage import apply_stage, plan_stage, report as stage_report


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def register_cli(stages: Any) -> None:
    ref = stages.add_parser("ref", help="local reference-library search and guarded single-image fetch")
    verbs = ref.add_subparsers(dest="verb", required=True)

    search = verbs.add_parser("search", help="list matching ids from local INDEX.csv files (no network)")
    search.add_argument("--type", required=True, choices=SUPPORTED_TYPES)
    search.add_argument("--group", default=None, help="limit to one by-type group directory")
    search.add_argument("--tag", default=None, help="exact tag/label match (case-insensitive)")
    search.add_argument("--limit", type=_positive_int, default=50, help="maximum ids to print (default: 50)")
    search.add_argument("--library-root", default=None,
                        help="reference-library root (default: repo production-local/reference-library)")

    fetch = verbs.add_parser("fetch", help="download EXACTLY ONE indexed image and append a receipt")
    fetch.add_argument("--id", action="append", required=True, help="one reference id (repeat is refused)")
    fetch.add_argument("--reason", required=True, help="why this single image is needed; stored in the receipt")
    fetch.add_argument("--out", required=True, help="directory for the image and ref-fetch-receipts.jsonl")
    fetch.add_argument("--library-root", default=None,
                       help="reference-library root (default: repo production-local/reference-library)")

    stage = verbs.add_parser("stage", help="copy indexed LOCAL reference images into the ComfyUI input folder with a "
                                           "provenance manifest; dry-run unless --apply; no network")
    pick = stage.add_mutually_exclusive_group(required=True)
    pick.add_argument("--ids", action="append", default=None, help="comma-separated reference ids (repeatable)")
    pick.add_argument("--type", default=None, choices=SUPPORTED_TYPES, help="select by type (with --series/--limit)")
    stage.add_argument("--series", default=None, help="one by-type group directory (only with --type)")
    stage.add_argument("--limit", type=_positive_int, default=None,
                       help="maximum entries with --type (default: 10; only with --type)")
    stage.add_argument("--apply", action="store_true", help="really copy and write the manifest (default: dry-run)")
    stage.add_argument("--library-root", default=None,
                       help="reference-library root (default: repo production-local/reference-library)")
    stage.add_argument("--comfy-input", default=None,
                       help="ComfyUI input folder (default: machine.json comfy.root/input)")
    stage.add_argument("--license-status", default=None,
                       help="license-status document (default: <library-root>/LICENSE-STATUS.json)")
    stage.add_argument("--machine", default=None, help=argparse.SUPPRESS)


def _comfy_input_dir(args: argparse.Namespace) -> Path:
    """Thư mục input của ComfyUI: ``--comfy-input`` nếu có, không thì ``comfy.root/input`` của machine.json."""
    if args.comfy_input:
        return Path(args.comfy_input)
    machine = read_json(Path(args.machine) if args.machine else DEFAULT_MACHINE_PATH)
    try:
        return settings_from_machine(machine).input_dir
    except (KeyError, TypeError) as error:
        raise Refused(f"machine config lacks the comfy keys needed for the input folder: {error}") from error


def _run_stage(args: argparse.Namespace, library_root: Path) -> int:
    plan = plan_stage(
        library_root, _comfy_input_dir(args), ids=args.ids, ref_type=args.type, series=args.series,
        limit=args.limit, license_status_path=Path(args.license_status) if args.license_status else None,
    )
    applied = False
    if args.apply and not plan.refused:
        plan = apply_stage(plan)
        applied = True
    print(json.dumps(stage_report(plan, applied=applied), indent=2, ensure_ascii=True))
    return EXIT_REFUSED if plan.refused else EXIT_OK


def run_ref(args: argparse.Namespace) -> int:
    library_root = Path(args.library_root) if args.library_root else default_library_root()
    if args.verb == "stage":
        return _run_stage(args, library_root)
    if args.verb == "search":
        entries = search_entries(library_root, args.type, group=args.group, tag=args.tag, limit=args.limit)
        print(json.dumps({
            "ok": True,
            "type": args.type,
            "group": args.group,
            "tag": args.tag,
            "count": len(entries),
            "ids": [entry.id for entry in entries],
        }, indent=2, ensure_ascii=True))
        return EXIT_OK
    if args.verb == "fetch":
        if len(args.id) != 1:
            raise Refused("ref fetch accepts exactly one --id per call; refusing a batch")
        result = fetch_one(library_root, args.id[0], args.reason, Path(args.out))
        print(json.dumps({
            "ok": True,
            "id": result.id,
            "file": str(result.file),
            "sha256": result.sha256,
            "bytes": result.bytes,
            "utc_time": result.utc_time,
            "receipt": str(result.receipt),
            "url": result.source_url,
        }, indent=2, ensure_ascii=True))
        return EXIT_OK
    raise Refused(f"unknown ref verb: {args.verb}")
