"""CPU tier contracts. Test workspaces use normal inherited directory permissions.

No override of pytest's tmp_path or OS ACLs; the new tests own their workspace
explicitly so they can run despite the separately reported pytest mode=0700 bug.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from video_fixtures import VideoWorld, run_video, SHOT, sha_file
from tier_workspace import workspace  # noqa: F401 - pytest fixture
from engine.core.errors import Refused
from engine.core import steplog
from engine.core.io import read_json, write_json_once
from engine.h3 import prepare
from engine.video import tiers, state as state_mod, run as run_mod, upscale, accept


@pytest.fixture
def world(workspace):
    return VideoWorld(workspace)


@pytest.fixture
def media_probe(monkeypatch):
    def probe(path):
        size = '1920x1080' if Path(path).name.startswith('fullhd') else '864x480'
        w, h = map(int, size.split('x'))
        return SimpleNamespace(width=w, height=h)
    monkeypatch.setattr(tiers, 'probe_video', probe)


def record(world, tier='2k', **overrides):
    previous = 'fullhd' if tier == '2k' else 'preview'
    cut = world.tmp / f'{previous}-cut.mp4'
    source = world.tmp / f'{previous}-shot.mp4'
    cut.write_bytes(b'approved cut fixture')
    source.write_bytes(b'approved shot fixture')
    ref = lambda p: {'path': p.name, 'sha256': sha_file(p)}
    body = {'schema': tiers.SCHEMA, 'episode_id': world.ctx().episode_id, 'domain': world.domain,
            'shotlist_sha256': sha_file(world.shotlist), 'target_tier': tier, 'source_tier': previous,
            'status': 'approved', 'approved_by': 'Kim', 'approved_at': '2026-01-01T00:00:00Z',
            'note': 'User watched the cut and approved promotion', 'cut': ref(cut), 'shots': {SHOT: ref(source)},
            **overrides}
    path = world.tmp / 'human-approval.json'
    path.write_text(json.dumps(body), encoding='utf-8')
    return path


def test_default_preview_overrides_old_1280_template_and_routes(world):
    graph = read_json(world.h3.template)
    graph['6']['inputs'].update(width=1280, height=704)
    world.h3.template.write_text(json.dumps(graph), encoding='utf-8')
    routes = read_json(world.routes)
    row = routes['domains'][world.domain]
    row['template']['sha256'] = sha_file(world.h3.template)
    row['geometry'] = {'width': 1280, 'height': 704, 'width_port': '6.width', 'height_port': '6.height'}
    world.routes.write_text(json.dumps(routes), encoding='utf-8')
    code, result = world.plan()
    assert code == 0, result
    assert result['tier'] == 'preview'
    assert result['upscale']['target'] == '864x480'
    plan = read_json(world.out / 'plan.json')
    shot = read_json(world.out / SHOT / 'plan-receipt.json')
    assert plan['tier'] == shot['tier'] == 'preview'
    assert (shot['geometry']['width'], shot['geometry']['height']) == (864, 480)
    code, dry = world.run('--dry-run', '--completion')
    assert code == 0, dry
    payload = dry['payloads'][0]
    assert payload['geometry'] == {'width': 864, 'height': 480, 'fps': 24}
    assert payload['graph_inputs']['6.width'] == 864
    assert payload['graph_inputs']['6.height'] == 480
    assert payload['tier'] == 'preview'
    assert steplog.verify(world.out)['ok']
    line = json.loads((world.out / 'steplog.jsonl').read_text('utf-8').splitlines()[0])
    assert line['settings']['tier'] == 'preview'
    assert line['settings']['geometry']['width'] == 864


def test_preview_size_reaches_h3_spec_and_prepared_graph(world, monkeypatch):
    assert world.plan()[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    spec = read_json(world.out / 'h3-spec-r001.json')
    assert spec['shots'][0]['mouth']['6.width'] == 864
    assert spec['shots'][0]['mouth']['6.height'] == 480
    manifest = world.write_h3_inputs()
    document = read_json(manifest)
    # This unit test isolates geometry binding from unrelated identity-library gates.
    monkeypatch.setattr(prepare, 'require_anchor_pack_or_approved_legacy', lambda *a: None)
    graph, receipt = prepare.build_shot(world.ctx(), document, document['shots'][0])
    assert graph['6']['inputs']['width'] == receipt['mouth']['6.width'] == 864
    assert graph['6']['inputs']['height'] == receipt['mouth']['6.height'] == 480
    assert receipt['wav']['sha256'] == sha_file(world.h3.wav)


@pytest.mark.parametrize('tier', ['fullhd', '2k'])
def test_higher_tier_requires_record(world, tier):
    code, result = world.plan('--tier', tier)
    assert code == 1 and 'TIER_APPROVAL_REQUIRED' in result['error']
    assert not (world.out / 'plan.json').exists()


@pytest.mark.parametrize('tier,target', [('preview', '864x480'), ('fullhd', '1920x1080'), ('2k', '2560x1440')])
def test_three_tiers_are_frozen_in_plan_and_steplog(world, media_probe, tier, target):
    extra = [] if tier == 'preview' else ['--tier-approval', str(record(world, tier))]
    code, result = world.plan('--tier', tier, *extra)
    assert code == 0, result
    plan = read_json(world.out / 'plan.json')
    assert plan['tier'] == tier and plan['resolution']['target'] == target
    assert result['upscale']['target'] == target
    assert plan['resolution']['h3_native'] == '864x480'
    settings = json.loads((world.out / 'steplog.jsonl').read_text('utf-8').splitlines()[0])['settings']
    assert settings['tier'] == tier and settings['resolution']['target'] == target
    assert steplog.verify(world.out)['ok']


@pytest.mark.parametrize('change', [
    {'schema': 'fake'}, {'episode_id': 'other'}, {'domain': 'other'}, {'target_tier': 'fullhd'},
    {'source_tier': 'preview'}, {'status': 'pending'}, {'status': 'rejected'},
    {'shotlist_sha256': '0' * 64}, {'approved_by': 'codex'}, {'approved_by': ''},
    {'approved_at': 'bad date'}, {'approved_at': '2026-01-01'}, {'approved_at': '2999-01-01T00:00:00Z'},
    {'note': ''}, {'shots': {}}, {'cut': {}},
])
def test_2k_refuses_invalid_approval_before_plan_write(world, media_probe, change):
    path = record(world, **change)
    code, result = world.plan('--tier', '2k', '--tier-approval', str(path))
    assert code == 1, result
    assert not (world.out / 'plan.json').exists()


def test_2k_refuses_mislabeled_fullhd_dimensions(world, monkeypatch):
    path = record(world)
    monkeypatch.setattr(tiers, 'probe_video', lambda p: SimpleNamespace(width=864, height=480))
    code, result = world.plan('--tier', '2k', '--tier-approval', str(path))
    assert code == 1 and 'needs 1920x1080' in result['error']


@pytest.mark.parametrize('changed', ['approval', 'cut', 'source', 'shotlist'])
def test_resume_rechecks_record_media_and_scope_hashes(world, media_probe, changed):
    path = record(world)
    assert world.plan('--tier', '2k', '--tier-approval', str(path))[0] == 0
    target = {'approval': path, 'cut': world.tmp / 'fullhd-cut.mp4',
              'source': world.tmp / 'fullhd-shot.mp4', 'shotlist': world.shotlist}[changed]
    target.write_bytes(target.read_bytes() + b'\nchanged')
    code, result = world.run('--completion', '--dry-run')
    assert code == 1 and 'hash mismatch' in result['error'].lower(), result


def test_explicit_tier_cannot_override_frozen_plan(world):
    assert world.plan()[0] == 0
    code, result = world.run('--dry-run', '--tier', '2k')
    assert code == 1 and 'TIER_PLAN_DRIFT' in result['error']


def test_gpu_token_does_not_bypass_tier_gate_or_open_comfy(world, monkeypatch):
    from engine.video import cli
    assert world.plan()[0] == 0
    monkeypatch.setattr(cli, '_handles', lambda *a: pytest.fail('tier refusal opened ComfyUI'))
    code, result = world.run('--tier', '2k', '--gpu-approved', 'token:user approved GPU')
    assert code == 1 and 'TIER_PLAN_DRIFT' in result['error']


def test_legacy_plan_acceptance_is_refused_before_ledger_write(world):
    assert world.plan()[0] == 0
    plan = read_json(world.out / 'plan.json')
    plan.pop('tier')
    (world.out / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    with pytest.raises(Refused, match='TIER_PLAN_MISSING'):
        accept.decide(world.ctx(), world.out, SHOT, 'pick', by='Kim', reason='watched', sha256='0' * 64)
    assert not (world.root / 'engine/h3-acceptance-ledger.jsonl').exists()


def test_preview_review_uses_same_bytes_without_upscale(world, monkeypatch, media_probe):
    assert world.plan()[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    state = world.state()
    native = world.tmp / 'preview-result.mp4'
    native.write_bytes(b'preview fixture')
    render = {'native': {'path': str(native), 'sha256': sha_file(native)}}
    render_path = world.out / SHOT / 'render.json'
    write_json_once(render_path, render, mode='utf8')
    state_mod.advance(world.out, state, 'rendered', receipt_key='render', receipt_path=render_path)
    monkeypatch.setattr(upscale, 'upscale', lambda *a, **k: pytest.fail('preview called an upscale backend'))
    code, result = world.run('--completion')
    assert code == 0 and result['gate']['kind'] == 'take-acceptance', result
    state = world.state()
    assert state['state'] == 'upscaled_1080'  # historical enum; receipt below records actual size
    up = state_mod.verify_ref(world.out, state['receipts']['upscale'], 'upscale')
    assert up['target'] == '864x480' and up['backend'] == 'native-preview'
    assert up['output']['sha256'] == sha_file(native)


def test_promoted_render_consumes_approved_clip_and_logs_tier_without_h3(world, media_probe, monkeypatch):
    path = record(world, 'fullhd')
    assert world.plan('--tier', 'fullhd', '--tier-approval', str(path))[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    monkeypatch.setattr(run_mod.render_mod, 'render', lambda *a, **k: pytest.fail('promotion called H3'))
    code, result = run_video(world.base('render', '--shot', SHOT, '--revision', '1', '--route', 'h3-ref2va',
                                      '--tier', 'fullhd'))
    assert code == 0, result
    state = world.state()
    render = state_mod.verify_ref(world.out, state['receipts']['render'], 'render')
    assert render['native']['sha256'] == sha_file(world.tmp / 'preview-shot.mp4')
    assert render['promotion']['approval']['sha256'] == sha_file(path)
    assert not (world.out / 'h3-r001').exists()
    line = json.loads((world.out / 'steplog.jsonl').read_text('utf-8').splitlines()[-1])
    assert line['settings']['tier'] == 'fullhd' and line['status'] == 'COMPLETE'
    assert steplog.verify(world.out)['ok']
    code, dry = world.run('--dry-run', '--completion')
    assert code == 0, dry
    assert dry['payloads'][0]['h3_inference'] is False
    assert dry['payloads'][0]['source']['sha256'] == sha_file(world.tmp / 'preview-shot.mp4')


@pytest.mark.parametrize('rejected', [False, True])
def test_promoted_output_review_and_rejection_without_h3_adoption(world, media_probe, rejected):
    path = record(world, 'fullhd')
    assert world.plan('--tier', 'fullhd', '--tier-approval', str(path))[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    plan = read_json(world.out / 'plan.json')
    state = world.state()
    source = tiers.validate(world.ctx(), plan)[SHOT]
    rendered = tiers.promote(world.ctx(), world.out, state, plan, source)
    state = state_mod.advance(world.out, state, 'rendered', receipt_key='render', receipt_path=rendered)
    output = world.tmp / 'fullhd-output.mp4'
    output.write_bytes(b'upscaled candidate')
    up_path = world.out / SHOT / 'up-test.json'
    write_json_once(up_path, {'output': {'path': str(output), 'sha256': sha_file(output)}}, mode='utf8')
    state_mod.advance(world.out, state, 'upscaled_1080', receipt_key='upscale', receipt_path=up_path)
    if rejected:
        from engine.h3 import ledger
        ledger.append_entry(world.ctx(), {'shot': SHOT, 'decision': 'reject', 'decided_by': 'Kim',
                            'reason': 'previous rejection', 'subject': {'sha256': sha_file(output)}, 'decided_unix': 0})
        with pytest.raises(Refused, match='TIER_TAKE_REJECTED'):
            accept.decide(world.ctx(), world.out, SHOT, 'pick', by='Kim', reason='watched', sha256=sha_file(output))
        assert world.state()['state'] == 'upscaled_1080'
        return
    result = accept.decide(world.ctx(), world.out, SHOT, 'pick', by='Kim', reason='watched', sha256=sha_file(output))
    assert result['state'] == 'accepted'
    accepted = read_json(Path(result['record']))
    assert accepted['tier_acceptance']['sha256'] == sha_file(output)
    assert accepted['h3_acceptance'] is None


def test_2k_still_requires_domain_target_qualification(world, media_probe):
    from engine.video.upscale_comfy import ComfyRealEsrgan1080, QUALIFICATION_SCHEMA, NAME, CONTRACT
    qualification = world.tmp / 'qual.json'
    qualification.write_text(json.dumps({'schema': QUALIFICATION_SCHEMA, 'status': 'qualified', 'backend': NAME,
        'backend_contract': CONTRACT, 'domain': world.domain, 'model': {'name': 'test'}}), encoding='utf-8')
    backend = ComfyRealEsrgan1080({'path': str(qualification), 'route': {'crop_mode': 'center-crop'}})
    with pytest.raises(Refused, match='UPSCALE_TARGET_UNQUALIFIED'):
        backend.run(world.ctx(), source={}, target='2560x1440', out_dir=world.tmp, shot=SHOT, revision=1,
                    gpu_approval=None, comfy=object(), render_receipt={}, receipt_root=world.out)


@pytest.mark.parametrize('tier', ['fullhd', '2k'])
def test_approval_measures_real_cpu_video_with_ffprobe(world, tier):
    import shutil
    import subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe are required for the real-media CPU test')
    path = record(world, tier)
    body = read_json(path)
    previous = body['source_tier']
    size = tiers.profile(previous)['target']
    cut = path.parent / body['cut']['path']
    source = path.parent / body['shots'][SHOT]['path']
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
               '-i', f'color=c=black:s={size}:r=24', '-frames:v', '1', '-an',
               '-c:v', 'libx264', '-threads', '1', str(cut)]
    rendered = subprocess.run(command, capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stderr
    shutil.copyfile(cut, source)
    body['cut']['sha256'] = sha_file(cut)
    body['shots'][SHOT]['sha256'] = sha_file(source)
    path.write_text(json.dumps(body), encoding='utf-8')
    code, planned = world.plan('--tier', tier, '--tier-approval', str(path))
    assert code == 0, planned
    assert tiers.validate(world.ctx(), read_json(world.out / 'plan.json'))[SHOT]['sha256'] == sha_file(source)
