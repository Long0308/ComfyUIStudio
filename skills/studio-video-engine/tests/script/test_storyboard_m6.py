"""Continuity plans use editorial rules and the shared spatial tool adapter."""
from __future__ import annotations

import copy

import pytest

from engine.core.errors import Refused
from engine.core.io import read_json
from engine.script.ingest import publish
from engine.storyboard.plan import build_plan, check_plan
from _m6_helpers import world


def setup(script_work, change=None):
    source, out, script, episode, domain = world(script_work)
    if change:
        change(script)
        # Each test authors one immutable input; no mutable receipt is reused.
        (source / 'script.json').unlink()
        publish(source, {'script.json': script})
    from engine.script.ingest import ingest
    ingest(source / 'script.json', source / 'engine/episode.json', out)
    return out, out / 'storyboard'


def test_same_seat_push_in_byte_identical_and_tamper_blocked(script_work):
    inputs, out = setup(script_work)
    first = build_plan(inputs, out, episode_id='sample')
    assert first == build_plan(inputs, out, episode_id='sample')
    report = check_plan(out, episode_id='sample')
    assert report == check_plan(out, episode_id='sample')
    assert first['canonical_mode'] == report['canonical_mode'] == 'ascii'
    assert report['ok'] and len(report['pairs']) == 9
    assert all(p['preset'] == 'cut_push' for p in report['pairs'])
    assert all('dip_white' not in p['allowed_presets'] for p in report['pairs'])
    assert all('crossfade' not in p['allowed_presets'] for p in report['pairs'])
    assert 'Teacher seated right' in (out / 'placement/S01_A.txt').read_text('utf-8')
    (out / 'placement/S01_A.txt').write_text('changed', encoding='utf-8')
    with pytest.raises(Refused, match='changed'):
        check_plan(out, episode_id='sample')


def test_angle_and_scene_change_flash_or_pan(script_work):
    def change(s):
        s['shots'][1]['continuity'].update(camera_id='closeup', motivation='follow pan right')
        s['shots'][2]['continuity'].update(setting_id='classroom')
    inputs, out = setup(script_work, change)
    build_plan(inputs, out, episode_id='sample')
    report = check_plan(out, episode_id='sample')
    assert report['ok']
    assert report['pairs'][0]['preset'] == 'whip'
    assert report['pairs'][1]['preset'] == 'dip_white'


@pytest.mark.parametrize('case', ['unknown', 'same_flash', 'dissolve_mismatch', 'unproven_carry'])
def test_check_refuses_bad_or_ambiguous_edit(script_work, case):
    def change(s):
        shot = s['shots'][1]
        if case == 'unknown':
            for row in s['shots']:
                row['continuity'] = {'setting_id': 'garden'}
        elif case == 'same_flash':
            shot['continuity']['transition'] = 'dip_white'
        elif case == 'dissolve_mismatch':
            shot['continuity'].update(setting_id='another', transition='crossfade')
        else:
            shot['entry'] = {'kind': 'carry', 'from_shot': s['shots'][0]['id']}
    inputs, out = setup(script_work, change)
    build_plan(inputs, out, episode_id='sample')
    assert not check_plan(out, episode_id='sample')['ok']


@pytest.mark.parametrize('scene_change', [False, True])
def test_spatial_api_wired_and_mismatch_blocks_dissolve(script_work, monkeypatch, scene_change):
    def change(s):
        for row in s['shots'][:2]:
            row['layout_brief'] = {'domain': 'jenniejoy_cartoon_3d', 'brief_id': row['id'], 'camera': {}, 'ground': {}}
        s['shots'][1]['continuity']['transition'] = 'crossfade'
        if scene_change:
            s['shots'][1]['continuity']['setting_id'] = 'another-scene-with-identical-camera'
    inputs, out = setup(script_work, change)
    from engine.storyboard import tool
    calls = []
    monkeypatch.setattr(tool, 'pins', lambda path: {'scene_layout.py': 'fixture-tool-sha'})
    def call(path, *args):
        calls.append(args[0])
        return {'validate': {'valid': True}, 'placement-text': {'lines': ['Measured placement.']},
                'continuity': {'classification': 'MISMATCH', 'offenders': ['prop moved']}}[args[0]]
    monkeypatch.setattr(tool, 'call', call)
    build_plan(inputs, out, episode_id='sample')
    report = check_plan(out, episode_id='sample')
    assert report['geometric_pairs'] == 1 and not report['ok']
    assert report['pairs'][0]['preset'] == ('dip_white' if scene_change else 'cut_push')
    assert calls.count('validate') == 2 and calls.count('placement-text') == 2 and calls.count('continuity') == 1
    assert (out / 'placement/S01_A.txt').read_text('utf-8') == 'Measured placement.\n'


def test_changed_ingest_is_rejected(script_work):
    inputs, out = setup(script_work)
    (inputs / 'script.json').write_text('{}', encoding='utf-8')
    with pytest.raises(Refused, match='changed'):
        build_plan(inputs, out, episode_id='sample')


def test_shared_tool_exit_one_is_valid_only_for_spatial_mismatch(monkeypatch):
    import json
    import subprocess
    from pathlib import Path
    from engine.storyboard import tool
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, json.dumps({'classification': 'MISMATCH', 'errors': []}), '')
    monkeypatch.setattr(tool.subprocess, 'run', run)
    assert tool.call(Path('scene_layout.py'), 'continuity', 'a.json', 'b.json')['classification'] == 'MISMATCH'
    assert '-B' in calls[0] and '-I' in calls[0]
    with pytest.raises(Refused, match='refused'):
        tool.call(Path('scene_layout.py'), 'validate', 'a.json')


def test_manifest_path_escape_refused(script_work):
    from engine.storyboard.plan import artifact
    with pytest.raises(Refused, match='escapes'):
        artifact(script_work, '../outside.json')


@pytest.mark.parametrize('provenance', ['invalid', {'jjv_scaffold': 'invalid'}])
def test_geometry_metadata_error_is_a_refusal(script_work, monkeypatch, provenance):
    def change(s):
        s['shots'][0]['layout_brief'] = {'domain': 'jenniejoy_cartoon_3d', 'provenance': provenance}
    inputs, out = setup(script_work, change)
    from engine.storyboard import tool
    monkeypatch.setattr(tool, 'pins', lambda path: {})
    with pytest.raises(Refused, match='must be objects'):
        build_plan(inputs, out, episode_id='sample')
