"""One grade run: refusals -> encode (audio stream copy) -> audio packet gate -> write-once outputs + receipt.

Every refusal (flag bounds, domain gate, LUT declaration/sha, LUT parse) happens BEFORE any frame is encoded.
Stills: the same frame index is written before and after the grade, as PNG, for the approval review.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ...captions.burn import audio_packets
from ...core.errors import Refused, Uncertain
from ...core.io import sha256_file, write_json_once, write_once
from ..logo.video_io import VideoInfo, ffmpeg_version, probe
from . import RECEIPT_SCHEMA
from .chain import GradeParams, build_graph, matrix_for
from .lut import parse_cube
from .policy import grade_policy, require_lut

FFMPEG_TIMEOUT = 1800


@dataclass(frozen=True)
class GradeRequest:
    video: Path
    lut: Path
    out: Path
    ffmpeg: str
    ffprobe: str
    lut_sha256: str | None = None
    grain: float = 0.0
    halation: float = 0.0
    soften: float = 0.0
    crf: int = 18
    still_frame: int | None = None  # default: the middle frame


def _tags(info: VideoInfo) -> str:
    """Source colour tags re-attached at the end of the graph; a source with no tags gets none (nothing invented)."""
    parts = []
    if info.color_primaries:
        parts.append(f"color_primaries={info.color_primaries}")
    if info.color_trc:
        parts.append(f"color_trc={info.color_trc}")
    if info.color_space:
        parts.append(f"colorspace={info.color_space}")
    return ("setparams=" + ":".join(parts)) if parts else ""


def _run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, cwd=cwd, timeout=FFMPEG_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise Uncertain(f"cannot run {cmd[0]}: {error}") from error


def _still(ffmpeg: str, video: Path, frame: int) -> bytes:
    done = _run([ffmpeg, "-v", "error", "-nostdin", "-i", str(video), "-vf", "select=eq(n\\,%d)" % frame,
                 "-vframes", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"])
    if done.returncode or not done.stdout:
        raise Uncertain(f"still extraction failed at frame {frame}: {done.stderr.decode('utf-8', 'replace')[-300:]}")
    return done.stdout


def grade_video(domain: dict, req: GradeRequest) -> dict:
    """Run one grade; returns the receipt (also written once beside the output)."""
    out = Path(req.out).resolve()  # ffmpeg chạy cwd=workdir tạm: mọi đường dẫn ghi phải tuyệt đối
    receipt_path = out.with_name(out.stem + ".grade-receipt.json")
    if out.suffix.lower() != ".mp4":
        raise Refused(f"output must be an .mp4 path: {out}")
    if out.exists() or receipt_path.exists():
        raise Refused(f"refusing to overwrite: output or receipt exists: {out}")
    if type(req.crf) is not int or not 0 <= req.crf <= 51:
        raise Refused("crf must be an integer 0..51")
    try:
        params = GradeParams(grain=req.grain, halation=req.halation, soften=req.soften)
    except ValueError as error:
        raise Refused(f"GRADE_PARAM_INVALID: {error}") from error
    policy = grade_policy(domain)                                       # gate 1: domain declares post.grade
    lut_info = require_lut(policy, Path(req.lut), req.lut_sha256)       # gate 2: LUT declared + sha bytes
    cube = parse_cube(Path(req.lut))                                    # gate 3: well-formed 3D cube
    video = Path(req.video).resolve()  # ffmpeg runs with cwd=workdir: every path it reads must be absolute
    if not video.is_file():
        raise Refused(f"video input not found: {video}")
    info: VideoInfo = probe(video, req.ffprobe)
    if info.nb_frames < 1:
        raise Refused("video has no frames")
    still_frame = info.nb_frames // 2 if req.still_frame is None else int(req.still_frame)
    if not 0 <= still_frame < info.nb_frames:
        raise Refused(f"still frame {still_frame} outside 0..{info.nb_frames - 1}")
    inputs = {"video": {"path": str(video), "sha256": sha256_file(video), "probe": info.as_dict()},
              "lut": {**lut_info, "size": cube.size}}

    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.partial{out.suffix}")
    workdir = Path(tempfile.mkdtemp(prefix="jjv-grade-"))
    try:
        shutil.copyfile(Path(req.lut), workdir / "grade.cube")
        matrix = matrix_for(info.color_space)
        in_range = "pc" if info.color_range == "pc" else "tv"
        graph = build_graph(params, "grade.cube", matrix=matrix, in_range=in_range, tags=_tags(info))
        maps = ["-map", "[vout]"] + (["-map", "0:a:0", "-c:a", "copy"] if info.audio_codec else [])
        cmd = [req.ffmpeg, "-y", "-v", "error", "-nostdin", "-i", str(video), "-filter_complex", graph, *maps,
               "-c:v", "libx264", "-preset", "slow", "-crf", str(req.crf),
               "-movflags", "+faststart", str(partial)]
        done = _run(cmd, cwd=str(workdir))
        if done.returncode:
            raise Uncertain(f"ffmpeg grade rc={done.returncode}: {done.stderr.decode('utf-8', 'replace')[-800:]}")
        after_info = probe(partial, req.ffprobe)
        if (after_info.nb_frames, after_info.width, after_info.height) != (info.nb_frames, info.width, info.height):
            raise Refused("grade changed the frame count or size")
        if info.audio_codec:
            pre, post = audio_packets(req.ffmpeg, video), audio_packets(req.ffmpeg, partial)
            if pre != post:
                raise Refused("AUDIO_PACKETS_CHANGED: audio packet hashes differ after stream copy")
            audio = {"mode": "copy", "packets_pre": pre, "packets_post": post, "packets_equal": True}
        else:
            audio = {"mode": "none", "packets_equal": None, "note": "source has no audio stream"}
        if sha256_file(video) != inputs["video"]["sha256"] or sha256_file(Path(req.lut)) != lut_info["sha256"]:
            raise Refused("an input changed during the grade")
        try:
            os.link(partial, out)
        except FileExistsError:
            raise Refused(f"refusing to overwrite: {out}") from None
    finally:
        partial.unlink(missing_ok=True)
        shutil.rmtree(workdir, ignore_errors=True)

    before_png = _still(req.ffmpeg, video, still_frame)
    after_png = _still(req.ffmpeg, out, still_frame)
    stem = out.stem
    outputs = {
        "video": {"path": str(out), "sha256": sha256_file(out), "probe": after_info.as_dict()},
        "before_still": {"path": str(out.with_name(stem + "_grade_before.png")), "frame": still_frame,
                         "sha256": write_once(out.with_name(stem + "_grade_before.png"), before_png)},
        "after_still": {"path": str(out.with_name(stem + "_grade_after.png")), "frame": still_frame,
                        "sha256": write_once(out.with_name(stem + "_grade_after.png"), after_png)},
    }
    receipt = {
        "schema": RECEIPT_SCHEMA, "cpu_only": True, "domain_id": policy.domain_id,
        "tool": {"ffmpeg": ffmpeg_version(req.ffmpeg)},
        "inputs": inputs,
        "params": params.as_dict(),
        "render": {"filter_chain": graph, "interp": "tetrahedral", "crf": req.crf, "preset": "slow",
                   "colour_matrix": matrix, "range_in": in_range, "range_work": "pc (rgb24)", "range_out": "tv"},
        "gates": {"domain": {"pass": True, "domain_id": policy.domain_id}, "lut": {"pass": True, "name": lut_info["name"]},
                  "audio": audio},
        "still_frame_index": still_frame,
        "outputs": outputs,
        "status": "RENDERED_PENDING_REVIEW",
    }
    receipt = json.loads(json.dumps(receipt))
    write_json_once(receipt_path, receipt, mode="utf8")
    return receipt
