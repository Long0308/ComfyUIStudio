"""Read an approved H3 preparation for GUI export; never prepare or submit it.

The H3 engine remains the approval authority.  ``load_prepared`` rechecks its
qualification, media hashes, current pack approvals and listen approval.  GUI
export additionally disallows the engine's explicitly permitted pilot/legacy
paths: this verb promises real, approved inputs, not a pilot placeholder.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import canonical_sha256, sha256_file
from ..h3 import pack_refs
from ..h3 import prepare as h3_prepare
from ..layout.context import Context
from ..video import anchor_verify
from ..voice import approval as voice_approval
from ..voice import receipts as voice_receipts


def _ref(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _absolute(path: str, root: Path) -> Path:
    given = Path(path)
    return (given if given.is_absolute() else Path(root) / given).resolve()


def _bindings(receipt: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    bound: set[tuple[str, str]] = set()
    result = []
    media = [("anchor", receipt["anchor"]), ("wav", receipt["wav"])]
    media += [(item.get("role", "reference"), item) for item in receipt.get("refs") or []]
    for role, item in media:
        ports = item.get("ports")
        input_name = item.get("input_name")
        if not isinstance(input_name, str) or not input_name or not isinstance(ports, list) or not ports:
            raise Refused(f"GUI_MEDIA_BINDING: {role} needs prepared input_name and ports")
        normalized = []
        for port in ports:
            if not isinstance(port, (list, tuple)) or len(port) != 2 or not isinstance(port[1], str):
                raise Refused(f"GUI_MEDIA_BINDING: malformed {role} port {port!r}")
            key = (str(port[0]), port[1])
            if key in bound:
                raise Refused(f"GUI_MEDIA_BINDING: duplicate media port {key!r}")
            node = graph.get(key[0]) or {}
            expected = ("LoadAudio", "audio") if role == "wav" else ("LoadImage", "image")
            if (node.get("class_type"), key[1]) != expected:
                raise Refused(f"GUI_MEDIA_BINDING: {role} port {key!r} is not {expected!r}")
            if (node.get("inputs") or {}).get(key[1]) != input_name:
                raise Refused(f"GUI_MEDIA_BINDING: prepared graph and {role} receipt disagree at {key!r}")
            bound.add(key)
            normalized.append(key)
        result.append({"path": str(Path(item["path"]).resolve()), "sha256": item["sha256"],
                       "ports": normalized, "role": role, "input_name": input_name})
    loaders = {(str(node_id), "audio" if node["class_type"] == "LoadAudio" else "image")
               for node_id, node in graph.items() if node.get("class_type") in ("LoadImage", "LoadAudio")}
    if bound != loaders:
        raise Refused("GUI_MEDIA_BINDING: every prepared image/audio loader must have an approved binding")
    return result


def load_video(ctx: Context, prepared_dir: Path, shot: str, tier: str = "preview") -> dict[str, Any]:
    """Return graph, explicit loader bindings and receipt hashes after existing gates.

    ``prepared_dir`` is the parent containing ``<shot>/preparation.json`` and
    ``graph.api.json``, as accepted by ``jjv h3 submit --out``.  H3 produces the
    native preview only; other tiers use the existing promotion/upscale route
    and are refused here rather than mislabelling the native graph.
    """
    if tier != "preview":
        raise Refused("GUI_TIER_REFUSED: H3 export supports preview only; higher tiers require their approved upscale route")
    shot = h3_prepare.safe(shot)
    folder = Path(prepared_dir) / shot
    preparation_path = folder / h3_prepare.PREPARATION_FILE
    if not preparation_path.is_file():
        raise Refused(f"GUI_PREPARATION: missing {preparation_path}; run jjv h3 prepare first")
    before = _ref(preparation_path)
    loaded = h3_prepare.load_prepared(ctx, Path(prepared_dir), shots=[shot])
    if len(loaded) != 1:
        raise Refused("GUI_PREPARATION: need exactly one prepared shot")
    loaded_folder, receipt, graph = loaded[0]
    if Path(loaded_folder).resolve() != folder.resolve() or (
            receipt.get("schema"), receipt.get("episode_id"), receipt.get("domain"), receipt.get("shot"),
            receipt.get("status")) != (
                h3_prepare.SCHEMA, ctx.episode_id, ctx.domain_id, shot, "PREPARED_NOT_SUBMITTED"):
        raise Refused("GUI_PREPARATION: schema, episode, domain, shot or preparation status mismatch")
    recorded_pack = receipt.get("anchor_pack")
    if not isinstance(recorded_pack, dict) or receipt.get("faces"):
        raise Refused("ANCHOR_PACK_MISSING: GUI export requires the approved shot anchor pack; legacy cast paths are refused")
    if (receipt.get("storyboard") or {}).get("pilot") is True:
        raise Refused("STORYBOARD_PENDING: GUI export refuses pilot substitute anchors")
    pack_path = _absolute(recorded_pack["path"], ctx.root)
    pack = anchor_verify.load_pack(ctx, pack_path)
    if pack.get("shot") != shot:
        raise Refused("ANCHOR_PACK_FOREIGN: pack belongs to another shot")
    # Deliberately use the same gate as H3 with pilot exemption switched OFF.
    pack_refs._require_pack_approvals(ctx, pack, allow_pending_storyboard=False)
    wanted = {(item["slot"], item["sha256"], item["role"])
              for item in (pack.get("ref_slots") or {}).get("bound") or []}
    refs = receipt.get("refs") or []
    actual = {(item.get("slot"), item.get("sha256"), item.get("role")) for item in refs}
    if actual != wanted or len(actual) != len(refs):
        raise Refused("ANCHOR_PACK_REF_MISMATCH: preparation must bind every approved pack ref exactly once")
    voice_dir = receipt.get("voice_dir")
    if not isinstance(voice_dir, str) or not voice_dir:
        raise Refused("E_LISTEN_APPROVAL: GUI export requires current listen-approved voice evidence; legacy proof is refused")
    voice_dir = _absolute(voice_dir, ctx.root)
    proof = receipt.get("voice_approval") or {}
    request_id = proof.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise Refused("E_LISTEN_APPROVAL: preparation has no voice request approval")
    approval_path = voice_approval.approval_path(voice_dir, request_id)
    approval_sha = (proof.get("approval") or {}).get("record_sha256")
    require_hash(approval_path, approval_sha, "voice approval record")
    graph_path = folder / h3_prepare.GRAPH_FILE
    source_graph_sha = canonical_sha256(graph, mode="ascii")
    if source_graph_sha != receipt.get("graph_sha256"):
        raise Refused("GUI_GRAPH_DRIFT: canonical graph does not match preparation receipt")
    bindings = _bindings(receipt, graph)
    receipts = {"preparation": before, "prepared_graph": _ref(graph_path), "anchor_pack": _ref(pack_path),
                "voice_approval": _ref(approval_path),
                "voice_plan": _ref(voice_dir / voice_receipts.PLAN_FILE),
                "voice_bindings": _ref(voice_dir / voice_receipts.BINDINGS_FILE),
                "voice_finalize": _ref(voice_dir / voice_receipts.FINALIZE_FILE)}
    template = receipt.get("template")
    if not isinstance(template, dict):
        raise Refused("GUI_PREPARATION: template provenance is missing")
    template_path = _absolute(template["path"], ctx.root)
    require_hash(template_path, template["sha256"], "prepared H3 template")
    receipts["template"] = _ref(template_path)
    require_hash(preparation_path, before["sha256"], "preparation during GUI export")
    require_hash(pack_path, recorded_pack["sha256"], "anchor pack during GUI export")
    return {"graph": graph, "graph_path": str(graph_path.resolve()), "bindings": bindings,
            "receipts": receipts, "shot": shot, "tier": tier,
            "source_graph_sha256": source_graph_sha}


__all__ = ["load_video"]
