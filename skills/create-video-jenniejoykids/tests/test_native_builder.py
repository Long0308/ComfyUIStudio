"""Native graph metadata tests; no Comfy runtime or GPU invocation."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_comfy_workflow import build_workflow, _visual_only_payload
from compile_prompts import compile_project


def item(name):
    data = json.loads((ROOT / 'examples' / (name + '.json')).read_text(encoding='utf-8'))
    return compile_project(data)['VIDEO'][0]


def runtime_prompt(graph, reference_node='6'):
    source = graph[reference_node]['inputs']['prompt']
    return graph[source[0]]['inputs']['value']


class NativeBuilderTests(unittest.TestCase):
    def test_scheduler_default_beta_and_explicit_simple_change_only_scheduler_input(self):
        video = item('zoo-60s')
        base = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav'}
        before = copy.deepcopy((base, video))
        default = build_workflow(base, video)
        beta = {**base, 'scheduler': 'beta'}
        simple = {**base, 'scheduler': 'simple'}
        explicit_before = copy.deepcopy((beta, simple))
        self.assertEqual(default, build_workflow(beta, video))
        self.assertEqual('beta', default[0]['prompt']['13']['inputs']['scheduler'])
        expected = copy.deepcopy(default)
        expected[0]['prompt']['13']['inputs']['scheduler'] = 'simple'
        self.assertEqual(expected, build_workflow(simple, video))
        self.assertNotIn('scheduler', default[1])
        self.assertEqual(before, (base, video))
        self.assertEqual(explicit_before, (beta, simple))

    def test_scheduler_invalid_values_raise_cleanly_without_mutating_config(self):
        video = item('zoo-60s')
        for value in (None, False, True, 0, 1.0, [], {}, '', 'SIMPLE', 'karras'):
            config = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav', 'scheduler': value}
            before = copy.deepcopy(config)
            with self.subTest(scheduler=value), self.assertRaisesRegex(ValueError, 'scheduler must be beta or simple'):
                build_workflow(config, video)
            self.assertEqual(before, config)

    def test_action_priority_precedes_full_cast_without_changing_payload_or_guide_chain(self):
        for suppressed in (False, True):
            source = item('zoo-60s')
            payload = json.loads(source['prompt'].split('\n', 1)[1])
            payload['action'] = source['action'] = (
                'Walk straight from outside through the gate into the garden; '
                'off-screen voiceover is reserved for later editorial.')
            source['prompt'] = 'Expanded scene data\n' + json.dumps(payload, ensure_ascii=False)
            before = copy.deepcopy(source)
            config = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                      'guide_audio': 'alice-original.wav', 'first_frame': 'rear.png',
                      'guide_frames': [{'image': 'rear-mid.png', 'frame_idx': 60},
                                       {'image': 'rear-end.png', 'frame_idx': 119}]}
            if suppressed:
                config.update(dialogue_presentation='voiceover', native_speech_conditioning=False)
            wrapper, receipt = build_workflow(config, source)
            graph = wrapper['prompt']
            text = runtime_prompt(graph)
            runtime = json.loads(text.split('\n', 2)[2])
            with self.subTest(suppressed=suppressed):
                self.assertTrue(text.startswith('Action priority for this segment. Action: ' + source['action']))
                self.assertLess(text.index(source['action']), text.index('"characters":'))
                self.assertLess(text.index('Camera: ' + source['camera']), text.index('"characters":'))
                self.assertLess(text.index('Setting: ' + source['setting']), text.index('"characters":'))
                self.assertEqual(source['characters'], runtime['characters'])
                self.assertEqual(source['action'], runtime['action'])
                self.assertEqual(['19', 0], graph['6']['inputs']['prompt'])
                self.assertEqual('PrimitiveStringMultiline', graph['19']['class_type'])
                self.assertEqual(['9', 0], graph['101']['inputs']['positive'])
                self.assertEqual(['101', 0], graph['103']['inputs']['positive'])
                self.assertEqual(['103', 0], graph['10']['inputs']['conditioning'])
                self.assertEqual(source['dialogue'], receipt['source_dialogue'])
                if suppressed:
                    self.assertNotIn('dialogue', runtime)
                    for line in source['dialogue']:
                        self.assertNotIn(line['text'], text)
                self.assertEqual(before, source)

    def test_action_priority_uses_derived_visual_payload(self):
        source = item('zoo-60s')
        payload = json.loads(source['prompt'].split('\n', 1)[1])
        payload['action'] = source['action'] = 'Walk ahead while off-screen voiceover is reserved for later editorial.'
        source['prompt'] = 'Expanded scene data\n' + json.dumps(payload)
        derived_action = 'The rear-view family continues forward between both gate pillars.'
        def derived(data, dialogue):
            result = _visual_only_payload(data, dialogue)
            result['action'] = derived_action
            return result
        with patch('build_comfy_workflow._visual_only_payload', side_effect=derived):
            wrapper, _ = build_workflow({
                'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                'dialogue_presentation': 'voiceover', 'native_speech_conditioning': False}, source)
        text = runtime_prompt(wrapper['prompt'])
        self.assertTrue(text.startswith('Action priority for this segment. Action: ' + derived_action))
        self.assertNotIn(source['action'], text)

    def test_nonverbal_short_learning_lines_allow_full_animal_cast_and_visual_words(self):
        project = json.loads((ROOT / 'examples/zoo-60s.json').read_text(encoding='utf-8'))
        scenes = compile_project(project)['VIDEO']
        for identifier, line, action in (
                ('S04', 'Tiger.', 'A tiger walks beside the habitat rail while the toddler points toward the tiger.'),
                ('S02', 'Little bird.', 'A little bird flutters onto a branch while the toddler follows the little bird with her gaze.')):
            source = copy.deepcopy(next(scene for scene in scenes if scene['segment_id'] == identifier))
            source['dialogue'][0]['text'] = line
            source['action'] = action + ' Off-screen voiceover is reserved for later editorial; visible mouths remain at rest.'
            payload = json.loads(source['prompt'].split('\n', 1)[1])
            payload.update(action=source['action'], dialogue=source['dialogue'])
            source['prompt'] = 'Expanded scene data\n' + json.dumps(payload)
            before = copy.deepcopy(source)
            wrapper, receipt = build_workflow({
                'reference_images': ['family-and-animal.png'], 'reference_audio': 'alice.wav',
                'guide_audio': 'alice-original.wav', 'dialogue_presentation': 'voiceover',
                'native_speech_conditioning': False}, source)
            runtime = json.loads(runtime_prompt(wrapper['prompt']).rsplit('\n', 1)[1])
            with self.subTest(line=line):
                self.assertEqual(source['characters'], runtime['characters'])
                self.assertEqual(source['setting'], runtime['setting'])
                self.assertEqual(source['action'], runtime['action'])
                self.assertNotIn('dialogue', runtime)
                self.assertEqual(line, receipt['source_dialogue'][0]['text'])
                self.assertEqual(before, source)

    def test_nonverbal_rejects_explicit_short_quoted_and_spoken_insertions(self):
        base = item('zoo-60s')
        for line, insertion in (('Tiger.', 'Hold composition on the quoted call "Tiger."'),
                                ('Tiger.', 'Hold composition; narration: Tiger.'),
                                ('Tiger.', 'Hold composition; the voiceover carries exactly Tiger.'),
                                ('Tiger.', 'Hold composition; the narration delivers exactly Tiger.'),
                                ('Little bird.', 'Hold composition; the voiceover reads Little bird.'),
                                ('Little bird.', 'Keep the camera still, then say Little bird.'),
                                ('Little bird.', 'Hold composition around “Little bird.”'),
                                ("Let's go to the zoo!", "Hold composition around 'Let's go to the zoo!'")):
            source = copy.deepcopy(base)
            source['dialogue'][0]['text'] = line
            source['action'] = 'Walk straight ahead; off-screen voiceover is reserved for later editorial.'
            source['camera'] = insertion
            payload = json.loads(source['prompt'].split('\n', 1)[1])
            payload.update(action=source['action'], camera=insertion, dialogue=source['dialogue'])
            source['prompt'] = 'Expanded scene data\n' + json.dumps(payload)
            with self.subTest(insertion=insertion), self.assertRaisesRegex(ValueError, 'embedded dialogue'):
                build_workflow({'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                                'dialogue_presentation': 'voiceover',
                                'native_speech_conditioning': False}, source)

    def test_multiframe_image_guides_chain_conditioning_and_keep_original_latent(self):
        config = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                  'guide_audio': 'original.wav', 'first_frame': 'outside.png',
                  'guide_frames': [{'image': 'gate-mid.png', 'frame_idx': 60},
                                   {'image': 'gate-end.png', 'frame_idx': 119}]}
        source = item('zoo-60s')
        before = copy.deepcopy((config, source))
        wrapper, receipt = build_workflow(config, source)
        graph = wrapper['prompt']
        self.assertEqual(['9', 0], graph['101']['inputs']['positive'])
        self.assertEqual(['101', 0], graph['103']['inputs']['positive'])
        self.assertEqual(['103', 0], graph['10']['inputs']['conditioning'])
        self.assertEqual(['6', 1], graph['14']['inputs']['latent_image'])
        for key, frame, image in (('101', 60, '100'), ('103', 119, '102')):
            self.assertEqual(frame, graph[key]['inputs']['frame_idx'])
            self.assertEqual(['6', 1], graph[key]['inputs']['latent'])
            self.assertEqual([image, 0], graph[key]['inputs']['image'])
            self.assertNotIn('audio', graph[key]['inputs'])
        self.assertEqual('9', receipt['frame_zero_guide_node'])
        self.assertEqual(['103', 0], receipt['final_positive'])
        self.assertEqual(before, (config, source))

    def test_multiframe_rejects_bad_indices_paths_and_order(self):
        base = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav'}
        source = item('zoo-60s')
        native = build_workflow(base, source)[1]['native_frames']
        variants = [None, {},
                    *[[{'image': 'x.png', 'frame_idx': value}]
                      for value in (0, -1, native, True, 60.0, '60')],
                    [{'image': 'x.png', 'frame_idx': 60}, {'image': 'y.png', 'frame_idx': 60}],
                    [{'image': 'x.png', 'frame_idx': 119}, {'image': 'y.png', 'frame_idx': 60}],
                    [{'image': '..\\escape.png', 'frame_idx': 60}],
                    [{'image': 'C:\\outside.png', 'frame_idx': 60}],
                    [{'image': '\\outside.png', 'frame_idx': 60}],
                    [{'image': 'x.png', 'frame_idx': 60, 'unexpected': True}]]
        for anchors in variants:
            with self.subTest(anchors=anchors), self.assertRaises(ValueError):
                build_workflow({**base, 'guide_frames': anchors}, source)

    def test_suppressed_native_speech_has_visual_payload_original_editorial_wav_and_provenance(self):
        source = item('zoo-60s')
        payload = json.loads(source['prompt'].split('\n', 1)[1])
        visual_action = 'Walk straight forward through the gate while off-screen voiceover accompanies the action.'
        payload['action'] = source['action'] = visual_action
        for key, value in {
                'subtitle': {'text': source['dialogue'][0]['text']},
                'repeat_cues': [{'text': source['dialogue'][1]['text']}],
                'script_tracking': {**source['script_tracking'], 'segment_summary': source['dialogue'][0]['text']},
                'purpose': source['dialogue'][1]['text']}.items():
            payload[key] = source[key] = value
        source['prompt'] = 'Scene data\n' + json.dumps(payload)
        before = copy.deepcopy(source)
        wrapper, receipt = build_workflow({
            'reference_images': ['family.png'], 'reference_audio': 'alice-identity.wav',
            'guide_audio': 'alice-original.wav', 'first_frame': 'rear.png',
            'dialogue_presentation': 'voiceover', 'native_speech_conditioning': False}, source)
        graph = wrapper['prompt']
        text = runtime_prompt(graph)
        runtime = json.loads(text.rsplit('\n', 1)[1])
        self.assertNotIn('5', graph)
        self.assertFalse(any(name.startswith('ref_audios') for name in graph['6']['inputs']))
        self.assertNotIn('<Audio', text)
        self.assertNotIn('audio', graph['9']['inputs'])
        self.assertEqual('alice-original.wav', graph['7']['inputs']['audio'])
        self.assertIn('No speech, ambience only', text)
        for line in source['dialogue']:
            self.assertNotIn(line['text'], text)
        for field in ('dialogue', 'script_tracking', 'purpose', 'subtitle', 'repeat_cues'):
            self.assertNotIn(field, runtime)
        self.assertNotIn('voice', runtime['audio_intent'])
        self.assertEqual(source['audio_intent']['music'], runtime['audio_intent']['music'])
        self.assertEqual(source['audio_intent']['sfx'], runtime['audio_intent']['sfx'])
        for field in ('characters', 'setting', 'lighting', 'camera', 'action'):
            self.assertEqual(source[field], runtime[field])
        self.assertEqual(source['dialogue'], receipt['source_dialogue'])
        self.assertEqual(source['audio_intent'], receipt['source_audio_intent'])
        self.assertEqual(before, source)

    def test_speech_suppression_requires_compatible_mode_boolean_and_visual_action(self):
        source = item('zoo-60s')
        base = {'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                'native_speech_conditioning': False}
        with self.assertRaisesRegex(ValueError, 'requires voiceover'):
            build_workflow(base, source)
        source['engine']['audio_mode'] = 'preserve_native'
        with self.assertRaisesRegex(ValueError, 'requires voiceover'):
            build_workflow({**base, 'dialogue_presentation': 'voiceover'}, source)
        with self.assertRaisesRegex(ValueError, 'must be a boolean'):
            build_workflow({**base, 'native_speech_conditioning': 'false'}, source)
        source['engine']['audio_mode'] = 'canonical_voicestudio'
        for field in ('action', 'camera'):
            changed = copy.deepcopy(source)
            payload = json.loads(changed['prompt'].split('\n', 1)[1])
            payload['action'] = changed['action'] = 'Walk ahead while off-screen voiceover accompanies the action.'
            payload[field] = changed[field] = payload[field] + ' ' + changed['dialogue'][0]['text']
            changed['prompt'] = 'Data\n' + json.dumps(payload)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'embedded dialogue'):
                build_workflow({**base, 'dialogue_presentation': 'voiceover'}, changed)

    def test_voiceover_does_not_request_visible_speaking_or_change_audio_routing(self):
        base = {'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'}
        for mode in ('on_screen', 'voiceover'):
            video = item('expanded-education')
            if mode == 'voiceover':
                payload = json.loads(video['prompt'].split('\n', 1)[1])
                payload['action'] = video['action'] = 'Walk forward while off-screen voiceover accompanies the action.'
                video['prompt'] = video['prompt'].split('\n', 1)[0] + '\n' + json.dumps(payload)
            wrapper, receipt = build_workflow({**base, 'dialogue_presentation': mode}, video)
            prompt = runtime_prompt(wrapper['prompt'])
            self.assertEqual(mode, receipt['dialogue_presentation'])
            self.assertIn('clear visible mouth phonemes' if mode == 'on_screen' else 'OFF-SCREEN VOICEOVER', prompt)
            if mode == 'voiceover':
                self.assertNotIn('clear visible mouth phonemes', prompt)
                self.assertNotIn('Allow purposeful expressions, blinks, mouth phonemes', prompt)
            self.assertEqual(['16', 0], wrapper['prompt']['17']['inputs']['audio'])

    def test_voiceover_rejects_unadapted_onscreen_actions(self):
        with self.assertRaisesRegex(ValueError, 'Voiceover needs'):
            build_workflow({'reference_images': ['alice.png'], 'reference_audio': 'alice.wav',
                            'dialogue_presentation': 'voiceover'}, item('zoo-60s'))

    def test_unknown_dialogue_presentation_rejected(self):
        with self.assertRaises(ValueError):
            build_workflow({'reference_images': ['milo.png'], 'reference_audio': 'milo.wav',
                            'dialogue_presentation': 'auto'}, item('expanded-education'))

    def test_payload_omits_fabricated_websocket_client_id(self):
        prompt, _ = build_workflow(
            {'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'},
            item('expanded-education'))
        self.assertEqual({'prompt'}, set(prompt))
        self.assertNotIn('client_id', prompt)
        self.assertEqual('SaveVideo', prompt['prompt']['18']['class_type'])

    def test_text_encoder_device_default_override_and_rejection(self):
        video = item('expanded-education')
        base = {'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'}
        for selection in (None, 'default', 'cpu'):
            config = dict(base)
            if selection is not None:
                config['text_encoder_device'] = selection
            prompt, provenance = build_workflow(config, video)
            expected = 'default' if selection is None else selection
            self.assertEqual(expected, prompt['prompt']['2']['inputs']['device'])
            self.assertEqual(expected, provenance['text_encoder_device'])
        for invalid in ('cuda', '', False, None, ['cpu']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_workflow({**base, 'text_encoder_device': invalid}, video)

    def test_non_alice_reference_and_voice_are_derived(self):
        video = item('expanded-education')
        config = {'reference_images': ['milo-keyframe.png', 'milo-wardrobe.png'],
                  'reference_audio': 'milo.wav', 'guide_audio': 'milo-guide.wav',
                  'reference_bindings': [
                      {'path': 'milo-keyframe.png', 'role': 'character_keyframe', 'character_ids': ['milo'], 'status': 'available'},
                      {'path': 'milo-wardrobe.png', 'role': 'wardrobe', 'character_ids': ['milo'], 'status': 'approved'}]}
        prompt, provenance = build_workflow(config, video)
        graph = prompt['prompt']
        text = runtime_prompt(graph)
        self.assertIn('Milo', text)
        self.assertNotIn('Alice', text)
        self.assertNotIn('approved family', text)
        self.assertIn('<Picture 1>: {"path": "milo-keyframe.png"', text)
        self.assertEqual('milo-keyframe.png', graph['30']['inputs']['image'])
        self.assertEqual(['30', 0], graph['6']['inputs']['ref_images.ref_image_0'])
        self.assertEqual(['milo'], provenance['speaker_ids'])
        self.assertEqual('available', provenance['reference_bindings'][0]['status'])

    def test_alice_family_explicit_bindings_preserve_order(self):
        config = {'reference_images': ['family.png', 'alice.png'], 'reference_audio': 'alice.wav',
                  'reference_bindings': [
                      {'path': 'family.png', 'role': 'family_lineup', 'character_ids': ['alice', 'mother', 'father'], 'status': 'approved'},
                      {'path': 'alice.png', 'role': 'face_front', 'character_ids': ['alice'], 'status': 'available'}]}
        prompt, provenance = build_workflow(config, item('zoo-60s'))
        self.assertEqual('family.png', prompt['prompt']['30']['inputs']['image'])
        self.assertEqual(['Alice'], provenance['speaker_names'])
        self.assertEqual(config['reference_bindings'], provenance['reference_bindings'])
        invalid = copy.deepcopy(config)
        invalid['reference_bindings'].reverse()
        with self.assertRaises(ValueError):
            build_workflow(invalid, item('zoo-60s'))

    def test_filename_only_staging_does_not_assert_approval(self):
        prompt, provenance = build_workflow({'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'}, item('expanded-education'))
        self.assertEqual('unverified', provenance['reference_bindings'][0]['status'])
        self.assertNotIn('approved family', runtime_prompt(prompt['prompt']))

    def test_selected_audio_mode_controls_editorial_policy_preserves_raw_av(self):
        for mode in ('canonical_voicestudio', 'preserve_native'):
            video = item('expanded-education')
            video['engine']['audio_mode'] = mode
            prompt, provenance = build_workflow({'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'}, video)
            self.assertEqual(mode, provenance['selected_mode'])
            self.assertIn('complete raw native video and audio', provenance['output_policy'])
            self.assertEqual(['16', 0], prompt['prompt']['17']['inputs']['audio'])
            self.assertIn('canonical VoiceStudio WAV' if mode == 'canonical_voicestudio' else 'Retain full native VO in the editorial mix', provenance['output_policy'])
            if mode == 'preserve_native':
                self.assertNotIn('Use the verified canonical', provenance['output_policy'])
        video['engine']['audio_mode'] = 'unsupported'
        with self.assertRaises(ValueError):
            build_workflow({'reference_images': ['milo.png'], 'reference_audio': 'milo.wav'}, video)


if __name__ == '__main__':
    unittest.main()
