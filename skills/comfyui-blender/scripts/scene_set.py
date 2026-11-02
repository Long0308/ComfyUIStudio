"""Shared scene SET: ground zones, fences and static props that several shot briefs reference.

A shot brief names its set with `"set": "<path.json>"` or `"set": "<set_id>"`. The set file is a
`scene_set` document (see `$defs/scene_set` in scene-layout.schema.json): no actors, no animals, no
camera, no cast. `resolve_set` merges it into the shot so static props cannot drift between shots.
A shot may add its own zones/fences/props (moving props, per-shot extras) but must not redefine a
set item differently: that is reported as SET_MISMATCH and the shot's copy is dropped.

Pure standard library; no bpy.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scene_common import SCHEMA_PATH, Finding, schema_errors

SET_KIND = "scene_set"


@dataclass(frozen=True)
class SetResolution:
    brief: dict[str, Any]
    findings: tuple[Finding, ...]
    set_id: str | None
    set_prop_ids: frozenset[str]


def _looks_like_path(ref: str) -> bool:
    return "/" in ref or "\\" in ref or ref.lower().endswith(".json")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _locate(ref: str, base: Path) -> tuple[Path | None, str, str]:
    """Return (path, error_code, message); path is None on failure."""
    if _looks_like_path(ref):
        raw = Path(ref)
        for candidate in ([raw] if raw.is_absolute() else [base / raw, Path.cwd() / raw]):
            if candidate.is_file():
                return candidate, "", ""
        return None, "SET_NOT_FOUND", f"set file '{ref}' not found (looked relative to {base})"
    hits: list[Path] = []
    for candidate in sorted(base.glob("*.json")):
        try:
            doc = _read(candidate)
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("kind") == SET_KIND and doc.get("set_id") == ref:
            hits.append(candidate)
    if not hits:
        return None, "SET_NOT_FOUND", f"no scene_set with set_id '{ref}' in {base}"
    if len(hits) > 1:
        return None, "SET_AMBIGUOUS", f"set_id '{ref}' is declared by {', '.join(h.name for h in hits)}"
    return hits[0], "", ""


def _diff(a: dict[str, Any], b: dict[str, Any]) -> str:
    keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return "; ".join(f"{k} {json.dumps(b.get(k))} != set's {json.dumps(a.get(k))}" for k in keys)


def _merge(label: str, set_items: list[dict[str, Any]], shot_items: list[dict[str, Any]], set_id: str, add) -> list[dict[str, Any]]:
    merged = [copy.deepcopy(i) for i in set_items]
    by_id = {i["id"]: i for i in set_items}
    for index, item in enumerate(shot_items):
        base = by_id.get(item["id"])
        if base is None:
            merged.append(copy.deepcopy(item))
        elif item != base:
            add("error", "SET_MISMATCH", f"{label}[{index}]({item['id']})",
                f"{label} item '{item['id']}' is redefined differently from set '{set_id}': {_diff(base, item)}")
    return merged


def resolve_set(brief: dict[str, Any], base_dir: Path | None = None) -> SetResolution:
    """Merge the brief's `set` (if any) into a copy of the brief. Never raises on bad input: see findings."""
    findings: list[Finding] = []

    def add(level: str, code: str, where: str, message: str) -> None:
        findings.append(Finding(level, code, where, message))

    out = copy.deepcopy(brief)
    ref = brief.get("set")
    if ref is None:
        if "ground" not in brief:
            add("error", "GROUND_MISSING", "ground", "a brief needs ground.zones, or a `set` that provides them")
        return SetResolution(out, tuple(findings), None, frozenset())
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    path, code, message = _locate(ref, base)
    if path is None:
        add("error", code, "set", message)
        return SetResolution(out, tuple(findings), None, frozenset())
    try:
        doc = _read(path)
    except (OSError, ValueError) as exc:
        add("error", "SET_INVALID", "set", f"{path.name}: {type(exc).__name__}: {exc}")
        return SetResolution(out, tuple(findings), None, frozenset())
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    problems = schema_errors(doc, {"$ref": "#/$defs/scene_set"}, schema, "set")
    for problem in problems:
        add("error", "SET_INVALID", "set", f"{path.name}: {problem}")
    if problems:
        return SetResolution(out, tuple(findings), None, frozenset())
    set_id = doc["set_id"]
    if doc["domain"] != brief.get("domain"):
        add("error", "SET_DOMAIN", "set", f"set '{set_id}' is domain {doc['domain']} but the brief is {brief.get('domain')}: sets are never shared across domains")
        return SetResolution(out, tuple(findings), set_id, frozenset())
    shot_zones = brief.get("ground", {}).get("zones", [])
    out["ground"] = {"zones": _merge("ground.zones", doc["ground"]["zones"], shot_zones, set_id, add)}
    for section in ("fences", "props"):
        merged = _merge(section, doc.get(section, []), brief.get(section, []), set_id, add)
        if merged:
            out[section] = merged
    return SetResolution(out, tuple(findings), set_id, frozenset(p["id"] for p in doc.get("props", [])))
