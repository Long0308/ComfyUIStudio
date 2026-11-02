"""CPU-only ingest. Authored timing is a reservation, never receipt-WAV evidence.

The authored duration is a preferred minimum; delivery.target_seconds / --target-seconds
is a hard limit and is refused by the shared allocator if it violates a floor.
Missing H3/voice bindings remain null in a separate skeleton schema.
"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path

from ..config.budget import _need, allocate, fixed_section_kinds, section_kinds, totals
from ..config.contract import build_contract, check_contract, render_delivery_contract, timeline_from_contract
from ..config.loader import SKILL_ROOT
from ..core.errors import Refused
from ..core.io import canonical_sha256, pretty_json, read_json, sha256_bytes, sha256_file, write_once
from ..voice.script_ingest import dialogue_from_script
from .validate import validate_script


def publish(out: Path, documents: dict[str, object]) -> dict[str, str]:
    """Preflight all existing artefacts before writing any; immutable and idempotent."""
    payloads = {name: value if isinstance(value, bytes) else pretty_json(value, mode='ascii')
                for name, value in documents.items()}
    for name, payload in payloads.items():
        path = out / name
        if not path.resolve().is_relative_to(out.resolve()):
            raise Refused(f'output path escapes workspace: {name}')
        if path.exists() and (not path.is_file() or path.read_bytes() != payload):
            raise Refused(f'refusing to overwrite {path}; use a new output directory')
    return {name: write_once(out / name, payload) for name, payload in payloads.items()}


def load_episode(ref: str, *, repo_root: Path | None = None) -> tuple[Path, dict]:
    from ..config.loader import REPO_ROOT, find_episode_file
    path = find_episode_file(ref, repo_root=repo_root or REPO_ROOT)
    return path, read_json(path)


def domain_for(episode: dict, *, skill_root: Path = SKILL_ROOT) -> dict:
    domain = episode.get('domain')
    # Resolve only a configured domain file, never arbitrary path traversal.
    if not isinstance(domain, str) or not domain or Path(domain).name != domain or '/' in domain or '\\' in domain:
        raise Refused('episode.domain must name a configured domain')
    return read_json(skill_root / 'domains' / f'{domain}.json')

SECTION_KIND_NAME = re.compile(r'^[a-z][a-z0-9_]*$')
# Kinds the engine always builds, or whose removal would leave a film without its speech, logo or end plate.
STRUCTURAL_KINDS = ('intro', 'dialogue', 'logo_hold', 'end_plate', 'end_card')


def parse_section_kinds(spec: str) -> list[tuple[str, bool]]:
    """``+vocab_card,-broll`` becomes ``[('vocab_card', True), ('broll', False)]``; a bare name means ``+``."""
    items: list[tuple[str, bool]] = []
    for raw in spec.split(','):
        token = raw.strip()
        on = not token.startswith('-')
        name = token[1:].strip() if token[:1] in ('+', '-') else token
        if not SECTION_KIND_NAME.match(name):
            raise Refused(f'--section-kinds: {raw.strip()!r} is not a section kind name '
                          '(lowercase letters, digits and underscores, optional + or - prefix)')
        items.append((name, on))
    names = [name for name, _ in items]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise Refused(f'--section-kinds names {repeated} more than once')
    return items


def effective_section_kinds(domain: dict, spec: str | None) -> dict:
    """The kinds this run uses. Every kind the domain declares is on by default; ``spec`` switches some.

    A kind the domain does not declare can never be switched on, and a structural kind can never be
    switched off. Nothing is written back to the domain file.
    """
    declared = list(section_kinds(domain))
    if spec is None:
        return {'declared': declared, 'requested': None, 'effective': declared}
    effective = list(declared)
    for name, on in parse_section_kinds(spec):
        if name not in declared:
            raise Refused(f'section kind {name!r} is not declared by domain {domain["domain_id"]!r}; '
                          f'declared kinds are {declared}')
        if on:
            continue
        if name in STRUCTURAL_KINDS:
            raise Refused(f'section kind {name!r} is structural and cannot be switched off for a run')
        effective.remove(name)
    return {'declared': declared, 'requested': spec, 'effective': effective}


def domain_for_run(domain: dict, effective: list[str]) -> dict:
    """A copy of the domain whose section vocabulary is this run's kinds. The domain file is never changed."""
    run = copy.deepcopy(domain)
    run['delivery'] = {**domain['delivery'], 'section_kinds': list(effective)}
    return run


