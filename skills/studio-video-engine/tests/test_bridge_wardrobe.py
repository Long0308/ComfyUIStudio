"""Bridge wardrobe anchors: preset refs attached to every take, refusal when they cannot be verified, stage command.

FAKE Codex CLI + a tiny fake registry; no network beyond loopback, no real Codex, no GPU.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import pytest

from engine.bridge import cli as bridge_cli, wardrobe
from engine.core.errors import Refused
from images_fixtures import make_png, sha
from test_bridge import NEWT, Bridge

LOGO_ROLE = "brand_logo_color"


@pytest.fixture()
def made(tmp_path):
    bridge = Bridge(tmp_path)
    yield bridge
    bridge.server.shutdown()
    bridge.server.server_close()


def build_registry(tmp: Path) -> tuple[Path, dict[str, Path]]:
    files = {"shirt": make_png(tmp / "wardrobe" / "originals" / "AO SO MI.png", (10, 10, 200), (40, 40)),
             "helmet": make_png(tmp / "wardrobe" / "originals" / "HELMET.png", (230, 230, 230), (40, 40)),
             "logo": make_png(tmp / "wardrobe" / "originals" / "LOGO.png", (200, 0, 0), (40, 40)),
             "vest": make_png(tmp / "wardrobe" / "originals" / "VEST.png", (0, 0, 90), (40, 40))}

    def src(key: str, role: str) -> dict:  # the registry path is on an OLD root: path_map must remap it
        return {"path": "D:/old-root/wardrobe/originals/" + files[key].name, "sha256": sha(files[key]), "role": role}

    registry = {"schema": "reg", "items": [
        {"id": "SHIRT", "kind": "shirt", "source_references": [src("shirt", "shirt_grid")]},
        {"id": "HELMET", "kind": "helmet", "source_references": [src("helmet", "helmet_shape"), src("logo", LOGO_ROLE)]},
        {"id": "VEST_A", "kind": "vest", "source_references": [src("vest", "vest_front")]},
        {"id": "VEST_B", "kind": "vest", "source_references": [src("vest", "vest_front")]}]}
    path = tmp / "wardrobe" / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    return path, files


def block(tmp: Path, registry: Path) -> dict:
    return {NEWT: {"required": True, "registry": str(registry), "default_context": "cong_truong",
                   "path_map": {"D:/old-root": str(tmp).replace("\\", "/")}, "stage_subdir": "wardrobe",
                   "ui_data": str(tmp / "ui-data"),
                   "contexts": {"cong_truong": ["SHIRT", "HELMET", "VEST_A", "VEST_B"],
                                "van_phong": ["SHIRT", {"item": "HELMET", "roles": [LOGO_ROLE]}]}}}


def run(bridge: Bridge, **kw) -> dict:
    code, started = bridge.call("POST", "/v1/images/codex", bridge.image_body(n=1, **kw))
    assert code == 202, started
    return bridge.wait(started["job_id"])


def sent_images(bridge: Bridge) -> list[str]:
    call = json.loads((bridge.homes["acct3"] / "calls.jsonl").read_text("utf-8").splitlines()[0])
    argv = call["argv"]
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-i"]


def test_default_context_attaches_the_site_set_to_every_take_and_records_it(made, tmp_path):
    registry, files = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    doc = run(made)
    expected = {sha(files[k]) for k in ("shirt", "helmet", "logo", "vest")}  # vest named by two items = one ref
    assert doc["state"] == "done", doc
    assert doc["ref_set"]["context"] == "cong_truong" and doc["ref_set"]["source"] == "preset"
    assert {r["sha256"] for r in doc["ref_set"]["refs"]} == expected and len(doc["ref_set"]["refs"]) == 4
    assert all({"name", "role", "sha256"} <= set(r) for r in doc["items"][0]["refs"])
    assert {sha(Path(p)) for p in sent_images(made)} == expected  # the fake CLI really got them as -i
    receipt = json.loads(Path(doc["images"][0]["receipt"]).read_text("utf-8"))
    assert {r["sha256"] for r in receipt["ref_hashes"]} == expected  # same provenance as the library path
    assert {r["role"] for r in receipt["ref_hashes"]} >= {"shirt_grid", "helmet_shape", LOGO_ROLE}


def test_office_context_has_no_helmet_or_vest(made, tmp_path):
    registry, files = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    doc = run(made, context="van_phong")
    assert doc["state"] == "done", doc
    assert {r["sha256"] for r in doc["ref_set"]["refs"]} == {sha(files["shirt"]), sha(files["logo"])}


def test_explicit_non_empty_refs_override_the_preset(made, tmp_path):
    registry, files = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    mine = make_png(tmp_path / "mine.png", (1, 2, 3), (32, 32))
    doc = run(made, refs=[{"role": "identity", "path": str(mine)}])
    assert doc["ref_set"]["source"] == "override" and [r["sha256"] for r in doc["ref_set"]["refs"]] == [sha(mine)]
    code, answer = made.call("POST", "/v1/images/codex", made.image_body(n=1, context="van_phong",
                                                                          refs=[{"role": "x", "path": str(mine)}]))
    assert code == 400 and "not both" in answer["error"]


def test_company_wardrobe_and_scene_refs_are_added_and_hashed(made, tmp_path):
    registry, files = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    upload = make_png(tmp_path / "up.png", (9, 9, 9), (32, 32))
    scene = make_png(tmp_path / "scene.png", (50, 60, 70), (32, 32))
    doc = run(made, context="van_phong",
              wardrobe_refs=[{"png_base64": base64.b64encode(upload.read_bytes()).decode()}],
              scene_ref={"path": str(scene)})
    by_role = {r["role"]: r["sha256"] for r in doc["ref_set"]["refs"]}
    assert by_role["company_wardrobe"] == sha(upload) and by_role["scene_location"] == sha(scene)
    assert len(doc["ref_set"]["refs"]) == 4 and {sha(Path(p)) for p in sent_images(made)} >= {sha(upload), sha(scene)}


def test_removed_suit_context_is_refused(made, tmp_path):
    registry, _ = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    code, answer = made.call("POST", "/v1/images/codex", made.image_body(n=1, context="van_phong_suit"))
    assert code == 400 and answer["ok"] is False and "context must be" in answer["error"] and "van_phong_suit" in answer["error"], answer
    assert not (made.homes["acct3"] / "calls.jsonl").exists()


@pytest.mark.parametrize("breakage", ["sha", "missing", "context"])
def test_unresolvable_wardrobe_refuses_the_job_instead_of_running_without_refs(made, tmp_path, breakage):
    registry, files = build_registry(tmp_path)
    made.cfg.wardrobe = block(tmp_path, registry)
    body = {}
    if breakage == "sha":
        files["helmet"].write_bytes(files["helmet"].read_bytes() + b"x")
    elif breakage == "missing":
        files["logo"].unlink()
    else:
        body["context"] = "khong_co"
    code, answer = made.call("POST", "/v1/images/codex", made.image_body(n=1, **body))
    assert code == 400 and answer["ok"] is False, answer
    assert any(w in answer["error"] for w in ("hashes", "not found", "context must be"))
    assert not (made.state / "jobs").exists() or not any((made.state / "jobs").iterdir())
    assert not (made.homes["acct3"] / "calls.jsonl").exists()  # the fake CLI was never called


def test_stage_copies_write_once_writes_presets_and_leaves_originals(tmp_path):
    registry, files = build_registry(tmp_path)
    world = Bridge(tmp_path / "w")
    try:
        wd = block(tmp_path, registry)
        before = {k: sha(v) for k, v in files.items()}
        first = wardrobe.stage(wd, NEWT, world.world.machine_path)
        again = wardrobe.stage(wd, NEWT, world.world.machine_path)  # idempotent: identical bytes
        input_dir = world.world.comfy_root / "input"
        assert first["files"] == again["files"] and len(first["files"]) == 4
        for row in first["contexts"]["cong_truong"]:
            staged = input_dir / row["file"]
            assert staged.is_file() and sha(staged) == row["sha256"] and row["file"].startswith("wardrobe/" + row["sha256"][:12] + "_")
        assert before == {k: sha(v) for k, v in files.items()} and all(v.is_file() for v in files.values())
        written = json.loads((tmp_path / "ui-data" / f"{NEWT}.json").read_text("utf-8"))
        assert written["schema"] == wardrobe.PRESETS_SCHEMA and written["domain"] == NEWT
        assert set(written["contexts"]) == {"cong_truong", "van_phong"} and len(written["contexts"]["van_phong"]) == 2
        assert all({"name", "file", "sha256"} <= set(r) for r in written["contexts"]["van_phong"])
        staged_file = input_dir / first["contexts"]["cong_truong"][0]["file"]
        staged_file.write_bytes(b"tampered")  # write-once: a different file at the target is refused, never replaced
        with pytest.raises(Refused, match="refusing to overwrite"):
            wardrobe.stage(wd, NEWT, world.world.machine_path)
    finally:
        world.server.shutdown()
        world.server.server_close()


def test_stage_cli_verb_prints_the_presets_json(tmp_path, capsys):
    registry, files = build_registry(tmp_path)
    world = Bridge(tmp_path / "w")
    try:
        state = tmp_path / "state"
        state.mkdir()
        (state / "config.json").write_text(json.dumps({"accounts": ["acct3"], "wardrobe": block(tmp_path, registry)}), "utf-8")
        args = argparse.Namespace(verb="wardrobe-stage", domain=NEWT, state_dir=str(state), machine=str(world.world.machine_path))
        assert bridge_cli.run_bridge(args) == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["domain"] == NEWT and printed["contexts"]["cong_truong"][0]["sha256"] == sha(files["shirt"])
    finally:
        world.server.shutdown()
        world.server.server_close()
