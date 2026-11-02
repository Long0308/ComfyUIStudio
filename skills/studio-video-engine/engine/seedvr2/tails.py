"""``jjv seedvr2 tails plan``: restore the frames the timeline reads outside the main plan's scope.

The coverage gaps (``coverage.find_gaps``) become a *tails plan*: a normal plan v2 (``kind: "tails"``) whose shots
are sub-ranges of the NATIVE clips the gaps name, so ``jjv seedvr2 execute`` runs it unchanged (same executor, same
guards, same receipts).  Per shot the planner:

* merges the shot's gaps into one range ``[lo, hi)`` and adds leading context frames (frames BEFORE the gap, taken
  from the same source, so the tail overlaps the last main-run chunk and the join can be measured).  Context is
  ``min(recipe context, frames before the gap)``, and when the gap is shorter than one core it is capped at
  ``core - gap`` so the range still plans as ONE chunk (example: a shot with 10 tail frames gets 3 context frames, not 4);
* cuts the segments with ``segments.run_segments`` (frame-exact, hashed, md5-verified) into the plan folder;
* binds them and writes the plan, with output prefix ``.../tails/<shot>/<chunk>`` so nothing collides with the main run.

Chunk windows of a tails shot are relative to ``source_range.start_frame``.  CPU only until ``execute --execute``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.paths import resolve_data_path
from ..media.probe import probe_video
from .chunking import plan_chunks
from .coverage import Gap, Read, add_scope, check_coverage, find_gaps, scope_from_shots
from .media_ops import Geometry, Probe, Runner, default_runner
from .plan import PlanResult, _bind_segment, _plan_chunk, assemble_plan, check_templates, prepare, shot_record, write_plan
from .segments import _Sources, run_segments

TAILS_PLAN_FILE = "seedvr2-tails-plan-v2.json"
ExtraScope = Sequence[tuple[str, int, int]]


@dataclass(frozen=True)
class TailShot:
    shot_id: str
    start: int  # source frame, inclusive (includes the leading context)
    end: int  # exclusive
    context: int
    gaps: tuple[Gap, ...]
    source: dict  # {path, sha256, frames}

    @property
    def frames(self) -> int:
        return self.end - self.start


def tail_gaps(config: ResolvedConfig, reads: Sequence[Read], extra_scope: ExtraScope = ()) -> list[Gap]:
    """Read frames outside the plan scope (each shot's whole clip) plus ``extra_scope`` (assembled tail ranges)."""
    return find_gaps(reads, add_scope(scope_from_shots(config.shots), extra_scope))


def context_frames(gap_frames: int, available_before: int, geometry: dict) -> int:
    """Leading context for a gap: the recipe context, capped to keep a sub-core gap in ONE chunk."""
    cap = geometry["context_frames_each_side"]
    if gap_frames < geometry["core_frames"]:
        cap = min(cap, geometry["core_frames"] - gap_frames)
    return max(0, min(cap, available_before))


def _source_of(shot_id: str, gaps: Sequence[Gap]) -> dict:
    sources = {(r.source["path"], r.source["sha256"], r.source["frames"]) for g in gaps for r in g.reads if r.source}
    if not sources:
        raise Refused(f"{shot_id}: no source clip is declared for the missing frames "
                      f"({', '.join(r for g in gaps for r in g.reasons())}); a tail needs the native clip "
                      "(outgoing_tail.native_path)")
    if len(sources) > 1:
        raise Refused(f"{shot_id}: the missing frames name {len(sources)} different source clips")
    path, sha, frames = sources.pop()
    return {"path": path, "sha256": sha, "frames": frames}


def tail_shots(gaps: Sequence[Gap], geometry: dict) -> list[TailShot]:
    """One range per shot (gaps of a shot are merged into the span that holds them all)."""
    by_shot: dict[str, list[Gap]] = defaultdict(list)
    for gap in gaps:
        by_shot[gap.shot].append(gap)
    shots = []
    for shot_id, shot_gaps in by_shot.items():
        source = _source_of(shot_id, shot_gaps)
        low, high = min(g.start for g in shot_gaps), max(g.end for g in shot_gaps)
        if high > source["frames"]:
            raise Refused(f"{shot_id}: missing frames reach f{high - 1}, the source clip has {source['frames']} frames")
        context = context_frames(high - low, low, geometry)
        shots.append(TailShot(shot_id, low - context, high, context, tuple(shot_gaps), source))
    return shots


def _gap_record(gap: Gap) -> dict:
    return {**gap.as_dict(), "transitions": [r.transition for r in gap.reads if r.transition]}


def tails_naming(block: dict) -> dict:
    """The main naming with ``tails/`` in front of ``{shot}`` in the output prefix (no collision with the main run)."""
    naming = {"input_name_template": block["input_name_template"],
              "output_prefix_template": block["output_prefix_template"].replace("{shot}", "tails/{shot}", 1)}
    check_templates(naming)
    return naming


def _episode_relative(path: str, episode_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(episode_root).resolve()).as_posix()
    except ValueError:
        return str(path)


def build_tails_plan(config: ResolvedConfig, *, repo_root: Path, reads: Sequence[Read], extra_scope: ExtraScope = (),
                     segments_root: Path | None = None, probe: Probe = probe_video) -> PlanResult | None:
    """The tails plan, or ``None`` when nothing is missing.  Without ``segments_root`` the plan is pending."""
    recipe, block, pilot_graph = prepare(config, repo_root)
    geometry = recipe["geometry"]
    gaps = tail_gaps(config, reads, extra_scope)
    if not gaps:
        return None
    naming = tails_naming(block)
    sources = _Sources(Geometry.from_recipe(recipe), recipe["native"], probe)
    by_id = {s["shot"]: s for s in config.shots}
    block = {**block, **naming}
    graphs: dict = {}
    shots = []
    for tail in tail_shots(gaps, geometry):
        path = Path(tail.source["path"])
        path = resolve_data_path(path if path.is_absolute() else Path(config.episode_root) / path)
        info = sources.check(tail.shot_id, path, tail.source["sha256"], tail.source["frames"])
        chunks = plan_chunks(tail.frames, geometry)
        for chunk in chunks:
            chunk["chunk_name"] = f"chunk-{chunk['index']:04d}"
        records = [_plan_chunk(c, tail.shot_id, tail.source["sha256"],
                               _bind_segment(segments_root, tail.shot_id, c["chunk_name"], c["segment_frames"],
                                             probe, info), block, recipe, pilot_graph, graphs) for c in chunks]
        shot = shot_record(shot_id=tail.shot_id, logical_shot=by_id[tail.shot_id]["logical_shot"],
                           source_path=_episode_relative(str(path), Path(config.episode_root)),
                           source_sha=tail.source["sha256"], info=info, frames=tail.frames, records=records,
                           recipe=recipe)
        shot["source_range"] = {"start_frame": tail.start, "end_frame_exclusive": tail.end,
                                "source_frames_total": tail.source["frames"]}
        shot["tail"] = {"context_before_frames": tail.context, "restored_gap_frames": sum(g.frames for g in tail.gaps),
                        "gaps": [_gap_record(g) for g in tail.gaps]}
        shots.append(shot)
    closed = check_coverage(reads, add_scope(scope_from_shots(config.shots), [
        *extra_scope, *((t.shot_id, t.start, t.end) for t in tail_shots(gaps, geometry))]))
    extra: dict[str, Any] = {"kind": "tails", "coverage": closed,
                             "tails": {"gap_count": len(gaps), "gap_frames": sum(g.frames for g in gaps),
                                       "shots": [s["shot_id"] for s in shots],
                                       "extra_scope": [list(r) for r in extra_scope]}}
    return assemble_plan(config, recipe, block, shots, graphs, extra=extra, naming=naming)


def plan_tails(config: ResolvedConfig, *, repo_root: Path, reads: Sequence[Read], out: Path,
               extra_scope: ExtraScope = (), dry_run: bool = False, probe: Probe = probe_video,
               runner: Runner = default_runner, ffmpeg: str = "ffmpeg", threads: int | None = None,
               verify_md5: bool = True) -> dict:
    """Plan, cut and bind the tails into ``out`` (must be fresh: the caller checks); one summary dict."""
    pending = build_tails_plan(config, repo_root=repo_root, reads=reads, extra_scope=extra_scope, probe=probe)
    if pending is None:
        return {"ok": True, "gaps": 0, "message": "every frame the timeline reads is inside the restored scope"}
    summary: dict[str, Any] = {"ok": True, "gaps": pending.plan["tails"]["gap_count"], "dry_run": dry_run,
                               "shots": [{"shot_id": s["shot_id"], "source_range": s["source_range"],
                                          "context_before_frames": s["tail"]["context_before_frames"],
                                          "gaps": s["tail"]["gaps"], "chunks": s["chunk_count"]}
                                         for s in pending.plan["shots"]]}
    if dry_run:
        return summary
    cut = run_segments(config, repo_root=repo_root, out_root=out, plan=pending.plan, probe=probe, runner=runner,
                       ffmpeg=ffmpeg, threads=threads, verify_md5=verify_md5)
    bound = build_tails_plan(config, repo_root=repo_root, reads=reads, extra_scope=extra_scope, segments_root=out,
                             probe=probe)
    assert bound is not None  # the same inputs produced a pending plan a moment ago
    written = write_plan(out, bound, plan_file=TAILS_PLAN_FILE)
    return {**summary, **written, "status": bound.plan["status"], "totals": bound.plan["totals"],
            "segments_receipt": cut["receipt_path"], "segments_cut": cut["cut"]}
