"""Path scope and error-class helpers shared by the ``qa`` and ``editorial`` verbs.

A file a stage reads must live inside the episode root unless the caller names it in an explicit
allow-list (``--allow-outside``): the shared studio logo is the one expected case.  Receipts never
echo absolute paths: they show the episode-relative path, or only the file name when outside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..config.loader import ConfigViolation, ResolvedConfig, resolve_episode
from ..core.errors import Refused, Uncertain


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def require_scoped(path: Path | str, root: Path, allow: Iterable[Path | str], label: str) -> Path:
    """The resolved path if it is inside ``root`` or covered by ``allow`` (a file or a folder)."""
    resolved = Path(path).resolve()
    if _inside(resolved, Path(root).resolve()):
        return resolved
    if any(_inside(resolved, Path(item).resolve()) for item in allow):
        return resolved
    raise Refused(f"{label} is outside the episode root and not allow-listed: {resolved.name} "
                  "(pass --allow-outside to name an expected shared file)")


def shown_path(path: Path | str, root: Path) -> str:
    """Episode-relative POSIX path for receipts; just the file name when outside the root."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return resolved.name


def resolve_episode_or_uncertain(ref: str) -> ResolvedConfig:
    """``resolve_episode`` where a missing episode is an unreadable input (exit 2), not a rule (exit 1)."""
    try:
        return resolve_episode(ref)
    except ConfigViolation:
        raise
    except Refused as error:
        raise Uncertain(str(error)) from error
