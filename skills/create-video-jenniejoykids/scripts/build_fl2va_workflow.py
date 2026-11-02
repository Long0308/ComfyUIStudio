"""Build one native H3 first/last continuation offline; never submit or load models."""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
from typing import Any

try:
    from .build_continuous_workflow import (
        build_continuous_workflow, validate_installed_schema, _relative,
    )
    from .build_comfy_workflow import apply_scene_metadata
except ImportError:
    from build_continuous_workflow import (
        build_continuous_workflow, validate_installed_schema, _relative,
    )
    from build_comfy_workflow import apply_scene_metadata


CHECKPOINT = 'minimax_h3_fl2va_pruned_int8_convrot.safetensors'
CHECKPOINT_SHA256 = 'e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a'
CHECKPOINT_BYTES = 20970379616


def _keyframe_bindings(segment: dict[str, Any], item: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """Only the two images actually consumed by native I2V may be referenced."""
    first = _relative(segment.get('first_frame'), 'first_frame')
    last = _relative(segment.get('last_frame'), 'last_frame')
    if any(PureWindowsPath(name).suffix.lower() != '.png' for name in (first, last)):
        raise ValueError('first_frame and last_frame require lossless staged PNGs')
    original_images = segment.get('reference_images', [])
    if not isinstance(original_images, list):
        raise ValueError('FL2VA reference_images must be an ordered list')
    images = [_relative(name, 'reference image') for name in original_images]
    if any(name not in (first, last) for name in images):
        raise ValueError('FL2VA reference_images may contain only first_frame and last_frame')
    supplied = segment.get('reference_bindings')
    if supplied is None:
        supplied = [{'path': name} for name in images]
    if (not isinstance(supplied, list) or len(supplied) != len(images)
            or any(not isinstance(binding, dict) for binding in supplied)):
        raise ValueError('FL2VA reference_bindings must match reference_images in order')
    supplied = [{**binding, 'path': _relative(binding.get('path'), 'reference binding path')}
                for binding in supplied]
    if any(binding['path'] != name for name, binding in zip(images, supplied)):
        raise ValueError('FL2VA reference_bindings must match reference_images in order')
    characters = item.get('characters')
    if (not isinstance(characters, list) or not characters
            or any(not isinstance(character, dict) or not isinstance(character.get('id'), str)
                   or not character['id'].strip() for character in characters)):
        raise ValueError('FL2VA requires an expanded character list with string IDs')
    cast = [character['id'] for character in characters]
    bindings = []
    for name, role in ((first, 'first_frame'), (last, 'last_frame')):
        old = next((binding for binding in supplied if binding['path'] == name), {})
        scope = old.get('scope', 'Actual PNG dimensions and source approval require review.')
        if not isinstance(scope, str):
            raise ValueError('FL2VA reference binding scope must be a string')
        bindings.append({
            'path': name, 'role': role,
            'character_ids': copy.deepcopy(old.get('character_ids', cast)),
            'status': old.get('status', 'unverified'),
            'scope': ('Native I2V first/last keyframe, not an extra identity reference. '
                      + scope),
        })
    return first, last, bindings


def build_fl2va_workflow(config: dict[str, Any], items: list[dict[str, Any]],
                        object_info: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt a single-segment continuous config with explicit ``last_frame``.

    Require explicit simple scheduler, canonical VoiceStudio voiceover with native
    speech disabled, and hard incoming boundary carry. Other dimensions, steps,
    seed and timing retain the reviewed core builder's limits. Inputs are immutable.
    """
    if not isinstance(config, dict) or not isinstance(items, list):
        raise ValueError('Config must be an object and VIDEO manifest a list')
    if object_info is not None and not isinstance(object_info, dict):
        raise ValueError('Installed object_info must be an object or omitted')
    segments = config.get('segments')
    if not isinstance(segments, list) or len(segments) != 1 or not isinstance(segments[0], dict):
        raise ValueError('FL2VA continuation currently requires exactly one segment')
    if config.get('carry_in_first_frame') is not True:
        raise ValueError('FL2VA continuation requires carry_in_first_frame:true')
    segment = segments[0]
    if segment.get('scheduler') != 'simple':
        raise ValueError('FL2VA requires explicit scheduler:simple for this verified profile')
    if (segment.get('dialogue_presentation') != 'voiceover'
            or segment.get('native_speech_conditioning') is not False):
        raise ValueError('FL2VA continuation requires voiceover and native_speech_conditioning:false')
    for field in ('guide_frames', 'guide_clips'):
        if not isinstance(segment.get(field, []), list) or segment.get(field):
            raise ValueError(f'FL2VA does not consume extra {field}; provide only first/last PNGs')
    selected = [item for item in items if isinstance(item, dict)
                and item.get('segment_id') == segment.get('segment_id')]
    if len(selected) != 1:
        raise ValueError('Expected exactly one selected expanded VIDEO item')
    item = selected[0]
    engine = item.get('engine')
    if not isinstance(engine, dict) or engine.get('audio_mode') != 'canonical_voicestudio':
        raise ValueError('FL2VA continuation requires canonical_voicestudio audio mode')
    first, last, bindings = _keyframe_bindings(segment, item)
    internal = copy.deepcopy(config)
    internal['segments'][0].update(first_frame=first, last_frame=last,
                                   reference_images=[first, last], reference_bindings=bindings)
    wrapper, provenance = build_continuous_workflow(internal, items)
    graph = wrapper['prompt']
    receipt = provenance['segments'][0]
    native = graph['6']['inputs']
    graph['1']['inputs']['unet_name'] = CHECKPOINT
    graph['20'] = {'class_type': 'LoadImage', 'inputs': {'image': last}}
    graph['6'] = {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {
        'clip': native['clip'], 'vae': native['vae'], 'prompt': native['prompt'],
        'width': native['width'], 'height': native['height'], 'length': native['length'],
        'first_frame': ['8', 0], 'last_frame': ['20', 0]}}
    graph['10']['inputs']['conditioning'] = ['6', 0]
    graph['13']['inputs']['scheduler'] = 'simple'
    # These intermediate Ref2VA-only nodes have no remaining consumer. The first
    # loaded image8 remains both I2V input and the exact editorial frame0 source.
    for node_id in ('9', '30', '31'):
        graph.pop(node_id, None)
    apply_scene_metadata(graph, {key: receipt[key] for key in ('scene_label', 'script_md') if key in receipt}, {
        '6': 'H3 first/last conditioning', '20': 'Last native-frame keyframe'})
    native_last = receipt['native_frames'] - 1
    editorial_last = receipt['last_used_frame_index']
    receipt.update({
        'engine_task': 'fl2va', 'scheduler': 'simple', 'steps': graph['13']['inputs']['steps'],
        'seed': graph['11']['inputs']['noise_seed'], 'frame_zero_guide_node': None,
        'image_guides': [], 'clip_guides': [], 'first_extra_guide_node': None, 'guide_chain': [],
        'final_positive': ['6', 0], 'guide_anchored': True,
        'reference_bindings': bindings,
        'keyframe_conditioning': [
            {'role': 'first_frame', 'image': ['8', 0], 'staged_asset': first, 'native_frame_index': 0},
            {'role': 'last_frame', 'image': ['20', 0], 'staged_asset': last,
             'native_frame_index': native_last}],
        'last_frame_actual_dimension_check': 'pending_before_Run',
        'last_frame_dimension_requirement': 'Probe actual PNG: exact native dimensions; native I2V cover-crops mismatched last-frame geometry.',
        'last_frame_editorial_note': (
            f'The supplied last keyframe conditions native frame{native_last}; editorial ends at actual '
            f'generated frame{editorial_last}. Never substitute the supplied last PNG for that used boundary. '
            'The saved actual boundary-end PNG is the next continuation input.'),
    })
    if object_info is not None:
        validate_installed_schema(graph, object_info)
        receipt['installed_schema_validation'] = 'passed'
    digest = hashlib.sha256(json.dumps(graph, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':')).encode('utf-8')).hexdigest()
    provenance.update({
        'builder': 'fl2va_single_continuation_h3', 'graph_sha256': digest,
        'installed_schema_validation': 'passed' if object_info is not None else 'pending',
        'model_checkpoint': {'filename': CHECKPOINT, 'expected_bytes': CHECKPOINT_BYTES,
                             'expected_sha256': CHECKPOINT_SHA256,
                             'artifact_verification': 'pending_external_size_and_SHA256_check'},
        'boundary_contract': 'Loaded accepted predecessor last USED PNG replaces editorial frame0 exactly before encoding; the actual current last USED frame is saved for the next continuation.',
        'limitations': provenance['limitations'] + ' FL2VA last-keyframe conditioning targets the native tail, not the shorter editorial endpoint. First/last image conditioning does not certify motion between them.',
    })
    return wrapper, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--out', type=Path, required=True, help='New output directory; never reuse an existing one')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        def asset(name: str) -> Path:
            path = Path(name)
            return path if path.is_absolute() else args.config.parent / path
        manifest = asset(config['video_manifest'])
        items = json.loads(manifest.read_text(encoding='utf-8-sig'))
        object_path = asset(config['installed_object_info']) if config.get('installed_object_info') else None
        objects = json.loads(object_path.read_text(encoding='utf-8-sig')) if object_path else None
        api, provenance = build_fl2va_workflow(config, items, objects)
        provenance['video_manifest'] = str(manifest.resolve())
        if object_path:
            provenance['installed_object_info'] = str(object_path.resolve())
        args.out.mkdir(parents=True, exist_ok=False)
        for name, data in (('workflow-api.json', api), ('workflow-gui.json', api['prompt']),
                           ('workflow-provenance.json', provenance)):
            (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, KeyError, TypeError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
