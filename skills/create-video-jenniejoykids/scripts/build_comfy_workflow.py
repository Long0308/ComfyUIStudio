"""Compile one expanded VIDEO JSON item to a native H3 API prompt, without submission."""
import argparse
import copy
import json
import re
from pathlib import Path, PureWindowsPath
from typing import cast


def _staged_image(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Guide images must be nonempty staged input-relative names')
    windows = PureWindowsPath(name)
    if (Path(name).is_absolute() or windows.drive or windows.root
            or '..' in windows.parts or ':' in name or '%' in name
            or any(ord(character) < 32 for character in name)):
        raise ValueError('Guide images must be staged input-relative without traversal')
    return name


def _scene_metadata(config: dict[str, object], segment_id: str) -> dict[str, str]:
    supplied = {field: config[field] for field in ('scene_label', 'script_md') if field in config}
    for field, value in supplied.items():
        if (not isinstance(value, str) or not value.strip()
                or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)):
            raise ValueError(f'{field} must be a nonempty string without control characters')
    if supplied and 'scene_label' not in supplied:
        supplied['scene_label'] = segment_id
    return cast(dict[str, str], supplied)


def apply_scene_metadata(graph: dict[str, dict[str, object]], metadata: dict[str, str],
                         node_titles: dict[str, str]) -> None:
    """Add display-only labels; script paths are metadata, never read or run."""
    if not metadata:
        return
    for node_id, kind in node_titles.items():
        display_meta: dict[str, str] = {'title': f'{metadata["scene_label"]} — {kind}'}
        if 'script_md' in metadata:
            display_meta['description'] = f'SCENE.md: {metadata["script_md"]}'
        graph[node_id]['_meta'] = display_meta


def _visual_only_payload(payload, dialogue):
    """Project source data into nonverbal conditioning without changing sources."""
    retained = (
        'schema_version', 'scene_id', 'segment_id', 'start', 'duration', 'style',
        'image_style_library', 'characters', 'setting', 'lighting', 'camera',
        'action', 'continuity', 'transition', 'reference_policy', 'render_text',
    )
    result = {key: copy.deepcopy(payload[key]) for key in retained if key in payload}
    result['audio_intent'] = {
        key: copy.deepcopy(value) for key, value in payload.get('audio_intent', {}).items()
        if key in ('music', 'sfx')}
    result['performance_policy'] = (
        'Preserve geometry, wardrobe, marks and anatomical asymmetry. '
        'Follow the forward body direction, grounded steps and declared gaze. '
        'Keep hidden rear-view faces hidden and visible mouths relaxed at rest. '
        'No speech, ambience only, with the declared quiet environmental effects.')
    # Animal names also belong in full cast/setting descriptions. Inspect acting
    # instructions for utterances, rather than banning shared learning words.
    performance_fields = [result.get(key, '') for key in ('action', 'camera', 'performance_policy')]
    performance_fields.extend(result.get('continuity', {}).get(key, '')
                              for key in ('action_continuation',))
    performance_fields.extend(result.get('transition', {}).get(key, '')
                              for key in ('intent', 'camera_continuity'))
    for text in performance_fields:
        if isinstance(text, str) and any(_contains_spoken_dialogue(text, line['text']) for line in dialogue):
            raise ValueError('Native speech suppression requires visual-only fields without embedded dialogue text')
    return result


def _contains_spoken_dialogue(text, spoken):
    """Recognize quoted/cued utterances without rejecting visual vocabulary."""
    def words(value):
        return ' '.join(re.findall(r'\w+', value.casefold()))
    phrase = words(spoken)
    if not phrase:
        return False
    # Closing apostrophes inside contractions are followed by a letter, so they
    # do not terminate a quote such as 'Let's go to the zoo!'.
    quoted = re.findall(r'''(?<!\w)["'“‘]([^\n]+?)["'”’](?!\w)''', text)
    if any(words(value) == phrase for value in quoted):
        return True
    cue = re.compile(r'\b(?:say|says|speak|speaks|utter|utters|recite|recites|pronounce|pronounces|'
                     r'narrate|narrates|sing|sings|read|reads|spoken\s+(?:line|words?)|'
                     r'(?:voiceover|narration|narrator|voice|dialogue)\s+(?:carries|delivers|reads)|'
                     r'(?:dialogue|voiceover|narration|speech|line)\s*[:=])', re.I)
    for clause in re.split(r'[.!?;\n]+', text):
        normalized = words(clause)
        position = f' {normalized} '.find(f' {phrase} ')
        if position < 0:
            continue
        # An isolated longer utterance is also dialogue even without quotes.
        # Short labels such as "Little bird" remain valid visual descriptions.
        if len(phrase.split()) >= 4 and normalized == phrase:
            return True
        if any(f' {phrase} ' in f' {words(clause[match.end():])} '
               for match in cue.finditer(clause)):
            return True
    return False