def _film_sequence(script: dict, domain: dict) -> list[dict] | None:
    """Map authored film beats to the domain's fixed section kinds.

    A film-sequence row with ``dialogue: null`` is fixed to its authored duration and uses
    ``row.kind``; the documented default is ``broll``. Dialogue rows are not re-timed here:
    their matching shots[] row continues through the existing speech/WAV rule.
    """
    fixed = fixed_section_kinds(domain)
    rows = script.get('film_sequence')
    if not rows:
        return None
    if not fixed:
        if isinstance(rows, list) and any(isinstance(r, dict) and r.get('dialogue') is None for r in rows):
            raise Refused('script.film_sequence has non-dialogue beats but this run enables no fixed section kind; '
                          'refusing rather than ignoring them')
        return None
    if not isinstance(rows, list):
        raise Refused('script.film_sequence must be an array')
    declared = set(section_kinds(domain))
    shots = {shot['id'] for shot in script['shots']}
    outro = (script.get('structure') or {}).get('outro') or {}
    outro_source = outro.get('source_shot_id')
    sequence: list[dict] = []
    seen_shots: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise Refused(f'film_sequence[{index}] needs a non-empty id')
        sid = row['id']
        if row.get('dialogue') is None:
            kind = row.get('kind') or 'broll'
            if kind not in declared:
                raise Refused(f'film_sequence row {sid}: kind {kind!r} is not enabled for domain '
                              f'{domain["domain_id"]!r} in this run; enabled kinds are {list(section_kinds(domain))}')
            if kind not in fixed:
                raise Refused(f'film_sequence row {sid}: kind {kind!r} is not fixed by the domain')
            seconds = row.get('duration_s')
            if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                    or not math.isfinite(seconds) or seconds <= 0):
                raise Refused(f'film_sequence row {sid}: non-dialogue beats need a positive duration_s')
            sequence.append({'id': sid, 'kind': kind, 'duration_s': seconds})
        elif sid in shots:
            if sid in seen_shots:
                raise Refused(f'film_sequence row {sid}: duplicate dialogue row')
            seen_shots.add(sid)
            sequence.append({'id': sid, 'kind': 'dialogue', 'line_id': sid})
        elif sid != outro_source:
            raise Refused(f'film_sequence row {sid}: dialogue row has no shots[] row; speech is never stretched')
    missing = [sid for sid in shots if sid not in seen_shots]
    if missing:
        raise Refused(f'film_sequence is missing dialogue shot(s) {missing}')
    return sequence

def _budget_inputs(script: dict, domain: dict) -> dict:
    rates = domain['frame_rates']
    if script.get('vocabulary_cards') and 'vocab_card' not in section_kinds(domain):
        raise Refused(f"script has {len(script['vocabulary_cards'])} vocabulary card(s) but section kind "
                      f"'vocab_card' is not enabled for domain {domain['domain_id']!r} in this run")
    pause_s = _need(domain, 'pause_native')['min'] / rates['native_fps']
    # wav_s is an authored reservation understood by the existing allocator, NOT a measured WAV.
    # The note and extra are carried to all downstream plans; voice/H3 must replace these estimates.
    end_lines = [x for x in script.get('voice_extras', []) if x.get('kind') == 'end_line']
    if len(end_lines) > 1:
        raise Refused('one end_line reservation is supported per delivery contract')
    sequence = _film_sequence(script, domain)
    inputs = {'schema': 'jjv/contract-inputs/v1',
              'note': 'AUTHORING ESTIMATES ONLY. wav_s reserves authored time; no WAV measured or approved. Rebudget after voice/H3.',
              'intro_frames': 0 if sequence is not None else
              round(script['structure']['intro']['duration_s'] * rates['delivery_fps']),
              'lines': [{'id': s['id'], 'wav_s': max(1 / rates['native_fps'], s['duration_s'] - pause_s)}
                        for s in script['shots']],
              'vocab': [{'term': c['term'], 'wav_s': c.get('target_duration_s', c.get('proposed_outro_duration_s', 1.0))}
                        for c in script['vocabulary_cards']],
              'end_card': True,
              **({'end_line': {'wav_s': end_lines[0]['target_duration_s']}} if end_lines else {}),
              'extra': {'status': 'planned_unmeasured', 'timing_evidence': 'authored_reservations_only'}}
    if sequence is not None:
        inputs['sequence'] = sequence
    return inputs


