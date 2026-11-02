"""``jjv voice reconcile``: bind an unreconciled POST to its take through ``/history`` diffs.

Never POSTs.  For a job with an intent and no take, the history is read and every entry that
is new since the intent's snapshot AND carries the same text, profile id and language is a
candidate.  Exactly one candidate: download, save, ``take.json`` (provenance ``reconciled``).
None or several: Uncertain (exit 2); the operator inspects VoiceStudio.
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import Uncertain
from ..core.io import read_json
from . import receipts
from .synth import SynthContext, bind_take


CREATED_KEYS = ("created_unix", "created_at_unix", "created_at", "timestamp")  # created_at: the real VoiceStudio /history key
CREATED_SLACK_S = 2.0


def _created_before_intent(item: dict, intent: dict) -> bool:
    """True when the entry carries a numeric creation time earlier than the intent's dispatch."""
    dispatched = intent.get("dispatched_unix")
    if not isinstance(dispatched, (int, float)):
        return False
    for key in CREATED_KEYS:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value < dispatched - CREATED_SLACK_S
    return False


def _echoes_request(item: dict, request: dict) -> bool:
    """Text, profile and language must match; any other request field the entry echoes must match too."""
    for key in ("text", "profile_id", "language"):
        if item.get(key) != request[key]:
            return False
    return all(str(item[key]) == str(request[key]) for key in request if key in item)


def matching_entries(intent: dict, history: list[dict]) -> list[dict]:
    """New-since-snapshot entries that echo the intent's request and are not older than it."""
    known = set(intent.get("history_ids_before") or [])
    request = intent["request"]
    return [item for item in history
            if isinstance(item.get("id"), str) and item["id"] not in known
            and _echoes_request(item, request) and not _created_before_intent(item, intent)]


def reconcile_job(context: SynthContext, job: dict) -> dict:
    request_id = job["request_id"]
    state = receipts.job_state(context.out, request_id)
    if state == "COMPLETED":
        return {"request_id": request_id, "status": "ALREADY_BOUND"}
    if state != "UNCERTAIN":
        return {"request_id": request_id, "status": "NOTHING_TO_RECONCILE", "state": state}
    folder = receipts.job_dir(context.out, request_id)
    intent_path = folder / receipts.INTENT
    if not intent_path.is_file():
        raise Uncertain(f"{request_id}: unknown.json without intent.json; inspect VoiceStudio by hand")
    intent = read_json(intent_path)
    if intent.get("request_sha256") != job["request_sha256"]:
        raise Uncertain(f"{request_id}: intent.json is bound to another request_sha256")
    candidates = matching_entries(intent, context.voice.history())
    if not candidates:
        raise Uncertain(f"{request_id}: no new history entry matches the intent; this verb never re-posts")
    if len(candidates) > 1:
        raise Uncertain(f"{request_id}: ambiguous history reconciliation: "
                        + ", ".join(str(item.get("id")) for item in candidates))
    item = candidates[0]
    audio_id = str(item["id"])
    if not receipts.SAFE_AUDIO_ID.match(audio_id):
        raise Uncertain(f"{request_id}: history id {audio_id!r} is not a usable audio id")
    take = bind_take(context, job, audio_id, context.voice.download(audio_id), "reconciled", item)
    return {"request_id": request_id, "status": "RECONCILED", "audio_id": audio_id,
            "native_sha256": take["native"]["sha256"]}


def run_reconcile(context: SynthContext) -> dict:
    results = [reconcile_job(context, job) for job in context.plan["jobs"]]
    return {"results": results, "reconciled": sum(r["status"] == "RECONCILED" for r in results)}


def adopt_takes(context: SynthContext, takes: list[dict]) -> dict:
    """Bind existing native WAVs (e.g. a batch made before the engine) as takes, by request id.

    Each row: ``{"request_id", "path", "audio_id"}``.  The file is hashed in place (not copied)
    when it is readable; ``take.json`` is write-once.  No HTTP."""
    by_id = {job["request_id"]: job for job in context.plan["jobs"]}
    results = []
    for row in takes:
        request_id = row.get("request_id")
        job = by_id.get(request_id)
        if job is None:
            raise Uncertain(f"adopt: {request_id!r} is not a planned request id")
        if receipts.job_state(context.out, request_id) == "COMPLETED":
            results.append({"request_id": request_id, "status": "ALREADY_BOUND"})
            continue
        audio_id = str(row.get("audio_id") or "adopted")
        if not receipts.SAFE_AUDIO_ID.match(audio_id):
            raise Uncertain(f"adopt: audio_id {audio_id!r} is not a plain token")
        source = Path(row["path"])
        if not source.is_file():
            raise Uncertain(f"adopt: {source} is not a file")
        take = bind_take(context, job, audio_id, source.read_bytes(), "adopted",
                         {"adopted_from": receipts.describe_path(source, episode_root=context.episode_root,
                                                                 out=context.out)})
        results.append({"request_id": request_id, "status": "ADOPTED", "native_sha256": take["native"]["sha256"]})
    return {"results": results, "adopted": sum(r["status"] == "ADOPTED" for r in results)}
