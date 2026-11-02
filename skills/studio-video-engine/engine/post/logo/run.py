"""Một lần chạy ghép logo: cổng domain/sha -> seed box -> bám -> cổng bám -> ghép + encode -> audio -> cổng mép -> ghi một lần.

Thứ tự là hợp đồng: từ chối domain, sha logo, seed box và cổng bám xảy ra TRƯỚC khi encode một frame nào; cổng mép
(đo trên bản đã giải mã, như tool gốc) xảy ra trước khi output được publish (file tạm bị xoá, không receipt).
"""
from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ...captions.burn import audio_packets
from ...core.errors import Refused, Uncertain
from ...core.io import sha256_file, write_json_once, write_once
from . import PORTED_FROM
from .asset import LogoAsset, load_icon
from .detect import Detection, detect_seed
from .edgecheck import EdgeCheckParams, edge_check, edge_gate, stack_results
from .policy import LogoPolicy, logo_policy, require_asset
from .render import RenderParams, composite_frame, sample_thread_color
from .strip import build_strip, build_track_preview
from .tracker import (TRACKER_TYPE, FrameTrack, TrackParams, box_corners, decompose, gate_tracks, track_sequence,
                      transform_points)
from .video_io import FrameWriter, VideoInfo, compare_outside_roi, ffmpeg_version, iter_frames, probe

RECEIPT_SCHEMA = "jjv/post-logo-receipt/v1"
Box = tuple[int, int, int, int]
Compositor = Callable[..., tuple]


@dataclass(frozen=True)
class Window:
    x: int
    y: int
    size: int


@dataclass(frozen=True)
class LogoRequest:
    """Inputs of one run. Tool thresholds keep the ported defaults; every value lands in the receipt."""
    video: Path
    logo: Path
    out: Path
    ffmpeg: str
    ffprobe: str
    logo_sha256: str | None = None
    seed_frame: int | None = None
    seed_box: Box | None = None
    logo_rect: Box | None = None
    logo_rotation: float = 0.0
    logo_skew: float = 0.0
    thread_rgb: tuple[int, int, int] | None = None  # None = sample the old mark's dark core at the seed frame
    track_window: int = 512
    crf: int = 10
    rng_seed: int = 20261031
    strip_frames: tuple[int, ...] | None = None
    preview_frames: tuple[int, ...] | None = None
    track: TrackParams = TrackParams()
    render: RenderParams = RenderParams()
    edge: EdgeCheckParams = EdgeCheckParams()
    edge_slack: float = 1.0


@dataclass(frozen=True)
class Seed:
    frame: int
    box: Box
    logo_rect: Box | None
    source: str  # "cli" | "auto"
    detection: Detection | None


def _check_box(box: Box, info: VideoInfo, label: str) -> Box:
    if len(box) != 4 or not all(isinstance(v, int) and not isinstance(v, bool) for v in box):
        raise Refused(f"{label} must be four integers x,y,w,h")
    x, y, w, h = box
    if w < 2 or h < 2 or x < 0 or y < 0 or x + w > info.width or y + h > info.height:
        raise Refused(f"{label} {list(box)} lies outside the {info.width}x{info.height} frame or is too small")
    return box


def _frame_set(values: tuple[int, ...] | None, default: list[int], info: VideoInfo, label: str) -> list[int]:
    chosen = sorted(set(values)) if values else sorted(set(default))
    bad = [v for v in chosen if not 0 <= v < info.nb_frames]
    if bad:
        raise Refused(f"{label} outside 0..{info.nb_frames - 1}: {bad}")
    return chosen


def _window_for(box: Box, info: VideoInfo, size: int) -> Window:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    size = min(size, info.width, info.height)
    x = int(min(max(0, cx - size / 2), info.width - size))
    y = int(min(max(0, cy - size / 2), info.height - size))
    return Window(x, y, size)


def _seed_logo_quad(rect: Box | None, box: Box, icon: LogoAsset, rotation: float, skew: float) -> np.ndarray:
    if rect is not None:
        x, y, w, h = rect
    else:
        h = box[3] * 0.6
        w = h * icon.aspect
        x, y = box[0] + box[2] / 2 - w / 2, box[1] + box[3] / 2 - h / 2
    quad = box_corners((x, y, w, h))
    center = quad.mean(axis=0)
    if skew:
        quad[1, 1] = center[1] - (h / 2) * (1 - skew)
        quad[2, 1] = center[1] + (h / 2) * (1 - skew)
    theta = math.radians(rotation)
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    return (quad - center) @ rot.T + center


