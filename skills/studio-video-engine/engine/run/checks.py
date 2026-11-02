"""Declared, read-only checks of ``jjv run episode``: recipe keys ``pre`` (on a step), ``post`` (on a stage),
``write_once`` and ``argv_if_exists`` (on a step).  Nothing here runs a verb: every verdict is read from files on
disk, so the same check holds in ``--dry-run``, on a reused stage and after the steps ran.

Check documents (``kind`` and ``next`` are required; ``{latest}`` inside ``next`` becomes the newest file's name):

* ``{"latest": GLOB, "list": KEY}``    the newest file matching GLOB lists gaps under KEY (``unmet`` of an H3 shots
                                        publication, ``pending`` of a boundaries draft): non-empty is a named STOP;
* ``{"latest": GLOB, "equals": FILE}`` FILE (an episode file) must hold the same bytes as the newest match
                                        (``files.shots`` must be the published ``shots-h3-vNNN.json``);
* ``"unless": FILE``                    the check applies only while FILE is absent (a complete ``boundaries.json``);
* ``{"file": F, "section": S, "ignore": [...]}``  every ``{"missing": NAME}`` marker of block S of F (``delivery.json``)
                                        is a STOP naming the key; ``ignore`` lists keys the step passes on its own argv.

A verdict is ``pending`` while its file does not exist: a real run stops (the step before should have written it);
a dry run only records it, because that file is planned.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import EngineError
from ..core.io import read_json, sha256_file
from .context import RunContext, resolve, resolve_all
from .dag import Step
from .ledger import expand

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PATHISH = re.compile(r"[\\/]|\.(json|jsonl|mp4|wav|png)$")


@dataclass(frozen=True)
class Verdict:
    kind: str
    ok: bool
    detail: str
    next_step: str = ""
    pending: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ok": self.ok, "detail": self.detail, "next_step": self.next_step,
                "pending": self.pending}


def write_once_exists(step: Step, ctx: RunContext, stage_id: str) -> str | None:
    """The resolved ``write_once`` path when it is already on disk (the step is then skipped), else None."""
    if not step.write_once:
        return None
    path = resolve(step.write_once, ctx, stage_id)
    return path if Path(path).is_file() else None


def optional_argv(step: Step, ctx: RunContext, stage_id: str, extra: dict[str, str] | None = None) -> tuple[str, ...]:
    """The step's argv plus every ``argv_if_exists`` block whose file is on disk."""
    argv = resolve_all(step.argv, ctx, stage_id, extra)
    for file, more in step.argv_if_exists:
        if Path(resolve(file, ctx, stage_id, extra)).is_file():
            argv += resolve_all(more, ctx, stage_id, extra)
    return argv


def _document(path: Path) -> dict[str, Any] | None:
    try:
        doc = read_json(path)
    except EngineError:
        return None
    return doc if isinstance(doc, dict) else None


def _items(value: Any) -> list[str]:
    rows = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict):
            rows.append(": ".join(str(item[k]) for k in ("code", "shot", "why") if item.get(k)) or json.dumps(item)[:80])
        else:
            rows.append(str(item))
    return rows


def marker_names(node: Any, prefix: str) -> list[str]:
    """``key.path = NAME`` for every ``{"missing": NAME}`` marker under ``node``, in document order."""
    if isinstance(node, dict):
        if set(node) == {"missing"} and isinstance(node["missing"], str):
            return [f"{prefix} = {node['missing']}"]
        return [m for key, value in node.items() for m in marker_names(value, f"{prefix}.{key}")]
    if isinstance(node, list):
        return [m for index, value in enumerate(node) for m in marker_names(value, f"{prefix}[{index}]")]
    return []


def _markers(spec: dict[str, Any], ctx: RunContext, stage_id: str, next_step: str) -> Verdict:
    kind, section = spec["kind"], spec["section"]
    file = Path(resolve(spec["file"], ctx, stage_id))
    if not file.is_file():
        return Verdict(kind, False, f"{file.name} does not exist yet", next_step, pending=True)
    block = (_document(file) or {}).get(section)
    if not isinstance(block, dict):
        return Verdict(kind, False, f"{file.name} has no {section} block", next_step)
    ignore = set(spec.get("ignore") or [])
    found = [m for key, value in block.items() if key not in ignore for m in marker_names(value, f"{section}.{key}")]
    if found:
        return Verdict(kind, False, f"{file.name}: {len(found)} unresolved value(s): " + "; ".join(found[:6]), next_step)
    return Verdict(kind, True, f"{file.name} {section}: every value resolved")


def evaluate(spec: dict[str, Any], ctx: RunContext, stage_id: str) -> Verdict:
    """One declared check, read-only (document shapes: module docstring)."""
    kind = spec["kind"]
    if "section" in spec:
        return _markers(spec, ctx, stage_id, resolve(str(spec["next"]), ctx, stage_id))
    unless = spec.get("unless")
    if unless and Path(resolve(unless, ctx, stage_id)).is_file():
        return Verdict(kind, True, f"{Path(resolve(unless, ctx, stage_id)).name} exists: check not needed")
    pattern = resolve(spec["latest"], ctx, stage_id)
    files = expand(pattern)
    latest = files[-1] if files else None
    next_step = resolve(str(spec["next"]).replace("{latest}", latest.name if latest else "<latest>"), ctx, stage_id)
    if latest is None:
        return Verdict(kind, False, f"no file matches {pattern}", next_step, pending=True)
    if spec.get("list"):
        doc = _document(latest)
        if doc is None:
            return Verdict(kind, False, f"{latest.name} is not a JSON object", next_step)
        rows = _items(doc.get(spec["list"]))
        if rows:
            return Verdict(kind, False, f"{latest.name} lists {len(rows)} {spec['list']}: " + "; ".join(rows[:5]), next_step)
    if spec.get("equals"):
        declared = Path(resolve(spec["equals"], ctx, stage_id))
        if not declared.is_file() or sha256_file(declared) != sha256_file(latest):
            return Verdict(kind, False, f"{spec['equals']} ({declared.name}) does not hold the latest published "
                                        f"{latest.name}", next_step)
    return Verdict(kind, True, f"{latest.name} passes")


def _resolved(text: str, base: Path | None = None) -> str | None:
    try:
        return str((base / text if base else Path(text)).resolve())
    except (OSError, ValueError):
        return None


def evidence(stdouts: list[str], episode_root: Path) -> tuple[set[str], set[str]]:
    """``(paths, sha256s)`` the stage's step outputs name.  A receipt older than this run still counts when one of this
    run's verbs reported it (an identical versioned file it reused) or reported its sha256."""
    paths: set[str] = set()
    shas: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            if _HEX64.match(node):
                shas.add(node)
            elif _PATHISH.search(node):
                paths.update(p for p in (_resolved(node), _resolved(node, episode_root)) if p)

    for text in stdouts:
        try:
            walk(json.loads(text))
        except ValueError:
            continue
    return paths, shas
