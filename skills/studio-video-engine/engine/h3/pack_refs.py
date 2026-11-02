"""Nối H3 với bộ neo ảnh của shot (``jjv/shot-anchor-pack/v1``): MỌI ảnh tham chiếu lấy từ pack, không bao giờ từ file casting.

``rows_from_pack`` (``jjv h3 inputs --anchor-dir``): pack phải hợp lệ theo luật dựng (``anchor_verify``), không stale (nguồn đã
ghi + ``--shotlist`` hiện tại: sha và context), ĐÃ nạp vào gốc ComfyUI input (``pack.staged`` của ``jjv video anchor-stage``; thiếu
hay lệch sha ⇒ ``ANCHOR_PACK_NOT_STAGED``); mỗi slot ``ref_images.ref_image_N`` tìm LoadImage của template qua CHÍNH input key đó
(không đoán theo tên node); loader ref không có ảnh ⇒ ``REF_SLOTS_UNFILLED`` (mute trong template hoặc thêm ref).  AddGuide
(``anchor_ports`` của spec) = storyboard của pack khi không pending; pending ⇒ ``STORYBOARD_PENDING`` trừ khi
``allow_pending_storyboard`` (pilot: ảnh ACTION đầu, rồi FACE, ghi ``storyboard.pilot: true``).  ``verify_row`` chạy lại toàn bộ
kiểm đó ở ``h3 prepare`` và ``load_prepared`` (submit): pack đổi sha, nguồn lệch, ref lệch slot/sha/tên nạp ⇒ Refused, không thay thế.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..comfy.settings import settings_from_machine
from ..comfy.staging import require_hash
from ..core.errors import EngineError, Refused
from ..core.io import read_json, sha256_file
from ..images import library as image_library
from ..layout.context import Context
from ..video import anchor_verify
from ..video.anchor_pack import PACK_FILE
from ..video.anchor_refs import STORYBOARD_RULE, resolve_recorded
from ..video.anchor_stage import GUIDE_SLOT

NOT_STAGED = "ANCHOR_PACK_NOT_STAGED"
UNFILLED = "REF_SLOTS_UNFILLED"
PENDING = "STORYBOARD_PENDING"
MISMATCH = "ANCHOR_PACK_REF_MISMATCH"
NOT_APPROVED = "ANCHOR_NOT_APPROVED"
APPROVAL_SHA_MISMATCH = "ANCHOR_APPROVAL_SHA_MISMATCH"
PACK_NOT_APPROVED = "ANCHOR_PACK_NOT_APPROVED"
LIBRARY_ROLES = ("face", "body", "location")  # roles whose image must carry a SHA-bound library approval (wardrobe: preset)
PILOT_ORDER = ("body", "face")
_SLOT = re.compile(r"ref_images\.ref_image_\d+")


def _rel(path: Path, root: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _absolute(text: str, root: Path) -> Path:
    given = Path(text)
    return given if given.is_absolute() else Path(root) / given


def staged_of(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``slot -> staged row`` của pack; chưa nạp hay nạp dưới subfolder (LoadImage không đọc được) ⇒ Refused."""
    rows = pack.get("staged")
    if not isinstance(rows, list) or not rows:
        raise Refused(f"{NOT_STAGED}: {pack.get('shot')}: the pack has no staged[]; run `jjv video anchor-stage` first")
    for row in rows:
        if row.get("input_subfolder"):
            raise Refused(f"{NOT_STAGED}: {pack.get('shot')}: {row.get('filename')} is staged under a subfolder; LoadImage reads the "
                          "input root only — re-run `jjv video anchor-stage`")
    return {row["slot"]: row for row in rows}


def ref_loaders(graph: dict[str, Any]) -> dict[str, str]:
    """``ref_images.ref_image_N -> LoadImage node id`` cho mọi input key như vậy của graph (không theo tên node)."""
    found: dict[str, str] = {}
    for item in graph.values():
        for key, value in (item.get("inputs") or {}).items():
            if _SLOT.fullmatch(key) and isinstance(value, list) and len(value) == 2 and str(value[0]) in graph \
                    and graph[str(value[0])].get("class_type") == "LoadImage":
                found[key] = str(value[0])
    return found


def _staged_for(pack: dict[str, Any], staged: dict[str, dict], slot: str, sha256: str) -> dict[str, Any]:
    row = staged.get(slot)
    if row is None or row.get("sha256") != sha256:
        raise Refused(f"{NOT_STAGED}: {pack.get('shot')}: slot {slot} ({str(sha256)[:12]}) is not in pack.staged; re-run "
                      "`jjv video anchor-stage`")
    return row


