"""``jjv seedvr2 adopt``: copy a reviewed scratch plan INTO the episode tree, hash-bound and write-once.

``seedvr2 plan --out`` refuses a folder inside the episode tree (a plan is scratch until it is reviewed) while
``seedvr2 execute --execute`` refuses a plan folder outside it (run receipts live beside the plan).  ``adopt``
closes that gap (ENGINE gap 2).  It loads the scratch plan exactly as ``execute`` would (``load_exec_plan``:
identity, ``PLANNED_NOT_RENDERED``, recipe-derived chunk windows), proves every API graph (``verify_task_graph``:
canonical sha == plan, == pilot except the two ports) and every bound segment (sha256 == plan) BEFORE anything is
written, then copies plan + graphs + segments into ``--into`` (inside the episode root; never the root itself,
its ``engine/`` config folder, the Comfy tree, the segments root or the scratch folder) with no-overwrite writes
and records ``ADOPT.json`` (sha256 + size of every adopted file).  Re-adopting identical bytes is a no-op
(``already_adopted``); any drift is ``Refused``.  CPU only: no ComfyUI, no network; the scratch folder is read only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..comfy.staging import link_new_file, require_hash
from ..config.loader import REPO_ROOT, ResolvedConfig, require_recipe, resolve_episode
from ..core.errors import Refused
from ..core.io import read_json, sha256_bytes, write_json_once, write_once
from ..core.paths import require_inside
from .execplan import ExecPlan, load_exec_plan, verify_task_graph
from .plan import PLAN_FILE, refuse_output_inside
from .recipe import load_pilot_graph
from .tails import TAILS_PLAN_FILE

ADOPT_SCHEMA = "jjv/seedvr2-adopt/v1"
ADOPT_FILE = "ADOPT.json"
DEFAULT_INTO = ("engine", "stages", "seedvr2")  # the orchestrator's stage folder (engine/run/context.py stage_dir)
PLAN_FILES = (PLAN_FILE, TAILS_PLAN_FILE)


def resolve_plan_file(plan: Path) -> Path:
    """``--plan`` names the plan file or its scratch folder (holding exactly one known plan file)."""
    given = Path(plan)
    if given.is_file():
        return given.resolve()
    if not given.is_dir():
        raise Refused(f"--plan not found: {given}")
    found = [given / name for name in PLAN_FILES if (given / name).is_file()]
    if len(found) != 1:
        raise Refused(f"--plan folder {given} must hold exactly one of {list(PLAN_FILES)}; found "
                      f"{[p.name for p in found] or 'none'}")
    return found[0].resolve()


def default_into(config: ResolvedConfig, plan: ExecPlan) -> Path:
    """``<episode root>/engine/stages/seedvr2/<plan stem>-<plan sha12>`` (one folder per reviewed plan)."""
    return Path(config.episode_root).joinpath(*DEFAULT_INTO) / f"{plan.path.stem}-{plan.sha256[:12]}"


def check_destination(into: Path, config: ResolvedConfig, plan: ExecPlan) -> Path:
    """Inside the episode root, not the root or its ``engine/`` folder, outside Comfy/segments/scratch trees."""
    episode = Path(config.episode_root).resolve()
    target = require_inside(into, episode, "--into (run receipts live beside the adopted plan)")
    if target in (episode, episode / "engine"):
        raise Refused(f"--into {target} is the episode root or its engine/ config folder; choose a sub-folder")
    refuse_output_inside(target, [Path(config.machine["comfy"]["root"]), plan.segments_root, plan.root],
                         containers=(), label="--into")
    return target


def _collect(plan: ExecPlan, pilot_graph: dict, recipe: dict) -> list[dict[str, Any]]:
    """Every file the adoption copies, verified against the plan: plan, graphs, segments (relative paths)."""
    files: list[dict[str, Any]] = [{"kind": "plan", "path": plan.path.name, "source": plan.path,
                                    "sha256": plan.sha256, "bytes": plan.path.stat().st_size}]
    seen: set[str] = set()
    for task in plan.tasks:
        chunk, label = task.chunk, f"{task.shot_id}/{task.name}"
        _, graph_sha = verify_task_graph(plan, task, pilot_graph=pilot_graph, recipe=recipe)
        graph_rel = chunk["api_graph_path"]
        if graph_rel not in seen:
            seen.add(graph_rel)
            source = plan.root / graph_rel
            files.append({"kind": "graph", "path": graph_rel, "source": source, "sha256": graph_sha,
                          "bytes": source.stat().st_size, "chunk": label})
        segment_rel = chunk["segment_path"]
        segment = require_inside(plan.segments_root / segment_rel, plan.segments_root, f"{label} segment")
        require_hash(segment, chunk["segment_sha256"], f"{label} segment")
        if segment_rel not in seen:
            seen.add(segment_rel)
            files.append({"kind": "segment", "path": segment_rel, "source": segment, "sha256": chunk["segment_sha256"],
                          "bytes": segment.stat().st_size, "chunk": label})
    return files


def _copy(entry: dict[str, Any], into: Path) -> None:
    target = require_inside(into / entry["path"], into, f"adopted {entry['kind']}")
    if entry["kind"] == "segment":
        link_new_file(entry["source"], target, entry["sha256"], f"adopted segment {entry['chunk']}")
        return
    payload = Path(entry["source"]).read_bytes()
    if sha256_bytes(payload) != entry["sha256"]:
        raise Refused(f"{entry['kind']} {entry['path']} changed while adopting (sha256 differs)")
    written = write_once(target, payload)  # idempotent for identical bytes, Refused for different ones
    require_hash(target, written, f"adopted {entry['kind']} {entry['path']}")


def _receipt(config: ResolvedConfig, plan: ExecPlan, into: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    listed = [{k: (v.as_posix() if isinstance(v, Path) else v) for k, v in f.items() if k != "source"} for f in files]
    return {"schema": ADOPT_SCHEMA, "episode_id": plan.plan["episode_id"], "domain": plan.plan["domain"],
            "production_version": plan.plan["production_version"], "plan_kind": plan.plan.get("kind"),
            "plan_file": plan.path.name, "plan_sha256": plan.sha256, "config_sha256": config.config_sha256,
            "source_dir": str(plan.root), "segments_root": str(plan.segments_root), "adopted_dir": str(into),
            "chunk_count": len(plan.tasks), "graph_count": sum(f["kind"] == "graph" for f in files),
            "segment_count": sum(f["kind"] == "segment" for f in files),
            "bytes": sum(f["bytes"] for f in files), "files": listed}


def adopt_plan(config: ResolvedConfig, recipe: dict, *, plan_path: Path, into: Path | None = None,
               segments_root: Path | None = None, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Verify, copy and receipt; one summary dict (``plan_path`` is what ``execute`` takes next)."""
    plan = load_exec_plan(plan_path, config, recipe, segments_root=segments_root)
    files = _collect(plan, load_pilot_graph(recipe, Path(repo_root)), recipe)
    target = check_destination(Path(into) if into else default_into(config, plan), config, plan)
    receipt = _receipt(config, plan, target, files)
    receipt_path = target / ADOPT_FILE
    already = receipt_path.is_file()
    if already:
        found = read_json(receipt_path)
        if found != receipt:
            raise Refused(f"{receipt_path} records a different adoption (plan {found.get('plan_sha256')!r} from "
                          f"{found.get('source_dir')!r}); choose another --into")
    elif target.exists() and any(target.iterdir()):
        raise Refused(f"--into {target} is not empty and holds no {ADOPT_FILE}")
    for entry in files:
        _copy(entry, target)
    receipt_sha = write_json_once(receipt_path, receipt, mode="ascii")
    adopted = target / plan.path.name
    require_hash(adopted, plan.sha256, "adopted plan")
    return {"ok": True, "already_adopted": already, "plan_path": str(adopted), "plan_sha256": plan.sha256,
            "adopted_dir": str(target), "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha,
            "files": len(files), "graphs": receipt["graph_count"], "segments": receipt["segment_count"],
            "bytes": receipt["bytes"], "status": plan.plan["status"],
            "next": f"jjv seedvr2 execute --episode <E> --plan \"{adopted}\" [--execute]"}


def register_cli(seedvr2_verbs: Any) -> None:
    p = seedvr2_verbs.add_parser("adopt", help="copy a reviewed scratch plan INTO the episode tree (hash-bound, "
                                               "write-once, ADOPT.json) so 'execute --execute' accepts it")
    p.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    p.add_argument("--plan", required=True, help="scratch plan folder (seedvr2 plan --out) or the plan file")
    p.add_argument("--segments-root", default=None,
                   help="folder holding <shot>/chunks/<chunk>/source-segment.mp4 (default: the plan folder)")
    p.add_argument("--into", default=None,
                   help="destination inside the episode tree (default: engine/stages/seedvr2/<plan>-<sha12>)")


def run(args: argparse.Namespace) -> int:
    config = resolve_episode(args.episode)
    recipe = require_recipe(config, "seedvr2")  # a domain without a qualified recipe refuses here
    summary = adopt_plan(config, recipe, plan_path=resolve_plan_file(Path(args.plan)),
                         into=Path(args.into) if args.into else None,
                         segments_root=Path(args.segments_root) if args.segments_root else None)
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=str))
    return 0
