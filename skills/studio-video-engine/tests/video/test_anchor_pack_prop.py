"""Shot chỉ có đạo cụ (``characters: []``): pack neo bằng storyboard đã duyệt, không face/body/wardrobe — mọi luật cũ còn nguyên.

Thế giới giả dùng chung với ``test_anchor_pack``; không GPU, không mạng.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _folder in (_HERE, _HERE.parent):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from test_anchor_pack import Library, approved_reader, blob, dump, presets, selection, sha  # noqa: E402
from test_ui_state import EP, ROWS, World  # noqa: E402

from engine.comfy.settings import settings_from_machine  # noqa: E402
from engine.core.errors import Refused  # noqa: E402
from engine.video import anchor_pack, anchor_stage, anchor_verify  # noqa: E402

PROP = "SCENE_01"


def prop_selection(world: World, board: Path, **over) -> Path:
    body = {"schema": "jjv/shot-anchor-selection/v1", "episode_id": EP, "shot": PROP, "chosen_by": "test", "characters": [],
            "storyboard": {"path": str(board), "sha256": sha(board), "user_approved": {"by": "Kim", "note": "duyệt tay"}}, **over}
    return dump(world.tmp / "prop-selection.json", body)


def build_prop(world: World, lib: Library, sel: Path, **kw):
    return anchor_pack.build(world.ctx(), shot=PROP, selection=sel, shotlist=world.draft(ROWS), library=lib.dir, **kw)


def test_prop_only_shot_builds_from_a_guide_without_characters_or_wardrobe(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"helmet-on-table")
    pack = build_prop(world, Library(world), prop_selection(world, board))
    assert pack["characters"] == [] and pack["face_refs"] == [] and pack["body_refs"] == [] and pack["wardrobe_refs"] == []
    assert pack["context"] is None and pack["storyboard_anchor"]["status"] == "approved" and pack["storyboard_anchor"]["sha256"] == sha(board)
    assert pack["ready_for_graph"] is True and pack["status"] == "approved" and pack["ref_slots"]["bound"] == [] and pack["problems"] == []
    assert pack["sources"]["wardrobe_presets"] is None
    assert anchor_verify.validate_pack(world.ctx(), pack) == []


def test_prop_only_shot_accepts_an_approved_location_prop_ref(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"helmet-on-table")
    prop = blob(tmp_path / "props" / "table.png", b"table")
    sel = prop_selection(world, board, location=[{"name": "table", "path": str(prop), "sha256": sha(prop), "user_approved": {"by": "Kim"}}])
    pack = build_prop(world, Library(world), sel)
    assert [r["role"] for r in pack["ref_slots"]["bound"]] == ["location"] and pack["location_refs"][0]["sha256"] == sha(prop)
    assert anchor_verify.validate_pack(world.ctx(), pack) == []


def test_prop_only_shot_stages_only_the_guide(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"helmet-on-table")
    pack = build_prop(world, Library(world), prop_selection(world, board))
    path, _ = anchor_pack.write_pack(pack, tmp_path / "packs")
    rows = anchor_stage.plan(world.ctx(), pack, settings_from_machine(world.ctx().machine), "x_anc")
    assert [(r["slot"], r["role"]) for r in rows] == [("guide.image", "storyboard")] and path.is_file()


def test_prop_only_shot_still_needs_a_guide(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"helmet-on-table")
    with pytest.raises(Refused, match="PROP_ONLY_NEEDS_STORYBOARD"):
        build_prop(world, Library(world), prop_selection(world, board, storyboard="PENDING"))


def test_missing_or_non_list_characters_is_still_refused(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"x")
    lib = Library(world)
    sel = prop_selection(world, board)
    doc = {k: v for k, v in __import__("json").loads(sel.read_text("utf-8")).items() if k != "characters"}
    with pytest.raises(Refused, match="characters"):
        build_prop(world, lib, dump(sel, doc))
    with pytest.raises(Refused, match="characters"):
        build_prop(world, lib, dump(sel, {**doc, "characters": None}))


def test_characters_present_still_require_wardrobe_context_and_library(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    with pytest.raises(Refused, match="WARDROBE"):  # không có preset ⇒ không có trang phục ⇒ Refused, không bỏ qua
        anchor_pack.build(world.ctx(), shot="S02_A", selection=selection(world, lib), shotlist=world.draft(ROWS), library=lib.dir)
    with pytest.raises(Refused, match="WARDROBE_CONTEXT_UNKNOWN"):
        anchor_pack.build(world.ctx(), shot="S02_A", selection=selection(world, lib, context=None), shotlist=world.draft(ROWS),
                          library=lib.dir, wardrobe=presets(world))
    with pytest.raises(Refused, match="NOT_IN_LIBRARY"):
        anchor_pack.build(world.ctx(), shot="S02_A", selection=selection(world, lib, characters=[{"character": "alice", "face": ["deadbeefdead"]}]),
                          shotlist=world.draft(ROWS), library=lib.dir, wardrobe=presets(world))


def test_legacy_staged_guide_name_is_still_refused_for_prop_shot(tmp_path) -> None:
    world, board = World(tmp_path), blob(tmp_path / "board" / "SCENE_01.png", b"helmet-on-table")
    pack = build_prop(world, Library(world), prop_selection(world, board))
    legacy = blob(tmp_path / "board" / "h3-0123456789ab.png", b"helmet-on-table")
    bad = {**pack, "storyboard_anchor": {**pack["storyboard_anchor"], "path": str(legacy), "name": legacy.name}}
    assert any("h3-<sha>" in p for p in anchor_verify.validate_pack(world.ctx(), bad))


def test_empty_characters_is_refused_when_the_shot_row_has_a_speaker_or_refs(tmp_path) -> None:
    """CR-ANCHOR-PROP-ONLY: ``characters: []`` chỉ hợp lệ khi shotlist cũng nói shot không có người; không thì lách được wardrobe."""
    world, board = World(tmp_path), blob(tmp_path / "board" / "S02_A.png", b"board")
    lib = Library(world)
    sel = prop_selection(world, board, shot="S02_A")
    with pytest.raises(Refused, match="PROP_ONLY_SHOT_HAS_CHARACTERS"):  # S02_A: speaker alice + refs [alice]
        anchor_pack.build(world.ctx(), shot="S02_A", selection=sel, shotlist=world.draft(ROWS), library=lib.dir)
    with pytest.raises(Refused, match="PROP_ONLY_SHOT_HAS_CHARACTERS"):  # chỉ có refs (không speaker) cũng đủ
        rows = [{**r, "speaker": None} if r["id"] == "S02_A" else r for r in ROWS]
        anchor_pack.build(world.ctx(), shot="S02_A", selection=sel, shotlist=world.draft(rows), library=lib.dir)


def test_script_character_references_map_the_speaker_role_to_the_library_character(tmp_path, monkeypatch) -> None:
    """Script nói người nói là role (CHAR_CHAMSOC_NU) nhưng thư viện khai CHAR_06: bảng ``character_references`` của CHÍNH shotlist là cầu nối."""
    import json

    world = World(tmp_path)
    lib = Library(world)
    # Gate: default face/body chỉ lấy take đã duyệt (SHA khớp) ⇒ fixture phải có approval, không nới cổng.
    all_shas = {row["sha256"] for kinds in lib.entries.values() for rows in kinds.values() for row in rows}
    monkeypatch.setattr(anchor_pack.library, "current_approval", approved_reader(lib, all_shas))
    shotlist = world.draft(ROWS)
    sel = selection(world, lib, characters=[{"character": "mother"}])  # S02_A: speaker alice, refs [alice]
    with pytest.raises(Refused, match="CHARACTER_NOT_IN_SHOT"):  # chưa có bảng ⇒ vẫn từ chối (không đoán)
        anchor_pack.build(world.ctx(), shot="S02_A", selection=sel, shotlist=shotlist, library=lib.dir, wardrobe=presets(world))
    document = json.loads(shotlist.read_text("utf-8"))
    document["character_references"] = {"alice": {"character_id": "mother", "source_role": "alice", "bible_name": "alice"}}
    shotlist.write_text(json.dumps(document), encoding="utf-8")
    pack = anchor_pack.build(world.ctx(), shot="S02_A", selection=sel, shotlist=shotlist, library=lib.dir, wardrobe=presets(world))
    assert [c["character"] for c in pack["characters"]] == ["mother"]
    other = selection(world, lib, characters=[{"character": "nobody"}])  # id không có trong bảng ⇒ vẫn từ chối
    with pytest.raises(Refused, match="CHARACTER_NOT_IN_SHOT"):
        anchor_pack.build(world.ctx(), shot="S02_A", selection=other, shotlist=shotlist, library=lib.dir, wardrobe=presets(world))
