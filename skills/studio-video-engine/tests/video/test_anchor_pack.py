"""``engine.video.anchor_pack``: bộ neo ảnh của MỘT shot (``jjv/shot-anchor-pack/v1``) — chỉ từ thư viện có receipt.

Thế giới giả: INDEX thư viện (FACE/ACTION) + receipt route ``codex-exec``, preset trang phục ``jjv/wardrobe-presets/v1``,
manifest thumbnail, storyboard PENDING / có receipt / user duyệt.  Không GPU, không mạng, không asset thật của domain nào.
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
from engine.video import anchor_pack, ui_state  # noqa: E402

DOMAIN = "jenniejoy_cartoon_3d"  # domain của World test; module không nêu tên domain nào


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Library:
    """Thư viện by-character (INDEX.json + file copy) và thư mục receipt ``<out>/<batch>/tNNN/<sha12>.receipt.json``."""

    def __init__(self, world: World, route: str = "codex-exec") -> None:
        self.world, self.dir, self.out = world, world.tmp / "library", world.tmp / "library-out"
        self.entries: dict[str, dict[str, list[dict]]] = {}
        self.route = route
        for character, kind, labels in (("alice", "FACE", ("01_NEUTRAL", "02_SMILE")), ("alice", "ACTION", ("01_FRONT", "02_WALK")),
                                        ("mother", "FACE", ("01_NEUTRAL",)), ("mother", "ACTION", ("01_FRONT",))):
            for index, label in enumerate(labels, 1):
                payload = f"{character}-{kind}-{label}".encode()
                digest = hashlib.sha256(payload).hexdigest()
                file = blob(self.dir / character / kind / f"{label}__{digest[:12]}.png", payload)
                prompt_id = f"{character}_{kind}_{index:02d}_r1"
                receipt = dump(self.out / f"batch-{character}-{kind}" / f"t{index:03d}" / f"{digest[:12]}.receipt.json",
                               {"schema": "jjv/library-image-receipt/v1", "episode_id": EP, "domain": DOMAIN, "status": "rendered_candidate",
                                "route": route, "provider": route, "prompt_id": prompt_id,
                                "output": {"path": str(file), "sha256": digest, "width": 3, "height": 4}})
                self.entries.setdefault(character, {}).setdefault(kind, []).append(
                    {"file": f"{character}/{kind}/{file.name}", "sha256": digest, "prompt_id": prompt_id, "receipt": str(receipt), "rev": "r1"})
        self.index = dump(self.dir / "INDEX.json", {"characters": self.entries, "revs": {"r1": "test"}})

    def entry(self, character: str, kind: str, index: int) -> dict:
        return self.entries[character][kind][index]

    def thumbs(self) -> Path:
        """Manifest thumbnail (hình dạng file thật: items[] subfolder/filename/source_sha256/thumb_sha256) + file jpg trong input."""
        items = []
        for character, kinds in self.entries.items():
            for kind, rows in kinds.items():
                for row in rows:
                    thumb = blob(self.world.input / "thumbs" / character / kind / (Path(row["file"]).stem + ".jpg"), b"jpg-" + row["sha256"][:6].encode())
                    items.append({"subfolder": f"thumbs/{character}/{kind}", "filename": thumb.name, "source_sha256": row["sha256"],
                                  "thumb_sha256": sha(thumb)})
        return dump(self.world.tmp / "thumbs.json", {"schema": "x.thumbs/v1", "items": items})


def presets(world: World, *, approved: bool = False) -> Path:
    vest = blob(world.input / "wardrobe" / "vest.png", b"site-vest")
    helmet = blob(world.input / "wardrobe" / "helmet.png", b"site-helmet")
    shirt = blob(world.input / "wardrobe" / "shirt.png", b"office-shirt")
    item = lambda p, role: {"name": p.name, "file": f"wardrobe/{p.name}", "sha256": sha(p), "role": role,  # noqa: E731
                            **({"approval": "approved"} if approved else {})}
    return dump(world.tmp / "wardrobe.json", {"schema": "jjv/wardrobe-presets/v1", "domain": DOMAIN, "default_context": "cong_truong",
                                              "contexts": {"cong_truong": [item(vest, "vest"), item(helmet, "helmet")],
                                                           "van_phong": [item(shirt, "shirt")]}})


def selection(world: World, lib: Library, **over) -> Path:
    body = {"schema": "jjv/shot-anchor-selection/v1", "episode_id": EP, "shot": "S02_A", "context": "cong_truong",
            "chosen_by": "test", "characters": [{"character": "alice", "role": "speaker", "face": [lib.entry("alice", "FACE", 1)["sha256"][:12]],
                                                "body": [lib.entry("alice", "ACTION", 0)["sha256"][:12], Path(lib.entry("alice", "ACTION", 1)["file"]).name]}],
            "storyboard": "PENDING", **over}
    return dump(world.tmp / "selection.json", body)


def build(world: World, lib: Library, sel: Path, **kw):
    wardrobe = kw.pop("wardrobe", None) or presets(world)  # chỉ viết preset khi caller không đưa file sẵn
    return anchor_pack.build(world.ctx(), shot="S02_A", selection=sel, shotlist=world.draft(ROWS), library=lib.dir, wardrobe=wardrobe, **kw)


def approved_reader(lib: Library, approved_shas: set[str]):
    by_prompt = {row["prompt_id"]: row["sha256"] for kinds in lib.entries.values() for rows in kinds.values() for row in rows}

    def current(out: Path, prompt_id: str):
        sha256 = by_prompt.get(prompt_id)
        if sha256 not in approved_shas:
            return None
        return {"candidate_sha256": sha256, "path": str(Path(out) / "_review" / prompt_id / "approvals" / "approval-v001.json")}

    return current


def test_builds_pack_from_library_wardrobe_and_pending_storyboard(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    pack = build(world, lib, selection(world, lib), thumbs=lib.thumbs())
    assert pack["schema"] == anchor_pack.SCHEMA and pack["episode_id"] == EP and pack["domain"] == DOMAIN and pack["shot"] == "S02_A"
    assert pack["scene"] == "SCENE_02" and pack["speaker"] == "alice" and pack["context"] == "cong_truong"
    face = pack["face_refs"]
    assert len(face) == 1 and face[0]["sha256"] == lib.entry("alice", "FACE", 1)["sha256"] and face[0]["character"] == "alice"
    assert face[0]["kind"] == "FACE" and face[0]["source_route"] == "codex" and face[0]["route"] == "codex-exec"
    assert face[0]["approval"] == "candidate" and face[0]["approval_record"] is None and face[0]["chosen"] == "selection"
    assert face[0]["receipt"]["sha256"] == sha(Path(lib.entry("alice", "FACE", 1)["receipt"]))
    assert face[0]["thumb"] == {"subfolder": "thumbs/alice/FACE", "filename": Path(lib.entry("alice", "FACE", 1)["file"]).stem + ".jpg",
                                "sha256": face[0]["thumb"]["sha256"]}
    assert [b["sha256"] for b in pack["body_refs"]] == [lib.entry("alice", "ACTION", 0)["sha256"], lib.entry("alice", "ACTION", 1)["sha256"]]
    assert [w["name"] for w in pack["wardrobe_refs"]] == ["vest.png", "helmet.png"] and all(w["verified"] for w in pack["wardrobe_refs"])
    assert pack["wardrobe_refs"][0]["source_route"] == "preset" and pack["wardrobe_refs"][0]["approval"] == "candidate"
    assert pack["location_refs"] == [] and pack["storyboard_anchor"]["status"] == "pending"
    assert "image route" in pack["storyboard_anchor"]["rule"]
    assert pack["status"] == "candidate" and pack["ready_for_graph"] is False
    slots = pack["ref_slots"]
    assert [s["slot"] for s in slots["bound"]] == [f"ref_images.ref_image_{i}" for i in range(5)]
    assert [s["role"] for s in slots["bound"]] == ["face", "body", "body", "wardrobe", "wardrobe"]
    assert slots["max_slots"] == 9 and slots["overflow"] == [] and slots["priority"] == ["face", "body", "wardrobe", "location"]
    assert slots["storyboard"] == "guide.image"
    assert pack["sources"]["library_index"]["sha256"] == sha(lib.index) and pack["sources"]["selection"]["sha256"] == sha(world.tmp / "selection.json")
    assert pack["sources"]["wardrobe_presets"]["sha256"] == sha(world.tmp / "wardrobe.json")
    assert pack["characters"] == [{"character": "alice", "role": "speaker", "face": [face[0]["sha256"]],
                                   "body": [b["sha256"] for b in pack["body_refs"]]}]


def test_slot_overflow_follows_priority_face_body_wardrobe_location(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    scene = blob(tmp_path / "scene.png", b"scene")
    sel = selection(world, lib, location=[{"name": "scene", "path": str(scene), "sha256": sha(scene),
                                           "user_approved": {"by": "Kim", "note": "bối cảnh duyệt tay"}}])
    pack = build(world, lib, sel, ref_slots=4)
    bound, overflow = pack["ref_slots"]["bound"], pack["ref_slots"]["overflow"]
    assert [s["role"] for s in bound] == ["face", "body", "body", "wardrobe"]
    assert [s["role"] for s in overflow] == ["wardrobe", "location"] and all(s["slot"] is None for s in overflow)
    assert pack["location_refs"][0]["sha256"] == sha(scene) and pack["location_refs"][0]["approval"] == "approved"
    assert pack["location_refs"][0]["source_route"] == "user-approved" and pack["location_refs"][0]["receipt"] is None
    assert any("priority" in p for p in pack["problems"])


def test_location_needs_an_image_receipt_or_user_approval_like_storyboard(tmp_path) -> None:
    """CR-ANCHOR-PACK: sha đúng chưa đủ — một casting sheet cũ khai dưới location[] phải bị từ chối (LOCATION_UNVERIFIED)."""
    world = World(tmp_path)
    lib = Library(world)
    casting = blob(tmp_path / "casting" / "CHAR_02_MASTER_FACE_LOCKED.png", b"old casting sheet dcb0789a")
    with pytest.raises(Refused, match="LOCATION_UNVERIFIED"):
        build(world, lib, selection(world, lib, location=[{"name": "site", "path": str(casting), "sha256": sha(casting)}]))
    with pytest.raises(Refused, match="LOCATION_UNVERIFIED"):  # receipt không phải route ảnh ⇒ cũng không nhận
        bad = dump(tmp_path / "casting" / "legacy.receipt.json", {"schema": "jjv/image-receipt/v1", "route": "legacy-casting",
                                                                  "provider": "legacy-casting", "output": {"path": str(casting), "sha256": sha(casting)}})
        build(world, lib, selection(world, lib, location=[{"name": "site", "path": str(casting), "sha256": sha(casting), "receipt": str(bad)}]))
    with pytest.raises(Refused, match="LOCATION_UNVERIFIED"):  # receipt route đúng nhưng sha của take khác file khai
        other = dump(tmp_path / "casting" / "other.receipt.json", {"schema": "jjv/image-receipt/v1", "route": "comfyui-local",
                                                                   "provider": "comfyui-local", "output": {"path": str(casting), "sha256": "0" * 64}})
        build(world, lib, selection(world, lib, location=[{"name": "site", "path": str(casting), "sha256": sha(casting), "receipt": str(other)}]))
    good = dump(tmp_path / "scene" / "site.receipt.json", {"schema": "jjv/image-receipt/v1", "route": "comfyui-local", "provider": "comfyui-local",
                                                           "output": {"path": str(casting), "sha256": sha(casting)}})
    pack = build(world, lib, selection(world, lib, location=[{"name": "site", "path": str(casting), "sha256": sha(casting), "receipt": str(good)}]))
    place = pack["location_refs"][0]
    assert place["source_route"] == "comfyui-local" and place["route"] == "comfyui-local" and place["approval"] == "candidate"
    assert place["receipt"]["sha256"] == sha(good) and place["user_approved"] is None
    with pytest.raises(Refused, match="user_approved"):
        build(world, lib, selection(world, lib, location=[{"name": "site", "path": str(casting), "sha256": sha(casting), "user_approved": {}}]))


def test_default_face_and_body_when_the_selection_omits_them_picks_approved_entries(tmp_path, monkeypatch) -> None:
    world = World(tmp_path)
    lib = Library(world)
    face = lib.entry("alice", "FACE", 1)
    body = lib.entry("alice", "ACTION", 1)
    monkeypatch.setattr(anchor_pack.library, "current_approval", approved_reader(lib, {face["sha256"], body["sha256"]}))
    pack = build(world, lib, selection(world, lib, characters=[{"character": "alice"}]))
    assert pack["face_refs"][0]["sha256"] == face["sha256"] and pack["face_refs"][0]["chosen"] == "default-approved"
    assert pack["body_refs"][0]["sha256"] == body["sha256"] and pack["body_refs"][0]["chosen"] == "default-approved"
    assert len(pack["face_refs"]) == 1 and len(pack["body_refs"]) == 1


def test_unapproved_only_library_refuses_and_lists_candidates(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    with pytest.raises(Refused, match="ANCHOR_NOT_APPROVED") as error:
        build(world, lib, selection(world, lib, characters=[{"character": "alice"}]))
    assert "01_NEUTRAL" in str(error.value) and "jjv images approve" in str(error.value)


def test_refusals_never_substitute_legacy_or_mismatched_files(tmp_path) -> None:
    world = World(tmp_path)
    lib = Library(world)
    with pytest.raises(Refused, match="NOT_IN_LIBRARY"):
        build(world, lib, selection(world, lib, characters=[{"character": "alice", "face": ["deadbeefdead"]}]))
    with pytest.raises(Refused, match="CHARACTER_NOT_IN_SHOT"):
        build(world, lib, selection(world, lib, characters=[{"character": "mother"}]))
    with pytest.raises(Refused, match="CONTEXT"):
        build(world, lib, selection(world, lib, context="rooftop"))
    with pytest.raises(Refused, match="STORYBOARD"):
        old = blob(tmp_path / "casting" / "old-storyboard.jpg", b"old")
        build(world, lib, selection(world, lib, storyboard={"path": str(old)}))
    with pytest.raises(Refused, match="unknown"):
        build(world, lib, selection(world, lib, legacy_face="x.png"))
    with pytest.raises(Refused, match="ROUTE"):
        receipt = Path(lib.entry("alice", "FACE", 1)["receipt"])
        dump(receipt, {**json.loads(receipt.read_text("utf-8")), "route": "legacy-casting", "provider": "legacy-casting"})
        build(world, lib, selection(world, lib))
    lib = Library(world)  # receipt sạch lại
    target = lib.dir / lib.entry("alice", "FACE", 1)["file"]
    target.write_bytes(b"tampered")
    with pytest.raises(Refused, match="SHA_MISMATCH"):
        build(world, lib, selection(world, lib))
    lib = Library(world)
    wardrobe = presets(world)
    (world.input / "wardrobe" / "vest.png").write_bytes(b"other")  # ảnh trang phục đổi byte sau khi preset ghi sha
    with pytest.raises(Refused, match="WARDROBE_REF_UNVERIFIED"):
        build(world, lib, selection(world, lib), wardrobe=wardrobe)


def test_storyboard_receipt_or_user_approval_and_approved_status(tmp_path, monkeypatch) -> None:
    world = World(tmp_path)
    lib = Library(world)
    board = blob(tmp_path / "board" / "S02_A.png", b"board")
    receipt = dump(tmp_path / "board" / "S02_A.receipt.json", {"schema": "jjv/image-receipt/v1", "episode_id": EP, "domain": DOMAIN,
                                                               "route": "comfyui-local", "provider": "comfyui-local",
                                                               "output": {"path": str(board), "sha256": sha(board)}})
    pack = build(world, lib, selection(world, lib, storyboard={"path": str(board), "receipt": str(receipt)}))
    board_ref = pack["storyboard_anchor"]
    assert board_ref["status"] == "candidate" and board_ref["source_route"] == "comfyui-local" and board_ref["sha256"] == sha(board)
    assert pack["ready_for_graph"] is False and pack["status"] == "candidate"
    assert any("ANCHOR_NOT_APPROVED" in reason for reason in pack["not_ready_reasons"])
    with pytest.raises(Refused, match="STORYBOARD"):
        dump(receipt, {**json.loads(receipt.read_text("utf-8")), "output": {"path": str(board), "sha256": "0" * 64}})
        build(world, lib, selection(world, lib, storyboard={"path": str(board), "receipt": str(receipt)}))
    approved_shas = {lib.entry("alice", "FACE", 1)["sha256"], lib.entry("alice", "ACTION", 0)["sha256"],
                     lib.entry("alice", "ACTION", 1)["sha256"]}
    monkeypatch.setattr(anchor_pack.library, "current_approval", approved_reader(lib, approved_shas))
    pack = build(world, lib, selection(world, lib, storyboard={"path": str(board), "sha256": sha(board),
                                                                "user_approved": {"by": "Kim", "note": "duyệt tay 31/10"}}),
                 wardrobe=presets(world, approved=True))
    assert pack["storyboard_anchor"]["status"] == "approved" and pack["storyboard_anchor"]["source_route"] == "user-approved"
    assert all(r["approval"] == "approved" for r in pack["face_refs"] + pack["body_refs"] + pack["wardrobe_refs"])
    assert pack["face_refs"][0]["approval_record"].endswith("approval-v001.json")
    assert pack["status"] == "approved"


def test_cli_writes_atomically_and_ui_state_exposes_the_pack(tmp_path, capsys) -> None:
    world = World(tmp_path)
    lib = Library(world)
    out = tmp_path / "packs"
    code = anchor_pack.main(["--episode", str(world.root), "--machine", str(world.machine), "--shot", "S02_A",
                             "--selection", str(selection(world, lib)), "--shotlist", str(world.draft(ROWS)), "--library", str(lib.dir),
                             "--wardrobe", str(presets(world)), "--thumbs", str(lib.thumbs()), "--out", str(out)])
    printed = json.loads(capsys.readouterr().out)
    file = out / "S02_A" / anchor_pack.PACK_FILE
    assert code == 0 and printed["ok"] and printed["pack"] == str(file) and file.is_file() and sha(file) == printed["sha256"]
    assert printed["status"] == "candidate" and printed["counts"] == {"face": 1, "body": 2, "wardrobe": 2, "location": 0}
    assert not [p for p in file.parent.iterdir() if p.suffix == ".tmp"]
    document = ui_state.build(world.ctx(), shotlist=world.draft(ROWS), anchor_dir=out)
    by_id = {s["id"]: s for s in document["shots"]}
    pack = by_id["S02_A"]["anchor_pack"]
    assert pack["status"] == "candidate" and pack["file"] == str(file) and pack["sha256"] == sha(file) and pack["problems"] == []
    assert pack["face"][0]["url"].startswith("/view?filename=") and "subfolder=thumbs/alice/FACE" in pack["face"][0]["url"]
    assert pack["face"][0]["approval"] == "candidate" and pack["face"][0]["verified"] is True
    assert pack["wardrobe"][0]["url"] == "/view?filename=vest.png&subfolder=wardrobe&type=input"
    assert pack["storyboard"] == {"status": "pending", "url": None, "sha256": None, "verified": None}
    assert [s["slot"] for s in pack["slots"]][:2] == ["ref_images.ref_image_0", "ref_images.ref_image_1"] and pack["overflow"] == []
    assert {r["name"] for r in by_id["S02_A"]["refs"]} >= {"vest.png", "helmet.png"}  # panel tab 02 thấy ngay qua refs
    assert by_id["S03_A"]["anchor_pack"] is None and document["sources"]["anchor_dir"] == str(out)
    (lib.dir / lib.entry("alice", "FACE", 1)["file"]).write_bytes(b"tampered")  # đổi byte sau khi pack ghi ⇒ không tin
    broken = {s["id"]: s for s in ui_state.build(world.ctx(), shotlist=world.draft(ROWS), anchor_dir=out)["shots"]}["S02_A"]
    assert broken["anchor_pack"]["status"] is None and any("ANCHOR_PACK" in p for p in broken["problems"])
    code = ui_state.main(["--episode", str(world.root), "--machine", str(world.machine), "--shotlist", str(world.draft(ROWS)),
                          "--out", str(tmp_path / "ui.json"), "--anchor-dir", str(out)])
    assert code == 0 and json.loads((tmp_path / "ui.json").read_text("utf-8"))["sources"]["anchor_dir"] == str(out)
