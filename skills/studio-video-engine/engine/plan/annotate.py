"""M9b-4: annotate a plan document with Studio feedback notes (pure; advisory only).

Notes NEVER change a row, an action, a cost or a gate and never edit an input: this module reads the plan rows and the
read-only feedback snapshot and returns one additive ``feedback`` block.  Binding comes only from the explicit
``review_evidence`` of each version descriptor (receipt path + raw SHA), re-verified against the receipt bytes on disk.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from . import shape
from .feedback import FeedbackError, FeedbackNote, FeedbackSnapshot, feedback_path, read_feedback, receipt_snapshot
from .graph import build_graph
from .load import PlanInputs

SCHEMA = "jjv/plan-feedback/v1"
_SEGMENTS = ("composite.segment", "composite.master")


def verified_evidence(inputs: PlanInputs, root: Path, warnings: list[str]) -> list[dict]:
    """The version's evidence refs whose receipt bytes under R still hash to the recorded SHA."""
    out = []
    for item in inputs.review_evidence:
        try:
            ok = hashlib.sha256(receipt_snapshot(root, item["receipt"])).hexdigest() == item["receipt_sha256"]
        except FeedbackError:
            ok = False
        if ok:
            out.append(item)
        else:
            warnings.append(f"{inputs.label}: review_evidence {item['receipt']} does not match its recorded sha256; "
                            "notes on it stay unbound")
    return out


def _matches(note: FeedbackNote, evidence: list[dict]) -> bool:
    for e in evidence:
        if (e["receipt"] == note.receipt and e["receipt_sha256"] == note.receipt_sha256
                and e.get("stage") in (None, note.stage) and e.get("shot") in (None, note.shot)
                and e.get("artifact_sha256") in (None, note.artifact_sha256)):
            return True
    return False


def _binding(note: FeedbackNote, old_ev: list[dict], new_ev: list[dict]) -> str:
    if note.stale:
        return "stale"
    if _matches(note, new_ev):
        return "new"
    return "old" if _matches(note, old_ev) else "unbound"


def segment_shots(new: PlanInputs, policy: dict, pins: dict, target: str) -> dict[str, list[str]]:
    """segment node id -> shots drawn in it (from the NEW graph; no row is altered)."""
    nodes = build_graph(new, policy, pins, target)
    return {i: list(n.meta.get("shots", [])) for i, n in nodes.items() if n.kind in _SEGMENTS}


def _related(note: FeedbackNote, ids: set[str], segs: dict[str, list[str]]) -> list[str]:
    def seg(kind: str) -> list[str]:
        return sorted(i for i, shots in segs.items() if i.startswith(kind + "[") and (note.shot is None or note.shot in shots))

    def per_shot(kind: str) -> list[str]:
        return [f"{kind}[{note.shot}]"] if note.shot else sorted(i for i in ids if i.startswith(kind + "["))

    stage, found = note.stage, []
    if stage == "h3":
        found = per_shot("motion.h3")
    elif stage == "seedvr2":
        found = [*per_shot("upscale.chunks"), *per_shot("master.verify")]
    elif stage == "timing":
        found = ["timing.words", *seg("composite.segment")]
    elif stage == "audio":
        found = ["audio.mix", "mux", "mux.master"]
    elif stage in ("editorial", "review"):
        found = seg("composite.segment")
    elif stage == "master":
        found = [*seg("composite.master"), "mux.master"]
    elif stage == "delivery":
        found = ["film.downscale.2k"]
    return [n for n in found if n in ids]


def _annotation(note: FeedbackNote, binding: str, rows: dict[str, dict], segs: dict[str, list[str]]) -> dict[str, Any]:
    related = [] if binding == "stale" else _related(note, set(rows), segs)
    return {"line": note.line, "id": note.id, "stage": note.stage, "shot": note.shot, "verdict": note.verdict,
            "note": note.note, "author": note.author, "frame": note.frame, "receipt": note.receipt,
            "artifact_sha256": note.artifact_sha256, "binding": binding, "superseded": note.superseded,
            "related_nodes": related,
            "related_changed": [{"node": n, "status": rows[n]["status"], "action_code": rows[n]["action_code"]}
                                for n in related if rows[n]["status"] != "UNCHANGED"]}


def _refuse(error: FeedbackError, path: Path) -> Exception:
    from ..core.errors import Refused
    return Refused(f"feedback {path}: {error}")


def read_snapshot(old: PlanInputs, new: PlanInputs, *, root: Path, episode: str, domain: str,
                  feedback: Path | None) -> FeedbackSnapshot:
    shots = {s["id"] for side in (old, new) for s in shape.shots(side.config)}
    target = feedback_path(root) if feedback is None else feedback
    try:
        return read_feedback(feedback, root=root, episode=episode, domain=domain, shots=shots, on_stale="mark")
    except FeedbackError as error:
        raise _refuse(error, target) from None


def build_block(snap: FeedbackSnapshot, rows: list[dict], old_ev: list[dict], new_ev: list[dict],
                segs: dict[str, list[str]]) -> dict[str, Any]:
    by_row = {r["node"]: r for r in rows}
    notes = [_annotation(n, _binding(n, old_ev, new_ev), by_row, segs) for n in snap.notes]
    by_node: dict[str, list[str]] = {}
    for item in notes:
        for node in item["related_nodes"]:
            by_node.setdefault(node, []).append(item["id"])
    stale = [n["id"] for n in notes if n["binding"] == "stale"]
    return {"schema": SCHEMA, "path": snap.path, "sha256": snap.sha256, "bytes": snap.bytes,
            "line_count": snap.line_count, "present": snap.present, "notes": notes, "stale": stale,
            "unmapped": [n["id"] for n in notes if not n["related_nodes"] and n["binding"] != "stale"],
            "unresolved_changes": [i for i in snap.unresolved_changes if i not in stale],
            "by_node": by_node,
            "advisory": "notes annotate only: they never change which segments re-render, never edit inputs, never "
                        "authorise a GPU job"}