def _ref_row(ctx: Context, pack: dict[str, Any], bound: dict[str, Any], staged: dict[str, dict], ports: list) -> dict[str, Any]:
    ref = next(r for r in pack[f"{bound['role']}_refs"] if r.get("sha256") == bound["sha256"])  # validate_pack đã kiểm
    row = _staged_for(pack, staged, bound["slot"], bound["sha256"])
    return {"path": _rel(resolve_recorded(ref["path"], ctx.machine), ctx.root), "sha256": bound["sha256"], "ports": ports,
            "role": bound["role"], "slot": bound["slot"], "name": ref["name"], "input_name": row["filename"]}


def _library_out(ctx: Context, ref: dict[str, Any], receipt_path: Path) -> Path:
    """Find the library root through the existing approval record or library receipt layout."""
    record = ref.get("approval_record")
    if isinstance(record, str):
        path = resolve_recorded(record, ctx.machine)
        if len(path.parents) >= 4 and path.parent.name == "approvals":
            return path.parents[3]
    return receipt_path.parents[2]


def _require_ref_approval(ctx: Context, pack: dict[str, Any], ref: dict[str, Any]) -> None:
    """Require a current, SHA-bound library approval for face/body/location; only verified recipe-owned wardrobe presets are exempt.

    Also the check the legacy cast path (``inputs._require_cast_face_approval``) reuses for every cast face."""
    role = ref.get("role")
    label = f"{pack.get('shot')} {role} {ref.get('name')}"
    if role == "wardrobe":
        # anchor_verify.require_valid has just proven this SHA is present in the pack's recorded preset.
        if ref.get("source_route") != "preset" or ref.get("verified") is not True:
            raise Refused(f"{NOT_APPROVED}: {label}: wardrobe exemption applies only to a verified, recipe-owned preset")
        return
    if role not in LIBRARY_ROLES:
        raise Refused(f"{NOT_APPROVED}: {label}: no current SHA-bound library approval is recorded for this ref")
    prompt_id = ref.get("prompt_id")
    receipt = ref.get("receipt")
    if not isinstance(prompt_id, str) or not isinstance(receipt, dict) or not isinstance(receipt.get("path"), str):
        raise Refused(f"{NOT_APPROVED}: {label}: missing library prompt_id or receipt; approve the exact library take first")
    receipt_path = resolve_recorded(receipt["path"], ctx.machine)
    if role == "location":
        problem = anchor_verify._receipt_problem(ref, ctx.machine)
        if problem:
            raise Refused(f"{NOT_APPROVED}: {label}: {problem}")
        body = read_json(receipt_path)
        if body.get("schema") != "jjv/library-image-receipt/v1" or body.get("prompt_id") != prompt_id:
            raise Refused(f"{NOT_APPROVED}: {label}: prompt_id does not match the library receipt")
    out = _library_out(ctx, ref, receipt_path)
    try:
        approval = image_library.current_approval(out, prompt_id)
    except EngineError as exc:
        raise Refused(f"{NOT_APPROVED}: {label}: current library approval could not be verified: {exc}") from exc
    if approval is None:
        raise Refused(f"{NOT_APPROVED}: {label}: no current library approval; approve it with `jjv images approve "
                      f"--episode {ctx.episode_id} --out <images-out> --library-out {out} --prompt-id {prompt_id} "
                      f"--sha {ref.get('sha256')} --reviewer <name> --scope character-reference`")
    approved_sha = approval.get("candidate_sha256")
    if approved_sha != ref.get("sha256"):
        raise Refused(f"{APPROVAL_SHA_MISMATCH}: {label}: current approval names sha256 {approved_sha}, "
                      f"but the pack ref is {ref.get('sha256')}; rebuild the pack after approving the intended take")
    if approval.get("schema") != image_library.APPROVAL_SCHEMA or approval.get("status") != "accepted_library_image":
        raise Refused(f"{NOT_APPROVED}: {label}: current record is not a library-image approval")
    recorded = ref.get("approval_record")
    current_path = approval.get("path")
    if not isinstance(recorded, str) or not isinstance(current_path, str) \
            or resolve_recorded(recorded, ctx.machine) != resolve_recorded(current_path, ctx.machine):
        raise Refused(f"{NOT_APPROVED}: {label}: pack does not bind the current approval record; rebuild the pack")
    if ref.get("approval") != "approved":
        raise Refused(f"{NOT_APPROVED}: {label}: the pack records this ref as {ref.get('approval')!r}; rebuild it after approval")


