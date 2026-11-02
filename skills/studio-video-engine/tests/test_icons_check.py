"""The registry gate: each rule is proven red by breaking exactly that rule in an otherwise green registry."""

from __future__ import annotations

from engine.editorial import icons as reg
from test_icons_support import (COLD, WARM, World, codes, needs_ffmpeg, tampered, write_png)

pytestmark = needs_ffmpeg


def test_green_registry_has_no_errors_and_reports_the_pair(tmp_path):
    world = World(tmp_path)
    report = world.validate(world.registry(), script_path=world.script_path)
    assert report["ok"] and report["errors"] == []
    assert codes(report, "warnings") >= {"W_CANDIDATE"}
    (pair,) = report["pairs"]
    assert pair["pair"] == ["warm", "cold"] and pair["status"] == "PASS"
    assert pair["delta_e_file"] >= 15 and pair["hue_distance_deg"] >= 40 and pair["silhouette_iou"] <= 0.95
    assert report["summary"]["spoken_terms"] == 4 and report["summary"]["candidate"] == 5


def test_spoken_word_without_an_icon_is_an_error(tmp_path):
    world = World(tmp_path)
    broken = tampered(world.registry(), lambda r: r["terms"].pop("cold"))
    assert "E_TERM_MISSING" in codes(world.validate(broken))


def test_term_pointing_at_an_unregistered_icon_is_an_error(tmp_path):
    world = World(tmp_path)
    broken = tampered(world.registry(), lambda r: r["terms"]["farm"].update(icon="ghost"))
    assert "E_ICON_MISSING" in codes(world.validate(broken))


def test_one_icon_for_two_words_is_refused_unless_marked_shared(tmp_path):
    world = World(tmp_path, per_word=False)
    assert "E_SHARED_ICON" in codes(world.validate(world.registry()))
    marked = world.validate(world.registry(allow_shared=("warm-cold",)))
    assert "E_SHARED_ICON" not in codes(marked) and "W_SHARED_MARKED" in codes(marked, "warnings")
    assert "E_PAIR_SAME_IMAGE" in codes(marked)        # shared is allowed, an opposite pair on one image never is


def test_same_bytes_under_two_icons_is_an_error(tmp_path):
    world = World(tmp_path)
    broken = tampered(world.registry(), lambda r: r["icons"]["creamy"].update(sha256=r["icons"]["farm"]["sha256"]))
    assert "E_DUP_IMAGE" in codes(world.validate(broken))


def test_missing_file_and_changed_file_are_errors(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    (world.assets / "png" / "farm.png").unlink()
    write_png(world.assets / "png" / "creamy.png", (1, 2, 3), "square")
    found = codes(world.validate(registry))
    assert {"E_FILE_MISSING", "E_SHA_MISMATCH"} <= found


def test_small_or_opaque_icon_is_an_error(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    world.recipe["min_side_px"] = 128
    assert "E_ICON_SIZE" in codes(world.validate(registry))
    world.recipe["min_side_px"] = 32
    flat = write_png(world.assets / "png" / "farm.png", (60, 170, 70), "disc", alpha=False)
    broken = tampered(registry, lambda r: r["icons"]["farm"].update(sha256=reg.sha256_file(flat)))
    assert "E_ICON_NO_ALPHA" in codes(world.validate(broken))


def test_palette_drift_is_an_error(tmp_path):
    world = World(tmp_path)
    broken = tampered(world.registry(), lambda r: r["icons"]["farm"]["palette"].update(rgb=[0.0, 0.0, 0.0]))
    assert "E_PALETTE_DRIFT" in codes(world.validate(broken))


def test_opposite_pair_with_similar_colour_is_an_error(tmp_path):
    world = World(tmp_path)
    write_png(world.assets / "png" / "cold.png", (WARM[0] - 6, WARM[1] + 5, WARM[2]), "square")
    # manifest sha for cold changed on disk: refresh it so the build accepts the file
    import json
    manifest = json.loads(world.manifest_path.read_text("utf-8"))
    for row in manifest["terms"]:
        if row["id"] == "cold":
            row["png_sha256"] = reg.sha256_file(world.assets / "png" / "cold.png")
    world.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = world.validate(world.registry())
    assert "E_PAIR_COLOUR" in codes(report)
    assert report["pairs"][0]["status"] == "FAIL"


def test_opposite_pair_with_the_same_shape_is_an_error(tmp_path):
    world = World(tmp_path)
    import json
    write_png(world.assets / "png" / "cold.png", COLD, "disc")      # warm is an orange disc, cold a blue disc
    manifest = json.loads(world.manifest_path.read_text("utf-8"))
    for row in manifest["terms"]:
        if row["id"] == "cold":
            row["png_sha256"] = reg.sha256_file(world.assets / "png" / "cold.png")
    world.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = world.validate(world.registry())
    assert codes(report) == {"E_PAIR_SHAPE"}                       # colours differ, silhouettes do not
    assert report["pairs"][0]["silhouette_iou"] > 0.95


def test_pair_field_and_attributes_are_checked(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    assert "E_PAIR_FIELD" in codes(world.validate(tampered(registry, lambda r: r["icons"]["warm"].update(pair=None))))
    missing = tampered(registry, lambda r: r["icons"]["cold"].update(attribute=None))
    assert "E_ATTRIBUTE_MISSING" in codes(world.validate(missing))
    plain = tampered(registry, lambda r: r["icons"]["farm"].update(attribute=None))
    assert "E_ATTRIBUTE_MISSING" not in codes(world.validate(plain))
    assert "W_ATTRIBUTE_MISSING" in codes(world.validate(plain), "warnings")


def test_status_rules(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    assert "E_STATUS" in codes(world.validate(tampered(registry, lambda r: r["icons"]["farm"].update(status="done"))))
    strict = world.validate(registry, require_approved=True)
    assert "E_NOT_APPROVED" in codes(strict)
    approved = tampered(registry, lambda r: [e.update(status="approved", approved=True) for e in r["icons"].values()])
    assert world.validate(approved, require_approved=True)["ok"]


def test_hand_edited_registry_and_script_drift_are_errors(tmp_path):
    world = World(tmp_path)
    registry = world.registry()
    edited = {**registry, "version": 7}                          # content changed, seal not renewed
    assert "E_REGISTRY_SHA" in codes(world.validate(edited))
    world.script["vocabulary_cards"].pop()                        # the script lost the Farm card
    world.write_script()
    assert "E_SCRIPT_DRIFT" in codes(world.validate(registry, script_path=world.script_path))
    assert "E_SCHEMA" in codes(world.validate({"schema": "x", "icons": {}}))
