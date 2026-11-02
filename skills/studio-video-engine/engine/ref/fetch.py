"""Fetch one reference image, with host, consent, receipt and short-window guards."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.errors import Failed, Refused, Uncertain
from ..core.io import sha256_bytes, sha256_file, write_once
from .library import find_entry_by_id

ALLOWED_HOSTS = frozenset({
    "ai-pose-gallery.pages.dev",
    "ai-costume-gallery.pages.dev",
    "ai-portrait-gallery.pages.dev",
})
FETCH_TIMEOUT_SECONDS = 30
RATE_LIMIT_SECONDS = 10.0
RECEIPTS_FILE = "ref-fetch-receipts.jsonl"
USER_AGENT = "jjv-ref/1.0 (studio reference library; one-image fetch)"
Opener = Callable[..., Any]
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


@dataclass(frozen=True)
class FetchResult:
    id: str
    file: Path
    sha256: str
    bytes: int
    utc_time: str
    receipt: Path
    source_url: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_source_url(url: str) -> str:
    """Allow only the three documented HTTPS reference-library hosts."""

    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").casefold()
    except ValueError as error:
        raise Refused(f"invalid source_url {url!r}: {error}") from error
    if parts.scheme.casefold() != "https":
        raise Refused(f"source_url must use https: {url!r}")
    if host not in ALLOWED_HOSTS:
        raise Refused(f"source_url host {host!r} is not allowed; allowed hosts: {sorted(ALLOWED_HOSTS)}")
    return url


def _safe_id(item_id: str) -> str:
    if not _SAFE_ID.fullmatch(item_id):
        raise Refused(f"reference id {item_id!r} is unsafe as a filename")
    return item_id


def _suffix(source_url: str) -> str:
    suffix = Path(urllib.parse.unquote(urllib.parse.urlsplit(source_url).path)).suffix
    return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ".img"


def _parse_utc(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recent_receipt(receipt_path: Path, item_id: str, now: datetime) -> dict[str, Any] | None:
    try:
        lines = receipt_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise Refused(f"cannot read fetch receipts {receipt_path}: {error}") from error
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("id") != item_id:
            continue
        stamp = _parse_utc(row.get("utc_time"))
        if stamp is None:
            continue
        age = (now - stamp).total_seconds()
        if -RATE_LIMIT_SECONDS < age < RATE_LIMIT_SECONDS:
            return row
    return None


def _response_header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except AttributeError:
        return ""


def _save_unique(out: Path, item_id: str, suffix: str, payload: bytes) -> tuple[Path, str]:
    digest = sha256_bytes(payload)
    for index in range(10_000):
        name = f"{item_id}{suffix}" if index == 0 else f"{item_id}-{index}{suffix}"
        candidate = out / name
        if candidate.is_file() and sha256_file(candidate) == digest:
            return candidate, digest
        if candidate.exists():
            continue
        try:
            stored = write_once(candidate, payload)
        except Refused:
            if candidate.is_file() and sha256_file(candidate) == digest:
                return candidate, digest
            continue
        return candidate, stored
    raise Failed(f"could not allocate a non-overwriting output name for reference id {item_id!r}")


def _append_receipt(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with path.open("a", encoding="utf-8", newline="") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise Uncertain(f"image was saved but its fetch receipt could not be appended: {error}",
                        evidence={"receipt": str(path)}) from error


def fetch_one(library_root: Path, item_id: str, reason: str, out: Path, *,
              opener: Opener | None = None) -> FetchResult:
    """Download exactly one indexed image and append one receipt line."""

    entry = find_entry_by_id(Path(library_root), item_id)
    source_url = validate_source_url(entry.source_url)
    safe_id = _safe_id(entry.id)
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise Refused("--reason must not be empty")

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not out_dir.is_dir():
        raise Refused(f"--out is not a directory: {out_dir}")
    receipt_path = out_dir / RECEIPTS_FILE
    now = _utc_now()
    recent = _recent_receipt(receipt_path, entry.id, now)
    if recent is not None:
        raise Refused(
            f"reference id {entry.id!r} was fetched less than {int(RATE_LIMIT_SECONDS)} seconds ago "
            f"at {recent.get('utc_time')}; wait before fetching it again"
        )

    request = urllib.request.Request(source_url, headers={"User-Agent": USER_AGENT}, method="GET")
    active_opener: Opener = urllib.request.urlopen if opener is None else opener
    try:
        with active_opener(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            validate_source_url(str(final_url))
            content_type = _response_header(response, "Content-Type").casefold()
            if content_type and not content_type.startswith("image/"):
                raise Failed(f"source answered with Content-Type {content_type!r}, not an image")
            payload = response.read()
    except (Refused, Failed):
        raise
    except urllib.error.HTTPError as error:
        raise Failed(f"reference image request answered HTTP {error.code}; no file was saved") from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise Uncertain(f"reference image request failed before a complete response: {error}") from error

    if not isinstance(payload, bytes):
        payload = bytes(payload)
    if not payload:
        raise Failed("reference image response was empty; no file was saved")

    stored_path, digest = _save_unique(out_dir, safe_id, _suffix(source_url), payload)
    stamp = _utc_text(_utc_now())
    receipt = {
        "id": entry.id,
        "url": source_url,
        "sha256": digest,
        "bytes": len(payload),
        "utc_time": stamp,
        "reason": cleaned_reason,
    }
    _append_receipt(receipt_path, receipt)
    return FetchResult(entry.id, stored_path, digest, len(payload), stamp, receipt_path, source_url)
