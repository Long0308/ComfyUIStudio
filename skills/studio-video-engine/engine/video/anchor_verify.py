"""Kiểm lại pack ĐÃ LƯU (``jjv/shot-anchor-pack/v1``) bằng đúng luật lúc dựng — chỉ đọc, không GPU, không nêu tên domain.

Một pack trên đĩa không được tin chỉ vì sha ảnh khớp (critic CR-ANCHOR-REFS 31/10): mỗi ref face/body phải mang receipt ảnh route
hợp lệ (``anchor_refs.ROUTES``) của ĐÚNG take; trang phục phải nằm trong preset đã ghi ở ``sources.wardrobe_presets`` (sha preset
khớp); bối cảnh và storyboard phải có receipt ảnh của đúng file HOẶC ``user_approved.by``; tên ảnh stage pilot ``h3-<sha>`` LUÔN
bị từ chối.  ``validate_pack`` trả các dòng ``ANCHOR_PACK_INVALID: …`` (rỗng = hợp lệ; ``require_valid`` ⇒ Refused).
``sources_drift`` băm lại các file nguồn pack ghi (trừ ``thumbs``: chỉ cho UI); ``shotlist_drift`` so sha shotlist HIỆN TẠI và
context / ``context_per_character`` của shot (luật user 31/10: đổi context ⇒ bộ trang phục cũ không còn đúng) ⇒ ``require_fresh``
Refused ``ANCHOR_PACK_STALE``.  Dùng chung cho ``anchor_pack_ui`` (panel), ``anchor_stage`` (nạp) và ``h3.pack_refs`` (H3).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..comfy.settings import ComfySettings
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..layout.context import Context
from . import ui_wardrobe
from .anchor_pack import SCHEMA
from .anchor_refs import RECEIPT_SCHEMAS, ROUTES, resolve_recorded

INVALID = "ANCHOR_PACK_INVALID"
STALE = "ANCHOR_PACK_STALE"
FOREIGN = "ANCHOR_PACK_FOREIGN"
ROLES = ("face", "body", "wardrobe", "location")
UI_ONLY_SOURCES = ("thumbs",)
_LEGACY_STAGED = re.compile(r"^h3-[0-9a-f]{8,64}(\.|$)", re.IGNORECASE)


def load_pack(ctx: Context, path: Path) -> dict[str, Any]:
    """Pack của ĐÚNG episode/domain; file lạ hay schema khác ⇒ Refused (không bao giờ đọc tiếp)."""
    pack = read_json(path) if Path(path).is_file() else None
    if not isinstance(pack, dict) or pack.get("schema") != SCHEMA:
        raise Refused(f"{FOREIGN}: {path} is not a {SCHEMA} pack")
    if (pack.get("episode_id"), pack.get("domain")) != (ctx.episode_id, ctx.domain_id):
        raise Refused(f"{FOREIGN}: {path} belongs to {pack.get('episode_id')!r}/{pack.get('domain')!r}, not "
                      f"{ctx.episode_id!r}/{ctx.domain_id!r}; episodes and domains are never mixed")
    return pack


def is_legacy_staged_name(value: Any) -> bool:
    return isinstance(value, str) and bool(_LEGACY_STAGED.match(Path(value).name))


def _file_ok(text: Any, sha: Any, machine: dict | None) -> tuple[Path | None, str | None]:
    """``(path, lỗi)``: file phải có thật và băm đúng sha đã ghi."""
    if not isinstance(text, str) or not isinstance(sha, str):
        return None, "needs path + sha256"
    path = resolve_recorded(text, machine)
    if not path.is_file():
        return path, f"{path} is missing"
    found = sha256_file(path)
    if found != sha:
        return path, f"{path} hashes to {found[:12]}, not the recorded {sha[:12]}"
    return path, None


def _receipt_problem(ref: dict[str, Any], machine: dict | None) -> str | None:
    """Receipt ảnh của đúng take: file receipt băm đúng sha ghi, schema ảnh, route trong ROUTES, output.sha256 = sha ref."""
    recorded = ref.get("receipt")
    if not isinstance(recorded, dict):
        return "no image receipt"
    receipt_path, error = _file_ok(recorded.get("path"), recorded.get("sha256"), machine)
    if error:
        return f"receipt {error}"
    body = read_json(receipt_path)
    if not isinstance(body, dict) or body.get("schema") not in RECEIPT_SCHEMAS:
        return f"{receipt_path.name} is not an image receipt {RECEIPT_SCHEMAS}"
    route = body.get("route") or body.get("provider")
    if route not in ROUTES:
        return f"receipt route {route!r} is not an image route {sorted(ROUTES)}"
    if (body.get("output") or {}).get("sha256") != ref.get("sha256"):
        return f"receipt {receipt_path.name} is for another take"
    return None


def _proof_problem(ref: dict[str, Any], machine: dict | None) -> str | None:
    """Bối cảnh / storyboard: receipt ảnh của đúng file HOẶC ``user_approved.by`` không rỗng."""
    approved = ref.get("user_approved")
    if isinstance(approved, dict) and isinstance(approved.get("by"), str) and approved["by"].strip():
        return None
    if isinstance(ref.get("receipt"), dict):
        return _receipt_problem(ref, machine)
    return "no image receipt and no user_approved {by} mark"


def _preset_shas(ctx: Context, pack: dict[str, Any]) -> tuple[set[str], str | None]:
    """Sha của mọi item trong preset trang phục pack ghi; preset đã đổi byte là chuyện của ``sources_drift`` (stale), không phải invalid."""
    source = (pack.get("sources") or {}).get("wardrobe_presets")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        return set(), "sources.wardrobe_presets is missing"
    path = resolve_recorded(source["path"], ctx.machine)
    if not path.is_file():
        return set(), f"wardrobe presets {path} is missing"
    try:
        anchors = ui_wardrobe.load_anchors(path, ctx.domain_id)
    except Refused as refusal:
        return set(), str(refusal)
    groups = [*anchors["contexts"].values(), anchors.get("company") or [], *((anchors.get("scene_refs") or {}).values())]
    return {item["sha256"] for group in groups for item in (group or []) if isinstance(item, dict)}, None


def validate_pack(ctx: Context, pack: dict[str, Any]) -> list[str]:
    """Mọi lỗi của pack đã lưu theo luật dựng, mỗi dòng ``ANCHOR_PACK_INVALID: <ref>: <vì sao>``; rỗng = hợp lệ."""
    problems: list[str] = []
    preset_shas, preset_error = (_preset_shas(ctx, pack) if pack.get("wardrobe_refs") else (set(), None))
    for role in ROLES:
        for ref in pack.get(f"{role}_refs") or []:
            label = f"{role} {ref.get('name')}"
            if is_legacy_staged_name(ref.get("name")) or is_legacy_staged_name(ref.get("path")):
                problems.append(f"{INVALID}: {label}: a staged pilot input (h3-<sha>) is never a reference")
                continue
            _, error = _file_ok(ref.get("path"), ref.get("sha256"), ctx.machine)
            if error is None and role in ("face", "body"):
                error = _receipt_problem(ref, ctx.machine)
            elif error is None and role == "wardrobe":
                error = preset_error or (None if ref.get("sha256") in preset_shas else "not in the recorded wardrobe presets")
            elif error is None:
                error = _proof_problem(ref, ctx.machine)
            if error:
                problems.append(f"{INVALID}: {label}: {error}")
    board = pack.get("storyboard_anchor") or {}
    if board.get("status") != "pending" and (is_legacy_staged_name(board.get("name")) or is_legacy_staged_name(board.get("path"))):
        problems.append(f"{INVALID}: storyboard: a staged pilot input (h3-<sha>) is never a reference")
    elif board.get("status") != "pending":
        _, error = _file_ok(board.get("path"), board.get("sha256"), ctx.machine)
        error = error or _proof_problem(board, ctx.machine)
        if error:
            problems.append(f"{INVALID}: storyboard: {error}")
    known = {(role, r.get("sha256")) for role in ROLES for r in pack.get(f"{role}_refs") or []}
    slots = [row.get("slot") for row in (pack.get("ref_slots") or {}).get("bound") or []]
    for row in (pack.get("ref_slots") or {}).get("bound") or []:
        if (row.get("role"), row.get("sha256")) not in known:
            problems.append(f"{INVALID}: slot {row.get('slot')}: bound to {str(row.get('sha256'))[:12]} which is no "
                            f"{row.get('role')} ref of this pack")
    if len(set(slots)) != len(slots):
        problems.append(f"{INVALID}: ref_slots: a slot is bound twice {slots}")
    return problems


def require_valid(ctx: Context, pack: dict[str, Any]) -> None:
    problems = validate_pack(ctx, pack)
    if problems:
        raise Refused("; ".join(problems))


def sources_drift(ctx: Context, pack: dict[str, Any]) -> list[str]:
    """Các file nguồn pack ghi (selection, shotlist, library_index, wardrobe_presets) băm lại trên đĩa; lệch ⇒ dòng mô tả."""
    lines = []
    for key, source in (pack.get("sources") or {}).items():
        if key in UI_ONLY_SOURCES or not isinstance(source, dict):
            continue
        path = resolve_recorded(str(source.get("path")), ctx.machine)
        now = sha256_file(path) if path.is_file() else None
        if now != source.get("sha256"):
            lines.append(f"{key} {str(source.get('sha256'))[:12]} -> now {now[:12] if now else 'missing'}")
    return lines


def shotlist_drift(ctx: Context, pack: dict[str, Any], shotlist: Path, settings: ComfySettings) -> list[str]:
    """Shotlist HIỆN TẠI: sha khác sha lúc dựng, hoặc context / context_per_character của shot đổi ⇒ dòng mô tả."""
    from . import ui_state  # import tại chỗ: ui_state -> anchor_pack_ui -> module này

    lines = []
    then = ((pack.get("sources") or {}).get("shotlist") or {}).get("sha256")
    now = sha256_file(shotlist)
    if now != then:
        lines.append(f"shotlist {str(then)[:12]} -> now {now[:12]} ({Path(shotlist).name})")
    _, rows = ui_state.load_shotlist(ctx, Path(shotlist), settings)
    row = next((r for r in rows if r["id"] == pack.get("shot")), None)
    if row is None:
        return lines + [f"shot {pack.get('shot')} is not in {Path(shotlist).name}"]
    if row.get("context") and row["context"] != pack.get("context"):
        lines.append(f"context {pack.get('context')} -> now {row['context']}")
    key = ui_wardrobe.PER_CHARACTER_KEY
    if (row.get(key) or None) != (pack.get(key) or None):
        lines.append(f"{key} {pack.get(key)} -> now {row.get(key)}")
    return lines


def require_fresh(ctx: Context, pack: dict[str, Any], *, shotlist: Path | None, settings: ComfySettings) -> list[str]:
    """Refused ``ANCHOR_PACK_STALE`` khi nguồn đã ghi hoặc shotlist hiện tại lệch; trả danh sách chưa so được (không đoán)."""
    lines = sources_drift(ctx, pack)
    if shotlist is not None:
        lines += shotlist_drift(ctx, pack, Path(shotlist), settings)
    if lines:
        raise Refused(f"{STALE}: {pack.get('shot')}: pack built from other inputs ({'; '.join(lines)}); rebuild it with "
                      "jjv video anchor-pack before staging or binding")
    return [] if shotlist is not None else ["shotlist"]


__all__ = ["INVALID", "STALE", "FOREIGN", "ROLES", "load_pack", "is_legacy_staged_name", "validate_pack", "require_valid",
           "sources_drift", "shotlist_drift", "require_fresh"]
