"""Trạng thái license và KEPT SET của thư viện tham chiếu (``<library>/LICENSE-STATUS.json``, ``jjv/ref-license-status/v1``).

Một item chỉ được stage khi ĐỦ ba điều kiện (CR-REFSTAGE): (1) nhóm ``"<type>/<group>"`` có ``status`` dùng-nội-bộ
(kết thúc ``INTERNAL_REFERENCE_ONLY`` và không mang token phủ định như QUARANTINED/DENIED); (2) nhóm khai ``kept_set``
trỏ tới một index JSON NẰM TRONG thư viện liệt kê đúng những id user đã quyết giữ, và id của item có trong đó; (3) khi
index có cột sha256, file nguồn phải băm đúng sha đó (thumbnail của một id kept không qua được).  ``not_granted`` là
deny thực thi, thắng mọi grant.  Cột ``license_status`` trong INDEX.csv chỉ THU HỒI được một dòng, không cấp.

Tài liệu mẫu::

    {"schema": "jjv/ref-license-status/v1",
     "groups": {"pose/<series>": {"status": "KEPT_BY_USER_<date>_INTERNAL_REFERENCE_ONLY",
                                  "kept_set": {"path": "<index>.json", "items": "items", "id": "id", "sha256": "sha256",
                                               "index_sha256": "<64 hex, tuỳ chọn>"}},
                "face/<group>": {"status": "CC0_1_0_INTERNAL_REFERENCE_ONLY",
                                 "kept_set": {"path": "<list>.json", "id": "id"}}},
     "not_granted": {"costume/<group>": "lý do"}}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..core.errors import Refused
from ..core.io import read_json, sha256_file
from ..core.paths import require_inside
from .library import RefEntry

LICENSE_STATUS_SCHEMA = "jjv/ref-license-status/v1"
LICENSE_STATUS_FILE = "LICENSE-STATUS.json"
LICENSE_STATUS_COLUMN = "license_status"
INTERNAL_USE_SUFFIX = ("INTERNAL", "REFERENCE", "ONLY")
NEGATIVE_TOKENS = frozenset({"DENIED", "QUARANTINED", "REVOKED", "PENDING", "FORBIDDEN", "BLOCKED", "NOT", "NO"})

REASON_LICENSE_MISSING = "license-status-missing"
REASON_LICENSE_NOT_INTERNAL = "license-status-not-internal-use"
REASON_LICENSE_NOT_GRANTED = "license-status-not-granted"
REASON_KEPT_SET_MISSING = "kept-set-missing"
REASON_KEPT_ID_MISSING = "kept-set-missing-id"
REASON_KEPT_SHA_MISMATCH = "kept-set-sha-mismatch"

Refusal = tuple[str, str]  # (reason, detail)


def is_internal_use(status: str) -> bool:
    """Đúng hoa, ngăn bằng ``_``, kết thúc ``INTERNAL_REFERENCE_ONLY`` và KHÔNG có token phủ định ở phía trước."""
    tokens = tuple(status.strip().split("_"))
    if len(tokens) < len(INTERNAL_USE_SUFFIX) or tokens[-len(INTERNAL_USE_SUFFIX):] != INTERNAL_USE_SUFFIX:
        return False
    return not any(token in NEGATIVE_TOKENS for token in tokens[:-len(INTERNAL_USE_SUFFIX)])


@dataclass(frozen=True)
class KeptSet:
    index_path: Path
    index_rel: str
    index_sha256: str
    id_key: str
    sha_key: str | None
    rows: Mapping[str, Mapping[str, Any]]

    @property
    def sha256_bound(self) -> bool:
        return self.sha_key is not None

    def report(self) -> dict[str, Any]:
        return {"index": self.index_rel, "index_sha256": self.index_sha256, "sha256_bound": self.sha256_bound}

    def check(self, item_id: str, source_sha256: str, variant: str) -> Refusal | None:
        row = self.rows.get(item_id)
        if row is None:
            return REASON_KEPT_ID_MISSING, (f"id {item_id!r} is not in the kept set {self.index_rel} ({len(self.rows)} ids): "
                                            "an index row alone grants nothing")
        if self.sha_key is None:
            return None
        expected = str(row.get(self.sha_key))
        if expected != source_sha256:
            return REASON_KEPT_SHA_MISMATCH, (f"{self.index_rel} keeps {item_id!r} as sha256 {expected[:12]} but the "
                                              f"{variant} file on disk is {source_sha256[:12]}; only the kept bytes may be staged")
        return None


@dataclass(frozen=True)
class GroupGrant:
    status: str
    kept_set: KeptSet | None


@dataclass(frozen=True)
class LicenseStatusFile:
    path: Path
    sha256: str
    groups: Mapping[str, GroupGrant]
    not_granted: Mapping[str, str]

    def report(self) -> dict[str, Any]:
        return {"path": str(self.path), "sha256": self.sha256}


def _load_kept_set(library_root: Path, group_key: str, spec: Any) -> KeptSet:
    label = f"kept set index of {group_key}"
    if not isinstance(spec, Mapping) or not isinstance(spec.get("path"), str) or not spec["path"]:
        raise Refused(f"{LICENSE_STATUS_FILE}: {group_key}.kept_set needs a 'path'")
    given = Path(spec["path"])
    index_path = require_inside(given if given.is_absolute() else library_root / given, library_root, label)
    if not index_path.is_file():
        raise Refused(f"{label} not found: {index_path}")
    digest = sha256_file(index_path)
    pinned = spec.get("index_sha256")
    rel = index_path.relative_to(Path(library_root).resolve()).as_posix()
    if pinned is not None and pinned != digest:
        raise Refused(f"{label} {rel} has sha256 {digest} but {LICENSE_STATUS_FILE} pins {pinned}; the kept set changed: "
                      "re-review it before staging")
    id_key, sha_key, items_key = spec.get("id", "id"), spec.get("sha256"), spec.get("items")
    if not isinstance(id_key, str) or (sha_key is not None and not isinstance(sha_key, str)) or (
            items_key is not None and not isinstance(items_key, str)):
        raise Refused(f"{LICENSE_STATUS_FILE}: {group_key}.kept_set 'id'/'sha256'/'items' must be key names")
    document = read_json(index_path)
    rows = document.get(items_key) if items_key is not None and isinstance(document, Mapping) else document
    if not isinstance(rows, list):
        raise Refused(f"{label} {rel}: expected a list of rows" + (f" under {items_key!r}" if items_key else ""))
    table: dict[str, Mapping[str, Any]] = {}
    for number, row in enumerate(rows):
        item_id = row.get(id_key) if isinstance(row, Mapping) else None
        if not isinstance(item_id, str) or not item_id.strip():
            raise Refused(f"{label} {rel}: row {number} has no string {id_key!r}")
        if sha_key is not None and not isinstance(row.get(sha_key), str):
            raise Refused(f"{label} {rel}: row {item_id!r} has no string {sha_key!r}")
        if item_id in table:
            raise Refused(f"{label} {rel}: id {item_id!r} is listed twice")
        table[item_id] = row
    return KeptSet(index_path, rel, digest, id_key, sha_key, table)


def load_license_status(library_root: Path, path: Path) -> LicenseStatusFile | None:
    """Không có file là ``None`` (mọi dòng sẽ thiếu trạng thái); file hỏng hay kept set hỏng là Refused cho cả lượt."""
    path = Path(path)
    if not path.is_file():
        return None
    doc = read_json(path)
    if not isinstance(doc, Mapping) or doc.get("schema") != LICENSE_STATUS_SCHEMA:
        raise Refused(f"{path} is not a {LICENSE_STATUS_SCHEMA} document")
    groups = doc.get("groups")
    if not isinstance(groups, Mapping):
        raise Refused(f"{path}: 'groups' must be an object keyed by '<type>/<group>'")
    table: dict[str, GroupGrant] = {}
    for key, value in groups.items():
        status = value.get("status") if isinstance(value, Mapping) else None
        if not isinstance(key, str) or "/" not in key or not isinstance(status, str) or not status.strip():
            raise Refused(f"{path}: group {key!r} needs a non-empty string 'status'")
        kept = _load_kept_set(Path(library_root), key, value["kept_set"]) if "kept_set" in value else None
        table[key] = GroupGrant(status.strip(), kept)
    denied = doc.get("not_granted") or {}
    if not isinstance(denied, Mapping):
        raise Refused(f"{path}: 'not_granted' must be an object keyed by '<type>/<group>'")
    return LicenseStatusFile(path, sha256_file(path), table, {str(k): str(v) for k, v in denied.items()})


def resolve_grant(entry: RefEntry, status_file: LicenseStatusFile | None) -> tuple[GroupGrant | None, Refusal | None]:
    """Grant của nhóm cho dòng ``entry`` (status dùng-nội-bộ + kept set), hoặc lý do từ chối."""
    key = f"{entry.type}/{entry.group}"
    column = (entry.row.get(LICENSE_STATUS_COLUMN) or "").strip()
    if column and not is_internal_use(column):
        return None, (REASON_LICENSE_NOT_INTERNAL, f"index column {LICENSE_STATUS_COLUMN}={column!r} revokes this row")
    if status_file is None:
        return None, (REASON_LICENSE_MISSING, f"no {LICENSE_STATUS_FILE} in the library root")
    if key in status_file.not_granted:
        return None, (REASON_LICENSE_NOT_GRANTED, f"{key} is listed in not_granted: {status_file.not_granted[key]}")
    grant = status_file.groups.get(key)
    if grant is None:
        return None, (REASON_LICENSE_MISSING, f"no '{key}' entry in {LICENSE_STATUS_FILE} (an index column can not grant)")
    if not is_internal_use(grant.status):
        return None, (REASON_LICENSE_NOT_INTERNAL, f"status {grant.status!r} of {key} does not read as internal use "
                                                   f"(needs the suffix {'_'.join(INTERNAL_USE_SUFFIX)} and no negative token)")
    if grant.kept_set is None:
        return None, (REASON_KEPT_SET_MISSING, f"{key} has no kept_set in {LICENSE_STATUS_FILE}: nothing binds its ids to "
                                               "the user's decision")
    return grant, None


__all__ = ["KeptSet", "GroupGrant", "LicenseStatusFile", "is_internal_use", "load_license_status", "resolve_grant",
           "LICENSE_STATUS_SCHEMA", "LICENSE_STATUS_FILE", "LICENSE_STATUS_COLUMN", "REASON_LICENSE_MISSING",
           "REASON_LICENSE_NOT_INTERNAL", "REASON_LICENSE_NOT_GRANTED", "REASON_KEPT_SET_MISSING",
           "REASON_KEPT_ID_MISSING", "REASON_KEPT_SHA_MISMATCH"]
