"""The shared music-bed library: read the registry, verify a bed file, and write the registry (versioned, with backup).

The registry (``<library>/music-beds/REGISTRY.json``) lists every bed that passed the vocal-free gate, with its sha256,
length, loudness, gate numbers and ``used_in`` (the films that used it).  The only code that changes it is here:

* every write goes through :func:`write_registry`: the registry sha256 at READ time must still be the one on disk
  (a concurrent edit is ``Refused``, never overwritten), the previous bytes are kept as ``REGISTRY.json.bak-<UTC>``,
  ``revision`` is incremented and ``updated`` set, the new bytes replace the file atomically;
* documents are never mutated: :func:`with_used_in` / :func:`with_bed` return a new document;
* a bed file is added write-once (an existing file must hold identical bytes).
"""

from __future__ import annotations

import copy
import shutil
import wave
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import Refused
from ..core.io import pretty_json, read_json, sha256_file, write_atomic, write_once

BEDS_DIR = "music-beds"
REGISTRY_FILE = "REGISTRY.json"
BED_KEYS = ("id", "file", "sha256", "duration_s", "generator", "vocal_gate", "used_in", "status")
GATE_KEYS = ("vocal_minus_bed_rms_db", "windows_over_-40dBFS", "pass")


def beds_dir(library: Path) -> Path:
    return Path(library) / BEDS_DIR


def registry_path(library: Path) -> Path:
    return beds_dir(library) / REGISTRY_FILE


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_registry(library: Path, schema: str) -> tuple[dict, str]:
    """``(document, sha256 of the file read)``; a document that is not a bed registry is ``Refused``."""
    path = registry_path(library)
    if not path.is_file():
        raise Refused(f"music library registry not found: {path}")
    document = read_json(path)
    problems = validate_registry(document, schema)
    if problems:
        raise Refused(f"{path}: " + "; ".join(problems))
    return document, sha256_file(path)


def validate_registry(document: object, schema: str) -> list[str]:
    """Problems of a registry document; ``schema`` is the id the recipe (``library.registry_schema``) names."""
    if not isinstance(document, dict) or document.get("schema") != schema:
        return [f"not a {schema} document"]
    beds = document.get("beds")
    if not isinstance(beds, list):
        return ["beds must be a list"]
    problems, seen = [], set()
    for index, row in enumerate(beds):
        missing = [key for key in BED_KEYS if not isinstance(row, dict) or key not in row]
        if missing:
            problems.append(f"beds[{index}] lacks {missing}")
            continue
        if row["id"] in seen:
            problems.append(f"duplicate bed id {row['id']!r}")
        seen.add(row["id"])
        if not isinstance(row["used_in"], list):
            problems.append(f"{row['id']}: used_in must be a list")
        gate_missing = [key for key in GATE_KEYS if key not in (row["vocal_gate"] or {})]
        if gate_missing:
            problems.append(f"{row['id']}: vocal_gate lacks {gate_missing}")
    return problems


def bed_path(library: Path, row: dict) -> Path:
    name = str(row["file"])
    if Path(name).name != name:
        raise Refused(f"bed {row['id']}: file {name!r} must be a plain file name inside {BEDS_DIR}/")
    return beds_dir(library) / name


def wav_facts(path: Path) -> dict:
    """Header facts of a WAV (no sample read): rate, channels, width, duration."""
    try:
        with wave.open(str(path), "rb") as handle:
            frames, rate = handle.getnframes(), handle.getframerate()
            return {"rate": rate, "channels": handle.getnchannels(), "sample_width": handle.getsampwidth(),
                    "duration_s": frames / rate}
    except (OSError, wave.Error, EOFError) as error:
        raise Refused(f"cannot read WAV {path}: {error}") from error


def check_file(library: Path, row: dict, *, rate: int, channels: int = 2, hash_file: bool = True) -> list[str]:
    """Why this bed's FILE cannot be used (empty = usable): missing, other bytes, other rate/channels, other length."""
    path = bed_path(library, row)
    if not path.is_file():
        return [f"file missing: {path.name}"]
    problems = []
    if hash_file and sha256_file(path) != row["sha256"]:
        problems.append("file bytes differ from the registry sha256")
    facts = wav_facts(path)
    if facts["rate"] != rate or facts["channels"] != channels or facts["sample_width"] != 2:
        problems.append(f"format {facts['rate']} Hz / {facts['channels']} ch / {facts['sample_width'] * 8} bit, "
                        f"the mix needs {rate} Hz / {channels} ch / 16 bit")
    if abs(facts["duration_s"] - float(row["duration_s"])) > 0.05:
        problems.append(f"file lasts {facts['duration_s']:.2f} s, the registry says {row['duration_s']} s")
    return problems


def with_used_in(document: dict, bed_id: str, entry: dict) -> tuple[dict, bool]:
    """``(new document, added)``: ``entry`` appended to the bed's ``used_in`` unless that film is already there."""
    new = copy.deepcopy(document)
    rows = [row for row in new["beds"] if row["id"] == bed_id]
    if len(rows) != 1:
        raise Refused(f"bed {bed_id!r} is not in the registry")
    if any(isinstance(u, dict) and u.get("film") == entry["film"] for u in rows[0]["used_in"]):
        return new, False
    rows[0]["used_in"].append(entry)
    return new, True


def with_bed(document: dict, row: dict) -> dict:
    missing = [key for key in BED_KEYS if key not in row]
    if missing:
        raise Refused(f"new bed row lacks {missing}")
    if any(existing["id"] == row["id"] or existing["sha256"] == row["sha256"] for existing in document["beds"]):
        raise Refused(f"bed {row['id']!r} (or a bed with the same sha256) is already in the registry")
    new = copy.deepcopy(document)
    new["beds"].append(copy.deepcopy(row))
    return new


def next_bed_id(document: dict, prefix: str) -> str:
    """``<prefix><n>`` with n one above the highest number any bed id with that prefix has."""
    numbers = [int(row["id"][len(prefix):]) for row in document["beds"]
               if row["id"].startswith(prefix) and row["id"][len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def write_registry(library: Path, document: dict, *, read_sha256: str, schema: str) -> dict:
    """Replace the registry with ``document`` (a changed copy of what ``load_registry`` returned, whose file sha was
    ``read_sha256``).  Returns ``{path, backup, revision, sha256}``."""
    path = registry_path(library)
    if sha256_file(path) != read_sha256:
        raise Refused(f"{path} changed since it was read; re-run (nothing was written)")
    problems = validate_registry(document, schema)
    if problems:
        raise Refused("; ".join(problems))
    backup = path.with_name(f"{REGISTRY_FILE}.bak-{utc_stamp()}")
    if backup.exists():
        raise Refused(f"backup {backup.name} already exists (two writes in one second); retry")
    shutil.copyfile(path, backup)
    new = copy.deepcopy(document)
    new["revision"] = int(document.get("revision", 0)) + 1
    new["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    write_atomic(path, pretty_json(new, mode="utf8"))
    return {"path": str(path), "backup": str(backup), "revision": new["revision"], "sha256": sha256_file(path)}


def add_bed_file(library: Path, source: Path, name: str) -> str:
    """Copy ``source`` into ``music-beds/<name>`` write-once; returns the sha256 (identical bytes are accepted)."""
    if Path(name).name != name:
        raise Refused(f"bed file name {name!r} must be a plain name")
    return write_once(beds_dir(library) / name, Path(source).read_bytes())
