"""Offline, standard-library JSON contract and production invariant validator."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
CHARACTER_FIELDS = ('id', 'name', 'entity', 'species', 'age', 'body_proportions',
                    'surface', 'eyes', 'brows', 'nose_beak', 'mouth', 'ears',
                    'hair_head', 'clothes', 'footwear', 'accessories',
                    'marks_asymmetry', 'reference_assets')
SHORTCUT = re.compile(r'\b(same[ -]as[ -](?:previous|above)|use[ -]reference|see[ -](?:registry|above|reference)|ditto)\b|\$ref', re.I)
SHA256 = re.compile(r'^[a-f0-9]{64}$')
LEGACY_EXPRESSIONS = {'happy', 'sad', 'angry', 'surprised', 'afraid', 'neutral'}
LEGACY_POSES = {'run', 'jump', 'laugh', 'cry'}
CANONICAL_EXPRESSIONS = {
    '01-neutral', '02-happy', '03-sad', '04-angry', '05-surprised',
    '06-afraid', '07-laughing', '08-crying', '09-sleepy', '10-sleeping',
    '11-wink', '12-thinking',
}
KNOWN_REUSABLE_CHARACTERS = {'alice': 'alice', 'mother': 'mom-alice'}
REUSE_RECORD_FIELDS = (
    'source_version', 'canonical_png', 'canonical_sha256', 'canonical_approval',
    'expressions_manifest', 'expressions_manifest_sha256', 'render_policy',
)

def _resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    workspace_path = WORKSPACE_ROOT / path
    return workspace_path if workspace_path.exists() else ROOT / path

def _file_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def _is_human(character):
    return ('human' in character.get('entity', '').lower()
            or character.get('species', '').lower().startswith('homo sapiens'))

def _historical_legacy_exception(data):
    engine = data.get('image_engine', {})
    return (engine.get('provider') == 'OpenAI'
            and engine.get('execution') == 'cloud'
            and engine.get('legacy_opt_in') is True)

def _reuse_policy_errors(data, verified_ids=None):
    """Return missing or identity-swapped bindings for known reusable cast."""
    historical_exception = _historical_legacy_exception(data)
    mapping = data.get('cast_reuse', {}).get('characters', {})
    if not isinstance(mapping, dict):
        return ['cast_reuse.characters: expected object']
    project_ids = {c['id'] for c in data.get('characters', [])}
    verified_ids = set(verified_ids or ())
    errors = []
    for request_id, expected_library_id in KNOWN_REUSABLE_CHARACTERS.items():
        if request_id not in project_ids:
            continue
        actual_library_id = mapping.get(request_id)
        if actual_library_id is None:
            if not historical_exception:
                errors.append(f'cast_reuse.characters.{request_id}: '
                              'complete cast_reuse binding required for reusable character')
        elif actual_library_id != expected_library_id:
            errors.append(f'cast_reuse.characters.{request_id}: expected identity '
                          f'{expected_library_id!r}, got {actual_library_id!r}')
        elif request_id not in verified_ids:
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'reusable character binding failed hash/shape validation')
    return errors

def _reuse_bindings(data, errors):
    """Validate a cast-reuse manifest and return request-to-library bindings."""
    reuse = data.get('cast_reuse')
    if not reuse:
        return []
    if not isinstance(reuse, dict):
        errors.append('cast_reuse: expected object')
        return []
    manifest_value = reuse.get('manifest_path')
    expected_manifest_hash = reuse.get('manifest_sha256')
    if not isinstance(manifest_value, str) or not manifest_value.strip():
        errors.append('cast_reuse.manifest_path: nonempty path required')
        return []
    manifest_path = _resolve_path(manifest_value)
    if not isinstance(expected_manifest_hash, str) or not SHA256.fullmatch(expected_manifest_hash):
        errors.append('cast_reuse.manifest_sha256: invalid SHA-256')
    elif not manifest_path.is_file():
        errors.append(f'cast_reuse.manifest_path: file not found: {manifest_path}')
        return []
    elif _file_sha256(manifest_path) != expected_manifest_hash:
        errors.append('cast_reuse.manifest_sha256: hash mismatch')
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        errors.append(f'cast_reuse.manifest_path: unreadable manifest: {exc}')
        return []
    if not isinstance(manifest, dict):
        errors.append('cast_reuse.manifest_path: manifest root must be an object')
        return []
    manifest_characters = manifest.get('characters')
    if not isinstance(manifest_characters, list):
        errors.append('cast_reuse.manifest_path: characters must be an array')
        return []
    records = {r.get('character_id'): r for r in manifest_characters
               if isinstance(r, dict) and r.get('character_id')}
    mapping = reuse.get('characters')
    if not isinstance(mapping, dict):
        errors.append('cast_reuse.characters: expected object')
        return []
    bindings = []
    for request_id, library_id in mapping.items():
        if not isinstance(request_id, str) or not request_id:
            errors.append('cast_reuse.characters: invalid request character ID')
            continue
        if not isinstance(library_id, str) or not library_id:
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'library character ID must be a nonempty string')
            continue
        record = records.get(library_id)
        if not record:
            errors.append(f'cast_reuse.characters.{request_id}: '
                          f'library character {library_id!r} absent from manifest')
            continue
        missing = [key for key in REUSE_RECORD_FIELDS
                   if not isinstance(record.get(key), str) or not record[key].strip()]
        if missing:
            errors.append(f'cast_reuse.characters.{request_id}: '
                          f'malformed record; missing {", ".join(missing)}')
            continue
        if record.get('render_policy') != 'reuse_existing_no_character_regeneration':
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'manifest does not prohibit character regeneration')
        record_expressions = record.get('expressions')
        if not isinstance(record_expressions, list):
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'expressions must be an array')
            record_expressions = []
        record_expression_ids = [
            item.get('expression_id') for item in record_expressions
            if isinstance(item, dict)
        ]
        if (len(record_expression_ids) != 12
                or len(set(record_expression_ids)) != 12
                or set(record_expression_ids) != CANONICAL_EXPRESSIONS):
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'expressions must contain exactly 12 unique canonical IDs')
        record_expressions_by_id = {
            item['expression_id']: item for item in record_expressions
            if isinstance(item, dict) and isinstance(item.get('expression_id'), str)
        }
        canonical_path = _resolve_path(record['canonical_png'])
        canonical_hash = record.get('canonical_sha256', '')
        if not SHA256.fullmatch(canonical_hash):
            errors.append(f'cast_reuse.characters.{request_id}: invalid canonical SHA-256')
        elif not canonical_path.is_file():
            errors.append(f'cast_reuse.characters.{request_id}: canonical file not found')
        elif _file_sha256(canonical_path) != canonical_hash:
            errors.append(f'cast_reuse.characters.{request_id}: canonical hash mismatch')
        expressions_path = _resolve_path(record['expressions_manifest'])
        expressions_hash = record.get('expressions_manifest_sha256', '')
        expressions = []
        if not SHA256.fullmatch(expressions_hash):
            errors.append(f'cast_reuse.characters.{request_id}: invalid expression-manifest SHA-256')
        elif not expressions_path.is_file():
            errors.append(f'cast_reuse.characters.{request_id}: expression manifest not found')
        elif _file_sha256(expressions_path) != expressions_hash:
            errors.append(f'cast_reuse.characters.{request_id}: expression-manifest hash mismatch')
        else:
            try:
                expression_manifest = json.loads(
                    expressions_path.read_text(encoding='utf-8-sig'))
                icons = expression_manifest.get('icons')
                if expression_manifest.get('character_id') != library_id:
                    errors.append(f'cast_reuse.characters.{request_id}: '
                                  'expression manifest character ID mismatch')
                if not isinstance(icons, list):
                    errors.append(f'cast_reuse.characters.{request_id}: '
                                  'expression manifest icons must be an array')
                    icons = []
                expression_ids = [i.get('expression_id') for i in icons
                                  if isinstance(i, dict)]
                if (len(expression_ids) != 12
                        or len(set(expression_ids)) != 12
                        or set(expression_ids) != CANONICAL_EXPRESSIONS):
                    errors.append(f'cast_reuse.characters.{request_id}: '
                                  'expression manifest must contain exactly 12 unique canonical IDs')
                expressions = []
                manifest_icons_by_id = {}
                for icon in icons:
                    if not isinstance(icon, dict):
                        errors.append(f'cast_reuse.characters.{request_id}: '
                                      'malformed expression icon')
                        continue
                    expression_id = icon.get('expression_id', 'unknown')
                    icon_png = icon.get('png')
                    if not isinstance(icon_png, str) or not icon_png:
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: png path required')
                        continue
                    icon_path = expressions_path.parent / icon_png
                    icon_hash = icon.get('sha256', '')
                    manifest_icons_by_id[expression_id] = (icon_path, icon_hash)
                    if not SHA256.fullmatch(icon_hash):
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: '
                                      'invalid SHA-256')
                    elif not icon_path.is_file():
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: file not found')
                    elif _file_sha256(icon_path) != icon_hash:
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: hash mismatch')
                for expression_id in sorted(CANONICAL_EXPRESSIONS):
                    expression = record_expressions_by_id.get(expression_id)
                    if not expression:
                        continue
                    expression_png = expression.get('png')
                    if not isinstance(expression_png, str) or not expression_png:
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: expression png path required')
                        continue
                    expression_path = _resolve_path(expression_png)
                    expression_hash = expression.get('sha256')
                    if not isinstance(expression_hash, str) or not SHA256.fullmatch(expression_hash):
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: invalid expression SHA-256')
                    elif not expression_path.is_file():
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: expression file not found')
                    elif _file_sha256(expression_path) != expression_hash:
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: expression hash mismatch')
                    manifest_entry = manifest_icons_by_id.get(expression_id)
                    if manifest_entry:
                        manifest_path, manifest_hash = manifest_entry
                        if manifest_path.resolve() != expression_path.resolve():
                            errors.append(f'cast_reuse.characters.{request_id}.'
                                          f'{expression_id}: manifest/image path mismatch')
                        if manifest_hash != expression_hash:
                            errors.append(f'cast_reuse.characters.{request_id}.'
                                          f'{expression_id}: manifest/image hash mismatch')
                    review_status = expression.get('review_status')
                    user_approval = expression.get('user_approval')
                    if not isinstance(review_status, str) or not review_status.strip():
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: review_status required')
                    if not isinstance(user_approval, str) or not user_approval.strip():
                        errors.append(f'cast_reuse.characters.{request_id}.'
                                      f'{expression_id}: user_approval required')
                    expressions.append({
                        'expression_id': expression_id,
                        'png': expression_png,
                        'sha256': expression_hash,
                        'review_status': review_status,
                        'user_approval': user_approval,
                    })
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                errors.append(f'cast_reuse.characters.{request_id}: '
                              f'malformed expression manifest: {exc}')
                expressions = []
        bindings.append({
            'request_character_id': request_id,
            'library_character_id': library_id,
            'source_version': record.get('source_version'),
            'canonical_path': record.get('canonical_png'),
            'canonical_sha256': canonical_hash,
            'canonical_approval': record.get('canonical_approval'),
            'expressions_manifest': record.get('expressions_manifest'),
            'expressions_manifest_sha256': expressions_hash,
            'expressions': expressions,
            'render_policy': record.get('render_policy'),
        })
    return bindings


def _schema(value, spec, root, path, errors):
    if '$ref' in spec:
        spec = root['$defs'][spec['$ref'].split('/')[-1]]
    types = {'object': dict, 'array': list, 'string': str,
             'number': (int, float), 'integer': int, 'boolean': bool}
    kind = spec.get('type')
    if kind and (not isinstance(value, types[kind]) or
                 (kind in ('integer', 'number') and isinstance(value, bool))):
        errors.append(f'{path}: expected {kind}')
        return
    if 'enum' in spec and value not in spec['enum']:
        errors.append(f'{path}: must be one of {spec["enum"]}')
    if isinstance(value, str):
        if len(value.strip()) < spec.get('minLength', 0):
            errors.append(f'{path}: empty or insufficient description')
        if 'pattern' in spec and not re.search(spec['pattern'], value):
            errors.append(f'{path}: invalid format')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or value < spec.get('minimum', -math.inf):
            errors.append(f'{path}: invalid number')
        if 'exclusiveMinimum' in spec and value <= spec['exclusiveMinimum']:
            errors.append(f'{path}: must exceed {spec["exclusiveMinimum"]}')
    if isinstance(value, dict):
        if len(value) < spec.get('minProperties', 0):
            errors.append(f'{path}: too few properties')
        for key in spec.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: required')
        for key, item in value.items():
            if key in spec.get('properties', {}):
                _schema(item, spec['properties'][key], root, f'{path}.{key}', errors)
            elif 'additionalProperties' in spec:
                additional = spec['additionalProperties']
                if additional is False:
                    errors.append(f'{path}.{key}: additional property prohibited')
                elif isinstance(additional, dict):
                    _schema(item, additional, root, f'{path}.{key}', errors)
    if isinstance(value, list):
        if len(value) < spec.get('minItems', 0):
            errors.append(f'{path}: too few items')
        for i, item in enumerate(value):
            _schema(item, spec.get('items', {}), root, f'{path}[{i}]', errors)


def validate_request(data):
    """Return all contract/invariant errors without repairing or mutating input."""
    schema = json.loads((ROOT / 'schemas/project.schema.json').read_text(encoding='utf-8'))
    errors = []
    _schema(data, schema, schema, '$', errors)
    if errors:
        return errors
    registry = {}
    for c in data['characters']:
        if c['id'] in registry:
            errors.append(f"characters: duplicate ID {c['id']}")
        registry[c['id']] = c

    def character(c, path):
        if any(k in c for k in ('$ref', 'same_as', 'character_ref')):
            errors.append(f'{path}: description pointer prohibited')
        for key in CHARACTER_FIELDS:
            if key == 'reference_assets':
                continue
            value = c[key]
            if SHORTCUT.search(value) or value.strip().lower() in {
                    c['name'].lower(), c['id'].lower(), 'alice', 'unknown', 'tbd'} and key not in {'id', 'name'}:
                errors.append(f'{path}.{key}: description shortcut')
        if c['id'] not in registry:
            errors.append(f'{path}: unknown character ID')
        elif c != registry[c['id']]:
            errors.append(f'{path}: identity drift from canonical registry')

    for i, c in enumerate(data['characters']):
        character(c, f'characters[{i}]')
    total = data['delivery']['duration']
    d = data['delivery']
    a, b = map(int, d['aspect_ratio'].split(':'))
    if not math.isclose(d['width'] / d['height'], a / b, abs_tol=.002):
        errors.append('delivery: aspect ratio does not match dimensions')
    if (d['draft']['width'], d['draft']['height']) != (1280, 720):
        errors.append('delivery.draft: expected 1280x720 review export')
    if (d['final']['width'], d['final']['height']) != (1920, 1080):
        errors.append('delivery.final: expected 1920x1080 final export')
    if not 0 <= data['qa']['subtitle_safe_fraction'] <= 1:
        errors.append('qa.subtitle_safe_fraction: must be between zero and one')
    image_engine = data['image_engine']
    if image_engine['provider'] == 'ComfyUI' and image_engine['execution'] != 'local':
        errors.append('image_engine: ComfyUI must use local execution')
    if image_engine['provider'] != 'ComfyUI' and not image_engine.get('legacy_opt_in'):
        errors.append('image_engine: non-ComfyUI routing requires explicit legacy_opt_in')

    reuse_bindings = _reuse_bindings(data, errors)
    reuse_ids = {binding['request_character_id'] for binding in reuse_bindings}
    errors.extend(_reuse_policy_errors(data, reuse_ids))
    project_ids = set(registry)
    reuse_mapping = data.get('cast_reuse', {}).get('characters', {})
    for request_id in reuse_mapping if isinstance(reuse_mapping, dict) else ():
        if request_id not in project_ids:
            errors.append(f'cast_reuse.characters.{request_id}: unknown request character ID')

    sheet = data['reference_policy']['sheet_requirements']
    mode = sheet['plan_mode']
    if mode == 'legacy-6x4':
        if reuse_bindings:
            errors.append('reference_policy.sheet_requirements.plan_mode: '
                          'legacy-6x4 cannot be combined with cast_reuse')
        views = set(sheet['turnaround'])
        if len(sheet['turnaround']) != 3 or views not in (
                {'front', 'left', 'right'}, {'front', 'left', 'back'},
                {'front', 'right', 'back'}):
            errors.append('reference_policy.sheet_requirements.turnaround: '
                          'require front and two distinct standard views')
        if set(sheet['expressions']) != LEGACY_EXPRESSIONS:
            errors.append('reference_policy.sheet_requirements.expressions: '
                          'incomplete legacy sheet plan')
        if set(sheet['poses']) != LEGACY_POSES:
            errors.append('reference_policy.sheet_requirements.poses: '
                          'incomplete legacy sheet plan')
    elif mode == 'canonical-12':
        views = set(sheet['turnaround'])
        if len(sheet['turnaround']) != 3 or views not in (
                {'front', 'left', 'right'}, {'front', 'left', 'back'},
                {'front', 'right', 'back'}):
            errors.append('reference_policy.sheet_requirements.turnaround: '
                          'require front and two distinct standard views')
        if len(sheet['expressions']) != 12 or set(sheet['expressions']) != CANONICAL_EXPRESSIONS:
            errors.append('reference_policy.sheet_requirements.expressions: '
                          'new characters require the canonical 12-expression plan')
        if not sheet['poses']:
            errors.append('reference_policy.sheet_requirements.poses: '
                          'new characters require an action-pose plan')
    else:
        if not reuse_bindings:
            errors.append('reference_policy.sheet_requirements.plan_mode: '
                          'reuse-only requires a valid cast_reuse manifest')
        if sheet['turnaround'] or sheet['expressions'] or sheet['poses']:
            errors.append('reference_policy.sheet_requirements: '
                          'reuse-only plans must not schedule character-sheet assets')
        human_ids = {c['id'] for c in data['characters'] if _is_human(c)}
        for request_id in sorted(human_ids - reuse_ids):
            errors.append(f'cast_reuse.characters.{request_id}: '
                          'human character has no reuse binding')
    policy = data['timeline_policy']

    def sequence(items, end, path):
        previous = 0.0
        ids = set()
        for item in items:
            if item['id'] in ids:
                errors.append(f'{path}: duplicate segment ID {item["id"]}')
            ids.add(item['id'])
            start, duration = item['start'], item['duration']
            delta = start - previous
            if delta < -1e-6:
                errors.append(f'{path}.{item["id"]}: overlapping or out-of-order segments')
            elif delta > 1e-6 and not policy['allow_gaps']:
                errors.append(f'{path}.{item["id"]}: timeline gap')
            if start + duration > end + 1e-6:
                errors.append(f'{path}.{item["id"]}: segment exceeds timeline')
            previous = start + duration
        if not math.isclose(previous, end, abs_tol=1e-6):
            errors.append(f'{path}: duration mismatch')

    sequence(data['scenes'], total, 'scenes')

    def segment(s, path):
        cast = set()
        for i, c in enumerate(s['characters']):
            character(c, f'{path}.characters[{i}]')
            if c['id'] in cast:
                errors.append(f'{path}: duplicate cast ID')
            cast.add(c['id'])
        last = 0
        for line in s['dialogue']:
            if line['speaker'] not in cast:
                errors.append(f'{path}: unknown dialogue speaker {line["speaker"]}')
            if not 0 <= line['start'] < line['end'] <= s['duration']:
                errors.append(f'{path}: malformed dialogue timing')
            if line['start'] < last:
                errors.append(f'{path}: overlapping or out-of-order dialogue')
            last = line['end']
        tracking = s['script_tracking']
        if tracking['status'] != 'ready':
            errors.append(f'{path}: script segment must be ready before generation')
        if tracking['dialogue_ids'] != [x['id'] for x in s['dialogue']]:
            errors.append(f'{path}: script tracking dialogue mismatch')
        for cue in s['repeat_cues']:
            if not 0 <= cue['start'] < cue['end'] <= s['duration']:
                errors.append(f'{path}: invalid repeat cue')
            if any(cue['start'] < x['end'] and cue['end'] > x['start'] for x in s['dialogue']):
                errors.append(f'{path}: repeat cue overlaps speech')
        for event in s['sfx']:
            if event['at'] > s['duration']:
                errors.append(f'{path}: SFX exceeds segment duration')
        if s['transition']['duration'] > s['duration']:
            errors.append(f'{path}: transition exceeds segment duration')
        if s.get('subshots'):
            sequence(s['subshots'], s['duration'], path + '.subshots')
            expanded_lines = []
            previous_sub = None
            for sub in s['subshots']:
                segment(sub, path + '.' + sub['id'])
                continuity = sub['continuity']
                if continuity['previous_scene_id'] != s['continuity']['previous_scene_id']:
                    errors.append(f'{path}.{sub["id"]}: logical predecessor scene differs from parent')
                if 'previous_segment_id' in continuity and continuity['previous_segment_id'] != (previous_sub['id'] if previous_sub else ''):
                    errors.append(f'{path}.{sub["id"]}: previous segment linkage mismatch')
                expected_entry = (previous_sub['continuity']['exit_state'] if previous_sub
                                  else s['continuity']['entry_state'])
                if continuity['entry_state'] != expected_entry:
                    errors.append(f'{path}.{sub["id"]}: subshot entry/exit continuation mismatch')
                if not {c['id'] for c in sub['characters']}.issubset(cast):
                    errors.append(f'{path}: subshot character missing from parent scene')
                for line in sub['dialogue']:
                    expanded_lines.append({**line, 'start': round(sub['start'] + line['start'], 6),
                                           'end': round(sub['start'] + line['end'], 6)})
                previous_sub = sub
            if previous_sub['continuity']['exit_state'] != s['continuity']['exit_state']:
                errors.append(f'{path}: final subshot exit differs from parent boundary')
            if expanded_lines != s['dialogue']:
                errors.append(f'{path}: subshot dialogue disagrees with parent script')

    previous = None
    for s in data['scenes']:
        segment(s, s['id'])
        if s['continuity']['previous_scene_id'] != (previous['id'] if previous else ''):
            errors.append(f'{s["id"]}: continuity previous scene mismatch')
        if previous and s['continuity']['entry_state'] != previous['continuity']['exit_state']:
            errors.append(f'{s["id"]}: action/layout continuation mismatch')
        previous = s
    library = data['image_style_library']
    if library['repository'] != 'https://github.com/freestylefly/awesome-gpt-image-2':
        errors.append('image_style_library: noncanonical repository')
    if library['revision'] != '63e6176fa01be51c000108dacd72716d3e46784b':
        errors.append('image_style_library: revision differs from packaged research pin')
    # The inspected packaged index is authoritative; never trust user-supplied IDs.
    index = ROOT / 'references/image-style-library.json'
    try:
        raw = json.loads(index.read_text(encoding='utf-8'))
        templates = raw.get('templates', raw.get('data', {}).get('templates', []))
        known = {t['id'] for t in templates}
        if not known:
            errors.append('image_style_library: packaged template index is empty')
        elif any(t not in known for t in library['template_ids']):
            errors.append('image_style_library: unknown template ID')
        chosen = [t for t in templates if t['id'] in library['template_ids']]
        if library['category'] not in {t['category'] for t in chosen}:
            errors.append('image_style_library: category absent from selected templates')
        for key in ('styles', 'scenes'):
            allowed = {v for t in chosen for v in t[key]}
            if any(v not in allowed for v in library[key]):
                errors.append(f'image_style_library: unknown {key} selection')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f'image_style_library: packaged index unavailable or malformed: {exc}')
    return errors

def character_generation_plan(data):
    """Return reused cast and the human characters that genuinely need creation."""
    errors = []
    bindings = _reuse_bindings(data, errors)
    if errors:
        raise ValueError('\n'.join(errors))
    reused = {binding['request_character_id'] for binding in bindings}
    policy_errors = _reuse_policy_errors(data, reused)
    if policy_errors:
        raise ValueError('\n'.join(policy_errors))
    generate = [c['id'] for c in data['characters']
                if (_is_human(c) and c['id'] not in reused
                    and (c['id'] not in KNOWN_REUSABLE_CHARACTERS
                         or _historical_legacy_exception(data)))]
    return {'reuse': bindings, 'generate': generate}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    try:
        errors = validate_request(json.loads(args.input.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    print(json.dumps({'valid': not errors, 'errors': errors}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
