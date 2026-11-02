"""``jjv voice synth``: one guarded VoiceStudio POST per planned job (GPU, ``--execute`` only).

Order per job: state from receipts -> GPU lock (``E_GPU_LOCK``) -> idle ComfyUI queue
(``E_QUEUE_BUSY``) -> VoiceStudio reachable (history snapshot) -> write-once ``intent.json``
-> POST -> native WAV saved write-once -> ``take.json``.  Any error once the intent exists
is Uncertain (exit 2, ``unknown.json``); a 4xx is Failed (exit 4, ``rejected.json``).  A job
with an intent and no take is never re-posted: ``jjv voice reconcile`` is the only way on.
A take whose native WAV still hashes is reused, never regenerated.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..comfy.lock import existence_lock
from ..comfy.queue import require_idle
from ..core.errors import EngineError, Failed, Refused, Uncertain
from ..core.io import sha256_file, write_json_once, write_once
from . import receipts
from .client import VoiceStudio, VoiceStudioError, VoiceStudioRejected
from .recipe import VoiceSettings
from .wavio import metrics, read_wav, validate_riff


@dataclass(frozen=True)
class SynthContext:
    settings: VoiceSettings
    out: Path
    plan: dict
    voice: VoiceStudio
    queue_reader: Callable[[], object]  # returns the ComfyUI ``/queue`` document
    episode_root: Path


def dry_run_rows(out: Path, plan: dict) -> list[dict]:
    return [{"request_id": job["request_id"], "state": receipts.job_state(out, job["request_id"]),
             "request_sha256": job["request_sha256"]} for job in plan["jobs"]]


def require_execute_preconditions(settings: VoiceSettings, plan: dict) -> None:
    if plan.get("script_status") != "LOCKED":
        raise Refused("voice synth --execute needs a LOCKED dialogue document (script-lock approval)")
    if settings.gpu_lock_path is None:
        raise Refused("E_GPU_LOCK: --execute requires machine.gpu_lock_path")
    if not settings.voicestudio_url:
        raise Refused("voice synth --execute requires a VoiceStudio URL (machine.voicestudio.url, "
                      "see CONFIG-PATCH.md, or --voicestudio-url)")
    if not settings.comfy_url:
        raise Refused("E_QUEUE_BUSY: --execute requires machine.comfy.url for the idle-queue check")


def _save_native(context: SynthContext, job: dict, audio_id: str, payload: bytes) -> dict:
    validate_riff(payload, f"{job['request_id']} native WAV")
    path = receipts.native_path(context.out, job["request_id"], audio_id)
    digest = write_once(path, payload)
    data = read_wav(path)
    return {"path": receipts.describe_path(path, episode_root=context.episode_root, out=context.out),
            "sha256": digest, "metrics": metrics(data)}


def _audio_id(generated: object) -> str:
    audio_id = generated.get("id") if isinstance(generated, Mapping) else None
    if not isinstance(audio_id, str) or not receipts.SAFE_AUDIO_ID.match(audio_id):
        raise VoiceStudioError("POST /generate answered without a usable audio id")
    return audio_id


def bind_take(context: SynthContext, job: dict, audio_id: str, payload: bytes, provenance: str,
              history_item: dict | None = None) -> dict:
    """Save the native WAV and write ``take.json`` (both write-once)."""
    native = _save_native(context, job, audio_id, payload)
    take = {"schema": "jjv/voice-take/v1", "request_id": job["request_id"], "request_sha256": job["request_sha256"],
            "audio_id": audio_id, "provenance": provenance, "native": native,
            "history_item": dict(history_item) if history_item else None}
    write_json_once(receipts.job_dir(context.out, job["request_id"]) / receipts.TAKE, take, mode="ascii", stamp=True)
    return take


def _history_ids(history: list[dict]) -> list[str]:
    return sorted(str(item["id"]) for item in history if isinstance(item.get("id"), str))


def _dispatch(context: SynthContext, job: dict) -> dict:
    """Under the lock: idle check, snapshot, intent, POST, save.  Returns the take."""
    folder = receipts.job_dir(context.out, job["request_id"])
    try:
        require_idle(context.queue_reader())
    except Refused as error:
        raise Refused(f"E_QUEUE_BUSY: {error}") from error
    try:
        history = context.voice.history()
    except VoiceStudioError as error:
        raise Refused(f"E_VOICESTUDIO_UNHEALTHY: {error}") from error  # before the intent: nothing was sent
    intent = {"schema": "jjv/voice-intent/v1", "request_id": job["request_id"],
              "request_sha256": job["request_sha256"], "request": job["request"],
              "history_ids_before": _history_ids(history),
              "dispatched_unix": time.time()}  # the one timestamped receipt: reconcile's created window
    write_json_once(folder / receipts.INTENT, intent, mode="ascii", stamp=True)
    try:
        generated = context.voice.generate(job["request"])
        audio_id = _audio_id(generated)
        payload = generated.get("wav_bytes")
        if not isinstance(payload, (bytes, bytearray)):
            payload = context.voice.download(audio_id)
        return bind_take(context, job, audio_id, bytes(payload), "generate")
    except VoiceStudioRejected as error:
        write_json_once(folder / receipts.REJECTED, {"request_id": job["request_id"], "error": str(error)},
                        mode="ascii", stamp=True)
        raise Failed(f"{job['request_id']}: {error}") from error
    except EngineError as error:
        write_json_once(folder / receipts.UNKNOWN, {"request_id": job["request_id"], "error": str(error),
                                                     "next": "jjv voice reconcile"}, mode="ascii", stamp=True)
        raise Uncertain(f"{job['request_id']}: outcome unknown after the POST; never auto-resubmitted. "
                        f"Run 'jjv voice reconcile'. ({error})") from error


def synth_job(context: SynthContext, job: dict) -> dict:
    state = receipts.job_state(context.out, job["request_id"])
    if state == "COMPLETED":
        take, _ = receipts.read_take(context.out, job, episode_root=context.episode_root)
        return {"request_id": job["request_id"], "status": "REUSED", "audio_id": take["audio_id"]}
    if state == "UNCERTAIN":
        raise Uncertain(f"{job['request_id']}: an earlier POST is unreconciled (intent without take); "
                        "run 'jjv voice reconcile' first, never re-post")
    if state == "REJECTED":
        raise Failed(f"{job['request_id']}: VoiceStudio rejected this request earlier (rejected.json); "
                     "fix the request in a new plan version")
    assert context.settings.gpu_lock_path is not None
    try:
        lock = existence_lock(context.settings.gpu_lock_path, timeout_seconds=context.settings.lock_timeout_seconds)
        lock.__enter__()
    except Refused as error:
        raise Refused(f"E_GPU_LOCK: {error}") from error
    try:
        take = _dispatch(context, job)
    finally:
        lock.__exit__(None, None, None)
    return {"request_id": job["request_id"], "status": "COMPLETED", "audio_id": take["audio_id"],
            "native_sha256": take["native"]["sha256"]}


def run_synth(context: SynthContext, *, category: str | None = None) -> dict:
    """Serial; stops at the first Uncertain/Failed and reports what completed."""
    require_execute_preconditions(context.settings, context.plan)
    results: list[dict] = []
    for job in context.plan["jobs"]:
        if category and job["category"] != category:
            continue
        try:
            results.append(synth_job(context, job))
        except EngineError as error:  # partial results travel with the error (the CLI prints them)
            error.evidence["results"] = list(results)
            error.evidence["stopped_at"] = job["request_id"]
            raise
    return {"results": results, "completed": sum(r["status"] == "COMPLETED" for r in results),
            "reused": sum(r["status"] == "REUSED" for r in results)}


def verify_takes(out: Path, plan: dict, episode_root: Path) -> list[dict]:
    rows = []
    for job in plan["jobs"]:
        state = receipts.job_state(out, job["request_id"])
        row = {"request_id": job["request_id"], "state": state}
        if state == "COMPLETED":
            take, path = receipts.read_take(out, job, episode_root=episode_root)
            row.update(audio_id=take["audio_id"], native_sha256=sha256_file(path))
        rows.append(row)
    return rows
