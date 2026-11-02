"""Listen approval of a voice take (``jjv voice approve``), bound to the WAV sha256.

A person listens to the native take and records ``approve --job ID --by NAME --note ...``.  The record
``<out>/jobs/<safe>/approval.json`` is write-once and carries the sha256 of the native WAV that was
approved; if the take on disk is another file the approval does not count.  When the domain says
``voice.require_listen_approval`` (set true by the shipped domains) ``finalize`` refuses every job without a valid
record (``E_LISTEN_APPROVAL``) and a later stage (H3 prepare) asks :func:`require_wav_approved` for the
sha256 of the WAV it is about to use: any WAV derived from a native take (base, editorial, receipt WAV,
split segment) resolves back to that take through ``voice-finalize.json``.

Technical measurements do not certify timbre, pronunciation or lip sync, so a machine cannot approve:
``--by`` must name the listener and agent-like names are Refused (a guard against accident, not malice).
"""

from __future__ import annotations

import re
import time
import math
import subprocess
from pathlib import Path

from ..core.errors import Refused, Uncertain
from ..core.io import read_json, sha256_file, write_json_once
from . import receipts
from . import resample_lineage
from .wavio import read_wav

APPROVAL_FILE = "approval.json"
APPROVAL_SCHEMA = "jjv/voice-approval/v1"
_MACHINE_NAMES = {"agent", "claude", "opus", "sonnet", "haiku", "worker", "root", "auto", "bot", "ai", "codex",
                  "gpt", "gemini", "assistant", "orchestrator", "engine", "system", "verifier", "critic"}
_WORDS = re.compile(r"[a-z0-9]+")


def check_listener(by: str) -> str:
    """The listener's name, or ``E_APPROVAL_BY`` when it is empty or names a machine."""
    name = str(by or "").strip()
    if not name or _MACHINE_NAMES & set(_WORDS.findall(name.lower())):
        raise Refused(f"E_APPROVAL_BY: --by must name the person who listened, not {by!r}")
    return name


def approval_path(out: Path, request_id: str) -> Path:
    return receipts.job_dir(out, request_id) / APPROVAL_FILE


def _record(out: Path, job: dict, native_sha: str) -> dict | None:
    """The approval record of ``job`` when it is bound to ``native_sha``; None when absent or bound elsewhere."""
    path = approval_path(out, job["request_id"])
    if not path.is_file():
        return None
    record = read_json(path)
    ok = (isinstance(record, dict) and record.get("schema") == APPROVAL_SCHEMA
          and record.get("request_sha256") == job["request_sha256"]
          and (record.get("subject") or {}).get("sha256") == native_sha)
    return record if ok else None


def approval_binding(out: Path, job: dict, native_sha: str) -> dict | None:
    """``{by, note, record_sha256, subject_sha256}`` of a valid approval, else None (no timestamps: stable)."""
    record = _record(out, job, native_sha)
    if record is None:
        return None
    return {"approved_by": record["approved_by"], "note": record["note"], "subject_sha256": native_sha,
            "record_sha256": sha256_file(approval_path(out, job["request_id"]))}


def approve(out: Path, job: dict, *, by: str, note: str, sha256: str | None, episode_root: Path | None,
            now: float | None = None) -> dict:
    """Write the approval of ``job``'s bound take; ``sha256`` (optional) is what the listener says they heard."""
    listener = check_listener(by)
    if not str(note or "").strip():
        raise Refused("E_APPROVAL_NOTE: --note is required (what was heard: timbre, pronunciation, pacing)")
    if receipts.job_state(out, job["request_id"]) != "COMPLETED":
        raise Refused(f"{job['request_id']}: no bound take to approve (state "
                      f"{receipts.job_state(out, job['request_id'])})")
    take, native = receipts.read_take(out, job, episode_root=episode_root)
    native_sha = take["native"]["sha256"]
    if sha256 is not None and sha256.lower() != native_sha:
        raise Refused(f"{job['request_id']}: --sha256 {sha256[:12]} is not the bound native take {native_sha[:12]}; "
                      "listen to the file the engine bound")
    existing = _record(out, job, native_sha)
    if existing is not None:
        return {"status": "ALREADY_APPROVED", "request_id": job["request_id"], "subject_sha256": native_sha,
                "approved_by": existing["approved_by"]}
    record = {"schema": APPROVAL_SCHEMA, "request_id": job["request_id"], "request_sha256": job["request_sha256"],
              "audio_id": take["audio_id"],
              "subject": {"kind": "native_take", "path": take["native"]["path"], "sha256": native_sha},
              "approved_by": listener, "note": str(note).strip(),
              "approved_unix": float(time.time() if now is None else now)}
    write_json_once(approval_path(out, job["request_id"]), record, mode="ascii", stamp=True)
    return {"status": "APPROVED", "request_id": job["request_id"], "subject_sha256": native_sha,
            "approved_by": listener, "native": str(native)}


