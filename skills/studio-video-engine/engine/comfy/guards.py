"""Pre-dispatch guards (invariant I12): graph shape, sha binding, node-class policy.

* ``ClaudeNode`` and ``JJClaudeBridge`` are refused ALWAYS (cloud/chat call, non-deterministic);
  nothing overrides it.
* Classes in the domain's ``forbidden_node_classes`` are refused.
* A class from a custom-node pack (``python_module`` ``custom_nodes.<pack>...``) is refused unless
  the pack is on the domain's ``allowed_custom_nodes`` (no allowlist = every pack refused).
* Every class is checked against ``GET /object_info/<class>``: unknown to this ComfyUI
  (cannot verify) is refused; a partner/API node is refused when the domain forbids partner
  nodes.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Iterable

from ..core.errors import Refused
from .client import ComfyClient, ComfyError

# JJClaudeBridge is the authoring-only Claude bridge custom node (chat/gateway call, never rendered).
ALWAYS_REFUSED = frozenset({"claudenode", "jjclaudebridge"})


@dataclass(frozen=True)
class ClassPolicy:
    forbidden: frozenset[str]  # lowercase class names
    forbid_partner: bool = True
    allowed_custom_nodes: frozenset[str] = frozenset()  # lowercase pack names
    banned_models: frozenset[str] = frozenset()  # domain model_policy.banned_models (empty = no policy)

    @classmethod
    def from_domain(cls, domain: dict) -> "ClassPolicy":
        policy = domain.get("model_policy")
        banned = policy.get("banned_models", []) if isinstance(policy, dict) and policy.get("enabled") is True else []
        return cls(frozenset(n.lower() for n in domain["forbidden_node_classes"]),
                   bool(domain["forbid_partner_nodes"]),
                   frozenset(n.lower() for n in domain.get("allowed_custom_nodes", [])),
                   frozenset(banned))


def graph_class_types(graph: object) -> list[str]:
    """Validate API-format graph shape; return its distinct class_types."""
    if not isinstance(graph, dict) or not graph:
        raise Refused("graph is not a non-empty API-format JSON object")
    if "nodes" in graph and "links" in graph:
        raise Refused("graph looks like a UI export; API-format JSON is required")
    classes: set[str] = set()
    for node_id, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise Refused(f"node {node_id!r} has no class_type; not API format")
        classes.add(node["class_type"])
    return sorted(classes)


def require_sha(actual: str, expected: str | None, label: str) -> None:
    if expected is not None and actual != expected.lower():
        raise Refused(f"{label} sha256 mismatch: expected {expected.lower()}, got {actual}")


def static_refusals(classes: Iterable[str], policy: ClassPolicy) -> list[str]:
    """Class-name refusals that need no network (safe in a dry run)."""
    return [f"{name}: node class is forbidden by policy"
            for name in classes if name.lower() in policy.forbidden | ALWAYS_REFUSED]


def _is_partner(entry: dict[str, Any]) -> bool:
    module, category = str(entry.get("python_module", "")), str(entry.get("category", ""))
    return bool(entry.get("api_node")) or "comfy_api_nodes" in module or category.lower().startswith("api node")


def custom_pack(entry: dict[str, Any]) -> str | None:
    """The custom-node pack a class comes from (``custom_nodes.<pack>[...]``), else None."""
    module = str(entry.get("python_module", ""))
    parts = module.replace("/", ".").replace("\\", ".").split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "custom_nodes" else None


def object_info_refusals(client: ComfyClient, classes: Iterable[str], policy: ClassPolicy,
                         cache: dict[str, str | None] | None = None) -> list[str]:
    """Network refusals: unknown classes always, partner/API classes when the policy forbids."""
    cache = {} if cache is None else cache
    reasons: list[str] = []
    for name in classes:
        if name not in cache:
            try:
                info = client.get("/object_info/" + urllib.parse.quote(name, safe=""))
            except ComfyError as error:
                raise Refused(f"cannot verify node class {name} via /object_info: {error}") from error
            entry = info.get(name) if isinstance(info, dict) else None
            if not isinstance(entry, dict):
                cache[name] = f"{name}: unknown to this ComfyUI (cannot verify)"
            elif _is_partner(entry):
                cache[name] = (f"{name}: partner/API node (module={entry.get('python_module')!r}, "
                               f"category={entry.get('category')!r})")
            elif (pack := custom_pack(entry)) is not None and pack.lower() not in policy.allowed_custom_nodes:
                cache[name] = (f"{name}: custom node pack {pack!r} is not on the domain allowlist "
                               "(allowed_custom_nodes)")
            else:
                cache[name] = None
        verdict = cache[name]
        if verdict and ("partner/API node" not in verdict or policy.forbid_partner):
            reasons.append(verdict)
    return reasons


def check_graph(client: ComfyClient | None, graph: object, policy: ClassPolicy, *,
                cache: dict[str, str | None] | None = None) -> list[str]:
    """Raise ``Refused`` unless the graph passes.  ``client=None`` runs the static checks only
    (used by dry runs, which must not touch the network) and returns the classes checked."""
    classes = graph_class_types(graph)
    problems = static_refusals(classes, policy)
    if problems:
        raise Refused("; ".join(problems))
    if policy.banned_models:  # domain model policy: a banned model never loads (guard 3)
        from ..policy import model_policy
        model_policy.check_anchor_graph({"model_policy": {"enabled": True, "banned_models": sorted(policy.banned_models)}},
                                        graph, where="graph validator")
    if client is not None:
        problems = object_info_refusals(client, classes, policy, cache)
        if problems:
            raise Refused("; ".join(problems))
    return classes
