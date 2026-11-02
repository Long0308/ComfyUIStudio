"""Manifest append planning for the ComfyUI review workflow manifest.

Plans the exact bytes that append one entry to ``WORKFLOW-MANIFEST.json``. Pure: nothing is
written here. Existing entries and top-level bytes are kept verbatim (spliced, never re-sorted or
re-serialised); every refusal is decided before the caller writes anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.errors import Refused
from ..core.io import pretty_json
from ..layout.context import Context

OWN_MANIFEST_SCHEMAS = frozenset({"jjv/workflow-manifest/v1"})
_DERIVED_TOP_KEYS = ("entries", "entry_count", "counts_by_kind", "counts_by_stage", "roots")


def _top_indent(text: str) -> str:
    """Indentation of the top-level keys (the whitespace before the first key)."""
    match = re.search(r'\{\r?\n([ \t]*)"', text)
    if match is None:
        raise Refused("manifest has no top-level keys to append to")
    return match.group(1)


def _entries_span(text: str, top: str) -> tuple[int, int]:
    """Byte-exact span ``[start, end)`` of the top-level ``entries`` array in ``text``."""
    match = re.search(r'\n' + re.escape(top) + r'"entries"\s*:\s*\[', text)
    if match is None:
        raise Refused("manifest has no top-level entries array")
    start = match.end() - 1
    _, end = json.JSONDecoder().raw_decode(text, start)
    return start, end


def _splice_entries(text: str, top: str, new_entries: list[dict[str, Any]], nl: str) -> str:
    """Insert ``new_entries`` before the closing bracket; every earlier byte stays as it was."""
    start, end = _entries_span(text, top)
    block = text[start:end]
    close = block.rindex("]")
    if block[1:close].strip() == "":
        new_block = json.dumps(new_entries, ensure_ascii=True, indent=top or 2).replace("\n", nl + top)
    else:
        last = block.rindex("}", 0, close)
        first = block.index("{")
        line_start = block.rfind("\n", 0, first) + 1
        elem = block[line_start:first]
        if elem.strip():
            raise Refused("manifest entries are not one-object-per-line; refusing to splice")
        added = "".join(
            "," + nl + elem + json.dumps(item, ensure_ascii=True, indent=top or 2).replace("\n", nl + elem)
            for item in new_entries
        )
        new_block = block[: last + 1] + added + block[last + 1:]
    return text[:start] + new_block + text[end:]


def _set_top_value(text: str, top: str, key: str, value: Any, nl: str) -> str:
    """Replace one top-level value in place, or add the key at the end if it is missing."""
    rendered = json.dumps(value, ensure_ascii=True, indent=top or 2).replace("\n", nl + top)
    match = re.search(r'\n' + re.escape(top) + re.escape(json.dumps(key)) + r'\s*:\s*', text)
    if match is not None:
        _, value_end = json.JSONDecoder().raw_decode(text, match.end())
        return text[: match.end()] + rendered + text[value_end:]
    close = text.rstrip().rfind("}")
    return text[:close].rstrip() + "," + nl + top + json.dumps(key) + ": " + rendered + nl + text[close:]


def _append_only_manifest_text(raw: str, entry: dict[str, Any], episode_root: Path) -> tuple[str, list[Any]]:
    """Return the new manifest text plus the existing entries it must keep verbatim."""
    body = raw.lstrip("\ufeff")
    parsed = json.loads(body)
    top = _top_indent(body)
    existing = list(parsed["entries"])
    kinds = dict(parsed.get("counts_by_kind") or {}) if isinstance(parsed.get("counts_by_kind"), dict) else {}
    stages = dict(parsed.get("counts_by_stage") or {}) if isinstance(parsed.get("counts_by_stage"), dict) else {}
    kind, stage = str(entry.get("kind", "unknown")), str(entry.get("stage", "unknown"))
    kinds[kind] = kinds.get(kind, 0) + 1
    stages[stage] = stages.get(stage, 0) + 1
    nl = "\r\n" if "\r\n" in body else "\n"

    start, end = _entries_span(body, top)
    kept_bytes = body[: start + body[start:end].rindex("}") + 1] if existing else body[:start + 1]
    text = _splice_entries(body, top, [entry], nl)
    if not text.startswith(kept_bytes):
        raise Refused("existing manifest bytes would change; manifest left unchanged")
    text = _set_top_value(text, top, "entry_count", len(existing) + 1, nl)
    text = _set_top_value(text, top, "counts_by_kind", kinds, nl)
    text = _set_top_value(text, top, "counts_by_stage", stages, nl)
    if parsed.get("schema") in OWN_MANIFEST_SCHEMAS:
        roots = {**(parsed.get("roots") or {}), "episode": str(episode_root.resolve())}
        text = _set_top_value(text, top, "roots", roots, nl)
    return text, existing


def _manifest_update_bytes(ctx: Context, manifest_path: Path, manifest: dict[str, Any],
                           entry: dict[str, Any], episode_root: Path) -> bytes | None:
    """Plan the manifest bytes that append ``entry``. Pure: writes nothing and refuses before any write.

    Existing entries are never re-sorted or re-serialised. A path that is already listed is only
    accepted when the row is identical (``None``: no-op); a different row under the same path is
    refused instead of replaced.
    """
    if not manifest_path.is_file():
        new_manifest = {
            **manifest,
            "entries": [entry],
            "entry_count": 1,
            "episode_id": manifest.get("episode_id") or ctx.episode_id,
            "roots": {**(manifest.get("roots") or {}), "episode": str(episode_root.resolve())},
            "counts_by_kind": {str(entry.get("kind", "unknown")): 1},
            "counts_by_stage": {str(entry.get("stage", "unknown")): 1},
        }
        return pretty_json(new_manifest, mode="ascii")
    raw = manifest_path.read_bytes().decode("utf-8")
    existing = json.loads(raw.lstrip("\ufeff"))["entries"]
    for item in existing:
        if item.get("path") == entry["path"]:
            if item == entry:
                return None
            raise Refused(f"{manifest_path} already lists {entry['path']} with different content; not replacing it")
    new_text, kept = _append_only_manifest_text(raw, entry, episode_root)
    check = json.loads(new_text.lstrip("\ufeff"))
    if check["entries"][: len(kept)] != kept or check["entries"][-1] != entry or len(check["entries"]) != len(kept) + 1:
        raise Refused("append-only check failed; manifest left unchanged")
    original = json.loads(raw.lstrip("\ufeff"))
    for key, value in original.items():
        if key not in _DERIVED_TOP_KEYS and check.get(key) != value:
            raise Refused(f"manifest field {key!r} changed during append; manifest left unchanged")
    return new_text.encode("utf-8")