def _require_pack_approvals(ctx: Context, pack: dict[str, Any], *, allow_pending_storyboard: bool) -> None:
    """Fail closed before H3 inputs are written; explicit pilot mode covers only a pending storyboard."""
    from ..policy import identity_guard
    identity_guard.check_refs(getattr(ctx, "domain", None),
                              [{**ref, "role": "face"} for ref in pack.get("face_refs") or []],
                              where=f"anchor pack {pack.get('shot')}")
    for role in ("face", "body", "wardrobe", "location"):
        for ref in pack.get(f"{role}_refs") or []:
            _require_ref_approval(ctx, pack, ref)
    if pack.get("status") == "approved" and pack.get("ready_for_graph") is True:
        return
    board = pack.get("storyboard_anchor") or {}
    if allow_pending_storyboard and board.get("status") == "pending":
        return
    if board.get("status") == "pending":
        raise Refused(f"{PENDING}: {pack.get('shot')}: the pack storyboard is pending; an explicit pilot flag is required")
    reasons = pack.get("not_ready_reasons") or []
    detail = "; ".join(str(reason) for reason in reasons) or f"status={pack.get('status')!r}, ready_for_graph={pack.get('ready_for_graph')!r}"
    raise Refused(f"{PACK_NOT_APPROVED}: {pack.get('shot')}: {detail}; approve the image refs and rebuild the pack before H3")


