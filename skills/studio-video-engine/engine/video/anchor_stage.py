"""``jjv video anchor-stage``: nạp ảnh GỐC của pack vào GỐC ComfyUI input và ghi ``staged[]`` vào pack — write-once, không GPU.

Luật user 31/10 ("bộ ảnh neo trong video nạp như workflow tạo ảnh"): mỗi ref đã gán slot (``pack.ref_slots.bound``) và storyboard
(khi không pending) được chép nguyên file (sha kiểm trước và sau, KHÔNG phải thumbnail) vào ``<input>/<prefix>_<episode>_<shot>_
<slot>_<sha12>.<ext>``.  Tên PHẲNG ở gốc input vì ``LoadImage`` không liệt kê subfolder (UI lane đo ``/object_info`` 31/10: giá trị
có ``/`` ⇒ "Media input missing"); ``comfy.staging.stage_input``: file đã có thì phải băm đúng, không bao giờ ghi đè.  Rồi pack nhận
``staged: [{slot, role, name, input_subfolder: "", filename, sha256}]`` + ``staged_at`` (các trường khác y nguyên; chạy lại cùng kết
quả ⇒ không ghi lại).  Trước mọi ghi: pack phải hợp lệ theo luật dựng (``anchor_verify``) và không stale (nguồn đã ghi + ``--shotlist``
hiện tại: sha và context của shot).  ``--dry-run`` chỉ in bảng slot → file (``state`` present/missing).  ``prefix`` mặc định = từ
đầu của domain id + ``_anc`` (``--input-prefix`` ghi đè); code không nêu tên domain, nhân vật hay ổ đĩa.
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
from ..comfy.staging import input_state, stage_input
from ..core.errors import EngineError, Refused, exit_code_for
from ..core.io import sha256_file, write_json_atomic
from ..layout.context import Context, load_context
from . import anchor_verify
from .anchor_pack import PACK_FILE
from .anchor_refs import hash_check, resolve_recorded

HELP = "02b: stage every bound pack ref (original bytes, sha-verified) flat into the ComfyUI input root + record staged[] in the pack"
STAGED_KEYS = ("slot", "role", "name", "input_subfolder", "filename", "sha256")
GUIDE_SLOT = "guide.image"
_PATH_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")


def default_prefix(domain_id: str) -> str:
    """``<từ đầu của domain id>_anc``: suy từ dữ liệu, không hardcode tên domain."""
    return f"{str(domain_id).split('_')[0]}_anc"


def _part(text: Any, label: str) -> str:
    if not isinstance(text, str) or not _PATH_PART.fullmatch(text):
        raise Refused(f"unsafe {label}: {text!r}")
    return text


def staged_filename(prefix: str, episode_id: str, shot: str, slot: str, sha256: str, suffix: str) -> str:
    short = str(slot).replace("ref_images.", "").replace(".", "_")
    name = f"{_part(prefix, 'input prefix')}_{_part(episode_id, 'episode id')}_{_part(shot, 'shot')}_{short}_{str(sha256)[:12]}{suffix}"
    return _part(name, "staged file name")


def _ref_of(pack: dict[str, Any], role: str, sha256: str) -> dict[str, Any]:
    hits = [r for r in pack.get(f"{role}_refs") or [] if r.get("sha256") == sha256]
    if len(hits) != 1:
        raise Refused(f"{anchor_verify.INVALID}: slot bound to {str(sha256)[:12]} matches {len(hits)} {role} refs of the pack")
    return hits[0]


def _row(ctx: Context, settings: ComfySettings, prefix: str, pack: dict[str, Any], slot: str, role: str, name: str,
         recorded: str, sha256: str) -> dict[str, Any]:
    source = resolve_recorded(recorded, ctx.machine)
    hash_check(source, sha256, f"{role} {name}")
    filename = staged_filename(prefix, pack["episode_id"], pack["shot"], slot, sha256, source.suffix.lower())
    _, state = input_state(settings.input_dir, filename, sha256)  # present ⇒ phải băm đúng, else Refused
    return {"slot": slot, "role": role, "name": name, "input_subfolder": "", "filename": filename, "sha256": sha256,
            "state": state, "source": str(source)}


def plan(ctx: Context, pack: dict[str, Any], settings: ComfySettings, prefix: str) -> list[dict[str, Any]]:
    """Một hàng mỗi slot đã gán (thứ tự ``ref_slots.bound``) + storyboard ở ``guide.image`` khi không pending; không ghi gì."""
    rows = []
    for bound in (pack.get("ref_slots") or {}).get("bound") or []:
        ref = _ref_of(pack, bound["role"], bound["sha256"])
        rows.append(_row(ctx, settings, prefix, pack, bound["slot"], bound["role"], ref["name"], ref["path"], bound["sha256"]))
    board = pack.get("storyboard_anchor") or {}
    if board.get("status") != "pending":
        rows.append(_row(ctx, settings, prefix, pack, GUIDE_SLOT, "storyboard", Path(str(board.get("path"))).name,
                         str(board.get("path")), str(board.get("sha256"))))
    return rows


def stage(ctx: Context, pack_path: Path, settings: ComfySettings, *, input_prefix: str | None = None,
          shotlist: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Kiểm (hợp lệ, không stale, sha nguồn, file có sẵn trong input băm đúng) ⇒ nạp các file còn thiếu ⇒ ghi ``staged`` vào pack."""
    pack_path = Path(pack_path)
    pack = anchor_verify.load_pack(ctx, pack_path)
    unchecked = anchor_verify.require_fresh(ctx, pack, shotlist=shotlist, settings=settings)  # stale trước: nguồn đổi = dựng lại
    anchor_verify.require_valid(ctx, pack)
    rows = plan(ctx, pack, settings, input_prefix or default_prefix(ctx.domain_id))
    public = [{key: row[key] for key in STAGED_KEYS} for row in rows]
    result = {"pack": str(pack_path), "shot": pack["shot"], "dry_run": dry_run, "stale_unchecked": unchecked,
              "overflow": [r.get("name") for r in (pack.get("ref_slots") or {}).get("overflow") or []]}
    if not dry_run:
        for row in rows:
            if row["state"] == "missing":
                stage_input(Path(row["source"]), settings.input_dir, row["filename"], row["sha256"])
                row["state"] = "linked"
    unchanged = pack.get("staged") == public
    if not dry_run and not unchanged:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_json_atomic(pack_path, {**pack, "staged": public, "staged_at": stamp}, mode="utf8")
    return {**result, "pack_sha256": sha256_file(pack_path), "unchanged": unchanged,
            "staged": [{**row, "state": raw["state"]} for row, raw in zip(public, rows)]}


