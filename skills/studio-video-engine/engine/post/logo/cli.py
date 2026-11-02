"""CLI glue: ``jjv post logo``. CPU only: no GPU, no ComfyUI, no network. One JSON summary on stdout."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from ...config import rules
from ...config.loader import REPO_ROOT, SKILL_ROOT, resolve_episode
from ...config.schema import validate
from ...core.errors import EngineError, Refused, exit_code_for
from ...core.io import read_json
from ...seedvr2.seam_media import find_ffmpeg
from .edgecheck import EdgeCheckParams
from .multimark import MarksRequest, composite_marks
from .policy import logo_policy
from .run import LogoRequest, composite_logo
from .tracker import TrackParams

_DOMAIN_ID = re.compile(r"^[a-z][a-z0-9_]*$")


def register_cli(stages: Any) -> None:
    post = stages.add_parser("post", help="post steps after the upscale (CPU only, domain-gated by domain.post)")
    verbs = post.add_subparsers(dest="verb", required=True)
    logo = verbs.add_parser("logo", help="collar-mark logo composite: seed box (auto or --seed-box) -> track -> gates -> "
                                         "encode with audio stream copy -> write-once mp4 + receipt")
    scope = logo.add_mutually_exclusive_group(required=True)
    scope.add_argument("--episode", help="episode ref; its resolved domain decides")
    scope.add_argument("--domain", help="domain id (domains/<id>.json) for a film that has no episode.json yet")
    logo.add_argument("--video", required=True)
    logo.add_argument("--logo", default=None, help="logo PNG with alpha (default: the domain-declared asset path)")
    logo.add_argument("--logo-sha256", default=None, help="expected sha256 of --logo; must equal the domain-declared sha")
    logo.add_argument("--out", required=True, help="output mp4 (write-once; receipt + review PNGs beside it)")
    logo.add_argument("--seed-box", default=None, help="x,y,w,h at --seed-frame; omitted = auto-detect (fail-closed)")
    logo.add_argument("--seed-frame", type=int, default=None, help="frame of --seed-box (default 0); needs --seed-box")
    logo.add_argument("--logo-rect", default=None,
                      help="x,y,w,h of the new mark at the seed frame (default: detected mark rect, else 0.6 box height centred)")
    logo.add_argument("--logo-rotation", type=float, default=0.0, help="degrees, clockwise positive")
    logo.add_argument("--logo-skew", type=float, default=0.0, help="0..0.4 fake perspective on the right edge")
    logo.add_argument("--thread-rgb", default="auto", help="r,g,b or 'auto' (median of the old mark's dark core at the seed)")
    logo.add_argument("--track-window", type=int, default=512)
    logo.add_argument("--crf", type=int, default=10)
    logo.add_argument("--rng-seed", type=int, default=20261031)
    logo.add_argument("--strip-frames", default=None, help="frames for the strips and the edge gate (default 10%%,50%%,90%%)")
    logo.add_argument("--preview-frames", default=None, help="frames drawn in the track preview (default 7 spread)")
    logo.add_argument("--gate-max-lost-fraction", type=float, default=TrackParams.gate_max_lost_fraction)
    logo.add_argument("--gate-max-gap", type=int, default=TrackParams.gate_max_gap_frames)
    logo.add_argument("--edge-slack", type=float, default=1.0, help="edge gate: mad_band <= mad_reference_outside + slack")
    logo.add_argument("--marks", default=None,
                      help="marks manifest JSON (jjv/post-logo-marks/v1): composite the real logo on several tracked marks "
                           "(helmet, vest chest, collar...); each mark has its own gates, failing marks are skipped and recorded")
    logo.add_argument("--ffmpeg", default=None)
    logo.add_argument("--ffprobe", default=None)


def _ints(text: str | None, count: int, label: str) -> tuple[int, ...] | None:
    if text is None:
        return None
    try:
        values = tuple(int(v) for v in text.split(","))
    except ValueError as error:
        raise Refused(f"{label} must be integers separated by commas") from error
    if count and len(values) != count:
        raise Refused(f"{label} needs {count} integers, got {len(values)}")
    return values


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


def build_request(args: argparse.Namespace, domain: dict) -> LogoRequest:
    policy = logo_policy(domain)
    logo = Path(args.logo) if args.logo else REPO_ROOT / policy.asset_path
    thread = None if args.thread_rgb.strip().lower() == "auto" else _ints(args.thread_rgb, 3, "--thread-rgb")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    ffprobe = args.ffprobe or str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    return LogoRequest(
        video=Path(args.video), logo=logo, out=Path(args.out), ffmpeg=ffmpeg, ffprobe=ffprobe,
        logo_sha256=args.logo_sha256, seed_frame=args.seed_frame, seed_box=_ints(args.seed_box, 4, "--seed-box"),
        logo_rect=_ints(args.logo_rect, 4, "--logo-rect"), logo_rotation=args.logo_rotation, logo_skew=args.logo_skew,
        thread_rgb=thread, track_window=args.track_window, crf=args.crf, rng_seed=args.rng_seed,
        strip_frames=_ints(args.strip_frames, 0, "--strip-frames"), preview_frames=_ints(args.preview_frames, 0, "--preview-frames"),
        track=TrackParams(gate_max_lost_fraction=args.gate_max_lost_fraction, gate_max_gap_frames=args.gate_max_gap),
        edge=EdgeCheckParams(), edge_slack=args.edge_slack)


def brief(receipt: dict) -> dict:
    seed = receipt["seed"]
    detection = seed.get("detection") or {}
    return {"ok": True, "status": receipt["status"], "domain_id": receipt["domain_id"],
            "seed": {k: seed[k] for k in ("frame", "box_xywh", "logo_rect_xywh", "source")},
            "detection": {k: detection[k] for k in ("score", "margin", "agreement") if k in detection} or None,
            "tracker_summary": receipt["tracker"]["summary"],
            "gates": {"track": receipt["gates"]["track"]["pass"], "edge": receipt["gates"]["edge"]["pass"],
                      "audio": receipt["gates"]["audio"]["mode"]},
            "outputs": {k: v["sha256"] for k, v in receipt["outputs"].items()},
            "receipt": str(Path(receipt["outputs"]["video"]["path"]).with_name(
                Path(receipt["outputs"]["video"]["path"]).stem + ".logo-receipt.json"))}


def brief_marks(receipt: dict) -> dict:
    video = receipt["outputs"]["video"]
    return {"ok": True, "status": receipt["status"], "domain_id": receipt["domain_id"],
            "marks_applied": receipt["marks_applied"], "marks_skipped": receipt["marks_skipped"],
            "gates": {"audio": receipt["gates"]["audio"]["mode"]},
            "outputs": {k: v["sha256"] for k, v in receipt["outputs"].items()},
            "receipt": str(Path(video["path"]).with_name(Path(video["path"]).stem + ".logo-receipt.json"))}


def build_marks_request(args: argparse.Namespace) -> MarksRequest:
    clash = [f for f, v in (("--seed-box", args.seed_box), ("--logo-rect", args.logo_rect), ("--logo", args.logo)) if v]
    if clash:
        raise Refused(f"--marks takes seeds and assets from the manifest; remove {clash}")
    ffmpeg = find_ffmpeg(args.ffmpeg)
    ffprobe = args.ffprobe or str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    return MarksRequest(video=Path(args.video), marks=Path(args.marks), out=Path(args.out), ffmpeg=ffmpeg, ffprobe=ffprobe,
                        repo_root=REPO_ROOT, crf=args.crf, track_window=args.track_window,
                        strip_frames=_ints(args.strip_frames, 0, "--strip-frames"), edge_slack=args.edge_slack,
                        track=TrackParams(gate_max_lost_fraction=args.gate_max_lost_fraction, gate_max_gap_frames=args.gate_max_gap))


def run_post(args: argparse.Namespace) -> int:
    try:
        domain = resolve_domain(args)
        if args.marks:
            print(json.dumps(brief_marks(composite_marks(domain, build_marks_request(args))), ensure_ascii=False, indent=1))
            return 0
        receipt = composite_logo(domain, build_request(args, domain))
    except EngineError as error:
        evidence = {k: v for k, v in error.evidence.items() if k != "per_frame"}
        print(json.dumps({"ok": False, "error": str(error), "evidence": evidence}, ensure_ascii=False, default=str),
              file=sys.stderr)
        return exit_code_for(error)
    print(json.dumps(brief(receipt), ensure_ascii=False, indent=1))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Stand-alone entry (tests): same parser as ``jjv post``."""
    parser = argparse.ArgumentParser(prog="post")
    stages = parser.add_subparsers(dest="stage", required=True)
    register_cli(stages)
    return run_post(parser.parse_args(["post", *(argv if argv is not None else sys.argv[1:])]))
