"""Validate a standalone motion sidecar; never submit jobs or infer acceptance."""
import argparse
import json
import math
import re
import sys
from pathlib import Path

from validate_request import CHARACTER_FIELDS, SHORTCUT

ROOT = Path(__file__).resolve().parents[1]


def _schema(value, spec, root, path, errors):
    if '$ref' in spec:
        spec = root['$defs'][spec['$ref'].rsplit('/', 1)[-1]]
    kinds = {'object': dict, 'array': list, 'string': str, 'number': (int, float), 'integer': int, 'boolean': bool}
    kind = spec.get('type')
    if kind and (not isinstance(value, kinds[kind]) or kind in ('number', 'integer') and isinstance(value, bool)):
        errors.append(f'{path}: expected {kind}')
        return
    if 'enum' in spec and value not in spec['enum']:
        errors.append(f'{path}: invalid choice')
    if isinstance(value, str):
        if len(value.strip()) < spec.get('minLength', 0):
            errors.append(f'{path}: insufficient description')
        if 'pattern' in spec and not re.search(spec['pattern'], value):
            errors.append(f'{path}: invalid format')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if (abs(value) > sys.float_info.max if isinstance(value, int) else not math.isfinite(value)) or value < spec.get('minimum', -math.inf) or value > spec.get('maximum', math.inf):
            errors.append(f'{path}: invalid number')
        if value <= spec.get('exclusiveMinimum', -math.inf):
            errors.append(f'{path}: must be positive')
    if isinstance(value, dict):
        for key in spec.get('required', []):
            if key not in value:
                errors.append(f'{path}.{key}: required')
        for key, item in value.items():
            if key in spec.get('properties', {}):
                _schema(item, spec['properties'][key], root, f'{path}.{key}', errors)
            elif spec.get('additionalProperties') is False:
                errors.append(f'{path}.{key}: unknown field')
    if isinstance(value, list):
        if len(value) < spec.get('minItems', 0):
            errors.append(f'{path}: too few items')
        for index, item in enumerate(value):
            _schema(item, spec.get('items', {}), root, f'{path}[{index}]', errors)


