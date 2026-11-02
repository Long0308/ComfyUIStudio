"""The stage DAG of ``jjv run episode`` is DATA (``recipes/run/<id>.json``, schema ``jjv/run-dag/v1``).

Nothing here names a stage, a verb or a domain: the recipe does.  This module loads and validates the shape
(unique ids, ``needs`` only point backwards, every ``human`` gate is a known kind, argv tokens are strings),
refuses a recipe for another domain, and selects the ``--from`` / ``--to`` range.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.loader import SKILL_ROOT
from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file

SCHEMA = "jjv/run-dag/v1"
RECIPE_DIR = SKILL_ROOT / "recipes" / "run"
DEFAULT_DAG = RECIPE_DIR / "episode-dag-v001.json"
# Human gate kinds the orchestrator knows how to read (engine/run/gates.py); any other name is a recipe error.
HUMAN_GATES = ("voice-listen-approval", "images-approval", "h3-acceptance", "music-approval", "user-review",
               "publish-approval", "receipt-gate", "library-coverage")


@dataclass(frozen=True)
class Step:
    id: str
    argv: tuple[str, ...]
    gpu: bool = False
    per_shot: str | None = None
    human: str | None = None
    note: str | None = None
    write_once: str | None = None                                  # skip when this output exists (write-once verbs)
    argv_if_exists: tuple[tuple[str, tuple[str, ...]], ...] = ()   # (file, extra argv) appended only when file exists
    pre: dict[str, Any] | None = None                              # read-only check before the step (engine/run/checks.py)
    argv_if_mode: tuple[tuple[str, tuple[str, ...]], ...] = ()     # (GPU proof scope.mode, extra argv) e.g. ("pilot", ("--pilot",))


@dataclass(frozen=True)
class Stage:
    id: str
    s: str
    label: str
    needs: tuple[str, ...]
    inputs: tuple[str, ...]
    gates: tuple[Step, ...]
    steps: tuple[Step, ...]
    receipts: tuple[str, ...]
    always: bool = False
    human: str | None = None
    human_gates: dict[str, dict[str, Any]] | None = None
    explain: dict[str, str] | None = None
    known_gap: str | None = None
    post: tuple[dict[str, Any], ...] = ()                          # read-only checks after the steps (also on reuse)

    @property
    def gpu_steps(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.gpu)

    @property
    def has_post(self) -> bool:
        return bool(self.human or self.post)


@dataclass(frozen=True)
class Dag:
    id: str
    path: Path
    sha256: str
    domains: tuple[str, ...]
    stages: tuple[Stage, ...]
    health_gate: dict[str, Any]
    notes: tuple[str, ...]
    human_proof: str = "legacy"        # "required": decisions need an issuer-signed proof (engine/run/proof.py)
    gpu_authorization: str = "flag"    # "proof": --approve-gpu is only a request; a scoped signed proof authorizes

    def stage(self, stage_id: str) -> Stage:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise Refused(f"unknown stage {stage_id!r}; stages: {', '.join(s.id for s in self.stages)}")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(stage.id for stage in self.stages)


def _strings(value: Any, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise Refused(f"run dag: {what} must be a list of non-empty strings")
    return tuple(value)


def _check_spec(raw: Any, where: str) -> dict[str, Any]:
    """A ``pre`` / ``post`` check: ``kind`` + ``next``, and either ``file`` + ``section`` (markers) or ``latest`` with
    ``list`` / ``equals`` (newest file); see engine/run/checks.py."""
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) and raw[k] for k in ("kind", "next")):
        raise Refused(f"run dag: {where} needs string kind and next")
    by_file = isinstance(raw.get("file"), str) and isinstance(raw.get("section"), str)
    by_latest = isinstance(raw.get("latest"), str) and (isinstance(raw.get("list"), str) or isinstance(raw.get("equals"), str))
    if not (by_file or by_latest):
        raise Refused(f"run dag: {where} needs file+section (markers) or latest+list|equals (newest file)")
    return dict(raw)


def _step(raw: Any, stage_id: str, kind: str) -> Step:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise Refused(f"run dag: stage {stage_id!r} {kind} entries need an id")
    where = f"stage {stage_id!r} {kind} {raw['id']!r}"
    argv = _strings(raw.get("argv"), f"{where} argv")
    if not argv:
        raise Refused(f"run dag: {where} has an empty argv")
    gpu = raw.get("gpu", False)
    if not isinstance(gpu, bool):
        raise Refused(f"run dag: {where} gpu must be true/false")
    human = raw.get("human")
    if human is not None and human not in HUMAN_GATES:
        raise Refused(f"run dag: {where} names unknown human gate {human!r}")
    write_once = raw.get("write_once")
    if write_once is not None and not (isinstance(write_once, str) and write_once):
        raise Refused(f"run dag: {where} write_once must be a path")
    extras = raw.get("argv_if_exists") or []
    if not isinstance(extras, list) or not all(isinstance(e, dict) and isinstance(e.get("file"), str) for e in extras):
        raise Refused(f"run dag: {where} argv_if_exists must be a list of {{file, argv}}")
    argv_if_exists = tuple((e["file"], _strings(e.get("argv"), f"{where} argv_if_exists argv")) for e in extras)
    modes = raw.get("argv_if_mode") or []
    if not isinstance(modes, list) or not all(isinstance(e, dict) and isinstance(e.get("mode"), str) for e in modes):
        raise Refused(f"run dag: {where} argv_if_mode must be a list of {{mode, argv}}")
    argv_if_mode = tuple((e["mode"], _strings(e.get("argv"), f"{where} argv_if_mode argv")) for e in modes)
    pre = _check_spec(raw["pre"], f"{where} pre") if raw.get("pre") is not None else None
    if kind == "gate" and (gpu or human or write_once or extras or pre):
        raise Refused(f"run dag: {where} may not be gpu, human or carry checks (gates never render)")
    return Step(id=raw["id"], argv=argv, gpu=gpu, per_shot=raw.get("per_shot"), human=human, note=raw.get("note"),
                write_once=write_once, argv_if_exists=argv_if_exists, pre=pre, argv_if_mode=argv_if_mode)


def _stage(raw: Any, seen: tuple[str, ...]) -> Stage:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise Refused("run dag: every stage needs a string id")
    sid = raw["id"]
    if sid in seen:
        raise Refused(f"run dag: duplicate stage id {sid!r}")
    needs = _strings(raw.get("needs", []), f"stage {sid!r} needs")
    for need in needs:
        if need not in seen:
            raise Refused(f"run dag: stage {sid!r} needs {need!r}, which is not an earlier stage")
    human = raw.get("human")
    if human is not None and human not in HUMAN_GATES:
        raise Refused(f"run dag: stage {sid!r} names unknown human gate {human!r}")
    steps = tuple(_step(s, sid, "step") for s in raw.get("steps", []))
    gates = tuple(_step(g, sid, "gate") for g in raw.get("gates", []))
    declared = raw.get("human_gates") or {}
    for name in [human] + [s.human for s in steps]:
        if name and name not in declared:
            raise Refused(f"run dag: stage {sid!r} uses human gate {name!r} without a human_gates.{name} block")
    explain = raw.get("explain")
    if explain is not None and (not isinstance(explain, dict) or not isinstance(explain.get("inputs_dir"), str)):
        raise Refused(f"run dag: stage {sid!r} explain needs inputs_dir")
    post_raw = raw.get("post") or []
    if not isinstance(post_raw, list):
        raise Refused(f"run dag: stage {sid!r} post must be a list of checks")
    post = tuple(_check_spec(p, f"stage {sid!r} post[{i}]") for i, p in enumerate(post_raw))
    return Stage(id=sid, s=str(raw.get("s", "")), label=str(raw.get("label", sid)), needs=needs,
                 inputs=_strings(raw.get("inputs", []), f"stage {sid!r} inputs"), gates=gates, steps=steps,
                 receipts=_strings(raw.get("receipts", []), f"stage {sid!r} receipts"),
                 always=bool(raw.get("always", False)), human=human, human_gates=declared or None,
                 explain=explain, known_gap=raw.get("known_gap"), post=post)


def recipe_for_domain(domain_id: str) -> Path:
    """The one recipe under ``recipes/run/`` whose ``domains`` lists ``domain_id`` (selection is data, not code)."""
    found = []
    for file in sorted(RECIPE_DIR.glob("*.json")):
        raw = read_json(file)
        if isinstance(raw, dict) and raw.get("schema") == SCHEMA and domain_id in (raw.get("domains") or []):
            found.append(file)
    if not found:
        raise Refused(f"no run recipe in {RECIPE_DIR.name}/ lists domain {domain_id!r}: a cross-domain run is refused "
                      "(nothing was read or run)")
    if len(found) > 1:
        raise Refused(f"more than one run recipe lists domain {domain_id!r}: {[f.name for f in found]}; "
                      "one domain, one recipe")
    return found[0]


def load_dag(path: str | Path | None = None, *, domain_id: str | None = None) -> Dag:
    """Load and validate a run recipe: ``path`` if given, else the recipe that lists ``domain_id``, else the default
    ``recipes/run/episode-dag-v001.json``."""
    file = Path(path) if path else recipe_for_domain(domain_id) if domain_id else DEFAULT_DAG
    if not file.is_file():
        raise Uncertain(f"run dag {file} does not exist")
    raw = read_json(file)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise Refused(f"{file.name}: schema must be {SCHEMA!r}")
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        raise Refused(f"{file.name}: id must be a string")
    domains = _strings(raw.get("domains"), "domains")
    if not domains:
        raise Refused(f"{file.name}: domains must name at least one domain")
    stages: list[Stage] = []
    for item in raw.get("stages") or []:
        stages.append(_stage(item, tuple(s.id for s in stages)))
    if not stages:
        raise Refused(f"{file.name}: stages is empty")
    health = raw.get("health_gate") or {}
    if not isinstance(health, dict):
        raise Refused(f"{file.name}: health_gate must be an object")
    human_proof, gpu_auth = raw.get("human_proof", "legacy"), raw.get("gpu_authorization", "flag")
    if human_proof not in ("legacy", "required") or gpu_auth not in ("flag", "proof"):
        raise Refused(f"{file.name}: human_proof is legacy|required and gpu_authorization is flag|proof")
    return Dag(id=raw["id"], path=file, sha256=sha256_file(file), domains=domains, stages=tuple(stages),
               health_gate=dict(health), notes=tuple(str(n) for n in raw.get("notes") or []),
               human_proof=human_proof, gpu_authorization=gpu_auth)


def require_domain(dag: Dag, domain_id: str) -> None:
    """A recipe is valid only for the domains it lists: two domains never share one recipe."""
    if domain_id not in dag.domains:
        raise Refused(f"run recipe {dag.id!r} is for domain(s) {list(dag.domains)}, not {domain_id!r}: "
                      "a cross-domain run is refused (nothing was read or run)")


def select_range(dag: Dag, from_id: str | None, to_id: str | None) -> tuple[tuple[Stage, str | None], ...]:
    """Every stage in order with ``None`` (in range) or the reason it is out of range."""
    ids = dag.ids
    start = ids.index(dag.stage(from_id).id) if from_id else 0
    end = ids.index(dag.stage(to_id).id) if to_id else len(ids) - 1
    if start > end:
        raise Refused(f"--from {from_id!r} comes after --to {to_id!r} (order: {', '.join(ids)})")
    rows = []
    for index, stage in enumerate(dag.stages):
        reason = (f"before --from {from_id}" if index < start else f"after --to {to_id}" if index > end else None)
        rows.append((stage, reason))
    return tuple(rows)
