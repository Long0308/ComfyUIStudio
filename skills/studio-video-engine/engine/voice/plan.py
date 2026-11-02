"""``jjv voice plan``: jobs from the episode dialogue + cast documents + recipe (offline).

Inputs (both validated against the schemas below):

* ``dialogue`` (``jjv/dialogue/v1``): ``status`` (LOCKED|DRAFT), ``dialogue[]`` rows
  ``{shot, speaker, text_tts, target_duration_s, max_duration_s?, split?}`` and optional
  ``vocabulary[]`` rows ``{term, speaker, target_duration_s}`` and optional ``extras[]`` rows
  ``{kind (end_line|brand_voice), id, speaker, text_tts, target_duration_s, max_duration_s?}``: a late end
  line ("See you again, baby!") or a brand voice reading, planned as first-class jobs
  ``request_id = "<kind>:<id>"`` with the same receipt, listen approval and single-trim rules.
* ``cast`` (``jjv/cast/v1``): ``speakers{<id>: {speech_allowed, voice?{profile_id, transform?}}}``.

Every request field (``language``, ``engine``, ``effect_preset``, ``wav_bits``) comes from the
recipe; profile ids and transforms from the cast; the text from the dialogue.  The
``request_sha256`` is the canonical sha of the request fields and is what a take is bound to.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config.loader import ResolvedConfig
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_file
from .recipe import VoiceSettings
from .receipts import describe_path
from .split import parse_split_plan

PLAN_SCHEMA_ID = "jjv/voice-plan/v1"
_SPEAKER_PREFIX = re.compile(r"^\s*[A-Za-z][\w .'-]{0,30}:\s")
_MARKUP = re.compile(r"[\[\]<>{}]")

EXTRA_KINDS = ("end_line", "brand_voice")
META_KEYS = ("subtitle", "start_frame", "duration_frames", "en_markup", "target_keywords", "icon", "emotion")
_LINE_META: dict = {  # optional per-line metadata: carried to voice-bindings.json, never sent to the TTS
    "subtitle": {"type": "object"},  # {"vi": "..."}: the subtitle text per language
    "start_frame": {"type": "integer", "minimum": 0},
    "duration_frames": {"type": "integer", "minimum": 1},
    "en_markup": {"type": "string"},
    "target_keywords": {"type": "array", "items": {"type": "string", "minLength": 1}},
    "icon": {"type": "string", "minLength": 1},
    "emotion": {"type": "string", "minLength": 1},  # recorded only: VoiceStudio has no emotion field
    "language": {"type": "string", "minLength": 1},  # must agree with the recipe language (else Refused)
    "effect_preset": {"type": "string", "minLength": 1},  # must be the recipe preset or in allowed_effect_presets
}

DIALOGUE_SCHEMA: dict = {
    "type": "object",
    "required": ["schema", "episode_id", "status", "dialogue"],
    "properties": {
        "schema": {"const": "jjv/dialogue/v1"},
        "episode_id": {"type": "string", "minLength": 1},
        "status": {"enum": ["LOCKED", "DRAFT"]},
        "fps": {"type": "integer", "minimum": 1},
        "language": {"type": "string", "minLength": 1},
        "dialogue": {"type": "array", "items": {
            "type": "object", "required": ["shot", "speaker", "text_tts", "target_duration_s"],
            "properties": {
                "shot": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.-]*$"},
                "speaker": {"type": "string", "minLength": 1},
                "text_tts": {"type": "string", "minLength": 1},
                "target_duration_s": {"type": "number", "exclusiveMinimum": 0},
                "max_duration_s": {"type": "number", "exclusiveMinimum": 0},
                "split": {"type": "object"},
                **_LINE_META,
            }}},
        "vocabulary": {"type": "array", "items": {
            "type": "object", "required": ["term", "speaker", "target_duration_s"],
            "properties": {
                "term": {"type": "string", "minLength": 1},
                "speaker": {"type": "string", "minLength": 1},
                "target_duration_s": {"type": "number", "exclusiveMinimum": 0},
                **_LINE_META,
            }}},
        "extras": {"type": "array", "items": {
            "type": "object", "required": ["kind", "id", "speaker", "text_tts", "target_duration_s"],
            "properties": {
                "kind": {"enum": list(EXTRA_KINDS)},
                "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,30}$"},
                "speaker": {"type": "string", "minLength": 1},
                "text_tts": {"type": "string", "minLength": 1},
                "target_duration_s": {"type": "number", "exclusiveMinimum": 0},
                "max_duration_s": {"type": "number", "exclusiveMinimum": 0},
                **_LINE_META,
            }}},
    },
}

CAST_SCHEMA: dict = {
    "type": "object",
    "required": ["schema", "episode_id", "speakers"],
    "properties": {
        "schema": {"const": "jjv/cast/v1"},
        "episode_id": {"type": "string", "minLength": 1},
        "speakers": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["speech_allowed"],
            "properties": {
                "speech_allowed": {"type": "boolean"},
                "voice": {"type": "object", "required": ["profile_id"], "properties": {
                    "profile_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"},
                    "transform": {"type": "object", "properties": {
                        "pitch_semitones": {"type": "number", "minimum": -12, "maximum": 12}}},
                }},
            }}},
    },
}


def _load(path: Path, schema: dict, label: str, episode_id: str) -> dict:
    document = read_json(path)
    errors = validate(document, schema, label=label)
    if errors:
        raise Refused("; ".join(errors))
    if document["episode_id"] != episode_id:
        raise Refused(f"{label}: episode_id {document['episode_id']!r} != {episode_id!r}")
    return document


def lint_text(text: str, label: str) -> None:
    """E_SPEAKER_PREFIX: no ``Name:`` prefix and no bracket markup reaches the TTS."""
    if _SPEAKER_PREFIX.match(text):
        raise Refused(f"E_SPEAKER_PREFIX: {label}: text_tts starts with a speaker prefix: {text[:40]!r}")
    if _MARKUP.search(text):
        raise Refused(f"E_SPEAKER_PREFIX: {label}: text_tts contains markup brackets: {text[:40]!r}")
    if not text.strip():
        raise Refused(f"{label}: text_tts is blank")


def _voice_of(cast: dict, speaker: str, label: str) -> tuple[str, dict]:
    entry = cast["speakers"].get(speaker)
    if entry is None:
        raise Refused(f"E_APPROVED_CAST: {label}: speaker {speaker!r} is not in the cast")
    if not entry["speech_allowed"]:
        raise Refused(f"E_APPROVED_CAST: {label}: silent character {speaker!r} has a line")
    voice = entry.get("voice")
    if not isinstance(voice, dict):
        raise Refused(f"{label}: speaker {speaker!r} has no voice binding (profile_id) in the cast")
    transform = voice.get("transform") if isinstance(voice.get("transform"), dict) else {}
    return voice["profile_id"], {"pitch_semitones": float(transform.get("pitch_semitones", 0) or 0)}


def request_fields(recipe: dict, text: str, profile_id: str, target_duration_s: float,
                   effect_preset: str | None = None) -> dict:
    return {
        "text": text, "profile_id": profile_id, "language": recipe["language"], "engine": recipe["engine"],
        "duration": f"{float(target_duration_s):g}", "effect_preset": effect_preset or recipe["effect_preset"],
        "wav_bits": recipe["wav_bits"],
    }


def _check_language(row: dict, document_language: str | None, recipe: dict, label: str) -> None:
    """A line (or the document) that names its spoken language must agree with the recipe's (ISO prefix ok)."""
    want = str(recipe["language"]).lower()
    for given in (row.get("language"), document_language):
        if given and not (want == str(given).lower() or want.startswith(str(given).lower())):
            raise Refused(f"E_LANGUAGE: {label}: the line is {given!r} but recipe {recipe['recipe_id']!r} speaks "
                          f"{recipe['language']!r}; plan with a recipe of that language")


