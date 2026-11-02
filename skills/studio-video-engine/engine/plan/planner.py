"""Compare two versions: status per node, propagation to dependants, action and priced estimate (T-E45 spec 2.2 / 2.3).

Rules, all from the spec:

* a node is CHANGED when its ``node_key`` differs from the old version's, NEW when it did not exist;
* a node whose upstream changed is CHANGED too (``motion.h3[shot]`` -> the segments that draw the shot); a
  *materialised* node (``timing.words``, ``editorial.build``: the new config already carries its output) does not
  propagate -- its effect is visible in the dependants' own slices, so a changed provenance sha with identical words
  leaves every segment alone (content addressing, spec 2.3 step 3);
* a GPU node is NEVER scheduled: CHANGED means "GPU job -- needs approval" with its price, unless a receipt that names
  the new core sha is on disk (``gpu_cores.<shot>.core_receipt``), in which case only the re-composite is left;
* a node whose input is named but not on disk (a receipt's mix plan after a drive move) is UNCERTAIN, not CHANGED: it
  cannot be compared, nothing is priced, and a dependant whose only difference is that part is UNCERTAIN too.
"""

from __future__ import annotations

from typing import Any, Mapping

from .costs import ZERO, Costs, Estimate
from .graph import build_graph
from .load import PlanInputs
from .model import Change, Node, diff_parts, group_counts, show, why_text

SCHEMA = "jjv/plan-explain/v1"
UNCERTAIN = "UNCERTAIN"           # row status: an input is named but not readable, so old vs new cannot be compared
NOT_MEASURED = Estimate(None, "n/a")
GPU_KINDS = ("motion.h3", "upscale.chunks")
SEGMENT_KINDS = ("composite.segment", "composite.master")
LEAF_CAP = 40
PINNED_KINDS = ("composite.segment", "composite.master")
_LAYERS = (("captions", lambda p: ".words[" in p or p.endswith(".words")), ("icons", lambda p: p.startswith(("icon:", "file:icon"))),
           ("transition", lambda p: p.startswith("transition:")), ("picture", lambda p: p.startswith("file:picture")),
           ("cards", lambda p: p.startswith(("card:", "cards."))), ("ending", lambda p: p.startswith("ending.")),
           ("cut-points", lambda p: p == "range" or p.startswith("range[")), ("pins", lambda p: p.startswith("pin.")),
           ("assets", lambda p: p.startswith("file:")), ("global", lambda p: p.startswith("global")))


def _layers(changes: list[Change]) -> list[str]:
    found: list[str] = []
    for c in changes:
        path = c.path.lstrip("+-")
        name = next((n for n, test in _LAYERS if test(path)), "shot" if path.startswith("shot:") else "other")
        if name not in found:
            found.append(name)
    return found


def _common_pins(old: PlanInputs, new: PlanInputs) -> tuple[dict, dict, list[str]]:
    both = sorted(set(old.pins) & set(new.pins))
    notes = [f"pin {k} is declared on one side only: not compared" for k in sorted(set(old.pins) ^ set(new.pins))]
    return {k: old.pins[k] for k in both}, {k: new.pins[k] for k in both}, notes


def _price(costs: Costs, node: Node) -> Estimate:
    meta = node.meta
    if node.kind == "composite.segment":
        return costs.price([("composite.review.frame", meta["frames"]), ("composite.review.call", 1)])
    if node.kind == "composite.master":
        rate = "composite.master.shot_frame" if meta["shot_drawn"] else "composite.master.vector_frame"
        return costs.price([(rate, meta["frames"])])
    table = {"motion.h3": ("motion.h3.native_frame", meta.get("native_frames")),
             "upscale.chunks": ("upscale.chunks.native_frame", meta.get("native_frames")),
             "master.verify": ("master.verify.shot", 1), "mux": ("mux.review", 1), "mux.master": ("mux.master", 1),
             "film.downscale.2k": ("film.downscale.2k", 1), "audio.mix": ("audio.mix", 1), "qa.av": ("qa.av", 1)}
    name, units = table[node.kind]
    return costs.price([(name, units)])


def _leaf(c: Change) -> str:
    return c.path if c.old is None and c.new is None else f"{c.path} {show(c.old)} -> {show(c.new)}"


def _segment_split(costs: Costs, node: Node) -> tuple[float | None, float]:
    """(frames x s/frame, fixed seconds per child render) of one segment: lets the summary price the bundle-sharing choice."""
    if node.kind == "composite.master":
        rate = "composite.master.shot_frame" if node.meta["shot_drawn"] else "composite.master.vector_frame"
        return costs.price([(rate, node.meta["frames"])]).seconds, 0.0
    return (costs.price([("composite.review.frame", node.meta["frames"])]).seconds,
            costs.price([("composite.review.call", 1)]).seconds or 0.0)