def derive(script: dict, episode: dict, domain: dict, *, target_seconds: float | None = None,
           vocabulary_speaker: str | None = None) -> dict[str, object]:
    validate_script(script)
    if script['film_id'] != episode['film_id']:
        raise Refused('script.film_id differs from episode.film_id')
    if script.get('domain', episode['domain']) != episode['domain']:
        raise Refused('script domain differs from episode domain')
    if script['fps'] != domain['frame_rates']['delivery_fps']:
        raise Refused('script fps differs from domain delivery fps')
    for s in script['shots']:
        if s.get('layout_brief') and s['layout_brief'].get('domain') != episode['domain']:
            raise Refused(f"{s['id']}: layout_brief domain differs from episode domain")
    source_sha = canonical_sha256(script, mode='ascii')
    inputs = _budget_inputs(script, domain)
    fps = domain['frame_rates']['delivery_fps']
    hard_target = target_seconds if target_seconds is not None else (script.get('delivery') or {}).get('target_seconds')
    if hard_target is not None and (isinstance(hard_target, bool) or not math.isfinite(hard_target) or hard_target <= 0):
        raise Refused('target_seconds must be finite and positive')
    sections = allocate(domain, inputs, target_frames=round(hard_target * fps) if hard_target is not None else None,
                        min_frames=round(script['duration_s'] * fps) if hard_target is None else None)
    contract = build_contract(sections, fps=fps, revision=f'script-{source_sha[:16]}',
                              inputs_sha256=sha256_bytes(pretty_json(inputs, mode='ascii')), extra=inputs['extra'])
    derived_episode = copy.deepcopy(episode)
    derived_episode['contract'] = contract
    derived_episode['timeline'] = timeline_from_contract(contract)
    errors = check_contract(derived_episode, domain)
    if errors:
        raise Refused('; '.join(errors))
    timings = {s.id: s.frames for s in sections}
    section_starts = {}
    cursor = 0
    for section in sections:
        section_starts[section.id] = cursor
        cursor += section.frames
    rows = []
    for shot in script['shots']:
        sid = shot['id']
        rows.append({'shot': sid, 'logical_shot': sid, 'speaker': shot['speaker'],
                     'listener': shot.get('listener'), 'entry': shot.get('entry', {'kind': 'cut', 'evidence': 'script; carry not proven'}),
                     'start_frame': section_starts[sid], 'duration_frames': timings[sid],
                     'authored_duration_frames': round(shot['duration_s'] * fps),
                     'clip': None, 'wav_binding': None, 'receipt_dir': None})
    bounds = []
    by_shot = {row['shot']: row for row in rows}
    cursor = sections[0].frames
    for a, b in zip(sections, sections[1:]):
        kind = by_shot[b.id]['entry']['kind'] if a.kind == b.kind == 'dialogue' else 'graphic'
        bounds.append({'from_shot': a.id, 'to_shot': b.id, 'frame': cursor, 'kind': kind})
        cursor += b.frames
    cast = []
    for role, info in script['character_references'].items():
        voice = (script.get('voice_reference') or {}).get(role) or {}
        cast.append({'role': role, 'character_id': (episode.get('cast_roles') or {}).get(role, role),
                     'canonical_path': info.get('canonical_path'), 'canonical_sha256': info.get('canonical_sha256'),
                     'reference_status': 'declared_unverified' if info.get('canonical_sha256') else 'unbound',
                     'profile_id': voice.get('profile_id', info.get('voice_profile_id')),
                     'speech_allowed': info.get('speech_allowed', True), 'description': info.get('full_description', '')})
    # The existing voice adapter requires an explicit card speaker; preserve the legacy script's
    # declarative alice_pronounces_each_term through a unique matching cast role, never a hard-coded name.
    speaker = vocabulary_speaker or script.get('vocabulary_speaker')
    if not speaker:
        declared = [r for r in script['character_references']
                    if script['structure'].get('outro', {}).get(f'{r}_pronounces_each_term') is True]
        if len(declared) == 1:
            speaker = declared[0]
    if speaker and speaker not in script['character_references']:
        raise Refused(f'unknown vocabulary speaker {speaker!r}')
    voice_script = copy.deepcopy(script)
    for shot, row in zip(voice_script['shots'], rows):
        shot.update(start_frame=row['start_frame'], duration_frames=row['duration_frames'],
                    duration_s=row['duration_frames'] / fps)
    card_start = section_starts['LOGO_HOLD'] + timings['LOGO_HOLD']
    for i, card in enumerate(voice_script['vocabulary_cards'], start=1):
        card.update(start_frame=card_start, target_duration_s=timings[f'CARD_{i:02d}'] / fps)
        card_start += timings[f'CARD_{i:02d}']
    dialogue = dialogue_from_script(voice_script, episode_id=episode['episode_id'], vocabulary_speaker=speaker)
    speakers = {}
    for row in cast:
        voice_ref = (script.get('voice_reference') or {}).get(row['role']) or {}
        voice = {'profile_id': row['profile_id']} if row['profile_id'] else None
        transform = {k: voice_ref[k] for k in ('pitch_semitones', 'tempo', 'formants') if k in voice_ref}
        if voice and transform:
            voice['transform'] = transform
        speakers[row['role']] = {'speech_allowed': row['speech_allowed'], **({'voice': voice} if voice else {})}
    from ..config.schema import validate
    from ..voice.plan import DIALOGUE_SCHEMA, CAST_SCHEMA
    cast_voice = {'schema': 'jjv/cast/v1', 'episode_id': episode['episode_id'], 'speakers': speakers}
    problems = validate(dialogue, DIALOGUE_SCHEMA, label='derived dialogue') + validate(cast_voice, CAST_SCHEMA, label='derived voice cast')
    if problems:
        raise Refused('; '.join(problems))
    return {'script.json': script, 'shots.json': {'schema': 'jjv/shots-skeleton/v1', 'episode_id': episode['episode_id'],
                'status': 'planned_unmeasured', 'script_sha256': source_sha, 'shots': rows},
            'boundaries-input.json': {'schema': 'jjv/boundaries-input/v1', 'episode_id': episode['episode_id'],
                'status': 'requires_storyboard_and_media_check', 'boundaries': bounds},
            'vocabulary.json': {'schema': 'jjv/vocabulary/v1', 'episode_id': episode['episode_id'],
                'cards': copy.deepcopy(script['vocabulary_cards'])},
            'cast-bindings.json': {'schema': 'jjv/cast-bindings/v1', 'episode_id': episode['episode_id'], 'characters': cast},
            'dialogue.json': dialogue, 'voice-cast.json': cast_voice, 'contract-inputs.json': inputs,
            'contract-plan.json': {'schema': 'jjv/script-contract-plan/v1', 'episode_id': episode['episode_id'],
                'contract': contract, 'timeline': derived_episode['timeline'],
                'authored_frames': round(script['duration_s'] * fps), **totals(sections)},
            'DELIVERY-CONTRACT.json': render_delivery_contract(derived_episode, domain)}


