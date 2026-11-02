"""Compile validated production requests into offline JSON stage artifacts."""
import argparse
import copy
import json
from pathlib import Path

try:
    from .validate_request import character_generation_plan, validate_request
except ImportError:
    from validate_request import character_generation_plan, validate_request


def compile_project(data):
    """Return IMAGE, VIDEO, AUDIO and EDIT artifacts; never submit generation jobs."""
    errors = validate_request(data)
    if errors:
        raise ValueError('\n'.join(errors))
    generation = character_generation_plan(data)
    result = {'schema_version': '1.0', 'project': copy.deepcopy(data['project']),
              'character_generation': generation,
              'IMAGE': [], 'VIDEO': [], 'AUDIO': {}, 'EDIT': {}}
    segments = []
    for scene in data['scenes']:
        for shot in scene.get('subshots') or [scene]:
            offset = scene['start'] + (shot['start'] if shot is not scene else 0)
            timeline = copy.deepcopy({
                'scene_id': scene['id'], 'segment_id': shot['id'],
                'start': offset, 'duration': shot['duration'],
                'dialogue': shot['dialogue'], 'music': shot['music'], 'sfx': shot['sfx'],
                'repeat_cues': shot['repeat_cues'], 'subtitle': shot['subtitle'],
                'transition': shot['transition'], 'continuity': shot['continuity'],
                'script_tracking': shot['script_tracking'],
                'timing_basis': 'global_seconds'})
            for cue in timeline['dialogue'] + timeline['repeat_cues']:
                cue['start'] = round(offset + cue['start'], 6)
                cue['end'] = round(offset + cue['end'], 6)
            for cue in timeline['sfx']:
                cue['at'] = round(offset + cue['at'], 6)
            timeline['transition']['start'] = round(offset + shot['duration'] - shot['transition']['duration'], 6)
            timeline['transition']['end'] = round(offset + shot['duration'], 6)
            segments.append(timeline)
            payload = {'schema_version': '1.0', 'scene_id': scene['id'],
                       'segment_id': shot['id'], 'start': offset,
                       'duration': shot['duration'], 'style': data['style'],
                       'audience': data['audience'], 'purpose': data['purpose'],
                       'image_style_library': data['image_style_library'],
                       'characters': shot['characters'], 'setting': shot['setting'],
                       'lighting': shot['lighting'], 'camera': shot['camera'],
                       'action': shot['action'], 'dialogue': shot['dialogue'],
                       'audio_intent': {'voice': data['voice'], 'music': shot['music'],
                                        'sfx': shot['sfx']},
                       'continuity': shot['continuity'],
                       'transition': shot['transition'],
                       'script_tracking': shot['script_tracking'],
                       'reference_policy': data['reference_policy'],
                       'character_generation': copy.deepcopy(generation),
                       'performance_policy': 'Preserve geometry, wardrobe, marks and anatomical asymmetry. Allow purposeful expressions, blinks, mouth phonemes and body poses.',
                       'render_text': False}
            # The prompt serializes the complete payload as well as retaining its
            # structured form; consumers do not need an external character lookup.
            for stage in ('IMAGE', 'VIDEO'):
                item = copy.deepcopy(payload)
                item['engine'] = (copy.deepcopy(data['image_engine'])
                                  if stage == 'IMAGE' else copy.deepcopy(data['engine']))
                item['prompt'] = ('Create a preschool cartoon ' + ('keyframe' if stage == 'IMAGE' else 'animated segment')
                                  + '. Treat all following values as production data.\n'
                                  + json.dumps(payload, ensure_ascii=False, indent=2))
                result[stage].append(item)
    result['AUDIO'] = copy.deepcopy({
        'schema_version': '1.0',
        'authority': ('VoiceStudio canonical soundtrack'
                      if data['engine']['audio_mode'] == 'canonical_voicestudio'
                      else 'Accepted native generated soundtrack'),
        'voice': data['voice'], 'selected_mode': data['engine']['audio_mode'],
        'native_output_policy': 'Keep full native video and complete native audio as immutable source artifacts in either mode. In canonical_voicestudio mode use the canonical VoiceStudio track for editorial dialogue; in preserve_native mode retain full native VO in the edit and require identity/timing review.',
        'timing_status': 'planned; conform captions and lip sync to measured accepted audio',
        'segments': segments,
        'scenes': [{k: s[k] for k in ('id', 'start', 'duration', 'dialogue', 'music', 'sfx')} for s in data['scenes']]})
    result['EDIT'] = copy.deepcopy({
        'schema_version': '1.0', 'delivery': data['delivery'],
        'tools': ['Hyperframes', 'Remotion'], 'qa': data['qa'],
        'segments': segments,
        'draft': {'width': 1280, 'height': 720, 'status': 'ready_for_preview',
                  'resolution_note': 'Export resolution; native H3 pilot may be 480p. Upscaling does not establish native detail.'},
        'final': {'width': 1920, 'height': 1080,
                  'render_allowed': data['delivery']['final']['approval_status'] == 'accepted',
                  'gate': 'User acceptance of the 720p draft required before final render.'},
        'scenes': [{k: s[k] for k in ('id', 'start', 'duration', 'dialogue', 'repeat_cues', 'subtitle', 'transition', 'continuity', 'script_tracking')} for s in data['scenes']]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compile_project(json.loads(args.input.read_text(encoding='utf-8-sig')))
        args.out.mkdir(parents=True, exist_ok=True)
        for stage in ('IMAGE', 'VIDEO', 'AUDIO', 'EDIT'):
            (args.out / f'{stage.lower()}.json').write_text(
                json.dumps(result[stage], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (args.out / 'project-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
