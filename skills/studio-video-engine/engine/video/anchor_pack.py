"""``jjv/shot-anchor-pack/v1``: bộ neo ảnh của MỘT shot cho graph video — chỉ đọc nguồn, không GPU, không đoán.

Luật user 31/10: mỗi cảnh ra video phải neo bằng ảnh ĐÃ TẠO từ luồng ảnh (Codex hoặc ComfyUI local) của nhân vật — mặt
(FACE), dáng toàn thân / sinh hoạt (ACTION), trang phục theo bối cảnh, bối cảnh (tuỳ chọn) và storyboard (khung hình đầu)
cũng do luồng ảnh tạo từ chính bộ neo đó.  Không bao giờ thay bằng file casting/storyboard cũ: FACE/ACTION chỉ chọn được
qua INDEX của thư viện (file + sha256 + receipt có route); storyboard phải có receipt ảnh hoặc được user đánh dấu duyệt rõ;
trang phục đọc từ preset ``jjv/wardrobe-presets/v1`` theo context của shot và ``context_per_character`` (``ui_wardrobe``, không
đoán context); bối cảnh (``location[]``) theo cùng luật storyboard: receipt ảnh của đúng file HOẶC ``user_approved`` (``anchor_refs``).
Thiếu ô bắt buộc hay lệch sha ⇒ Refused, không ghi gì.  Mọi đường dẫn do caller truyền; code không nêu tên domain, nhân vật hay ổ đĩa.

Selection ``jjv/shot-anchor-selection/v1`` (viết tay, nhỏ): ``shot``, ``context``, ``characters[] {character, role?, face[]?,
body[]?}`` (phần tử = 12+ hex đầu sha256 hoặc tên file trong INDEX; bỏ trống ⇒ ảnh đầu của INDEX, ghi ``chosen: default``),
``location[]?`` ({name, path, sha256, receipt? | user_approved?}), ``storyboard`` = ``"PENDING"`` | {path, receipt} | {path, sha256,
user_approved {by, note}}.  CLI: ``python -m engine.video.anchor_pack …`` hoặc ``jjv video anchor-pack --episode E --out DIR --shot S
--selection F --shotlist F --library DIR --wardrobe F [--thumbs MANIFEST] [--ref-slots N] [--library-out DIR]`` ⇒
``<out>/<shot>/anchor-pack.json`` (temp + os.replace); ``cli.py`` gọi ``add_arguments`` rồi ``run(ctx, args)``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from ..comfy.settings import ComfySettings, settings_from_machine
from ..core.errors import EngineError, Refused, exit_code_for
from ..core.io import read_json, sha256_file, write_json_atomic
from ..images import library
from ..layout.context import Context, load_context
from . import ui_wardrobe
from .anchor_refs import RECEIPT_SCHEMAS, file_ref as _file_ref, hash_check as _hash_check, location_refs, rel as _rel, \
    resolve_recorded, route_of as _route, storyboard_ref, wardrobe_refs

SCHEMA = "jjv/shot-anchor-pack/v1"
SELECTION_SCHEMA = "jjv/shot-anchor-selection/v1"
PACK_FILE = "anchor-pack.json"
INDEX_FILE = "INDEX.json"
HELP = "02: build the jjv/shot-anchor-pack/v1 of ONE shot from library images with receipts (read-only; never GPU)"
PRIORITY = ("face", "body", "wardrobe", "location")
KIND_OF = {"face": "FACE", "body": "ACTION"}
DEFAULT_SLOTS = 9  # MiniMaxH3ReferenceToVideo.ref_images: autogrow prefix ref_image_, min 0, max 9 (đo /object_info 31/10)
SELECTION_KEYS = ("schema", "episode_id", "shot", "context", "chosen_by", "comment", "characters", "location", "storyboard")
CHARACTER_KEYS = ("character", "role", "face", "body")
LOCATION_KEYS = ("name", "path", "sha256", "receipt", "user_approved")
STORYBOARD_KEYS = ("path", "sha256", "receipt", "user_approved")
_HEX = re.compile(r"[0-9a-f]{12,64}")


# ---- helpers (đường dẫn / sha / receipt dùng chung nằm ở anchor_refs) ----------------------------------------
def _only_keys(row: Any, allowed: tuple[str, ...], where: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise Refused(f"{where}: must be an object")
    extra = sorted(set(row) - set(allowed))
    if extra:
        raise Refused(f"{where}: unknown keys {extra} (allowed {list(allowed)}; shas come from receipts, never typed by hand)")
    return row


# ---- selection / library ------------------------------------------------------------------------------
def load_selection(ctx: Context, path: Path, shot: str) -> dict[str, Any]:
    doc = _only_keys(read_json(path), SELECTION_KEYS, Path(path).name)
    if doc.get("schema") != SELECTION_SCHEMA:
        raise Refused(f"{Path(path).name}: not a {SELECTION_SCHEMA} document")
    if doc.get("episode_id") != ctx.episode_id or doc.get("shot") != shot:
        raise Refused(f"{Path(path).name}: selection is for {doc.get('episode_id')!r}/{doc.get('shot')!r}, not {ctx.episode_id!r}/{shot!r}")
    characters = doc.get("characters")
    if not isinstance(characters, list):
        raise Refused(f"{shot}: selection needs a characters list (who is in this shot; [] = prop-only shot)")
    if not characters and doc.get("storyboard", "PENDING") == "PENDING":
        raise Refused(f"PROP_ONLY_NEEDS_STORYBOARD: {shot}: characters [] has no face/body to anchor on; it needs a non-PENDING storyboard guide")
    for row in characters:
        _only_keys(row, CHARACTER_KEYS, f"{shot} characters[]")
        if not isinstance(row.get("character"), str) or not row["character"]:
            raise Refused(f"{shot}: every characters[] row needs a character id")
    for row in doc.get("location") or []:
        _only_keys(row, LOCATION_KEYS, f"{shot} location[]")
    board = doc.get("storyboard", "PENDING")
    if board != "PENDING":
        _only_keys(board, STORYBOARD_KEYS, f"{shot} storyboard")
    return doc


def load_index(library_dir: Path) -> tuple[Path, dict[str, Any]]:
    path = Path(library_dir) if Path(library_dir).is_file() else Path(library_dir) / INDEX_FILE
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("characters"), dict):
        raise Refused(f"{path}: library index needs a characters object ({{<character>: {{FACE: [...], ACTION: [...]}}}})")
    return path, doc


def _pick(entries: list[dict], token: str, label: str) -> dict[str, Any]:
    wanted = str(token).strip()
    low = wanted.lower()
    hits = [e for e in entries if isinstance(e, dict) and (
        (_HEX.fullmatch(low) and str(e.get("sha256", "")).startswith(low))
        or Path(str(e.get("file", ""))).name == wanted or Path(str(e.get("file", ""))).stem == wanted)]
    if len(hits) != 1:
        raise Refused(f"NOT_IN_LIBRARY: {label}: {wanted!r} matches {len(hits)} index entries (need exactly one; "
                      "a casting/legacy file outside the library index is never used)")
    return hits[0]


def _approval(receipt: Path, prompt_id: str, library_out: Path | None, sha256: str) -> tuple[str, str | None]:
    out = Path(library_out) if library_out else receipt.parents[2]
    try:
        found = library.current_approval(out, prompt_id)
    except EngineError:
        found = None
    if isinstance(found, dict) and found.get("candidate_sha256") == sha256:
        return "approved", found.get("path")
    return "candidate", None


def _thumb(thumbs: dict[str, dict] | None, sha: str, settings: ComfySettings, problems: list[str]) -> dict[str, str] | None:
    row = (thumbs or {}).get(sha)
    if row is None:
        return None
    file = settings.input_dir / row["subfolder"] / row["filename"]
    if file.is_file() and sha256_file(file) == row["sha256"]:
        return row
    problems.append(f"THUMB_UNVERIFIED: thumbnail {row['subfolder']}/{row['filename']} missing or sha256 differs; no URL for {sha[:12]}")
    return None


def _library_ref(ctx: Context, index_dir: Path, character: str, role: str, entry: dict, chosen: str, thumbs: dict | None,
                 settings: ComfySettings, library_out: Path | None, problems: list[str]) -> dict[str, Any]:
    label = f"{character} {KIND_OF[role]} {entry.get('file')}"
    for key in ("file", "sha256", "receipt"):
        if not isinstance(entry.get(key), str):
            raise Refused(f"{label}: index entry needs {key!r}")
    path = index_dir / entry["file"]
    _hash_check(path, entry["sha256"], label)
    receipt_path = resolve_recorded(entry["receipt"], ctx.machine)
    if not receipt_path.is_file():
        raise Refused(f"RECEIPT_MISSING: {label}: {receipt_path}")
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema") not in RECEIPT_SCHEMAS:
        raise Refused(f"{label}: {receipt_path.name} is not an image receipt {RECEIPT_SCHEMAS}")
    if (receipt.get("output") or {}).get("sha256") != entry["sha256"] or receipt.get("prompt_id") != entry.get("prompt_id"):
        raise Refused(f"{label}: receipt {receipt_path.name} is for another take/prompt_id than the index entry")
    raw, route = _route(receipt, label)
    approval, record = _approval(receipt_path, str(entry.get("prompt_id")), library_out, entry["sha256"])
    return {"character": character, "role": role, "kind": KIND_OF[role], "name": Path(entry["file"]).name, "path": _rel(path),
            "sha256": entry["sha256"], "prompt_id": entry.get("prompt_id"), "rev": entry.get("rev"), "chosen": chosen,
            "route": raw, "source_route": route, "receipt": _file_ref(receipt_path), "approval": approval, "approval_record": record,
            "thumb": _thumb(thumbs, entry["sha256"], settings, problems)}


def _character_refs(ctx: Context, index_dir: Path, index: dict, row: dict, role: str, **kw: Any) -> list[dict[str, Any]]:
    character, kind = row["character"], KIND_OF[role]
    entries = ((index["characters"].get(character) or {}).get(kind)) or []
    if not entries:
        raise Refused(f"{role.upper()}_MISSING: {character} has no {kind} images in the library index; nothing substituted")
    tokens = row.get(role)
    if tokens is None:
        approved = []
        states = []
        for entry in entries:
            receipt_text = entry.get("receipt") if isinstance(entry, dict) else None
            prompt_id = entry.get("prompt_id") if isinstance(entry, dict) else None
            sha = entry.get("sha256") if isinstance(entry, dict) else None
            if not isinstance(receipt_text, str) or not isinstance(prompt_id, str) or not isinstance(sha, str):
                states.append((entry, "candidate"))
                continue
            receipt_path = resolve_recorded(receipt_text, ctx.machine)
            status, _ = _approval(receipt_path, prompt_id, kw.get("library_out"), sha)
            states.append((entry, status))
            if status == "approved":
                approved.append(entry)
        if not approved:
            candidates = ", ".join(
                f"{Path(str(entry.get('file', '<unknown>'))).name} (sha256={str(entry.get('sha256', ''))[:12]}, "
                f"prompt_id={entry.get('prompt_id')}, {status})"
                for entry, status in states
            )
            first_receipt = next((resolve_recorded(e["receipt"], ctx.machine) for e in entries
                                  if isinstance(e, dict) and isinstance(e.get("receipt"), str)), None)
            out = Path(kw.get("library_out")) if kw.get("library_out") else (first_receipt.parents[2] if first_receipt else "<library-out>")
            raise Refused(f"ANCHOR_NOT_APPROVED: {character} {kind} has no currently approved image; candidates: {candidates}. "
                          "Approve the selected take with `jjv images approve --episode "
                          f"{ctx.episode_id} --out <images-out> --library-out {out} --prompt-id <prompt_id> "
                          "--sha <sha256> --reviewer <name> --scope character-reference`.")
        return [_library_ref(ctx, index_dir, character, role, approved[0], "default-approved", **kw)]
    if not isinstance(tokens, list) or not tokens or not all(isinstance(t, str) and t.strip() for t in tokens):
        raise Refused(f"{character}: {role} must be a non-empty list of sha prefixes or index file names (or absent = default)")
    return [_library_ref(ctx, index_dir, character, role, _pick(entries, t, f"{character} {kind}"), "selection", **kw) for t in tokens]


# ---- wardrobe / location / storyboard: anchor_refs (receipt ảnh HOẶC user_approved; sha đúng chưa đủ) ---------------
def assign_slots(face: list, body: list, wardrobe: list, location: list, max_slots: int, problems: list[str]) -> dict[str, Any]:
    """Thứ tự ưu tiên cố định face > body > wardrobe > location; quá ``max_slots`` ⇒ ``overflow`` (slot None), không bỏ im lặng."""
    ordered = [(role, ref) for role, refs in zip(PRIORITY, (face, body, wardrobe, location)) for ref in refs]
    rows = [{"role": role, "name": ref["name"], "sha256": ref["sha256"], "slot": f"ref_images.ref_image_{i}" if i < max_slots else None}
            for i, (role, ref) in enumerate(ordered)]
    overflow = [r for r in rows if r["slot"] is None]
    if overflow:
        problems.append(f"REF_SLOTS_OVERFLOW: {len(ordered)} refs for {max_slots} ref_images slots; priority face > body > wardrobe "
                        f"> location leaves {[r['name'] for r in overflow]} unbound (mute those loaders or drop a lower-priority ref)")
    return {"max_slots": max_slots, "priority": list(PRIORITY), "bound": [r for r in rows if r["slot"]], "overflow": overflow,
            "storyboard": "guide.image"}


# ---- build / write --------------------------------------------------------------------------------------
def _shot_row(ctx: Context, shotlist: Path, shot: str, settings: ComfySettings) -> dict[str, Any]:
    from . import ui_state  # import tại chỗ: ui_state nhập module này để gắn pack vào trạng thái panel

    _, rows = ui_state.load_shotlist(ctx, Path(shotlist), settings)
    found = [r for r in rows if r["id"] == shot]
    if len(found) != 1:
        raise Refused(f"UNKNOWN_SHOT: {shot} is not in {shotlist}")
    return found[0]


def _shot_characters(shotlist: Path, row: dict[str, Any]) -> set[str]:
    """Tên + ``character_id`` của người trong shot: speaker/refs của hàng, cộng ``character_id`` mà bảng ``character_references`` CỦA CHÍNH
    shotlist gán cho role/tên đó (script gọi người nói là role, thư viện gọi là CHAR_XX); không có bảng ⇒ chỉ tên thô, không đoán."""
    names = {r["name"] for r in row.get("refs") or []} | ({row["speaker"]} if row.get("speaker") else set())
    table = read_json(shotlist).get("character_references")
    for role, entry in (table.items() if isinstance(table, dict) else []):
        if isinstance(entry, dict) and isinstance(entry.get("character_id"), str) and (
                role in names or entry.get("source_role") in names or entry.get("bible_name") in names):
            names.add(entry["character_id"])
    return names


def _load_thumbs(path: Path | None) -> dict[str, dict] | None:
    if path is None:
        return None
    doc = read_json(path)
    rows = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise Refused(f"{path}: thumbs manifest needs items[] with subfolder, filename, source_sha256, thumb_sha256")
    return {r["source_sha256"]: {"subfolder": r["subfolder"], "filename": r["filename"], "sha256": r["thumb_sha256"]}
            for r in rows if isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ("subfolder", "filename", "source_sha256", "thumb_sha256"))}


def build(ctx: Context, *, shot: str, selection: Path, shotlist: Path, library: Path, wardrobe: Path | None = None, thumbs: Path | None = None,
          ref_slots: int = DEFAULT_SLOTS, library_out: Path | None = None) -> dict[str, Any]:
    """Pack của ``shot``; không ghi gì.  Mọi từ chối xảy ra trước mọi ghi."""
    settings = settings_from_machine(ctx.machine)
    row = _shot_row(ctx, shotlist, shot, settings)
    spec = load_selection(ctx, Path(selection), shot)
    context = spec.get("context") if isinstance(spec.get("context"), str) else None
    if row.get("context") and context and row["context"] != ui_wardrobe.context_of({"context": context}):
        raise Refused(f"CONTEXT_CONFLICT: {shot}: shotlist says {row['context']!r}, selection says {context!r}")
    context = row.get("context") or (ui_wardrobe.context_of({"context": context}) if context else None)
    per_character = row.get(ui_wardrobe.PER_CHARACTER_KEY) if isinstance(row.get(ui_wardrobe.PER_CHARACTER_KEY), dict) else {}
    if not spec["characters"] and (row.get("speaker") or row.get("refs")):
        raise Refused(f"PROP_ONLY_SHOT_HAS_CHARACTERS: {shot}: selection says characters [] but the shotlist row names speaker "
                      f"{row.get('speaker')!r} / refs {[r.get('name') if isinstance(r, dict) else r for r in row.get('refs') or []]}; "
                      "a prop-only pack is for a shot with nobody in it")
    if spec["characters"] and wardrobe is None:
        raise Refused(f"WARDROBE_PRESETS_REQUIRED: {shot}: characters are in the shot, so --wardrobe presets are required")
    if spec["characters"] and context is None and not per_character:
        raise Refused(f"WARDROBE_CONTEXT_UNKNOWN: {shot}: neither the shotlist (context / {ui_wardrobe.PER_CHARACTER_KEY}) nor the "
                      "selection names a known context; never guessed")
    index_path, index = load_index(Path(library))
    in_shot = _shot_characters(Path(shotlist), row)
    absent = [c["character"] for c in spec["characters"] if c["character"] not in in_shot]
    if absent:
        raise Refused(f"CHARACTER_NOT_IN_SHOT: {shot}: {absent} are not among the shot's refs/speaker {sorted(in_shot)}")
    problems: list[str] = []
    kw = {"thumbs": _load_thumbs(Path(thumbs) if thumbs else None), "settings": settings, "library_out": library_out, "problems": problems}
    face = [r for c in spec["characters"] for r in _character_refs(ctx, index_path.parent, index, c, "face", **kw)]
    body = [r for c in spec["characters"] for r in _character_refs(ctx, index_path.parent, index, c, "body", **kw)]
    clothes = (wardrobe_refs(ctx, Path(wardrobe), shot, row.get("scene"), context, per_character, settings)
               if spec["characters"] else [])  # shot chỉ có đạo cụ: không ai mặc ⇒ không trang phục
    places = location_refs(ctx, list(spec.get("location") or []), shot,
                           approval_lookup=lambda receipt, pid, sha: _approval(receipt, pid, library_out, sha))
    board = storyboard_ref(ctx, spec.get("storyboard", "PENDING"), shot)
    if int(ref_slots) < 1:
        raise Refused(f"--ref-slots must be >= 1, got {ref_slots}")
    slots = assign_slots(face, body, clothes, places, int(ref_slots), problems)
    # Wardrobe refs are recipe-owned presets: anchor_verify proves their membership in the recorded preset
    # and sha, so they do not need a separate character-image approval record.
    approval_required = face + body + places
    not_ready_reasons = [f"ANCHOR_NOT_APPROVED: {r['role']} {r['name']} sha256={r['sha256']} needs a current, sha-matched image approval"
                         for r in approval_required if r.get("approval") != "approved"]
    if board.get("status") != "approved":
        not_ready_reasons.append(f"STORYBOARD_NOT_APPROVED: status={board.get('status')}")
    status = "approved" if not not_ready_reasons else "candidate"
    characters = [{"character": c["character"], "role": c.get("role"), "face": [r["sha256"] for r in face if r["character"] == c["character"]],
                   "body": [r["sha256"] for r in body if r["character"] == c["character"]]} for c in spec["characters"]]
    return {"schema": SCHEMA, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "episode_id": ctx.episode_id,
            "domain": ctx.domain_id, "shot": shot, "scene": row.get("scene"), "speaker": row.get("speaker"), "context": context,
            ui_wardrobe.PER_CHARACTER_KEY: per_character or None, "chosen_by": spec.get("chosen_by"), "characters": characters, "face_refs": face, "body_refs": body, "wardrobe_refs": clothes,
            "location_refs": places, "storyboard_anchor": board, "ref_slots": slots, "status": status,
            "ready_for_graph": status == "approved", "not_ready_reasons": not_ready_reasons,
            "sources": {"selection": _file_ref(Path(selection)), "shotlist": _file_ref(Path(shotlist)), "library_index": _file_ref(index_path),
                        "wardrobe_presets": _file_ref(Path(wardrobe)) if wardrobe else None, "thumbs": _file_ref(Path(thumbs)) if thumbs else None},
            "problems": problems}


def write_pack(pack: dict[str, Any], out: Path) -> tuple[Path, str]:
    path = Path(out) / pack["shot"] / PACK_FILE
    return path, write_json_atomic(path, pack, mode="utf8")


# ---- CLI ------------------------------------------------------------------------------------------------
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--shot", required=True)
    parser.add_argument("--selection", required=True, help=f"{SELECTION_SCHEMA} of this shot (who, which library images, context)")
    parser.add_argument("--shotlist", required=True, help="jjv/script/v1 or jjv/shotlist-draft/v1 of this episode")
    parser.add_argument("--library", required=True, help=f"by-character library folder holding {INDEX_FILE} (or the index file)")
    parser.add_argument("--wardrobe", default=None, help="jjv/wardrobe-presets/v1 of this domain (context -> refs); required unless characters is []")
    parser.add_argument("--thumbs", default=None, help="thumbnail manifest (items[] subfolder/filename/source_sha256/thumb_sha256) under ComfyUI input")
    parser.add_argument("--ref-slots", type=int, default=DEFAULT_SLOTS, help=f"ref_images slots of the video node (default {DEFAULT_SLOTS})")
    parser.add_argument("--library-out", default=None, help="library submit folder holding _review/ (default: derived from each receipt path)")


def run(ctx: Context, args: argparse.Namespace) -> dict[str, Any]:
    pack = build(ctx, shot=args.shot, selection=Path(args.selection), shotlist=Path(args.shotlist), library=Path(args.library),
                 wardrobe=Path(args.wardrobe) if args.wardrobe else None, thumbs=Path(args.thumbs) if args.thumbs else None, ref_slots=args.ref_slots,
                 library_out=Path(args.library_out) if args.library_out else None)
    path, digest = write_pack(pack, Path(args.out))
    return {"pack": str(path), "sha256": digest, "shot": pack["shot"], "status": pack["status"], "ready_for_graph": pack["ready_for_graph"],
            "counts": {role: len(pack[f"{role}_refs"]) for role in PRIORITY}, "storyboard": pack["storyboard_anchor"]["status"],
            "slots": [s["slot"] for s in pack["ref_slots"]["bound"]], "overflow": [s["name"] for s in pack["ref_slots"]["overflow"]],
            "not_ready_reasons": pack["not_ready_reasons"],
            "problems": pack["problems"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=HELP)
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help=f"folder: <out>/<shot>/{PACK_FILE} (temp + os.replace)")
    parser.add_argument("--machine", default=None, help=argparse.SUPPRESS)
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        ctx = load_context(args.episode, args.machine)
        result = run(ctx, args)
    except EngineError as error:
        print(json.dumps({"ok": False, "error": str(error)}))  # ASCII-safe: console có thể là cp1252
        return exit_code_for(error)
    print(json.dumps({"ok": True, "episode_id": ctx.episode_id, "domain": ctx.domain_id, **result}, indent=2))
    return 0


__all__ = ["SCHEMA", "SELECTION_SCHEMA", "PACK_FILE", "PRIORITY", "HELP", "build", "write_pack", "resolve_recorded", "add_arguments",
           "run", "main"]

if __name__ == "__main__":
    sys.exit(main())
