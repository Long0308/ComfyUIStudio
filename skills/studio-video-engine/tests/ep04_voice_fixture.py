"""Read-only derivation of the first episode's voice documents for the parity test.

Reads production-local (locked script + the historical batch manifest) and never writes
there; tests may name the episode, engine sources may not.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.config.loader import REPO_ROOT

EPISODE_SLUG = "04-milk-and-mom"
EPISODE_ROOT = REPO_ROOT / "production-local" / "JennieJoyKids-Story" / EPISODE_SLUG
SCRIPT = EPISODE_ROOT / "script" / "script-astra-candidate-v003.json"
BATCH = EPISODE_ROOT / "audio" / "voicestudio-batch-v001"
TRIM_V002 = EPISODE_ROOT / "audio" / "dialogue-trim-v002"

SPLIT_S06B = {"pad_tail_silence": True, "segments": [
    {"label": "seg1-foodlist", "samples": 240_000, "speech_conditioning": True},
    {"label": "seg2-motto", "samples": 280_000, "speech_conditioning": True},
    {"label": "seg3-sleep", "samples": 80_000, "speech_conditioning": False}]}


def available() -> bool:
    return all(p.is_file() for p in (SCRIPT, BATCH / "manifest.json", TRIM_V002 / "manifest.json",
                                      EPISODE_ROOT / "engine" / "episode.json"))


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def derive_documents() -> dict:
    """``{dialogue, cast, takes, expected_request_sha, trim_v002}`` from the locked sources."""
    script = _read(SCRIPT)
    manifest = _read(BATCH / "manifest.json")
    contract = manifest["voice_contract"]
    dialogue = {
        "schema": "jjv/dialogue/v1", "episode_id": script["film_id"], "status": "LOCKED",
        "dialogue": [{"shot": s["id"], "speaker": s["speaker"], "text_tts": s["speech_text"],
                      "target_duration_s": s["duration_s"],
                      **({"split": SPLIT_S06B} if s["id"] == "S06_B" else {})} for s in script["shots"]],
        "vocabulary": [{"term": c["term"], "speaker": "alice", "target_duration_s": c["proposed_outro_duration_s"]}
                       for c in script["vocabulary_cards"]],
    }
    cast = {"schema": "jjv/cast/v1", "episode_id": script["film_id"], "speakers": {
        "mother": {"speech_allowed": True, "voice": {"profile_id": contract["mother_profile_id"],
                                                     "transform": {"pitch_semitones": 0}}},
        "alice": {"speech_allowed": True, "voice": {
            "profile_id": contract["alice_profile_id"],
            "transform": {"pitch_semitones": contract["alice_transform"]["pitch_semitones"]}}},
        "milkmaid": {"speech_allowed": False}}}
    takes = [{"request_id": rid, "path": str(BATCH / job["native_path"]), "audio_id": job["voice_history_id"]}
             for rid, job in manifest["jobs"].items()]
    trim = {item["shot_id"]: item for item in _read(TRIM_V002 / "manifest.json")["items"]}
    return {"dialogue": dialogue, "cast": cast, "takes": takes,
            "expected_request_sha": {rid: job["request_sha256"] for rid, job in manifest["jobs"].items()},
            "trim_v002": trim}
