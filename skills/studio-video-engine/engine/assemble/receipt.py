"""Assemble receipt: the hashed evidence of one master run (``jjv/assemble-receipt/v1``).

Pure functions only; the caller owns ffmpeg and passes the measured pieces in.  The receipt is
written write-once by ``engine.core.io.write_json_once`` (identical bytes are a no-op, anything
else is a refusal), like every other engine artefact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core.io import sha256_file, write_json_once

SCHEMA = "jjv/assemble-receipt/v1"

def _file(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256_file(Path(path))}

def segment_row(row: Mapping[str, Any], shas: Mapping[str, str]) -> dict:
    """One receipt segment row (same shape the staged script wrote)."""
    probe = row.get("probe") or {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "start_f": row["start_f"],
        "dur_f": row["dur_f"],
        "transition_in": list(row["trans"]),
        "source": row.get("src_path") or row.get("logo_path"),
        "input_sha256": shas.get(row["id"]),
        "source_size": [probe.get("width"), probe.get("height")] if probe else None,
        "placeholder": bool(row.get("placeholder")),
        "note": row.get("note"),
    }

def build_receipt(
    *,
    domain_id: str,
    tag: str,
    edl_path: Path,
    edl_sha256: str,
    film: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    shas: Mapping[str, str],
    audio: Mapping[str, Any],
    captions: Mapping[str, Any],
    mix_integrated_lufs: float | None,
    outputs: Mapping[str, Path],
    stems: Mapping[str, Path],
    picture: Path,
    mux: Mapping[str, Any],
    probes: Mapping[str, Any],
) -> dict:
    """The full receipt document (dict; the caller writes it once)."""
    return {
        "schema": SCHEMA,
        "domain_id": domain_id,
        "tag": tag,
        "edl": {"path": str(edl_path), "sha256": edl_sha256},
        "film": dict(film),
        "segments": [segment_row(row, shas) for row in segments],
        "audio": dict(audio),
        "captions": dict(captions),
        "mix_integrated_lufs": mix_integrated_lufs,
        "outputs": {name: _file(path) for name, path in outputs.items()},
        "stems": {name: _file(path) for name, path in stems.items()},
        "picture_sha256": sha256_file(picture),
        "mux": dict(mux),
        "ffprobe": dict(probes),
        "placeholders": [row["id"] for row in segments if row.get("placeholder")],
    }

def write_receipt(out_dir: Path, tag: str, receipt: Mapping[str, Any]) -> Path:
    """Write ``receipt-<tag>.json`` beside the outputs (write-once); return its path."""
    path = Path(out_dir) / f"receipt-{tag}.json"
    write_json_once(path, receipt, mode="utf8", stamp=True)
    return path
