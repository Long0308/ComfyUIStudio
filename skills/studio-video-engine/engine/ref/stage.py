"""``jjv ref stage``: đưa ảnh tham chiếu NỘI BỘ (đã có trong thư viện local) vào thư mục input của ComfyUI, kèm nguồn gốc.

Luật của động từ này (không phụ thuộc domain nào):

- Chỉ chọn qua ``by-type/<type>/<group>/INDEX.csv``; file nguồn được tìm trong thư mục nhóm theo thứ tự
  ``full/<id>.*`` (bản đầy đủ) -> ``thumbs/<id>.*`` (thumbnail) -> ``<id>.*`` (nằm ngay trong nhóm), và phải nằm
  TRONG thư viện (symlink thoát ra ngoài bị từ chối).
- Quyền theo :mod:`engine.ref.license`: nhóm có status dùng-nội-bộ VÀ id nằm trong kept set của nhóm VÀ sha256 khớp
  kept set khi index có sha.  Thiếu một điều kiện là từ chối; cả lượt bị từ chối khi có bất kỳ dòng nào bị từ chối.
- Mặc định là dry-run: lập kế hoạch, băm sha256 nguồn, kiểm tra đích, KHÔNG ghi gì. ``--apply`` mới copy
  (copy, không bao giờ move) qua :func:`engine.comfy.staging.link_new_file` (temp -> verify -> ``os.link``,
  không ghi đè; file đã có cùng sha là ``present`` và được bỏ qua; khác sha là xung đột -> cả lượt bị từ chối).
- Manifest ``<input>/reference-library/manifests/stage-<id>.json`` là tài liệu deterministic theo lựa chọn
  (không có timestamp) nên chạy lại cùng lựa chọn là no-op; thời điểm copy ghi ở ``STAGED-LEDGER.jsonl``.
- Không mạng, không GPU, không xoá.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..comfy.staging import link_new_file
from ..core.errors import Refused, Uncertain
from ..core.io import canonical_sha256, sha256_file, write_json_once
from ..core.paths import require_inside
from .library import RefEntry, find_entry_by_id, search_entries
from .license import LICENSE_STATUS_FILE, LicenseStatusFile, load_license_status, resolve_grant

MANIFEST_SCHEMA = "jjv/ref-stage-manifest/v1"
STAGE_DIR = "reference-library"
MANIFESTS_DIR = "manifests"
LEDGER_FILE = "STAGED-LEDGER.jsonl"
DEFAULT_LIMIT = 10
_IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")
# (tên biến thể, thư mục con trong nhóm) theo thứ tự ưu tiên; "" là chính thư mục nhóm
_VARIANTS = (("full", "full"), ("thumb", "thumbs"), ("root", ""))

REASON_SOURCE_MISSING = "source-file-missing"
REASON_SOURCE_OUTSIDE = "source-outside-library"
REASON_NAME_CONFLICT = "staged-name-conflict"


@dataclass(frozen=True)
class StageItem:
    id: str
    type: str
    group: str
    variant: str
    index_path: str  # posix, tương đối so với library_root
    source_path: Path
    source_sha256: str
    bytes: int
    license_status: str
    license_source: str
    kept_set: dict[str, Any]
    staged_path: str  # posix, tương đối so với thư mục input của ComfyUI
    target: Path
    state: str  # "present" | "missing" | "copied"

    def manifest_row(self) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "group": self.group, "variant": self.variant,
            "index_path": self.index_path, "source_path": str(self.source_path),
            "source_sha256": self.source_sha256, "bytes": self.bytes,
            "license_status": self.license_status, "license_source": self.license_source, "kept_set": self.kept_set,
            "staged_path": self.staged_path,
        }

    def report_row(self) -> dict[str, Any]:
        return {**self.manifest_row(), "state": self.state}


@dataclass(frozen=True)
class StageRefusal:
    id: str
    type: str
    group: str
    reason: str
    detail: str

    def report_row(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "group": self.group, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class StagePlan:
    library_root: Path
    comfy_input_dir: Path
    license_status_file: LicenseStatusFile | None
    items: tuple[StageItem, ...]
    refused: tuple[StageRefusal, ...]
    manifest_id: str
    manifest_document: dict[str, Any]

    @property
    def stage_root(self) -> Path:
        return self.comfy_input_dir / STAGE_DIR

    @property
    def manifest_path(self) -> Path:
        return self.stage_root / MANIFESTS_DIR / f"stage-{self.manifest_id}.json"

    @property
    def ledger_path(self) -> Path:
        return self.stage_root / LEDGER_FILE


# ---- lựa chọn ------------------------------------------------------------------------------
def _safe_name(text: str, label: str) -> str:
    if not text or text in {".", ".."} or Path(text).name != text or text.startswith("."):
        raise Refused(f"{label} {text!r} is unsafe as a path component")
    return text


def select_entries(library_root: Path, *, ids: list[str] | None, ref_type: str | None,
                   series: str | None, limit: int | None) -> list[RefEntry]:
    if ids:
        if series is not None or limit is not None:
            raise Refused("--series and --limit go with --type, not with --ids")
        wanted = [token.strip() for raw in ids for token in str(raw).split(",") if token.strip()]
        if not wanted:
            raise Refused("--ids names no reference id")
        if len(set(wanted)) != len(wanted):
            raise Refused("--ids repeats an id")
        return [find_entry_by_id(library_root, item_id) for item_id in wanted]
    if not ref_type:
        raise Refused("give --ids or --type")
    return search_entries(library_root, ref_type, group=series, limit=DEFAULT_LIMIT if limit is None else limit)


def _locate_source(library_root: Path, entry: RefEntry) -> tuple[str, Path] | None:
    group_dir = library_root / "by-type" / entry.type / entry.group
    for variant, sub in _VARIANTS:
        base = group_dir / sub if sub else group_dir
        for suffix in _IMAGE_SUFFIXES:
            candidate = base / f"{entry.id}{suffix}"
            if candidate.is_file():
                return variant, candidate
    return None


def _index_relative(library_root: Path, index_path: Path) -> str:
    try:
        return index_path.resolve().relative_to(library_root).as_posix()
    except ValueError:
        return index_path.name


# ---- kế hoạch ------------------------------------------------------------------------------
def _plan_entry(entry: RefEntry, library_root: Path, comfy_input_dir: Path,
                status_file: LicenseStatusFile | None) -> StageItem | StageRefusal:
    _safe_name(entry.id, "reference id")
    _safe_name(entry.type, "reference type")
    _safe_name(entry.group, "reference group")

    def refuse(reason: str, detail: str) -> StageRefusal:
        return StageRefusal(entry.id, entry.type, entry.group, reason, detail)

    grant, refusal = resolve_grant(entry, status_file)
    if grant is None or grant.kept_set is None:
        return refuse(*(refusal or ("license-status-missing", "no grant")))
    located = _locate_source(library_root, entry)
    if located is None:
        return refuse(REASON_SOURCE_MISSING,
                      f"no full/, thumbs/ or group file named {entry.id}.* under by-type/{entry.type}/{entry.group}")
    variant, found = located
    try:
        source_path = require_inside(found, library_root, "reference source")
    except Refused as error:
        return refuse(REASON_SOURCE_OUTSIDE, f"{found} resolves outside the library: {error}")
    digest = sha256_file(source_path)
    kept_refusal = grant.kept_set.check(entry.id, digest, variant)
    if kept_refusal is not None:
        return refuse(*kept_refusal)
    name = source_path.name
    target = require_inside(comfy_input_dir / STAGE_DIR / entry.type / entry.group / name, comfy_input_dir,
                            "ComfyUI input")
    staged_path = f"{STAGE_DIR}/{entry.type}/{entry.group}/{name}"
    state = "missing"
    if target.exists():
        if not target.is_file() or sha256_file(target) != digest:
            found_sha = sha256_file(target) if target.is_file() else "not-a-file"
            return refuse(REASON_NAME_CONFLICT,
                          f"{staged_path} already holds different bytes (expected {digest}, found {found_sha})")
        state = "present"
    return StageItem(entry.id, entry.type, entry.group, variant, _index_relative(library_root, entry.index_path),
                     source_path, digest, source_path.stat().st_size, grant.status, "license-status-file",
                     grant.kept_set.report(), staged_path, target, state)


def _manifest_document(library_root: Path, comfy_input_dir: Path, status_file: LicenseStatusFile | None,
                       items: tuple[StageItem, ...]) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "library_root": str(library_root),
        "comfy_input_dir": str(comfy_input_dir),
        "license_status_file": None if status_file is None else status_file.report(),
        "items": [item.manifest_row() for item in items],
    }
    manifest_id = canonical_sha256(body, mode="ascii")[:12]
    return manifest_id, {"schema": MANIFEST_SCHEMA, "manifest_id": manifest_id,
                         **{key: value for key, value in body.items() if key != "schema"}}


def plan_stage(library_root: Path, comfy_input_dir: Path, *, ids: list[str] | None = None,
               ref_type: str | None = None, series: str | None = None, limit: int | None = None,
               license_status_path: Path | None = None) -> StagePlan:
    """Lập kế hoạch (không ghi gì): chọn dòng, giải quyền (status + kept set), băm nguồn, kiểm tra đích."""
    library_root = Path(library_root).resolve()
    comfy_input_dir = Path(comfy_input_dir)
    if not comfy_input_dir.is_dir():
        raise Refused(f"ComfyUI input folder is not a directory: {comfy_input_dir}")
    comfy_input_dir = comfy_input_dir.resolve()
    status_file = load_license_status(library_root, Path(license_status_path) if license_status_path
                                      else library_root / LICENSE_STATUS_FILE)
    entries = select_entries(library_root, ids=ids, ref_type=ref_type, series=series, limit=limit)
    items: list[StageItem] = []
    refused: list[StageRefusal] = []
    for entry in entries:
        outcome = _plan_entry(entry, library_root, comfy_input_dir, status_file)
        (items if isinstance(outcome, StageItem) else refused).append(outcome)  # type: ignore[arg-type]
    ordered = tuple(sorted(items, key=lambda item: (item.type, item.group, item.id)))
    manifest_id, document = _manifest_document(library_root, comfy_input_dir, status_file, ordered)
    return StagePlan(library_root, comfy_input_dir, status_file, ordered, tuple(refused), manifest_id, document)


# ---- thực thi -------------------------------------------------------------------------------
def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _append_ledger(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise Uncertain(f"a reference was staged but the ledger line could not be appended: {error}",
                        evidence={"ledger": str(path), "id": row.get("id")}) from error


def apply_stage(plan: StagePlan) -> StagePlan:
    """Copy từng file còn thiếu (không ghi đè), ghi ledger từng dòng, rồi ghi manifest write-once."""
    if plan.refused:
        raise Refused(f"{len(plan.refused)} of {len(plan.items) + len(plan.refused)} candidates refused; nothing staged")
    done: list[StageItem] = []
    for item in plan.items:
        if item.state == "present":
            done.append(item)
            continue
        link_new_file(item.source_path, item.target, item.source_sha256, f"staged reference {item.id}")
        _append_ledger(plan.ledger_path, {
            "utc_time": _utc_now_text(), "manifest_id": plan.manifest_id, "id": item.id,
            "sha256": item.source_sha256, "staged_path": item.staged_path, "source_path": str(item.source_path),
        })
        done.append(StageItem(**{**item.__dict__, "state": "copied"}))
    write_json_once(plan.manifest_path, plan.manifest_document, mode="ascii")
    return StagePlan(plan.library_root, plan.comfy_input_dir, plan.license_status_file, tuple(done), plan.refused,
                     plan.manifest_id, plan.manifest_document)


def report(plan: StagePlan, *, applied: bool) -> dict[str, Any]:
    """Một JSON cho stdout; ``ok`` chỉ khi không có dòng nào bị từ chối."""
    counts = {
        "selected": len(plan.items) + len(plan.refused),
        "stageable": len(plan.items),
        "present": sum(item.state == "present" for item in plan.items),
        "copied": sum(item.state == "copied" for item in plan.items),
        "refused": len(plan.refused),
    }
    status_file = plan.license_status_file
    body: dict[str, Any] = {
        "ok": not plan.refused,
        "dry_run": not applied,
        "library_root": str(plan.library_root),
        "comfy_input_dir": str(plan.comfy_input_dir),
        "stage_root": str(plan.stage_root),
        "license_status_file": None if status_file is None else status_file.report(),
        "manifest": str(plan.manifest_path) if applied else None,
        "manifest_id": plan.manifest_id,
        "counts": counts,
        "items": [item.report_row() for item in plan.items],
        "refused": [refusal.report_row() for refusal in plan.refused],
    }
    if plan.refused:
        body["error"] = (f"{counts['refused']} of {counts['selected']} candidates refused "
                         f"({', '.join(sorted({r.reason for r in plan.refused}))}); nothing is staged")
    return body
