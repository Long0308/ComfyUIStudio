"""``jjv seedvr2 seam-blend``: verify a shot, resolve the policy, stream the blend, write a receipt."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256, read_json, sha256_file, write_json_once
from . import seam_blend as core
from .seam_blend_policy import (SeamPolicy, decide_policy, measure_shot,
                                measurement_from_policy_doc)
from .seam_media import (Encoder, decode_planes, dependency_versions, emit_default,
                         ffmpeg_version, find_ffmpeg, require_numpy)

RECEIPT_SCHEMA = "seam-blend-receipt/v002"
MODES = ("auto", "core", "hf8", "lin8")
PLAN_FILE = "PRODUCTION-PLAN.json"
POLICY_FILE = "SEAM-POLICY.json"
Emitter = Callable[[str], None]


def locate_plan(config) -> Path:
    block = config.episode.get("seedvr2") or {}
    version = block.get("production_version")
    if not version:
        raise Refused(f"episode {config.episode.get('episode_id')!r} has no "
                      "seedvr2.production_version")
    matches = sorted(path for path in Path(config.episode_root).glob(f"*/{version}/{PLAN_FILE}")
                     if path.is_file())
    if len(matches) != 1:
        raise Refused(f"expected exactly one {version}/{PLAN_FILE} under the episode tree, "
                      f"found {len(matches)}")
    return matches[0]


def load_shot(plan: dict, config, shot_id: str) -> tuple[dict, list[dict], int, Path]:
    matches = [shot for shot in plan.get("shots") or [] if shot.get("shot_id") == shot_id]
    if len(matches) != 1:
        raise Refused(f"shot {shot_id} not found exactly once in the plan")
    shot = matches[0]
    config_shot = next((item for item in config.shots if item.get("shot") == shot_id), None)
    if config_shot is None:
        raise Refused(f"shot {shot_id} is not in the episode shots.json")
    if shot.get("source_sha256") and shot["source_sha256"] != config_shot["clip"]["sha256"]:
        raise Refused(f"{shot_id}: plan source sha256 differs from shots.json")
    video = shot.get("source_video") or {}
    nframes = video.get("frames")
    if not isinstance(nframes, int) or nframes < 1:
        raise Refused(f"{shot_id}: plan source_video.frames is missing")
    if nframes != config_shot["clip"]["frames"]:
        raise Refused(f"{shot_id}: plan frames {nframes} != shots.json "
                      f"{config_shot['clip']['frames']}")
    raw = shot.get("source_path")
    if not raw:
        raise Refused(f"{shot_id}: plan shot has no source_path")
    source = Path(raw)
    if not source.is_absolute():
        source = Path(config.episode_root) / source
    chunks = shot.get("chunks") or []
    return shot, chunks, nframes, source


@dataclass
class Deps:
    decode: Callable[..., tuple] = decode_planes
    encoder_factory: Callable[..., Encoder] = Encoder
    measure: Callable[..., dict] | None = None
    ffmpeg_version: Callable[[str], str] = ffmpeg_version
    clock: Callable[[], float] = time.time
    emit: Emitter = emit_default


def _verify_stage(shot_id: str, chunks: list[dict], jobs: list[dict], plan_sha: str,
                  plan_root: Path, geometry: core.BlendGeometry) -> list[dict]:
    records = []
    for chunk, job in zip(chunks, jobs):
        core.check_job(shot_id, chunk, job, plan_sha, plan_root, geometry)
        raw_sha = sha256_file(Path(job["output_path"]))
        core_sha = sha256_file(Path(job["core_path"]))
        if raw_sha != job.get("output_sha256"):
            raise Refused(f"{chunk['chunk_name']}: raw sha256 {raw_sha[:16]} != job "
                          f"{str(job.get('output_sha256'))[:16]}")
        if core_sha != job.get("core_sha256"):
            raise Refused(f"{chunk['chunk_name']}: core sha256 {core_sha[:16]} != job "
                          f"{str(job.get('core_sha256'))[:16]}")
        records.append({
            "chunk": chunk["chunk_name"], "job_json": job["_path"],
            "job_json_sha256": sha256_file(Path(job["_path"])), "status": job["status"],
            "segment": [chunk["segment_start_frame"], chunk["segment_end_frame_exclusive"]],
            "core": [chunk["core_start_frame"], chunk["core_end_frame_exclusive"]],
            "segment_frames": chunk["segment_frames"],
            "raw_path": job["output_path"], "raw_sha256": raw_sha,
            "core_path": job["core_path"], "core_sha256": core_sha,
        })
    return records


def run_seam_blend(config, *, shot_id: str, out: str | None, mode: str = "auto",
                   dry_run: bool = False, policy_path: str | None = None,
                   ffmpeg: str | None = None, threads: int = 4,
                   deps: Deps | None = None) -> dict:
    """Verify one shot, resolve the policy and (unless ``dry_run``) write the blended mp4."""
    deps = deps or Deps()
    started = deps.clock()
    if mode not in MODES:
        raise Refused(f"unknown mode {mode!r}")
    if not dry_run and not out:
        raise Refused("--out is required unless --dry-run")
    plan_path = locate_plan(config)
    plan_root = plan_path.parent
    plan = read_json(plan_path)
    if plan.get("episode_id") and plan["episode_id"] != config.episode["episode_id"]:
        raise Refused(f"plan episode_id {plan['episode_id']!r} != resolved episode")
    if plan.get("film_id") and plan["film_id"] != config.episode["film_id"]:
        raise Refused(f"plan film_id {plan['film_id']!r} != resolved film")
    geometry = core.geometry_from_plan(plan)
    shot, chunks, nframes, source = load_shot(plan, config, shot_id)
    plan_sha = sha256_file(plan_path)

    jobs: list[dict] = []
    for chunk in chunks:
        job_path = plan_root / "runs" / shot_id / chunk["chunk_name"] / "job.json"
        if not job_path.is_file():
            raise Refused(f"{shot_id}/{chunk['chunk_name']}: job.json missing - shot is incomplete")
        job = read_json(job_path)
        job["_path"] = str(job_path)
        jobs.append(job)
    deps.emit(f"[verify] {shot_id}: {len(chunks)} job.json files present")
    records = _verify_stage(shot_id, chunks, jobs, plan_sha, plan_root, geometry)
    deps.emit(f"[verify] {shot_id}: status + sha256 ok for every chunk")
    policy = SeamPolicy.from_config(config)
    windows = core.plan_windows(chunks, nframes, half=policy.window_half_frames,
                                blend_frames=policy.blend_frames,
                                allow_clipped_tail=policy.allow_clipped_tail)
    deps.emit(f"[verify] geometry ok: {len(windows)} seams "
              f"{[(window['lo'], window['hi']) for window in windows]}")

    measurement = None
    candidate = Path(policy_path) if policy_path else plan_root / POLICY_FILE
    if candidate.is_file():
        measurement = measurement_from_policy_doc(candidate, shot_id, plan_sha)
        deps.emit(f"[policy] measurement read from {candidate}")

    if mode == "auto" and measurement is None:
        if dry_run:
            decision = {"mode_requested": "auto", "mode": "auto", "decision": "deferred",
                        "reason": "dry-run decodes nothing: auto resolves at build time from the "
                                  "motion measurement (or pass --policy / install SEAM-POLICY.json)",
                        "thresholds": policy.thresholds(), "measurement": None}
        else:
            shot["job_paths"] = {chunk["chunk_name"]: jobs[index]["core_path"]
                                 for index, chunk in enumerate(chunks)}
            measurement_fn = deps.measure or measure_shot
            measurement = measurement_fn(shot, chunks, windows, geometry, source,
                                         find_ffmpeg(ffmpeg), threads, deps.emit)
            decision = decide_policy("auto", policy, measurement)
            deps.emit(f"[policy] {shot_id}: {decision['reason']}")
    else:
        decision = decide_policy(mode, policy, measurement)

    summary = {
        "ok": True, "dry_run": dry_run, "stage": "seedvr2.seam-blend",
        "episode_id": config.episode["episode_id"], "shot": shot_id,
        "plan": {"path": str(plan_path), "sha256": plan_sha, "schema": plan.get("schema")},
        "source": {"path": str(source), "frames": nframes},
        "geometry": geometry.as_dict(), "mode_requested": mode, "policy": decision,
        "windows": [{"S": window["S"], "lo": window["lo"], "hi": window["hi"],
                     "clipped_at_shot_end": window["clipped"]} for window in windows],
        "chunks": [{key: record[key] for key in ("chunk", "segment_frames", "raw_sha256",
                                                 "core_sha256")} for record in records],
    }
    if dry_run:
        summary["output"] = {"path": str(out) if out else None, "written": False}
        return summary

    out_path = Path(out).resolve()
    if out_path.suffix.lower() != ".mp4":
        raise Refused("--out must be an .mp4 file")
    if core._inside(out_path, plan_root):
        raise Refused("--out lies inside the production plan tree; refusing to write there")
    if out_path.exists():
        raise Refused(f"refusing to overwrite existing output: {out_path}")
    ffmpeg_path = find_ffmpeg(ffmpeg)
    resolved_mode = decision["mode"]
    require_numpy()  # every build mode decodes and writes yuv420p planes

    def load(index: int) -> dict:
        chunk, job = chunks[index], jobs[index]
        raw = deps.decode(ffmpeg_path, Path(job["output_path"]), geometry.crop_filter,
                          geometry.final_width, geometry.final_height, threads)
        core_planes = deps.decode(ffmpeg_path, Path(job["core_path"]), None,
                                  geometry.final_width, geometry.final_height, threads)
        core.check_frame_counts(chunk, job["output_frame_count"], raw[0].shape[0],
                                core_planes[0].shape[0])
        diffs = core.check_core_equals_raw(chunk, raw, core_planes)
        records[index].update(raw_frames_decoded=int(raw[0].shape[0]),
                              core_frames_decoded=int(core_planes[0].shape[0]),
                              core_equals_raw_trim_crop_maxdiff_YUV=diffs)
        deps.emit(f"[load] {chunk['chunk_name']}: raw {raw[0].shape[0]}f "
                  f"core {core_planes[0].shape[0]}f core==trim+crop")
        return {"raw": raw, "core": core_planes}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_name(f".{out_path.stem}.{os.getpid()}.partial.mp4")
    encoder = deps.encoder_factory(ffmpeg_path, temporary, geometry.final_width,
                                   geometry.final_height, geometry.fps, threads)
    gains: list[dict] = []
    kinds: list[str] = []
    try:
        for frame, planes, kind in core.assemble_frames(
                chunks, nframes, windows, load, resolved_mode,
                blend_frames=policy.blend_frames, sigma=policy.hf8_sigma, gains_out=gains):
            encoder.write(planes)
            kinds.append(kind)
        encoder.close()
        if encoder.frames != nframes:
            raise Uncertain(f"wrote {encoder.frames} frames, expected {nframes}")
        try:
            os.link(temporary, out_path)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite concurrent output: {out_path}") from error
    except BaseException:
        encoder.abort()
        temporary.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)

    receipt = {
        "schema": RECEIPT_SCHEMA, "script": str(Path(__file__).resolve()),
        "script_sha256": sha256_file(Path(__file__)),
        "argv": list(sys.argv), "ffmpeg": ffmpeg_path,
        "ffmpeg_version": deps.ffmpeg_version(ffmpeg_path),
        "dependencies": dependency_versions(),
        "episode_id": config.episode["episode_id"], "shot": shot_id,
        "mode": resolved_mode, "mode_requested": mode, "policy": decision,
        "sigma": policy.hf8_sigma if resolved_mode == "hf8" else None,
        "weights_on_next_chunk": ([round(weight, 5) for weight in
                                   core.seam_weights(policy.blend_frames)]
                                  if resolved_mode != "core" else None),
        "plan": {"path": str(plan_path), "sha256": plan_sha, "schema": plan.get("schema")},
        "config": {"config_sha256": config.config_sha256,
                   "domain_sha256": canonical_sha256(config.domain, mode="ascii"),
                   "episode_root": config.episode_root},
        "geometry": geometry.as_dict(),
        "source": {"path": str(source), "frames": nframes},
        "chunks": records,
        "seams": [{"S": window["S"], "chunk_k": window["k"], "chunk_k1": window["k"] + 1,
                   "window": [window["lo"], window["hi"]],
                   "clipped_at_shot_end": window["clipped"],
                   "blended": resolved_mode != "core"} for window in windows],
        "blended_frames": gains, "blended_frame_count": kinds.count("blend"),
        "output": {"path": str(out_path), "sha256": sha256_file(out_path),
                   "frames": int(encoder.frames),
                   "size": [geometry.final_width, geometry.final_height],
                   "codec": "libx264 crf0 yuv420p",
                   "frames_mapping": "output frame f == source frame f (same mapping as the "
                                     "concatenated cores)"},
        "receipt_canonicalization": "utf8",
        "elapsed_s": round(deps.clock() - started, 1),
    }
    receipt_path = out_path.with_name(out_path.name + ".receipt.json")
    write_json_once(receipt_path, receipt, mode="utf8")
    deps.emit(f"[done] {out_path} frames={encoder.frames} "
              f"blended={kinds.count('blend')} receipt={receipt_path}")
    summary["output"] = {"path": str(out_path), "sha256": receipt["output"]["sha256"],
                         "frames": int(encoder.frames), "written": True}
    summary["receipt"] = {"path": str(receipt_path), "sha256": sha256_file(receipt_path)}
    summary["mode"] = resolved_mode
    return summary


def register_cli(subparsers) -> None:
    """Register ``jjv seedvr2 seam-blend`` on an argparse sub-parser group."""
    parser = subparsers.add_parser(
        "seam-blend",
        help="blend verified SeedVR2 chunk seams (CPU; --dry-run verifies and prints the plan)")
    parser.add_argument("--episode", required=True,
                        help="episode.json path, episode root or slug")
    parser.add_argument("--shot", required=True, help="shot id, e.g. S02_A")
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--out", default=None, help="output .mp4 (required unless --dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="verify + print the plan; decode nothing and write nothing")
    parser.add_argument("--policy", default=None,
                        help=f"recorded measurement document (default: <plan>/{POLICY_FILE})")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--ffmpeg", default=None)


def emit_json(value: dict) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=True))
