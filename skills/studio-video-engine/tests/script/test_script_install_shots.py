"""`jjv script ingest --install-shots` + `prerender` config: stages that run before any clip exists find the shot list."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from config_fixtures import make_live_action_world

from engine.config.loader import ConfigViolation, resolve_episode
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.script.ingest import ingest
from _m6_helpers import world


def _with_declared_shots(source: Path) -> Path:
    episode = source / 'engine/episode.json'
    data = read_json(episode)
    data['files'] = {'shots': 'shots.json'}
    episode.write_text(json.dumps(data), encoding='utf-8')
    return episode


def test_install_shots_writes_the_declared_skeleton_once(script_work):
    source, out, _, _, _ = world(script_work)
    episode = _with_declared_shots(source)
    result = ingest(source / 'script.json', episode, out, install=True)
    target = source / 'engine/shots.json'
    assert result['installed_shots'] == {'path': str(target), 'sha256': sha256_file(target),
                                         'schema': 'jjv/shots-skeleton/v1'}
    assert read_json(target)['shots'][0]['clip'] is None
    assert sha256_file(target) == sha256_file(out / 'shots.json')
    assert ingest(source / 'script.json', episode, out, install=True) == result  # idempotent


def test_install_shots_is_off_by_default(script_work):
    source, out, _, _, _ = world(script_work)
    episode = _with_declared_shots(source)
    assert 'installed_shots' not in ingest(source / 'script.json', episode, out)
    assert not (source / 'engine/shots.json').exists()


def test_install_shots_never_overwrites_another_file(script_work):
    source, out, _, _, _ = world(script_work)
    episode = _with_declared_shots(source)
    (source / 'engine/shots.json').write_text('{"schema": "jjv/shots/v1"}', encoding='utf-8')
    with pytest.raises(Refused, match='overwrite'):
        ingest(source / 'script.json', episode, out, install=True)
    assert read_json(source / 'engine/shots.json') == {'schema': 'jjv/shots/v1'}


def test_install_shots_needs_a_declared_shot_list(script_work):
    source, out, _, _, _ = world(script_work)
    with pytest.raises(Refused, match='files.shots'):
        ingest(source / 'script.json', source / 'engine/episode.json', out, install=True)


def _skeleton(world_, ids=('S01_A', 'S02_A', 'S03_A')):
    path = world_.engine_dir / 'shots.json'
    path.write_text(json.dumps({'schema': 'jjv/shots-skeleton/v1', 'episode_id': 'live-fixture',
                                'status': 'planned_unmeasured',
                                'shots': [{'shot': i, 'clip': None, 'wav_binding': None} for i in ids]}), encoding='utf-8')
    return path


def test_prerender_accepts_a_skeleton_but_default_does_not(tmp_path):
    w = make_live_action_world(tmp_path)
    _skeleton(w)
    kwargs = dict(skill_root=w.skill_root, machine_path=w.machine_path)
    with pytest.raises(ConfigViolation, match='schema'):
        resolve_episode(str(w.episode_file), **kwargs)
    config = resolve_episode(str(w.episode_file), prerender=True, **kwargs)
    assert [r['shot'] for r in config.shots] == ['S01_A', 'S02_A', 'S03_A']


@pytest.mark.parametrize('ids', [(), ('S01_A', 'S01_A'), ('shot-1',)])
def test_prerender_still_checks_the_skeleton_shape(tmp_path, ids):
    w = make_live_action_world(tmp_path)
    _skeleton(w, ids)
    with pytest.raises(ConfigViolation, match='unique shot ids'):
        resolve_episode(str(w.episode_file), skill_root=w.skill_root, machine_path=w.machine_path, prerender=True)


def test_prerender_still_validates_a_real_shot_list_in_full(tmp_path):
    w = make_live_action_world(tmp_path)
    w.edit(w.engine_dir / 'shots.json', lambda d: d['shots'][0].update(clip=None))
    with pytest.raises(ConfigViolation):
        resolve_episode(str(w.episode_file), skill_root=w.skill_root, machine_path=w.machine_path, prerender=True)
    ok = make_live_action_world(tmp_path / 'ok')
    assert resolve_episode(str(ok.episode_file), skill_root=ok.skill_root, machine_path=ok.machine_path, prerender=True)