def _preset(row: dict, recipe: dict, label: str) -> str | None:
    wanted = row.get("effect_preset")
    if wanted is None or wanted == recipe["effect_preset"]:
        return None
    if wanted not in (recipe.get("allowed_effect_presets") or []):
        raise Refused(f"E_EFFECT_PRESET: {label}: preset {wanted!r} is not the recipe's "
                      f"{recipe['effect_preset']!r} nor in its allowed_effect_presets")
    return str(wanted)


def _job(category: str, source_id: str, speaker: str, text: str, target: float, cast: dict,
         recipe: dict, extra: dict, row: dict | None = None, language: str | None = None) -> dict:
    label = f"{category}:{source_id}"
    row = row or {}
    lint_text(text, label)
    _check_language(row, language, recipe, label)
    profile_id, transform = _voice_of(cast, speaker, label)
    request = request_fields(recipe, text, profile_id, target, _preset(row, recipe, label))
    meta = {key: row[key] for key in META_KEYS if key in row}
    if meta:
        extra = {**extra, "meta": meta}  # only when present: plans without metadata stay byte-identical
    return {
        "request_id": label, "category": category, "source_id": source_id, "speaker": speaker,
        "profile_id": profile_id, "text_tts": text, "target_duration_s": float(target),
        "transform": transform, "request": request,
        "request_sha256": canonical_sha256(request, mode="ascii"), **extra,
    }