# ---- CLI ------------------------------------------------------------------------------------------------
def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--shot", required=True)
    parser.add_argument("--input-prefix", default=None, help="file name prefix in the ComfyUI input root (default: <domain first word>_anc)")
    parser.add_argument("--shotlist", default=None, help="CURRENT shotlist to compare against the pack (sha + context); omitted = unchecked")
    parser.add_argument("--dry-run", action="store_true", help="print slot -> file (present/missing); write nothing")


def run(ctx: Context, args: argparse.Namespace) -> dict[str, Any]:
    pack_path = Path(args.out) / args.shot / PACK_FILE
    return stage(ctx, pack_path, settings_from_machine(ctx.machine), input_prefix=args.input_prefix,
                 shotlist=Path(args.shotlist) if args.shotlist else None, dry_run=bool(args.dry_run))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=HELP)
    parser.add_argument("--episode", required=True, help="episode.json path, episode root or slug")
    parser.add_argument("--out", required=True, help=f"anchor-pack folder: <out>/<shot>/{PACK_FILE}")
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


__all__ = ["HELP", "STAGED_KEYS", "GUIDE_SLOT", "default_prefix", "staged_filename", "plan", "stage", "add_arguments", "run", "main"]

if __name__ == "__main__":
    sys.exit(main())
