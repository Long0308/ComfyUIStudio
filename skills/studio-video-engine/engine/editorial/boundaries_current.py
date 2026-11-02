"""Quy ước ``boundaries.json`` hiện hành: bản vật chất hoá + biên nhận ``boundaries.current.json``.

Mọi bên ghi (``boundaries write``, ``boundaries swap``) ghi theo thứ tự: file ``versions/`` -> marker
``boundaries.publishing`` -> ``boundaries.json`` -> biên nhận -> xoá marker.  Bên đọc kiểm sha256 của ``boundaries.json``
với biên nhận; không có biên nhận (episode cũ) thì như trước, TRỪ KHI marker còn đó (publish dang dở: từ chối).

STAMP-2: biên nhận và marker mang ``engine_tree_sha256`` (``write_json_atomic(..., stamp=True)``).  Danh tính của biên
nhận khi so là NỘI DUNG (``receipt_identity``), không phải byte: publish không đổi gì thì KHÔNG ghi lại biên nhận, kể cả
khi cây engine đã khác (dấu vẫn chỉ đúng engine đã ghi ``boundaries.json``); publish thật ghi biên nhận mới có dấu mới.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused, Uncertain
from ..core.io import (canonical_sha256, pretty_json, read_json, sha256_bytes, sha256_file, write_atomic,
                       write_json_atomic, write_once)

RECEIPT_NAME = "boundaries.current.json"
RECEIPT_SCHEMA = "jjv/boundaries-current/v1"
MARKER_NAME = "boundaries.publishing"
MARKER_SCHEMA = "jjv/boundaries-publishing/v1"
IDENTITY_FIELDS = ("schema", "version", "path", "sha256", "writer", "inputs_digest")
_RETRIES = 8


def inputs_digest(document: dict) -> str:
    """Digest of the boundaries content a writer was asked to produce (draft marking excluded)."""
    return canonical_sha256(document, mode="utf8")


def _suffix(path: Path) -> int:
    return int(re.search(r"-v(\d+)\.json$", path.name).group(1))   # type: ignore[union-attr]


def _versions(folder: Path, prefix: str) -> list[tuple[int, Path]]:
    if not folder.is_dir():
        return []
    found = [(_suffix(p), p) for p in folder.glob(f"{prefix}-v[0-9][0-9][0-9]*.json") if re.fullmatch(
        re.escape(prefix) + r"-v\d{3,}\.json", p.name)]
    return sorted(found)


def next_version(folder: Path, prefix: str) -> int:
    """The number a new (different) payload would get: max suffix + 1."""
    existing = _versions(folder, prefix)
    return (existing[-1][0] if existing else 0) + 1


def write_version(folder: Path, prefix: str, payload: bytes) -> tuple[int, bool, Path, str]:
    """``(version, reused, path, sha256)``: identical LATEST reused, else max suffix + 1, exclusive create, retried."""
    for _ in range(_RETRIES):
        existing = _versions(folder, prefix)
        if existing and existing[-1][1].read_bytes() == payload:
            return existing[-1][0], True, existing[-1][1], sha256_file(existing[-1][1])
        version = (existing[-1][0] if existing else 0) + 1
        target = folder / f"{prefix}-v{version:03d}.json"
        try:
            return version, False, target, write_once(target, payload)
        except Refused:   # someone created that number first: look again
            continue
    raise Refused(f"could not allocate a {prefix} version in {folder} after {_RETRIES} tries")


def read_receipt(out: Path) -> dict | None:
    path = Path(out) / RECEIPT_NAME
    return read_json(path) if path.is_file() else None


def receipt_identity(receipt: Any) -> dict | None:
    """What a receipt certifies (its provenance header left out); ``None`` for a document that is not a receipt."""
    return {key: receipt.get(key) for key in IDENTITY_FIELDS} if isinstance(receipt, dict) else None


def _write_receipt(out: Path, receipt: dict) -> None:
    """Write the stamped receipt unless the one on disk already certifies the same content (no-op publish)."""
    try:
        existing = read_receipt(out)
    except Uncertain:   # unreadable receipt: replace it
        existing = None
    if receipt_identity(existing) != receipt_identity(receipt):
        write_json_atomic(out / RECEIPT_NAME, receipt, mode="utf8", stamp=True)


def publish(out: Path, document: dict, *, version: int, version_path: str, writer: str) -> str:
    """Marker -> ``boundaries.json`` -> receipt -> remove marker; returns the sha256 of ``boundaries.json``.

    The marker (target version + sha) exists for the whole window in which ``boundaries.json`` and the receipt may
    disagree, so a crash there is never read as a legacy folder."""
    out = Path(out)
    payload = pretty_json(document, mode="utf8")
    marker = {"schema": MARKER_SCHEMA, "version": version, "path": version_path, "sha256": sha256_bytes(payload),
              "writer": writer}
    write_json_atomic(out / MARKER_NAME, marker, mode="utf8", stamp=True)
    digest = write_atomic(out / "boundaries.json", payload)
    receipt = {"schema": RECEIPT_SCHEMA, "version": version, "path": version_path, "sha256": digest, "writer": writer,
               "inputs_digest": inputs_digest(document)}
    _write_receipt(out, receipt)
    (out / MARKER_NAME).unlink(missing_ok=True)
    return digest


def recover(out: Path) -> bool:
    """Finish an interrupted publish from the versioned file the marker names; False when there is none."""
    out = Path(out)
    marker_path = out / MARKER_NAME
    if not marker_path.is_file():
        return False
    marker: Any = read_json(marker_path)
    source = out / str(marker.get("path", "")) if isinstance(marker, dict) else None
    if source is None or not source.is_file() or sha256_file(source) != marker.get("sha256"):
        raise Refused("interrupted publish cannot be completed: the versioned file the marker names is missing or "
                      "changed; re-run `jjv editorial boundaries write`")
    publish(out, read_json(source), version=marker["version"], version_path=marker["path"], writer=marker["writer"])
    return True


def verify(boundaries_path: Path) -> None:
    """Refuse on an interrupted publish, or when a receipt sits beside ``boundaries_path`` and the file no longer matches."""
    receipt_path = Path(boundaries_path).parent / RECEIPT_NAME
    if Path(boundaries_path).name != "boundaries.json":
        return
    if (receipt_path.parent / MARKER_NAME).is_file():
        raise Refused("interrupted publish: boundaries.json may not match its receipt; re-run the same "
                      "`jjv editorial boundaries write` (or `boundaries swap`) command to complete it")
    if not receipt_path.is_file():
        return
    receipt: Any = read_json(receipt_path)
    if not isinstance(receipt, dict) or sha256_file(Path(boundaries_path)) != receipt.get("sha256"):
        raise Refused("boundaries.json does not match boundaries.current.json (edited by hand or an older run left it "
                      "stale); re-run `jjv editorial boundaries write` or restore the versioned file")


def staleness(out: Path, document: dict) -> dict:
    receipt = read_receipt(out)
    if receipt is None:
        return {"current_version": None, "current_is_stale": None}   # no receipt: unknown, not "fresh"
    return {"current_version": receipt.get("version"),
            "current_is_stale": receipt.get("inputs_digest") != inputs_digest(document)}
