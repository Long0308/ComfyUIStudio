"""Exercise promotion adapter and real CPU geometry checks; no GPU or network."""
from pathlib import Path
from types import SimpleNamespace
import json
import shutil
import subprocess
import pytest

from test_resolution_tiers import record, world, media_probe  # noqa: F401
from tier_workspace import workspace  # noqa: F401
from video_fixtures import SHOT, run_video, sha_file
from engine.core.errors import Refused
from engine.core.io import read_json, write_json_once
from engine.video import tiers, state as state_mod, upscale_comfy as adapter


@pytest.mark.parametrize('mismatched', [False, True])
@pytest.mark.parametrize('tier,target,source_size', [
    ('fullhd', '1920x1080', (864, 480)), ('2k', '2560x1440', (1920, 1080))])
def test_adapter_checks_promotion_and_produces_bound_receipt(world, media_probe, monkeypatch, mismatched,
                                                           tier, target, source_size):
    path = record(world, tier)
    assert world.plan('--tier', tier, '--tier-approval', str(path))[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    plan = read_json(world.out / 'plan.json')
    state = world.state()
    source = tiers.validate(world.ctx(), plan)[SHOT]
    rendered = read_json(tiers.promote(world.ctx(), world.out, state, plan, source))
    qual = world.tmp / 'qualification.json'
    qual.write_text(json.dumps({'schema': adapter.QUALIFICATION_SCHEMA, 'status': 'qualified',
        'backend': adapter.NAME, 'backend_contract': adapter.CONTRACT, 'domain': world.domain,
        'model': {'name': 'fixture-model'}, 'targets': [target]}), encoding='utf-8')
    backend = adapter.ComfyRealEsrgan1080({'path': str(qual), 'route': {'crop_mode': 'center-crop'}})
    if mismatched:
        rendered['promotion']['source'] = {**source, 'sha256': '0' * 64}
    saved = world.tmp / 'saved-upscaled.mp4'
    saved.write_bytes(b'fake-server-upscaled-media')
    captures = []

    def dispatch(client, settings, **kw):
        captures.append(kw['graph'])
        write_json_once(kw['receipt_dir'] / adapter.SUBMITTED_FILE, {'prompt_id': 'test-prompt'}, mode='utf8')

    def wait(client, settings, **kw):
        write_json_once(kw['receipt_dir'] / adapter.commands.JOB_FILE, {'prompt_id': 'test-prompt',
            'graph_sha256': 'f' * 64, 'outputs': [{'node_id': '9', 'exists': True,
                'path': str(saved), 'sha256': sha_file(saved)}]}, mode='utf8')

    def measured(p):
        size = tuple(map(int, target.split('x'))) if Path(p).parent.name == 'upscale-test' else source_size
        return {'width': size[0], 'height': size[1],
                'frames': 124, 'fps': '24/1', 'audio_streams': 1}

    monkeypatch.setattr(adapter, 'dispatch', dispatch)
    monkeypatch.setattr(adapter.commands, 'cmd_check', lambda *a, **k: ({}, True))
    monkeypatch.setattr(adapter.commands, 'cmd_wait', wait)
    monkeypatch.setattr(adapter, 'container_instance', lambda *a: None)
    monkeypatch.setattr(adapter, 'probe_media', measured)
    handles = SimpleNamespace(settings=SimpleNamespace(input_dir=world.h3.settings().input_dir,
        container='fake', history_timeout_seconds=1), client=object(), probe=object(), ps=lambda *a: '')
    kwargs = dict(source=source, target=target, out_dir=world.tmp / 'upscale-test', shot=SHOT, revision=1,
                  gpu_approval={'kind': 'token', 'value': 'unit-test-only'}, comfy=handles,
                  render_receipt=rendered, receipt_root=world.out)
    if mismatched:
        with pytest.raises(Refused, match='TIER_SOURCE_DRIFT'):
            backend.run(world.ctx(), **kwargs)
        assert captures == []
        return
    result = backend.run(world.ctx(), **kwargs)
    assert len(captures) == 1
    assert captures[0]['5']['inputs']['crop'] == 'center'
    assert result['source']['sha256'] == source['sha256']
    assert result['approved_source'] == source
    width, height = map(int, target.split('x'))
    assert result['output']['width'] == width and result['output']['height'] == height
    assert Path(result['output']['path']).name == f'{SHOT}-{height}p.mp4'
    assert result['tier_approval']['sha256'] == sha_file(path)
    assert all(result['checks'].values())


@pytest.mark.parametrize('size,refused', [('864x480', False), ('1280x704', True)])
def test_native_preview_output_is_measured_before_review_receipt(world, size, refused):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg/ffprobe required')
    assert world.plan()[0] == 0
    assert run_video(world.base('prompt'))[0] == 0
    native = world.tmp / 'native.mp4'
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
               '-i', f'color=c=black:s={size}:r=24', '-frames:v', '1', '-an', '-c:v', 'libx264',
               '-threads', '1', str(native)]
    proc = subprocess.run(command, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    state = world.state()
    render = {'native': {'path': str(native), 'sha256': sha_file(native)}}
    receipt = world.out / SHOT / 'render-fixture.json'
    write_json_once(receipt, render, mode='utf8')
    state = state_mod.advance(world.out, state, 'rendered', receipt_key='render', receipt_path=receipt)
    if refused:
        with pytest.raises(Refused, match='TIER_OUTPUT_GEOMETRY.*1280x704'):
            tiers.retain_preview(world.ctx(), world.out, state, render)
        assert not (world.out / SHOT / 'upscale').exists()
        assert world.state()['state'] == 'rendered'
    else:
        ready = read_json(tiers.retain_preview(world.ctx(), world.out, state, render))
        assert ready['target'] == '864x480' and ready['output']['sha256'] == sha_file(native)
