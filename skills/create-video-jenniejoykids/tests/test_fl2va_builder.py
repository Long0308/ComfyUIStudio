"""Native FL2VA graph contracts; no model files, server calls or rendering."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_continuous_workflow import build_continuous_workflow
from build_fl2va_workflow import build_fl2va_workflow, CHECKPOINT, CHECKPOINT_SHA256
from test_continuous_builder import fixture, serialize


def fl_fixture():
    config, items = fixture(1)
    config['carry_in_first_frame'] = True
    segment = config['segments'][0]
    segment.update(first_frame='accepted-A119.png', last_frame='target-B119.png',
                   reference_images=[], scheduler='simple', dialogue_presentation='voiceover',
                   native_speech_conditioning=False)
    items[0]['action'] = 'Walk straight forward through the gate; off-screen voiceover is reserved for editorial.'
    serialize(items[0])
    return config, items


class FL2VABuilderTests(unittest.TestCase):
    def test_first_last_native_av_and_canonical_carry_contract(self):
        config, items = fl_fixture()
        before = copy.deepcopy((config, items))
        wrapper, proof = build_fl2va_workflow(config, items)
        graph = wrapper['prompt']
        self.assertEqual({'prompt'}, set(wrapper))
        self.assertEqual(before, (config, items))
        self.assertEqual(CHECKPOINT, graph['1']['inputs']['unet_name'])
        self.assertEqual({'clip': ['2', 0], 'vae': ['3', 0], 'prompt': ['19', 0],
                          'width': 864, 'height': 480, 'length': 124,
                          'first_frame': ['8', 0], 'last_frame': ['20', 0]}, graph['6']['inputs'])
        self.assertEqual('MiniMaxH3ImageToVideo', graph['6']['class_type'])
        self.assertEqual(['6', 0], graph['10']['inputs']['conditioning'])
        self.assertEqual(['6', 1], graph['14']['inputs']['latent_image'])
        self.assertEqual('simple', graph['13']['inputs']['scheduler'])
        self.assertFalse(any(node['class_type'] in ('MiniMaxH3AddGuide', 'MiniMaxH3ReferenceToVideo')
                             for node in graph.values()))
        self.assertEqual({'8', '20'}, {key for key, node in graph.items() if node['class_type'] == 'LoadImage'})
        self.assertEqual({'images': ['15', 0], 'audio': ['16', 0], 'fps': 24.0}, graph['17']['inputs'])
        self.assertEqual({'image': ['15', 0], 'batch_index': 1, 'length': 119}, graph['50']['inputs'])
        self.assertEqual({'image1': ['8', 0], 'image2': ['50', 0]}, graph['52']['inputs'])
        self.assertEqual({'audio': ['7', 0], 'start_index': 0.0, 'duration': 5.0}, graph['58']['inputs'])
        self.assertEqual(['52', 0], graph['56']['inputs']['images'])
        self.assertEqual(119, graph['51']['inputs']['batch_index'])
        self.assertEqual(['51', 0], graph['55']['inputs']['images'])
        receipt = proof['segments'][0]
        self.assertEqual(123, receipt['keyframe_conditioning'][1]['native_frame_index'])
        self.assertEqual(119, receipt['last_used_frame_index'])
        self.assertIn('actual generated frame119', receipt['last_frame_editorial_note'])
        self.assertEqual(items[0]['dialogue'], receipt['source_dialogue'])
        self.assertEqual('pending', proof['installed_schema_validation'])
        self.assertEqual('not_submitted', proof['submission'])
        self.assertEqual(CHECKPOINT_SHA256, proof['model_checkpoint']['expected_sha256'])

    def test_complete_literal_cast_and_only_consumed_keyframe_bindings(self):
        config, items = fl_fixture()
        config['segments'][0]['reference_images'] = ['accepted-A119.png']
        graph, proof = build_fl2va_workflow(config, items)
        text = graph['prompt']['19']['inputs']['value']
        payload = json.loads(text.split('\n', 2)[2])
        self.assertEqual(items[0]['characters'], payload['characters'])
        self.assertNotIn('dialogue', payload)
        for line in items[0]['dialogue']:
            self.assertNotIn(line['text'], text)
        bindings = proof['segments'][0]['reference_bindings']
        self.assertEqual(['first_frame', 'last_frame'], [value['role'] for value in bindings])
        self.assertEqual(['accepted-A119.png', 'target-B119.png'], [value['path'] for value in bindings])
        self.assertTrue(all(value['status'] == 'unverified' for value in bindings))
        self.assertIn('<Picture 1>', text)
        self.assertIn('<Picture 2>', text)

    def test_timing_dimensions_steps_seed_remain_general_and_derived(self):
        config, items = fl_fixture()
        items[0]['duration'] = 2
        items[0]['dialogue'][0]['end'] = 1.8
        serialize(items[0])
        config['segments'][0].update(editorial_frames=48, width=640, height=352, steps=6, seed=7)
        wrapper, proof = build_fl2va_workflow(config, items)
        graph, receipt = wrapper['prompt'], proof['segments'][0]
        self.assertEqual((640, 352, 56), tuple(graph['6']['inputs'][key] for key in ('width', 'height', 'length')))
        self.assertEqual(6, graph['13']['inputs']['steps'])
        self.assertEqual(7, graph['11']['inputs']['noise_seed'])
        self.assertEqual(47, receipt['last_used_frame_index'])
        self.assertEqual(55, receipt['keyframe_conditioning'][1]['native_frame_index'])
        self.assertIn('native frame55', receipt['last_frame_editorial_note'])

    def test_windows_relative_reference_spellings_normalize_without_source_mutation(self):
        config, items = fl_fixture()
        segment = config['segments'][0]
        segment.update(first_frame='boundaries\\first.png', last_frame='boundaries/last.png',
                       reference_images=['boundaries/first.png', 'boundaries\\last.png'],
                       reference_bindings=[{'path': 'boundaries\\first.png'}, {'path': 'boundaries/last.png'}])
        before = copy.deepcopy(config)
        wrapper, proof = build_fl2va_workflow(config, items)
        self.assertEqual(before, config)
        self.assertEqual('boundaries/first.png', wrapper['prompt']['8']['inputs']['image'])
        self.assertEqual('boundaries/last.png', wrapper['prompt']['20']['inputs']['image'])
        self.assertEqual(['boundaries/first.png', 'boundaries/last.png'],
                         [binding['path'] for binding in proof['segments'][0]['reference_bindings']])

    def test_malformed_binding_cast_and_engine_fail_as_validation_errors(self):
        for change in ('scope', 'cast', 'engine'):
            config, items = fl_fixture()
            if change == 'scope':
                config['segments'][0].update(reference_images=['accepted-A119.png'],
                    reference_bindings=[{'path': 'accepted-A119.png', 'scope': 1}])
            if change == 'cast': items[0]['characters'] = [None]
            if change == 'engine': items[0]['engine'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_fl2va_workflow(config, items)

    def test_ref2va_builder_output_and_defaults_are_unchanged(self):
        config, items = fixture(1)
        before = build_continuous_workflow(config, items)
        build_fl2va_workflow(*fl_fixture())
        self.assertEqual(before, build_continuous_workflow(config, items))
        self.assertEqual('beta', before[0]['prompt']['13']['inputs']['scheduler'])
        self.assertEqual('MiniMaxH3ReferenceToVideo', before[0]['prompt']['6']['class_type'])

    def test_rejects_unsupported_scope_or_unconsumed_references(self):
        changes = [('scheduler', None), ('scheduler', 'beta'), ('last_frame', None),
                   ('last_frame', '../outside.png'), ('last_frame', 'C:\\outside.png'),
                   ('last_frame', 'compressed.jpg'), ('native_speech_conditioning', True),
                   ('dialogue_presentation', 'on_screen'), ('guide_frames', [{'image': 'x.png', 'frame_idx': 60}]),
                   ('guide_clips', [{'video': 'x.mkv', 'frame_idx': 0, 'frames': 124}]),
                   ('reference_images', ['unconsumed.png']), ('reference_images', 'accepted-A119.png'),
                   ('reference_bindings', [{'path': 'unknown.png'}]), ('steps', 0), ('seed', -1)]
        for key, value in changes:
            config, items = fl_fixture()
            config['segments'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                build_fl2va_workflow(config, items)
        for change in ('no-carry', 'two-segments', 'native-audio'):
            config, items = fl_fixture()
            if change == 'no-carry': config['carry_in_first_frame'] = False
            if change == 'two-segments': config['segments'] *= 2
            if change == 'native-audio': items[0]['engine']['audio_mode'] = 'preserve_native'
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_fl2va_workflow(config, items)

    def test_final_transformed_graph_is_the_only_installed_schema_validation(self):
        config, items = fl_fixture()
        objects = {'synthetic': 'test only; not installed schema evidence'}
        with patch('build_fl2va_workflow.validate_installed_schema') as validate:
            wrapper, proof = build_fl2va_workflow(config, items, objects)
        validate.assert_called_once_with(wrapper['prompt'], objects)
        self.assertEqual('MiniMaxH3ImageToVideo', validate.call_args.args[0]['6']['class_type'])
        self.assertEqual('passed', proof['installed_schema_validation'])
        self.assertEqual('pending_external_size_and_SHA256_check', proof['model_checkpoint']['artifact_verification'])
        with self.assertRaisesRegex(ValueError, 'Installed object schema missing'):
            build_fl2va_workflow(config, items, {})
        for invalid in ([], False, 4, 'bad'):
            with self.subTest(schema=invalid), self.assertRaisesRegex(ValueError, 'object_info must be an object'):
                build_fl2va_workflow(config, items, invalid)

    def test_cli_outputs_are_new_and_invalid_input_creates_nothing(self):
        config, items = fl_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'video.json').write_text(json.dumps(items), encoding='utf-8')
            config['video_manifest'] = 'video.json'
            (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            command = [sys.executable, '-B', str(ROOT / 'scripts/build_fl2va_workflow.py'),
                       str(folder / 'config.json'), '--out', str(folder / 'fresh')]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            wrapper = json.loads((folder / 'fresh/workflow-api.json').read_text(encoding='utf-8'))
            self.assertEqual(wrapper['prompt'], json.loads((folder / 'fresh/workflow-gui.json').read_text(encoding='utf-8')))
            before = (folder / 'fresh/workflow-api.json').read_bytes()
            self.assertNotEqual(0, subprocess.run(command, capture_output=True, check=False).returncode)
            self.assertEqual(before, (folder / 'fresh/workflow-api.json').read_bytes())
            (folder / 'schema.json').write_text('[]', encoding='utf-8')
            config['installed_object_info'] = 'schema.json'
            (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            command[-1] = str(folder / 'invalid-schema')
            bad_schema = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, bad_schema.returncode)
            self.assertIn('object_info must be an object', bad_schema.stderr)
            self.assertNotIn('Traceback', bad_schema.stderr)
            self.assertFalse((folder / 'invalid-schema').exists())
            config.pop('installed_object_info')
            config['segments'][0]['last_frame'] = '../unsafe.png'
            (folder / 'config.json').write_text(json.dumps(config), encoding='utf-8')
            command[-1] = str(folder / 'invalid')
            self.assertNotEqual(0, subprocess.run(command, capture_output=True, check=False).returncode)
            self.assertFalse((folder / 'invalid').exists())


if __name__ == '__main__':
    unittest.main()
