"""``resolve_data_path`` must never remap a recorded path outside its current legacy root."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.core import paths


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    old_root = tmp_path / "old-root" / "03 Voice"
    new_root = tmp_path / "new-root" / "03 Voice"
    new_root.mkdir(parents=True)
    return old_root, new_root


def test_dotdot_in_the_legacy_suffix_is_not_remapped(tmp_path: Path) -> None:
    old_root, new_root = _roots(tmp_path)
    outside = new_root.parent / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_text("do not hash", encoding="utf-8")

    recorded = old_root / ".." / "outside" / "secret.wav"
    assert not recorded.exists()
    assert paths.resolve_data_path(recorded, {"legacy_roots": {str(old_root): str(new_root)}}) == recorded


def test_a_symlink_escape_is_not_remapped(tmp_path: Path) -> None:
    old_root, new_root = _roots(tmp_path)
    outside = new_root.parent / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_text("do not hash", encoding="utf-8")
    try:
        (new_root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create directory symlinks")

    recorded = old_root / "link" / "secret.wav"
    assert (new_root / "link" / "secret.wav").is_file()
    assert paths.resolve_data_path(recorded, {"legacy_roots": {str(old_root): str(new_root)}}) == recorded


def test_a_normal_legacy_path_still_resolves(tmp_path: Path) -> None:
    old_root, new_root = _roots(tmp_path)
    target = new_root / "ep" / "mix-plan.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")

    recorded = old_root / "ep" / "mix-plan.json"
    assert not recorded.exists()
    assert paths.resolve_data_path(recorded, {"legacy_roots": {str(old_root): str(new_root)}}) == target
