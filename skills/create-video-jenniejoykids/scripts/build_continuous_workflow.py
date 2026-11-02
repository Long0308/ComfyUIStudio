"""Build one dependent H3 prompt for continuous shots; never submit or render."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath

try:
    from .build_comfy_workflow import build_workflow, apply_scene_metadata
except ImportError:
    from build_comfy_workflow import build_workflow, apply_scene_metadata


FPS = 24
SHARED_IDS = {'1', '2', '3', '4'}


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be a finite number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{label} must be a finite number')
    return value


def _integer(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f'{label} must be an integer in {minimum}..{maximum}')
    return value


def _relative(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty staged relative name')
    windows = PureWindowsPath(value)
    if (Path(value).is_absolute() or windows.is_absolute() or windows.drive or windows.root
            or '..' in windows.parts or ':' in value or '%' in value
            or any(ord(character) < 32 for character in value)):
        raise ValueError(f'{label} must be relative, without traversal or dynamic formatting')
    return value.replace('\\', '/')


def _remap(graph, offset):
    names = {key: key if key in SHARED_IDS else str(int(key) + offset) for key in graph}
    result = {}
    for key, original in graph.items():
        node = copy.deepcopy(original)
        for field, value in node['inputs'].items():
            if isinstance(value, list) and len(value) == 2 and value[0] in names:
                node['inputs'][field] = [names[value[0]], value[1]]
        result[names[key]] = node
    return result, names


def _input_spec(inputs, name):
    """Resolve normal sockets and Comfy v3 autogrow socket names."""
    combined = {**inputs.get('required', {}), **inputs.get('optional', {})}
    if name in combined:
        return combined[name]
    group, separator, socket = name.partition('.')
    spec = combined.get(group)
    if not separator or not spec or spec[0] != 'COMFY_AUTOGROW_V3':
        return None
    template = spec[1]['template']
    prefix = template['prefix']
    if not socket.startswith(prefix) or not socket[len(prefix):].isdigit():
        return None
    index = int(socket[len(prefix):])
    if index >= template['max']:
        return None
    return next(iter(template['input']['required'].values()))


def validate_installed_schema(graph, object_info):
    """Check installed sockets, literal ranges/options, links and acyclic execution."""
    dependencies = {}
    for key, node in graph.items():
        kind = node['class_type']
        definition = object_info.get(kind)
        if not isinstance(definition, dict):
            raise ValueError(f'Installed object schema missing {kind}')
        schema = definition['input']
        missing = set(schema.get('required', {})) - set(node['inputs'])
        if missing:
            raise ValueError(f'{kind} missing required inputs: {sorted(missing)}')
        dependencies[key] = set()
        for name, value in node['inputs'].items():
            spec = _input_spec(schema, name)
            if spec is None:
                raise ValueError(f'Installed {kind} has no input {name}')
            expected = spec[0]
            options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                source = graph.get(value[0])
                if source is None or isinstance(value[1], bool) or not isinstance(value[1], int):
                    raise ValueError(f'Invalid source link at {key}.{name}')
                outputs = object_info[source['class_type']]['output']
                if not 0 <= value[1] < len(outputs) or outputs[value[1]] != expected:
                    raise ValueError(f'Installed output type mismatch at {key}.{name}')
                dependencies[key].add(value[0])
                continue
            # Input-file inventories in a saved schema can predate newly staged
            # assets. Check their socket shape here, not stale dropdown options.
            if (kind, name) in (('LoadImage', 'image'), ('LoadAudio', 'audio'), ('LoadVideo', 'file')):
                _relative(value, f'{key}.{name}')
                continue
            choices = expected if isinstance(expected, list) else options.get('options')
            if expected == 'COMFY_DYNAMICCOMBO_V3':
                choices = [choice['key'] for choice in choices]
            if choices is not None and value not in choices:
                raise ValueError(f'Invalid installed option at {key}.{name}')
            if expected in ('INT', 'FLOAT'):
                _number(value, f'{key}.{name}')
                if expected == 'INT' and not isinstance(value, int):
                    raise ValueError(f'{key}.{name} must be an integer')
                if value < options.get('min', -math.inf) or value > options.get('max', math.inf):
                    raise ValueError(f'Installed range violation at {key}.{name}')
            elif expected == 'STRING' and not isinstance(value, str):
                raise ValueError(f'{key}.{name} must be a string')
            elif choices is None and expected not in ('STRING', 'BOOLEAN'):
                raise ValueError(f'{key}.{name} requires an installed typed link')
    settled = set()
    while len(settled) < len(graph):
        ready = {key for key, refs in dependencies.items() if key not in settled and refs <= settled}
        if not ready:
            raise ValueError('Workflow contains a dependency cycle')
        settled.update(ready)


def build_continuous_workflow(config, items, object_info=None):
    """Return API wrapper and provenance for ordered expanded VIDEO items.

    Config contains ``segments`` (single-shot builder configs plus
    ``editorial_frames``); CLI also requires ``video_manifest``. Each item must
    occupy adjacent global time and have a matching previous exit/next entry.
    """
    if not isinstance(config, dict) or not isinstance(items, list):
        raise ValueError('Config must be an object and VIDEO manifest a list')
    carry_initial = config.get('carry_in_first_frame', False)
    if not isinstance(carry_initial, bool):
        raise ValueError('carry_in_first_frame must be a boolean')
    segments = config.get('segments')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 100:
        raise ValueError('Provide 1..100 ordered segment configurations')
    manifest = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('segment_id'), str):
            raise ValueError('Every VIDEO item requires a string segment_id')
        if item['segment_id'] in manifest:
            raise ValueError('Duplicate segment_id in VIDEO manifest')
        manifest[item['segment_id']] = item
    graph, receipts, used_ids, prefixes = {}, [], set(), set()
    previous_item, previous_last, dimensions = None, None, None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError('Each segment configuration must be an object')
        identifier = segment.get('segment_id')
        if not isinstance(identifier, str) or identifier in used_ids or identifier not in manifest:
            raise ValueError('Segment IDs must be unique and present in VIDEO manifest')
        used_ids.add(identifier)
        item = manifest[identifier]
        try:
            payload = json.loads(item['prompt'].split('\n', 1)[1])
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError('Every VIDEO item requires a serialized expanded JSON prompt') from exc
        if not isinstance(payload, dict) or any(item.get(key) != value for key, value in payload.items()):
            raise ValueError('Serialized prompt must agree with all expanded VIDEO fields')
        start = _number(item.get('start'), f'{identifier}.start')
        duration = _number(item.get('duration'), f'{identifier}.duration')
        if not 0 <= start <= (2 ** 53 - 1) / FPS or not 0 < duration <= 15:
            raise ValueError('Segments require nonnegative starts and 0..15 second durations')
        for line in item.get('dialogue', []):
            beginning = _number(line.get('start'), 'dialogue.start')
            ending = _number(line.get('end'), 'dialogue.end')
            if not 0 <= beginning < ending <= duration:
                raise ValueError('Dialogue must fit entirely inside the used editorial span')
        frames = _integer(segment.get('editorial_frames'), 'editorial_frames', 2, 360)
        if not math.isclose(frames / FPS, duration, abs_tol=1e-9, rel_tol=0):
            raise ValueError('editorial_frames must exactly cover logical duration at 24fps')
        if not math.isclose(start * FPS, round(start * FPS), abs_tol=1e-8, rel_tol=0):
            raise ValueError('Segment starts must fall on 24fps frame boundaries')
        continuity = item.get('continuity', {})
        for state in ('entry_state', 'exit_state'):
            if not isinstance(continuity.get(state), str) or not continuity[state].strip():
                raise ValueError(f'{identifier} requires a nonempty {state}')
        if previous_item is not None:
            if not math.isclose(start, previous_item['start'] + previous_item['duration'], abs_tol=1e-9, rel_tol=0):
                raise ValueError('Ordered segments must occupy contiguous global times')
            if continuity['entry_state'] != previous_item['continuity']['exit_state']:
                raise ValueError('Next entry_state must equal previous exit_state exactly')
            if segment.get('first_frame'):
                raise ValueError('Only the initial segment may supply first_frame')
        elif not segment.get('first_frame'):
            raise ValueError('The initial segment requires a staged first_frame')
        if index == 0 and carry_initial and PureWindowsPath(segment['first_frame']).suffix.lower() != '.png':
            raise ValueError('carry_in_first_frame requires a lossless accepted-boundary PNG')
        width = _integer(segment.get('width', 864), 'width', 32, 16384)
        height = _integer(segment.get('height', 480), 'height', 32, 16384)
        if dimensions is not None and dimensions != (width, height):
            raise ValueError('Continuous segments require identical native dimensions')
        dimensions = width, height
        _integer(segment.get('steps', 20), 'steps', 1, 10000)
        _integer(segment.get('seed', 43), 'seed', 0, 2 ** 64 - 1)
        prefix = _relative(segment.get('output_prefix'), 'output_prefix')
        outputs = {label: f'{prefix}/{label}' for label in ('native', 'editorial', 'boundary-start', 'boundary-end')}
        if any(value.casefold() in prefixes for value in outputs.values()):
            raise ValueError('All output prefixes must be unique, ignoring Windows case')
        prefixes.update(value.casefold() for value in outputs.values())
        for name in segment.get('reference_images', []):
            _relative(name, 'reference image')
        for name in ('reference_audio', 'guide_audio', 'first_frame'):
            if segment.get(name):
                _relative(segment[name], name)
        if item.get('engine', {}).get('audio_mode') == 'canonical_voicestudio' and not segment.get('guide_audio'):
            raise ValueError('Canonical editorial previews require an original guide_audio WAV')
        if (item.get('engine', {}).get('audio_mode') == 'canonical_voicestudio'
                and PureWindowsPath(segment['guide_audio']).suffix.lower() != '.wav'):
            raise ValueError('Canonical guide_audio must be the original staged WAV')
        wrapper, receipt = build_workflow(segment, item)
        if frames > receipt['native_frames']:
            raise ValueError('editorial_frames exceeds generated native frame count')
        local, ids = _remap(wrapper['prompt'], index * 1000)
        for shared in SHARED_IDS:
            if shared in graph and graph[shared] != local[shared]:
                raise ValueError('Shared model loaders must have identical configurations')
        zero_guide = receipt['frame_zero_guide_node']
        if zero_guide is not None:
            zero_guide = ids[zero_guide]
        if previous_last is not None:
            if zero_guide is None:
                zero_guide = str(index * 1000 + 9)
                local[zero_guide] = {'class_type': 'MiniMaxH3AddGuide', 'inputs': {
                    'positive': [ids['6'], 0], 'latent': [ids['6'], 1],
                    'frame_idx': 0, 'vae': ['3', 0], 'audio_vae': ['4', 0]}}
                if receipt['first_extra_guide_node']:
                    first_later_guide = ids[receipt['first_extra_guide_node']]
                    local[first_later_guide]['inputs']['positive'] = [zero_guide, 0]
                else:
                    local[ids['10']]['inputs']['conditioning'] = [zero_guide, 0]
            guide = local[zero_guide]
            guide['inputs']['image'] = previous_last
        incoming_image = previous_last
        if index == 0 and carry_initial:
            incoming_image = local[zero_guide]['inputs'].get('image') if zero_guide else None
            if (not isinstance(incoming_image, list) or len(incoming_image) != 2
                    or incoming_image[1] != 0 or incoming_image[0] not in local
                    or local[incoming_image[0]]['class_type'] != 'LoadImage'):
                raise ValueError('Cross-job carry requires the loaded initial first_frame image')
            receipt.update(carry_in_first_frame=True, carry_in_source={
                'image': list(incoming_image),
                'staged_asset': local[incoming_image[0]]['inputs']['image'],
                'source_requirement': 'Lossless PNG of the accepted actual predecessor last USED frame.',
                'expected_native_width': width, 'expected_native_height': height,
                'actual_dimension_check': 'pending_before_Run',
                'dimension_requirement': 'Probe actual PNG dimensions before Run: exact native width/height; no resize or crop permitted.',
                'pixel_contract': 'Initial editorial frame0 equals the loaded boundary tensor before encoding; native AV remains untouched. Lossy exports may differ.'})
        local[ids['18']]['inputs']['filename_prefix'] = outputs['native']
        # IDs50..59 are outside every core builder socket, including 9 image refs.
        extra = lambda suffix: str(index * 1000 + suffix)
        used = extra(50)
        local[used] = {'class_type': 'ImageFromBatch', 'inputs': {
            'image': [ids['15'], 0], 'batch_index': 0 if incoming_image is None else 1,
            'length': frames if incoming_image is None else frames - 1}}
        editorial_image = [used, 0]
        if incoming_image is not None:
            local[extra(52)] = {'class_type': 'ImageBatch', 'inputs': {
                'image1': incoming_image, 'image2': editorial_image}}
            editorial_image = [extra(52), 0]
        local[extra(51)] = {'class_type': 'ImageFromBatch', 'inputs': {
            'image': editorial_image, 'batch_index': frames - 1, 'length': 1}}
        local[extra(53)] = {'class_type': 'ImageFromBatch', 'inputs': {
            'image': editorial_image, 'batch_index': 0, 'length': 1}}
        for suffix, label, image in ((54, 'boundary-start', [extra(53), 0]),
                                     (55, 'boundary-end', [extra(51), 0])):
            local[extra(suffix)] = {'class_type': 'SaveImage', 'inputs': {
                'images': image, 'filename_prefix': outputs[label]}}
        canonical = receipt['selected_mode'] == 'canonical_voicestudio'
        audio = [ids['7'], 0] if canonical else [ids['16'], 0]
        local[extra(58)] = {'class_type': 'TrimAudioDuration', 'inputs': {
            'audio': audio, 'start_index': 0.0, 'duration': frames / FPS}}
        local[extra(56)] = {'class_type': 'CreateVideo', 'inputs': {
            'images': editorial_image, 'audio': [extra(58), 0], 'fps': float(FPS)}}
        local[extra(57)] = {'class_type': 'SaveVideo', 'inputs': {
            'video': [extra(56), 0], 'filename_prefix': outputs['editorial'],
            'format': 'auto', 'codec': 'auto'}}
        apply_scene_metadata(local, {field: receipt[field]
                                     for field in ('scene_label', 'script_md') if field in receipt}, {
            extra(54): 'Boundary first frame', extra(55): 'Boundary last used frame',
            extra(56): 'Editorial AV assembly', extra(57): 'Editorial AV output'})
        graph.update(local)
        receipt.update({
            'editorial_frames': frames, 'editorial_seconds': frames / FPS,
            'last_used_frame_index': frames - 1,
            'previous_editorial_last_image': previous_last,
            'editorial_image': editorial_image,
            'boundary_last_image': [extra(51), 0],
            'native_save_node': ids['18'], 'editorial_save_node': extra(57),
            'runtime_prompt_node': ids[receipt['runtime_prompt_node']],
            'frame_zero_guide_node': zero_guide,
            'image_guides': [{**anchor, 'image_node': ids[anchor['image_node']],
                              'guide_node': ids[anchor['guide_node']]}
                             for anchor in receipt['image_guides']],
            'clip_guides': [{**clip, **{field: ids[clip[field]]
                                      for field in ('video_node', 'components_node', 'frames_node', 'guide_node')}}
                            for clip in receipt['clip_guides']],
            'first_extra_guide_node': (ids[receipt['first_extra_guide_node']]
                                       if receipt['first_extra_guide_node'] else None),
            'guide_chain': ([{'kind': 'frame_zero', 'frame_idx': 0, 'guide_node': zero_guide}]
                            if zero_guide and receipt['frame_zero_guide_node'] is None else [])
                           + [{**anchor, 'guide_node': ids[anchor['guide_node']]}
                              for anchor in receipt['guide_chain']],
            'final_positive': local[ids['10']]['inputs']['conditioning'],
            'guide_anchored': True, 'output_prefixes': outputs,
            'editorial_audio_source': 'original_guide_wav' if canonical else 'native_generated_audio',
            'editorial_audio_note': 'Trimmed to logical span; listening and complete-word checks still required.',
        })
        receipts.append(receipt)
        previous_item, previous_last = item, [extra(51), 0]
    if object_info is not None:
        validate_installed_schema(graph, object_info)
        for receipt in receipts:
            receipt['installed_schema_validation'] = 'passed'
    digest = hashlib.sha256(json.dumps(graph, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'prompt': graph}, {
        **({'carry_in_first_frame': True} if carry_initial else {}),
        'schema_version': '1.0', 'builder': 'continuous_h3', 'fps': FPS,
        'segments': receipts, 'graph_sha256': digest,
        'installed_schema_validation': 'passed' if object_info is not None else 'pending',
        'staged_asset_inventory_validation': 'pending; saved dropdown inventories may predate staging',
        'submission': 'not_submitted', 'runtime_benchmark': 'pending',
        'boundary_contract': 'Last USED editorial image directly guides the next sampler at frame0 and replaces its editorial frame0 before encoding.',
        'limitations': 'Image conditioning is probabilistic. Exact pre-encode seam identity does not prove correct motion, sound, or identity; lossy encoded pixels can differ. Review doorway crossing and consecutive boundary frames.',
        'native_output_policy': 'Preserve complete unmodified native frame batches and generated audio in separate native SaveVideo outputs.',
    }


def _read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--out', type=Path, required=True,
                        help='New directory; existing directories are never reused')
    args = parser.parse_args()
    try:
        config = _read(args.config)
        def asset_path(name):
            path = Path(name)
            return path if path.is_absolute() else args.config.parent / path
        items = _read(asset_path(config['video_manifest']))
        object_path = config.get('installed_object_info')
        objects = _read(asset_path(object_path)) if object_path else None
        api, provenance = build_continuous_workflow(config, items, objects)
        provenance['video_manifest'] = str(asset_path(config['video_manifest']).resolve())
        if object_path:
            provenance['installed_object_info'] = str(asset_path(object_path).resolve())
        args.out.mkdir(parents=True, exist_ok=False)
        for name, payload in (('workflow-api.json', api), ('workflow-gui.json', api['prompt']),
                              ('workflow-provenance.json', provenance)):
            (args.out / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