def build_workflow(config, item):
    scene_metadata = _scene_metadata(config, item['segment_id'])
    width, height = config.get('width', 864), config.get('height', 480)
    text_encoder_device = config.get('text_encoder_device', 'default')
    if text_encoder_device not in ('default', 'cpu'):
        raise ValueError('text_encoder_device must be default or cpu')
    scheduler = config.get('scheduler', 'beta')
    if not isinstance(scheduler, str) or scheduler not in ('beta', 'simple'):
        raise ValueError('scheduler must be beta or simple')
    presentation = config.get('dialogue_presentation', 'on_screen')
    if presentation not in ('on_screen', 'voiceover'):
        raise ValueError('dialogue_presentation must be on_screen or voiceover')
    speech_conditioning = config.get('native_speech_conditioning', True)
    if not isinstance(speech_conditioning, bool):
        raise ValueError('native_speech_conditioning must be a boolean')
    mode = item.get('engine', {}).get('audio_mode')
    if not speech_conditioning and (presentation != 'voiceover' or mode != 'canonical_voicestudio'):
        raise ValueError('Disabling native speech requires voiceover and canonical_voicestudio mode')
    seconds = item['duration']
    if width <= 0 or height <= 0 or width % 32 or height % 32:
        raise ValueError('Native dimensions must be positive multiples of 32')
    if not 0 < seconds <= 15:
        raise ValueError('Commission only trained-range shots up to 15 seconds')
    if not item.get('characters') or not item.get('script_tracking', {}).get('status') == 'ready':
        raise ValueError('Expanded cast and ready script tracking required')
    prompt_payload = json.loads(item['prompt'].split('\n', 1)[1])
    if prompt_payload['characters'] != item['characters']:
        raise ValueError('Serialized prompt and expanded cast disagree')
    serialized_prompt = item['prompt']
    if presentation == 'voiceover':
        action = prompt_payload.get('action', '')
        if ('off-screen voiceover' not in action.lower() or
                re.search(r'\b(?:says|speaks)\b|\btowards?\s+(?:the\s+)?audience\b', action, re.I)):
            raise ValueError('Voiceover needs an explicit off-screen voiceover action without on-screen speaking or audience-turn instructions')
        # Override the compiler's generic permission for mouth acting in this
        # derived runtime prompt; source manifest and full cast remain intact.
        prompt_payload['performance_policy'] = (
            'Preserve geometry, wardrobe, marks and anatomical asymmetry. '
            'Use body poses and blinks following the declared action. '
            'English is off-screen voiceover; visible mouths stay at rest and hidden rear-view faces stay hidden.')
        serialized_prompt = item['prompt'].split('\n', 1)[0] + '\n' + json.dumps(prompt_payload, ensure_ascii=False)
    if not speech_conditioning:
        prompt_payload = _visual_only_payload(prompt_payload, item['dialogue'])
        serialized_prompt = ('Animate this visual-only preschool cartoon scene.\n'
                             + json.dumps(prompt_payload, ensure_ascii=False))
    images = config['reference_images']
    if not 1 <= len(images) <= 9 or not config.get('reference_audio'):
        raise ValueError('1–9 image references and voice identity audio required')
    cast = {c['id']: c for c in item['characters']}
    speakers = list(dict.fromkeys(line['speaker'] for line in item['dialogue']))
    if any(s not in cast for s in speakers):
        raise ValueError('Every dialogue speaker must be in the expanded cast')
    if mode not in ('canonical_voicestudio', 'preserve_native'):
        raise ValueError('Unsupported or missing selected audio mode')
    # Filename-only configurations remain useful for offline staging, but never
    # establish reference role or approval. Explicit bindings preserve image order.
    bindings = config.get('reference_bindings')
    if bindings is None:
        bindings = [{'path': name, 'role': 'image_reference',
                     'character_ids': list(cast), 'status': 'unverified',
                     'scope': 'Staged reference; role and identity approval require review'}
                    for name in images]
    if not isinstance(bindings, list) or len(bindings) != len(images):
        raise ValueError('Provide exactly one ordered binding per image reference')
    for name, binding in zip(images, bindings):
        if (not isinstance(binding, dict) or binding.get('path') != name or
                not isinstance(binding.get('role'), str) or not binding['role'].strip() or
                binding.get('status') not in ('available', 'planned', 'approved', 'unverified') or
                not isinstance(binding.get('character_ids'), list) or not binding['character_ids'] or
                any(c not in cast for c in binding['character_ids'])):
            raise ValueError('Invalid reference binding, image order, character IDs or approval status')
    voice = item['audio_intent']['voice']
    speaker_names = [cast[s]['name'] for s in speakers]
    binding_text = ' '.join(
        f'<Picture {i + 1}>: ' + json.dumps(binding, ensure_ascii=False)
        for i, binding in enumerate(bindings))
    for name in images + [config['reference_audio']] + [config.get('guide_audio', '')]:
        if name and (Path(name).is_absolute() or '..' in Path(name).parts or ':' in name):
            raise ValueError('Use staged Comfy input-relative asset names')
    length = max(5, round(seconds * 24))
    length += (5 - length % 17) % 17
    guides = config.get('guide_frames', [])
    if not isinstance(guides, list) or len(guides) > 450:
        raise ValueError('guide_frames must be an ordered list of at most450 image anchors')
    previous_index = 0
    for guide in guides:
        if not isinstance(guide, dict) or set(guide) != {'image', 'frame_idx'}:
            raise ValueError('Each guide_frames entry requires only image and frame_idx')
        index = guide['frame_idx']
        if (isinstance(index, bool) or not isinstance(index, int)
                or not previous_index < index < length):
            raise ValueError('Guide frame indices must be strictly increasing, nonzero and below native_frames')
        _staged_image(guide['image'])
        previous_index = index
    clips = config.get('guide_clips', [])
    if not isinstance(clips, list):
        raise ValueError('guide_clips must be an ordered list')
    if len(guides) * 2 + len(clips) * 4 > 900:
        raise ValueError('Combined image/clip guides exceed the node-ID budget below1000')
    previous_index = -1
    for clip in clips:
        if not isinstance(clip, dict) or set(clip) != {'video', 'frame_idx', 'frames'}:
            raise ValueError('Each guide_clips entry requires only video, frame_idx and frames')
        index, count = clip['frame_idx'], clip['frames']
        if (isinstance(index, bool) or not isinstance(index, int)
                or isinstance(count, bool) or not isinstance(count, int)
                or not previous_index < index or count < 5 or (count - 5) % 17
                or index + count > length):
            raise ValueError('Clip guides require increasing nonnegative starts, 17k+5 frames and a span within native_frames')
        _staged_image(clip['video'])
        previous_index = index
    graph = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'minimax_h3_ref2va_pruned_int8_convrot.safetensors', 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'type': 'minimax', 'device': text_encoder_device}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_video_vae_int8_convrot.safetensors'}},
        '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'minimax_h3_audio_vae_fp32.safetensors'}},
    }
    if speech_conditioning:
        graph['5'] = {'class_type': 'LoadAudio', 'inputs': {'audio': config['reference_audio']}}
    voice_reference_text = (
        '<Audio 1> is the supplied voice identity reference for dialogue speakers '
        + json.dumps(speaker_names, ensure_ascii=False) + ', profile '
        + json.dumps(voice['profile_id'], ensure_ascii=False) + '. '
        if speech_conditioning else 'No speech, ambience only. ')
    # Put the selected runtime acting/space instructions before long identity
    # facts. The full structured payload below remains the authority for every
    # appearance detail; this preamble does not shorten or mutate that payload.
    priority = 'Action priority for this segment. ' + ' '.join(
        f'{label}: {" ".join(prompt_payload.get(field, "").split())}'
        for label, field in (('Action', 'action'), ('Camera', 'camera'), ('Setting', 'setting')))
    prompt = (priority + ' Reference bindings (approval status is metadata, not inferred): ' + binding_text + ' '
              + voice_reference_text +
              'Animate living preschool cartoon characters, with independent joint motion, '
              'grounded steps and blinks; soft restrained colors. '
              + ('Keep visible mouths relaxed at rest and hidden rear-view faces hidden. '
                 'Follow the forward body direction and gaze with grounded alternating steps. '
                 if not speech_conditioning else
                 'Use clear visible mouth phonemes for on-screen speech. '
                 if presentation == 'on_screen' else
                 'All supplied English dialogue is OFF-SCREEN VOICEOVER, not visible character speech. '
                 'Follow the declared forward body direction and gaze; do not turn toward camera to speak, '
                 'do not show speaking mouth phonemes, and do not walk backward. ')
              +
              'Keep all exact appearance, clothing, anatomical asymmetry and location layout. '
              'No generated captions or text. '
              + ('Audio guide timing controls spoken performance.\n' if speech_conditioning else
                 'No vocalizations, singing or added narration; quiet environmental ambience only.\n')
              + serialized_prompt)
    # The H3 prompt widget has dynamicPrompts=True. Its frontend serializer
    # interprets JSON braces/pipes as choices and URL // as comments. A linked
    # literal STRING source has no dynamic widget flag and bypasses that parser.
    graph['19'] = {'class_type': 'PrimitiveStringMultiline', 'inputs': {'value': prompt}}
    ref_inputs = {'clip': ['2', 0], 'vae': ['3', 0], 'audio_vae': ['4', 0],
                  'prompt': ['19', 0], 'width': width, 'height': height, 'length': length,
                  'ref_image_size': 'match'}
    if speech_conditioning:
        ref_inputs['ref_audios.ref_audio_0'] = ['5', 0]
    for i, name in enumerate(images):
        key = str(30 + i)
        graph[key] = {'class_type': 'LoadImage', 'inputs': {'image': name}}
        ref_inputs[f'ref_images.ref_image_{i}'] = [key, 0]
    graph['6'] = {'class_type': 'MiniMaxH3ReferenceToVideo', 'inputs': ref_inputs}
    positive = ['6', 0]
    frame_zero_guide = None
    if config.get('guide_audio'):
        graph['7'] = {'class_type': 'LoadAudio', 'inputs': {'audio': config['guide_audio']}}
    if (speech_conditioning and config.get('guide_audio')) or config.get('first_frame'):
        guide = {'positive': positive, 'latent': ['6', 1], 'frame_idx': 0,
                 'vae': ['3', 0], 'audio_vae': ['4', 0]}
        if speech_conditioning and config.get('guide_audio'):
            guide['audio'] = ['7', 0]
        if config.get('first_frame'):
            name = config['first_frame']
            _staged_image(name)
            graph['8'] = {'class_type': 'LoadImage', 'inputs': {'image': name}}
            guide['image'] = ['8', 0]
        graph['9'] = {'class_type': 'MiniMaxH3AddGuide', 'inputs': guide}
        positive = ['9', 0]
        frame_zero_guide = '9'
    image_guides, clip_guides = [], []
    guide_chain = ([{'kind': 'frame_zero', 'frame_idx': 0, 'guide_node': frame_zero_guide}]
                   if frame_zero_guide else [])
    extra_guides = sorted([('image', anchor) for anchor in guides] + [('clip', clip) for clip in clips],
                          key=lambda entry: (entry[1]['frame_idx'], entry[0]))
    next_id, first_extra = 100, None
    for kind, anchor in extra_guides:
        if kind == 'image':
            image_id, guide_id = str(next_id), str(next_id + 1)
            next_id += 2
            graph[image_id] = {'class_type': 'LoadImage', 'inputs': {'image': anchor['image']}}
            image = [image_id, 0]
            image_guides.append({**anchor, 'image_node': image_id, 'guide_node': guide_id})
        else:
            video_id, components_id, frames_id, guide_id = map(str, range(next_id, next_id + 4))
            next_id += 4
            graph[video_id] = {'class_type': 'LoadVideo', 'inputs': {'file': anchor['video']}}
            graph[components_id] = {'class_type': 'GetVideoComponents', 'inputs': {'video': [video_id, 0]}}
            graph[frames_id] = {'class_type': 'ImageFromBatch', 'inputs': {
                'image': [components_id, 0], 'batch_index': 0, 'length': anchor['frames']}}
            image = [frames_id, 0]
            clip_guides.append({**anchor, 'video_node': video_id, 'components_node': components_id,
                                'frames_node': frames_id, 'guide_node': guide_id,
                                'source_preflight': {'status': 'pending', 'required_fps': 24,
                                                     'minimum_source_frames': anchor['frames'],
                                                     'note': 'Probe actual source fps/count; staged filenames do not prove them.'},
                                'audio_policy': 'Video guide audio is not connected to any conditioning or editorial output.'})
        graph[guide_id] = {'class_type': 'MiniMaxH3AddGuide', 'inputs': {
            'positive': positive, 'latent': ['6', 1], 'frame_idx': anchor['frame_idx'],
            'vae': ['3', 0], 'image': image}}
        positive = [guide_id, 0]
        if first_extra is None:
            first_extra = guide_id
        guide_chain.append({'kind': kind, 'frame_idx': anchor['frame_idx'], 'guide_node': guide_id})
    graph.update({
        '10': {'class_type': 'BasicGuider', 'inputs': {'model': ['1', 0], 'conditioning': positive}},
        '11': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': config.get('seed', 43)}},
        '12': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
        '13': {'class_type': 'BasicScheduler', 'inputs': {'model': ['1', 0], 'scheduler': scheduler, 'steps': config.get('steps', 20), 'denoise': 1.0}},
        '14': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['11', 0], 'guider': ['10', 0], 'sampler': ['12', 0], 'sigmas': ['13', 0], 'latent_image': ['6', 1]}},
        '15': {'class_type': 'VAEDecode', 'inputs': {'samples': ['14', 0], 'vae': ['3', 0]}},
        '16': {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': ['14', 0], 'vae': ['4', 0]}},
        '17': {'class_type': 'CreateVideo', 'inputs': {'images': ['15', 0], 'audio': ['16', 0], 'fps': 24.0}},
        '18': {'class_type': 'SaveVideo', 'inputs': {'video': ['17', 0], 'filename_prefix': config.get('output_prefix', 'JennieJoyKids/pilot'), 'format': 'auto', 'codec': 'auto'}},
    })
    apply_scene_metadata(graph, scene_metadata, {
        '6': 'H3 reference conditioning', '19': 'Script and literal prompt',
        '13': 'Sampling schedule', '14': 'Native sampler',
        '17': 'Native AV assembly', '18': 'Native AV output'})
    # Omit a fabricated client ID so the local UI can receive broadcast progress.
    # A websocket-specific ID must come from that live client, not this builder.
    return {'prompt': graph}, {
        **scene_metadata,
        'schema_version': '1.0', 'scene_id': item['scene_id'], 'segment_id': item['segment_id'],
        'logical_seconds': seconds, 'native_frames': length, 'native_seconds': length / 24,
        'native_width': width, 'native_height': height, 'fps': 24, 'batch': 1,
        'text_encoder_device': text_encoder_device,
        'dialogue_presentation': presentation,
        'native_speech_conditioning': speech_conditioning,
        'native_audio_guide_applied': bool(speech_conditioning and config.get('guide_audio')),
        'source_dialogue': copy.deepcopy(item['dialogue']),
        'source_audio_intent': copy.deepcopy(item['audio_intent']),
        'frame_zero_guide_node': frame_zero_guide, 'image_guides': image_guides,
        'clip_guides': clip_guides, 'first_extra_guide_node': first_extra, 'guide_chain': guide_chain,
        'runtime_prompt_node': '19', 'runtime_prompt_transport': 'literal_string_link',
        'final_positive': positive,
        'canonical_audio_guide': config.get('guide_audio'), 'guide_anchored': positive != ['6', 0],
        'reference_bindings': bindings, 'speaker_ids': speakers, 'speaker_names': speaker_names,
        'voice_profile_id': voice['profile_id'], 'selected_mode': mode,
        'output_policy': ('Preserve complete raw native video and audio as immutable source artifacts. '
                          + ('Use the verified canonical VoiceStudio WAV for editorial dialogue, avoiding duplicate speech.'
                             if mode == 'canonical_voicestudio' else
                             'Retain full native VO in the editorial mix; review voice identity and timing before acceptance.')),
        'installed_schema_validation': 'pending', 'runtime_benchmark': 'pending',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    items = json.loads(Path(config['video_manifest']).read_text(encoding='utf-8-sig'))
    selected = [x for x in items if x['segment_id'] == config['segment_id']]
    if len(selected) != 1:
        raise ValueError('Expected exactly one expanded video segment')
    prompt, provenance = build_workflow(config, selected[0])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'workflow-api.json').write_text(json.dumps(prompt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.out / 'workflow-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
