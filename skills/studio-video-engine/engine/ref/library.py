"""Read-only lookup over the generated ``by-type/<type>/<group>/INDEX.csv`` files."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from ..config.loader import REPO_ROOT
from ..core.errors import Refused

SUPPORTED_TYPES = ("pose", "costume", "face")
_TAG_SPLIT = re.compile(r"[;,|]")


@dataclass(frozen=True)
class RefEntry:
    """One index row, retaining its type/group provenance."""

    id: str
    type: str
    group: str
    source_url: str
    row: Mapping[str, str]
    index_path: Path


def default_library_root() -> Path:
    """The canonical local library, resolved from the repository rather than the cwd."""

    return REPO_ROOT / "production-local" / "reference-library"


def _require_type(ref_type: str) -> None:
    if ref_type not in SUPPORTED_TYPES:
        raise Refused(f"unknown reference type {ref_type!r}; choose one of {SUPPORTED_TYPES}")


def _index_files(library_root: Path, ref_type: str, group: str | None) -> Iterator[tuple[str, Path]]:
    _require_type(ref_type)
    root = Path(library_root)
    if not root.is_dir():
        raise Refused(f"reference-library root is not a directory: {root}")
    type_root = root / "by-type" / ref_type
    if not type_root.is_dir():
        return
    if group is not None:
        if not group or group in (".", "..") or "/" in group or "\\" in group:
            return
        candidate = type_root / group / "INDEX.csv"
        if candidate.is_file():
            yield group, candidate
        return
    for group_dir in sorted((path for path in type_root.iterdir() if path.is_dir()),
                            key=lambda path: path.name.casefold()):
        candidate = group_dir / "INDEX.csv"
        if candidate.is_file():
            yield group_dir.name, candidate


def _matches_tag(row: Mapping[str, str], needle: str) -> bool:
    wanted = needle.strip().casefold()
    if not wanted:
        return True
    for key, value in row.items():
        if key in (None, "id", "source_url") or not value:
            continue
        for token in _TAG_SPLIT.split(str(value)):
            if token.strip().casefold() == wanted:
                return True
    return False


def iter_entries(library_root: Path, ref_type: str, *, group: str | None = None,
                 tag: str | None = None) -> Iterator[RefEntry]:
    """Yield matching rows in stable group/file order."""

    for group_name, index_path in _index_files(Path(library_root), ref_type, group):
        try:
            with index_path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = set(reader.fieldnames or ())
                missing = {"id", "source_url"} - fields
                if missing:
                    raise Refused(f"{index_path} lacks required columns: {sorted(missing)}")
                for row_number, row in enumerate(reader, start=2):
                    item_id = (row.get("id") or "").strip()
                    source_url = (row.get("source_url") or "").strip()
                    if not item_id or not source_url:
                        raise Refused(f"{index_path}:{row_number} has an empty id or source_url")
                    if tag is not None and not _matches_tag(row, tag):
                        continue
                    yield RefEntry(item_id, ref_type, group_name, source_url, dict(row), index_path)
        except OSError as error:
            raise Refused(f"cannot read reference index {index_path}: {error}") from error


def search_entries(library_root: Path, ref_type: str, *, group: str | None = None,
                   tag: str | None = None, limit: int = 50) -> list[RefEntry]:
    """Return at most ``limit`` local index entries; this function never uses the network."""

    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise Refused("--limit must be a positive integer")
    entries: list[RefEntry] = []
    for entry in iter_entries(library_root, ref_type, group=group, tag=tag):
        entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def find_entry_by_id(library_root: Path, item_id: str) -> RefEntry:
    """Find exactly one index row for an id across pose, costume and face."""

    wanted = item_id.strip()
    if not wanted:
        raise Refused("--id cannot be empty")
    matches = [
        entry
        for ref_type in SUPPORTED_TYPES
        for entry in iter_entries(library_root, ref_type)
        if entry.id == wanted
    ]
    if not matches:
        raise Refused(f"reference id {wanted!r} was not found in the local INDEX.csv files")
    if len(matches) > 1:
        where = ", ".join(f"{entry.type}/{entry.group}" for entry in matches)
        raise Refused(f"reference id {wanted!r} is ambiguous ({where}); refusing to choose an image")
    return matches[0]
