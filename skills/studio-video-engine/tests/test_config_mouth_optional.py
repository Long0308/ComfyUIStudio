"""M8b-e2 (root decision c): ``files.mouth_boxes`` is OPTIONAL everywhere - no engine verb reads the boxes.

Red tests of production-local/engine/M8b-e2-MOUTH.md section 3.6: an episode without the key resolves; a named but
missing file is still a violation; an episode that names the file hashes the same body as before (ep04's hash does
not move); the box consistency rules still run when the file is named (``test_config.py::test_mouth_box_errors``).
"""

from __future__ import annotations

from pathlib import Path

from config_fixtures import make_world

from engine.config import hashes
from engine.config.loader import build_config
from engine.core.io import canonical_sha256, read_json


def _report(world):
    return build_config(world.episode_file, skill_root=world.skill_root, machine_path=world.machine_path)


def test_an_episode_without_mouth_boxes_resolves(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.edit_episode(lambda d: d["files"].pop("mouth_boxes"))
    (world.engine_dir / "mouth-boxes.json").unlink()
    report = _report(world)
    assert report.ok, report.violations
    assert report.config.mouth_boxes is None and "mouth-boxes" not in report.config.sources
    assert report.config.as_dict()["mouth_boxes"] is None


def test_a_named_but_missing_mouth_boxes_file_is_still_a_violation(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    (world.engine_dir / "mouth-boxes.json").unlink()
    report = _report(world)
    assert not report.ok and any(v.startswith("mouth-boxes: file not found") for v in report.violations)


def test_naming_the_file_hashes_the_same_body_as_before(tmp_path: Path, monkeypatch) -> None:
    """The hashed document keeps ``mouth_boxes`` = the file's content when named: ep04's config_sha256 is unchanged."""
    world = make_world(tmp_path)
    seen: list[dict] = []
    original = hashes.full_body

    def capture(body: dict, delivery_sha):
        seen.append(body)
        return original(body, delivery_sha)

    monkeypatch.setattr(hashes, "full_body", capture)
    report = _report(world)
    assert report.ok and len(seen) == 1
    body = seen[0]
    assert set(body) == {"machine", "domain", "recipes", "episode", "shots", "mouth_boxes"}
    assert body["mouth_boxes"] == read_json(world.engine_dir / "mouth-boxes.json")
    assert report.config.config_sha256 == canonical_sha256(original(body, report.config.delivery_contract_sha256),
                                                           mode="ascii")
    assert "mouth-boxes" in report.config.sources
    world.edit_episode(lambda d: d["files"].pop("mouth_boxes"))
    without = _report(world)
    assert without.ok and seen[1]["mouth_boxes"] is None and without.config.config_sha256 != report.config.config_sha256
    assert "mouth_boxes" not in hashes.core_body(body["machine"], body["domain"], body["recipes"], body["episode"]), \
        "the core hash never covers the boxes (only the episode's files table, which names them)"
