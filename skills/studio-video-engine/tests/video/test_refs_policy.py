"""Chính sách ``refs`` của panel + hai verb ``jjv video anchor-pack|ui-state`` qua entry thật ``bin/jjv.py``.

Luật user 31/10: ảnh tham chiếu hiện cho một shot CHỈ đến từ bộ neo ``jjv/shot-anchor-pack/v1`` đã kiểm sha; ảnh LoadImage của
graph pilot cũ (``h3-<sha>``: character sheet / storyboard cũ, có thể là NGƯỜI KHÁC) không bao giờ trộn vào ``refs`` — chúng nằm
riêng ở ``legacy_refs`` với ``blocked``.  Không pack ⇒ ``refs: []`` + problem.  Cổng trang phục chỉ từ ``pack.ref_slots``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from test_anchor_pack import Library, presets, selection  # noqa: E402
from test_ui_state import EP, ROWS, World, blob, dump, sha  # noqa: E402

from engine.video import anchor_pack, ui_state  # noqa: E402

SKILL = _TESTS.parent
PILOT_SHA = "dcb0789a" * 8  # hình dạng tên file pilot thật: h3-<sha256>.png trong ComfyUI/input
BLOCKED = "NOT_APPROVED_LEGACY_PILOT_INPUT"


def jjv():
    spec = importlib.util.spec_from_file_location("jjv_cli_video_verbs", SKILL / "bin" / "jjv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pilot_receipt(world: World, shot: str) -> Path:
    """Thư mục receipt pilot: preparation.json + graph có LoadImage trỏ ảnh ``h3-<sha>`` đã stage (có URL thật)."""
    staged = blob(world.input / f"h3-{PILOT_SHA}.png", b"pilot-character-sheet")
    folder = world.root / "technical" / "pilot-v001" / shot
    api = world.graph(folder / "workflow.api.json", f"prompt of {shot}", image=staged.name)
    dump(folder / "preparation.json", {"film_id": EP, "shot_id": shot, "status": "PREPARED_NOT_SUBMITTED", "version": "pilot-v001",
                                       "api": {"path": str(api), "sha256": sha(api)}})
    return folder.parent


def rows_with_context() -> list[dict]:
    return [dict(ROWS[0]), {**ROWS[1], "context": "site"}, dict(ROWS[2])]


def write_pack(world: World, lib: Library, out: Path) -> Path:
    code = anchor_pack.main(["--episode", str(world.root), "--machine", str(world.machine), "--shot", "S02_A",
                             "--selection", str(selection(world, lib)), "--shotlist", str(world.draft(ROWS)), "--library", str(lib.dir),
                             "--wardrobe", str(presets(world)), "--thumbs", str(lib.thumbs()), "--out", str(out)])
    assert code == 0
    return out


# ---- verbs qua entry thật ---------------------------------------------------------------------------------
def test_jjv_video_ui_state_and_anchor_pack_help_exit_zero_via_real_entry() -> None:
    for verb in ("ui-state", "anchor-pack"):
        done = subprocess.run([sys.executable, "-I", str(SKILL / "bin" / "jjv.py"), "video", verb, "--help"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert done.returncode == 0, (verb, done.stdout, done.stderr)
        assert f"jjv video {verb}" in done.stdout and "--episode" in done.stdout, (verb, done.stdout)
    assert "--shotlist" in subprocess.run([sys.executable, "-I", str(SKILL / "bin" / "jjv.py"), "video", "ui-state", "-h"],
                                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def test_jjv_video_anchor_pack_then_ui_state_end_to_end(tmp_path, capsys) -> None:
    world = World(tmp_path)
    lib = Library(world)
    packs, out = tmp_path / "packs", tmp_path / "ui.json"
    code = jjv().main(["video", "anchor-pack", "--episode", str(world.root), "--machine", str(world.machine), "--out", str(packs),
                       "--shot", "S02_A", "--selection", str(selection(world, lib)), "--shotlist", str(world.draft(ROWS)),
                       "--library", str(lib.dir), "--wardrobe", str(presets(world))])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["ok"] and printed["episode_id"] == EP and (packs / "S02_A" / anchor_pack.PACK_FILE).is_file()
    code = jjv().main(["video", "ui-state", "--episode", str(world.root), "--machine", str(world.machine),
                       "--shotlist", str(world.draft(ROWS)), "--out", str(out), "--anchor-dir", str(packs)])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["ok"] and printed["out"] == str(out) and sha(out) == printed["sha256"]
    assert json.loads(out.read_text("utf-8"))["sources"]["anchor_dir"] == str(packs)


# ---- refs chỉ từ pack; pilot cũ bị chặn -----------------------------------------------------------------------
def test_refs_come_only_from_the_verified_pack_never_from_pilot_graph_inputs(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    packs = write_pack(world, lib, tmp_path / "packs")
    h3 = pilot_receipt(world, "S02_A")
    pilot_receipt(world, "S03_A")
    document = ui_state.build(world.ctx(), shotlist=world.draft(ROWS), h3_dirs=[h3], anchor_dir=packs)
    by_id = {s["id"]: s for s in document["shots"]}
    s02 = by_id["S02_A"]
    assert s02["status"] == "prompted" and s02["anchor_pack"]["status"] == "candidate"  # receipt pilot vẫn tính trạng thái
    assert all(PILOT_SHA not in (r["url"] or "") and "h3-" not in (r["url"] or "") for r in s02["refs"]), s02["refs"]
    assert {r["name"] for r in s02["refs"]} == {Path(lib.entry("alice", "FACE", 1)["file"]).name,
                                                Path(lib.entry("alice", "ACTION", 0)["file"]).name,
                                                Path(lib.entry("alice", "ACTION", 1)["file"]).name, "vest.png", "helmet.png"}
    assert s02["legacy_refs"] == [{"name": "Ảnh cảnh đã duyệt", "url": f"/view?filename=h3-{PILOT_SHA}.png&type=input", "blocked": BLOCKED}]
    s03 = by_id["S03_A"]  # có receipt pilot nhưng KHÔNG có pack ⇒ không ảnh nào, không bao giờ lấy pilot thay thế
    assert s03["refs"] == [] and s03["anchor_pack"] is None and s03["legacy_refs"][0]["blocked"] == BLOCKED
    assert any(p.startswith("ANCHOR_PACK_MISSING") for p in s03["problems"])
    assert s03["cast"] == ["mother", "alice"] and s02["cast"] == ["alice"]
    plain = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), h3_dirs=[h3])["shots"]}  # không --anchor-dir
    assert all(s["refs"] == [] and s["anchor_pack"] is None for s in plain.values())
    assert all(any(p.startswith("ANCHOR_PACK_MISSING") for p in s["problems"]) for s in plain.values())


def test_broken_pack_shows_no_refs_at_all(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    packs = write_pack(world, lib, tmp_path / "packs")
    (lib.dir / lib.entry("alice", "FACE", 1)["file"]).write_bytes(b"tampered")
    s02 = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), anchor_dir=packs)["shots"]}["S02_A"]
    assert s02["refs"] == [] and s02["anchor_pack"]["status"] is None and any("ANCHOR_PACK_BROKEN" in p for p in s02["problems"])


def test_stale_pack_is_flagged_when_shotlist_or_wardrobe_bytes_changed(tmp_path) -> None:
    """Pack ghi sha của shotlist/wardrobe lúc dựng; input hiện tại khác byte ⇒ problem ANCHOR_PACK_STALE (vẫn hiện ref đã kiểm)."""
    world = World(tmp_path)
    lib = Library(world)
    packs = write_pack(world, lib, tmp_path / "packs")  # dựng với draft(ROWS) + presets(world)
    fresh = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), wardrobe=presets(world), anchor_dir=packs)["shots"]}
    assert fresh["S02_A"]["anchor_pack"]["stale"] == [] and not any("ANCHOR_PACK_STALE" in p for p in fresh["S02_A"]["problems"])
    moved = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(rows_with_context()), wardrobe=presets(world),
                                                  anchor_dir=packs)["shots"]}  # cùng đường dẫn shotlist, byte khác
    s02 = moved["S02_A"]
    assert s02["anchor_pack"]["stale"] == ["shotlist"] and s02["anchor_pack"]["status"] == "candidate" and len(s02["refs"]) == 5
    assert sum(1 for p in s02["problems"] if p.startswith("ANCHOR_PACK_STALE")) == 1 and "shotlist" in [p for p in s02["problems"] if "STALE" in p][0]
    both = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(rows_with_context()), wardrobe=presets(world, approved=True),
                                                 anchor_dir=packs)["shots"]}["S02_A"]  # wardrobe ghi lại ⇒ sha khác
    assert both["anchor_pack"]["stale"] == ["shotlist", "wardrobe_presets"]
    no_wardrobe = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), anchor_dir=packs)["shots"]}["S02_A"]
    assert no_wardrobe["anchor_pack"]["stale"] == [] and no_wardrobe["anchor_pack"]["stale_unchecked"] == ["wardrobe_presets"]  # không --wardrobe ⇒ không so, không đoán


# ---- cổng trang phục: pack.ref_slots là nguồn duy nhất ---------------------------------------------------------
def test_wardrobe_ports_come_from_pack_ref_slots_or_stay_null(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    packs = write_pack(world, lib, tmp_path / "packs")
    pack = json.loads((packs / "S02_A" / anchor_pack.PACK_FILE).read_text("utf-8"))
    slot_of = {row["sha256"]: row["slot"] for row in pack["ref_slots"]["bound"]}
    with_pack = ui_state.build(world.ctx(), shotlist=world.draft(rows_with_context()), wardrobe=presets(world), anchor_dir=packs)
    s02 = {s["id"]: s for s in with_pack["shots"]}["S02_A"]
    ports = {r["name"]: r["port"] for r in s02["wardrobe"]["refs"]}
    assert ports == {"vest.png": slot_of[sha(world.input / "wardrobe" / "vest.png")], "helmet.png": slot_of[sha(world.input / "wardrobe" / "helmet.png")]}
    assert ports["vest.png"] == "ref_images.ref_image_3" and ports["helmet.png"] == "ref_images.ref_image_4"  # sau face(0) body(1,2)
    without = ui_state.build(world.ctx(), shotlist=world.draft(rows_with_context()), wardrobe=presets(world))
    s02 = {s["id"]: s for s in without["shots"]}["S02_A"]
    assert [r["port"] for r in s02["wardrobe"]["refs"]] == [None, None] and s02["refs"] == []
    assert not any("WARDROBE_EXTRA_ANCHORS" in p for p in s02["problems"])  # không còn luật 'một slot mỗi vai' của v004
