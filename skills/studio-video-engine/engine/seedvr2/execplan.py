"""Load and validate a SeedVR2 plan v2 for execution; select the chunks to run.

The plan is *evidence*, not authority: every geometry value is re-derived from the resolved
recipe and compared, chunk windows are recomputed with ``plan_chunks`` and must equal the
plan's, and the plan must belong to the resolved episode/domain/recipe.  Paths inside the plan
are relative: graphs to the plan folder, segments to ``segments_root`` (default: the same
folder).  Segment hashes are plan-bound; graphs are bound by canonical sha.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config.loader import ResolvedConfig
from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file
from ..core.paths import require_inside
from .chunking import plan_chunks, shot_source_range
from .media_ops import Geometry
from .plan import PLAN_SCHEMA
from .recipe import INPUT_PORT, OUTPUT_PORT, clone_api_graph

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_WINDOW_KEYS = ("core_start_frame", "core_end_frame_exclusive", "core_frames", "context_before_frames",
                "context_after_frames", "segment_start_frame", "segment_end_frame_exclusive",
                "segment_frames", "core_offset_in_segment", "seedvr2_padded_frames")
WINDOW_KEYS = _WINDOW_KEYS
PLAN_KINDS = (None, "tails")  # None = a normal whole-clip plan; "tails" = sub-range plan (jjv seedvr2 tails plan)


@dataclass(frozen=True)
class Task:
    shot: dict
    chunk: dict

    @property
    def shot_id(self) -> str:
        return self.shot["shot_id"]

    @property
    def name(self) -> str:
        return self.chunk["chunk_name"]


@dataclass(frozen=True)
class ExecPlan:
    plan: dict
    path: Path
    sha256: str
    root: Path  # the plan folder: graphs and run receipts live under it
    segments_root: Path
    geometry: Geometry
    tasks: tuple[Task, ...]

    def shot_tasks(self, shot_id: str) -> list[Task]:
        return [t for t in self.tasks if t.shot_id == shot_id]

    @property
    def shot_ids(self) -> list[str]:
        return [shot["shot_id"] for shot in self.plan["shots"]]


def _same(label: str, found: object, expected: object) -> None:
    if found != expected:
        raise Refused(f"plan {label} differs from the resolved config: {found!r} != {expected!r}; "
                      "re-plan (jjv seedvr2 plan) against the current config")


def _check_identity(plan: dict, config: ResolvedConfig, recipe: dict, geometry: Geometry) -> None:
    _same("schema", plan.get("schema"), PLAN_SCHEMA)
    if plan.get("status") != "PLANNED_NOT_RENDERED":
        raise Refused(f"plan status is {plan.get('status')!r}; execution needs PLANNED_NOT_RENDERED "
                      "(every chunk segment bound and its graph emitted)")
    if plan.get("kind") not in PLAN_KINDS:
        raise Refused(f"plan kind {plan.get('kind')!r} is unknown (known: normal, 'tails')")
    _same("canonicalization", plan.get("canonicalization"), "ascii")
    _same("machine sha256 (gpu_lock_path, comfy url/container/output_dir)", plan.get("machine_sha256"),
          canonical_sha256(config.machine, mode="ascii"))
    _same("domain sha256", plan.get("domain_sha256"), canonical_sha256(config.domain, mode="ascii"))
    _same("domain", plan.get("domain"), config.domain["domain_id"])
    _same("episode_id", plan.get("episode_id"), config.episode["episode_id"])
    _same("film_id", plan.get("film_id"), config.episode["film_id"])
    _same("production_version", plan.get("production_version"),
          (config.episode.get("seedvr2") or {}).get("production_version"))
    _same("recipe_id", plan.get("recipe_id"), recipe["recipe_id"])
    _same("recipe sha256", plan.get("recipe_canonical_sha256"), canonical_sha256(recipe, mode="ascii"))
    _same("recipe_geometry", plan.get("recipe_geometry"), recipe["geometry"])
    target = plan.get("target") or {}
    keys = ("processing_width", "processing_height", "final_width", "final_height",
            "crop_left", "crop_top", "crop_filter", "fps")
    _same("target", {k: target.get(k) for k in keys},
          {"processing_width": geometry.processing_width, "processing_height": geometry.processing_height,
           "final_width": geometry.final_width, "final_height": geometry.final_height,
           "crop_left": geometry.crop_left, "crop_top": geometry.crop_top,
           "crop_filter": geometry.crop_filter, "fps": geometry.fps_text})


def _check_chunk(shot_id: str, chunk: dict, expected: dict, position: int) -> None:
    label = f"{shot_id}/{chunk.get('chunk_name')}"
    if chunk.get("index") != position or chunk.get("chunk_name") != f"chunk-{position:04d}":
        raise Refused(f"{label}: chunk index/name are not contiguous")
    for key in _WINDOW_KEYS:
        if chunk.get(key) != expected[key]:
            raise Refused(f"{label}: {key} {chunk.get(key)!r} != recipe-derived {expected[key]!r}")
    if chunk.get("expected_raw_output_frames") != chunk["segment_frames"]:
        raise Refused(f"{label}: expected_raw_output_frames must equal segment_frames (plan v2)")
    if chunk.get("expected_core_output_frames") != chunk["core_frames"]:
        raise Refused(f"{label}: expected_core_output_frames must equal core_frames")
    if chunk["core_offset_in_segment"] + chunk["core_frames"] > chunk["segment_frames"]:
        raise Refused(f"{label}: core trim exceeds the raw output")
    for key in ("segment_sha256", "api_graph_canonical_sha256"):
        if not isinstance(chunk.get(key), str) or not _SHA.match(chunk[key]):
            raise Refused(f"{label}: {key} is not a bound sha256")
    for key in ("segment_path", "api_graph_path", "comfy_input_name"):
        if not isinstance(chunk.get(key), str) or not chunk[key].strip():
            raise Refused(f"{label}: {key} is missing")
    if chunk.get("gpu_submitted") or chunk.get("comfy_post_called") or chunk.get("prompt_id"):
        raise Refused(f"{label}: plan claims a submission; a plan is prepare-only")


def _shot_tasks(shot: dict, config_shot: dict, recipe: dict, *, tails: bool = False) -> list[Task]:
    shot_id = shot.get("shot_id")
    if not isinstance(shot_id, str) or not _SAFE_ID.match(shot_id):
        raise Refused(f"unsafe shot id: {shot_id!r}")
    video, native = shot["source_video"], recipe["native"]
    if (video.get("width"), video.get("height")) != (native["width"], native["height"]):
        raise Refused(f"{shot_id}: plan source size {video.get('width')}x{video.get('height')} is not the "
                      f"recipe native size {native['width']}x{native['height']}")
    frames = video["frames"]
    window = shot_source_range(shot)
    if tails:
        # A tails shot restores a sub-range of a NATIVE clip that is not the config shot clip: the plan binds it
        # (source sha, range); the segment sha256 is what execute verifies against the file on disk.
        if window is None:
            raise Refused(f"{shot_id}: a tails plan shot needs a source_range")
        if not isinstance(shot.get("source_sha256"), str) or not _SHA.match(shot["source_sha256"]):
            raise Refused(f"{shot_id}: tails source_sha256 is not a sha256")
        _same(f"{shot_id} planned frames", frames, window[1] - window[0])
    else:
        if window is not None:
            raise Refused(f"{shot_id}: source_range is only valid in a tails plan")
        _same(f"{shot_id} source sha256", shot.get("source_sha256"), config_shot["clip"]["sha256"])
        _same(f"{shot_id} source frames", frames, config_shot["clip"]["frames"])
    expected = plan_chunks(frames, recipe["geometry"])
    chunks = shot.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != len(expected):
        raise Refused(f"{shot_id}: chunk count differs from the recipe-derived plan")
    for position, (chunk, win) in enumerate(zip(chunks, expected)):
        _check_chunk(shot_id, chunk, win, position)
    if shot["expected_output"]["restored_core_frames"] != frames:
        raise Refused(f"{shot_id}: restored core frame total differs from the source")
    return [Task(shot, chunk) for chunk in chunks]


def _match_shots(plan: dict, config: ResolvedConfig) -> list[dict]:
    """The config shot of every plan shot: all of them, in order (normal) or an ordered subset (tails)."""
    plan_ids = [s.get("shot_id") for s in plan.get("shots") or []]
    config_ids = [s["shot"] for s in config.shots]
    if plan.get("kind") != "tails":
        if plan_ids != config_ids:
            raise Refused("plan shots differ from the episode shots (ids or order)")
        return list(config.shots)
    if not plan_ids or len(set(plan_ids)) != len(plan_ids) or any(i not in config_ids for i in plan_ids):
        raise Refused("tails plan shots must be a non-empty, duplicate-free subset of the episode shots")
    if plan_ids != [i for i in config_ids if i in plan_ids]:
        raise Refused("tails plan shots are not in episode order")
    by_id = {s["shot"]: s for s in config.shots}
    return [by_id[i] for i in plan_ids]


def load_exec_plan(plan_path: Path, config: ResolvedConfig, recipe: dict, *,
                   segments_root: Path | None = None) -> ExecPlan:
    plan_path = Path(plan_path).resolve()
    if not plan_path.is_file():
        raise Refused(f"plan not found: {plan_path}")
    plan = read_json(plan_path)
    geometry = Geometry.from_recipe(recipe)
    _check_identity(plan, config, recipe, geometry)
    matched = _match_shots(plan, config)
    tasks: list[Task] = []
    for shot, config_shot in zip(plan["shots"], matched):
        tasks.extend(_shot_tasks(shot, config_shot, recipe, tails=plan.get("kind") == "tails"))
    if plan["totals"]["total_chunks"] != len(tasks):
        raise Refused("plan totals.total_chunks differs from the chunks present")
    root = plan_path.parent
    return ExecPlan(plan=plan, path=plan_path, sha256=sha256_file(plan_path), root=root,
                    segments_root=Path(segments_root).resolve() if segments_root else root,
                    geometry=geometry, tasks=tuple(tasks))


def verify_task_graph(plan: ExecPlan, task: Task, *, pilot_graph: dict, recipe: dict) -> tuple[dict, str]:
    """The chunk API graph of ``task`` (shared by ``execute`` and ``adopt``): inside ``<plan>/workflows``,
    canonical sha == the plan's, and == the pilot graph except the two ports (rebuilt from the plan naming).
    Returns ``(graph, file sha256)``."""
    chunk = task.chunk
    root = plan.root / "workflows"
    path = require_inside(plan.root / chunk["api_graph_path"], root, f"{task.name} API graph")
    if not path.is_file():
        raise Refused(f"{task.shot_id}/{task.name} API graph is missing: {path}")
    graph = read_json(path)
    if canonical_sha256(graph, mode="ascii") != chunk["api_graph_canonical_sha256"]:
        raise Refused(f"{task.shot_id}/{task.name} canonical API graph hash changed")
    prefix = plan.plan["naming"]["output_prefix_template"].format(shot=task.shot_id, chunk=task.name)
    rebuilt, _ = clone_api_graph(pilot_graph, recipe, input_name=chunk["comfy_input_name"], output_prefix=prefix)
    if canonical_sha256(rebuilt, mode="ascii") != chunk["api_graph_canonical_sha256"]:
        raise Refused(f"{task.shot_id}/{task.name} graph differs from the pilot beyond the two ports "
                      f"({INPUT_PORT[0]}.{INPUT_PORT[1]}, {OUTPUT_PORT[0]}.{OUTPUT_PORT[1]})")
    return graph, sha256_file(path)


def select_tasks(tasks: tuple[Task, ...] | list[Task], *, only: str | None = None,
                 max_chunks: int | None = None) -> list[Task]:
    """``--only SHOT[:IDX],...`` in the requested order, then ``--max-chunks``."""
    selected = list(tasks)
    if only:
        selectors = [item.strip() for item in only.split(",")]
        if any(not item for item in selectors):
            raise Refused("--only selectors must not be empty")
        selected, seen = [], set()
        for selector in selectors:
            shot_id, separator, index_text = selector.partition(":")
            matches = [t for t in tasks if t.shot_id == shot_id]
            if not matches:
                raise Refused(f"--only shot is absent from the plan: {shot_id}")
            if separator:
                try:
                    index = int(index_text)
                except ValueError:
                    raise Refused(f"--only index must be an integer: {selector}") from None
                matches = [t for t in matches if t.chunk["index"] == index]
                if not matches:
                    raise Refused(f"--only chunk is absent: {selector}")
            for task in matches:
                key = (task.shot_id, task.chunk["index"])
                if key in seen:
                    raise Refused(f"--only chunk is duplicated: {selector}")
                seen.add(key)
                selected.append(task)
    if max_chunks is not None:
        if max_chunks < 1:
            raise Refused("--max-chunks must be positive")
        selected = selected[:max_chunks]
    if not selected:
        raise Refused("no chunks selected")
    return selected
