"""CR-ANCHOR-REFS: pack ĐÃ LƯU được kiểm lại bằng đúng luật lúc dựng khi nạp (``anchor_verify`` qua ``anchor_pack_ui``): receipt
route ảnh của đúng take, ``user_approved.by``, trang phục phải nằm trong preset đã ghi; ảnh stage pilot ``h3-<sha>`` LUÔN bị từ chối
⇒ ``ANCHOR_PACK_INVALID``, ``refs`` rỗng, cổng trang phục null.  Không GPU, không mạng."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _folder in (_HERE, _HERE.parent):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

from pack_fixtures import SHOT, blob, dump, saved_pack, sha  # noqa: E402

from engine.comfy.settings import settings_from_machine  # noqa: E402
from engine.core.io import read_json  # noqa: E402
from engine.video import anchor_pack_ui, anchor_verify  # noqa: E402


def load(world, pack_path: Path) -> dict:
    shots = [{"id": SHOT, "problems": [], "refs": [], "wardrobe": {"refs": [{"name": "vest.png", "sha256": "x", "port": None}]}}]
    return anchor_pack_ui.attach_ui(shots, pack_path.parent.parent, world.ctx(), settings_from_machine(world.ctx().machine))[0]


def rewrite(pack_path: Path, mutate) -> None:
    pack = read_json(pack_path)
    mutate(pack)
    dump(pack_path, pack)


def test_a_valid_saved_pack_loads_with_refs_and_no_invalid_problem(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    shot = load(world, pack_path)
    assert shot["anchor_pack"]["status"] == "candidate" and len(shot["refs"]) == 4
    assert not [p for p in shot["problems"] if "ANCHOR_PACK" in p]
    assert anchor_verify.validate_pack(world.ctx(), read_json(pack_path)) == []


def test_a_legacy_pilot_input_as_face_is_invalid_even_with_a_consistent_receipt(tmp_path) -> None:
    world, lib, pack_path = saved_pack(tmp_path)
    pilot = blob(world.input / ("h3-dcb0789a" + "0" * 56 + ".png"), b"pilot face of another person")
    receipt = dump(world.tmp / "pilot.receipt.json", {"schema": "jjv/library-image-receipt/v1", "route": "codex-exec", "provider": "codex-exec",
                                                      "prompt_id": "p", "output": {"path": str(pilot), "sha256": sha(pilot)}})

    def mutate(pack: dict) -> None:
        face = pack["face_refs"][0]
        pack["face_refs"] = [{**face, "name": pilot.name, "path": str(pilot), "sha256": sha(pilot), "prompt_id": "p",
                              "receipt": {"path": str(receipt), "sha256": sha(receipt)}}]
        pack["ref_slots"]["bound"][0] = {**pack["ref_slots"]["bound"][0], "name": pilot.name, "sha256": sha(pilot)}
        pack["characters"][0]["face"] = [sha(pilot)]

    rewrite(pack_path, mutate)
    shot = load(world, pack_path)
    assert shot["refs"] == [] and shot["anchor_pack"]["status"] is None
    assert any(p.startswith("ANCHOR_PACK_INVALID") and "h3-dcb0789a" in p for p in shot["problems"])
    assert any("ANCHOR_PACK_INVALID" in p for p in shot["anchor_pack"]["problems"])
    assert shot["wardrobe"]["refs"][0]["port"] is None
    problems = anchor_verify.validate_pack(world.ctx(), read_json(pack_path))
    assert problems and all(p.startswith("ANCHOR_PACK_INVALID") for p in problems)


def test_a_legacy_pilot_input_as_storyboard_anchor_is_invalid_even_when_user_approved(tmp_path) -> None:
    """CR-H3-PACK-BIND: nhánh storyboard_anchor cũng phải chặn ảnh stage pilot ``h3-<sha>`` (trước đây lọt qua thành AddGuide)."""
    world, lib, pack_path = saved_pack(tmp_path, storyboard=True)
    pilot = blob(world.input / ("h3-5150f6a2" + "0" * 56 + ".png"), b"pilot storyboard of the wrong take")
    rewrite(pack_path, lambda pack: pack["storyboard_anchor"].update(name=pilot.name, path=str(pilot), sha256=sha(pilot)))
    problems = anchor_verify.validate_pack(world.ctx(), read_json(pack_path))
    assert any(p.startswith("ANCHOR_PACK_INVALID: storyboard") and "h3-<sha>" in p for p in problems), problems


@pytest.mark.parametrize("case", ["route", "take_sha", "wardrobe_not_in_preset", "location_no_proof", "storyboard_no_proof",
                                  "bound_sha_unknown"])
def test_each_creation_rule_is_rechecked_on_load(tmp_path, case) -> None:
    world, lib, pack_path = saved_pack(tmp_path, storyboard=(case == "storyboard_no_proof"))
    receipt = Path(lib.entry("alice", "FACE", 1)["receipt"])
    if case == "route":  # receipt đổi route sang casting cũ; sha receipt trong pack cập nhật theo để chỉ luật route bị chạm
        dump(receipt, {**read_json(receipt), "route": "legacy-casting", "provider": "legacy-casting"})
        rewrite(pack_path, lambda pack: pack["face_refs"][0]["receipt"].update(sha256=sha(receipt)))
    elif case == "take_sha":  # receipt của take khác (output.sha256 khác file)
        dump(receipt, {**read_json(receipt), "output": {**read_json(receipt)["output"], "sha256": "0" * 64}})
        rewrite(pack_path, lambda pack: pack["face_refs"][0]["receipt"].update(sha256=sha(receipt)))
    elif case == "wardrobe_not_in_preset":  # file thật, sha đúng, nhưng không nằm trong preset đã ghi ở sources
        other = blob(world.input / "wardrobe" / "other.png", b"not-a-preset-item")

        def swap(pack: dict) -> None:
            pack["wardrobe_refs"][0].update(name="other.png", file="wardrobe/other.png", path=str(other), sha256=sha(other))
            pack["ref_slots"]["bound"][2].update(name="other.png", sha256=sha(other))

        rewrite(pack_path, swap)
    elif case == "location_no_proof":
        site = blob(world.tmp / "site.png", b"site")
        rewrite(pack_path, lambda pack: pack.__setitem__("location_refs", [
            {"role": "location", "name": "site", "path": str(site), "sha256": sha(site), "route": None, "source_route": "user-approved",
             "receipt": None, "approval": "approved", "user_approved": {"by": "", "note": ""}, "rule": "x"}]))
    elif case == "storyboard_no_proof":
        rewrite(pack_path, lambda pack: pack["storyboard_anchor"].update(receipt=None, user_approved=None, source_route="user-approved"))
    elif case == "bound_sha_unknown":
        rewrite(pack_path, lambda pack: pack["ref_slots"]["bound"][0].update(sha256="f" * 64))
    shot = load(world, pack_path)
    assert shot["refs"] == [] and shot["anchor_pack"]["status"] is None, case
    assert any(p.startswith("ANCHOR_PACK_INVALID") for p in shot["problems"]), (case, shot["problems"])
