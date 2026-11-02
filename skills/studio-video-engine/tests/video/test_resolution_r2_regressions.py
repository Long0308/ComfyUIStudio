"""R2 refusal order, rejected-source promotion, and adapter approval regressions."""
import json
from pathlib import Path

import pytest

from test_resolution_tiers import record, world, media_probe  # noqa: F401
from tier_workspace import workspace  # noqa: F401
from video_fixtures import CARTOON, LIVE, SHOT, sha_file
from engine.core.errors import Refused
from engine.core.io import read_json
from engine.h3 import ledger
from engine.video import tiers, upscale_comfy as adapter


def test_wrong_domain_is_refused_before_tier_gate_or_output_creation(world):
    body = read_json(world.shotlist)
    body['domain'] = LIVE if world.domain == CARTOON else CARTOON
    world.shotlist.write_text(json.dumps(body), encoding='utf-8')
    code, result = world.plan('--tier', '2k')
    assert code == 1 and 'VIDEO_DOMAIN_REFUSED' in result['error']
    assert not world.out.exists()


@pytest.mark.parametrize('tier', ['fullhd', '2k'])
@pytest.mark.parametrize('subject', ['cut', 'shot'])
def test_rejected_previous_tier_bytes_cannot_be_promoted(world, media_probe, tier, subject):
    approval = record(world, tier)
    body = read_json(approval)
    ref = body['cut'] if subject == 'cut' else body['shots'][SHOT]
    ledger.append_entry(world.ctx(), {'shot': SHOT, 'decision': 'reject', 'decided_by': 'Kim',
        'reason': 'User rejected these bytes', 'subject': {'sha256': ref['sha256']}, 'decided_unix': 1})
    code, result = world.plan('--tier', tier, '--tier-approval', str(approval))
    assert code == 1 and 'TIER_SOURCE_REJECTED' in result['error']
    assert not world.out.exists()


def test_new_rejection_blocks_frozen_promotion_on_resume(world, media_probe):
    approval = record(world, '2k')
    assert world.plan('--tier', '2k', '--tier-approval', str(approval))[0] == 0
    plan = read_json(world.out / 'plan.json')
    source = tiers.validate(world.ctx(), plan)[SHOT]
    ledger.append_entry(world.ctx(), {'shot': SHOT, 'decision': 'reject', 'decided_by': 'Kim',
        'reason': 'Rejected after planning', 'subject': source, 'decided_unix': 1})
    with pytest.raises(Refused, match='TIER_SOURCE_REJECTED'):
        tiers.validate(world.ctx(), plan)


def test_qualified_2k_adapter_still_refuses_missing_promotion(world):
    qual = world.tmp / 'qualification.json'
    qual.write_text(json.dumps({'schema': adapter.QUALIFICATION_SCHEMA, 'status': 'qualified',
        'backend': adapter.NAME, 'backend_contract': adapter.CONTRACT, 'domain': world.domain,
        'model': {'name': 'fixture'}, 'targets': ['2560x1440']}), encoding='utf-8')
    backend = adapter.ComfyRealEsrgan1080({'path': str(qual), 'route': {'crop_mode': 'center-crop'}})
    with pytest.raises(Refused, match='TIER_APPROVAL_REQUIRED'):
        backend.run(world.ctx(), source={}, target='2560x1440', out_dir=world.tmp / 'must-not-exist',
                    shot=SHOT, revision=1, gpu_approval=None, comfy=object(),
                    render_receipt={}, receipt_root=world.out)
    assert not (world.tmp / 'must-not-exist').exists()
