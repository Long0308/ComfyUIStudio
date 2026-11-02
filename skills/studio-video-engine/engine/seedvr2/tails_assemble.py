"""``jjv seedvr2 tails check|assemble``: prove a tails run, then cut the tail masters and the tail map.

Port of the first episode's hand tools ``check_tail_run.py`` and ``assemble_tail_masters.py``, generalised from "one chunk per
shot, context offset known" to any tails plan (``kind: "tails"``):

* ``check``: per chunk the COMPLETED job re-verifies (hashes, provenance, probes: ``receipts.verify_completed_chunk``),
  and the core's frames are bit-identical (framemd5) to ``crop(trim(raw))``; per shot the finalized concat
  (``runs/<shot>/shot.json``) has exactly the planned frames.  Read-only except one JSON report.
* ``assemble`` (only when ``check`` is green, re-run here): for every gap the core frames ``[gap - range_start, +n)``
  are cut losslessly into ``<out>/master-tails/<shot>-tail-<W>x<H>-n<first>-n<last>.mp4`` (context frames are
  dropped, never shown) and ``<out>/MASTER-TAIL-MAP.json`` (``jjv/master-tail-map/v1``, same keys as the first episode's
  ``mam-r27-master-tail-map/v1``) maps every output frame ``k`` of a transition to the clip frame, floor and ceil
  (``idx = (d + k) * native_fps / delivery_fps``), refusing a mapping that leaves the clip.
"""

from __future__ import annotations

import os
import uuid
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from ..core.errors import EngineError, Failed, Refused
from ..core.io import read_json, sha256_file, write_json_atomic, write_json_once
from ..media.probe import probe_video
from . import receipts as rc
from .execplan import ExecPlan
from .media_ops import CORE_ENCODINGS, Probe, Runner, core_trim_filter, default_runner, run_command, verify_video
from .segment_cut import framemd5, trim_filter

MAP_SCHEMA = "jjv/master-tail-map/v1"
MAP_FILE = "MASTER-TAIL-MAP.json"
REPORT_FILE = "tails-check.json"


def _tail_plan_shots(plan: ExecPlan) -> list[dict]:
    if plan.plan.get("kind") != "tails":
        raise Refused("this is not a tails plan (kind != 'tails'); tails check/assemble only read plans made by "
                      "jjv seedvr2 tails plan")
    return plan.plan["shots"]


def _chunk_checks(plan: ExecPlan, task: Any, probe: Probe, runner: Runner, ffmpeg: str,
                  chk: Callable[[str, bool, Any], None]) -> None:
    label = task.name
    paths = rc.task_paths(plan, task)
    if not paths["job"].is_file():
        chk(f"{label} job.json present", False, str(paths["job"]))
        return
    job = read_json(paths["job"])
    chk(f"{label} job COMPLETED", job.get("status") == "COMPLETED", job.get("status"))
    chk(f"{label} job bound to this plan sha", job.get("plan_sha256") == plan.sha256, job.get("plan_sha256"))
    if job.get("status") != "COMPLETED":
        return
    identity = rc.task_identity(plan, task, graph_file_sha256=sha256_file(plan.root / task.chunk["api_graph_path"]))
    try:
        rc.verify_completed_chunk(plan, task, job, identity, probe)
        chk(f"{label} receipts re-verify (hashes, provenance, probes)", True, None)
    except EngineError as error:
        chk(f"{label} receipts re-verify (hashes, provenance, probes)", False, str(error))
        return
    chunk = task.chunk
    vf = core_trim_filter(chunk["core_offset_in_segment"], chunk["core_frames"], plan.geometry)
    expected = framemd5(Path(job["output_path"]), vf=vf, runner=runner, ffmpeg=ffmpeg)
    found = framemd5(Path(job["core_path"]), runner=runner, ffmpeg=ffmpeg)
    chk(f"{label} core == crop(trim(raw)) (framemd5)", found == expected and len(found) == chunk["core_frames"],
        {"core_frames": len(found), "expected": len(expected)})


def check_tails_run(plan: ExecPlan, *, probe: Probe = probe_video, runner: Runner = default_runner,
                    ffmpeg: str = "ffmpeg", write_report: bool = True) -> dict:
    """Acceptance A of a tails run; ``all_pass`` only if every check is green."""
    _tail_plan_shots(plan)
    report, ok = [], True
    for shot_id in plan.shot_ids:
        row: dict[str, Any] = {"shot": shot_id, "checks": {}}

        def chk(name: str, condition: bool, detail: Any = None, row: dict = row) -> None:
            nonlocal ok
            row["checks"][name] = {"pass": bool(condition), "detail": detail}
            ok = ok and bool(condition)

        tasks = plan.shot_tasks(shot_id)
        for task in tasks:
            _chunk_checks(plan, task, probe, runner, ffmpeg, chk)
        receipt_path = plan.root / "runs" / shot_id / "shot.json"
        frames = tasks[0].shot["expected_output"]["restored_core_frames"]
        if not receipt_path.is_file():
            chk("shot.json present (execute finalizes a shot once every chunk is COMPLETED)", False, str(receipt_path))
        else:
            receipt = read_json(receipt_path)
            path = Path(receipt.get("path") or "")
            good = path.is_file() and sha256_file(path) == receipt.get("sha256")
            chk("shot concat sha256 == receipt", good, str(path))
            chk("shot concat frames == planned range", receipt.get("frame_count") == frames, receipt.get("frame_count"))
            row["core_path"] = str(path)
        report.append(row)
    result = {"all_pass": ok, "plan_sha256": plan.sha256, "shots": report}
    if write_report:
        write_json_atomic(plan.root / "runs" / REPORT_FILE, result, mode="ascii")
    return result


