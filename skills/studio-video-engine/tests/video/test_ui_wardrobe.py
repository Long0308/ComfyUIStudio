"""``engine.video.ui_wardrobe``: neo trang phục theo context cho ui_state — không bao giờ đoán context.

Preset đọc từ ``jjv/wardrobe-presets/v1`` (schema của file thật ``data/wardrobe/<domain>.json``; file do caller truyền,
domain phải khớp); context của shot lấy từ shotlist (``context``/``setting``/``location``); thiếu ⇒ ghi từ chối, không
gắn gì; ``default_context`` của file không bao giờ được dùng.  Không GPU, không mạng.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parents[1]
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from test_ui_state import EP, ROWS, World, blob, dump  # noqa: E402

from engine.core.errors import Refused  # noqa: E402
from engine.video import ui_state, ui_wardrobe  # noqa: E402

DOMAIN = "jenniejoy_cartoon_3d"  # domain của World test; module không nêu tên domain nào


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def presets_file(world: World, *, domain: str = DOMAIN, bad_sha: bool = False) -> Path:
    """Đúng hình dạng file thật: contexts.<khoá> = [{name, file (tương đối ComfyUI/input), sha256, role}] + default_context."""
    vest = blob(world.input / "wardrobe" / "vest.png", b"site-vest")
    helmet = blob(world.input / "wardrobe" / "helmet.png", b"site-helmet")
    shirt = blob(world.input / "wardrobe" / "shirt.png", b"office-shirt")
    company = blob(world.input / "wardrobe" / "company.png", b"company")
    scene = blob(world.tmp / "anchors" / "scene-02.png", b"scene")  # ngoài input ⇒ không có URL, vẫn verify sha
    item = lambda p, role: {"name": p.name, "file": f"wardrobe/{p.name}", "sha256": sha(p), "role": role}  # noqa: E731
    return dump(world.tmp / "wardrobe.json", {
        "schema": "jjv/wardrobe-presets/v1", "domain": domain, "default_context": "cong_truong",
        "contexts": {"cong_truong": [{**item(vest, "vest"), "sha256": ("0" * 64) if bad_sha else sha(vest)}, item(helmet, "helmet")],
                     "van_phong": [item(shirt, "shirt")]},
        "company": [item(company, "company_upload")],
        "scene_refs": {"SCENE_02": [{"name": "scene-02", "file": str(scene), "sha256": sha(scene), "role": "scene"}]}})


def test_context_normalisation_never_guesses() -> None:
    assert ui_wardrobe.context_of({"context": "CÔNG TRƯỜNG"}) == "cong_truong"
    assert ui_wardrobe.context_of({"context": "site"}) == "cong_truong"
    assert ui_wardrobe.context_of({"setting": "office"}) == "van_phong"
    assert ui_wardrobe.context_of({"location": " Văn phòng "}) == "van_phong"
    assert ui_wardrobe.context_of({"context": "van_phong_suit"}) is None  # đã gỡ: không alias, không map về van_phong
    assert ui_wardrobe.context_of({"context": None, "setting": None, "location": None}) is None
    assert ui_wardrobe.context_of({"context": "rooftop"}) is None  # lạ ⇒ không đoán, không rơi xuống khoá sau
    assert ui_wardrobe.context_of({"scene": "SCENE_02", "visual": "công trường"}) is None  # không suy từ mô tả


def test_load_refuses_other_domain_schema_or_unknown_context(tmp_path) -> None:
    world = World(tmp_path)
    with pytest.raises(Refused, match="domain"):
        ui_wardrobe.load_anchors(presets_file(world, domain="another_domain"), DOMAIN)
    with pytest.raises(Refused, match="schema"):
        ui_wardrobe.load_anchors(dump(tmp_path / "x.json", {"schema": "jjv/wardrobe-anchors/v1", "domain": DOMAIN}), DOMAIN)
    with pytest.raises(Refused, match="contexts"):
        ui_wardrobe.load_anchors(dump(tmp_path / "y.json", {"schema": "jjv/wardrobe-presets/v1", "domain": DOMAIN}), DOMAIN)
    with pytest.raises(Refused, match="vocabulary"):
        ui_wardrobe.load_anchors(dump(tmp_path / "z.json", {"schema": "jjv/wardrobe-presets/v1", "domain": DOMAIN,
                                                            "contexts": {"rooftop": [{"name": "a", "file": "a.png", "sha256": "a" * 64}]}}),
                                 DOMAIN)
    with pytest.raises(Refused, match="vocabulary"):  # van_phong_suit đã gỡ khỏi từ vựng
        ui_wardrobe.load_anchors(dump(tmp_path / "s.json", {"schema": "jjv/wardrobe-presets/v1", "domain": DOMAIN,
                                                            "contexts": {"van_phong_suit": [{"name": "a", "file": "a.png", "sha256": "a" * 64}]}}),
                                 DOMAIN)
    with pytest.raises(Refused, match="missing"):
        ui_wardrobe.load_anchors(tmp_path / "no-such.json", DOMAIN)


def test_attach_by_context_verifies_sha_and_never_guesses_a_graph_port(tmp_path) -> None:
    world = World(tmp_path)
    from engine.comfy.settings import settings_from_machine

    anchors = ui_wardrobe.load_anchors(presets_file(world), DOMAIN)
    settings = settings_from_machine(world.ctx().machine)
    site = ui_wardrobe.attach({"id": "S02_A", "scene": "SCENE_02", "context": "site"}, anchors, settings)
    assert site["context"] == "cong_truong" and site["refused"] is None and site["per_character"] == {}
    assert [(r["role"], r["port"], r["verified"], r["characters"]) for r in site["refs"]] == [  # port: chỉ pack.ref_slots gán
        ("wardrobe_anchor", None, True, []), ("wardrobe_anchor", None, True, []),
        ("company_wardrobe", None, True, []), ("scene_reference", None, True, [])]
    assert site["refs"][0]["url"] == "/view?filename=vest.png&subfolder=wardrobe&type=input" and site["refs"][0]["file"] == "wardrobe/vest.png"
    assert site["refs"][3]["url"] is None and site["problems"] == []  # không còn luật 'một slot mỗi vai' (v004)
    office = ui_wardrobe.attach({"id": "S03_A", "scene": "SCENE_03", "setting": "văn phòng"}, anchors, settings)
    assert [r["role"] for r in office["refs"]] == ["wardrobe_anchor", "company_wardrobe"]  # SCENE_03 không có scene ref
    assert office["refs"][0]["port"] is None and office["refs"][0]["context"] == "van_phong" and office["problems"] == []
    unknown = ui_wardrobe.attach({"id": "SCENE_01", "scene": "SCENE_01"}, anchors, settings)
    assert unknown["context"] is None and unknown["refs"] == [] and unknown["refused"].startswith("WARDROBE_CONTEXT_UNKNOWN")


def test_attach_per_character_for_two_person_shots(tmp_path) -> None:
    """``context_per_character``: mỗi nhân vật nhận preset theo context của mình; ảnh chung được gộp; context lạ ⇒ problem riêng."""
    world = World(tmp_path)
    from engine.comfy.settings import settings_from_machine

    anchors = ui_wardrobe.load_anchors(presets_file(world), DOMAIN)
    settings = settings_from_machine(world.ctx().machine)
    two = ui_wardrobe.attach({"id": "S03_A", "scene": "SCENE_03", "context": "cong_truong",
                              "context_per_character": {"CHAR_A": "cong_truong", "CHAR_B": "van_phong"}}, anchors, settings)
    assert two["context"] == "cong_truong" and two["per_character"] == {"CHAR_A": "cong_truong", "CHAR_B": "van_phong"}
    assert [(r["name"], r["context"], r["characters"]) for r in two["refs"]] == [
        ("vest.png", "cong_truong", []), ("helmet.png", "cong_truong", []), ("shirt.png", "van_phong", ["CHAR_B"]),
        ("company.png", None, [])]  # cả shot = [] ; shirt chỉ cho CHAR_B ; không trùng ảnh
    assert two["refused"] is None and two["problems"] == [] and all(r["port"] is None for r in two["refs"])
    only = ui_wardrobe.attach({"id": "S03_A", "context_per_character": {"CHAR_A": "site", "CHAR_B": "office"}}, anchors, settings)
    assert only["context"] is None and only["refused"] is None  # không context shot, nhưng từng nhân vật có ⇒ vẫn gắn
    assert [(r["name"], r["characters"]) for r in only["refs"]] == [("vest.png", ["CHAR_A"]), ("helmet.png", ["CHAR_A"]),
                                                                    ("shirt.png", ["CHAR_B"]), ("company.png", [])]
    mixed = ui_wardrobe.attach({"id": "S03_A", "context": "site", "context_per_character": {"CHAR_B": "rooftop"}}, anchors, settings)
    assert [r["name"] for r in mixed["refs"]] == ["vest.png", "helmet.png", "company.png"] and mixed["per_character"] == {"CHAR_B": None}
    assert len(mixed["problems"]) == 1 and mixed["problems"][0].startswith("WARDROBE_CONTEXT_UNKNOWN") and "'CHAR_B'" in mixed["problems"][0]
    none = ui_wardrobe.attach({"id": "S03_A", "context_per_character": {"CHAR_B": "rooftop"}}, anchors, settings)
    assert none["refs"] == [] and none["refused"].startswith("WARDROBE_CONTEXT_UNKNOWN") and len(none["problems"]) == 1
    removed = ui_wardrobe.attach({"id": "S04_A", "context": "van_phong_suit"}, anchors, settings)  # đã gỡ ⇒ từ chối, không map
    assert removed["refs"] == [] and removed["context"] is None and removed["refused"].startswith("WARDROBE_CONTEXT_UNKNOWN")
    broken = ui_wardrobe.attach({"id": "S02_A", "context": "site"}, ui_wardrobe.load_anchors(presets_file(world, bad_sha=True), DOMAIN),
                                settings)
    assert broken["refs"][0]["verified"] is False and broken["refs"][0]["attached"] is False
    assert any(p.startswith("WARDROBE_REF_UNVERIFIED") for p in broken["problems"])


def test_ui_state_records_wardrobe_per_shot_and_only_when_asked(tmp_path) -> None:
    world = World(tmp_path)
    rows = [dict(ROWS[0]), {**ROWS[1], "context": "site"}, {**ROWS[2], "context": "office"}]
    document = ui_state.build(world.ctx(), shotlist=world.draft(rows), wardrobe=presets_file(world))
    by_id = {s["id"]: s for s in document["shots"]}
    assert by_id["SCENE_01"]["wardrobe"]["refused"].startswith("WARDROBE_CONTEXT_UNKNOWN") and by_id["SCENE_01"]["status"] == "planned"
    assert any("WARDROBE_CONTEXT_UNKNOWN" in p for p in by_id["SCENE_01"]["problems"]) and by_id["SCENE_01"]["context"] is None
    attached = [(r["role"], r["name"]) for r in by_id["S02_A"]["wardrobe"]["refs"] if r["attached"]]
    assert attached[0] == ("wardrobe_anchor", "vest.png") and by_id["S02_A"]["context"] == "cong_truong"
    assert by_id["S02_A"]["refs"] == [] and all(r["port"] is None for r in by_id["S02_A"]["wardrobe"]["refs"])  # không pack ⇒ không ảnh, không cổng
    assert by_id["S03_A"]["wardrobe"]["context"] == "van_phong"
    assert document["sources"]["wardrobe"]["schema"] == "jjv/wardrobe-presets/v1"
    plain = ui_state.build(world.ctx(), shotlist=world.draft(rows))  # không truyền wardrobe ⇒ không gắn, không bịa
    assert all(s["wardrobe"] is None for s in plain["shots"]) and plain["sources"]["wardrobe"] is None
    with pytest.raises(Refused, match="missing"):
        ui_state.build(world.ctx(), shotlist=world.draft(rows), wardrobe=tmp_path / "no-such-wardrobe.json")


def test_cli_accepts_wardrobe_flag(tmp_path, capsys) -> None:
    world = World(tmp_path)
    out = tmp_path / "data" / "video" / f"{EP}.json"
    code = ui_state.main(["--episode", str(world.root), "--machine", str(world.machine), "--shotlist", str(world.draft(ROWS)),
                          "--out", str(out), "--wardrobe", str(presets_file(world))])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["problems"] == 6  # 3 shot không context ⇒ 3 từ chối + 3 ANCHOR_PACK_MISSING (không --anchor-dir)
    assert all(s["wardrobe"]["refused"] for s in json.loads(out.read_text("utf-8"))["shots"])
