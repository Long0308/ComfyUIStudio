"""pytest for scene_layout.py: validator rules, camera framing math and emit-bpy output.

Run (no GPU, no Blender needed):
    python -m pytest -p no:cacheprovider --basetemp <dir> test_scene_layout.py
The optional Blender smoke test runs only with SCENE_LAYOUT_RUN_BLENDER=1 and never renders (--no-render).
"""
from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scene_layout as sl  # noqa: E402

EXAMPLES = HERE.parent / "assets" / "examples"
CARTOON = EXAMPLES / "scene-layout.example.ep04-S01_A.cartoon.json"
LIVE = EXAMPLES / "scene-layout.example.live-action-previz.json"
BLENDER = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")


def cartoon() -> dict:
    return copy.deepcopy(json.loads(CARTOON.read_text(encoding="utf-8")))


def live() -> dict:
    return copy.deepcopy(json.loads(LIVE.read_text(encoding="utf-8")))


def codes(brief: dict) -> set[str]:
    findings, _ = sl.validate(brief)
    return {f.code for f in findings if f.level == "error"}


def actor(brief: dict, ident: str) -> dict:
    return next(a for a in brief["actors"] if a["id"] == ident)


def cow(brief: dict, ident: str) -> dict:
    return next(m for g in brief["animals"] for m in g["members"] if m["id"] == ident)


# ------------------------------------------------------------------ examples and schema

def test_both_examples_validate_clean() -> None:
    for path in (CARTOON, LIVE):
        findings, info = sl.validate(json.loads(path.read_text(encoding="utf-8")))
        assert [f.line() for f in findings] == [], path.name
        assert info["framing"], "framing report must list every actor/animal"


def test_example_domains_are_separate() -> None:
    assert cartoon()["domain"] == "jenniejoy_cartoon_3d"
    assert live()["domain"] == "newtecons_live_action"
    assert live()["status"] == "previz_only"
    assert all(a["role"] == "proxy" and not a.get("cast_ref") for a in live()["actors"])


def test_schema_rejects_unknown_and_missing_fields() -> None:
    b = cartoon()
    b["surprise"] = 1
    del b["camera"]["lens_mm"]
    assert codes(b) == {"SCHEMA"}


# ------------------------------------------------------------------ counts

def test_cow_count_rule_catches_third_cow() -> None:
    b = cartoon()
    group = b["animals"][0]
    group["members"].append({"id": "COW_C", "position": [5.0, 12.0], "facing_deg": -90, "scale": 1.0, "zone": "pen"})
    group["count"] = 3  # internally consistent group, but the production fact is exactly two
    assert "RULE_COUNT" in codes(b)


def test_declared_count_must_match_members() -> None:
    b = cartoon()
    b["animals"][0]["count"] = 3
    assert "COUNT_MISMATCH" in codes(b)


def test_duplicate_ids_rejected() -> None:
    b = cartoon()
    cow(b, "COW_B")["id"] = "COW_A"
    assert "DUP_ID" in codes(b)


# ------------------------------------------------------------------ behind-fence

def test_cow_through_front_fence_fails() -> None:
    b = cartoon()
    cow(b, "COW_A")["position"] = [-3.0, 4.1]  # body now straddles the front rail line y=4
    found = codes(b)
    assert "NOT_BEHIND_FENCE" in found and "NOT_IN_ZONE" in found


def test_cow_poking_through_side_return_fails() -> None:
    b = cartoon()
    cow(b, "COW_B")["position"] = [7.6, 15.0]
    assert "NOT_BEHIND_FENCE" in codes(b)


def test_cow_clearly_behind_fence_passes_rule() -> None:
    b = cartoon()
    cow(b, "COW_A")["position"] = [-3.0, 6.5]
    found = codes(b)
    assert "NOT_BEHIND_FENCE" not in found and "RULE_COUNT" not in found


def test_family_must_stay_outside_pen() -> None:
    b = cartoon()
    actor(b, "ALICE")["position"] = [-3.3, 3.9]
    assert "INSIDE_FENCE" in codes(b)


def test_front_edge_is_enforced_against_camera_and_family_side() -> None:
    b = cartoon()
    b["fences"][0]["front_edge"] = "max_y"  # audience side flipped: camera at y=-13 is now behind the pen
    found = codes(b)
    assert "FRONT_EDGE_CAMERA" in found and "OUTSIDE_NOT_FRONT" in found
    for edge in ("min_x", "max_x"):  # sideways front edges also reject the garden-side camera/family
        b["fences"][0]["front_edge"] = edge
        assert "OUTSIDE_NOT_FRONT" in codes(b), edge


def test_front_edge_message_reports_distance_behind_front_edge() -> None:
    b = cartoon()
    cow(b, "COW_A")["position"] = [-3.0, 4.1]
    findings, _ = sl.validate(b)
    message = next(f.message for f in findings if f.code == "NOT_BEHIND_FENCE")
    assert "front_edge=min_y" in message and "IN FRONT OF" in message
    cow(b, "COW_A")["position"] = [-3.0, 3.0]
    findings, _ = sl.validate(b)
    assert any("IN FRONT OF" in f.message for f in findings if f.code == "NOT_BEHIND_FENCE")