def _guide(ctx: Context, pack: dict[str, Any], staged: dict[str, dict], anchor_ports: list,
           allow_pending: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """AddGuide image: storyboard của pack; pending ⇒ STORYBOARD_PENDING, hoặc (pilot, cờ rõ) ảnh ACTION/FACE đầu của pack."""
    board = pack.get("storyboard_anchor") or {}
    shot = pack.get("shot")
    if board.get("status") != "pending":
        row = _staged_for(pack, staged, GUIDE_SLOT, str(board.get("sha256")))
        anchor = {"path": _rel(resolve_recorded(str(board["path"]), ctx.machine), ctx.root), "sha256": board["sha256"],
                  "ports": anchor_ports, "role": "storyboard", "slot": GUIDE_SLOT, "name": Path(str(board["path"])).name,
                  "input_name": row["filename"]}
        return anchor, {"status": board["status"], "pilot": False}
    if not allow_pending:
        raise Refused(f"{PENDING}: {shot}: the pack storyboard is pending ({STORYBOARD_RULE}); make the first frame with the "
                      "image route and rebuild the pack, or pass --allow-pending-storyboard for a PILOT only")
    bound = (pack.get("ref_slots") or {}).get("bound") or []
    pick = next((b for role in PILOT_ORDER for b in bound if b.get("role") == role), None)
    if pick is None:
        raise Refused(f"{PENDING}: {shot}: no body/face ref in the pack to stand in as the pilot guide")
    ref = _ref_row(ctx, pack, pick, staged, anchor_ports)
    return {**ref, "role": f"pilot-guide:{pick['role']}", "slot": GUIDE_SLOT}, {"status": "pending", "pilot": True}


def rows_from_pack(ctx: Context, pack_path: Path, graph: dict[str, Any], *, anchor_ports: list, shotlist: Path | None,
                   allow_pending_storyboard: bool = False, drop_unfilled: bool = False) -> dict[str, Any]:
    """``{anchor_pack, anchor, refs, storyboard, overflow, dropped_refs}`` cho một manifest row; mọi từ chối trước mọi ghi.

    ``drop_unfilled`` (spec key ``drop_unfilled_refs``): a template ref loader the pack has no image for is not an error;
    its slot is listed in ``dropped_refs`` and ``h3 prepare`` removes that loader (``prepare.drop_ref_loaders``)."""
    pack_path = Path(pack_path)
    pack = anchor_verify.load_pack(ctx, pack_path)
    settings = settings_from_machine(ctx.machine)
    unchecked = anchor_verify.require_fresh(ctx, pack, shotlist=shotlist, settings=settings)  # stale trước: nguồn đổi = dựng lại
    anchor_verify.require_valid(ctx, pack)
    _require_pack_approvals(ctx, pack, allow_pending_storyboard=allow_pending_storyboard)
    staged = staged_of(pack)
    loaders = ref_loaders(graph)
    bound = (pack.get("ref_slots") or {}).get("bound") or []
    refs = []
    for row in bound:
        loader = loaders.get(row["slot"])
        if loader is None:
            raise Refused(f"{pack['shot']}: the template has no LoadImage wired to {row['slot']}; the pack binds {len(bound)} refs")
        refs.append(_ref_row(ctx, pack, row, staged, [[loader, "image"]]))
    unfilled = sorted(set(loaders) - {r["slot"] for r in bound})
    if unfilled and not drop_unfilled:
        raise Refused(f"{UNFILLED}: {pack['shot']}: template ref loaders {unfilled} have no pack ref (the pack binds {len(bound)}); "
                      "mute them in the template or add refs to the pack")
    anchor, storyboard = _guide(ctx, pack, staged, anchor_ports, allow_pending_storyboard)
    record = {"path": _rel(pack_path, ctx.root), "sha256": sha256_file(pack_path), "context": pack.get("context"),
              "shotlist": {"path": _rel(Path(shotlist), ctx.root), "sha256": sha256_file(shotlist)} if shotlist else None,
              "stale_unchecked": unchecked}
    return {"anchor_pack": record, "anchor": anchor, "refs": refs, "storyboard": storyboard,
            "overflow": [r.get("name") for r in (pack.get("ref_slots") or {}).get("overflow") or []],
            "dropped_refs": unfilled}


def verify_row(ctx: Context, row: dict[str, Any]) -> None:
    """Chạy lại ở prepare / load_prepared: pack cùng sha, hợp lệ, không stale, mọi ref và AddGuide khớp slot + sha + tên nạp."""
    recorded = row["anchor_pack"]
    pack_path = _absolute(recorded["path"], ctx.root)
    require_hash(pack_path, recorded["sha256"], "anchor pack")
    pack = anchor_verify.load_pack(ctx, pack_path)
    shotlist = None
    if recorded.get("shotlist"):
        shotlist = _absolute(recorded["shotlist"]["path"], ctx.root)
        require_hash(shotlist, recorded["shotlist"]["sha256"], "anchor pack shotlist")
    anchor_verify.require_fresh(ctx, pack, shotlist=shotlist, settings=settings_from_machine(ctx.machine))  # stale trước
    anchor_verify.require_valid(ctx, pack)
    _require_pack_approvals(ctx, pack, allow_pending_storyboard=(row.get("storyboard") or {}).get("pilot") is True)
    staged = staged_of(pack)
    bound = {b["slot"]: b for b in (pack.get("ref_slots") or {}).get("bound") or []}
    for ref in row.get("refs") or []:
        slot, want = ref.get("slot"), bound.get(ref.get("slot"))
        if want is None or (want["sha256"], want["role"]) != (ref.get("sha256"), ref.get("role")) \
                or _staged_for(pack, staged, slot, want["sha256"])["filename"] != ref.get("input_name"):
            raise Refused(f"{MISMATCH}: {pack['shot']}: {slot} {ref.get('name')} no longer matches the pack; rebuild the manifest")
    anchor, story, board = row["anchor"], row.get("storyboard") or {}, pack.get("storyboard_anchor") or {}
    if story.get("pilot") is True:
        pick = next((b for b in bound.values() if b["sha256"] == anchor.get("sha256")), None)
        ok = board.get("status") == "pending" and pick is not None \
            and _staged_for(pack, staged, pick["slot"], pick["sha256"])["filename"] == anchor.get("input_name")
    else:
        if board.get("status") == "pending":
            raise Refused(f"{PENDING}: {pack['shot']}: the pack storyboard is pending; the manifest is not a pilot")
        ok = anchor.get("sha256") == board.get("sha256") and story.get("status") == board.get("status") \
            and _staged_for(pack, staged, GUIDE_SLOT, str(board.get("sha256")))["filename"] == anchor.get("input_name")
    if not ok:
        raise Refused(f"{MISMATCH}: {pack['shot']}: the AddGuide image no longer matches the pack storyboard; rebuild the manifest")


__all__ = ["PACK_FILE", "NOT_STAGED", "UNFILLED", "PENDING", "MISMATCH", "NOT_APPROVED", "APPROVAL_SHA_MISMATCH",
           "PACK_NOT_APPROVED", "staged_of", "ref_loaders", "rows_from_pack", "verify_row"]
