"""Neo trang phục theo context cho ``ui_state`` (``jjv/wardrobe-presets/v1``) — chỉ đọc, không gửi gì, không đoán.

File preset do caller truyền (``domain`` trong file phải bằng domain của episode; code không nêu tên domain, cổng hay ổ
đĩa).  ``contexts`` của file là bộ từ vựng (vd ``cong_truong`` / ``van_phong``); context của shot đọc từ shotlist
(``context`` / ``setting`` / ``location``) và, cho cảnh hai người, ``context_per_character`` ({nhân vật: context}); mỗi giá trị
chuẩn hoá về đúng khoá của file; thiếu, lạ, hoặc không có trong file ⇒ ``WARDROBE_CONTEXT_UNKNOWN`` (từ chối cả shot, hoặc problem
riêng cho nhân vật đó) và KHÔNG gắn gì (``default_context`` của file bị bỏ qua có chủ ý).  Mỗi ref ghi name + sha256 (băm lại
file trên đĩa; lệch ⇒ ``attached: false``) + ``port: null``: cổng graph KHÔNG được đoán ở đây — chỉ ``anchor_pack.ref_slots`` của
shot (nguồn duy nhất) gán cổng, ``anchor_pack_ui`` chép sang.  Cũng chứa :func:`view_url` (URL ``/view?...`` tương đối, chỉ cho
file có thật) dùng chung với ``ui_state``.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from ..comfy.settings import ComfySettings
from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path
from ..layout.context import REPO_ROOT

SCHEMA = "jjv/wardrobe-presets/v1"
CONTEXT_KEYS = ("context", "setting", "location")
PER_CHARACTER_KEY = "context_per_character"
ALIASES = {"cong_truong": ("cong_truong", "cong truong", "công trường", "site", "construction", "construction site"),
           "van_phong": ("van_phong", "van phong", "văn phòng", "office")}
_SHA = re.compile(r"[0-9a-f]{64}")


def view_url(path: Path, root: Path, kind: str) -> str | None:
    """``/view?filename=..[&subfolder=..]&type=kind`` khi ``path`` là file thật dưới ``root``; else None (không bịa URL)."""
    try:
        relative = Path(path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    if not Path(path).is_file():
        return None
    sub = "/".join(relative.parts[:-1])
    return f"/view?filename={relative.name}" + (f"&subfolder={sub}" if sub else "") + f"&type={kind}"


def _norm(text: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).casefold().replace("_", " ").split())


def context_of(row: Mapping[str, Any]) -> str | None:
    """Khoá context (``cong_truong`` …) từ khoá shotlist đầu tiên có giá trị; lạ hoặc thiếu ⇒ None (không suy từ mô tả)."""
    for key in CONTEXT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            wanted = _norm(value)
            return next((name for name, aliases in ALIASES.items() if wanted in {_norm(a) for a in aliases}), None)
    return None


def contexts_of(row: Mapping[str, Any], known: Mapping[str, Any]) -> tuple[str | None, dict[str, str | None], list[str]]:
    """Context của shot + của từng nhân vật (``context_per_character``); giá trị lạ / không có trong ``known`` ⇒ None + problem."""
    raw = row.get(PER_CHARACTER_KEY)
    raw = raw if isinstance(raw, dict) else {}
    per = {str(c): (lambda k: k if k in known else None)(context_of({"context": v})) for c, v in raw.items()}
    problems = [f"WARDROBE_CONTEXT_UNKNOWN: shot {row.get('id')!r} character {c!r} context {raw[c]!r} is unknown or not in the presets "
                "file; nothing attached for that character, never guessed" for c, k in per.items() if k is None]
    return context_of(row), per, problems


def _check_item(item: Any, path: Path, where: str) -> None:
    file = item.get("file") if isinstance(item, dict) else None
    if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip() \
            or not isinstance(file or item.get("path"), str) or not isinstance(item.get("sha256"), str) \
            or not _SHA.fullmatch(item["sha256"]):
        raise Refused(f"{path}: wardrobe preset in {where} needs name, file (or path) and a 64-hex sha256: {item!r}")


def load_anchors(path: Path, domain_id: str) -> dict[str, Any]:
    """Đọc + kiểm hình dạng ``jjv/wardrobe-presets/v1`` của ĐÚNG domain; trả bản sao kèm ``_path``/``_sha256``."""
    path = Path(path)
    if not path.is_file():
        raise Refused(f"WARDROBE_FILE_MISSING: wardrobe presets file is missing: {path}; nothing attached")
    doc = read_json(path)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise Refused(f"{path}: wardrobe presets schema must be {SCHEMA}, got {doc.get('schema') if isinstance(doc, dict) else doc!r}")
    if doc.get("domain") != domain_id:
        raise Refused(f"{path}: wardrobe presets belong to domain {doc.get('domain')!r}, not {domain_id!r}; domains are never mixed")
    contexts = doc.get("contexts")
    if not isinstance(contexts, dict) or not contexts or not all(isinstance(v, list) and v for v in contexts.values()):
        raise Refused(f"{path}: wardrobe presets need a non-empty contexts object of non-empty lists")
    unknown = sorted(k for k in contexts if k not in ALIASES)
    if unknown:
        raise Refused(f"{path}: wardrobe contexts {unknown} are not in the known vocabulary {sorted(ALIASES)}; not guessed")
    for name, items in contexts.items():
        for item in items:
            _check_item(item, path, f"contexts.{name}")
    for item in doc.get("company") or []:
        _check_item(item, path, "company")
    for scene, items in (doc.get("scene_refs") or {}).items():
        for item in items or []:
            _check_item(item, path, f"scene_refs.{scene}")
    return {**doc, "_path": str(path), "_sha256": sha256_file(path)}


def _locate(item: dict[str, Any], settings: ComfySettings, machine: Mapping | None) -> Path:
    """``file`` tương đối ⇒ dưới ComfyUI input (cách LoadImage đọc), rồi repo root; tuyệt đối ⇒ remap legacy roots."""
    given = Path(item.get("file") or item["path"])
    if given.is_absolute():
        return resolve_data_path(given, machine)
    staged = settings.input_dir / given
    return staged if staged.is_file() else resolve_data_path(REPO_ROOT / given, machine)


def _ref(item: dict[str, Any], role: str, context: str | None, character: str | None, settings: ComfySettings,
         machine: Mapping | None) -> dict[str, Any]:
    """``characters: []`` = cả shot (context của shot); ``[C]`` = chỉ nhân vật C (``context_per_character``).  ``port`` luôn null."""
    file = _locate(item, settings, machine)
    verified = file.is_file() and sha256_file(file) == item["sha256"]
    return {"role": role, "name": item["name"], "sha256": item["sha256"], "file": item.get("file") or item.get("path"),
            "path": str(file), "preset_role": item.get("role"), "port": None, "context": context,
            "characters": [character] if character else [], "verified": verified, "attached": verified,
            "url": view_url(file, settings.input_dir, "input")}


def _collect(refs: dict[tuple[str, str], dict], item: dict, role: str, context: str | None, character: str | None,
             settings: ComfySettings, machine: Mapping | None) -> None:
    key = (role, item["sha256"])
    found = refs.get(key)
    if found is None:
        refs[key] = _ref(item, role, context, character, settings, machine)
    elif character and found["characters"] and character not in found["characters"]:  # cùng ảnh, thêm nhân vật; [] đã là cả shot
        refs[key] = {**found, "characters": [*found["characters"], character]}


def attach(row: Mapping[str, Any], anchors: dict[str, Any], settings: ComfySettings, machine: Mapping | None = None) -> dict[str, Any]:
    """Ref trang phục của MỘT shot: preset theo context của shot và/hoặc của từng nhân vật + ``company`` + ``scene_refs``.

    Không context nào dùng được (shot lẫn nhân vật) ⇒ ``refused`` (ghi rõ), ``refs`` rỗng; ``default_context`` không được dùng.
    Nhân vật có context lạ ⇒ problem riêng, các nhân vật khác vẫn gắn.  ``port`` luôn null (xem docstring module)."""
    context, per, problems = contexts_of(row, anchors["contexts"])
    wanted = ([(context, None)] if context in anchors["contexts"] else []) + [(k, c) for c, k in per.items() if k]
    if not wanted:
        why = "has no site/office context in the shotlist" if context is None else f"context {context!r} is not in the presets file"
        return {"context": context, "per_character": per, "refs": [], "problems": problems,
                "refused": f"WARDROBE_CONTEXT_UNKNOWN: shot {row.get('id')!r} {why} (keys {CONTEXT_KEYS} / {PER_CHARACTER_KEY}); "
                           "nothing attached, never guessed (default_context ignored)"}
    scene_refs = anchors.get("scene_refs") or {}
    refs: dict[tuple[str, str], dict] = {}
    for key, character in wanted:
        for item in anchors["contexts"][key]:
            _collect(refs, item, "wardrobe_anchor", key, character, settings, machine)
    for item in anchors.get("company") or []:
        _collect(refs, item, "company_wardrobe", None, None, settings, machine)
    for item in scene_refs.get(str(row.get("id"))) or scene_refs.get(str(row.get("scene"))) or []:
        _collect(refs, item, "scene_reference", None, None, settings, machine)
    rows = list(refs.values())
    problems = problems + [f"WARDROBE_REF_UNVERIFIED: {r['name']} ({r['sha256'][:12]}) missing or sha256 differs at {r['path']}; not attached"
                           for r in rows if not r["verified"]]
    return {"context": context, "per_character": per, "refs": rows, "refused": None, "problems": problems}