# ------------------------------------------------------------------ actor in zone / pose planes

def test_actor_outside_declared_zone_fails() -> None:
    b = cartoon()
    actor(b, "MOTHER")["position"] = [9.5, -2.2]
    assert "NOT_IN_ZONE" in codes(b)


def test_unknown_zone_fails() -> None:
    b = cartoon()
    actor(b, "ALICE")["zone"] = "nowhere"
    assert "ZONE_UNKNOWN" in codes(b)


def test_seated_plane_must_match_support_prop() -> None:
    b = cartoon()
    actor(b, "MOTHER")["support"]["top_z"] = 0.40  # bench seat top is 0.56
    assert "SUPPORT_TOP" in codes(b)


def test_seated_head_height_plane_checked() -> None:
    b = cartoon()
    actor(b, "MILKMAID")["head_top_z"] = 2.6
    assert "POSE_PLANE" in codes(b)


def test_kneeling_and_seated_need_correct_support() -> None:
    b = cartoon()
    actor(b, "MILKMAID")["support"] = {"kind": "floor", "top_z": 0.0}
    assert "SEATED_NO_SUPPORT" in codes(b)


def test_actor_not_over_its_support_prop() -> None:
    b = cartoon()
    actor(b, "MOTHER")["position"] = [0.0, -2.2]
    assert "SUPPORT_XY" in codes(b)


# ------------------------------------------------------------------ camera framing math

def test_projection_math_known_values() -> None:
    cam = {"position_xy": [0.0, 0.0], "height_m": 0.0, "target": [0.0, 10.0, 0.0], "lens_mm": 36.0, "sensor_width_mm": 36.0}
    x, y, depth = sl.camera_ndc(cam, 160, 90, (0.0, 10.0, 0.0))
    assert (abs(x), abs(y)) == (0.0, 0.0) and depth == pytest.approx(10.0)
    # lens == sensor width -> half-width at 10 m is 5 m: a point 5 m right sits exactly on the frame edge
    x, _, _ = sl.camera_ndc(cam, 160, 90, (5.0, 10.0, 0.0))
    assert x == pytest.approx(1.0)
    # 16:9 -> vertical half-extent is 5 * 9/16 m
    _, y, _ = sl.camera_ndc(cam, 160, 90, (0.0, 10.0, 5.0 * 9 / 16))
    assert y == pytest.approx(1.0)
    assert sl.camera_ndc(cam, 160, 90, (0.0, -1.0, 0.0)) is None


def test_camera_must_frame_all_actors() -> None:
    b = cartoon()
    b["camera"]["lens_mm"] = 90  # far too tight: family leaves the frame
    assert "CAMERA_CROP" in codes(b)


def test_camera_aimed_away_from_actor_fails() -> None:
    b = live()
    b["camera"]["position_xy"] = [3.5, 3.5]  # inside the room, past the near proxies
    assert codes(b) & {"CAMERA_BEHIND", "CAMERA_CROP"}


def test_camera_margin_rule_is_stricter_than_frame_edge() -> None:
    b = live()
    b["rules"][-1]["margin"] = 0.45
    assert "CAMERA_CROP" in codes(b)


def test_camera_degenerate_rejected() -> None:
    b = cartoon()
    b["camera"]["target"] = [0.0, -13.0, 5.1]
    assert "CAMERA_DEGENERATE" in codes(b)
    b["camera"]["target"] = [0.0, -13.0, 0.0]  # straight down: roll undefined
    assert "CAMERA_DEGENERATE" in codes(b)


