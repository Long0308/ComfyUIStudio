"""Review-workflow note text and GUI skeleton for ``workflow_publish.py`` (N58 split, no behaviour change)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

WORKFLOW_SCHEMA = "jjv/comfy-review-workflow/v1"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _redact(text: str) -> str:
    """Keep prompts printable without carrying credential-shaped text into outputs."""
    text = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED_KEY]", text)
    text = re.sub(r"(?i)\bbearer\s+\S+", "[REDACTED_AUTH]", text)
    text = re.sub(r"(?i)\baccess[_ -]?token\b", "[REDACTED_FIELD]", text)
    return text


def _slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return clean or "image"


def _relative(path: Path, root: Path) -> str:
    resolved, base = path.resolve(), root.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return resolved.as_posix()


def _prompt_text(receipt: dict[str, Any]) -> str:
    prompt = receipt.get("prompt")
    candidate = prompt.get("file") if isinstance(prompt, dict) else None
    if isinstance(candidate, str):
        path = Path(candidate)
        if path.is_file():
            return _redact(path.read_text(encoding="utf-8", errors="replace"))
    return "(prompt text not available)"


def _reference_hashes(receipt: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    guide = receipt.get("guide")
    if isinstance(guide, dict) and guide.get("sha256"):
        rows.append({"role": str(guide.get("role") or "guide"), "sha256": str(guide["sha256"])})
    for ref in receipt.get("ref_hashes") or []:
        if isinstance(ref, dict) and ref.get("sha256"):
            rows.append({"role": str(ref.get("role") or "reference"), "sha256": str(ref["sha256"])})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        unique[(row["role"], row["sha256"])] = row
    return list(unique.values())


def _codex_session(receipt: dict[str, Any]) -> str | None:
    runtime = receipt.get("runtime_id")
    if isinstance(runtime, str) and runtime:
        return runtime
    codex = receipt.get("codex")
    if isinstance(codex, dict) and isinstance(codex.get("session_folder"), str):
        return codex["session_folder"]
    source = receipt.get("source_path")
    if isinstance(source, str):
        match = _UUID.search(source)
        if match:
            return match.group(0)
    return None


def _account_label(receipt: dict[str, Any]) -> str | None:
    value = receipt.get("account_label")
    return _redact(str(value)) if isinstance(value, str) and value else None


def _note_text(receipt: dict[str, Any], *, stage: str, input_name: str, output_sha256: str, route: str,
               source_receipt: dict[str, Any] | None = None) -> str:
    provenance = source_receipt or receipt
    refs = _reference_hashes(provenance)
    lines = [
        "JJv IMAGE REVIEW",
        f"stage: {stage}",
        f"episode: {receipt.get('episode_id')}",
        f"shot: {receipt.get('shot')}",
        f"route: {route}",
        f"account_label: {_account_label(provenance) or 'not exposed'}",
        f"codex_session_id: {_codex_session(provenance) or 'not exposed'}",
        f"output_sha256: {output_sha256}",
        f"prompt_sha256: {provenance.get('prompt_sha256')}",
        f"loadimage_input: {input_name}",
    ]
    if source_receipt is not None:
        lines.extend([
            f"native_source_sha256: {(source_receipt.get('output') or {}).get('sha256')}",
            f"native_sha256: {(receipt.get('native') or {}).get('sha256')}",
        ])
    lines.append("reference_hashes:")
    lines.extend(f"- {row['role']}: {row['sha256']}" for row in refs)
    lines.extend(["prompt:", _prompt_text(provenance)])
    return _redact("\n".join(lines))


def _note_node(text: str) -> dict[str, Any]:
    return {
        "id": 1,
        "type": "Note",
        "pos": [40, 40],
        "size": [520, 420],
        "flags": {},
        "order": 0,
        "mode": 0,
        "inputs": [],
        "outputs": [],
        "title": "GHI CHU | prompt + provenance",
        "properties": {"Node name for S&R": "Note"},
        "widgets_values": [text],
        "widgets_values_named": {"text": text},
    }


def _base_gui(*, title: str, note: str, metadata: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "id": digest[:8] + "-0000-4000-8000-" + digest[:12],
        "revision": 0,
        "last_node_id": 1,
        "last_link_id": 0,
        "nodes": [_note_node(note)],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {"title": title, "jjv": {"schema": WORKFLOW_SCHEMA, **metadata}},
        "version": 0.4,
    }
