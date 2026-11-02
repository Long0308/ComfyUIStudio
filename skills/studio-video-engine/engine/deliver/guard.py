"""Write-target containment and canonical sidecar placement for the delivery verbs.

Pure path logic: nothing here creates, writes or deletes. A write target is never resolved through
``Path.resolve`` (which follows links silently); it is joined lexically, checked against its declared
root, and every component below that root is refused if it is a symlink or a Windows junction.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from ..core.errors import Refused

FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # set on Windows symlinks and junctions
EPISODE_FILE = ("engine", "episode.json")


def is_reparse_point(path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def contained_write(candidate, root, label: str) -> Path:
    """Absolute form of ``candidate`` (already joined to its base, not resolved), refused unless it lies
    strictly beneath ``root`` and no component below ``root`` is a symlink or junction."""
    root_abs = Path(os.path.abspath(os.fspath(root)))
    target = Path(os.path.abspath(os.fspath(candidate)))
    try:
        rel = os.path.relpath(target, root_abs)
    except ValueError as exc:  # different drive
        raise Refused(f"{label} is outside {root_abs}: {target}") from exc
    parts = Path(rel).parts
    if not parts or parts[0] == ".." or Path(rel).is_absolute():
        raise Refused(f"{label} escapes {root_abs}: {target}")
    cursor = root_abs
    for part in parts:
        cursor = cursor / part
        if is_reparse_point(cursor):
            raise Refused(f"{label} passes through a symlink or junction: {cursor}")
    return target


def in_episode_tree(target) -> bool:
    """True when some ancestor of ``target`` is an episode root (holds ``engine/episode.json``)."""
    return any(parent.joinpath(*EPISODE_FILE).is_file() for parent in Path(target).parents)


def canonical_placement(target, own, label: str) -> bool:
    """True when ``target`` is this episode's own canonical sidecar. Any other path inside an episode tree is
    refused (a canonical-looking or alternate sidecar there would bypass write-once); an explicit path outside
    every episode tree is allowed and is non-canonical (staging or scratch use)."""
    if os.path.normcase(str(target)) == os.path.normcase(str(own)):
        return True
    if in_episode_tree(target):
        raise Refused(f"{label} {target} lies inside an episode tree; only the episode's own "
                      "engine/delivery.json may be written there")
    return False