def _output_mapping(transition: dict, gap_start: int, frames: int, native_fps: Fraction) -> dict | None:
    fps = transition.get("delivery_fps")
    if not fps:
        return None
    floors, ceils = [], []
    for k in range(transition["output_frames"]):
        index = Fraction(transition["delivery_start_frame"] + k) * native_fps / fps
        floors.append(index.__floor__() - gap_start)
        ceils.append(index.__ceil__() - gap_start)
    if min(floors) < 0 or max(ceils) > frames - 1:
        raise Refused(f"transition {transition['id']}: the frame mapping leaves its tail clip "
                      f"(floor {min(floors)}, ceil {max(ceils)}, clip frames {frames})")
    return {"floor": floors, "ceil": ceils}


def _cut_clip(core: Path, clip: Path, start: int, frames: int, plan: ExecPlan, probe: Probe, runner: Runner,
              ffmpeg: str) -> None:
    g = plan.geometry
    if clip.exists():
        raise Refused(f"refusing to overwrite tail clip: {clip}")
    clip.parent.mkdir(parents=True, exist_ok=True)
    temporary = clip.with_name(f".{clip.stem}.{uuid.uuid4().hex}.tmp{clip.suffix}")
    command = [ffmpeg, "-v", "error", "-i", str(core), "-map", "0:v:0", "-vf", trim_filter(start, start + frames),
               "-fps_mode", "passthrough", "-an", *CORE_ENCODINGS[g.core_encoding], str(temporary)]
    try:
        run_command(runner, command, f"tail clip cut of {core.name}")
        verify_video(temporary, frames=frames, width=g.final_width, height=g.final_height, fps=g.fps,
                     probe=probe, error=Failed)
        expected = framemd5(core, vf=trim_filter(start, start + frames), runner=runner, ffmpeg=ffmpeg)
        if framemd5(temporary, runner=runner, ffmpeg=ffmpeg) != expected:
            raise Failed(f"tail clip {clip.name}: frames differ from the finalized core")
        try:
            os.link(temporary, clip)
        except FileExistsError as error:
            raise Refused(f"refusing to overwrite concurrent tail clip: {clip}") from error
    finally:
        temporary.unlink(missing_ok=True)


def assemble_tail_masters(plan: ExecPlan, out_dir: Path, *, probe: Probe = probe_video, runner: Runner = default_runner,
                          ffmpeg: str = "ffmpeg") -> dict:
    """Cut the tail clips and write ``MASTER-TAIL-MAP.json`` under ``out_dir`` (write-once); ``Refused`` unless green."""
    verdict = check_tails_run(plan, probe=probe, runner=runner, ffmpeg=ffmpeg)
    if not verdict["all_pass"]:
        failed = [f"{s['shot']}: {name}" for s in verdict["shots"] for name, c in s["checks"].items() if not c["pass"]]
        raise Refused("the tails run is not green, nothing assembled: " + "; ".join(failed[:8]),
                      evidence={"stage": "tails_check", "failed": failed})
    out, g = Path(out_dir), plan.geometry
    tails: list[dict] = []
    for shot, row in zip(_tail_plan_shots(plan), verdict["shots"]):
        window = shot["source_range"]
        for gap in shot["tail"]["gaps"]:
            first, frames = gap["start_frame"], gap["frames"]
            name = f"{shot['shot_id']}-tail-{g.final_width}x{g.final_height}-n{first:03d}-n{first + frames - 1:03d}.mp4"
            clip = out / "master-tails" / name
            _cut_clip(Path(row["core_path"]), clip, first - window["start_frame"], frames, plan, probe, runner, ffmpeg)
            base = {"shot": shot["shot_id"], "clip": f"master-tails/{name}", "clip_sha256": sha256_file(clip),
                    "frames": frames, "native_first": first, "start_from_frame_30fps": 0,
                    "source_core": row["core_path"]}
            for transition in gap["transitions"] or [None]:
                mapping = _output_mapping(transition, first, frames, g.fps) if transition else None
                tails.append({"transition": transition["id"] if transition else None, **base,
                              **({"delivery_fps": transition["delivery_fps"], "clip_frame_for_output_k": mapping}
                                 if mapping else {})})
    document = {"schema": MAP_SCHEMA, "plan_sha256": plan.sha256, "tails": tails}
    map_sha = write_json_once(out / MAP_FILE, document, mode="ascii")
    return {"ok": True, "map_path": str(out / MAP_FILE), "map_sha256": map_sha, "tails": tails}
