"""Storyboard prose comes from the script; geometry is never invented from prose.

With shot.layout_brief, the shared scene-layout API validates geometry, generates
placement text and measures continuity. Without it, explicit seat/camera/setting
declarations can plan an edit; missing declarations stay UNKNOWN and fail check.
"""
from __future__ import annotations

from pathlib import Path

from ..core.errors import Refused
from ..core.io import canonical_sha256, read_json, sha256_bytes, sha256_file
from ..editorial.boundaries_suggest_rules import allowed, classify, motion_cue, preference
from ..script.ingest import publish
from . import tool as scene


def artifact(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise Refused(f'artefact escapes workspace: {name}')
    return path


def load_ingest(root: Path, episode_id: str) -> dict:
    receipt = read_json(root / 'ingest-receipt.json')
    if receipt.get('schema') != 'jjv/script-ingest/v1' or receipt.get('episode_id') != episode_id:
        raise Refused('ingest receipt episode/schema mismatch')
    for name, digest in receipt['output_content_sha256'].items():
        if canonical_sha256(read_json(artifact(root, name)), mode='ascii') != digest:
            raise Refused(f'ingest artefact changed: {name}; ingest into a new folder')
    return read_json(root / 'script.json')


def build_plan(ingest_dir: Path, out: Path, *, episode_id: str, scene_tool: Path | None = None) -> dict:
    script = load_ingest(Path(ingest_dir), episode_id)
    skeleton = read_json(Path(ingest_dir) / 'shots.json')
    by_id = {r['shot']: r for r in skeleton['shots']}
    documents: dict = {}
    rows = []
    has_geometry = any(s.get('layout_brief') for s in script['shots'])
    tool_pins = scene.pins(scene_tool) if has_geometry else None
    for shot in script['shots']:
        sid = shot['id']
        brief = {'schema': 'jjv/storyboard-brief/v1', 'shot': sid, 'episode_id': episode_id,
                 'status': 'authored_plan', 'speaker': shot['speaker'], 'listener': shot.get('listener'),
                 'speech_text': shot['speech_text'], 'visual': shot['visual'],
                 'continuity': shot.get('continuity') or {}, 'mouth_rule': shot.get('mouth_rule'),
                 'avoid_actions': shot.get('avoid_actions', []), 'entry': by_id[sid]['entry'],
                 'duration_frames': by_id[sid]['duration_frames'],
                 'geometry': f'geometry/{sid}.json' if shot.get('layout_brief') else None}
        documents[f'briefs/{sid}.json'] = brief
        if shot.get('layout_brief'):
            # Embedded, self-contained geometry only; do not silently copy mutable external sets.
            geometry = shot['layout_brief']
            if geometry.get('set') is not None:
                raise Refused(f'{sid}: embed the resolved set geometry; relative external sets are not portable')
            provenance = geometry.get('provenance', {})
            if not isinstance(provenance, dict) or not isinstance(provenance.get('jjv_scaffold', {}), dict):
                raise Refused(f'{sid}: geometry provenance and jjv_scaffold must be objects')
            if provenance.get('jjv_scaffold', {}).get('filled') is False:
                raise Refused(f'{sid}: layout geometry is an unfilled scaffold')
            documents[brief['geometry']] = geometry
        lines = [f"Shot {sid}. Authored placement (geometry not measured):", shot['visual']]
        if brief['mouth_rule']:
            lines.append(f"Mouth constraints: {brief['mouth_rule']}")
        documents[f'placement/{sid}.txt'] = ('\n'.join(lines) + '\n').encode('utf-8')
        rows.append({'shot': sid, 'brief': f'briefs/{sid}.json', 'placement': f'placement/{sid}.txt',
                     'geometry': brief['geometry']})
    # Geometry calls need real paths. Persist only validated snapshots, then freeze the final manifest.
    if has_geometry:
        geometry_docs = {k: v for k, v in documents.items() if k.startswith('geometry/')}
        publish(Path(out), geometry_docs)
        for row in rows:
            if row['geometry']:
                path = Path(out) / row['geometry']
                scene.call(scene_tool, 'validate', str(path))
                placement = scene.call(scene_tool, 'placement-text', str(path))
                documents[row['placement']] = ('\n'.join(placement['lines']) + '\n').encode('utf-8')
    hashes = {name: sha256_bytes(value) if isinstance(value, bytes) else canonical_sha256(value, mode='ascii')
              for name, value in documents.items()}
    plan = {'schema': 'jjv/storyboard-plan/v1', 'episode_id': episode_id,
            'canonical_mode': 'ascii',
            'script_sha256': canonical_sha256(script, mode='ascii'), 'shots': rows,
            'files': hashes, 'tool': tool_pins}
    documents['storyboard-plan.json'] = plan
    publish(Path(out), documents)
    return plan


def _declared_framing(a: dict, b: dict) -> str | None:
    left, right = a['continuity'], b['continuity']
    if any(left.get(k) and right.get(k) and left[k] != right[k] for k in ('setting_id', 'camera_id')):
        return 'new_framing'
    if right.get('framing') in ('same_framing', 'new_framing'):
        return right['framing']
    if all(left.get(k) and left.get(k) == right.get(k) for k in ('setting_id', 'camera_id', 'seat_id')):
        return 'same_framing'
    return None


def check_plan(root: Path, *, episode_id: str, scene_tool: Path | None = None) -> dict:
    root = Path(root)
    plan = read_json(root / 'storyboard-plan.json')
    if plan.get('schema') != 'jjv/storyboard-plan/v1' or plan.get('episode_id') != episode_id:
        raise Refused('storyboard episode/schema mismatch')
    for name, digest in plan['files'].items():
        path = artifact(root, name)
        actual = sha256_file(path) if name.endswith('.txt') else canonical_sha256(read_json(path), mode='ascii')
        if digest != actual:
            raise Refused(f'storyboard input changed: {name}; re-plan into a new folder')
    if plan['tool'] is not None and scene.pins(scene_tool) != plan['tool']:
        raise Refused('scene API changed since planning')
    briefs = {r['shot']: read_json(artifact(root, r['brief'])) for r in plan['shots']}
    picture_shots = frozenset(briefs)
    pairs = []
    for arow, brow in zip(plan['shots'], plan['shots'][1:]):
        a, b = briefs[arow['shot']], briefs[brow['shot']]
        spatial = None
        geometry_framing = None
        if arow['geometry'] and brow['geometry']:
            apath, bpath = artifact(root, arow['geometry']), artifact(root, brow['geometry'])
            spatial = scene.call(scene_tool, 'continuity', str(apath), str(bpath))
            ga, gb = read_json(apath), read_json(bpath)
            if 'camera' in ga and 'camera' in gb:
                geometry_framing = ('same_framing' if ga['camera'] == gb['camera']
                                    and ga.get('ground') == gb.get('ground') else 'new_framing')
        continuity = spatial['classification'].lower() if spatial else 'unknown'
        declared_framing = _declared_framing(a, b)
        resolved_framing = ('new_framing' if 'new_framing' in (geometry_framing, declared_framing)
                            else geometry_framing or declared_framing)
        framing = classify(None, resolved_framing, 0.35)
        if geometry_framing and resolved_framing == geometry_framing:
            framing['source'] = 'layout_geometry'
        motive = b['continuity'].get('motivation', '')
        motivated, _ = motion_cue({'motivation': motive})
        choices = preference(framing['framing'], motivated)
        candidates = allowed(framing['framing'], continuity, picture_shots, a['shot'], b['shot'])
        preset, rule = choices[0]
        if b['entry']['kind'] == 'carry':
            preset, rule, candidates = 'none', 'R1_carry', ['none']
        declared = b['continuity'].get('transition')
        problems = []
        if framing['framing'] == 'unmeasured' and preset != 'none':
            problems.append('UNKNOWN_FRAMING: supply camera/seat/setting ids or an explicit framing declaration')
        if declared and declared not in candidates:
            problems.append(f'TRANSITION_NOT_ALLOWED: {declared}; allowed {candidates}')
        if preset == 'none':
            problems.append('CARRY_UNPROVEN: script carry requires H3 frame evidence before continuity acceptance')
        pairs.append({'from_shot': a['shot'], 'to_shot': b['shot'], 'framing': framing,
                      'continuity': continuity, 'spatial': spatial, 'preset': preset, 'rule': rule,
                      'allowed_presets': candidates, 'problems': problems,
                      'evidence': 'geometry_and_declarations' if spatial else 'author_declarations_only',
                      'media_feasibility': 'pending clips/tails and editorial boundaries suggest'})
    report = {'schema': 'jjv/storyboard-check/v1', 'episode_id': episode_id,
              'canonical_mode': 'ascii',
              'ok': all(not p['problems'] for p in pairs),
              'plan_sha256': canonical_sha256(plan, mode='ascii'), 'pairs': pairs,
              'geometric_pairs': sum(p['spatial'] is not None for p in pairs),
              'status': 'authoring_check_only_not_media_approval'}
    publish(root, {'storyboard-check.json': report})
    return report
