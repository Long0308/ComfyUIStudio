"""Receipt layout of the voice stage under ``--out`` and the state derived from it.

    <out>/voice-plan.json                 plan (write-once)
    <out>/jobs/<safe>/intent.json         written BEFORE the POST (history snapshot, request sha)
    <out>/jobs/<safe>/unknown.json        the POST outcome is unknown (never resubmitted)
    <out>/jobs/<safe>/rejected.json       VoiceStudio rejected the request (4xx)
    <out>/jobs/<safe>/take.json           a native WAV is bound (generate | reconciled | adopted)
    <out>/native/<safe>-<audio_id>-native.wav
    <out>/finalize/...                    editorial, receipt and segment WAVs
    <out>/voice-finalize.json             finalize receipt (write-once; E_TRIM_ONCE)
    <out>/voice-bindings.json             subtitle line id -> receipt WAV, the shape timing/mix read (write-once)

State is DERIVED from these files; there is no mutable manifest.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file
from ..core.paths import resolve_data_path

PLAN_FILE = "voice-plan.json"
FINALIZE_FILE = "voice-finalize.json"
BINDINGS_FILE = "voice-bindings.json"
INTENT, UNKNOWN, REJECTED, TAKE = "intent.json", "unknown.json", "rejected.json", "take.json"
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
SAFE_AUDIO_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_id(request_id: str) -> str:
    return _UNSAFE.sub("-", request_id).strip("-")


def job_dir(out: Path, request_id: str) -> Path:
    return Path(out) / "jobs" / safe_id(request_id)


def native_path(out: Path, request_id: str, audio_id: str) -> Path:
    return Path(out) / "native" / f"{safe_id(request_id)}-{audio_id}-native.wav"


def describe_path(path: Path, *, episode_root: Path | None, out: Path | None) -> str:
    """Episode-relative when inside the episode, out-relative when inside out, else absolute."""
    resolved = Path(path).resolve()
    for root in (episode_root, out):
        if root is not None:
            try:
                return resolved.relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                continue
    return resolved.as_posix()


def resolve_described(described: str, *, episode_root: Path | None, out: Path | None) -> Path:
    """Inverse of :func:`describe_path` for a path stored in a receipt."""
    given = Path(described)
    if given.is_absolute():
        return resolve_data_path(given)      # a receipt written under a retired root: read the file where it lives now
    for root in (episode_root, out):
        if root is not None and (Path(root) / given).is_file():
            return Path(root) / given
    raise Uncertain(f"receipt path {described!r} not found under the episode root or {out}")


def job_state(out: Path, request_id: str) -> str:
    """``COMPLETED`` (take bound), ``UNCERTAIN`` (intent without take), ``REJECTED`` or ``READY``."""
    folder = job_dir(out, request_id)
    if (folder / TAKE).is_file():
        return "COMPLETED"
    if (folder / REJECTED).is_file():
        return "REJECTED"
    if (folder / INTENT).is_file() or (folder / UNKNOWN).is_file():
        return "UNCERTAIN"
    return "READY"


def read_take(out: Path, job: dict, *, episode_root: Path | None) -> tuple[dict, Path]:
    """The take receipt of ``job`` with its native WAV verified against the recorded sha."""
    folder = job_dir(out, job["request_id"])
    take = read_json(folder / TAKE)
    if not isinstance(take, dict) or take.get("request_sha256") != job["request_sha256"]:
        raise Refused(f"{job['request_id']}: take.json is bound to another request_sha256")
    native = take.get("native") or {}
    path = resolve_described(str(native.get("path")), episode_root=episode_root, out=out)
    if path.suffix.lower() != ".wav":
        raise Refused(f"{job['request_id']}: take native path is not a .wav: {path}")
    if sha256_file(path) != native.get("sha256"):
        raise Refused(f"{job['request_id']}: native WAV hash differs from take.json ({path})")
    return take, path


def load_plan(out: Path) -> dict:
    plan = read_json(Path(out) / PLAN_FILE)
    if not isinstance(plan, dict) or plan.get("schema") != "jjv/voice-plan/v1":
        raise Refused(f"{Path(out) / PLAN_FILE}: not a jjv/voice-plan/v1 document")
    return plan