def unapproved(out: Path, jobs: list[dict], episode_root: Path | None) -> list[dict]:
    """Rows ``{request_id, reason}`` for every job whose bound take has no valid approval."""
    rows = []
    for job in jobs:
        state = receipts.job_state(out, job["request_id"])
        if state != "COMPLETED":
            rows.append({"request_id": job["request_id"], "reason": f"no bound take ({state})"})
            continue
        take, _ = receipts.read_take(out, job, episode_root=episode_root)
        if _record(out, job, take["native"]["sha256"]) is not None:
            continue
        stale = approval_path(out, job["request_id"]).is_file()
        rows.append({"request_id": job["request_id"], "native_sha256": take["native"]["sha256"],
                     "reason": "approval is bound to another WAV" if stale else "not approved"})
    return rows


def require_approved(out: Path, jobs: list[dict], episode_root: Path | None) -> None:
    missing = unapproved(out, jobs, episode_root)
    if missing:
        raise Refused("E_LISTEN_APPROVAL: the domain requires a listen approval before finalize; "
                      f"missing: {[(m['request_id'], m['reason']) for m in missing]}; "
                      "run 'jjv voice approve --job ID --by <listener> --note <what was heard>'")


def _wav_shas(entry: dict) -> set[str]:
    shas = {entry["native"]["sha256"], entry["base"]["sha256"], entry["editorial"]["sha256"],
            entry["receipt_wav"]["sha256"]}
    split = entry.get("split") or {}
    shas.update(seg["sha256"] for seg in (split.get("segments") or []))
    if split.get("full"):
        shas.add(split["full"]["sha256"])
    return shas


def _lineage_required(receipt: dict, entry: dict) -> bool:
    transform = entry.get("transform")
    return (receipt.get("mode") == "resample_lineage" or "lineage" in entry
            or isinstance(transform, dict) and transform.get("mode") == "resample_lineage")


