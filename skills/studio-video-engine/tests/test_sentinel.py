"""SENTINEL: pytest must never create or stat the real machine-wide GPU lock."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import pytest

import conftest
from engine.comfy import lock

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "engine"


def test_tripwire_blocks_every_route_to_the_real_lock() -> None:
    real = conftest.REAL_LOCK
    with conftest.deliberate_trips():
        for action in (
            lambda: os.stat(real),
            lambda: os.lstat(real),
            lambda: os.path.exists(real),
            lambda: Path(real).exists(),
            lambda: Path(real).is_file(),
            lambda: os.open(real, os.O_CREAT | os.O_EXCL | os.O_WRONLY),
            lambda: open(real, "rb"),
            lambda: Path(real).unlink(missing_ok=True),
            lambda: os.path.exists(real.replace("\\", "/")),
        ):
            with pytest.raises(conftest.RealLockTouched):
                action()


def test_tripwire_ignores_unrelated_paths(tmp_path: Path) -> None:
    sibling = tmp_path / ".comfyui-image-submit.lock"
    sibling.write_bytes(b"x")
    assert sibling.exists() and sibling.stat().st_size == 1


def test_engine_source_hardcodes_no_lock_path() -> None:
    for source in ENGINE_ROOT.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert ".comfyui-image-submit" not in text, source
        assert "04-milk-and-mom" not in text, source


def test_existence_lock_requires_an_injected_path() -> None:
    parameters = inspect.signature(lock.existence_lock.__wrapped__).parameters
    assert parameters["path"].default is inspect.Parameter.empty
    assert parameters["timeout_seconds"].default is inspect.Parameter.empty


def test_no_violation_recorded_so_far() -> None:
    assert conftest.ATTEMPTS == []
