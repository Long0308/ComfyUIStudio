"""Which engine produced a receipt: ``engine_tree_sha256`` and the helpers that stamp it.

The tree is ``engine/**``, ``recipes/**`` and ``bin/**`` of the skill.  Left out: ``__pycache__``,
``tests`` folders, documentation (``*.md``), editor/temp/backup files (``*.tmp``, ``*.bak*``,
``*~``, dot-files such as the ``.<name>.<uuid>.tmp`` that ``write_once`` leaves for a moment) and
anything that vanishes while the walk is running (a concurrent writer's temp file is not part of
the engine).  The digest covers every kept file's relative path and sha256, sorted, so renaming,
adding, removing or editing a file changes it.

``stamp`` is opt-in on purpose: a deterministic, write-once artefact (build-config output) must not
change its bytes when the engine changes; receipts that are evidence of a run take the header.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
TREE_DIRS = ("engine", "recipes", "bin")
EXCLUDED_DIRS = frozenset({"__pycache__", "tests", ".pytest_cache", "node_modules"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".tmp", ".md", "~")


def _kept(name: str) -> bool:
    return not (name.startswith(".") or name.endswith(EXCLUDED_SUFFIXES) or ".bak" in name)


def tree_files(skill_root: Path = SKILL_ROOT) -> list[str]:
    """Relative POSIX paths of the kept files, sorted."""
    found: list[str] = []
    for top in TREE_DIRS:
        base = Path(skill_root) / top
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS)
            for name in files:
                if _kept(name):
                    found.append((Path(folder) / name).relative_to(skill_root).as_posix())
    return sorted(found)


def engine_tree_sha256(skill_root: Path = SKILL_ROOT) -> dict:
    """``{"engine_tree_sha256", "file_count"}``; files that vanish during the walk are skipped."""
    digest, count = hashlib.sha256(), 0
    for relative in tree_files(skill_root):
        try:
            payload = (Path(skill_root) / relative).read_bytes()
        except OSError:
            continue  # deleted/locked between listing and reading: a temp file of a concurrent writer
        digest.update(relative.encode("utf-8") + b"\0" + hashlib.sha256(payload).hexdigest().encode("ascii") + b"\n")
        count += 1
    return {"engine_tree_sha256": digest.hexdigest(), "file_count": count}


def receipt_header(skill_root: Path = SKILL_ROOT) -> dict:
    """The provenance fields every receipt of a run records."""
    tree = engine_tree_sha256(skill_root)
    return {"engine_tree_sha256": tree["engine_tree_sha256"], "engine_tree_files": tree["file_count"]}


def stamp(receipt: dict, skill_root: Path = SKILL_ROOT) -> dict:
    """A copy of ``receipt`` with the provenance header; a header already present is never replaced."""
    return {**receipt_header(skill_root), **receipt}
