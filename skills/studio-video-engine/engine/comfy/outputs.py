"""Locate and describe the files a finished prompt wrote (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.errors import Failed, Refused
from ..core.io import sha256_file
from ..core.paths import require_inside


def node_output_entries(history_entry: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    """Every ``{"filename": ...}`` record listed under ``outputs[node_id]`` (any list key)."""
    outputs = history_entry.get("outputs")
    node = outputs.get(node_id) if isinstance(outputs, dict) else None
    if not isinstance(node, dict):
        return []
    return [item for value in node.values() if isinstance(value, list)
            for item in value if isinstance(item, dict) and isinstance(item.get("filename"), str)]


def resolve_output(output_root: Path, entry: dict[str, Any]) -> Path:
    """The existing file an output record points at, which must sit inside ``output_root``."""
    if entry.get("type", "output") != "output":
        raise Failed(f"output record has type {entry.get('type')!r}, expected 'output'")
    subfolder = entry.get("subfolder", "")
    if not isinstance(subfolder, str):
        raise Failed("output record has an invalid subfolder")
    path = require_inside(Path(output_root) / subfolder / entry["filename"], output_root,
                          "ComfyUI output")
    if not path.is_file():
        raise Failed(f"ComfyUI output is missing: {path}")
    return path


def collect_outputs(history_entry: dict[str, Any], output_root: Path) -> list[dict[str, Any]]:
    """All output records of a prompt with path, size and sha256 (for receipts)."""
    found: list[dict[str, Any]] = []
    outputs = history_entry.get("outputs")
    for node_id in sorted(outputs) if isinstance(outputs, dict) else []:
        for entry in node_output_entries(history_entry, node_id):
            record: dict[str, Any] = {"node_id": node_id, "filename": entry["filename"],
                                      "subfolder": entry.get("subfolder", ""),
                                      "type": entry.get("type", "output"), "path": None,
                                      "exists": False, "sha256": None, "bytes": None}
            if record["type"] == "output":
                try:
                    path = resolve_output(output_root, entry)
                except (Refused, Failed) as error:
                    record["error"] = str(error)
                else:
                    record.update(path=str(path), exists=True, sha256=sha256_file(path),
                                  bytes=path.stat().st_size)
            found.append(record)
    return found
