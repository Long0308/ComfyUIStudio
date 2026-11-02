"""Gắn bộ neo ảnh cảnh (``jjv/shot-anchor-pack/v1``, xem ``anchor_pack``) vào trạng thái panel ``ui_state`` — chỉ đọc.

Luật user 31/10: ``refs`` của một shot CHỈ đến từ pack đã kiểm (face/body/wardrobe/location + storyboard có receipt); mọi ảnh
LoadImage của graph pilot cũ nằm riêng ở ``legacy_refs`` (``ui_state``), không bao giờ trộn vào ``refs``.  Mỗi shot nhận
``anchor_pack``: ``None`` + ``refs: []`` + problem ``ANCHOR_PACK_MISSING`` khi chưa có ``<anchor_dir>/<shot>/anchor-pack.json`` (hoặc không
truyền ``--anchor-dir``); có file ⇒ pack phải thuộc đúng episode/domain/shot, mọi ảnh được băm lại trên đĩa (lệch ⇒ ``status: None``,
``refs: []`` + problem ``ANCHOR_PACK_BROKEN``, không bịa).  Cổng trang phục ``wardrobe.refs[].port`` chép từ ``pack.ref_slots.bound``
theo sha256 (nguồn duy nhất; ref ở ``overflow`` hoặc pack hỏng ⇒ null).  ``pack.sources`` (sha shotlist / wardrobe lúc dựng) lệch
input của lượt này ⇒ problem ``ANCHOR_PACK_STALE`` + ``anchor_pack.stale`` (ref đã kiểm vẫn hiện; thiếu input để so ⇒ ``stale_unchecked``).
Pack đã lưu được kiểm lại bằng ĐÚNG luật lúc dựng (``anchor_verify``: receipt route ảnh của đúng take, ``user_approved.by``, trang
phục trong preset đã ghi, tên stage pilot ``h3-<sha>`` luôn bị từ chối) ⇒ lệch ⇒ ``ANCHOR_PACK_INVALID``, ``refs: []``.  ``staged``
(``jjv video anchor-stage``: tên file ở gốc ComfyUI input cho từng slot) được chép nguyên cho panel.  URL ``/view?...`` chỉ cho file
có thật trong ComfyUI input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..comfy.settings import ComfySettings
from ..core.io import read_json, sha256_file
from ..layout.context import Context
from . import anchor_verify
from .anchor_pack import PACK_FILE, PRIORITY, SCHEMA, resolve_recorded
from .ui_wardrobe import view_url

MISSING = "ANCHOR_PACK_MISSING"
INVALID = anchor_verify.INVALID


def _ui_ref(ref: dict[str, Any], settings: ComfySettings, machine: dict | None, problems: list[str]) -> dict[str, Any]:
    path = resolve_recorded(ref["path"], machine)
    verified = path.is_file() and sha256_file(path) == ref["sha256"]
    if not verified:
        problems.append(f"ANCHOR_PACK_REF_CHANGED: {ref['name']} ({ref['sha256'][:12]}) missing or sha256 differs at {path}")
    url = None
    if isinstance(ref.get("file"), str):
        url = view_url(settings.input_dir / ref["file"], settings.input_dir, "input")
    elif isinstance(ref.get("thumb"), dict):
        url = view_url(settings.input_dir / ref["thumb"]["subfolder"] / ref["thumb"]["filename"], settings.input_dir, "input")
    url = url or view_url(path, settings.input_dir, "input") or view_url(path, settings.output_dir, "output")
    return {"name": ref["name"], "character": ref.get("character"), "sha256": ref["sha256"], "approval": ref.get("approval"),
            "source_route": ref.get("source_route"), "chosen": ref.get("chosen"), "verified": verified, "url": url}


def _storyboard(board: dict[str, Any], settings: ComfySettings, machine: dict | None, problems: list[str]) -> dict[str, Any]:
    path = resolve_recorded(board["path"], machine) if isinstance(board.get("path"), str) else None
    ok = None if path is None else (path.is_file() and sha256_file(path) == board.get("sha256"))
    if ok is False:
        problems.append(f"ANCHOR_PACK_REF_CHANGED: storyboard {str(board.get('sha256') or '')[:12]} missing or sha256 differs")
    return {"status": board.get("status"), "sha256": board.get("sha256"), "verified": ok,
            "url": view_url(path, settings.input_dir, "input") if ok else None, "name": path.name if ok else None}


def _ports(wardrobe: Any, pack: dict[str, Any]) -> Any:
    """``wardrobe.refs[].port`` theo ``pack.ref_slots.bound`` (sha256 → slot); không có trong ``bound`` ⇒ giữ null."""
    if not isinstance(wardrobe, dict):
        return wardrobe
    slot_of = {r["sha256"]: r["slot"] for r in (pack.get("ref_slots") or {}).get("bound") or [] if isinstance(r, dict)}
    return {**wardrobe, "refs": [{**r, "port": slot_of.get(r["sha256"])} for r in wardrobe.get("refs") or []]}


def _stale(pack: dict[str, Any], current: dict[str, str | None] | None) -> tuple[list[str], list[str], list[str]]:
    """Nguồn của pack (``sources.<key>.sha256``) so với input hiện tại: (lệch, không so được vì caller không đưa, dòng problem)."""
    sources = pack.get("sources") if isinstance(pack.get("sources"), dict) else {}
    stale, unchecked, lines = [], [], []
    for key, now in (current or {}).items():
        then = (sources.get(key) or {}).get("sha256") if isinstance(sources.get(key), dict) else None
        if now is None:
            unchecked.append(key)
        elif then != now:
            stale.append(key)
            lines.append(f"{key} {str(then or 'missing')[:12]} -> now {now[:12]}")
    return stale, unchecked, lines


def _summary(shot: dict[str, Any], file: Path, pack: dict[str, Any], ctx: Context, settings: ComfySettings,
             current: dict[str, str | None] | None) -> dict[str, Any]:
    problems: list[str] = []
    groups = {role: [_ui_ref(r, settings, ctx.machine, problems) for r in pack.get(f"{role}_refs") or []] for role in PRIORITY}
    board = _storyboard(pack.get("storyboard_anchor") or {}, settings, ctx.machine, problems)
    broken = list(problems)  # file đổi byte / mất ⇒ BROKEN; file nguyên mà sai luật dựng (route, user_approved, preset) ⇒ INVALID
    invalid = anchor_verify.validate_pack(ctx, pack)  # luật dựng chạy lại khi nạp: sha đúng CHƯA đủ (CR-ANCHOR-REFS)
    problems += invalid
    stale, unchecked, lines = _stale(pack, current)
    summary = {"file": str(file), "sha256": sha256_file(file), "status": None if problems else pack.get("status"),
               "context": pack.get("context"), "context_per_character": pack.get("context_per_character"),
               "ready_for_graph": pack.get("ready_for_graph"), **groups, "storyboard": {k: board[k] for k in ("status", "sha256", "verified", "url")},
               "slots": list((pack.get("ref_slots") or {}).get("bound") or []),
               "overflow": list((pack.get("ref_slots") or {}).get("overflow") or []), "stale": stale, "stale_unchecked": unchecked,
               "staged": pack.get("staged"), "staged_at": pack.get("staged_at"), "problems": problems}
    flagged = shot["problems"] + ([f"ANCHOR_PACK_STALE: {shot['id']}: pack built from other inputs ({'; '.join(lines)}); "
                                   "rebuild with jjv video anchor-pack before trusting its slots"] if stale else [])
    if problems:  # pack hỏng / không hợp lệ ⇒ không ảnh nào được hiện, cổng trang phục giữ null
        code = "ANCHOR_PACK_BROKEN" if broken else INVALID
        return {**shot, "refs": [], "anchor_pack": summary, "problems": flagged + [f"{code}: {file}: " + "; ".join(problems)]}
    refs = [{"name": r["name"], "url": r["url"]} for role in PRIORITY for r in groups[role]]
    refs += [{"name": board["name"], "url": board["url"]}] if board["verified"] else []
    return {**shot, "refs": refs, "wardrobe": _ports(shot.get("wardrobe"), pack), "anchor_pack": summary, "problems": flagged}


def _without(shot: dict[str, Any], why: str) -> dict[str, Any]:
    return {**shot, "refs": [], "anchor_pack": None,
            "problems": shot["problems"] + [f"{MISSING}: {shot['id']}: {why}; refs empty (legacy pilot inputs are never shown as references)"]}


def attach_ui(shots: list[dict[str, Any]], anchor_dir: Path | None, ctx: Context, settings: ComfySettings,
              current: dict[str, str | None] | None = None) -> list[dict[str, Any]]:
    """Bản sao ``shots`` với ``refs`` + ``anchor_pack`` từng shot; không pack / pack lạ / pack hỏng ⇒ ``refs: []`` + problem, không bịa.

    ``current`` = {``shotlist``: sha256, ``wardrobe_presets``: sha256 | None} của input lượt này: lệch ``pack.sources`` ⇒
    ``ANCHOR_PACK_STALE`` (ref đã kiểm vẫn hiện; None ⇒ ghi ``stale_unchecked``, không đoán)."""
    result = []
    for shot in shots:
        if anchor_dir is None:
            result.append(_without(shot, "no --anchor-dir given"))
            continue
        file = Path(anchor_dir) / shot["id"] / PACK_FILE
        if not file.is_file():
            result.append(_without(shot, f"no {file}"))
            continue
        pack = read_json(file)
        if not isinstance(pack, dict) or (pack.get("schema"), pack.get("episode_id"), pack.get("domain"), pack.get("shot")) != (
                SCHEMA, ctx.episode_id, ctx.domain_id, shot["id"]):
            problem = f"ANCHOR_PACK_FOREIGN: {file} is not a {SCHEMA} pack of this episode/domain/shot; ignored"
            result.append({**shot, "refs": [], "anchor_pack": {"file": str(file), "status": None, "problems": [problem]},
                           "problems": shot["problems"] + [problem]})
            continue
        result.append(_summary(shot, file, pack, ctx, settings, current))
    return result


__all__ = ["MISSING", "PACK_FILE", "attach_ui"]
