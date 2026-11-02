"""project_root(): env / default / container fallback and the real error reason (loaded without ComfyUI)."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("panel_core_iso", Path(__file__).resolve().parents[1] / "core.py")
core = importlib.util.module_from_spec(spec); spec.loader.exec_module(core)


def test_env_root_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(core.ENV_ROOT, str(tmp_path))
    assert core.project_root() == tmp_path.resolve()


def test_unmounted_env_gives_real_reason(tmp_path, monkeypatch):
    missing = tmp_path / "nope"
    monkeypatch.setenv(core.ENV_ROOT, str(missing))
    with pytest.raises(core.ProjectRootError) as e:
        core.project_root()
    assert str(missing) in str(e.value) and "project root not mounted" in str(e.value) and core.ENV_ROOT in str(e.value)


def test_container_fallback_when_default_missing(tmp_path, monkeypatch):
    monkeypatch.delenv(core.ENV_ROOT, raising=False)
    monkeypatch.setattr(core, "DEFAULT_ROOT", str(tmp_path / "no-windows-root"))
    monkeypatch.setattr(core, "CONTAINER_ROOT", str(tmp_path))
    assert core.project_root() == tmp_path.resolve()


def test_nothing_mounted_lists_both_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv(core.ENV_ROOT, raising=False)
    monkeypatch.setattr(core, "DEFAULT_ROOT", str(tmp_path / "a"))
    monkeypatch.setattr(core, "CONTAINER_ROOT", str(tmp_path / "b"))
    with pytest.raises(ValueError) as e:
        core.project_root()
    assert "a" in str(e.value) and "b" in str(e.value)


def test_route_shows_real_reason_not_generic():
    src = (Path(__file__).resolve().parents[1] / "routes.py").read_text(encoding="utf-8")
    assert "isinstance(exc, ValueError)" in src  # ProjectRootError is a ValueError
