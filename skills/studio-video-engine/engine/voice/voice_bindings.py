"""``voice-bindings.json``: subtitle line id -> final receipt WAV, in the shape the next stages read.

Written by ``finalize`` next to ``voice-finalize.json`` (write-once).  One document, three readers:

* ``jjv timing words --dialogue``: ``dialogue[]`` rows ``{id, start_frame, end_frame_exclusive, speech_text,
  audio{path, sha256, offset_frames, duration_seconds}, speaker, en_markup, target_keywords}`` and
  ``vocabulary[]`` ``{term, icon, anchor}`` (``engine/timing/dialogue.py``);
* ``jjv audio mix`` / ``jjv qa``: ``wav_bindings[]`` ``{name, path, sha256, start_frame}`` with the names
  ``dlg <id>`` / ``voc <term>`` (``engine/qa/bindings.py``), ``outro_cards[]`` and the ``extras[]`` of the late
  classes (end line -> ``--extra-wav``, brand voice -> ``--brand-voice``);
* the subtitle track: every row carries ``dialogue_vi`` / ``subtitle`` (the VI text) beside the EN text.

Start frames come from the dialogue document (script ``start_frame``) when it has them; otherwise they are
``null`` placeholders, ``timeline_bound`` is false and the readers Refuse them by name (a null is never a frame).
A split line binds as its ONE full WAV (``split.full``), the H3 segments are listed under ``h3_segments``.
"""

from __future__ import annotations

from pathlib import Path

from ..core.io import sha256_file, write_json_once
from . import receipts

BINDINGS_SCHEMA = "jjv/voice-bindings/v1"


def _optional(meta: dict, *keys: str) -> dict:
    return {k: meta[k] for k in keys if k in meta}


def _audio(entry: dict) -> dict:
    wav = entry["mix"]["wavs"][0]
    return {"path": wav["path"], "sha256": wav["sha256"], "offset_frames": 0, "duration_seconds": wav["duration_s"],
            "samples": wav["samples"], "sample_rate": wav["sample_rate"], "channels": wav["channels"]}


def _frames(meta: dict) -> dict:
    start, length = meta.get("start_frame"), meta.get("duration_frames")
    return {"start_frame": start, "duration_frames": length,
            "end_frame_exclusive": start + length if start is not None and length is not None else None}


def _subtitle_fields(meta: dict) -> dict:
    sub = meta.get("subtitle") or {}
    return {"subtitle": sub, **({"dialogue_vi": sub["vi"]} if "vi" in sub else {})}


def _extra(entry: dict, job: dict, meta: dict) -> dict:
    mix = entry["mix"]
    wav = mix["wavs"][0]
    start = meta.get("start_frame")
    usage = dict(mix["usage"])
    if "templates" in usage and start is not None:
        usage["extra_wav_args"] = [t.replace("{start_frame}", str(start)) for t in usage["templates"]]
    return {"id": job["source_id"], "class": entry["class"], "request_id": job["request_id"], "speaker": job["speaker"],
            "speech_text": job["text_tts"], "name": mix["name"], **_subtitle_fields(meta),
            "start_frame": start, "audio": _audio(entry), "usage": usage,
            "needs_allow_outside": mix["needs_allow_outside"]}


def build_bindings(plan: dict, receipt: dict, *, plan_sha256: str, finalize_sha256: str) -> dict:
    jobs = {job["request_id"]: job for job in plan["jobs"]}
    dialogue, outro, wavs, extras, vocabulary, pending = [], [], [], [], [], []
    for entry in receipt["entries"]:
        job = jobs[entry["request_id"]]
        meta = job.get("meta") or {}
        klass = entry["class"]
        if klass in ("end_line", "brand_voice"):
            extras.append(_extra(entry, job, meta))
            continue
        audio, frames = _audio(entry), _frames(meta)
        if frames["start_frame"] is None:
            pending.append(job["request_id"])
        name = entry["mix"]["name"]
        wavs.append({"name": name, "path": audio["path"], "sha256": audio["sha256"], "start_frame": frames["start_frame"]})
        common = {"speaker": job["speaker"], **frames, **_subtitle_fields(meta), "audio": audio,
                  "request_id": job["request_id"], "listen_approval": entry["listen_approval"],
                  **_optional(meta, "emotion")}
        if klass == "dialogue":
            dialogue.append({"id": job["source_id"], "speech_text": job["text_tts"],
                             **_optional(meta, "en_markup", "target_keywords"), **common})
        else:
            outro.append({"term": job["source_id"], "speech_text": job["text_tts"], **_optional(meta, "icon"), **common})
            if meta.get("icon"):
                vocabulary.append({"term": job["source_id"], "icon": meta["icon"], "anchor": "first"})
    return {"schema": BINDINGS_SCHEMA, "episode_id": plan["episode_id"],
            **({"fps": plan["fps"]} if "fps" in plan else {}),
            "plan_sha256": plan_sha256, "finalize_sha256": finalize_sha256,
            "timeline_bound": not pending, "pending_start_frames": pending,
            "dialogue": dialogue, "vocabulary": vocabulary, "outro_cards": outro, "wav_bindings": wavs,
            "extras": extras,
            "readers": {"timing": "jjv timing words --dialogue <this file> (needs timeline_bound)",
                        "mix": "jjv audio mix --review-config <file carrying wav_bindings> + extras[].usage"}}


def write_bindings(out: Path, plan: dict, receipt: dict) -> tuple[Path, str]:
    document = build_bindings(plan, receipt, plan_sha256=sha256_file(out / receipts.PLAN_FILE),
                              finalize_sha256=sha256_file(out / receipts.FINALIZE_FILE))
    path = out / receipts.BINDINGS_FILE
    return path, write_json_once(path, document, mode="ascii")
