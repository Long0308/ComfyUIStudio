"""Run staged CPU tests in a Windows managed sandbox.

Python 3.14 gives mkdir(mode=0o700) a Windows ACL that this managed sandbox
cannot reopen. Only for test-tree descendants of .gui-export-stage, inherit
the normal parent ACL instead. Engine code and production folders are untouched.
Native operators should prefer the ordinary `python -I -m pytest` command.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROPOSED = Path(__file__).resolve().parents[1]
STAGE = PROPOSED.parent
WORKSPACE = next(p for p in STAGE.parents if (p / ".agents/skills/studio-video-engine").is_dir())
SKILL = WORKSPACE / ".agents/skills/studio-video-engine"
sys.path.insert(0, str(SKILL))
import engine
engine.__path__.insert(0, str(PROPOSED / "engine"))


def _is_staged_test_tree(path):
    try:
        relative = Path(os.path.abspath(os.fspath(path))).relative_to(STAGE)
    except (TypeError, ValueError):
        return False
    return bool(relative.parts) and relative.parts[0].startswith("pytest-")


def main():
    real_mkdir = os.mkdir

    def mkdir_with_inherited_test_acl(path, mode=0o777, *, dir_fd=None):
        if os.name == "nt" and mode == 0o700 and _is_staged_test_tree(path):
            mode = 0o777
        return real_mkdir(path, mode, dir_fd=dir_fd)

    os.mkdir = mkdir_with_inherited_test_acl
    try:
        import pytest
        return pytest.main(sys.argv[1:])
    finally:
        os.mkdir = real_mkdir


if __name__ == "__main__":
    raise SystemExit(main())
