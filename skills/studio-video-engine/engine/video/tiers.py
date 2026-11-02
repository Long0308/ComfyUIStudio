"""Resolution tiers and human promotion records, independent of GPU permission.

H3 generates preview pixels only. Higher tiers upscale approved source clips;
they never regenerate the approved preview through H3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..comfy.staging import require_hash
from ..core.errors import Refused
from ..core.io import read_json, sha256_file, write_json_once
from ..h3 import ledger
from ..layout.context import SKILL_ROOT
from ..media.probe import probe_video
from ..voice.approval import check_listener
from . import state as state_mod

NAMES = ('preview', 'fullhd', '2k')
SCHEMA = 'jjv/video-tier-approval/v1'
POLICY = SKILL_ROOT / 'recipes/video/resolution-tiers-v001.json'


def profile(tier: str) -> dict:
    if tier not in NAMES:
        raise Refused(f'TIER_UNKNOWN: --tier must be one of {NAMES}')
    return read_json(POLICY)['tiers'][tier]


def _media(ref: Any, root: Path, size: str) -> dict:
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str) or not isinstance(ref.get('sha256'), str):
        raise Refused('TIER_APPROVAL_INVALID: media needs path and sha256')
    path = (root / ref['path']).resolve()
    require_hash(path, ref['sha256'], 'tier-approved media')
    info = probe_video(path)
    if f'{info.width}x{info.height}' != size:
        raise Refused(f'TIER_APPROVAL_INVALID: {path} is {info.width}x{info.height}, needs {size}')
    return {'path': str(path), 'sha256': ref['sha256']}


def approval(ctx: Any, tier: str, path: Path | None, shotlist: dict, shots: list[str]) -> tuple[dict | None, dict]:
    """Validate the entire scope before writes. Relative media paths use record.parent."""
    spec = profile(tier)
    previous = spec.get('requires_approved_tier')
    if previous is None:
        if path is not None:
            raise Refused('TIER_APPROVAL_UNEXPECTED: preview needs no promotion record')
        return None, {}
    if path is None or not Path(path).is_file():
        raise Refused(f'TIER_APPROVAL_REQUIRED: --tier {tier} needs --tier-approval <record.json> '
                      f'({SCHEMA}, approved {previous} cut); GPU permission is separate')
    path = Path(path).resolve()
    record_sha = sha256_file(path)
    body = read_json(path)
    expected = {'schema': SCHEMA, 'episode_id': ctx.episode_id, 'domain': ctx.domain_id,
                'target_tier': tier, 'source_tier': previous, 'status': 'approved',
                'shotlist_sha256': shotlist['sha256']}
    if not isinstance(body, dict) or any(body.get(k) != v for k, v in expected.items()):
        raise Refused('TIER_APPROVAL_INVALID: schema, episode, domain, target/source tier, status or shotlist mismatch')
    if not isinstance(body.get('approved_by'), str):
        raise Refused('TIER_APPROVAL_INVALID: approved_by must name a person')
    check_listener(body['approved_by'])
    try:
        stamp = datetime.fromisoformat(body['approved_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc):
            raise ValueError('timezone missing or future timestamp')
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise Refused('TIER_APPROVAL_INVALID: approved_at needs a past ISO-8601 timestamp with timezone') from error
    if not isinstance(body.get('note'), str) or not body['note'].strip():
        raise Refused('TIER_APPROVAL_INVALID: note must record what the user approved')
    sources = body.get('shots')
    if not isinstance(sources, dict) or set(sources) != set(shots):
        raise Refused('TIER_APPROVAL_INVALID: shots must cover exactly this shotlist')
    size = profile(previous)['target']
    cut = _media(body.get('cut'), path.parent, size)
    verified = {shot: _media(ref, path.parent, size) for shot, ref in sources.items()}
    rejected = ledger.rejected_shas(ctx)
    if any(ref['sha256'] in rejected for ref in (cut, *verified.values())):
        raise Refused('TIER_SOURCE_REJECTED: rejected cut/source bytes cannot be promoted in another folder')
    require_hash(path, record_sha, 'tier approval during validation')
    return {'path': str(path), 'sha256': record_sha, 'cut': cut}, verified


def resolve(ctx: Any, route: dict, template: dict, tier: str, record: Path | None,
            shotlist: dict, shots: list[str]) -> tuple[dict, dict]:
    spec = profile(tier)
    binding, _ = approval(ctx, tier, record, shotlist, shots)
    native = profile('preview')['target']
    width, height = map(int, native.split('x'))
    declared = route.get('geometry') or {}
    node = route['ports']['length'].split('.')[0]
    ports = {axis: declared.get(f'{axis}_port', f'{node}.{axis}') for axis in ('width', 'height')}
    graph = read_json(template['path'])
    for dotted in ports.values():
        if not isinstance(dotted, str) or len(dotted.split('.')) != 2:
            raise Refused('TIER_GEOMETRY_INVALID: geometry ports must be NODE.input')
        n, key = dotted.split('.')
        if key not in (graph.get(n, {}).get('inputs') or {}):
            raise Refused(f'TIER_GEOMETRY_MISSING: editable H3 template has no {dotted}')
    resolution = {'tier': tier, 'target': spec['target'], 'h3_native': native,
                  'method': spec['method'], 'crop_mode': 'center-crop', 'approval': binding}
    return resolution, {'width': width, 'height': height, 'ports': ports}


def validate(ctx: Any, plan: dict, requested: str | None = None) -> dict:
    """Recheck frozen policy, approval bytes, source media and shotlist at execution/resume."""
    resolution = plan.get('resolution')
    if not isinstance(resolution, dict) or plan.get('tier') != resolution.get('tier'):
        raise Refused('TIER_PLAN_MISSING: re-plan legacy output with an explicit resolution tier')
    tier = resolution['tier']
    spec = profile(tier)
    if requested is not None and requested != tier:
        raise Refused(f'TIER_PLAN_DRIFT: --tier {requested} differs from frozen plan tier {tier}; use a new --out')
    if (resolution.get('target'), resolution.get('h3_native'), resolution.get('method')) != (
            spec['target'], profile('preview')['target'], spec['method']):
        raise Refused('TIER_PLAN_DRIFT: frozen resolution no longer matches policy; re-plan')
    shotlist = plan['shotlist']
    # Planning stores absolute shotlist paths for a stable promotion scope.
    require_hash(Path(shotlist['path']), shotlist['sha256'], 'tier shotlist')
    binding = resolution.get('approval')
    record = None
    if binding is not None:
        record = Path(binding['path'])
        require_hash(record, binding['sha256'], 'tier approval record')
    checked, sources = approval(ctx, tier, record, shotlist, [r['shot'] for r in plan['shots']])
    if checked != binding:
        raise Refused('TIER_APPROVAL_INVALID: frozen approval binding changed')
    return sources


def effective_route(route: dict, plan: dict) -> dict:
    resolution = plan['resolution']
    return {**route, 'upscale': {**route['upscale'], 'target': resolution['target'],
                               'crop_mode': resolution['crop_mode']}}


def promotion_payload(plan: dict, shot: str, source: dict) -> dict:
    return {'shot': shot, 'tier': plan['tier'], 'resolution': plan['resolution'],
            'submit': False, 'route': 'approved-tier-source', 'source': source,
            'target': plan['resolution']['target'], 'h3_inference': False}


def promote(ctx: Any, out: Path, state: dict, plan: dict, source: dict) -> Path:
    """Bind the approved previous-tier clip as input, with no H3 inference or media rewrite."""
    body = {'schema': state_mod.RENDER_RECEIPT_SCHEMA, 'episode_id': ctx.episode_id, 'domain': ctx.domain_id,
            'shot': state['shot'], 'revision': state['revision'], 'tier': plan['tier'],
            'resolution': plan['resolution'], 'route': 'approved-tier-source',
            'promotion': {'approval': plan['resolution']['approval'], 'source': source},
            'plan_receipt': state['receipts']['plan'], 'prompt_receipt': state['receipts']['prompt'],
            'native': {**source, 'name': Path(source['path']).name}}
    path = state_mod.shot_dir(out, state['shot']) / 'render' / state_mod.rev(state['revision']) / 'render-receipt.json'
    write_json_once(path, body, mode='utf8')
    return path


def retain_preview(ctx: Any, out: Path, state: dict, render: dict) -> Path:
    """Review-ready receipt at native size; no pixels are rescaled or copied.

    The historical state name upscaled_1080 is retained for receipt compatibility;
    target/tier and backend describe the actual 864x480 artifact.
    """
    source = render['native']
    verify_preview(source)
    body = {'schema': state_mod.UPSCALE_RECEIPT_SCHEMA, 'episode_id': ctx.episode_id, 'domain': ctx.domain_id,
            'shot': state['shot'], 'revision': state['revision'], 'tier': 'preview',
            'backend': 'native-preview', 'target': profile('preview')['target'],
            'source': source, 'output': source, 'status': 'review-pending',
            'render_receipt': state['receipts']['render']}
    path = state_mod.shot_dir(out, state['shot']) / 'upscale' / state_mod.rev(state['revision']) / 'upscale-receipt.json'
    write_json_once(path, body, mode='utf8')
    return path


def verify_preview(source: dict) -> dict:
    path = Path(source['path'])
    require_hash(path, source['sha256'], 'preview take')
    info = probe_video(path)
    size = f'{info.width}x{info.height}'
    if size != profile('preview')['target']:
        raise Refused(f'TIER_OUTPUT_GEOMETRY: preview output is {size}, needs 864x480; not review-ready')
    return {'width': info.width, 'height': info.height}
