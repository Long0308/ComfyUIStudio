"""CLI glue: ``jjv edit assemble`` (CPU only, domain-gated by ``domain.delivery.assemble``).

``--episode`` resolves the episode and takes the gate from its domain; ``--domain`` reads
``domains/<id>.json`` directly, for a film that has no ``engine/episode.json`` yet.
One JSON summary on stdout; refusals carry a stable code and map to the engine exit codes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from ..config import rules
from ..config.loader import SKILL_ROOT, resolve_episode
from ..config.schema import validate
from ..core.errors import EngineError, exit_code_for
from ..core.io import read_json
from ..seedvr2.seam_media import find_ffmpeg
from .edl import code_of, refuse, validate_edl
from . import cutkind
from .render import AssemblePolicy, assemble, probe_media, safe_token

_DOMAIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")

def load_domain(domain_id: str) -> dict:
    """``domains/<id>.json`` checked against the domain schema and rules (no episode needed)."""
    if not _DOMAIN_ID.match(domain_id or ""):
        refuse("ASSEMBLE_BAD_DOMAIN", f"invalid domain id {domain_id!r}")
    path = SKILL_ROOT / "domains" / f"{domain_id}.json"
    if not path.is_file():
        refuse("ASSEMBLE_BAD_DOMAIN", f"no domain file for {domain_id!r}: {path}")
    domain = read_json(path)
    problems = list(validate(domain, read_json(SKILL_ROOT / "schemas" / "domain.schema.json"), label="domain"))
    problems += rules.check_domain(domain, domain_id) if not problems else []
    if problems:
        refuse("ASSEMBLE_BAD_DOMAIN", "; ".join(problems))
    return domain

def resolve_domain(args: argparse.Namespace) -> dict:
    if args.domain:
        return load_domain(args.domain)
    return resolve_episode(args.episode).domain

def resolve_base(edl_path: Path, explicit: str | None) -> Path:
    """Relative EDL paths resolve against ``--base``, else the nearest folder holding the repo marker."""
    if explicit:
        return Path(explicit)
    for parent in Path(edl_path).resolve().parents:
        if (parent / "AGENTS.md").is_file():
            return parent
    return Path(edl_path).resolve().parent

def register_edit_verb(verbs: Any) -> None:
    """Add ``assemble`` to the existing ``jjv edit`` subparser."""
    run = verbs.add_parser(
        "assemble", help="EDL -> master picture + stems + multitrack mux + receipt "
                         "(CPU only, domain-gated by domain.delivery.assemble)")
    scope = run.add_mutually_exclusive_group(required=True)
    scope.add_argument("--episode", help="episode ref; its resolved domain decides")
    scope.add_argument("--domain", help="domain id (domains/<id>.json) for a film with no episode.json yet")
    run.add_argument("--edl", required=True, help="EDL JSON (schema id, fps, kinds from the domain)")
    run.add_argument("--out-dir", help="output folder (required unless --validate-only)")
    run.add_argument("--tag", help="write-once label (required unless --validate-only)")
    run.add_argument("--base", default=None, help="base folder for relative EDL paths (default: repo root)")
    run.add_argument("--preview", action="store_true",
                     help="preview cut (labelled 'preview'); without it a domain with final_gate makes a FINAL cut, "
                          "which needs approval receipts for every clip")
    run.add_argument("--approvals", action="append", default=[], metavar="DIR",
                     help="folder(s) holding <shot>/acceptance/*.json user approvals (repeatable)")
    run.add_argument("--validate-only", action="store_true", help="validate the EDL and stop (no ffmpeg)")
    run.add_argument("--ffmpeg", default=None)
    run.add_argument("--ffprobe", default=None)

def _binaries(args: argparse.Namespace) -> tuple[str, str]:
    ffmpeg = find_ffmpeg(getattr(args, "ffmpeg", None))
    ffprobe = getattr(args, "ffprobe", None) or str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    return ffmpeg, ffprobe

def _ffprobe(args: argparse.Namespace) -> str:
    explicit = getattr(args, "ffprobe", None)
    if explicit:
        return explicit
    ffmpeg = find_ffmpeg(getattr(args, "ffmpeg", None))
    return str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))

def run_assemble(args: argparse.Namespace) -> int:
    try:
        domain = resolve_domain(args)
        policy = AssemblePolicy.from_domain(domain)
        edl_path = Path(args.edl).resolve()
        base = resolve_base(edl_path, getattr(args, "base", None))
        edl = read_json(edl_path)
        if getattr(args, "validate_only", False):
            validation = validate_edl(edl, base, schema=policy.edl_schema, fps=policy.fps, kinds=policy.kinds,
                                      transitions=policy.transitions,
                                      probe=lambda path: probe_media(path, _ffprobe(args)))
            gate_report = None
            if policy.final_gate is not None:
                kind = "preview" if getattr(args, "preview", False) else "final"
                try:
                    gate_report = {"cut_kind": kind, "status": "APPROVED" if cutkind.gate_cut(
                        policy.final_gate, validation, kind, getattr(args, "approvals", [])) else "n/a"}
                except EngineError as error:
                    gate_report = {"cut_kind": kind, "status": "UNAPPROVED", "message": str(error)}
            print(json.dumps({"ok": True, "status": "VALID", "domain_id": policy.domain_id,
                              **({"final_gate": gate_report} if gate_report else {}),
                              "segments": len(validation["segments"]),
                              "total_frames": validation["total_frames"],
                              "duration_s": round(validation["total_frames"] / policy.fps, 3)}, indent=1))
            return 0
        if not args.out_dir or not args.tag:
            refuse("ASSEMBLE_USAGE", "--out-dir and --tag are required unless --validate-only")
        ffmpeg, ffprobe = _binaries(args)
        document = assemble(edl_path, Path(args.out_dir), args.tag, policy, base=base,
                            ffmpeg=ffmpeg, ffprobe=ffprobe,
                            cut_kind="preview" if getattr(args, "preview", False) else "final",
                            approval_roots=getattr(args, "approvals", []))
        print(json.dumps({"ok": True, "status": "ASSEMBLED", "domain_id": document["domain_id"],
                          "duration_s": document["film"]["duration_s"],
                          "outputs": {name: row["sha256"] for name, row in document["outputs"].items()},
                          "placeholders": document["placeholders"],
                          **({"cut_kind": document["cut_kind"]} if "cut_kind" in document else {}),
                          "receipt": str(Path(args.out_dir) /
                                         f"receipt-{safe_token(args.tag, 'tag')}.json")}, indent=1))
        return 0
    except EngineError as error:
        print(json.dumps({"ok": False, "code": code_of(error), "error": str(error),
                          "evidence": {k: v for k, v in error.evidence.items()}}, ensure_ascii=False, default=str),
              file=sys.stderr)
        return exit_code_for(error)

def main(argv: Sequence[str] | None = None) -> int:
    """Stand-alone entry (tests): the same parser shape as ``jjv edit assemble``."""
    parser = argparse.ArgumentParser(prog="jjv edit")
    stages = parser.add_subparsers(dest="stage", required=True)
    edit = stages.add_parser("edit")
    verbs = edit.add_subparsers(dest="verb", required=True)
    register_edit_verb(verbs)
    return run_assemble(parser.parse_args(["edit", "assemble", *(argv if argv is not None else sys.argv[1:])]))
