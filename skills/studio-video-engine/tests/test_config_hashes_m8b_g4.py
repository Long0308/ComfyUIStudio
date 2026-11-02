"""M8b(g4): machine.brand / machine.remotion / machine.publish are delivery/tool paths, not render content.

They must stay OUT of config_core_sha256 (a machine path change must not read as "config core changed"),
while still moving the full config_sha256.
"""

from __future__ import annotations

from pathlib import Path

from config_fixtures import make_world
from engine.config import hashes, loader

PATH_BLOCKS = ("brand", "remotion", "publish")


def _machine() -> dict:
    return {
        "comfy": {"url": "http://127.0.0.1:8188"},
        "brand": {"kit": "D:\\old\\kit"},
        "remotion": {"browser": "D:\\old\\chrome.exe"},
        "publish": {"film_library": "D:\\old\\film-library.json"},
    }


def test_the_path_blocks_are_not_part_of_the_core_body() -> None:
    body = hashes.core_body(_machine(), {}, {}, {})["machine"]
    for block in PATH_BLOCKS:
        assert block not in body
    assert "comfy" in body


def test_changing_only_brand_remotion_publish_leaves_the_core_hash_unchanged() -> None:
    base = _machine()
    moved = {**base, "brand": {"kit": "E:\\new\\kit"}, "remotion": {"browser": "E:\\x.exe"},
             "publish": {"film_library": "E:\\lib.json"}}
    assert hashes.config_core_sha256(base, {}, {}, {}) == hashes.config_core_sha256(moved, {}, {}, {})


def test_a_real_machine_field_still_moves_the_core_hash() -> None:
    base = _machine()
    changed = {**base, "comfy": {"url": "http://127.0.0.1:9188"}}
    assert hashes.config_core_sha256(base, {}, {}, {}) != hashes.config_core_sha256(changed, {}, {}, {})


def test_the_stage_keys_are_unchanged_by_this_fix() -> None:
    assert hashes.STAGE_MACHINE_KEYS == ("voicestudio", "timing", "audio")


def test_changing_only_brand_remotion_publish_moves_the_full_hash_but_not_the_core(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    build = lambda: loader.build_config(world.episode_file, skill_root=world.skill_root,  # noqa: E731
                                        machine_path=world.machine_path).config
    base = build()

    def move_paths(m: dict) -> None:
        m["brand"] = {"kit": "E:\\moved\\kit"}
        m["remotion"] = {"browser": "E:\\moved\\chrome.exe"}
        m["publish"] = {"film_library": "E:\\moved\\film-library.json"}

    world.edit(world.machine_path, move_paths)
    moved = build()
    assert moved.config_core_sha256 == base.config_core_sha256 != ""
    assert moved.config_sha256 != base.config_sha256
