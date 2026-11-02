"""CR-M6: storyboard continuity through the REAL shared scene_layout.py (no monkeypatch).

Three shots, two pairs:
- S01_A -> S02_A: identical embedded geometry and identical declarations -> same_framing -> cut_push.
- S02_A -> S03_A: identical declarations but the geometry camera lens differs -> new_framing -> not cut_push.
The geometry is the shipped ep04 S01_A example; the only edit is the lens on S03_A.
"""
from __future__ import annotations

import json

import pytest

from engine.core.io import read_json
from engine.layout.tool import SCENE_LAYOUT
from engine.script.ingest import ingest, publish
from engine.storyboard.plan import build_plan, check_plan
from _m6_helpers import world

EXAMPLE = SCENE_LAYOUT.parent.parent / 'assets/examples/scene-layout.example.ep04-S01_A.cartoon.json'
SAME_DECLARATION = {'setting_id': 'garden', 'camera_id': 'wide', 'seat_id': 'bench'}


def _geometry() -> dict:
    return json.loads(EXAMPLE.read_text(encoding='utf-8'))


def _setup(script_work):
    source, out, script, episode, _domain = world(script_work)
    shots = script['shots'][:3]
    for shot in shots:
        shot['continuity'] = dict(SAME_DECLARATION)
        shot['layout_brief'] = _geometry()
    shots[2]['layout_brief']['camera']['lens_mm'] = 30  # only geometry change; 50 fails the real CAMERA_CROP check
    script['shots'] = shots
    script['duration_s'] = 40  # 3 shots cannot fill the 110 s sample; budget must hold
    (source / 'script.json').unlink()
    publish(source, {'script.json': script})
    ingest(source / 'script.json', source / 'engine/episode.json', out)
    return out, out / 'storyboard'


def test_real_scene_layout_continuity_drives_cut_push_and_new_framing(script_work):
    if not SCENE_LAYOUT.is_file() or not EXAMPLE.is_file():
        pytest.skip(f'shared comfyui-blender scene_layout.py or ep04 example missing: {SCENE_LAYOUT}')
    inputs, out = _setup(script_work)
    build_plan(inputs, out, episode_id='sample')
    report = check_plan(out, episode_id='sample')

    assert report['ok'], report
    assert report['geometric_pairs'] == 2 and len(report['pairs']) == 2
    same, new = report['pairs']
    # Proof the real tool ran: a real continuity report is attached to each geometric pair.
    assert isinstance(same['spatial'], dict) and 'classification' in same['spatial']
    assert isinstance(new['spatial'], dict) and 'classification' in new['spatial']
    assert same['framing']['framing'] == 'same_framing'
    assert same['preset'] == 'cut_push'
    assert new['framing']['framing'] == 'new_framing'
    assert new['preset'] != 'cut_push'
    assert read_json(out / 'storyboard-plan.json')['tool'] is not None
