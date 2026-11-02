"""Locked script -> ``jjv/dialogue/v1``: the voice stage starts from the script, no hand-made dialogue file.

Reads the film script the production already locks (``shots[]`` with ``speech_text``, ``speaker``,
``duration_s``, ``dialogue_vi`` ...; ``vocabulary_cards[]``) and returns the dialogue document ``voice plan``
consumes: one dialogue row per spoken shot (EN text + speaker + the VI subtitle as metadata + frames),
one vocabulary row per card, plus the extras (end line, brand voice) from ``script.voice_extras`` and/or an
extras file.  Nothing is invented: a spoken shot without a speaker, a card without a speaker, or a duplicate
shot id is Refused.  Speaker -> profile id is NOT decided here: the approved cast document does that in plan.

Script keys read (all optional beyond the first three of a shot): ``status`` (``LOCKED*`` = LOCKED, anything
else DRAFT, so ``synth --execute`` refuses an unlocked script), ``film_id``, ``fps``, ``language.spoken``;
shot ``id speaker speech_text duration_s`` + ``dialogue_vi start_frame duration_frames target_keywords
en_markup voice{emotion,effect_preset} voice_split max_duration_s``; card ``term duration (proposed_outro_
duration_s) icon vi start_frame speaker``.
"""

from __future__ import annotations

from ..core.errors import Refused

SUBTITLE_VI = "dialogue_vi"


def _subtitle(row: dict, key: str = SUBTITLE_VI) -> dict:
    value = row.get(key)
    return {"subtitle": {"vi": value}} if isinstance(value, str) and value.strip() else {}


def _voice_tag(row: dict) -> dict:
    tag = row.get("voice") if isinstance(row.get("voice"), dict) else {}
    return {k: tag[k] for k in ("emotion", "effect_preset") if isinstance(tag.get(k), str) and tag[k]}


def _frames(row: dict) -> dict:
    out = {}
    for key in ("start_frame", "duration_frames"):
        if isinstance(row.get(key), int) and not isinstance(row.get(key), bool):
            out[key] = row[key]
    return out


def _shot_row(shot: dict) -> dict:
    name = shot.get("id")
    if not isinstance(shot.get("speaker"), str) or not shot["speaker"]:
        raise Refused(f"script shot {name!r} speaks but has no speaker")
    row = {"shot": name, "speaker": shot["speaker"], "text_tts": " ".join(str(shot["speech_text"]).split()),
           "target_duration_s": shot["duration_s"], **_subtitle(shot), **_frames(shot), **_voice_tag(shot)}
    if isinstance(shot.get("target_keywords"), list):
        row["target_keywords"] = [str(k) for k in shot["target_keywords"]]
    if isinstance(shot.get("en_markup"), str):
        row["en_markup"] = shot["en_markup"]
    if shot.get("voice_split") is not None:
        row["split"] = shot["voice_split"]
    if isinstance(shot.get("max_duration_s"), (int, float)):
        row["max_duration_s"] = shot["max_duration_s"]
    return row


def _card_row(card: dict, default_speaker: str | None) -> dict:
    speaker = card.get("speaker") or default_speaker
    if not speaker:
        raise Refused(f"vocabulary card {card.get('term')!r} has no speaker: add card.speaker, "
                      "script.vocabulary_speaker or pass --vocabulary-speaker")
    duration = card.get("target_duration_s", card.get("proposed_outro_duration_s"))
    row = {"term": card["term"], "speaker": speaker, "target_duration_s": duration,
           **_subtitle(card, "vi"), **_voice_tag(card)}
    if isinstance(card.get("icon"), str) and card["icon"]:
        row["icon"] = card["icon"]
    if isinstance(card.get("start_frame"), int):
        row["start_frame"] = card["start_frame"]
    return row


def dialogue_from_script(script: dict, *, episode_id: str, extras: list[dict] | None = None,
                         vocabulary_speaker: str | None = None) -> dict:
    """The ``jjv/dialogue/v1`` document derived from ``script`` (pure; the same script gives the same document)."""
    shots = [s for s in script.get("shots") or [] if isinstance(s, dict) and str(s.get("speech_text") or "").strip()]
    ids = [s.get("id") for s in shots]
    if len(set(ids)) != len(ids):
        raise Refused(f"script has duplicate spoken shot ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    default_speaker = vocabulary_speaker or script.get("vocabulary_speaker")
    status = str(script.get("status") or "")
    document: dict = {
        "schema": "jjv/dialogue/v1", "episode_id": episode_id,
        "status": "LOCKED" if status.upper().startswith("LOCKED") else "DRAFT",
        "dialogue": [_shot_row(s) for s in shots],
    }
    cards = [c for c in script.get("vocabulary_cards") or [] if isinstance(c, dict) and c.get("term")]
    if cards:
        document["vocabulary"] = [_card_row(c, default_speaker) for c in cards]
    joined = [*(script.get("voice_extras") or []), *(extras or [])]
    if joined:
        document["extras"] = joined
    if isinstance(script.get("fps"), int) and not isinstance(script.get("fps"), bool):
        document["fps"] = script["fps"]
    spoken = (script.get("language") or {}).get("spoken") if isinstance(script.get("language"), dict) else None
    if isinstance(spoken, str) and spoken:
        document["language"] = spoken
    return document
