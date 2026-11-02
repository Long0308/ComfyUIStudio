"""``plan_explain``: load two versions, compare, price, and return the one JSON document of ``jjv plan explain``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from . import annotate, report
from .costs import load_costs
from .graph import TARGETS
from .load import load_inputs
from .planner import explain

SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COSTS = SKILL_ROOT / "recipes" / "plan" / "costs-v001.json"
DEFAULT_POLICY = SKILL_ROOT / "recipes" / "plan" / "policy-v001.json"
POLICY_SCHEMA = "jjv/plan-policy/v1"


def load_policy(path: str | Path) -> dict:
    doc = read_json(Path(path))
    if doc.get("schema") != POLICY_SCHEMA:
        raise Refused(f"{path}: schema must be {POLICY_SCHEMA!r}")
    return doc


def _core_notes(old, new) -> list[str]:
    a, b = old.config_core_sha256, new.config_core_sha256
    if a and b and a != b:
        return [f"config_core_sha256 changed {a[:12]} -> {b[:12]}: the contract, domain, machine or episode block differs "
                "(mux and QA re-run; no segment or GPU node is touched by it)"]
    if bool(a) != bool(b):
        return ["config_core_sha256 is declared on one side only: the contract / domain change is not compared"]
    return []


def _episode_scope(episode: str | Path) -> tuple[Path, str, str]:
    """(episode root R, episode id, domain id) of ``--episode`` (episode.json, engine dir, root or slug)."""
    from ..config.loader import find_episode_file
    episode_file = find_episode_file(str(episode))
    doc = read_json(episode_file)
    ident, domain = doc.get("episode_id"), doc.get("domain")
    if not isinstance(ident, str) or not isinstance(domain, str):
        raise Refused(f"{episode_file}: episode_id and domain must be strings")
    return episode_file.parent.parent, ident, domain


def _feedback_file(root: Path, feedback: str | Path | None) -> Path | None:
    if feedback is None:
        return None
    base, target = root.resolve(), Path(feedback).resolve()
    if base != target and base not in target.parents:
        raise Refused(f"--feedback {feedback} must be inside the episode root {root}")
    return target


def plan_explain(old_dir: str | Path, new_dir: str | Path, *, costs_path: str | Path | None = None,
                 policy_path: str | Path | None = None, target: str = "review",
                 episode: str | Path | None = None, feedback: str | Path | None = None) -> dict[str, Any]:
    """Read-only.  Never runs, queues or posts anything; a changed GPU node is only *listed* with its price.

    ``episode`` (+ optional ``feedback``) only ANNOTATES the document with Studio notes (additive ``feedback`` key)."""
    if feedback is not None and episode is None:
        raise Refused("--feedback requires --episode")
    if target not in TARGETS:
        raise Refused(f"--target must be one of {TARGETS}")
    costs = load_costs(costs_path or DEFAULT_COSTS)
    policy = load_policy(policy_path or DEFAULT_POLICY)
    keys = policy["pins"]["keys"]
    old = load_inputs(old_dir, pin_keys=keys, label="old")
    new = load_inputs(new_dir, pin_keys=keys, label="new")
    doc = explain(old, new, costs, policy, target)
    summary = report.summarise(doc["rows"])
    notes = _core_notes(old, new)
    out = {
        "schema": doc["schema"], "ok": True, "target": target,
        "old": {"dir": old.root, "config_sha256": old.config_sha256, "config_core_sha256": old.config_core_sha256,
                "sources": old.sources},
        "new": {"dir": new.root, "config_sha256": new.config_sha256, "config_core_sha256": new.config_core_sha256,
                "sources": new.sources},
        "costs": {"path": costs.path, "sha256": costs.sha256, "version": costs.version},
        "policy": {"path": str(policy_path or DEFAULT_POLICY), "sha256": sha256_file(Path(policy_path or DEFAULT_POLICY))},
        "headline": report.headline(doc["rows"], summary), "summary": summary,
        "warnings": [*old.warnings, *new.warnings, *doc["notes"], *notes], "pins": doc["pins"], "rows": doc["rows"],
    }
    if episode is None:
        return out
    root, ident, domain = _episode_scope(episode)
    path = _feedback_file(root, feedback)
    warnings: list[str] = []
    old_ev, new_ev = annotate.verified_evidence(old, root, warnings), annotate.verified_evidence(new, root, warnings)
    snap = annotate.read_snapshot(old, new, root=root, episode=ident, domain=domain, feedback=path)
    segs = annotate.segment_shots(new, policy, doc["pins"]["new"], target)
    out["warnings"] = [*out["warnings"], *warnings]
    out["feedback"] = annotate.build_block(snap, doc["rows"], old_ev, new_ev, segs)
    return out
