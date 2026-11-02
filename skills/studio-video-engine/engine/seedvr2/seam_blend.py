"""CPU-only seam blending for verified SeedVR2 4K chunk cores (port of ``seam_blend_v001``).

Chunk geometry comes from the plan (``core_start_frame``/``segment_start_frame``/...); the window
shape and the auto-policy thresholds come from the resolved config (``domain.seam_blend``), never
from constants in this module.  A seam ``S`` (the ``core_end_frame_exclusive`` of chunk ``k``) owns
output frames ``[S-half, S+half)``; frame ``S-half+i`` is blended with weight
``w_i = (i+0.5)/blend_frames`` on chunk ``k+1``.

Modes
  core : plain concatenation of the production core files (baseline)
  lin8 : linear cross-fade of Y, U, V over the blend window
  hf8  : Y = linear low band + gain-restored high band (one gain >= 1 per frame); U, V linear
  auto : policy from the recorded/measured motion metric (decided at build time)

Everything is verified before it is trusted: job status, sha256 of raw + core files, frame counts,
dimensions, and that each core equals the raw segment trimmed and cropped.  Any mismatch is a
``Refused`` (exit 1) and no output file is left behind.  ``--dry-run`` performs that verification
and prints the plan: it decodes no pixels, writes nothing, and reports ``auto`` as ``deferred``
unless a recorded policy document supplies the measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Refused
from ..core.io import sha256_file  # noqa: F401 - re-exported for receipts and tests
from .seam_media import require_cv2, require_numpy

BLEND_MODES = ("core", "hf8", "lin8")


@dataclass(frozen=True)
class BlendGeometry:
    processing_width: int
    processing_height: int
    final_width: int
    final_height: int
    crop_left: int
    crop_top: int
    fps: str

    @property
    def crop_filter(self) -> str:
        return f"crop={self.final_width}:{self.final_height}:{self.crop_left}:{self.crop_top}"

    def as_dict(self) -> dict:
        return {"processing": [self.processing_width, self.processing_height],
                "final": [self.final_width, self.final_height],
                "crop": [self.crop_left, self.crop_top], "fps": self.fps}


def geometry_from_plan(plan: dict) -> BlendGeometry:
    target = plan.get("target") or {}
    if not target:
        raise Refused("plan has no target block (processing/final size and crop); re-plan")
    try:
        geometry = BlendGeometry(
            processing_width=int(target["processing_width"]),
            processing_height=int(target["processing_height"]),
            final_width=int(target["final_width"]),
            final_height=int(target["final_height"]),
            crop_left=int(target["crop_left"]),
            crop_top=int(target["crop_top"]),
            fps=str(target.get("fps") or plan["recipe_geometry"]["fps"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise Refused(f"plan target is incomplete: {error!r}") from error
    if (geometry.final_width + geometry.crop_left > geometry.processing_width
            or geometry.final_height + geometry.crop_top > geometry.processing_height):
        raise Refused("plan final crop does not fit inside the processing size")
    return geometry


def seam_weights(blend_frames: int) -> list[float]:
    """Weight on chunk k+1 for window frame ``i``: ``(i+0.5)/n``."""
    if blend_frames < 1:
        raise Refused("blend_frames must be positive")
    return [(i + 0.5) / blend_frames for i in range(blend_frames)]


def plan_windows(chunks: list[dict], nframes: int, *, half: int, blend_frames: int,
                 allow_clipped_tail: bool = False) -> list[dict]:
    """Validate chunk geometry and return one window per seam (``chunks`` is plan order)."""
    if not chunks:
        raise Refused("plan has no chunks")
    position = 0
    for index, chunk in enumerate(chunks):
        if chunk["core_start_frame"] != position:
            raise Refused(f"chunk {index}: core_start {chunk['core_start_frame']} != expected "
                          f"{position} (gap/overlap in cores)")
        if chunk["core_end_frame_exclusive"] - chunk["core_start_frame"] != chunk["core_frames"]:
            raise Refused(f"chunk {index}: core_frames inconsistent with the core range")
        position = chunk["core_end_frame_exclusive"]
    if position != nframes:
        raise Refused(f"cores cover {position} frames but the shot has {nframes}")
    last = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        if index < last and chunk["core_frames"] < blend_frames:
            raise Refused(f"chunk {index} core_frames={chunk['core_frames']} < {blend_frames}: "
                          "seam windows would overlap")
    windows: list[dict] = []
    for index in range(last):
        seam = chunks[index]["core_end_frame_exclusive"]
        low, high_full = seam - half, seam + half
        high = min(high_full, nframes)
        clipped = high < high_full
        if clipped and not allow_clipped_tail:
            raise Refused(
                f"seam {index}->{index + 1} at S={seam}: window [{low},{high_full}) runs past the "
                f"shot end ({nframes}); last chunk core has only {chunks[index + 1]['core_frames']} "
                "frame(s) (set seam_blend.allow_clipped_tail to clip it)")
        if low < 0:
            raise Refused(f"seam at S={seam}: window starts before frame 0")
        for nearby in (index, index + 1):
            chunk = chunks[nearby]
            if chunk["segment_start_frame"] > low or chunk["segment_end_frame_exclusive"] < high:
                raise Refused(
                    f"seam S={seam}: chunk {nearby} segment "
                    f"[{chunk['segment_start_frame']},{chunk['segment_end_frame_exclusive']}) "
                    f"does not cover window [{low},{high})")
        if windows and low < windows[-1]["hi"]:
            raise Refused(f"seam windows overlap at S={seam}")
        windows.append({"k": index, "S": seam, "lo": low, "hi": high, "clipped": clipped})
    return windows


def lerp_plane(left, right, weight: float):
    np = require_numpy()
    blended = (1.0 - weight) * left.astype(np.float32) + weight * right.astype(np.float32)
    return np.clip(np.rint(blended), 0, 255).astype(np.uint8)


def blend_y_hf(left, right, weight: float, sigma: float = 1.5):
    """Low band blended linearly, high band blended and gain-restored (gain >= 1)."""
    np = require_numpy()
    cv2 = require_cv2()
    a, b = left.astype(np.float32), right.astype(np.float32)
    low_a, low_b = cv2.GaussianBlur(a, (0, 0), sigma), cv2.GaussianBlur(b, (0, 0), sigma)
    high_a, high_b = a - low_a, b - low_b
    high_mix = (1.0 - weight) * high_a + weight * high_b
    target = float(np.sqrt((1.0 - weight) * float(high_a.var()) + weight * float(high_b.var())))
    gain = max(1.0, target / max(float(high_mix.std()), 1e-6))
    mixed = (1.0 - weight) * low_a + weight * low_b + gain * high_mix
    return np.clip(np.rint(mixed), 0, 255).astype(np.uint8), gain


def blend_frame(raw_a, raw_b, index_a: int, index_b: int, weight: float, mode: str,
                sigma: float = 1.5):
    """Blend one raw frame pair; returns (Y, U, V, gain|None)."""
    if mode == "hf8":
        y_plane, gain = blend_y_hf(raw_a[0][index_a], raw_b[0][index_b], weight, sigma)
    elif mode == "lin8":
        y_plane, gain = lerp_plane(raw_a[0][index_a], raw_b[0][index_b], weight), None
    else:
        raise Refused(f"mode {mode!r} does not blend")
    return (y_plane,
            lerp_plane(raw_a[1][index_a], raw_b[1][index_b], weight),
            lerp_plane(raw_a[2][index_a], raw_b[2][index_b], weight),
            gain)


def assemble_frames(chunks: list[dict], nframes: int, windows: list[dict], load,
                    mode: str, *, blend_frames: int, sigma: float = 1.5,
                    gains_out: list | None = None):
    """Yield ``(frame_index, (Y, U, V), kind)`` for every output frame in order."""
    if mode not in BLEND_MODES:
        raise Refused(f"mode {mode!r} is not a build mode")
    window_at: dict[int, dict] = {}
    for window in windows:
        for frame in range(window["lo"], window["hi"]):
            window_at[frame] = window
    cache: dict[int, dict] = {}

    def get(index: int) -> dict:
        if index not in cache:
            cache[index] = load(index)
        return cache[index]

    owner = 0
    for frame in range(nframes):
        while frame >= chunks[owner]["core_end_frame_exclusive"]:
            owner += 1
        for dead in [index for index in cache if index < owner - 1]:
            del cache[dead]
        window = window_at.get(frame) if mode != "core" else None
        if window is None:
            chunk, core = chunks[owner], get(owner)["core"]
            index = frame - chunk["core_start_frame"]
            yield frame, (core[0][index], core[1][index], core[2][index]), "core"
            continue
        chunk_a, chunk_b = window["k"], window["k"] + 1
        offset = frame - window["lo"]
        weight = (offset + 0.5) / blend_frames
        planes_a, planes_b = get(chunk_a)["raw"], get(chunk_b)["raw"]
        y_plane, u_plane, v_plane, gain = blend_frame(
            planes_a, planes_b, frame - chunks[chunk_a]["segment_start_frame"],
            frame - chunks[chunk_b]["segment_start_frame"], weight, mode, sigma)
        if gains_out is not None:
            gains_out.append({"seam": window["S"], "frame": frame, "i": offset,
                              "w": round(weight, 5),
                              "gain": None if gain is None else round(gain, 6)})
        yield frame, (y_plane, u_plane, v_plane), "blend"


def check_frame_counts(chunk: dict, job_frames: int, raw_frames: int, core_frames: int) -> None:
    """Decoded raw frames == plan segment_frames == job count; core likewise."""
    name = chunk.get("chunk_name", "?")
    if not (raw_frames == chunk["segment_frames"] == job_frames):
        raise Refused(f"{name}: raw frames decoded={raw_frames}, plan segment_frames="
                      f"{chunk['segment_frames']}, job count={job_frames} (must all agree)")
    if core_frames != chunk["core_frames"]:
        raise Refused(f"{name}: core frames decoded={core_frames} != plan core_frames="
                      f"{chunk['core_frames']}")


def check_core_equals_raw(chunk: dict, raw, core) -> list[int]:
    """The core file must equal the raw segment trimmed to the core range."""
    np = require_numpy()
    offset, frames = chunk["core_offset_in_segment"], chunk["core_frames"]
    diffs = []
    for plane in range(3):
        expected, found = raw[plane][offset:offset + frames], core[plane]
        if expected.shape != found.shape:
            raise Refused(f"{chunk.get('chunk_name', '?')}: core plane {plane} shape "
                          f"{found.shape} != raw trim shape {expected.shape}")
        diffs.append(int(np.abs(expected.astype(np.int16) - found.astype(np.int16)).max()))
    if any(diffs):
        raise Refused(f"{chunk.get('chunk_name', '?')}: core != raw trim+crop "
                      f"(max abs diff YUV = {diffs})")
    return diffs


def _inside(child: Path, parent: Path) -> bool:
    child, parent = Path(child).resolve(), Path(parent).resolve()
    return child == parent or parent in child.parents


def check_job(shot_id: str, chunk: dict, job: dict, plan_sha: str, plan_root: Path,
              geometry: BlendGeometry) -> None:
    name = chunk["chunk_name"]
    label = f"{shot_id}/{name}"
    if job.get("status") != "COMPLETED":
        raise Refused(f"{label}: job status {job.get('status')!r} != COMPLETED (shot incomplete)")
    if job.get("shot_id") != shot_id or job.get("chunk_name") != name:
        raise Refused(f"{label}: job.json is for {job.get('shot_id')}/{job.get('chunk_name')}")
    if job.get("plan_sha256") and job["plan_sha256"] != plan_sha:
        raise Refused(f"{label}: job.plan_sha256 does not match the plan file on disk")
    for key in ("output_path", "core_path"):
        path = job.get(key)
        if not path or not Path(path).is_file():
            raise Refused(f"{label}: {key} missing ({path})")
        if not _inside(Path(path), plan_root):
            raise Refused(f"{label}: {key} lies outside the production plan tree")
    if job.get("output_frame_count") != chunk["segment_frames"]:
        raise Refused(f"{label}: job output_frame_count={job.get('output_frame_count')} != "
                      f"segment_frames={chunk['segment_frames']}")
    if job.get("core_frame_count") != chunk["core_frames"]:
        raise Refused(f"{label}: job core_frame_count={job.get('core_frame_count')} != "
                      f"core_frames={chunk['core_frames']}")
    raw_dims = job.get("output_dimensions") or {}
    if (raw_dims.get("width"), raw_dims.get("height")) != (
            geometry.processing_width, geometry.processing_height):
        raise Refused(f"{label}: raw dimensions {raw_dims} != "
                      f"{geometry.processing_width}x{geometry.processing_height}")
    core_dims = job.get("core_dimensions") or {}
    if (core_dims.get("width"), core_dims.get("height")) != (
            geometry.final_width, geometry.final_height):
        raise Refused(f"{label}: core dimensions {core_dims} != "
                      f"{geometry.final_width}x{geometry.final_height}")