def _classify(nodes_new: Mapping[str, Node], nodes_old: Mapping[str, Node], new: PlanInputs,
              pin_changes: list[Change]) -> dict[str, dict]:
    """status / changes / propagation per node of the NEW graph (topological order)."""
    info: dict[str, dict] = {}
    for node_id, node in nodes_new.items():
        old = nodes_old.get(node_id)
        unresolved = [*node.meta.get("unresolved", ()), *(old.meta.get("unresolved", ()) if old else ())]
        uncertain_up = [d for d in node.deps if info[d]["status"] == UNCERTAIN]
        changes = [] if old is None or old.key == node.key else diff_parts(old.parts, node.parts)
        if uncertain_up:                         # that part is not comparable, so its difference is not a change
            changes = [c for c in changes if c.path.lstrip("+-") not in uncertain_up]
        if old is not None and old.key != node.key and not changes and node.kind in PINNED_KINDS:
            changes = list(pin_changes)          # same slice, other key: the pins (compositor, remotion, gl) moved
        if old is None:
            status = "NEW"
        elif unresolved:
            status, changes = UNCERTAIN, []      # one side could not read the input: nothing to diff
        elif changes or (old.key != node.key and not uncertain_up):
            status = "CHANGED"
        else:
            status = "UNCHANGED"
        upstream = [d for d in node.deps if info[d]["propagates"]]
        if status == "UNCHANGED" and upstream:
            status = "CHANGED"
        if status == "UNCHANGED" and uncertain_up:
            status = UNCERTAIN
        roots: dict[str, list[str]] = {node_id: unresolved} if unresolved else {}
        for dep in uncertain_up:
            roots.update(info[dep]["uncertain_roots"])
        shot = node.meta.get("shot")
        verified = bool(shot and node.kind == "motion.h3" and (new.core_receipts.get(shot) or {}).get("verified"))
        output_same = old is not None and old.output == node.output
        propagates = status in ("NEW", "CHANGED") and not node.materialised
        info[node_id] = {"node": node, "old": old, "status": status, "changes": changes, "upstream": upstream,
                         "verified": verified, "output_same": output_same, "propagates": propagates,
                         "uncertain_roots": roots}
    return info


def _uncertain_reasons(info: dict) -> list[str]:
    """Why a row cannot be compared: its own unreadable inputs, else the root node(s) upstream that cannot be."""
    node_id = info["node"].id
    return [reason for root, reasons in info["uncertain_roots"].items() if root == node_id for reason in reasons] or [
        f"upstream {root} not comparable: {'; '.join(reasons)}"
        for root, reasons in info["uncertain_roots"].items() if root != node_id]


def _action(info: dict, all_info: dict, costs: Costs, audio_changed: bool, picture_changed: bool) -> tuple[str, str, Estimate, bool]:
    node, status = info["node"], info["status"]
    if status == "UNCHANGED":
        return "reuse", "reuse", ZERO, False
    if status == UNCERTAIN:
        return ("not_comparable", "cannot compare: " + "; ".join(_uncertain_reasons(info))
                + " -- put the input back (or name it in plan-inputs.json) and re-run plan explain", NOT_MEASURED, False)
    kind = node.kind
    if kind == "timing.words":
        text = ("key changed but the words are identical: nothing downstream moves" if info["output_same"]
                else "materialised: the new config already carries the new words (no run)")
        return "materialised", text, ZERO, False
    if kind == "editorial.build":
        return "materialised", "materialised: the new config / events already carry the new blocks (no run)", ZERO, False
    if kind in GPU_KINDS:
        if info["verified"]:
            return "core_present", "core already produced (receipt names the new core sha): GPU job not needed", ZERO, False
        return ("gpu_job_needs_approval", "GPU job -- NEVER AUTO, needs approval (--accept-gpu-seconds)",
                _price(costs, node), True)
    if kind in SEGMENT_KINDS:
        layers = ",".join(_layers(info["changes"]) or ["upstream"])
        pending = [u for u in info["upstream"] if all_info[u]["node"].kind in GPU_KINDS and not all_info[u]["verified"]]
        suffix = f" after GPU job {', '.join(pending)}" if pending else ""
        label = "re-composite 4K segment" if kind == "composite.master" else "re-composite segment"
        return "recomposite", f"{label} [{layers}]{suffix}", _price(costs, node), False
    if kind == "audio.mix":
        return "rebuild_mix", "rebuild the mix (CPU), then remux audio only; no picture is touched", _price(costs, node), False
    if kind in ("mux", "mux.master"):
        if audio_changed and not picture_changed:
            return "remux_audio_only", "remux audio only: picture segments reused, video stream-copy", _price(costs, node), False
        if picture_changed and not audio_changed:
            return "rejoin", "re-join changed segments by stream copy; audio mix unchanged", _price(costs, node), False
        return "rejoin_and_remux", "re-join segments and remux the new audio", _price(costs, node), False
    if kind == "master.verify":
        return "reverify", "rebuild master config + re-hash this shot's core", _price(costs, node), False
    if kind == "film.downscale.2k":
        return "downscale", "re-run the 2K lanczos downscale of the new master", _price(costs, node), False
    return "rerun_verifier", "re-run the verifier on the new film", _price(costs, node), False


