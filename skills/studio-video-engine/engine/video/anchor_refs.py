"""Ref có bằng chứng cho ``anchor_pack`` (``jjv/shot-anchor-pack/v1``): trang phục theo preset, bối cảnh, storyboard — chỉ đọc.

Cùng MỘT luật cho bối cảnh (``location[]``) và storyboard: file phải mang receipt ảnh của đúng take (route ``codex`` |
``comfyui-local``, sha của receipt = sha file trên đĩa) HOẶC được user đánh dấu ``user_approved {by, note}``; chỉ đúng sha256
thì CHƯA đủ — một casting sheet / storyboard cũ khai vào đây bị ``Refused`` (``LOCATION_UNVERIFIED`` / ``STORYBOARD_UNVERIFIED``),
không bao giờ được thay thế im lặng.  Trang phục đọc từ ``jjv/wardrobe-presets/v1`` theo context của shot và
``context_per_character`` (cảnh hai người) qua ``ui_wardrobe`` — không đoán context.  Mọi đường dẫn do caller truyền.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.settings import ComfySettings
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path
from ..layout.context import REPO_ROOT, Context
from . import ui_wardrobe

RECEIPT_SCHEMAS = ("jjv/library-image-receipt/v1", "jjv/image-receipt/v1")
ROUTES = {"codex-exec": "codex", "codex-adopt": "codex", "codex-builtin": "codex", "comfyui-local": "comfyui-local",
          "user-approved-external": "user-approved-external"}  # ảnh ngoài luồng sinh: `images library register` (bắt buộc file duyệt)
STORYBOARD_RULE = ("the first frame must itself be produced by an image route (codex | comfyui-local) from this pack's refs and "
                   "carry its receipt; an old casting/storyboard file is never substituted unless the user marks it approved")
LOCATION_RULE = ("a location image must carry an image receipt (codex | comfyui-local) of this very file or a user_approved "
                 "{by, note} mark; an old casting/storyboard file is never used as a location")


# ---- helpers dùng chung với anchor_pack --------------------------------------------------------------------
def rel(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def resolve_recorded(text: str, machine: dict | None) -> Path:
    """Đường dẫn ghi trong selection/pack: tương đối ⇒ dưới repo root; tuyệt đối ⇒ remap legacy roots (không sửa file ghi)."""
    given = Path(text)
    return resolve_data_path(given if given.is_absolute() else REPO_ROOT / given, machine)


def hash_check(path: Path, sha: str, label: str) -> str:
    if not Path(path).is_file():
        raise Refused(f"FILE_MISSING: {label}: {path} is not a file")
    found = sha256_file(path)
    if found != sha:
        raise Refused(f"SHA_MISMATCH: {label}: {path} hashes to {found[:12]}, expected {str(sha)[:12]}; nothing substituted")
    return found


def file_ref(path: Path) -> dict[str, str]:
    return {"path": rel(path), "sha256": sha256_file(path)}


def route_of(receipt: dict[str, Any], label: str, code: str = "ROUTE_UNKNOWN") -> tuple[str, str]:
    raw = receipt.get("route") or receipt.get("provider")
    if raw not in ROUTES:
        raise Refused(f"{code}: {label}: receipt route {raw!r} is not an image route {sorted(ROUTES)}; never substituted")
    return str(raw), ROUTES[str(raw)]


def image_receipt(ctx: Context, text: str, path: Path, label: str, code: str) -> dict[str, Any]:
    """Receipt ảnh của ĐÚNG file ``path`` (schema + route + sha take = sha file); sai bất kỳ ⇒ Refused mang ``code``."""
    receipt_path = resolve_recorded(text, ctx.machine)
    receipt = read_json(receipt_path) if receipt_path.is_file() else None
    if not isinstance(receipt, dict) or receipt.get("schema") not in RECEIPT_SCHEMAS:
        raise Refused(f"{code}: {label}: {receipt_path} is not an image receipt {RECEIPT_SCHEMAS}")
    sha = hash_check(path, str((receipt.get("output") or {}).get("sha256")), f"{code} {label}")
    raw, route = route_of(receipt, label, code)
    return {"route": raw, "source_route": route, "receipt": file_ref(receipt_path), "sha256": sha}


def user_approved(spec: dict, label: str) -> dict[str, str] | None:
    given = spec.get("user_approved")
    if given is None:
        return None
    if not isinstance(given, dict) or not isinstance(given.get("by"), str) or not given["by"].strip():
        raise Refused(f"{label}: user_approved needs {{by, note}} (who marked it approved)")
    return {"by": given["by"], "note": str(given.get("note") or "")}


# ---- wardrobe / location / storyboard -------------------------------------------------------------------
def wardrobe_refs(ctx: Context, presets: Path, shot: str, scene: str | None, context: str | None,
                  per_character: dict | None, settings: ComfySettings) -> list[dict[str, Any]]:
    anchors = ui_wardrobe.load_anchors(Path(presets), ctx.domain_id)
    row = {"id": shot, "scene": scene, "context": context, ui_wardrobe.PER_CHARACTER_KEY: per_character or {}}
    bound = ui_wardrobe.attach(row, anchors, settings, ctx.machine)
    if bound["refused"]:
        raise Refused(bound["refused"].replace("WARDROBE_CONTEXT_UNKNOWN", "WARDROBE_CONTEXT_UNKNOWN (selection context)"))
    unknown = [p for p in bound["problems"] if p.startswith("WARDROBE_CONTEXT_UNKNOWN")]
    if unknown:
        raise Refused("; ".join(unknown))
    bad = [r for r in bound["refs"] if not r["verified"]]
    if bad:
        raise Refused("WARDROBE_REF_UNVERIFIED: " + "; ".join(f"{r['name']} ({r['sha256'][:12]}) at {r['path']}" for r in bad))
    if not bound["refs"]:
        raise Refused(f"WARDROBE_MISSING: context {context!r} has no wardrobe refs in {presets}")
    items = {i["sha256"]: i for group in [*anchors["contexts"].values(), anchors.get("company") or []] for i in group}
    return [{"role": "wardrobe", "name": r["name"], "file": r["file"], "path": rel(Path(r["path"])), "sha256": r["sha256"],
             "preset_role": r["preset_role"], "preset_group": r["role"], "context": r["context"], "characters": r["characters"],
             "verified": True, "source_route": "preset",
             "approval": "approved" if (items.get(r["sha256"]) or {}).get("approval") == "approved" else "candidate"}
            for r in bound["refs"]]


def location_refs(ctx: Context, rows: list[dict], shot: str, *, approval_lookup=None) -> list[dict[str, Any]]:
    """Mỗi bối cảnh: sha đúng + (receipt ảnh của đúng file HOẶC user_approved); thiếu cả hai ⇒ LOCATION_UNVERIFIED."""
    refs = []
    for index, row in enumerate(rows):
        label = f"{shot} location[{index}]"
        if not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            raise Refused(f"LOCATION_UNVERIFIED: {label}: needs path + sha256")
        path = resolve_recorded(row["path"], ctx.machine)
        sha = hash_check(path, row["sha256"], f"LOCATION_UNVERIFIED {label}")
        approved = user_approved(row, label)
        proof = image_receipt(ctx, row["receipt"], path, label, "LOCATION_UNVERIFIED") if isinstance(row.get("receipt"), str) else None
        if proof is None and approved is None:
            raise Refused(f"LOCATION_UNVERIFIED: {label}: {path} has no image receipt and no user_approved mark; {LOCATION_RULE}")
        # Bind the ID to the verified receipt, never to untrusted selection input.
        prompt_id, approval, record = None, "candidate", None
        if proof:
            receipt_path = resolve_recorded(row["receipt"], ctx.machine)
            receipt = read_json(receipt_path)
            if receipt.get("schema") == "jjv/library-image-receipt/v1":
                prompt_id = receipt.get("prompt_id")
                if isinstance(prompt_id, str) and prompt_id and approval_lookup:
                    approval, record = approval_lookup(receipt_path, prompt_id, sha)
                else:
                    prompt_id = None
        refs.append({"role": "location", "name": row.get("name") or path.name, "path": rel(path), "sha256": sha,
                     "route": (proof or {}).get("route"), "source_route": proof["source_route"] if proof else "user-approved",
                     "receipt": (proof or {}).get("receipt"), "prompt_id": prompt_id, "approval_record": record,
                     "approval": approval if prompt_id else ("approved" if approved else "candidate"),
                     "user_approved": approved, "rule": LOCATION_RULE})
    return refs


def storyboard_ref(ctx: Context, spec: Any, shot: str) -> dict[str, Any]:
    if spec == "PENDING":
        return {"status": "pending", "path": None, "sha256": None, "source_route": None, "receipt": None, "rule": STORYBOARD_RULE}
    label = f"STORYBOARD {shot}"
    if not isinstance(spec.get("path"), str):
        raise Refused(f"STORYBOARD_UNVERIFIED: {label}: needs path")
    path = resolve_recorded(spec["path"], ctx.machine)
    approved = user_approved(spec, label)
    if isinstance(spec.get("receipt"), str):
        proof = image_receipt(ctx, spec["receipt"], path, label, "STORYBOARD_UNVERIFIED")
        return {"status": "approved" if approved else "candidate", "path": rel(path), **proof, "user_approved": approved,
                "rule": STORYBOARD_RULE}
    if approved is None:
        raise Refused(f"STORYBOARD_UNVERIFIED: {label}: {path} has no image receipt and no user_approved mark; an old "
                      "casting/storyboard file is never substituted")
    sha = hash_check(path, str(spec.get("sha256")), f"STORYBOARD_UNVERIFIED {label}")
    return {"status": "approved", "path": rel(path), "sha256": sha, "route": None, "source_route": "user-approved", "receipt": None,
            "user_approved": approved, "rule": STORYBOARD_RULE}


__all__ = ["RECEIPT_SCHEMAS", "ROUTES", "STORYBOARD_RULE", "LOCATION_RULE", "rel", "resolve_recorded", "hash_check", "file_ref",
           "route_of", "image_receipt", "user_approved", "wardrobe_refs", "location_refs", "storyboard_ref"]
