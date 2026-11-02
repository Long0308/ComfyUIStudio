"""Dependent-shot graph contract tests; no server or GPU actions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_continuous_workflow import build_continuous_workflow, validate_installed_schema
from compile_prompts import compile_project


def serialize(item):
    payload = json.loads(item['prompt'].split('\n', 1)[1])
    for field in payload:
        payload[field] = item[field]
    item['prompt'] = 'Expanded scene data\n' + json.dumps(payload)


def fixture(count=2):
    project = json.loads((ROOT / 'examples/zoo-60s.json').read_text(encoding='utf-8'))
    original = compile_project(project)['VIDEO'][0]
    items, segments = [], []
    for index in range(count):
        item = copy.deepcopy(original)
        item.update(segment_id=f'test_{index}', start=index * 5, duration=5)
        item['dialogue'] = item['dialogue'][:1]
        item['continuity'].update(entry_state=f'state-{index}', exit_state=f'state-{index + 1}')
        payload = json.loads(item['prompt'].split('\n', 1)[1])
        for field in ('segment_id', 'start', 'duration', 'continuity', 'dialogue'):
            payload[field] = item[field]
        item['prompt'] = 'Expanded scene data\n' + json.dumps(payload)
        items.append(item)
        segments.append({'segment_id': item['segment_id'], 'editorial_frames': 120,
                         'reference_images': ['family.png'], 'reference_audio': 'alice.wav',
                         'guide_audio': f'guide-{index}.wav', 'output_prefix': f'Film/S{index}',
                         'width': 864, 'height': 480, 'steps': 20, 'seed': 4300 + index})
    segments[0]['first_frame'] = 'outside.png'
    return {'segments': segments}, items


class ContinuousBuilderTests(unittest.TestCase):
    def test_segment_scheduler_delegation_default_compatibility_and_validation(self):
        config, items = fixture()
        before = copy.deepcopy((config, items))
        default = build_continuous_workflow(config, items)
        beta = copy.deepcopy(config)
        for segment in beta['segments']:
            segment['scheduler'] = 'beta'
        self.assertEqual(default, build_continuous_workflow(beta, items))
        simple = copy.deepcopy(config)
        simple['segments'][1]['scheduler'] = 'simple'
        simple_before = copy.deepcopy(simple)
        wrapper, receipt = build_continuous_workflow(simple, items)
        expected_graph = copy.deepcopy(default[0])
        expected_graph['prompt']['1013']['inputs']['scheduler'] = 'simple'
        self.assertEqual(expected_graph, wrapper)
        self.assertEqual('beta', wrapper['prompt']['13']['inputs']['scheduler'])
        self.assertEqual(default[1]['segments'], receipt['segments'])
        self.assertEqual(set(default[1]), set(receipt))
        self.assertNotEqual(default[1]['graph_sha256'], receipt['graph_sha256'])
        self.assertEqual(simple_before, simple)
        self.assertEqual(before, (config, items))
        for value in (None, False, [], {}, 'karras'):
            invalid = copy.deepcopy(config)
            invalid['segments'][1]['scheduler'] = value
            invalid_before = copy.deepcopy(invalid)
            with self.subTest(scheduler=value), self.assertRaisesRegex(ValueError, 'scheduler must be beta or simple'):
                build_continuous_workflow(invalid, items)
            self.assertEqual(invalid_before, invalid)

    def test_later_guides_do_not_bypass_incoming_frame_zero_conditioning(self):
        for speech in (True, False):
            config, items = fixture()
            for segment, item in zip(config['segments'], items):
                segment['guide_frames'] = [{'image': f'{item["segment_id"]}-mid.png', 'frame_idx': 60},
                                           {'image': f'{item["segment_id"]}-end.png', 'frame_idx': 119}]
                if not speech:
                    segment.update(dialogue_presentation='voiceover', native_speech_conditioning=False)
                    item['action'] = 'Walk straight ahead while off-screen voiceover accompanies the action.'
                    serialize(item)
            before = copy.deepcopy((config, items))
            wrapper, receipt = build_continuous_workflow(config, items)
            graph = wrapper['prompt']
            with self.subTest(speech=speech):
                self.assertEqual(['51', 0], graph['1009']['inputs']['image'])
                self.assertEqual(0, graph['1009']['inputs']['frame_idx'])
                self.assertEqual(['1009', 0], graph['1101']['inputs']['positive'])
                self.assertEqual(['1101', 0], graph['1103']['inputs']['positive'])
                self.assertEqual(['1103', 0], graph['1010']['inputs']['conditioning'])
                for node in ('1009', '1101', '1103'):
                    self.assertEqual(['1006', 1], graph[node]['inputs']['latent'])
                self.assertEqual(['7', 0], graph['58']['inputs']['audio'])
                self.assertEqual(['1007', 0], graph['1058']['inputs']['audio'])
                self.assertEqual(['1016', 0], graph['1017']['inputs']['audio'])
                self.assertEqual(['51', 0], graph['1052']['inputs']['image1'])
                self.assertEqual('1009', receipt['segments'][1]['frame_zero_guide_node'])
                self.assertEqual('1101', receipt['segments'][1]['image_guides'][0]['guide_node'])
                self.assertEqual(['1103', 0], receipt['segments'][1]['final_positive'])
                if not speech:
                    self.assertNotIn('audio', graph['1009']['inputs'])
                    self.assertFalse(any(name.startswith('ref_audios') for name in graph['1006']['inputs']))
                self.assertEqual(before, (config, items))

    def test_existing_multiframe_base_zero_guide_keeps_audio(self):
        config, items = fixture()
        for segment in config['segments']:
            segment['guide_frames'] = [{'image': 'middle.png', 'frame_idx': 60}]
        graph = build_continuous_workflow(config, items)[0]['prompt']
        self.assertEqual(['1007', 0], graph['1009']['inputs']['audio'])
        self.assertEqual(['51', 0], graph['1009']['inputs']['image'])
        self.assertEqual(['1009', 0], graph['1101']['inputs']['positive'])
        self.assertEqual(['1101', 0], graph['1010']['inputs']['conditioning'])

    def test_one_graph_serial_guides_exact_editorial_seam_and_native_av(self):
        config, items = fixture(3)
        original = copy.deepcopy((config, items))
        wrapper, provenance = build_continuous_workflow(config, items)
        graph = wrapper['prompt']
        self.assertEqual({'prompt'}, set(wrapper))
        self.assertEqual(original, (config, items))
        self.assertEqual(4, sum(n['class_type'] in ('UNETLoader', 'CLIPLoader', 'VAELoader') for n in graph.values()))
        for index in range(3):
            offset = index * 1000
            key = lambda suffix: str(offset + suffix)
            self.assertEqual(124, graph[key(6)]['inputs']['length'])
            self.assertEqual([key(15), 0], graph[key(17)]['inputs']['images'])
            self.assertEqual([key(16), 0], graph[key(17)]['inputs']['audio'])
            self.assertEqual([key(17), 0], graph[key(18)]['inputs']['video'])
            self.assertEqual('Film/S' + str(index) + '/native', graph[key(18)]['inputs']['filename_prefix'])
            self.assertEqual([key(7), 0], graph[key(58)]['inputs']['audio'])
            self.assertEqual(5.0, graph[key(58)]['inputs']['duration'])
            self.assertEqual(119, graph[key(51)]['inputs']['batch_index'])
            if index:
                previous = [str(offset - 1000 + 51), 0]
                self.assertEqual(previous, graph[key(9)]['inputs']['image'])
                self.assertEqual(0, graph[key(9)]['inputs']['frame_idx'])
                self.assertEqual(previous, graph[key(52)]['inputs']['image1'])
                self.assertEqual([key(50), 0], graph[key(52)]['inputs']['image2'])
                self.assertEqual(1, graph[key(50)]['inputs']['batch_index'])
                self.assertEqual(119, graph[key(50)]['inputs']['length'])
                self.assertEqual([key(52), 0], graph[key(56)]['inputs']['images'])
        self.assertEqual('not_submitted', provenance['submission'])
        self.assertEqual(64, len(provenance['graph_sha256']))
        self.assertIn('probabilistic', provenance['limitations'])
        self.assertEqual('pending', provenance['installed_schema_validation'])

    def test_native_mode_editorial_retains_native_audio_and_builds_image_guide(self):
        config, items = fixture()
        for item, segment in zip(items, config['segments']):
            item['engine']['audio_mode'] = 'preserve_native'
            segment.pop('guide_audio')
        graph = build_continuous_workflow(config, items)[0]['prompt']
        self.assertEqual(['16', 0], graph['58']['inputs']['audio'])
        self.assertEqual(['1016', 0], graph['1058']['inputs']['audio'])
        self.assertEqual(['51', 0], graph['1009']['inputs']['image'])
        self.assertEqual(['1009', 0], graph['1010']['inputs']['conditioning'])
        self.assertEqual(['1006', 1], graph['1014']['inputs']['latent_image'])

    def test_rejects_timeline_or_state_discontinuity(self):
        for field, value in (('start', 5.1), ('start', 4), ('duration', 4), ('start', True), ('duration', float('nan'))):
            config, items = fixture()
            items[1][field] = value
            serialize(items[1])
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_continuous_workflow(config, items)
        config, items = fixture()
        items[1]['continuity']['entry_state'] = 'different pose'
        serialize(items[1])
        with self.assertRaisesRegex(ValueError, 'entry_state'):
            build_continuous_workflow(config, items)

    def test_rejects_stale_serialized_action(self):
        config, items = fixture()
        items[1]['action'] = 'A changed direction absent from serialized prompt'
        with self.assertRaisesRegex(ValueError, 'Serialized prompt'):
            build_continuous_workflow(config, items)

    def test_rejects_word_cutoff_or_nonwav_canonical_track(self):
        config, items = fixture()
        items[0]['dialogue'][0]['end'] = 5.1
        serialize(items[0])
        with self.assertRaisesRegex(ValueError, 'Dialogue'):
            build_continuous_workflow(config, items)
        config, items = fixture()
        config['segments'][0]['guide_audio'] = 'compressed.mp3'
        with self.assertRaisesRegex(ValueError, 'original staged WAV'):
            build_continuous_workflow(config, items)

    def test_rejects_invalid_frames_dimensions_and_shared_model_changes(self):
        for field, value in (('editorial_frames', 124), ('editorial_frames', 0),
                             ('editorial_frames', True), ('editorial_frames', 120.0),
                             ('width', 832), ('width', True), ('height', 479),
                             ('steps', 0), ('seed', -1), ('text_encoder_device', 'cpu')):
            config, items = fixture()
            config['segments'][1][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_continuous_workflow(config, items)

    def test_rejects_duplicate_or_unresolved_ids_and_prefixes(self):
        for location in ('config-id', 'manifest-id', 'missing-id', 'prefix'):
            config, items = fixture()
            if location == 'config-id':
                config['segments'][1]['segment_id'] = config['segments'][0]['segment_id']
            elif location == 'manifest-id':
                items.append(copy.deepcopy(items[0]))
            elif location == 'missing-id':
                config['segments'][1]['segment_id'] = 'missing'
            else:
                config['segments'][1]['output_prefix'] = config['segments'][0]['output_prefix'].lower()
            with self.subTest(location=location), self.assertRaises(ValueError):
                build_continuous_workflow(config, items)

    def test_rejects_missing_or_conflicting_image_or_audio_guides(self):
        for change in ('missing-initial', 'extra-first-frame', 'missing-canonical-wav'):
            config, items = fixture()
            if change == 'missing-initial':
                config['segments'][0].pop('first_frame')
            elif change == 'extra-first-frame':
                config['segments'][1]['first_frame'] = 'stale.png'
            else:
                config['segments'][1].pop('guide_audio')
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_continuous_workflow(config, items)

    def test_rejects_unsafe_paths_and_dynamic_prefixes(self):
        for field, value in (('output_prefix', '../escape'), ('output_prefix', 'Film/%date%'),
                             ('first_frame', 'C:outside.png'), ('reference_audio', '..\\alice.wav'),
                             ('guide_audio', 'C:/alice.wav'), ('first_frame', '\\outside.png')):
            config, items = fixture()
            config['segments'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                build_continuous_workflow(config, items)

    def test_cli_writes_wrapper_gui_map_and_provenance_without_reusing_directory(self):
        config, items = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'video.json').write_text(json.dumps(items), encoding='utf-8')
            config['video_manifest'] = 'video.json'
            source = folder / 'config.json'
            source.write_text(json.dumps(config), encoding='utf-8')
            command = [sys.executable, str(ROOT / 'scripts/build_continuous_workflow.py'),
                       str(source), '--out', str(folder / 'new')]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            wrapper = json.loads((folder / 'new/workflow-api.json').read_text(encoding='utf-8'))
            gui = json.loads((folder / 'new/workflow-gui.json').read_text(encoding='utf-8'))
            self.assertEqual(wrapper['prompt'], gui)
            for reference, source in (('6', '19'), ('1006', '1019')):
                self.assertEqual([source, 0], gui[reference]['inputs']['prompt'])
                self.assertEqual('PrimitiveStringMultiline', gui[source]['class_type'])
                self.assertIn('https://github.com/', gui[source]['inputs']['value'])
                self.assertIn('"characters":', gui[source]['inputs']['value'])
            provenance = json.loads((folder / 'new/workflow-provenance.json').read_text(encoding='utf-8'))
            self.assertEqual('not_submitted', provenance['submission'])
            before = (folder / 'new/workflow-api.json').read_bytes()
            repeated = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, repeated.returncode)
            self.assertEqual(before, (folder / 'new/workflow-api.json').read_bytes())

    def test_installed_schema_detects_missing_socket_type_and_cycle(self):
        graph = {'1': {'class_type': 'Source', 'inputs': {}},
                 '2': {'class_type': 'Consumer', 'inputs': {'image': ['1', 0], 'length': 1}}}
        schema = {'Source': {'input': {}, 'output': ['IMAGE']},
                  'Consumer': {'input': {'required': {'image': ['IMAGE'], 'length': ['INT', {'min': 1, 'max': 10}]}},
                               'output': ['IMAGE']}}
        validate_installed_schema(graph, schema)
        for variant in ('missing', 'type', 'range', 'cycle'):
            changed = copy.deepcopy(graph)
            if variant == 'missing':
                changed['2']['inputs'].pop('image')
            elif variant == 'type':
                changed['2']['inputs']['image'] = ['1', 3]
            elif variant == 'range':
                changed['2']['inputs']['length'] = 0
            else:
                changed['2']['inputs']['image'] = ['2', 0]
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                validate_installed_schema(changed, schema)

    def test_installed_dynamic_combo_keys_and_stale_asset_inventory(self):
        schema = {'Combo': {'input': {'required': {'format': ['COMFY_DYNAMICCOMBO_V3', {
            'options': [{'key': 'auto', 'inputs': {'required': {}}}]}]}}, 'output': []},
                  'LoadImage': {'input': {'required': {'image': [['old.png']]}}, 'output': ['IMAGE']}}
        graph = {'1': {'class_type': 'Combo', 'inputs': {'format': 'auto'}},
                 '2': {'class_type': 'LoadImage', 'inputs': {'image': 'new-staged.png'}}}
        validate_installed_schema(graph, schema)
        graph['1']['inputs']['format'] = 'unsupported'
        with self.assertRaises(ValueError):
            validate_installed_schema(graph, schema)


if __name__ == '__main__':
    unittest.main()