def _lineage_approval(out: Path, job: dict, entry: dict, wav_sha256: str,
                      episode_root: Path | None) -> dict:
    """Verify the recorded conversion and both files before inheriting source approval."""
    lineage = entry.get("lineage")
    if lineage is None:
        raise Refused("E_VOICE_LINEAGE_MISSING: explicit resample entry has no lineage record")
    if not isinstance(lineage, dict) or lineage.get("schema") != "jjv/voice-resample-lineage/v1":
        raise Refused("E_VOICE_LINEAGE_INVALID: malformed lineage schema")
    for key in ("source_sha256", "derived_sha256", "approval_record_sha256"):
        if not isinstance(lineage.get(key), str) or not re.fullmatch(r"[a-f0-9]{64}", lineage[key]):
            raise Refused(f"E_VOICE_LINEAGE_INVALID: malformed {key}")
    command = lineage.get("converter_command")
    if (not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command)
            or not isinstance(lineage.get("converter_command_line"), str)
            or not lineage["converter_command_line"].strip()
            or not isinstance(lineage.get("converter_version"), str)
            or not lineage["converter_version"].startswith("ffmpeg version ")
            or not all(isinstance(lineage.get(k), dict) and lineage[k]
                       for k in ("source_format", "derived_format", "checks"))):
        raise Refused("E_VOICE_LINEAGE_INVALID: converter, format or measurement evidence is malformed")
    for key in ("source_duration_s", "derived_duration_s"):
        duration = lineage.get(key)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise Refused(f"E_VOICE_LINEAGE_INVALID: malformed {key}")
    if abs(lineage["source_duration_s"] - lineage["derived_duration_s"]) > 0.001:
        raise Refused("E_VOICE_LINEAGE_DURATION: recorded duration drift exceeds 1 ms")
    expected_options = ["-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-i"]
    expected_tail = ["-map", "0:a:0", "-map_metadata", "-1", "-af", resample_lineage.CONVERSION_FILTER,
                     "-c:a", "pcm_s16le"]
    if (len(command) != 17 or command[1:7] != expected_options or command[8:16] != expected_tail
            or lineage["converter_command_line"] != subprocess.list2cmdline(command)
            or "\n" in lineage["converter_version"] or "\r" in lineage["converter_version"]):
        raise Refused("E_VOICE_LINEAGE_CONVERTER: conversion command differs from recorded explicit soxr route")
    checks = lineage["checks"]
    numeric_keys = ("duration_delta_ms", "roundtrip_duration_delta_ms", "correlation", "residual_db", "delay_ms")
    if any(isinstance(checks.get(k), bool) or not isinstance(checks.get(k), (int, float))
           or not math.isfinite(checks[k]) for k in numeric_keys):
        raise Refused("E_VOICE_LINEAGE_CHECKS: missing or nonfinite measurement")
    integer_keys = ("delay_samples", "compared_samples", "source_samples", "derived_samples", "roundtrip_samples")
    if (any(type(checks.get(k)) is not int for k in integer_keys)
            or any(checks[k] <= 0 for k in integer_keys if k != "delay_samples")
            or checks.get("thresholds") != resample_lineage.THRESHOLDS
            or checks.get("channels_identical") is not True
            or not all(isinstance(checks.get(k), str) and checks[k] for k in ("delay_method", "null_method"))):
        raise Refused("E_VOICE_LINEAGE_CHECKS: malformed or incomplete fidelity evidence")
    if (not 0 <= checks["duration_delta_ms"] <= 1 or not 0 <= checks["roundtrip_duration_delta_ms"] <= 1
            or not 0.9999 <= checks["correlation"] <= 1.000000000001
            or not -300 <= checks["residual_db"] <= -60
            or abs(checks["delay_samples"]) >= 24
            or abs(checks["delay_ms"] - checks["delay_samples"] * 1000 / 24000) > 1e-9):
        raise Refused("E_VOICE_LINEAGE_CHECKS: recorded fidelity measurements exceed explicit thresholds")
    native, derived = entry.get("native"), entry.get("receipt_wav")
    if not isinstance(native, dict) or not isinstance(derived, dict):
        raise Refused("E_VOICE_LINEAGE_INVALID: entry needs native and receipt_wav descriptors")
    if lineage["source_sha256"] != native.get("sha256"):
        raise Refused("E_VOICE_LINEAGE_SOURCE: lineage source differs from native take")
    if lineage["derived_sha256"] != derived.get("sha256") or wav_sha256 != lineage["derived_sha256"]:
        raise Refused("E_VOICE_LINEAGE_DERIVED: only the recorded derived receipt WAV inherits approval")
    try:
        take, source_path = receipts.read_take(out, job, episode_root=episode_root)
    except (Refused, Uncertain, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Refused(f"E_VOICE_LINEAGE_SOURCE: cannot verify bound source take: {exc}") from exc
    if take["native"]["sha256"] != lineage["source_sha256"]:
        raise Refused("E_VOICE_LINEAGE_SOURCE: lineage source differs from bound take")
    if not isinstance(derived.get("path"), str) or not derived["path"]:
        raise Refused("E_VOICE_LINEAGE_INVALID: derived WAV path is missing")
    try:
        derived_path = receipts.resolve_described(derived["path"], episode_root=episode_root, out=out)
        actual_sha = sha256_file(derived_path)
    except (Refused, Uncertain, OSError, ValueError, TypeError) as exc:
        raise Refused(f"E_VOICE_LINEAGE_DERIVED: cannot verify derived WAV: {exc}") from exc
    if derived_path.suffix.lower() != ".wav" or actual_sha != lineage["derived_sha256"]:
        raise Refused("E_VOICE_LINEAGE_DERIVED: derived WAV hash or extension differs from lineage")
    if Path(command[7]).resolve() != source_path.resolve():
        raise Refused("E_VOICE_LINEAGE_CONVERTER: command source path differs from bound source take")
    try:
        source_audio, derived_audio = read_wav(source_path), read_wav(derived_path)
    except (Refused, Uncertain, OSError, ValueError) as exc:
        raise Refused(f"E_VOICE_LINEAGE_FORMAT: cannot verify WAV formats: {exc}") from exc
    for name, audio, expected, sample_key in (("source", source_audio, (24000, 1, 2), "source_samples"),
                                             ("derived", derived_audio, (48000, 2, 2), "derived_samples")):
        recorded_format = lineage[f"{name}_format"]
        if ((audio.rate, audio.channels, audio.sample_width) != expected
                or recorded_format != resample_lineage._format(audio)
                or checks[sample_key] != audio.frames
                or abs(lineage[f"{name}_duration_s"] - audio.duration_s) > 1e-12):
            raise Refused(f"E_VOICE_LINEAGE_FORMAT: {name} WAV differs from recorded format or duration")
    samples = derived_audio.samples()
    if samples[::2] != samples[1::2]:
        raise Refused("E_VOICE_LINEAGE_CHECKS: derived WAV channels are not exact duplicates")
    try:
        binding = approval_binding(out, job, lineage["source_sha256"])
    except (Uncertain, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Refused(f"E_VOICE_LINEAGE_APPROVAL: malformed source approval: {exc}") from exc
    if binding is None:
        raise Refused("E_VOICE_LINEAGE_APPROVAL: lineage source has no listen approval bound to this request")
    if binding["record_sha256"] != lineage["approval_record_sha256"]:
        raise Refused("E_VOICE_LINEAGE_APPROVAL: source approval record changed since conversion")
    return binding


def require_wav_approved(out: Path, plan: dict, wav_sha256: str, episode_root: Path | None) -> dict:
    """For H3 prepare: ``wav_sha256`` must belong to a finalized job whose native take is approved.

    Returns ``{request_id, class, approval}``; ``E_LISTEN_APPROVAL`` when the WAV is unknown to the finalize
    receipt or its take has no valid approval (always checked: the caller decides whether the domain
    requires it by calling this function)."""
    path = Path(out) / receipts.FINALIZE_FILE
    if not path.is_file():
        raise Refused(f"E_LISTEN_APPROVAL: {path} does not exist; finalize before binding a WAV")
    receipt = read_json(path)
    entries = receipt.get("entries") or []
    target_sha = wav_sha256.lower()
    entry = None
    for candidate in entries:
        if _lineage_required(receipt, candidate):
            # Do not route explicit conversions through the broad legacy set of derived hashes.
            shas = {v.get("sha256") for v in (candidate.get("native"), candidate.get("base"),
                    candidate.get("editorial"), candidate.get("receipt_wav")) if isinstance(v, dict)}
            lineage = candidate.get("lineage")
            if isinstance(lineage, dict):
                shas.add(lineage.get("derived_sha256"))
        else:
            shas = _wav_shas(candidate)
        if target_sha in shas:
            entry = candidate
            break
    if entry is None:
        raise Refused(f"E_LISTEN_APPROVAL: WAV {wav_sha256[:12]} is not in {receipts.FINALIZE_FILE}")
    job = next((j for j in plan["jobs"] if j["request_id"] == entry.get("request_id")), None)
    lineage_required = _lineage_required(receipt, entry)
    if job is None:
        code = "E_VOICE_LINEAGE_JOB" if lineage_required else "E_LISTEN_APPROVAL"
        raise Refused(f"{code}: finalize entry names an unknown planned request")
    if lineage_required:
        binding = _lineage_approval(out, job, entry, target_sha, episode_root)
    else:
        binding = approval_binding(out, job, entry["native"]["sha256"])
    if binding is None:
        raise Refused(f"E_LISTEN_APPROVAL: {entry['request_id']} has no listen approval bound to its native take")
    return {"request_id": entry["request_id"], "class": entry["category"], "approval": binding}