def install_shots(episode_file: Path, episode: dict, skeleton: dict) -> dict:
    """Write the derived skeleton to the shot list the episode DECLARES (``episode.files.shots``), write-once.

    So stages that run before any clip exists (voice, H3 inputs) find a shot list where the episode says it is.
    Never overwrites: an identical file is a no-op, any other existing file (including a real ``jjv/shots/v1``) is Refused."""
    name = (episode.get('files') or {}).get('shots')
    if not isinstance(name, str) or not name:
        raise Refused('--install-shots needs episode.files.shots (the name of the shot list the episode declares)')
    target = Path(episode_file).parent / name
    payload = pretty_json(skeleton, mode='ascii')
    if target.exists() and (not target.is_file() or target.read_bytes() != payload):
        raise Refused(f'refusing to overwrite {target}: it is not the skeleton this script derives')
    return {'path': str(target), 'sha256': write_once(target, payload), 'schema': skeleton['schema']}


def ingest(script_path: Path, episode_file: Path, out: Path, *, skill_root: Path = SKILL_ROOT,
           target_seconds: float | None = None, vocabulary_speaker: str | None = None,
           install: bool = False, section_kinds_spec: str | None = None) -> dict:
    script, episode = read_json(script_path), read_json(episode_file)
    # Planning may write only to an explicitly chosen derived folder, never on top of the source tree.
    source_root = Path(episode_file).resolve().parent.parent
    if Path(out).resolve().is_relative_to(source_root):
        raise Refused('ingest output must be outside the source episode tree; use a derived workspace')
    real_domain = domain_for(episode, skill_root=skill_root)
    kinds = effective_section_kinds(real_domain, section_kinds_spec)
    run_domain = real_domain if section_kinds_spec is None else domain_for_run(real_domain, kinds['effective'])
    documents = derive(script, episode, run_domain,
                       target_seconds=target_seconds, vocabulary_speaker=vocabulary_speaker)
    hashes = {name: canonical_sha256(doc, mode='ascii') for name, doc in documents.items()}
    receipt = {'schema': 'jjv/script-ingest/v1', 'episode_id': episode['episode_id'],
               'canonical_mode': 'ascii',
               'script_sha256': canonical_sha256(script, mode='ascii'), 'script_file_sha256': sha256_file(script_path),
               'episode_content_sha256': canonical_sha256(episode, mode='ascii'),
               'schema_file_sha256': sha256_file(SKILL_ROOT / 'schemas/script.schema.json'),
               'domain_sha256': canonical_sha256(real_domain, mode='ascii'),
               'output_content_sha256': hashes, 'section_kinds': kinds, 'status': 'planned_unmeasured'}
    documents['ingest-receipt.json'] = receipt
    written = publish(Path(out), documents)
    installed = install_shots(episode_file, episode, documents['shots.json']) if install else None
    return {'status': 'planned_unmeasured', 'files': written, 'section_kinds': kinds, 'total_frames': documents['contract-plan.json']['total_frames'],
            'shot_ids': [s['shot'] for s in documents['shots.json']['shots']],
            'boundary_count': len(documents['boundaries-input.json']['boundaries']),
            **({'installed_shots': installed} if installed else {})}
