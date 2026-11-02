"""Ghép logo thật lên NHIỀU điểm đánh dấu mỗi shot (mũ, ngực áo, cổ áo...), mỗi điểm bám và qua cổng RIÊNG.

Thứ tự hợp đồng: cổng domain -> manifest -> sha từng biến thể asset -> (mới mở video) -> bám từng mark ->
cổng bám PER MARK (mark hỏng bị bỏ + ghi, mark khác vẫn chạy) -> encode (audio stream copy) -> cổng mép PER MARK
trên bản đã giải mã (mark hỏng mép bị bỏ rồi encode lại không có nó) -> publish write-once. Không mark nào đạt = Refused.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from ...captions.burn import audio_packets
from ...core.errors import Refused, Uncertain
from ...core.io import sha256_file, write_json_once
from . import PORTED_FROM
from .edgecheck import EdgeCheckParams, EdgeGateError, edge_check, edge_gate
from .mark_render import MarkRenderParams, render_mark
from .marks import Mark, MarkAsset, load_manifest, load_variant
from .policy import logo_policy
from .run import Window, _check_box, _frame_set, _load_frames, _quads, _summary, _window_for, _write_png
from .strip import build_strip
from .tracker import TRACKER_TYPE, TrackGateError, TrackParams, box_corners, gate_tracks, track_sequence
from .video_io import FrameWriter, VideoInfo, compare_outside_roi, ffmpeg_version, iter_frames, probe

RECEIPT_SCHEMA = "jjv/post-logo-multimark-receipt/v1"
NO_MARK_APPLIED = "NO_MARK_APPLIED"


@dataclass(frozen=True)
class MarksRequest:
    video: Path
    marks: Path
    out: Path
    ffmpeg: str
    ffprobe: str
    repo_root: Path
    crf: int = 10
    preset: str = "slow"
    rng_seed: int = 20261101
    track_window: int = 512
    strip_frames: tuple[int, ...] | None = None
    strip_size: int = 256
    track: TrackParams = TrackParams()
    render: MarkRenderParams = MarkRenderParams()
    edge_slack: float = 1.0


@dataclass(frozen=True)
class Plan:
    mark: Mark
    asset: MarkAsset
    window: Window
    box_quads: list
    logo_quads: list
    tracks: list
    track_params: TrackParams
    render: MarkRenderParams
    seed_logo_quad: np.ndarray
    weights: list | None = None   # per-frame 0..1 when the mark is partial (fade in/out), else None


def _seed_quad(mark: Mark, asset: MarkAsset) -> np.ndarray:
    """Quad TL,TR,BR,BL của logo mới tại frame seed: quad của manifest, hoặc vừa khít (contain) trong seed box."""
    if mark.quad is not None:
        return np.array(mark.quad, np.float64)
    x, y, w, h = mark.seed_box
    nw, nh = (h * asset.aspect, h) if w / h > asset.aspect else (w, w / asset.aspect)
    return box_corners((x + w / 2 - nw / 2, y + h / 2 - nh / 2, nw, nh))


def _window_size(mark: Mark, req: MarksRequest, ring: float) -> int:
    auto = int(max(mark.seed_box[2], mark.seed_box[3]) * (ring + 1.5))
    return mark.track_window or max(req.track_window, auto)


def _collect(video: Path, info: VideoInfo, wins: dict[str, Window], keep: set[int],
             ffmpeg: str) -> tuple[dict[str, list[np.ndarray]], dict[int, np.ndarray]]:
    grays: dict[str, list[np.ndarray]] = {k: [] for k in wins}
    kept: dict[int, np.ndarray] = {}
    count = 0
    for idx, frame in enumerate(iter_frames(video, info, ffmpeg)):
        count += 1
        gray = None
        for key, win in wins.items():
            if gray is None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grays[key].append(gray[win.y:win.y + win.size, win.x:win.x + win.size].copy())
        if idx in keep:
            kept[idx] = frame.copy()
    if count != info.nb_frames:
        raise Uncertain(f"decoded {count} frames, ffprobe counted {info.nb_frames}")
    return grays, kept


def _margin_violations(quads: list, win: Window, info: VideoInfo, mark: Mark, ring: float, lk_win: int) -> list[int]:
    """Hộp bám phải cách mép cửa sổ ít nhất phần vành đặc trưng cần ((ring-1)/2 x cạnh dài + lk_win).
    Cạnh cửa sổ trùng cạnh khung hình thì không xét (ngoài khung không còn gì để bám)."""
    margin = (ring - 1) / 2 * max(mark.seed_box[2], mark.seed_box[3]) + lk_win
    left, top = 0 if win.x == 0 else margin, 0 if win.y == 0 else margin
    right = 0 if win.x + win.size >= info.width else margin
    bottom = 0 if win.y + win.size >= info.height else margin
    return [i for i, q in enumerate(quads)
            if (q[:, 0].min() < win.x + left or q[:, 1].min() < win.y + top
                or q[:, 0].max() > win.x + win.size - right or q[:, 1].max() > win.y + win.size - bottom)]


def _run_weights(tracks: list, margin_bad: list[int], logo_quads: list, info: VideoInfo, mark: Mark) -> list[float]:
    """Mark từng phần: chỉ vẽ trên đoạn frame liên tục TỐT quanh frame seed (bám thật, trong khung, không chạm biên cửa sổ);
    cuối đoạn mờ dần trong fade_frames; ngoài đoạn = 0 (không vẽ lơ lửng). Đoạn ngắn hơn min_run thì từ chối."""
    bad = set(margin_bad)
    for t, q in zip(tracks, logo_quads):
        off = (q[:, 0].min() < 0 or q[:, 1].min() < 0 or q[:, 0].max() > info.width or q[:, 1].max() > info.height)
        if t.status == "held" or off or (t.status != "seed" and t.ncc_seed < mark.min_ncc):
            bad.add(t.index)
    lo = hi = mark.seed_frame
    if lo in bad:
        raise TrackGateError("SEED_FRAME_UNTRACKABLE", f"seed frame {lo} is itself outside the valid track", {})
    while lo - 1 >= 0 and lo - 1 not in bad:
        lo -= 1
    while hi + 1 < len(tracks) and hi + 1 not in bad:
        hi += 1
    if hi - lo + 1 < mark.min_run:
        raise TrackGateError("TRACK_RUN_TOO_SHORT", f"valid run f{lo}-f{hi} shorter than min_run {mark.min_run}",
                             {"run": [lo, hi], "bad_frames": len(bad)})
    weights = [0.0] * len(tracks)
    for i in range(lo, hi + 1):
        w = 1.0
        if lo > 0 and mark.fade_frames:
            w = min(w, (i - lo + 1) / (mark.fade_frames + 1))
        if hi < len(tracks) - 1 and mark.fade_frames:
            w = min(w, (hi - i + 1) / (mark.fade_frames + 1))
        weights[i] = round(w, 4)
    return weights


def _track_mark(mark: Mark, asset: MarkAsset, win: Window, gray: list[np.ndarray], req: MarksRequest,
                tparams: TrackParams, info: VideoInfo) -> Plan:
    """Bám một mark rồi qua cổng bám + cổng mép cửa sổ; ném TrackGateError nếu hỏng."""
    box_local = (mark.seed_box[0] - win.x, mark.seed_box[1] - win.y, mark.seed_box[2], mark.seed_box[3])
    tracks = track_sequence(gray, mark.seed_frame, box_local, tparams)
    box_quads = _quads(tracks, box_corners(mark.seed_box), win)
    seed_quad = _seed_quad(mark, asset)
    margin = _margin_violations(box_quads, win, info, mark, tparams.ring_scale, tparams.lk_win)
    logo_quads = _quads(tracks, seed_quad, win)
    weights = None
    if mark.partial:
        weights = _run_weights(tracks, margin, logo_quads, info, mark)
    else:
        gate_tracks(tracks, margin, tparams)
    return Plan(mark, asset, win, box_quads, logo_quads, tracks, tparams,
                req.render.with_overrides(mark.render_overrides), seed_quad, weights)


def _skip(mark: Mark, code: str, message: str, evidence: dict | None = None) -> dict:
    return {"id": mark.id, "type": mark.type, "status": "skipped", "code": code, "message": message[:400],
            "evidence": {k: v for k, v in (evidence or {}).items() if k != "per_frame"}}


def _encode(video: Path, info: VideoInfo, partial: Path, plans: list[Plan], req: MarksRequest,
            roi_frames: set[int]) -> tuple[list[str], dict[str, dict], dict[int, tuple[int, int, int, int]]]:
    """Mỗi mark có RNG riêng (seed + vị trí trong manifest) nên bỏ một mark không làm đổi hạt của mark khác."""
    rngs = {p.mark.id: np.random.default_rng([req.rng_seed, i]) for i, p in enumerate(plans)}
    stats: dict[str, dict] = {p.mark.id: {"removed_px": [], "surface_mean_l": []} for p in plans}
    rois: dict[int, list[tuple]] = {}
    writer = FrameWriter(partial, video, info, req.crf, req.ffmpeg, preset=req.preset)
    for idx, frame in enumerate(iter_frames(video, info, req.ffmpeg)):
        for p in plans:
            w = 1.0 if p.weights is None else p.weights[idx]
            if w <= 0.0:
                continue
            drawn, dbg = render_mark(frame, p.box_quads[idx], p.logo_quads[idx], p.asset, p.mark, p.render, rngs[p.mark.id])
            frame = drawn if w >= 1.0 else np.clip(frame * (1 - w) + drawn * w, 0, 255).astype(np.uint8)
            stats[p.mark.id]["removed_px"].append(dbg["removed_px"])
            stats[p.mark.id]["surface_mean_l"].append(dbg["surface_mean_l"])
            if idx in roi_frames:
                rois.setdefault(idx, []).append(tuple(dbg["roi"]))
        writer.write(frame)
    writer.close()
    if writer.count != info.nb_frames:
        raise Uncertain(f"encoded {writer.count} frames, expected {info.nb_frames}")
    union = {i: (min(r[0] for r in v), min(r[1] for r in v), max(r[2] for r in v), max(r[3] for r in v))
             for i, v in rois.items()}
    return writer.cmd, stats, union


def _edge_params(p: Plan, info: VideoInfo) -> EdgeCheckParams:
    side = int(max(96, 2.4 * max(p.mark.seed_box[2], p.mark.seed_box[3])))
    return EdgeCheckParams(crop=min(side, info.width, info.height))


def _edge_failures(plans: list[Plan], info: VideoInfo, before: dict, after: dict, slack: float) -> tuple[dict, dict]:
    failing, reports = {}, {}
    for p in plans:
        params = _edge_params(p, info)
        results = [edge_check(i, before[i], after[i], tuple(p.box_quads[i].mean(axis=0)),
                              [q for o in plans for q in (o.box_quads[i], o.logo_quads[i])], params) for i in sorted(before)]
        try:
            reports[p.mark.id] = edge_gate(results, slack)
        except EdgeGateError as error:
            failing[p.mark.id] = error
    return failing, reports


def _stack(images: list[np.ndarray]) -> np.ndarray:
    width = max(i.shape[1] for i in images)
    pad = [cv2.copyMakeBorder(i, 0, 6, 0, width - i.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for i in images]
    return np.vstack(pad)


def _mark_receipt(p: Plan) -> dict:
    return {"id": p.mark.id, "type": p.mark.type, "status": "applied", "mark": p.mark.as_dict(),
            "asset": p.asset.as_dict(), "seed_logo_quad": p.seed_logo_quad.round(2).tolist(),
            "track_window": {"x": p.window.x, "y": p.window.y, "size": p.window.size},
            "tracker": {"params": p.track_params.as_dict(), "summary": _summary(p.tracks)},
            "render_params": p.render.as_dict(),
            "applied_frames": None if p.weights is None else {
                "first": next(i for i, w in enumerate(p.weights) if w > 0), "last": max(i for i, w in enumerate(p.weights) if w > 0),
                "full_weight": sum(1 for w in p.weights if w >= 1.0), "weights_at_ends": [w for w in p.weights if 0 < w < 1]}}


def composite_marks(domain: dict, req: MarksRequest) -> dict:
    out = Path(req.out)
    receipt_path = out.with_name(out.stem + ".logo-receipt.json")
    if out.suffix.lower() != ".mp4":
        raise Refused(f"output must be an .mp4 path: {out}")
    if out.exists() or receipt_path.exists():
        raise Refused(f"refusing to overwrite: output or receipt exists: {out}")
    if type(req.crf) is not int or not 0 <= req.crf <= 51:
        raise Refused("crf must be 0..51")
    policy = logo_policy(domain)                                               # gate 1: domain enables the step
    marks, manifest = load_manifest(req.marks)                                 # gate 2: manifest valid
    assets = {v: load_variant(policy, v, req.repo_root) for v in sorted({m.asset for m in marks})}  # gate 3: sha per variant
    video = Path(req.video)
    if not video.is_file():
        raise Refused(f"video input not found: {video}")
    info = probe(video, req.ffprobe)
    if info.nb_frames < 2:
        raise Refused(f"video has {info.nb_frames} frame(s); nothing to track")
    for m in marks:
        _check_box(m.seed_box, info, f"mark {m.id} seed box")
        if not 0 <= m.seed_frame < info.nb_frames:
            raise Refused(f"mark {m.id}: seed frame {m.seed_frame} outside 0..{info.nb_frames - 1}")
    n = info.nb_frames - 1
    strip_frames = _frame_set(req.strip_frames, [round(f * n) for f in (0.08, 0.36, 0.64, 0.92)], info, "strip frames")
    inputs = {"video": {"path": str(video), "sha256": sha256_file(video), "probe": info.as_dict()}, "manifest": manifest,
              "assets": {k: v.as_dict() for k, v in assets.items()}}
    tparams = {m.id: replace(req.track, ring_scale=m.ring_scale or req.track.ring_scale) for m in marks}
    wins = {m.id: _window_for(m.seed_box, info, _window_size(m, req, tparams[m.id].ring_scale)) for m in marks}
    grays, kept = _collect(video, info, wins, set(strip_frames), req.ffmpeg)
    plans: list[Plan] = []
    skipped: list[dict] = []
    for m in marks:                                                            # gate 4: track gate, PER MARK
        try:
            plans.append(_track_mark(m, assets[m.asset], wins[m.id], grays[m.id], req, tparams[m.id], info))
        except TrackGateError as error:
            skipped.append(_skip(m, error.code, str(error), error.details))
    del grays
    out.parent.mkdir(parents=True, exist_ok=True)
    published = False
    for _ in range(len(marks) + 1):
        if not plans:
            raise Refused(f"{NO_MARK_APPLIED}: every mark failed its gate; nothing published",
                          evidence={"skipped": skipped})
        partial = out.with_name(f".{out.stem}.{uuid.uuid4().hex}.partial{out.suffix}")
        try:
            cmd, stats, union = _encode(video, info, partial, plans, req, set(strip_frames))
            after_info = probe(partial, req.ffprobe)
            if (after_info.nb_frames, after_info.width, after_info.height) != (info.nb_frames, info.width, info.height):
                raise Refused("encode changed the frame count or size")
            if info.audio_codec:
                pre, post = audio_packets(req.ffmpeg, video), audio_packets(req.ffmpeg, partial)
                if pre != post:
                    raise Refused("AUDIO_PACKETS_CHANGED: audio packet hashes differ after stream copy")
                audio = {"mode": "copy", "packets_pre": pre, "packets_post": post, "packets_equal": True}
            else:
                audio = {"mode": "none", "packets_equal": None, "note": "source has no audio stream"}
            after = _load_frames(partial, info, strip_frames, req.ffmpeg)
            failing, edge_reports = _edge_failures(plans, info, kept, after, req.edge_slack)  # gate 5: edge, PER MARK
            if failing:
                skipped += [_skip(p.mark, "EDGE_BAND_FAIL", str(failing[p.mark.id]), failing[p.mark.id].details)
                            for p in plans if p.mark.id in failing]
                plans = [p for p in plans if p.mark.id not in failing]
                continue
            integrity = compare_outside_roi(video, partial, info, union, req.ffmpeg)
            if sha256_file(video) != inputs["video"]["sha256"]:
                raise Refused("an input changed during the render")
            try:
                os.link(partial, out)
            except FileExistsError:
                raise Refused(f"refusing to overwrite: {out}") from None
            published = True
        finally:
            partial.unlink(missing_ok=True)
        break
    if not published:
        raise Refused(f"{NO_MARK_APPLIED}: marks kept failing the edge gate", evidence={"skipped": skipped})
    stem = out.stem
    outputs = {"video": {"path": str(out), "sha256": sha256_file(out), "probe": after_info.as_dict()}}
    rows = []
    for p in plans:
        centers = {i: tuple(p.box_quads[i].mean(axis=0)) for i in strip_frames}
        rows.append(build_strip({i: kept[i] for i in strip_frames}, after, centers, req.strip_size, 1))
        outputs[f"strip_4x_{p.mark.id}"] = {**_write_png(out.with_name(f"{stem}_strip_4x_{p.mark.id}.png"), build_strip(
            {i: kept[i] for i in strip_frames}, after, centers, min(req.strip_size, 96), 4)), "frames": strip_frames}
        outputs[f"strip_1to1_{p.mark.id}"] = {**_write_png(out.with_name(f"{stem}_strip_1to1_{p.mark.id}.png"), rows[-1]),
                                              "frames": strip_frames}
    outputs["strip_1to1"] = {**_write_png(out.with_name(stem + "_strip_1to1.png"), _stack(rows)), "frames": strip_frames}
    applied = []
    for p in plans:
        entry = _mark_receipt(p)
        entry["render_stats"] = {k: {"min": min(v), "max": max(v), "mean": round(float(np.mean(v)), 2)} for k, v in stats[p.mark.id].items()}
        entry["edge_gate"] = edge_reports[p.mark.id]
        applied.append(entry)
    receipt = {
        "schema": RECEIPT_SCHEMA, "ported_from": PORTED_FROM, "cpu_only": True, "domain_id": policy.domain_id,
        "tool": {"ffmpeg": ffmpeg_version(req.ffmpeg), "opencv": cv2.__version__, "numpy": np.__version__},
        "inputs": inputs, "tracker_type": TRACKER_TYPE,
        "marks_applied": [m["id"] for m in applied], "marks_skipped": [{"id": s["id"], "code": s["code"]} for s in skipped],
        "marks": applied + skipped,
        "gates": {"audio": audio, "edge_slack": req.edge_slack},
        "render": {"rng_seed": req.rng_seed, "crf": req.crf, "preset": req.preset, "encode_cmd": cmd},
        "integrity_vs_input": {"note": "MAD source vs output; roi = union of all applied marks' ROI", "frames": integrity},
        "outputs": outputs, "status": "RENDERED_PENDING_REVIEW",
    }
    receipt = json.loads(json.dumps(receipt, default=str))
    write_json_once(receipt_path, receipt, mode="utf8")
    return receipt