def _collect_windows(video: Path, info: VideoInfo, win: Window, keep: set[int],
                     ffmpeg: str) -> tuple[list[np.ndarray], dict[int, np.ndarray]]:
    windows: list[np.ndarray] = []
    kept: dict[int, np.ndarray] = {}
    for idx, frame in enumerate(iter_frames(video, info, ffmpeg)):
        crop = frame[win.y:win.y + win.size, win.x:win.x + win.size]
        windows.append(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        if idx in keep:
            kept[idx] = frame.copy()
    if len(windows) != info.nb_frames:
        raise Uncertain(f"decoded {len(windows)} frames, ffprobe counted {info.nb_frames}")
    return windows, kept


def _quads(tracks: list[FrameTrack], seed_pts: np.ndarray, win: Window) -> list[np.ndarray]:
    offset = np.array([win.x, win.y], dtype=np.float64)
    return [transform_points(t.matrix, seed_pts - offset) + offset for t in tracks]


def _margin_violations(quads: list[np.ndarray], win: Window, margin: int) -> list[int]:
    return [idx for idx, quad in enumerate(quads)
            if (quad[:, 0].min() < win.x + margin or quad[:, 1].min() < win.y + margin
                or quad[:, 0].max() > win.x + win.size - margin or quad[:, 1].max() > win.y + win.size - margin)]


def _summary(tracks: list[FrameTrack]) -> dict:
    tracked = [t for t in tracks if t.status == "tracked"]
    conf = [t.confidence for t in tracked]
    ncc = [t.ncc_seed for t in tracks if t.status != "seed"]
    return {
        "frames_total": len(tracks), "frames_tracked": len(tracked),
        "frames_held": [t.index for t in tracks if t.status == "held"],
        "frames_interpolated": [t.index for t in tracks if t.status == "interpolated"],
        "confidence_min": round(min(conf), 4) if conf else None,
        "confidence_mean": round(float(np.mean(conf)), 4) if conf else None,
        "inliers_min": min((t.inliers for t in tracked), default=None),
        "ncc_seed_min": round(min(ncc), 4) if ncc else None,
        "ncc_peak_min": round(min(t.ncc_peak for t in tracks), 4),
        "reanchor_abs_max_px": [round(max(abs(t.reanchor_dx) for t in tracks), 2),
                                round(max(abs(t.reanchor_dy) for t in tracks), 2)],
        "rotation_deg_range": [round(math.degrees(min(decompose(t.matrix)[2] for t in tracks)), 2),
                               round(math.degrees(max(decompose(t.matrix)[2] for t in tracks)), 2)],
    }


def _resolve_seed(req: LogoRequest, policy: LogoPolicy, info: VideoInfo, icon: LogoAsset, video: Path) -> Seed:
    if req.seed_box is not None:
        frame = req.seed_frame if req.seed_frame is not None else 0
        if not 0 <= frame < info.nb_frames:
            raise Refused(f"seed frame {frame} outside 0..{info.nb_frames - 1}")
        rect = _check_box(req.logo_rect, info, "logo rect") if req.logo_rect is not None else None
        return Seed(frame, _check_box(req.seed_box, info, "seed box"), rect, "cli", None)
    if req.seed_frame is not None:
        raise Refused("--seed-frame needs --seed-box; auto-detection chooses the seed frame itself")
    if policy.detect is None:
        raise Refused("SEED_BOX_REQUIRED: the domain declares no post.logo_composite.detect block; pass --seed-box")
    count = min(policy.detect.search_frames, info.nb_frames)
    frames = list(iter_frames(video, info, req.ffmpeg, count))
    if len(frames) != count:
        raise Uncertain(f"decoded {len(frames)} of the first {count} frames for detection")
    detection = detect_seed(frames, policy.detect, icon.aspect)
    rect = _check_box(req.logo_rect, info, "logo rect") if req.logo_rect is not None else detection.rect
    return Seed(detection.frame, detection.box, rect, "auto", detection)


def _load_frames(video: Path, info: VideoInfo, wanted: list[int], ffmpeg: str) -> dict[int, np.ndarray]:
    return {i: f.copy() for i, f in enumerate(iter_frames(video, info, ffmpeg, max(wanted) + 1)) if i in wanted}


def _png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise Uncertain("PNG encode failed")
    return buffer.tobytes()


def _write_png(path: Path, image: np.ndarray) -> dict:
    payload = _png(image)
    return {"path": str(path), "sha256": write_once(path, payload)}


def composite_logo(domain: dict, req: LogoRequest, *, compositor: Compositor = composite_frame) -> dict:
    """Run one composite; returns the receipt (also written once beside the output)."""
    out = Path(req.out)
    receipt_path = out.with_name(out.stem + ".logo-receipt.json")
    if out.suffix.lower() != ".mp4":
        raise Refused(f"output must be an .mp4 path: {out}")
    if out.exists() or receipt_path.exists():
        raise Refused(f"refusing to overwrite: output or receipt exists: {out}")
    if type(req.crf) is not int or not 0 <= req.crf <= 51 or type(req.track_window) is not int or req.track_window < 64:
        raise Refused("crf must be 0..51 and track window >= 64")
    policy = logo_policy(domain)                                      # gate 1: the domain must enable the step
    asset = require_asset(policy, Path(req.logo), req.logo_sha256)   # gate 2: the logo bytes match the declared sha
    video = Path(req.video)
    if not video.is_file():
        raise Refused(f"video input not found: {video}")
    info = probe(video, req.ffprobe)
    if info.nb_frames < 2:
        raise Refused(f"video has {info.nb_frames} frame(s); nothing to track")
    icon = load_icon(Path(req.logo))
    inputs = {"video": {"path": str(video), "sha256": sha256_file(video), "probe": info.as_dict()}, "logo": asset}
    seed = _resolve_seed(req, policy, info, icon, video)              # gate 3: SEED_BOX_NOT_FOUND / _AMBIGUOUS
    n = info.nb_frames - 1
    strip_frames = _frame_set(req.strip_frames, [round(0.1 * n), round(0.5 * n), round(0.9 * n)], info, "strip frames")
    preview_frames = _frame_set(req.preview_frames, [int(round(v)) for v in np.linspace(0, n, 7)], info, "preview frames")
    win = _window_for(seed.box, info, req.track_window)
    keep = set(strip_frames) | set(preview_frames) | {seed.frame}
    windows, kept = _collect_windows(video, info, win, keep, req.ffmpeg)
    box_local = (seed.box[0] - win.x, seed.box[1] - win.y, seed.box[2], seed.box[3])
    tracks = track_sequence(windows, seed.frame, box_local, req.track)
    box_quads = _quads(tracks, box_corners(seed.box), win)
    seed_logo_quad = _seed_logo_quad(seed.logo_rect, seed.box, icon, req.logo_rotation, req.logo_skew)
    logo_quads = _quads(tracks, seed_logo_quad, win)
    margin_bad = _margin_violations(box_quads, win, int(max(seed.box[2], seed.box[3]) * req.track.ring_scale))
    track_report = {"pass": True, **gate_tracks(tracks, margin_bad, req.track)}  # gate 4: raises TrackGateError
    if req.thread_rgb is None:
        try:
            thread_rgb = sample_thread_color(kept[seed.frame], box_quads[seed.frame])
        except ValueError as error:
            raise Refused(f"THREAD_COLOR_UNSAMPLED: {error}; pass --thread-rgb") from error
        thread_how = "auto: median BGR of the dark core (<0.45 x box median) of the old mark at the seed frame"
    else:
        thread_rgb, thread_how = tuple(int(v) for v in req.thread_rgb), "cli"
    rparams = replace(req.render, thread_rgb=thread_rgb)
    rng = np.random.default_rng(req.rng_seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.partial{out.suffix}")
    try:
        writer = FrameWriter(partial, video, info, req.crf, req.ffmpeg)
        debug_rows: list[dict] = []
        for idx, frame in enumerate(iter_frames(video, info, req.ffmpeg)):
            composed, dbg = compositor(frame, box_quads[idx], logo_quads[idx], icon.alpha, rparams, rng)
            writer.write(composed)
            debug_rows.append({"frame": idx, "roi": list(dbg.roi_xyxy), "removed_px": dbg.removed_px,
                               "logo_px": round(dbg.logo_px, 1), "fabric_mean_l": round(dbg.fabric_mean_l, 1)})
        writer.close()
        if writer.count != info.nb_frames:
            raise Uncertain(f"encoded {writer.count} frames, expected {info.nb_frames}")
        after_info = probe(partial, req.ffprobe)
        if (after_info.nb_frames, after_info.width, after_info.height) != (info.nb_frames, info.width, info.height):
            raise Refused("encode changed the frame count or size")
        if info.audio_codec:
            pre, post = audio_packets(req.ffmpeg, video), audio_packets(req.ffmpeg, partial)
            if pre != post:
                raise Refused("AUDIO_PACKETS_CHANGED: audio packet hashes differ after stream copy")
            audio = {"mode": "copy", "packets_pre": pre, "packets_post": post, "packets_equal": True,
                     "method": "sha256 of ordered binary SHA256 packet payload digests per stream; no timestamps"}
        else:
            audio = {"mode": "none", "packets_equal": None, "note": "source has no audio stream"}
        after = _load_frames(partial, info, strip_frames, req.ffmpeg)
        before = {i: kept[i] for i in strip_frames}
        centers = {i: tuple(box_quads[i].mean(axis=0)) for i in strip_frames}
        edge_results = [edge_check(i, before[i], after[i], centers[i], [box_quads[i], logo_quads[i]], req.edge)
                        for i in strip_frames]
        edge_report = edge_gate(edge_results, req.edge_slack)       # gate 5: raises EdgeGateError before publish
        rois = {row["frame"]: tuple(row["roi"]) for row in debug_rows if row["frame"] in strip_frames}
        integrity = compare_outside_roi(video, partial, info, rois, req.ffmpeg)
        if sha256_file(video) != inputs["video"]["sha256"] or sha256_file(Path(req.logo)) != asset["sha256"]:
            raise Refused("an input changed during the render")
        try:
            os.link(partial, out)
        except FileExistsError:
            raise Refused(f"refusing to overwrite: {out}") from None
    finally:
        partial.unlink(missing_ok=True)
    stem = out.stem
    outputs = {"video": {"path": str(out), "sha256": sha256_file(out), "probe": after_info.as_dict()}}
    outputs["track_preview"] = {**_write_png(out.with_name(stem + "_track_preview.png"), build_track_preview(
        {i: kept[i] for i in preview_frames}, {i: box_quads[i] for i in preview_frames},
        {i: logo_quads[i] for i in preview_frames})), "frames": preview_frames}
    outputs["strip_1to1"] = {**_write_png(out.with_name(stem + "_strip_1to1.png"),
                                          build_strip(before, after, centers, 128, 1)), "frames": strip_frames}
    outputs["strip_4x"] = {**_write_png(out.with_name(stem + "_strip_4x.png"),
                                        build_strip(before, after, centers, 128, 4)), "frames": strip_frames}
    outputs["edgecheck_6x"] = {**_write_png(out.with_name(stem + "_edgecheck_6x.png"), stack_results(edge_results)),
                               "frames": strip_frames}
    receipt = {
        "schema": RECEIPT_SCHEMA, "ported_from": PORTED_FROM, "cpu_only": True, "domain_id": policy.domain_id,
        "tool": {"ffmpeg": ffmpeg_version(req.ffmpeg), "opencv": cv2.__version__, "numpy": np.__version__},
        "inputs": inputs, "logo_icon": icon.as_dict(),
        "seed": {"frame": seed.frame, "box_xywh": list(seed.box), "source": seed.source,
                 "logo_rect_xywh": list(seed.logo_rect) if seed.logo_rect else None,
                 "logo_rect_source": "cli" if req.logo_rect is not None else ("auto" if seed.source == "auto" else "default 0.6 box height"),
                 "logo_quad_seed": seed_logo_quad.round(2).tolist(), "logo_rotation_deg": req.logo_rotation,
                 "logo_skew": req.logo_skew, "track_window": {"x": win.x, "y": win.y, "size": win.size},
                 "detection": seed.detection.as_dict() if seed.detection else None,
                 "detect_config": policy.detect.as_dict() if (seed.source == "auto" and policy.detect) else None},
        "tracker": {"type": TRACKER_TYPE, "params": req.track.as_dict(), "summary": _summary(tracks),
                    "window_margin_violations": margin_bad,
                    "per_frame": [t.as_dict((win.x, win.y), box_local) for t in tracks]},
        "gates": {"track": track_report, "edge": edge_report, "audio": audio},
        "render": {"params": rparams.as_dict(), "thread_rgb_how": thread_how, "rng_seed": req.rng_seed, "crf": req.crf,
                   "encode_cmd": writer.cmd, "per_frame": debug_rows},
        "integrity_vs_input": {"note": "MAD (0..255) source vs output; outside the ROI only compression noise remains",
                               "frames": integrity},
        "outputs": outputs, "status": "RENDERED_PENDING_REVIEW",
    }
    receipt = json.loads(json.dumps(receipt))  # JSON-native types: the returned receipt equals the stored one
    write_json_once(receipt_path, receipt, mode="utf8")
    return receipt
