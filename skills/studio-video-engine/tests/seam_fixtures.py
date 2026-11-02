"""Tiny synthetic production tree for the seam-blend tests (no ffmpeg, no 4K)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from engine.config.loader import ResolvedConfig
from engine.core.io import canonical_sha256, sha256_file
from engine.seedvr2 import seam_blend_run as sbr

try:
    import numpy as np
except ImportError:  # optional engine dependency
    np = None

TW, TH = 64, 36
PW, PH, CROP = 72, 36, 8
SHOT = "S02_A"
VERSION = "seedvr2-production-v004"


def media_bytes(frames: int, width: int, height: int, tag: str) -> bytes:
    return f"media|{frames}|{width}|{height}|{tag}".encode("ascii")


def make_chunks(cores: list[int], context: int = 4) -> tuple[list[dict], int]:
    total = sum(cores)
    chunks, position = [], 0
    for index, core in enumerate(cores):
        start, end = position, position + core
        segment_start, segment_end = max(0, start - context), min(total, end + context)
        chunks.append({
            "index": index, "chunk_name": f"chunk-{index:04d}",
            "core_start_frame": start, "core_end_frame_exclusive": end, "core_frames": core,
            "segment_start_frame": segment_start, "segment_end_frame_exclusive": segment_end,
            "segment_frames": segment_end - segment_start,
            "core_offset_in_segment": start - segment_start,
        })
        position = end
    return chunks, total


def seam_policy_block(**overrides) -> dict:
    block = {"policy_version": "seam-policy/v001", "window_half_frames": 4, "blend_frames": 8,
             "low_motion_max": 5.0, "excess_trigger": 1.0, "hf8_sigma": 1.5,
             "allow_clipped_tail": True, "motion_metric": "native_mean_absdY",
             "excess_metric": "mean_excess_peak"}
    block.update(overrides)
    return block


@dataclass
class Tree:
    config: ResolvedConfig
    plan_path: Path
    plan: dict
    chunks: list[dict]
    frames: int
    shot: str
    cores: dict[str, Path]
    raws: dict[str, Path]

    @property
    def plan_sha(self) -> str:
        return sha256_file(self.plan_path)

    def job_path(self, index: int) -> Path:
        return self.plan_path.parent / "runs" / self.shot / f"chunk-{index:04d}" / "job.json"

    def set_status(self, index: int, status: str) -> None:
        path = self.job_path(index)
        job = json.loads(path.read_text("utf-8"))
        job["status"] = status
        path.write_text(json.dumps(job), "utf-8")


def build_tree(root: Path, *, cores: list[int] | None = None, shot: str = SHOT,
               policy: dict | None = None, complete: bool = True) -> Tree:
    root = Path(root)
    episode_root = root / "episode"
    plan_dir = episode_root / "technical" / VERSION
    chunks, frames = make_chunks(cores or [13, 13, 13, 3], context=4)
    source = episode_root / "clips" / f"{shot}.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(media_bytes(frames, TW, TH, "source"))
    shot_record = {"shot_id": shot, "logical_shot": shot, "source_path": str(source),
                   "source_sha256": sha256_file(source),
                   "source_video": {"width": TW, "height": TH, "fps": "24/1", "frames": frames},
                   "chunks": chunks, "chunk_count": len(chunks)}
    plan = {
        "schema": "milk-and-mom-seedvr2-production-plan/v004",
        "status": "PLAN_PREPARED", "film_id": "test-film", "episode_id": "test-episode",
        "production_version": VERSION, "shots": [shot_record],
        "recipe_geometry": {"fps": "24/1", "processing_width": PW, "processing_height": PH,
                            "final_width": TW, "final_height": TH, "final_crop_left": CROP,
                            "final_crop_top": 0},
        "target": {"processing_width": PW, "processing_height": PH, "final_width": TW,
                   "final_height": TH, "crop_left": CROP, "crop_top": 0,
                   "crop_filter": f"crop={TW}:{TH}:{CROP}:0", "fps": "24/1"},
        "totals": {"total_chunks": len(chunks)},
    }
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plan_dir / "PRODUCTION-PLAN.json"
    plan_path.write_text(json.dumps(plan, indent=2), "utf-8")
    plan_sha = sha256_file(plan_path)
    cores_map, raws_map = {}, {}
    for index, chunk in enumerate(chunks):
        chunk_dir = plan_dir / "runs" / shot / f"chunk-{index:04d}"
        (chunk_dir / "output").mkdir(parents=True)
        (chunk_dir / "core").mkdir(parents=True)
        raw = chunk_dir / "output" / f"{chunk['chunk_name']}_00001_.mp4"
        core = chunk_dir / "core" / f"{chunk['chunk_name']}_00001_-core-{TW}x{TH}.mp4"
        raw.write_bytes(media_bytes(chunk["segment_frames"], PW, PH, chunk["chunk_name"]))
        core.write_bytes(media_bytes(chunk["core_frames"], TW, TH, "core-" + chunk["chunk_name"]))
        cores_map[chunk["chunk_name"]], raws_map[chunk["chunk_name"]] = core, raw
        job = {
            "schema": "test-job/v004", "status": "COMPLETED" if complete else "WAITING",
            "film_id": "test-film", "production_version": VERSION, "shot_id": shot,
            "chunk_index": index, "chunk_name": chunk["chunk_name"], "plan_sha256": plan_sha,
            "output_path": str(raw), "output_sha256": sha256_file(raw),
            "output_frame_count": chunk["segment_frames"],
            "output_dimensions": {"width": PW, "height": PH},
            "core_path": str(core), "core_sha256": sha256_file(core),
            "core_frame_count": chunk["core_frames"],
            "core_dimensions": {"width": TW, "height": TH},
        }
        (chunk_dir / "job.json").write_text(json.dumps(job, indent=2), "utf-8")
    domain = {"schema": "jjv/domain/v1", "domain_id": "jenniejoy_cartoon_3d",
              "label": "test", "seam_blend": policy or seam_policy_block()}
    episode = {"schema": "jjv/episode/v1", "episode_id": "test-episode",
               "film_id": "test-film", "domain": "jenniejoy_cartoon_3d",
               "seedvr2": {"production_version": VERSION,
                           "input_name_template": "x-{shot}-{chunk}-{seg_sha12}.mp4",
                           "output_prefix_template": "x/{shot}/{chunk}"}}
    shots = [{"shot": shot, "clip": {"path": f"clips/{shot}.mp4",
                                     "sha256": sha256_file(source), "frames": frames}}]
    config = ResolvedConfig(
        machine={}, domain=domain, recipes={}, episode=episode, shots=shots, mouth_boxes={},
        episode_root=str(episode_root), sources={},
        config_sha256=canonical_sha256({"domain": domain, "episode": episode}, mode="ascii"))
    return Tree(config=config, plan_path=plan_path, plan=plan, chunks=chunks, frames=frames,
                shot=shot, cores=cores_map, raws=raws_map)


def policy_document(plan_sha: str, *, shot: str = SHOT, motion: float = 1.0,
                    excess: float = 2.2, measured: bool = True) -> dict:
    return {"schema": "seam-policy/v001", "plan_sha256": plan_sha,
            "rows": [{"shot": shot, "measured": measured, "native_mean_absdY": motion,
                      "mean_excess_peak": excess, "policy": "hf8", "confidence": "high"}]}


# --------------------------------------------------------------------------- fakes for the build path

class FakeEncoder:
    def __init__(self, ffmpeg: str, path: Path, width: int, height: int, fps: str,
                 threads: int = 4) -> None:
        self.path, self.width, self.height, self.frames = Path(path), width, height, 0

    def write(self, planes) -> None:
        assert len(planes) == 3
        self.frames += 1

    def close(self) -> None:
        self.path.write_bytes(f"FAKE-MP4|{self.frames}|{self.width}x{self.height}".encode())

    def abort(self) -> None:
        self.path.unlink(missing_ok=True)


def fake_planes(tree: "Tree") -> dict[str, tuple]:
    """Raw = random per chunk; core = the exact raw trim, so verification passes."""
    rng = np.random.default_rng(7)
    registry = {}
    for chunk in tree.chunks:
        segment = chunk["segment_frames"]
        raw = (rng.integers(0, 256, (segment, TH, TW), dtype=np.uint8),
               rng.integers(0, 256, (segment, TH // 2, TW // 2), dtype=np.uint8),
               rng.integers(0, 256, (segment, TH // 2, TW // 2), dtype=np.uint8))
        offset, count = chunk["core_offset_in_segment"], chunk["core_frames"]
        registry[tree.raws[chunk["chunk_name"]].name] = raw
        registry[tree.cores[chunk["chunk_name"]].name] = tuple(
            plane[offset:offset + count].copy() for plane in raw)
    return registry


def fake_deps(tree: "Tree", messages: list[str] | None = None, measurement: dict | None = None,
              decode_called: list[str] | None = None) -> sbr.Deps:
    registry = fake_planes(tree)

    def decode(ffmpeg, path, vf, width, height, threads=4):
        if decode_called is not None:
            decode_called.append(str(path))
        return registry[Path(path).name]

    def measure(*_args, **_kwargs):
        assert measurement is not None, "measure called without a fixture value"
        return measurement

    return sbr.Deps(decode=decode, encoder_factory=FakeEncoder, measure=measure,
                    ffmpeg_version=lambda _ffmpeg: "ffmpeg test", clock=lambda: 0.0,
                    emit=(messages.append if messages is not None else (lambda _m: None)))


def measurement(motion: float, excess: float) -> dict:
    return {"native_mean_absdY": motion, "mean_excess_peak": excess, "source": "measured"}
