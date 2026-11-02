"""Per-shot seam policy: config thresholds, a recorded measurement, and the live metric.

The rule is data: hf8 only when the shot is low-motion AND its mean seam excess clears the
configured trigger; every other case is the plain core.  No threshold is a constant in this file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from ..core.errors import Refused, Uncertain
from ..core.io import read_json
from .seam_blend import BlendGeometry
from .seam_media import iter_gray, require_numpy


@dataclass(frozen=True)
class SeamPolicy:
    """Window shape plus auto-policy thresholds, all read from ``domain.seam_blend``."""

    policy_version: str
    window_half_frames: int
    blend_frames: int
    low_motion_max: float
    excess_trigger: float
    hf8_sigma: float
    allow_clipped_tail: bool
    motion_metric: str
    excess_metric: str
    source: str

    @classmethod
    def from_config(cls, config) -> "SeamPolicy":
        block = (config.domain or {}).get("seam_blend")
        if not isinstance(block, dict):
            raise Refused(
                f"domain {config.domain.get('domain_id')!r} has no seam_blend block; "
                "auto thresholds must come from config, not code")
        try:
            policy = cls(
                policy_version=str(block["policy_version"]),
                window_half_frames=int(block["window_half_frames"]),
                blend_frames=int(block["blend_frames"]),
                low_motion_max=float(block["low_motion_max"]),
                excess_trigger=float(block["excess_trigger"]),
                hf8_sigma=float(block["hf8_sigma"]),
                allow_clipped_tail=bool(block["allow_clipped_tail"]),
                motion_metric=str(block["motion_metric"]),
                excess_metric=str(block["excess_metric"]),
                source="domain.seam_blend",
            )
        except KeyError as error:
            raise Refused(f"domain.seam_blend is missing {error.args[0]!r}") from error
        if policy.window_half_frames < 1 or policy.blend_frames != 2 * policy.window_half_frames:
            raise Refused("domain.seam_blend: blend_frames must equal 2 * window_half_frames")
        for name in ("low_motion_max", "excess_trigger", "hf8_sigma"):
            if not math.isfinite(getattr(policy, name)):
                raise Refused(f"domain.seam_blend: {name} must be finite, got {getattr(policy, name)!r}")
        if policy.low_motion_max <= 0 or policy.hf8_sigma <= 0:
            raise Refused("domain.seam_blend: low_motion_max and hf8_sigma must be positive")
        if policy.motion_metric not in ("native_mean_absdY", "native_mean_abs_dY"):
            raise Refused(f"domain.seam_blend: unknown motion_metric {policy.motion_metric!r}")
        if policy.excess_metric != "mean_excess_peak":
            raise Refused(f"domain.seam_blend: unknown excess_metric {policy.excess_metric!r}")
        return policy

    def thresholds(self) -> dict:
        return {"policy_version": self.policy_version, "policy_source": self.source,
                "window_half_frames": self.window_half_frames,
                "blend_frames": self.blend_frames,
                "low_motion_max": self.low_motion_max,
                "excess_trigger": self.excess_trigger,
                "hf8_sigma": self.hf8_sigma,
                "allow_clipped_tail": self.allow_clipped_tail,
                "motion_metric": self.motion_metric, "excess_metric": self.excess_metric}


def decide_policy(requested: str, policy: SeamPolicy, measurement: dict | None) -> dict:
    """Map an explicit mode or a recorded/measured motion metric to ``core|hf8|lin8``."""
    if requested not in ("auto", "core", "hf8", "lin8"):
        raise Refused(f"unknown mode {requested!r}")
    if requested != "auto":
        return {"mode_requested": requested, "mode": requested,
                "reason": f"explicit --mode {requested}",
                "thresholds": policy.thresholds(), "measurement": measurement}
    if measurement is None:
        raise Refused("auto policy needs a motion measurement (recorded policy document or a build)")
    try:
        motion = float(measurement["native_mean_absdY"])
        excess = float(measurement["mean_excess_peak"])
    except (KeyError, TypeError, ValueError) as error:
        raise Refused(f"measurement is incomplete: {error!r}") from error
    if not (math.isfinite(motion) and math.isfinite(excess)):
        raise Refused(f"measurement must be finite (native_mean_absdY={motion}, mean_excess_peak={excess}): "
                      "a NaN would silently fall through to plain core")
    if motion > policy.low_motion_max:
        mode = "core"
        reason = (f"high motion {motion:.3f} > low_motion_max {policy.low_motion_max}: "
                  "plain core")
    elif excess > policy.excess_trigger:
        mode = "hf8"
        reason = (f"low motion {motion:.3f} <= {policy.low_motion_max} and mean seam excess "
                  f"{excess:.3f} > {policy.excess_trigger}: hf8")
    else:
        mode = "core"
        reason = (f"low motion {motion:.3f} but mean seam excess {excess:.3f} <= "
                  f"{policy.excess_trigger}: plain core")
    return {"mode_requested": requested, "mode": mode, "reason": reason,
            "thresholds": policy.thresholds(), "measurement": measurement}


def measurement_from_policy_doc(path: Path, shot_id: str, plan_sha: str) -> dict | None:
    """Read a policy document (``seam-policy/v001`` rows or a simple ``shots`` map)."""
    document = read_json(path)
    if not isinstance(document, dict):
        raise Uncertain(f"policy document {path} is not a JSON object")
    if document.get("plan_sha256") and document["plan_sha256"] != plan_sha:
        raise Refused(f"policy document {path} was measured on plan "
                      f"{document['plan_sha256'][:16]}, not {plan_sha[:16]}; re-measure")
    rows = document.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("shot") == shot_id:
                if not row.get("measured"):
                    raise Refused(f"policy document row {shot_id} is {row.get('policy')!r} "
                                  "(no measurement)")
                return {
                    "native_mean_absdY": row.get("native_mean_absdY"),
                    "mean_excess_peak": row.get("mean_excess_peak"),
                    "source": str(path), "policy_in_document": row.get("policy"),
                    "confidence": row.get("confidence"),
                }
        raise Refused(f"policy document {path} has no row for {shot_id}")
    shots = document.get("shots")
    if isinstance(shots, dict) and isinstance(shots.get(shot_id), dict):
        return {**shots[shot_id], "source": str(path)}
    raise Refused(f"policy document {path} has no measurement for {shot_id}")


def summarize_measurement(native_d: list[float], core_d: list[float], ref_d: list[float],
                          windows: list[dict]) -> dict:
    """Per-shot motion metric + mean/max ``excess_peak`` over the seam windows."""
    if len(core_d) != len(ref_d):
        raise Refused("core and reference motion sequences differ in length")
    seams = []
    for window in windows:
        seam = window["S"]
        frame_range = [t for t in range(seam - 5, seam + 4) if 0 <= t < len(core_d)]
        if not frame_range:
            raise Refused(f"seam S={seam}: no measurable frame pair")
        peak = max(core_d[t] - ref_d[t] for t in frame_range)
        seams.append({"S": seam, "excess_peak": round(peak, 3),
                      "d_peak": round(max(core_d[t] for t in frame_range), 3)})
    excess = [row["excess_peak"] for row in seams]
    return {"native_mean_absdY": round(sum(native_d) / len(native_d), 3) if native_d else 0.0,
            "mean_excess_peak": round(sum(excess) / len(excess), 3),
            "max_excess_peak": round(max(excess), 3),
            "min_excess_peak": round(min(excess), 3),
            "n_seams": len(seams), "seams": seams, "source": "measured"}


def _mean_diff(frames: Iterator[Any]) -> list[float]:
    np = require_numpy()
    previous, diffs = None, []
    for frame in frames:
        if previous is not None:
            diffs.append(float(np.abs(frame.astype(np.int16) - previous.astype(np.int16)).mean()))
        previous = frame
    return diffs


def measure_shot(shot: dict, chunks: list[dict], windows: list[dict], geometry: BlendGeometry,
                 source: Path, ffmpeg: str, threads: int, emit: Callable[[str], None]) -> dict:
    """Stream the native + lanczos reference + core sequences and summarize the policy metric."""
    video = shot["source_video"]
    native_w, native_h = int(video["width"]), int(video["height"])
    emit(f"[measure] {shot['shot_id']}: native motion")
    native_d = _mean_diff(iter_gray(ffmpeg, source, "format=gray", native_w, native_h, threads))
    emit(f"[measure] {shot['shot_id']}: lanczos reference motion")
    reference_vf = (f"scale={geometry.processing_width}:{geometry.processing_height}:flags=lanczos,"
                    f"{geometry.crop_filter},format=gray")
    ref_d = _mean_diff(iter_gray(ffmpeg, source, reference_vf,
                                 geometry.final_width, geometry.final_height, threads))
    emit(f"[measure] {shot['shot_id']}: core motion")
    core_d: list[float] = []
    previous = None
    np = require_numpy()
    for chunk in chunks:
        path = Path((shot.get("job_paths") or {}).get(chunk["chunk_name"], ""))
        if not path.is_file():
            raise Refused(f"{chunk['chunk_name']}: core path is not resolved for measurement")
        for frame in iter_gray(ffmpeg, path, "format=gray",
                               geometry.final_width, geometry.final_height, threads):
            if previous is not None:
                core_d.append(float(np.abs(frame.astype(np.int16)
                                           - previous.astype(np.int16)).mean()))
            previous = frame
    return summarize_measurement(native_d, core_d, ref_d, windows)
