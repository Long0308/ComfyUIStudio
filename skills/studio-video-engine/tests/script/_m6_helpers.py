"""Shared M6 fixtures-as-helpers. Named uniquely: a second module called conftest breaks tests/conftest.py."""
from __future__ import annotations

import copy
from pathlib import Path

from engine.config.loader import SKILL_ROOT
from engine.core.io import read_json
from engine.script.ingest import publish


def sample() -> tuple[dict, dict, dict]:
    episode = {'episode_id': 'sample', 'film_id': 'sample', 'title': 'A new topic',
               'domain': 'jenniejoy_cartoon_3d'}
    script = {'schema': 'jjv/script/v1', 'film_id': 'sample', 'title': 'A new topic',
              'duration_s': 110, 'fps': 30, 'status': 'DRAFT',
              'structure': {'intro': {'duration_s': 3}},
              'character_references': {'teacher': {'speech_allowed': True}, 'child': {'speech_allowed': True}},
              'voice_reference': {'teacher': {'profile_id': 'voice-a'}, 'child': {'profile_id': 'voice-b'}},
              'vocabulary_speaker': 'child',
              'shots': [{'id': f'S{i:02d}_A', 'speaker': 'teacher', 'listener': 'child',
                         'speech_text': f'Look at word {i}.', 'duration_s': 5.4,
                         'visual': 'Teacher seated right, child seated left.',
                         'continuity': {'setting_id': 'garden', 'camera_id': 'wide', 'seat_id': 'bench'}}
                        for i in range(1, 11)],
              'vocabulary_cards': [{'term': f'word {i}', 'target_duration_s': .8} for i in range(8)]}
    domain = read_json(SKILL_ROOT / 'domains/jenniejoy_cartoon_3d.json')
    return script, episode, domain


def world(script_work: Path):
    script, episode, domain = sample()
    source = script_work / 'source'
    (source / 'engine').mkdir(parents=True)
    publish(source / 'engine', {'episode.json': episode})
    publish(source, {'script.json': script})
    return source, script_work / 'out', script, episode, domain
