"""CLI glue: ``jjv post grade``. CPU only. Registered next to ``post logo`` under the same ``post`` verb group."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from ...config import rules
from ...config.loader import SKILL_ROOT, resolve_episode
from ...config.schema import validate
from ...core.errors import EngineError, Refused, exit_code_for
from ...core.io import read_json
from ...seedvr2.seam_media import find_ffmpeg
from .run import GradeRequest, grade_video

_DOMAIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def _post_verbs(stages: Any) -> Any:
    """The ``post`` verb group is created by ``post logo``; reuse it so both verbs share one ``post`` command."""
    import argparse as _ap
    post = stages.choices.get("post")
    if post is None:
        post = stages.add_parser("post", help="post steps after the upscale (CPU only, domain-gated)")
    for action in post._actions:  # noqa: SLF001 - argparse has no public accessor for an existing subparsers action
        if isinstance(action, _ap._SubParsersAction):  # noqa: SLF001
            return action
    return post.add_subparsers(dest="verb", required=True)


def register_cli(stages: Any) -> None:
    verbs = _post_verbs(stages)
    grade = verbs.add_parser("grade", help="cinematic post grade: 3D LUT (domain-declared) + soften/halation/grain "
                                           "-> write-once mp4 + before/after stills + receipt")
    scope = grade.add_mutually_exclusive_group(required=True)
    scope.add_argument("--episode", help="episode ref; its resolved domain decides")
    scope.add_argument("--domain", help="domain id (domains/<id>.json) for a film that has no episode.json yet")
    grade.add_argument("--in", dest="src", required=True, help="input mp4")
    grade.add_argument("--out", required=True, help="output mp4 (write-once; receipt + stills beside it)")
    grade.add_argument("--lut", required=True, help=".cube file; must be declared by the domain by name and sha256")
    grade.add_argument("--lut-sha256", default=None, help="optional expected sha256 of --lut (must equal the domain sha)")
    grade.add_argument("--grain", type=float, default=0.0, help="0..1 (own layer, applied before the LUT)")
    grade.add_argument("--halation", type=float, default=0.0, help="0..1 red glow from highlights")
    grade.add_argument("--soften", type=float, default=0.0, help="0..1 gaussian blend")
    grade.add_argument("--crf", type=int, default=18)
    grade.add_argument("--still-frame", type=int, default=None, help="frame index for the before/after stills (default middle)")
    grade.add_argument("--ffmpeg", default=None)
    grade.add_argument("--ffprobe", default=None)


def load_domain(domain_id: str) -> dict:
    """``domains/<id>.json`` checked against the schema and the domain rules (no episode needed)."""
    if not _DOMAIN_ID.match(domain_id or ""):
        raise Refused(f"invalid domain id {domain_id!r}")
    path = SKILL_ROOT / "domains" / f"{domain_id}.json"
    if not path.is_file():
        raise Refused(f"no domain file for {domain_id!r}: {path}")
    domain = read_json(path)
    errors = validate(domain, read_json(SKILL_ROOT / "schemas" / "domain.schema.json"), label="domain")
    problems = list(errors) + (rules.check_domain(domain, domain_id) if not errors else [])
    if problems:
        raise Refused("; ".join(problems))
    return domain


def resolve_domain(args: argparse.Namespace) -> dict:
    return load_domain(args.domain) if args.domain else resolve_episode(args.episode).domain


def build_request(args: argparse.Namespace) -> GradeRequest:
    ffmpeg = find_ffmpeg(args.ffmpeg)
    ffprobe = args.ffprobe or str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    out = Path(args.out)
    return GradeRequest(video=Path(args.src), lut=Path(args.lut), out=out, ffmpeg=ffmpeg, ffprobe=ffprobe,
                        lut_sha256=args.lut_sha256, grain=args.grain, halation=args.halation, soften=args.soften,
                        crf=args.crf, still_frame=args.still_frame)


def brief(receipt: dict) -> dict:
    video = receipt["outputs"]["video"]
    return {"ok": True, "status": receipt["status"], "domain_id": receipt["domain_id"],
            "lut": receipt["inputs"]["lut"]["name"], "params": receipt["params"],
            "gates": {"audio": receipt["gates"]["audio"]["mode"]},
            "outputs": {k: v["sha256"] for k, v in receipt["outputs"].items()},
            "receipt": str(Path(video["path"]).with_name(Path(video["path"]).stem + ".grade-receipt.json"))}


def run_grade(args: argparse.Namespace) -> int:
    try:
        domain = resolve_domain(args)
        receipt = grade_video(domain, build_request(args))
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error), "evidence": getattr(error, "evidence", {})},
                         ensure_ascii=False, default=str), file=sys.stderr)
        return exit_code_for(error)
    except ValueError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return exit_code_for(Refused(str(error)))
    print(json.dumps(brief(receipt), ensure_ascii=False, indent=1))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Stand-alone entry (tests): same parser as ``jjv post``."""
    parser = argparse.ArgumentParser(prog="post")
    stages = parser.add_subparsers(dest="stage", required=True)
    register_cli(stages)
    return run_grade(parser.parse_args(["post", *(argv if argv is not None else sys.argv[1:])]))
