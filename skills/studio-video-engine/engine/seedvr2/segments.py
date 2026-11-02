"""``jjv seedvr2 segments``: cut the per-chunk source segments a SeedVR2 plan needs (replaces the per-episode hand tool).

Input is a plan (the pending plan ``jjv seedvr2 plan`` writes, a tails plan, or - without ``--plan`` - the plan
built in memory from the config).  The plan is evidence, not authority: its identity (episode, recipe, config sha)
and every chunk window are re-derived and compared, each source file is re-hashed and re-probed, then every chunk
is cut frame-exactly (``segment_cut``), verified (count, size, fps and, by default, frame md5 of the cut equals
the frame md5 of the source slice) and linked in place.  Nothing is ever overwritten; an existing segment is kept
only if it proves to be the same frames.  Output: ``<out>/<shot>/chunks/<chunk>/source-segment.mp4`` (the layout
``plan --segments-root`` binds) and a hashed receipt with no timestamp.  CPU only: no ComfyUI, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config.loader import ResolvedConfig, require_recipe
from ..core.errors import Failed, Refused
from ..core.io import canonical_sha256, read_json, sha256_bytes, sha256_file, write_json_once
from ..core.paths import require_inside, resolve_data_path
from ..media.probe import VideoInfo, probe_video
from .chunking import plan_chunks, shot_source_range
from .execplan import PLAN_KINDS, WINDOW_KEYS
from .media_ops import Geometry, Probe, Runner, default_runner, verify_video
from .plan import PLAN_SCHEMA, build_plan
from .segment_cut import SEGMENT_ENCODE, SEGMENT_ENCODE_NAME, cut_segment, framemd5, slice_md5

RECEIPT_SCHEMA = "jjv/seedvr2-segments/v1"
RECEIPT_FILE = "segments-receipt.json"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CutJob:
    shot_id: str
    chunk_name: str
    relative: str  # segment path under the segments root
    source: Path
    source_sha256: str
    source_frames: int  # frames the source FILE must have
    start: int  # absolute source frame, inclusive
    end: int  # exclusive
    chunk_index: int

    @property
    def frames(self) -> int:
        return self.end - self.start


def _need(found: object, expected: object, label: str) -> None:
    if found != expected:
        raise Refused(f"plan {label} differs from the resolved config: {found!r} != {expected!r}; "
                      "re-plan (jjv seedvr2 plan) against the current config")


def _shot_source(shot: Mapping[str, Any], config_shot: Mapping[str, Any] | None, episode_root: Path,
                 tails: bool) -> tuple[Path, str, int]:
    shot_id = shot["shot_id"]
    if tails:
        sha = shot.get("source_sha256")
        if not isinstance(sha, str) or not _SHA.match(sha):
            raise Refused(f"{shot_id}: tails source_sha256 is not a sha256")
        total = shot_source_range(shot)
        if total is None:
            raise Refused(f"{shot_id}: a tails plan shot needs a source_range")
        path, frames = Path(shot["source_path"]), shot["source_range"]["source_frames_total"]
    else:
        clip = config_shot["clip"]
        _need(shot.get("source_sha256"), clip["sha256"], f"{shot_id} source sha256")
        _need(shot.get("source_path"), clip["path"], f"{shot_id} source path")
        _need(shot["source_video"]["frames"], clip["frames"], f"{shot_id} source frames")
        path, frames, sha = Path(clip["path"]), clip["frames"], clip["sha256"]
    return resolve_data_path(path if path.is_absolute() else Path(episode_root) / path), sha, frames


def jobs_from_plan(plan: Mapping[str, Any], config: ResolvedConfig, recipe: dict) -> list[CutJob]:
    """Every chunk cut of ``plan``, after re-deriving identity and windows (``Refused`` on any difference)."""
    _need(plan.get("schema"), PLAN_SCHEMA, "schema")
    if plan.get("kind") not in PLAN_KINDS:
        raise Refused(f"plan kind {plan.get('kind')!r} is unknown")
    tails = plan.get("kind") == "tails"
    _need(plan.get("episode_id"), config.episode["episode_id"], "episode_id")
    _need(plan.get("domain"), config.domain["domain_id"], "domain")
    _need(plan.get("recipe_canonical_sha256"), canonical_sha256(recipe, mode="ascii"), "recipe sha256")
    _need(plan.get("config_sha256"), config.config_sha256, "config_sha256")
    by_id = {s["shot"]: s for s in config.shots}
    jobs: list[CutJob] = []
    seen: set[str] = set()
    for shot in plan.get("shots") or []:
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not _SAFE_ID.match(shot_id) or shot_id not in by_id or shot_id in seen:
            raise Refused(f"plan shot id {shot_id!r} is unsafe, duplicated or not an episode shot")
        seen.add(shot_id)
        source, sha, total = _shot_source(shot, by_id[shot_id], Path(config.episode_root), tails)
        window = shot_source_range(shot)
        base, frames = (window[0], window[1] - window[0]) if window else (0, shot["source_video"]["frames"])
        expected = plan_chunks(frames, recipe["geometry"])
        if len(shot.get("chunks") or []) != len(expected):
            raise Refused(f"{shot_id}: chunk count differs from the recipe-derived plan")
        for position, (chunk, win) in enumerate(zip(shot["chunks"], expected)):
            name = f"chunk-{position:04d}"
            relative = f"{shot_id}/chunks/{name}/source-segment.mp4"
            bad = [k for k in WINDOW_KEYS if chunk.get(k) != win[k]]
            if bad or chunk.get("chunk_name") != name or chunk.get("segment_path") != relative:
                raise Refused(f"{shot_id}/{name}: chunk window or segment path differs from the recipe-derived "
                              f"plan ({bad or 'name/path'})")
            jobs.append(CutJob(shot_id, name, relative, source, sha, total, base + win["segment_start_frame"],
                               base + win["segment_end_frame_exclusive"], position))
    return jobs


def select_jobs(jobs: list[CutJob], only: str | None) -> list[CutJob]:
    """``--only SHOT[:IDX],...``; every selector must match something."""
    if not only:
        return jobs
    chosen: list[CutJob] = []
    for selector in (item.strip() for item in only.split(",")):
        shot_id, separator, index = selector.partition(":")
        if not shot_id or (separator and not index.isdigit()):
            raise Refused(f"bad --only selector: {selector!r}")
        matches = [j for j in jobs if j.shot_id == shot_id and (not separator or j.chunk_index == int(index))]
        if not matches:
            raise Refused(f"--only selector matches no chunk: {selector}")
        chosen.extend(j for j in matches if j not in chosen)
    return chosen


class _Sources:
    """Each source file is hashed and probed once per run."""

    def __init__(self, geometry: Geometry, native: Mapping[str, int], probe: Probe) -> None:
        self.geometry, self.native, self.probe = geometry, native, probe
        self._done: dict[Path, VideoInfo] = {}

    def check(self, label: str, path: Path, sha256: str, frames: int) -> VideoInfo:
        """Hash + probe ``path`` once: sha, exact frame count, recipe fps and native size, else ``Refused``."""
        if path in self._done:
            return self._done[path]
        if not path.is_file():
            raise Refused(f"{label}: source clip not found: {path}")
        actual = sha256_file(path)
        if actual != sha256:
            raise Refused(f"{label}: source sha256 {actual} != plan {sha256}")
        info = self.probe(path)
        if info.frames is None:
            info = self.probe(path, count_packets=True)
        if info.frames != frames:
            raise Refused(f"{label}: source has {info.frames} frames, the plan says {frames}")
        if info.fps != self.geometry.fps or (info.width, info.height) != (self.native["width"], self.native["height"]):
            raise Refused(f"{label}: source is {info.width}x{info.height} @ {info.fps}; the recipe needs "
                          f"{self.native['width']}x{self.native['height']} @ {self.geometry.fps}")
        self._done[path] = info
        return info


def _same_frames(found: list[str], expected: list[str], label: str, error: type[Exception]) -> None:
    if found != expected:
        first = next((i for i, (a, b) in enumerate(zip(found, expected)) if a != b), min(len(found), len(expected)))
        raise error(f"{label}: frame md5 differs from the source slice (first difference at frame {first}; "
                    f"{len(found)} vs {len(expected)} frames)")


def _one(job: CutJob, out: Path, ctx: Mapping[str, Any]) -> dict:
    destination = require_inside(out / job.relative, out, f"{job.shot_id}/{job.chunk_name} segment")
    g, runner, ffmpeg = ctx["geometry"], ctx["runner"], ctx["ffmpeg"]
    row = {"shot_id": job.shot_id, "chunk": job.chunk_name, "segment_path": job.relative,
           "source_path": str(job.source), "source_sha256": job.source_sha256,
           "source_start_frame": job.start, "source_end_frame_exclusive": job.end, "frames": job.frames}
    expected = slice_md5(job.source, job.start, job.end, runner=runner, ffmpeg=ffmpeg) if ctx["verify_md5"] else None
    if expected is not None and len(expected) != job.frames:
        raise Failed(f"{job.shot_id}/{job.chunk_name}: the source slice decodes to {len(expected)} frames, "
                     f"expected {job.frames}")
    if destination.exists():
        verify_video(destination, frames=job.frames, width=ctx["native"]["width"], height=ctx["native"]["height"],
                     fps=g.fps, probe=ctx["probe"])
        if expected is not None:
            _same_frames(framemd5(destination, runner=runner, ffmpeg=ffmpeg), expected,
                         f"existing segment {job.relative}", Refused)
        status = "existing_verified" if expected is not None else "existing_probed"
    else:
        def check(temporary: Path) -> None:
            if expected is not None:
                _same_frames(framemd5(temporary, runner=runner, ffmpeg=ffmpeg), expected,
                             f"cut {job.relative}", Failed)

        cut_segment(job.source, destination, start=job.start, end_exclusive=job.end, fps=g.fps,
                    width=ctx["native"]["width"], height=ctx["native"]["height"], runner=runner,
                    probe=ctx["probe"], ffmpeg=ffmpeg, threads=ctx["threads"], check=check)
        status = "cut"
    return {**row, "sha256": sha256_file(destination), "bytes": destination.stat().st_size, "status": status,
            "md5_verified": expected is not None}


def run_segments(config: ResolvedConfig, *, repo_root: Path, out_root: Path, plan: Mapping[str, Any] | None = None,
                 plan_path: Path | None = None, only: str | None = None, verify_md5: bool = True,
                 dry_run: bool = False, probe: Probe = probe_video, runner: Runner = default_runner,
                 ffmpeg: str = "ffmpeg", threads: int | None = None) -> dict:
    """Cut (or, with ``dry_run``, list) the segments of ``plan``; one summary dict."""
    recipe = require_recipe(config, "seedvr2")
    plan_sha = None
    if plan is None and plan_path is not None:
        plan, plan_sha = read_json(Path(plan_path)), sha256_file(Path(plan_path))
    if plan is None:
        plan = build_plan(config, repo_root=repo_root, probe=probe).plan
    all_jobs = jobs_from_plan(plan, config, recipe)
    jobs = select_jobs(all_jobs, only)
    out = Path(out_root)
    if out.exists() and not out.is_dir():
        raise Refused(f"--out {out} exists and is not a directory")
    sources = _Sources(Geometry.from_recipe(recipe), recipe["native"], probe)
    for job in jobs:
        sources.check(job.shot_id, job.source, job.source_sha256, job.source_frames)
    summary: dict[str, Any] = {"ok": True, "dry_run": dry_run, "episode_id": plan["episode_id"],
                               "out": str(out), "chunks": len(jobs), "plan_sha256": plan_sha}
    if dry_run:
        summary["segments"] = [{"shot_id": j.shot_id, "chunk": j.chunk_name, "segment_path": j.relative,
                                "source_start_frame": j.start, "source_end_frame_exclusive": j.end,
                                "frames": j.frames, "exists": (out / j.relative).exists()} for j in jobs]
        return summary
    ctx = {"geometry": sources.geometry, "native": recipe["native"], "runner": runner, "probe": probe,
           "ffmpeg": ffmpeg, "threads": threads, "verify_md5": verify_md5}
    rows = [_one(job, out, ctx) for job in jobs]
    receipt = {"schema": RECEIPT_SCHEMA, "episode_id": plan["episode_id"], "plan_kind": plan.get("kind") or "normal",
               "config_sha256": config.config_sha256, "recipe_id": recipe["recipe_id"],
               "recipe_canonical_sha256": canonical_sha256(recipe, mode="ascii"), "plan_file_sha256": plan_sha,
               "encode": {"name": SEGMENT_ENCODE_NAME, "args": SEGMENT_ENCODE,
                          "filter": "trim=start_frame:end_frame,setpts=PTS-STARTPTS"},
               "md5_verified": verify_md5,
               # how a segment came to be (cut now / kept from an earlier run) is not part of what it IS:
               # the receipt stays identical on a re-run, and the summary below carries the statuses
               "segments": [{k: v for k, v in r.items() if k not in ("status", "md5_verified")} for r in rows]}
    name = RECEIPT_FILE if not only else f"segments-receipt-only-{sha256_bytes(only.encode())[:8]}.json"
    summary.update(receipt_path=str(out / name), receipt_sha256=write_json_once(out / name, receipt, mode="ascii"),
                   cut=sum(r["status"] == "cut" for r in rows), segments=rows)
    return summary
