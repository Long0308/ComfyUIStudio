"""SeedVR2 plan v2 (prepare only): shots -> chunks -> per-chunk API graphs, driven by config.

Plan-only: nothing is cut, uploaded or submitted.  Existing source segments can be *bound*
(read-only, hashed) through ``segments_root``; without one the plan marks segments pending and
emits no graphs, because a graph names its input segment by content hash.

v2 contract: ``expected_raw_output_frames`` equals ``segment_frames`` (the frames SeedVR2
returns for the raw segment); ``seedvr2_padded_frames`` is informational only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence

from ..config.loader import REPO_ROOT, ResolvedConfig, require_recipe
from ..config.pins import check_recipe_self_pins
from ..core.errors import Refused
from ..core.io import canonical_sha256, sha256_file, write_json_once
from ..media.probe import VideoInfo, probe_video
from .chunking import plan_chunks, seam_pairs
from .coverage import Read, add_scope, check_coverage, scope_from_shots
from .recipe import ALLOWED_PORT_PATHS, clone_api_graph, load_pilot_graph

PLAN_SCHEMA = "jjv/seedvr2-plan/v2"
PLAN_FILE = "seedvr2-plan-v2.json"
EPISODES_DIR = "production-local"  # <repo>/production-local/<film>/<episode>/engine/episode.json (loader.find_episode_file)
EPISODE_MARKER = Path("engine") / "episode.json"  # a folder holding this file IS an episode tree
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FIELDS = {"shot": "S01_A", "chunk": "chunk-0000", "src_sha16": "0" * 16, "seg_sha12": "0" * 12,
           "start": 0, "end": 1}  # template fields (not plan keys): {start:06d}-{end:06d} in names
Probe = Callable[..., VideoInfo]


@dataclass(frozen=True)
class PlanResult:
    plan: dict
    graphs: dict  # relative path -> API graph


def check_templates(block: dict) -> None:
    """Both templates may use only known fields, must name shot+chunk, and stay path-safe."""
    names = {"input_name_template": ("shot", "chunk", "seg_sha12"), "output_prefix_template": ("shot", "chunk")}
    for key, required in names.items():
        template = block[key]
        for field in required:
            if "{" + field not in template:
                raise Refused(f"seedvr2.{key} must use {{{field}}}")
        try:
            sample = template.format(**_FIELDS)
        except (KeyError, IndexError, ValueError) as error:
            raise Refused(f"seedvr2.{key} is not a valid template: {error!r}") from error
        if key == "input_name_template" and not _SAFE_NAME.match(sample):
            raise Refused("seedvr2.input_name_template must produce a plain file name")
        if key == "output_prefix_template" and (
                ".." in sample or sample.startswith(("/", "\\")) or ":" in sample or "\\" in sample):
            raise Refused("seedvr2.output_prefix_template must be a relative forward-slash path")


def _bind_source(shot: dict, episode_root: Path, geometry: dict, probe: Probe,
                 native: dict) -> tuple[Path, VideoInfo]:
    path = Path(episode_root) / shot["clip"]["path"]
    if not path.is_file():
        raise Refused(f"{shot['shot']}: source clip not found: {path}")
    actual = sha256_file(path)
    if actual != shot["clip"]["sha256"]:
        raise Refused(f"{shot['shot']}: source sha256 {actual} != config {shot['clip']['sha256']}")
    info = probe(path)
    if info.frames is None:
        info = probe(path, count_packets=True)
    if info.frames != shot["clip"]["frames"]:
        raise Refused(f"{shot['shot']}: source has {info.frames} frames, config says {shot['clip']['frames']}")
    if info.fps != Fraction(geometry["fps"]):
        raise Refused(f"{shot['shot']}: source fps {info.fps} != recipe {geometry['fps']}")
    if info.width * geometry["processing_height"] != geometry["processing_width"] * info.height:
        raise Refused(f"{shot['shot']}: source aspect cannot map to the processing size without distortion")
    if (info.width, info.height) != (native["width"], native["height"]):
        raise Refused(f"{shot['shot']}: source is {info.width}x{info.height}, the qualified recipe native "
                      f"size is {native['width']}x{native['height']}; a different native size needs a new "
                      "recipe qualified by a user-authorised pilot")
    return path, info


def _bind_segment(root: Path | None, shot_id: str, name: str, frames: int, probe: Probe,
                  source: VideoInfo) -> tuple[str, str | None]:
    relative = f"{shot_id}/chunks/{name}/source-segment.mp4"
    if root is None or not (Path(root) / relative).is_file():
        return relative, None
    path = Path(root) / relative
    info = probe(path)
    if info.frames is None:
        info = probe(path, count_packets=True)
    if info.frames != frames:
        raise Refused(f"{shot_id}/{name}: segment has {info.frames} frames, plan needs {frames}")
    if info.fps != source.fps:
        raise Refused(f"{shot_id}/{name}: segment fps {info.fps} != source fps {source.fps}")
    if (info.width, info.height) != (source.width, source.height):
        raise Refused(f"{shot_id}/{name}: segment size {info.width}x{info.height} != source "
                      f"{source.width}x{source.height}")
    return relative, sha256_file(path)


def _plan_chunk(chunk: dict, shot_id: str, source_sha: str, segment: tuple[str, str | None],
                block: dict, recipe: dict, pilot_graph: dict, graphs: dict) -> dict:
    relative, segment_sha = segment
    name = chunk["chunk_name"]
    record = {
        **chunk,
        "frame_range": {  # key names kept identical to v004 (consumed by receipts and GUI titles)
            "start_frame": chunk["segment_start_frame"],
            "end_frame_exclusive": chunk["segment_end_frame_exclusive"],
            "frames": chunk["segment_frames"],
            **{k: chunk[k] for k in ("core_start_frame", "core_end_frame_exclusive", "core_frames",
                                     "context_before_frames", "context_after_frames")}},
        "expected_raw_output_frames": chunk["segment_frames"],  # v2: == segment_frames
        "expected_core_output_frames": chunk["core_frames"],
        "segment_path": relative, "segment_sha256": segment_sha,
        "comfy_input_name": None, "api_graph_canonical_sha256": None, "api_graph_path": None,
        "pilot_diff": None, "gpu_submitted": False, "comfy_post_called": False, "prompt_id": None,
    }
    seconds = recipe["pilot"]["server_execution_s"]
    record["estimate"] = {
        "basis": f"{seconds} s measured for one {recipe['geometry']['max_raw_segment_frames']}-frame pilot chunk",
        "gpu_seconds_conservative": seconds,
        "gpu_seconds_linear_by_padded_frames": round(
            seconds * chunk["seedvr2_padded_frames"] / float(recipe["geometry"]["max_raw_segment_frames"]), 2),
    }
    if segment_sha is None:
        return record
    input_name = block["input_name_template"].format(
        shot=shot_id, chunk=name, src_sha16=source_sha[:16], seg_sha12=segment_sha[:12],
        start=chunk["segment_start_frame"], end=chunk["segment_end_frame_exclusive"])
    prefix = block["output_prefix_template"].format(shot=shot_id, chunk=name)
    graph, changes = clone_api_graph(pilot_graph, recipe, input_name=input_name, output_prefix=prefix)
    canonical = canonical_sha256(graph, mode="ascii")
    graph_path = f"workflows/{shot_id}/{name}-{canonical}.api.json"
    graphs[graph_path] = graph
    record.update(comfy_input_name=input_name, api_graph_canonical_sha256=canonical,
                  api_graph_path=graph_path, pilot_diff={"api_changed_keys": changes})
    return record


def _plan_shot(shot: dict, config: ResolvedConfig, recipe: dict, block: dict, pilot_graph: dict,
               segments_root: Path | None, probe: Probe, graphs: dict) -> dict:
    geometry = recipe["geometry"]
    _, info = _bind_source(shot, Path(config.episode_root), geometry, probe, recipe["native"])
    source_sha = shot["clip"]["sha256"]
    chunks = plan_chunks(info.frames, geometry)
    for chunk in chunks:
        chunk["chunk_name"] = f"chunk-{chunk['index']:04d}"
    records = [
        _plan_chunk(chunk, shot["shot"], source_sha,
                    _bind_segment(segments_root, shot["shot"], chunk["chunk_name"],
                                  chunk["segment_frames"], probe, info),
                    block, recipe, pilot_graph, graphs)
        for chunk in chunks
    ]
    return shot_record(shot_id=shot["shot"], logical_shot=shot["logical_shot"], source_path=shot["clip"]["path"],
                       source_sha=source_sha, info=info, frames=info.frames, records=records, recipe=recipe)


def shot_record(*, shot_id: str, logical_shot: str, source_path: str, source_sha: str, info: VideoInfo,
                frames: int, records: list[dict], recipe: dict) -> dict:
    """One plan shot around its planned chunk ``records`` (``frames`` = frames this plan restores)."""
    geometry = recipe["geometry"]
    return {
        "shot_id": shot_id, "logical_shot": logical_shot,
        "source_path": source_path, "source_sha256": source_sha,
        "source_video": {"width": info.width, "height": info.height, "fps": geometry["fps"],
                         "frames": frames},
        "chunks": records, "chunk_count": len(records),
        "expected_output": {
            "restored_core_frames": frames,
            "processing_width": geometry["processing_width"], "processing_height": geometry["processing_height"],
            "final_crop": {"width": geometry["final_width"], "height": geometry["final_height"],
                           "left": geometry["final_crop_left"], "top": geometry["final_crop_top"]},
            "fps": geometry["fps"],
        },
        "seam_pairs_to_inspect": seam_pairs(records),
        "estimate": {
            "gpu_seconds_conservative": round(len(records) * recipe["pilot"]["server_execution_s"], 2),
            "gpu_seconds_linear_by_padded_frames": round(
                sum(r["estimate"]["gpu_seconds_linear_by_padded_frames"] for r in records), 2),
        },
        "acceptance_state": "PLANNED_NOT_RENDERED_NOT_ACCEPTED",
    }


def prepare(config: ResolvedConfig, repo_root: Path) -> tuple[dict, dict, dict]:
    """``(recipe, naming block, pilot graph)`` after every recipe/template guard; ``Refused`` otherwise."""
    recipe = require_recipe(config, "seedvr2")
    unpinned = check_recipe_self_pins(recipe)
    if unpinned:
        raise Refused("; ".join(unpinned))
    if set(recipe["allowed_api_diff_paths"]) != ALLOWED_PORT_PATHS:
        raise Refused(f"allowed_api_diff_paths must be exactly {sorted(ALLOWED_PORT_PATHS)}")
    block = config.episode.get("seedvr2")
    if block is None:
        raise Refused(f"episode {config.episode['episode_id']!r} has no seedvr2 block (naming templates)")
    check_templates(block)
    return recipe, block, load_pilot_graph(recipe, Path(repo_root))


def build_plan(config: ResolvedConfig, *, repo_root: Path, segments_root: Path | None = None,
               probe: Probe = probe_video, reads: Sequence[Read] | None = None,
               extra_scope: Sequence[tuple[str, int, int]] = ()) -> PlanResult:
    """Plan every shot of ``config``; ``Refused`` if the domain has no qualified recipe.

    With ``reads`` (what the timeline displays, see ``coverage``) the plan first proves that every read
    frame lies in the restored scope (each shot's whole clip plus ``extra_scope`` tail ranges) and is
    ``Refused`` before binding any source when one does not."""
    recipe, block, pilot_graph = prepare(config, repo_root)
    coverage = None
    if reads is not None:
        coverage = check_coverage(reads, add_scope(scope_from_shots(config.shots), extra_scope))
    graphs: dict = {}
    shots = [_plan_shot(shot, config, recipe, block, pilot_graph, segments_root, probe, graphs)
             for shot in config.shots]
    return assemble_plan(config, recipe, block, shots, graphs, extra={"coverage": coverage} if coverage else {})


def assemble_plan(config: ResolvedConfig, recipe: dict, block: dict, shots: list[dict], graphs: dict, *,
                  extra: dict | None = None, naming: dict | None = None) -> PlanResult:
    """The plan envelope around already planned ``shots`` (shared by the main plan and the tails plan)."""
    chunks = [c for s in shots for c in s["chunks"]]
    bound = sum(1 for c in chunks if c["segment_sha256"])
    geometry = recipe["geometry"]
    plan = {
        "schema": PLAN_SCHEMA,
        "status": "PLANNED_NOT_RENDERED" if bound == len(chunks) else "PLANNED_SEGMENTS_PENDING",
        "episode_id": config.episode["episode_id"], "film_id": config.episode["film_id"],
        "domain": config.domain["domain_id"], "production_version": block["production_version"],
        "recipe_id": recipe["recipe_id"], "recipe_canonical_sha256": canonical_sha256(recipe, mode="ascii"),
        "config_sha256": config.config_sha256, "canonicalization": "ascii",
        # execution refuses a plan whose machine/domain config changed since (re-plan instead)
        "machine_sha256": canonical_sha256(config.machine, mode="ascii"),
        "domain_sha256": canonical_sha256(config.domain, mode="ascii"),
        "naming": naming or {"input_name_template": block["input_name_template"],
                             "output_prefix_template": block["output_prefix_template"]},
        "pilot": {k: recipe["pilot"][k] for k in (
            "prompt_id", "graph_file_sha256", "graph_canonical_sha256", "graph_recipe_sha256",
            "server_execution_s", "sampled_peak_container_memory_bytes", "sampled_peak_gpu_mib")},
        "recipe_geometry": dict(geometry),
        "target": {"processing_width": geometry["processing_width"], "processing_height": geometry["processing_height"],
                   "final_width": geometry["final_width"], "final_height": geometry["final_height"],
                   "crop_left": geometry["final_crop_left"], "crop_top": geometry["final_crop_top"],
                   "crop_filter": (f"crop={geometry['final_width']}:{geometry['final_height']}:"
                                   f"{geometry['final_crop_left']}:{geometry['final_crop_top']}"),
                   "fps": geometry["fps"]},
        "workflow_diff_contract": {"allowed_api_changed_paths": sorted(recipe["allowed_api_diff_paths"]),
                                   "all_other_api_recipe_keys_identical": True},
        "execution": {"prepare_only": True, "gpu_job_submitted": False, "comfy_post_called": False,
                      "automatic_queue": False, "prompt_id": None, "serialize_gpu_chunks": True},
        "totals": {"total_sources": len(shots), "total_source_frames": sum(s["source_video"]["frames"] for s in shots),
                   "total_chunks": len(chunks), "segments_bound": bound, "total_api_graphs": len(graphs)},
        "estimate": {"gpu_seconds_conservative": round(len(chunks) * recipe["pilot"]["server_execution_s"], 2),
                     "gpu_seconds_linear_by_padded_frames": round(
                         sum(s["estimate"]["gpu_seconds_linear_by_padded_frames"] for s in shots), 2)},
        "shots": shots,
        "acceptance_state": "NOT_RENDERED_NOT_ACCEPTED", "fullfilm_complete": False, "registration_allowed": False,
    }
    plan.update(extra or {})
    return PlanResult(plan, graphs)


def container_roots(repo_root: Path = REPO_ROOT) -> tuple[Path, Path]:
    """The two trees that hold EVERY episode: the repo root and the episodes root (``EPISODES_DIR``).

    They also hold the machine-level engine scratch (``<episodes root>/engine/staging/``, where pytest's
    ``--basetemp`` may live), so a folder INSIDE them is not evidence by itself: it is judged by the precise
    trees (episode root, Comfy root, segments root) and by ``EPISODE_MARKER`` (any episode tree)."""
    repo = Path(repo_root).resolve()
    return repo, (repo / EPISODES_DIR).resolve()


def _episode_tree_above(out: Path, container: Path) -> Path | None:
    """The nearest ancestor of ``out`` below ``container`` that is an episode tree, if any."""
    for folder in (out, *out.parents):
        if folder == container:
            return None
        if (folder / EPISODE_MARKER).is_file():
            return folder
    return None


def refuse_output_inside(out_dir: Path, protected: list[Path | None], *,
                         containers: Sequence[Path] | None = None, label: str = "--out") -> Path:
    """The plan goes to a fresh scratch location: not inside, equal to, or above any evidence tree.

    A root that is one of ``containers`` (default :func:`container_roots`) is refused only when ``--out`` IS it or
    sits ABOVE it: inside such a container only the precise roots of ``protected`` and any episode tree
    (``EPISODE_MARKER``) are refused, so a scratch folder under ``<episodes root>/engine/staging/`` is accepted
    while ``<episodes root>/<film>/<other episode>/...`` is not."""
    out = Path(out_dir).resolve()
    holders = {Path(c).resolve() for c in (container_roots() if containers is None else containers)}
    for root in protected:
        if root is None:
            continue
        resolved = Path(root).resolve()
        if out == resolved or out in resolved.parents:
            raise Refused(f"{label} {out} is inside, equal to or above protected tree {resolved}")
        if resolved not in out.parents:
            continue
        if resolved not in holders:
            raise Refused(f"{label} {out} is inside, equal to or above protected tree {resolved}")
        episode = _episode_tree_above(out, resolved)
        if episode is not None:
            raise Refused(f"{label} {out} is inside, equal to or above protected tree {episode} "
                          f"(an episode tree: it holds {EPISODE_MARKER.as_posix()})")
    return out


def require_fresh_out(out_dir: Path) -> None:
    """``--out`` must be absent or an empty directory, so a plan never lands among old files."""
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        raise Refused(f"--out {out} exists and is not a directory")
    if out.is_dir() and any(out.iterdir()):
        raise Refused(f"--out {out} is not empty")


def write_plan(out_dir: Path, result: PlanResult, *, plan_file: str = PLAN_FILE) -> dict:
    """Write graphs and the plan with no-overwrite semantics; return paths and shas."""
    out = Path(out_dir)
    graph_shas = {rel: write_json_once(out / rel, graph, mode="ascii") for rel, graph in sorted(result.graphs.items())}
    plan_sha = write_json_once(out / plan_file, result.plan, mode="ascii")
    return {"plan_path": str(out / plan_file), "plan_sha256": plan_sha, "graph_files": len(graph_shas)}
