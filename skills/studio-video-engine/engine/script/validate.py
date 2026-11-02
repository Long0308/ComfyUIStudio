"""Validate authoring JSON with the engine's existing schema validator and semantic checks."""
from __future__ import annotations

from pathlib import Path

from ..config.loader import SKILL_ROOT
from ..config.schema import validate
from ..core.errors import Refused
from ..core.io import read_json


def validate_script(script: dict, *, schema_path: Path | None = None) -> None:
    errors = validate(script, read_json(schema_path or SKILL_ROOT / 'schemas/script.schema.json'), label='script')
    if errors:
        raise Refused('; '.join(errors))
    shots = script['shots']
    ids = [s['id'] for s in shots]
    if len(ids) != len(set(ids)):
        errors.append('script.shots: duplicate shot ids')
    terms = [c['term'].casefold() for c in script['vocabulary_cards']]
    if len(terms) != len(set(terms)):
        errors.append('script.vocabulary_cards: duplicate terms')
    cast = script['character_references']
    for role, voice in script.get('voice_reference', {}).items():
        if role in cast and not isinstance(voice, dict):
            errors.append(f'voice_reference.{role}: a cast role needs an object')
    for i, shot in enumerate(shots):
        sid = shot['id']
        if not shot['speech_text'].strip():
            errors.append(f'{sid}: speech_text is blank')
        for role in [shot['speaker'], *([shot['listener']] if shot.get('listener') else [])]:
            if role not in cast:
                errors.append(f'{sid}: undeclared cast role {role!r}')
        if cast.get(shot['speaker'], {}).get('speech_allowed') is False:
            errors.append(f'{sid}: silent cast role cannot speak')
        frames = shot.get('duration_frames')
        if frames is not None and abs(frames - shot['duration_s'] * script['fps']) > 1e-4:
            errors.append(f'{sid}: duration_frames disagrees with duration_s * fps')
        if 'end_frame_exclusive' in shot and 'start_frame' in shot and frames is not None:
            if shot['end_frame_exclusive'] != shot['start_frame'] + frames:
                errors.append(f'{sid}: end_frame_exclusive disagrees with start + duration')
        if 'end_s' in shot and 'start_s' in shot:
            if abs(shot['end_s'] - shot['start_s'] - shot['duration_s']) > 1e-4:
                errors.append(f'{sid}: end_s disagrees with start + duration')
        entry = shot.get('entry') or {}
        if entry.get('kind') == 'carry' and (i == 0 or entry.get('from_shot') != ids[i - 1]):
            errors.append(f'{sid}: carry must name the immediate predecessor')
        brief = shot.get('layout_brief')
        if brief and script.get('domain') and brief.get('domain') != script['domain']:
            errors.append(f'{sid}: layout_brief domain differs from script domain')
    for card in script['vocabulary_cards']:
        if card.get('speaker') and card['speaker'] not in cast:
            errors.append(f"card {card['term']}: undeclared speaker")
        for sid in card.get('shot_ids', []):
            if sid not in ids:
                errors.append(f"card {card['term']}: unknown shot {sid}")
    for extra in script.get('voice_extras', []):
        role = extra['speaker']
        if role not in cast or cast[role].get('speech_allowed') is False:
            errors.append(f'extra {extra["id"]}: undeclared or silent speaker {role!r}')
    for role in script.get('voice_reference', {}):
        if isinstance(script['voice_reference'][role], dict) and role not in cast:
            errors.append(f'voice_reference: undeclared cast role {role}')
    if errors:
        raise Refused('; '.join(errors))