def _validate_motion_plan(data):
    """Return errors without mutating input. Frame rounding matches JS Math.round."""
    schema = json.loads((ROOT / 'schemas/motion-plan.schema.json').read_text(encoding='utf-8'))
    errors = []
    _schema(data, schema, schema, '$', errors)
    if errors:
        return errors

    def unique(items, path):
        ids = [item['id'] for item in items]
        if len(ids) != len(set(ids)):
            errors.append(f'{path}: duplicate ID')

    unique(data['sources'], 'sources')
    unique(data['shots'], 'shots')
    sources = {source['id']: source for source in data['sources']}
    fps = data['delivery']['fps']
    for source in sources.values():
        pts = source.get('frame_pts_seconds')
        if source.get('variable_frame_rate') and pts is None:
            errors.append(f"sources.{source['id']}: VFR requires recorded PTS")
        if pts and 'start_pts_seconds' in source and abs(pts[0] - source['start_pts_seconds']) > .001:
            errors.append(f"sources.{source['id']}: start_pts_seconds differs from recorded PTS")
        if pts is not None and (len(pts) != source['frame_count'] or any(a >= b for a, b in zip(pts, pts[1:])) or pts[-1:] and pts[-1] > source.get('start_pts_seconds', pts[0]) + source['duration_seconds'] + .001):
            errors.append(f"sources.{source['id']}: invalid recorded PTS")
    if errors:
        return errors
    for need in data.get('needed_frames', []):
        reference = sources.get(need['source_id'])
        if reference is None or need['end_frame'] < need['start_frame'] or need['end_frame'] >= reference['frame_count']:
            errors.append('needed_frames: invalid source or frame range')
    canonical = {}
    previous_end = 0
    for shot in data['shots']:
        path = 'shots.' + shot['id']
        if shot['start_seconds'] < previous_end - 1e-6:
            errors.append(f'{path}: overlapping or out-of-order shot')
        previous_end = shot['start_seconds'] + shot['duration_seconds']
        source = sources.get(shot.get('reference_source_id'))
        if 'reference_source_id' in shot and source is None:
            errors.append(f'{path}: unknown reference_source_id')
        unique(shot['characters'], path + '.characters')
        for character in shot['characters']:
            for key in CHARACTER_FIELDS:
                if key == 'reference_assets':
                    continue
                value = character[key]
                if SHORTCUT.search(value) or key not in ('id', 'name') and value.strip().lower() in (character['id'].lower(), character['name'].lower(), 'alice', 'unknown', 'tbd'):
                    errors.append(f'{path}.characters.{key}: description shortcut')
            if any(key in character for key in ('$ref', 'same_as', 'character_ref')):
                errors.append(f'{path}.characters: description pointer prohibited')
            if character['id'] in canonical and character != canonical[character['id']]:
                errors.append(f'{path}.characters: identity drift')
            canonical[character['id']] = character
        unique(shot['events'], path + '.events')
        event_ids = {event['id'] for event in shot['events']}
        for event in shot['events']:
            ep = path + '.events.' + event['id']
            if not 0 <= event['start_seconds'] < event['end_seconds'] <= shot['duration_seconds']:
                errors.append(f'{ep}: event timing outside shot')
            for space in ('local', 'global'):
                for edge in ('start', 'end'):
                    key = f'expected_{space}_{edge}_frame'
                    seconds = event[f'{edge}_seconds'] + (shot['start_seconds'] if space == 'global' else 0)
                    if key in event and event[key] != math.floor(seconds * fps + .5):
                        errors.append(f'{ep}.{key}: frame mismatch at delivery fps {fps}')
            motion = event.get('motion')
            if motion:
                if motion['evidence'] == 'measured' and source is None:
                    errors.append(f'{ep}: measured motion requires reference source')
                if motion['coordinate_space'] == 'source_pixels' and source is None:
                    errors.append(f'{ep}: source_pixels requires reference source')
                bounds = source if motion['coordinate_space'] == 'source_pixels' else data['delivery']
                if bounds:
                    for key in ('start_box', 'end_box'):
                        box = motion[key]
                        if box['x'] + box['width'] > bounds['width'] or box['y'] + box['height'] > bounds['height']:
                            errors.append(f'{ep}.{key}: box exceeds coordinate space')
                curve = motion['curve']; params = curve['parameters']
                expected = {'linear': set(), 'cubic_ease_out': {'x1', 'y1', 'x2', 'y2'}, 'spring': {'stiffness', 'damping', 'mass'}}[curve['type']]
                if set(params) != expected or any(isinstance(v, bool) or not isinstance(v, (int, float)) or (abs(v) > sys.float_info.max if isinstance(v, int) else not math.isfinite(v)) for v in params.values()):
                    errors.append(f'{ep}.curve: explicit numeric parameters required: {sorted(expected)}')
                elif curve['type'] == 'spring' and any(v <= 0 for v in params.values()):
                    errors.append(f'{ep}.curve: spring parameters must be positive')
                elif curve['type'] == 'cubic_ease_out' and any(not 0 <= params[k] <= 1 for k in ('x1', 'x2')):
                    errors.append(f'{ep}.curve: cubic x control points outside 0..1')
                overshoot = motion['visible_overshoot']
                if overshoot['evidence'] == 'measured' and source is None:
                    errors.append(f'{ep}: measured overshoot requires reference source')
        for item in shot.get('source_events', []):
            if source is None:
                errors.append(f'{path}.source_events: reference source required')
                continue
            timestamp = item['timestamp_seconds']
            source_start = source.get('start_pts_seconds', source.get('frame_pts_seconds', [0])[0])
            if not source_start <= timestamp <= source_start + source['duration_seconds']:
                errors.append(f'{path}.source_events: timestamp outside source')
            index = item.get('frame_index')
            if index is not None:
                if index >= source['frame_count']:
                    errors.append(f'{path}.source_events: frame index outside source')
                elif 'frame_pts_seconds' in source:
                    if abs(timestamp - source['frame_pts_seconds'][index]) > .001:
                        errors.append(f'{path}.source_events: timestamp differs from recorded PTS')
                elif not source.get('variable_frame_rate') and abs(timestamp - source_start - index * source['fps_den'] / source['fps_num']) > source['fps_den'] / source['fps_num'] / 2 + 1e-6:
                    errors.append(f'{path}.source_events: timestamp differs from source FPS')
        layout = shot['layout']; delivery = data['delivery']
        margin = layout['safe_margin']
        if 2 * margin >= min(delivery['width'], delivery['height']):
            errors.append(f'{path}.layout: safe margin consumes canvas')
        for key in ('headline_box', 'logo_reserved_box'):
            box = layout[key]
            if box['x'] < margin or box['y'] < margin or box['x'] + box['width'] > delivery['width'] - margin or box['y'] + box['height'] > delivery['height'] - margin:
                errors.append(f'{path}.layout.{key}: outside safe margin')
        check = layout['longest_copy_check']
        if check['line_count'] > layout['max_headline_lines'] or not check['fits']:
            errors.append(f'{path}.layout: longest copy fails layout')
        review = shot['review']
        if not 0 <= review['legible_start_seconds'] <= review['legible_end_seconds'] <= shot['duration_seconds'] or review['legible_end_seconds'] - review['legible_start_seconds'] < review['minimum_reading_hold_seconds']:
            errors.append(f'{path}.review: reading hold outside shot or below configured minimum')
        if review['status'] == 'reviewed' and (layout['font_status'] != 'verified' or check['status'] != 'measured'):
            errors.append(f'{path}.review: reviewed layout requires verified font and measured longest copy')
        for cue in shot.get('audio_cues', []):
            if cue['event_id'] not in event_ids:
                errors.append(f'{path}.audio_cues: unknown event_id')
            else:
                event = next(item for item in shot['events'] if item['id'] == cue['event_id'])
                if not event['start_seconds'] <= cue['timeline_hit_seconds'] <= event['end_seconds']:
                    errors.append(f'{path}.audio_cues: hit outside linked event')
            if cue['source_transient_seconds'] > cue['source_duration_seconds'] or cue['timeline_hit_seconds'] > shot['duration_seconds']:
                errors.append(f'{path}.audio_cues: timestamp outside source or shot')
            if not math.isclose(cue['offset_seconds'] + cue['source_transient_seconds'], cue['timeline_hit_seconds'], abs_tol=1e-6):
                errors.append(f'{path}.audio_cues: transient alignment mismatch')
    return errors


def validate_motion_plan(data):
    """Return contract errors, including numeric overflow, without mutating input."""
    try:
        return _validate_motion_plan(data)
    except OverflowError:
        return ['numeric values exceed supported arithmetic range']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    try:
        errors = validate_motion_plan(json.loads(args.plan.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as exc:
        parser.exit(2, f'{exc}\n')
    for error in errors:
        print(error)
    if not errors:
        print('Motion sidecar valid; visual/audio review remains separate.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