def build_jobs(dialogue: dict, cast: dict, recipe: dict) -> list[dict]:
    lang = dialogue.get("language")
    jobs: list[dict] = []
    for row in dialogue["dialogue"]:
        extra = {"max_duration_s": row.get("max_duration_s"), "split": None}
        if row.get("split") is not None:
            plan = parse_split_plan(row["split"], f"dialogue:{row['shot']}")
            extra["split"] = {"pad_tail_silence": plan.pad_tail_silence, "segments": [
                {"label": s.label, "samples": s.samples, "speech_conditioning": s.speech_conditioning}
                for s in plan.segments]}
        jobs.append(_job("dialogue", row["shot"], row["speaker"], row["text_tts"], row["target_duration_s"],
                         cast, recipe, extra, row, lang))
    for row in dialogue.get("vocabulary") or []:
        jobs.append(_job("vocabulary", row["term"], row["speaker"], row["term"], row["target_duration_s"],
                         cast, recipe, {"max_duration_s": None, "split": None}, row, lang))
    for row in dialogue.get("extras") or []:
        jobs.append(_job(row["kind"], row["id"], row["speaker"], row["text_tts"], row["target_duration_s"],
                         cast, recipe, {"max_duration_s": row.get("max_duration_s"), "split": None}, row, lang))
    ids = [job["request_id"] for job in jobs]
    if len(set(ids)) != len(ids):
        raise Refused(f"duplicate voice request ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    if not jobs:
        raise Refused("the dialogue document has no lines")
    return jobs


def _validated(document: dict, episode_id: str) -> dict:
    errors = validate(document, DIALOGUE_SCHEMA, label="dialogue")
    if errors:
        raise Refused("; ".join(errors))
    if document["episode_id"] != episode_id:
        raise Refused(f"dialogue: episode_id {document['episode_id']!r} != {episode_id!r}")
    return document


def build_plan(config: ResolvedConfig, settings: VoiceSettings, *, dialogue_path: Path | None = None,
               cast_path: Path, out: Path | None, derived: dict | None = None) -> dict:
    """The deterministic plan document (no timestamps).

    ``derived`` = ``{"document": <jjv/dialogue/v1>, "source": {"kind": "script", "path", "sha256"}}`` when the
    dialogue comes from a locked script (``engine.voice.script_ingest``) instead of a dialogue file."""
    episode_id = config.episode["episode_id"]
    if derived is not None:
        dialogue = _validated(derived["document"], episode_id)
        dialogue_input = {"derived_from": derived["source"], "sha256": canonical_sha256(dialogue, mode="ascii")}
    else:
        dialogue = _load(dialogue_path, DIALOGUE_SCHEMA, "dialogue", episode_id)
        root_ = Path(config.episode_root)
        dialogue_input = {"path": describe_path(dialogue_path, episode_root=root_, out=out),
                          "sha256": sha256_file(dialogue_path)}
    cast = _load(cast_path, CAST_SCHEMA, "cast", episode_id)
    recipe = settings.recipe
    jobs = build_jobs(dialogue, cast, recipe.data)
    root = Path(config.episode_root)
    return {
        "schema": PLAN_SCHEMA_ID,
        "episode_id": episode_id,
        "domain": config.domain["domain_id"],
        "config_sha256": config.config_sha256,
        "canonical_mode": "ascii",
        "recipe": {"id": recipe.recipe_id, "sha256": recipe.sha256},
        "script_status": dialogue["status"],
        **({"fps": dialogue["fps"]} if "fps" in dialogue else {}),
        "inputs": {
            "dialogue": dialogue_input,
            "cast": {"path": describe_path(cast_path, episode_root=root, out=out), "sha256": sha256_file(cast_path)},
        },
        "request_contract": {key: recipe.data[key] for key in ("engine", "language", "effect_preset", "wav_bits")},
        "job_count": len(jobs),
        "jobs": jobs,
    }