def _why(info: dict, all_info: dict) -> tuple[list[str], int]:
    node, changes = info["node"], info["changes"]
    if info["status"] == UNCERTAIN:
        return _uncertain_reasons(info), 0
    if node.kind in ("mux", "mux.master"):
        changed = sum(1 for d in node.deps if all_info[d]["status"] != "UNCHANGED" and all_info[d]["node"].kind in SEGMENT_KINDS)
        audio = (all_info.get("audio.mix") or {}).get("status")
        lines = ([f"{changed} segment(s) changed"] if changed else []) + (
            ["audio.mix changed"] if audio in ("CHANGED", "NEW") else ["audio.mix not comparable"] if audio == UNCERTAIN else [])
        lines += ["config core changed (contract / domain / machine / episode)"] * any(
            c.path.lstrip("+-") == "global.config_core_sha256" for c in changes)
        return lines, len(lines)
    if node.kind == "editorial.build":
        return [f"{block}: {n} leaves" for block, n in group_counts(changes).items()], len(changes)
    lines = [] if node.kind in ("qa.av", "film.downscale.2k") else why_text(changes)
    lines += [f"upstream {u} changed" for u in info["upstream"][:3]]
    if len(info["upstream"]) > 3:
        lines.append(f"(+{len(info['upstream']) - 3} more upstream)")
    return lines or ["input changed upstream"], len(changes)


def _row(item: dict, all_info: dict, costs: Costs, audio_changed: bool, picture_changed: bool) -> dict:
    node = item["node"]
    code, action, est, approval = _action(item, all_info, costs, audio_changed, picture_changed)
    why, leaves = ([], 0) if item["status"] == "UNCHANGED" else _why(item, all_info)
    row = {"node": node.id, "kind": node.kind, "device": node.device, "status": item["status"], "why": why,
           "changed_leaves": leaves, "action_code": code, "action": action, "est_seconds": est.seconds,
           "est_basis": est.basis, "cost_lines": list(est.lines), "requires_approval": approval,
           "key_old": item["old"].key[:12] if item["old"] else None, "key_new": node.key[:12]}
    row["leaves"] = [_leaf(c) for c in item["changes"][:LEAF_CAP]]
    if node.kind in SEGMENT_KINDS:
        frame_s, call_s = _segment_split(costs, node)
        row.update({"range": [node.meta["start"], node.meta["end_exclusive"]], "frames": node.meta["frames"],
                    "segment_kind": node.meta["seg_kind"], "layers": _layers(item["changes"]),
                    "frame_seconds": frame_s, "call_seconds": call_s})
    return row


def explain(old: PlanInputs, new: PlanInputs, costs: Costs, policy: Mapping[str, Any], target: str = "review") -> dict:
    """The plan document (``jjv/plan-explain/v1``): every node of the new version with status, why, action, estimate."""
    pins_old, pins_new, notes = _common_pins(old, new)
    nodes_old = build_graph(old, policy, pins_old, target)
    nodes_new = build_graph(new, policy, pins_new, target)
    pin_changes = [Change(f"pin.{k}", pins_old[k], pins_new[k]) for k in pins_old if pins_old[k] != pins_new[k]]
    info = _classify(nodes_new, nodes_old, new, pin_changes)
    audio_changed = info["audio.mix"]["status"] != "UNCHANGED"
    removed = [i for i in nodes_old if i not in nodes_new and nodes_old[i].kind in SEGMENT_KINDS]
    picture_changed = bool(removed) or any(i["status"] != "UNCHANGED" for i in info.values()
                                           if i["node"].kind in SEGMENT_KINDS)
    rows = [_row(item, info, costs, audio_changed, picture_changed) for item in info.values()]
    rows += [{"node": i, "kind": nodes_old[i].kind, "device": "cpu", "status": "REMOVED", "why": ["cut points moved"],
              "changed_leaves": 0, "action_code": "drop", "action": "segment no longer exists in the new cut list",
              "est_seconds": 0.0, "est_basis": "n/a", "cost_lines": [], "requires_approval": False, "leaves": [],
              "range": [nodes_old[i].meta["start"], nodes_old[i].meta["end_exclusive"]], "frames": 0,
              "segment_kind": nodes_old[i].meta["seg_kind"], "layers": ["cut-points"], "frame_seconds": 0.0,
              "call_seconds": 0.0, "key_old": nodes_old[i].key[:12], "key_new": None} for i in removed]
    return {"schema": SCHEMA, "target": target, "rows": rows, "notes": notes, "pins": {"old": pins_old, "new": pins_new}}
