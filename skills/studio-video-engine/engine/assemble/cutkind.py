"""Preview / final cut kind for the assemble verb (only where the domain declares ``final_gate``).

A FINAL cut needs every clip's media sha256 bound to a user-approval receipt (``engine.policy.final_gate``);
a PREVIEW cut is always allowed but is labelled: ``preview-`` tag prefix and ``cut_kind: preview`` in the receipt.
A domain without the gate is unchanged: no relabel, no extra receipt keys.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..core.errors import Refused
from ..policy import final_gate

CUT_KINDS = ("preview", "final")


def effective_tag(gate: Mapping[str, Any] | None, cut_kind: str, tag: str) -> str:
    if gate is None:
        return tag
    if cut_kind not in CUT_KINDS:
        raise Refused(f"ASSEMBLE_USAGE: cut kind must be one of {CUT_KINDS}, got {cut_kind!r}")
    return tag if cut_kind == "final" or tag.startswith("preview") else f"preview-{tag}"


def gate_cut(gate: Mapping[str, Any] | None, validation: Mapping[str, Any], cut_kind: str,
             roots: Iterable[Any]) -> dict | None:
    """``None`` when the domain has no gate; else ``{"cut_kind", "approvals"}`` or ``Refused`` for an unapproved final."""
    if gate is None:
        return None
    if cut_kind == "preview":
        return {"cut_kind": "preview", "approvals": []}
    if cut_kind != "final":
        raise Refused(f"ASSEMBLE_USAGE: cut kind must be one of {CUT_KINDS}, got {cut_kind!r}")
    kinds = gate.get("shot_kinds") or ["clip"]
    shots = [(str(row["id"]), [row.get("sha256"), row.get("approved_sha256")])
             for row in validation["segments"] if row.get("kind") in kinds]
    rows = final_gate.check_shots({"final_gate": gate}, shots, list(roots), verb="edit assemble")
    return {"cut_kind": "final", "approvals": rows}
