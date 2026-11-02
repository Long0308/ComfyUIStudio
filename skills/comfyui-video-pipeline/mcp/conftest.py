"""Keep pytest's unused basetemp ACL from masking test results on Windows."""

from __future__ import annotations

import shutil
import tempfile

import _pytest.tmpdir
import pytest

_original_cleanup_dead_symlinks = _pytest.tmpdir.cleanup_dead_symlinks


def _safe_cleanup_dead_symlinks(root: object) -> None:
    try:
        _original_cleanup_dead_symlinks(root)
    except PermissionError:
        # These tests deliberately create and clean their own workspace temp
        # directories; pytest's owner-only basetemp is not used.
        return


_pytest.tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks


@pytest.fixture(autouse=True)
def _isolated_bridge_shared(monkeypatch: pytest.MonkeyPatch):
    """Every MCP tool call writes a bridge heartbeat; keep it out of the live shared folder."""
    shared = tempfile.mkdtemp(prefix="jj-bridge-shared-")
    monkeypatch.setenv("JJ_BRIDGE_SHARED", shared)
    try:
        yield shared
    finally:
        shutil.rmtree(shared, ignore_errors=True)
