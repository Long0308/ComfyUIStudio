"""Offline M6 acceptance: script errors, reusable budgets, bytes and downstream inputs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import pytest

from engine.config.budget import BudgetRefused
from engine.config.contract import check_contract, timeline_from_contract
from engine.config.loader import SKILL_ROOT
from engine.config.schema import validate
from engine.core.errors import Refused
from engine.core.io import read_json, sha256_file
from engine.script.cli import register_cli, run_script
from engine.script.ingest import derive, ingest, publish
from engine.script.parity import differences
from engine.script.validate import validate_script
from engine.storyboard.cli import register_cli as register_storyboard
from engine.voice.plan import CAST_SCHEMA, DIALOGUE_SCHEMA
from _m6_helpers import sample, world


def test_fake_110_seconds_no_domain_change_and_downstream_schemas():
    script, episode, domain = sample()
    before = copy.deepcopy(domain)
    docs = derive(script, episode, domain, target_seconds=110)
    contract = docs['contract-plan.json']['contract']
    assert docs['DELIVERY-CONTRACT.json']['master']['frames'] == 3300
    assert domain == before
    assert not check_contract({**episode, 'contract': contract, 'timeline': timeline_from_contract(contract)}, domain)
    assert not validate(docs['dialogue.json'], DIALOGUE_SCHEMA)
    assert not validate(docs['voice-cast.json'], CAST_SCHEMA)
    assert all(s['frames'] >= 90 for s in contract['sections'] if s['kind'] == 'vocab_card')
    assert all(s['frames'] >= 60 for s in contract['sections'] if s['kind'] == 'logo_hold')
    rows = docs['shots.json']['shots']
    assert [s['shot'] for s in rows] == [s['id'] for s in script['shots']]
    assert all(s['clip'] is None and s['wav_binding'] is None for s in rows)
    assert docs['shots.json']['schema'] != 'jjv/shots/v1'
    assert len(docs['boundaries-input.json']['boundaries']) == len(contract['sections']) - 1
    assert docs['dialogue.json']['vocabulary'][0]['target_duration_s'] >= 3


def test_short_target_refused_with_options_and_no_output(script_work):
    source, out, _, _, _ = world(script_work)
    with pytest.raises(BudgetRefused) as exc:
        ingest(source / 'script.json', source / 'engine/episode.json', out, target_seconds=30)
    assert exc.value.options and exc.value.table
    assert 'floors' in str(exc.value)
    assert not out.exists()


def test_hard_script_target_refuses_but_authored_schedule_is_rebudgeted():
    script, episode, domain = sample()
    script['duration_s'] = 30
    docs = derive(script, episode, domain)
    assert docs['contract-plan.json']['total_frames'] > 900
    script['delivery'] = {'target_seconds': 30}
    with pytest.raises(BudgetRefused):
        derive(script, episode, domain)


def test_ingest_idempotent_and_tamper_refuses_before_any_write(script_work):
    source, out, script, _, _ = world(script_work)
    paths = (source / 'script.json', source / 'engine/episode.json')
    result = ingest(*paths, out)
    again = ingest(*paths, out)
    assert result == again
    assert all(sha256_file(out / name) == digest for name, digest in result['files'].items())
    assert read_json(out / 'ingest-receipt.json')['canonical_mode'] == 'ascii'
    assert read_json(out / 'contract-plan.json')['contract']['inputs_sha256'] == sha256_file(out / 'contract-inputs.json')
    (out / 'vocabulary.json').write_text('{}', encoding='utf-8')
    (out / 'dialogue.json').unlink()
    with pytest.raises(Refused, match='overwrite'):
        ingest(*paths, out)
    assert not (out / 'dialogue.json').exists()


@pytest.mark.parametrize('change,expected', [
    (lambda s: s.pop('shots'), 'shots'),
    (lambda s: s.update(fps=True), 'fps'),
    (lambda s: s.update(duration_s=float('nan')), 'finite'),
    (lambda s: s['shots'][0].update(duration_s=-1), 'duration_s'),
    (lambda s: s['shots'][0].update(speech_text=123), 'speech_text'),
    (lambda s: s['shots'][0].update(id='../escape'), 'pattern'),
    (lambda s: s['shots'][1].update(id=s['shots'][0]['id']), 'duplicate shot'),
    (lambda s: s['shots'][0].update(speaker='missing'), 'undeclared'),
    (lambda s: s['character_references']['teacher'].update(speech_allowed=False), 'silent'),
    (lambda s: s['shots'][0].update(duration_frames=3), 'disagrees'),
    (lambda s: s['vocabulary_cards'][0].update(shot_ids=['missing']), 'unknown shot'),
    (lambda s: s['shots'][0].update(entry={'kind': 'carry', 'from_shot': 'S00_A'}), 'predecessor'),
    (lambda s: s['vocabulary_cards'][1].update(term='word 0'), 'duplicate terms'),
    (lambda s: s['voice_reference'].update(teacher='invalid'), 'object'),
    (lambda s: s['voice_reference']['teacher'].update(profile_id=9), 'profile_id'),
    (lambda s: s['shots'][0].update(speech_text='   '), 'blank'),
    (lambda s: s.update(voice_extras=[{'kind': 'end_line'}]), 'required'),
    (lambda s: s.update(voice_extras=[{'kind': 'end_line', 'id': 'bye', 'speaker': 'nobody',
                                    'text_tts': 'Goodbye.', 'target_duration_s': 1}]), 'undeclared'),
])
def test_schema_and_semantic_errors(change, expected):
    script, _, _ = sample()
    change(script)
    with pytest.raises(Refused, match=expected):
        validate_script(script)


def test_ingest_never_writes_inside_source_episode(script_work):
    source, _, _, _, _ = world(script_work)
    with pytest.raises(Refused, match='outside'):
        ingest(source / 'script.json', source / 'engine/episode.json', source / 'generated')
    assert not (source / 'generated').exists()


def test_registry_silent_and_unbound_roles_preserved():
    script, episode, domain = sample()
    script['character_references']['worker'] = {'speech_allowed': False, 'canonical_path': None}
    docs = derive(script, episode, domain)
    worker = next(c for c in docs['cast-bindings.json']['characters'] if c['role'] == 'worker')
    assert worker['reference_status'] == 'unbound'
    assert not docs['voice-cast.json']['speakers']['worker']['speech_allowed']


def test_cli_registration_without_editing_bin_and_refusal_options(script_work, capsys):
    parser = argparse.ArgumentParser()
    stages = parser.add_subparsers(dest='stage', required=True)
    register_cli(stages)
    register_storyboard(stages)
    source, out, _, _, _ = world(script_work)
    args = parser.parse_args(['script', 'ingest', '--script', str(source / 'script.json'),
                              '--episode', str(source / 'engine/episode.json'), '--out', str(out), '--target-seconds', '20'])
    assert run_script(args) == 1
    assert json.loads(capsys.readouterr().out)['options']
    args = parser.parse_args(['storyboard', 'check', '--episode', str(source / 'engine/episode.json')])
    assert args.stage == 'storyboard' and args.verb == 'check'


def test_parity_lists_every_changed_leaf():
    assert differences({'a': [1, 2], 'b': 3}, {'a': [1, 4, 5], 'b': 8}) == [
        {'path': '$.a[1]', 'generated': 2, 'reference': 4},
        {'path': '$.a[2]', 'generated': None, 'reference': 5},
        {'path': '$.b', 'generated': 3, 'reference': 8}]


def test_end_line_gets_its_own_plate_budget():
    script, episode, domain = sample()
    script['voice_extras'] = [{'kind': 'end_line', 'id': 'bye', 'speaker': 'teacher',
                              'text_tts': 'Goodbye.', 'target_duration_s': 1.6}]
    docs = derive(script, episode, domain)
    plate = next(s for s in docs['contract-plan.json']['contract']['sections'] if s['kind'] == 'end_plate')
    assert plate['frames'] >= 48 + 24 and plate['speech_frames'] == 48


def test_existing_config_contract_planner_reproduces_ingest_contract(script_work):
    from engine.config.cli import plan_contract
    source, out, _, episode, _ = world(script_work)
    ingest(source / 'script.json', source / 'engine/episode.json', out, target_seconds=110)
    contract = read_json(out / 'contract-plan.json')['contract']
    publish(out / 'engine', {'episode.json': {**episode, 'files': {'contract_inputs': '../contract-inputs.json'}}})
    planned = plan_contract(out / 'engine/episode.json', skill_root=SKILL_ROOT,
                            target_seconds=110, revision=contract['revision'])
    assert planned['contract'] == contract
