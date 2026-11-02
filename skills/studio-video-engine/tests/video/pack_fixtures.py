"""Pack ĐÃ LƯU cho các test staging / nạp lại / H3: dựng bằng chính ``anchor_pack.build`` (thư viện có receipt + preset trang
phục + storyboard tuỳ chọn) rồi ghi ``<tmp>/packs/<shot>/anchor-pack.json``.  Không GPU, không mạng, không asset thật."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _folder in (_HERE, _HERE.parent):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from test_anchor_pack import Library, presets, selection, sha  # noqa: E402
from test_ui_state import EP, ROWS, World, blob, dump  # noqa: E402

from engine.video import anchor_pack  # noqa: E402
from engine.images import library as library_mod  # noqa: E402

SHOT = "S02_A"
BOARD_BYTES = b"board-first-frame"


def storyboard_spec(world: World) -> dict:
    """Storyboard có receipt ảnh route ``comfyui-local`` (candidate, ``ready_for_graph``)."""
    board = blob(world.tmp / "board" / f"{SHOT}.png", BOARD_BYTES)
    receipt = dump(world.tmp / "board" / f"{SHOT}.receipt.json", {
        "schema": "jjv/image-receipt/v1", "episode_id": EP, "domain": world.domain, "route": "comfyui-local",
        "provider": "comfyui-local", "output": {"path": str(board), "sha256": sha(board)}})
    return {"path": str(board), "receipt": str(receipt)}


def _approve_library(lib: Library) -> None:
    """Write current library-mode approval records for fixture takes using the production reader's format."""
    items = library_mod.checklist_items()
    for kinds in lib.entries.values():
        for entries in kinds.values():
            for entry in entries:
                sha256 = entry["sha256"]
                receipt = Path(entry["receipt"])
                checklist = dump(library_mod.review_dir(lib.out, entry["prompt_id"]) / "checklist.json", {
                    "schema": library_mod.CHECKLIST_SCHEMA, "key": entry["prompt_id"], "items": items,
                    "candidates": {sha256: {item: {"status": "pass", "note": "fixture"} for item in items}},
                })
                dump(library_mod.review_dir(lib.out, entry["prompt_id"]) / "approvals" / "approval-v001.json", {
                    "schema": library_mod.APPROVAL_SCHEMA, "prompt_id": entry["prompt_id"], "candidate_sha256": sha256,
                    "receipt": {"path": str(receipt), "sha256": sha(receipt)}, "checklist_path": str(checklist),
                    "status": "accepted_library_image",
                })


def saved_pack(tmp: Path, *, storyboard: bool = False, rows: list[dict] | None = None, approved: bool = False,
               thumbs: bool = True) -> tuple[World, Library, Path]:
    """1 FACE + 1 ACTION + 2 trang phục (+ storyboard khi ``storyboard=True``) ⇒ pack 4 ref bound; trả (world, library, pack)."""
    world = World(tmp)
    lib = Library(world)
    if approved:
        _approve_library(lib)
    characters = [{"character": "alice", "role": "speaker", "face": [lib.entry("alice", "FACE", 1)["sha256"][:12]],
                   "body": [lib.entry("alice", "ACTION", 0)["sha256"][:12]]}]
    board = storyboard_spec(world) if storyboard else "PENDING"
    if approved and isinstance(board, dict):
        board["user_approved"] = {"by": "fixture", "note": "approved fixture storyboard"}
    sel = selection(world, lib, characters=characters, storyboard=board)
    pack = anchor_pack.build(world.ctx(), shot=SHOT, selection=sel, shotlist=world.draft(rows or ROWS), library=lib.dir,
                             wardrobe=presets(world), thumbs=lib.thumbs() if thumbs else None)
    path, _ = anchor_pack.write_pack(pack, Path(tmp) / "packs")
    return world, lib, path


def staged_name(prefix: str, slot: str, sha256: str, ext: str = ".png") -> str:
    """Tên file nạp ở GỐC ComfyUI input (LoadImage không đọc được subfolder — UI lane đo 31/10): ``<prefix>_<ep>_<shot>_<slot>_<sha12>``."""
    short = slot.replace("ref_images.", "").replace(".", "_")
    return f"{prefix}_{EP}_{SHOT}_{short}_{sha256[:12]}{ext}"


__all__ = ["SHOT", "BOARD_BYTES", "saved_pack", "storyboard_spec", "staged_name", "EP", "ROWS", "World", "blob", "dump", "sha",
           "presets"]