def test_unknown_species_without_footprint_is_a_validation_error_not_a_crash(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    b = cartoon()
    b["animals"][0]["species"] = "goat"
    for member in b["animals"][0]["members"]:
        member.pop("footprint", None)
        member.pop("height_m", None)
    assert "SPECIES_UNKNOWN" in codes(b)
    path = tmp_path / "goat.json"
    path.write_text(json.dumps(b), encoding="utf-8")
    assert sl.main(["validate", str(path)]) == 1  # exit 1 = invalid brief, never 2 = crash
    assert "SPECIES_UNKNOWN" in capsys.readouterr().out
    assert sl.main(["emit-bpy", str(path), str(tmp_path / "goat.py")]) == 1
    assert not (tmp_path / "goat.py").exists()


# ------------------------------------------------------------------ domain isolation

def test_cartoon_brief_rejects_live_action_tokens() -> None:
    b = cartoon()
    b["notes"].append("reuse the NEWTECONS CHAR_03 wardrobe")
    assert "DOMAIN_LEAK" in codes(b)


def test_live_action_brief_rejects_cartoon_tokens_and_cast_binding() -> None:
    b = live()
    b["notes"].append("same cast as the Alice cartoon")
    actor(b, "PROXY_01")["cast_ref"] = "production-local/character-library/alice/x.png"
    found = codes(b)
    assert "DOMAIN_LEAK" in found and "DOMAIN_CAST" in found


def test_live_action_requires_previz_status_and_proxy_role() -> None:
    b = live()
    b["status"] = "layout_guide_only"
    actor(b, "PROXY_02")["role"] = "adult"
    assert {"DOMAIN_STATUS", "DOMAIN_ROLE"} <= codes(b)


def test_live_action_previz_forbids_animal_proxies() -> None:
    b = live()
    b["animals"] = [{"species": "cow", "count": 1, "members": [
        {"id": "COW_X", "position": [3.0, 3.5], "facing_deg": 0, "zone": "room"}]}]
    assert "DOMAIN_ANIMALS" in codes(b)


def test_domain_leak_is_detected_in_keys_too() -> None:
    b = cartoon()
    b["provenance"]["newtecons_wardrobe_lot"] = "n/a"
    findings, _ = sl.validate(b)
    leaks = [f for f in findings if f.code == "DOMAIN_LEAK"]
    assert leaks and "key" in leaks[0].message
    c = live()
    c["provenance"]["alice_reference"] = "n/a"
    assert "DOMAIN_LEAK" in codes(c)


def test_aec_has_no_animals_and_only_scale_figures() -> None:
    b = live()
    b["domain"], b["status"] = "aec", "layout_guide_only"
    b["notes"] = ["simplified blockout for view framing"]
    b["purpose"] = "view framing check"
    b["animals"] = [{"species": "cow", "count": 1, "members": [
        {"id": "COW_X", "position": [3.0, 3.5], "facing_deg": 0, "zone": "room"}]}]
    found = codes(b)
    assert {"DOMAIN_ANIMALS", "DOMAIN_ROLE"} <= found


# ------------------------------------------------------------------ emit-bpy

def test_template_is_valid_python() -> None:
    compile(sl.TEMPLATE_PATH.read_text(encoding="utf-8"), "bpy_layout_template.py", "exec")


@pytest.mark.parametrize("path", [CARTOON, LIVE], ids=lambda p: p.name)
def test_emit_bpy_compiles_and_embeds_normalized_brief(path: Path) -> None:
    brief = json.loads(path.read_text(encoding="utf-8"))
    text = sl.emit_bpy(brief)
    compile(text, "emitted.py", "exec")
    assert brief["brief_id"] in text and brief["domain"] in text
    assert "__BRIEF_JSON_PLACEHOLDER__" not in text and "__DOMAIN__" not in text
    assigned = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], "id", None) == "BRIEF")
    embedded = json.loads(ast.literal_eval(assigned.value.args[0]))
    assert embedded == sl.normalize(brief)
    # Workbench only: nothing may switch to a GPU-heavy engine.
    assert 'ENGINE = "BLENDER_WORKBENCH"' in text
    assert "BLENDER_EEVEE" not in text and '"CYCLES"' not in text


def test_cli_emit_writes_file_refuses_overwrite_and_invalid(tmp_path: Path) -> None:
    out = tmp_path / "build.py"
    assert sl.main(["emit-bpy", str(CARTOON), str(out)]) == 0
    compile(out.read_text(encoding="utf-8"), str(out), "exec")
    assert sl.main(["emit-bpy", str(CARTOON), str(out)]) == 2  # no silent overwrite
    bad = cartoon()
    cow(bad, "COW_A")["position"] = [-3.0, 3.0]
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    assert sl.main(["emit-bpy", str(bad_path), str(tmp_path / "never.py")]) == 1
    assert not (tmp_path / "never.py").exists()


def test_cli_validate_exit_codes_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert sl.main(["validate", str(LIVE)]) == 0
    capsys.readouterr()
    bad = cartoon()
    cow(bad, "COW_B")["position"] = [7.9, 15.0]
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    assert sl.main(["validate", str(bad_path), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False and any(f["code"] == "NOT_BEHIND_FENCE" for f in report["findings"])
    assert sl.main(["validate", str(tmp_path / "missing.json")]) == 2


@pytest.mark.skipif(os.environ.get("SCENE_LAYOUT_RUN_BLENDER") != "1" or not BLENDER.exists(),
                    reason="set SCENE_LAYOUT_RUN_BLENDER=1 (Blender 5.2 installed) to run; --no-render uses no GPU")
def test_blender_background_build_no_render(tmp_path: Path) -> None:
    script = tmp_path / "build.py"
    assert sl.main(["emit-bpy", str(CARTOON), str(script)]) == 0
    out = tmp_path / "out"
    result = subprocess.run([str(BLENDER), "--background", "--factory-startup", "--python-exit-code", "1",
                             "--python", str(script), "--", "--out-dir", str(out), "--width", "320", "--height", "180", "--no-render"],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    doc = json.loads((out / "S01_A-spatial-layout-positions.json").read_text(encoding="utf-8"))
    assert doc["render"]["engine"] == "BLENDER_WORKBENCH" and doc["render"]["rendered"] is False
    assert all(a["passed"] for a in doc["assertions"])
    cows = [e for e in doc["entities"] if e["kind"] == "animal"]
    assert len(cows) == 2 and all(e["world_bbox_min"][1] > 4.1 for e in cows)
