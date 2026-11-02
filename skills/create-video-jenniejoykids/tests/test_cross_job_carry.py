"""Cross-job editorial carry must preserve every complete native A/V output."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_continuous_workflow import build_continuous_workflow
from test_continuous_builder import fixture, serialize


class CrossJobCarryTests(unittest.TestCase):
    def test_single_continuation_has_external_carry_complete_native_av_and_no_sibling(self):
        config, items = fixture(1)
        item, segment = items[0], config['segments'][0]
        item.update(segment_id='S01_B', start=5)
        item['action'] = 'Continue forward while off-screen voiceover is reserved for later editorial.'
        serialize(item)
        segment.update(segment_id='S01_B', first_frame='actual-A119.png',
                       dialogue_presentation='voiceover', native_speech_conditioning=False,
                       guide_frames=[{'image': 'planned-B119.png', 'frame_idx': 119}])
        config['carry_in_first_frame'] = True
        before = copy.deepcopy((config, items))
        wrapper, receipt = build_continuous_workflow(config, items)
        graph = wrapper['prompt']
        self.assertEqual(1, len(receipt['segments']))
        self.assertEqual('S01_B', receipt['segments'][0]['segment_id'])
        self.assertTrue(all(int(key) < 1000 for key in graph))
        self.assertEqual('actual-A119.png', graph['8']['inputs']['image'])
        self.assertEqual(['8', 0], graph['52']['inputs']['image1'])
        self.assertEqual({'image': ['15', 0], 'batch_index': 1, 'length': 119}, graph['50']['inputs'])
        self.assertEqual(124, graph['6']['inputs']['length'])
        self.assertEqual(['15', 0], graph['17']['inputs']['images'])
        self.assertEqual(['16', 0], graph['17']['inputs']['audio'])
        self.assertEqual(['17', 0], graph['18']['inputs']['video'])
        self.assertEqual(['7', 0], graph['58']['inputs']['audio'])
        self.assertEqual(['19', 0], graph['6']['inputs']['prompt'])
        self.assertEqual(['9', 0], graph['101']['inputs']['positive'])
        self.assertEqual(['101', 0], graph['10']['inputs']['conditioning'])
        self.assertIsNone(receipt['segments'][0]['previous_editorial_last_image'])
        self.assertEqual(['8', 0], receipt['segments'][0]['carry_in_source']['image'])
        self.assertEqual('not_submitted', receipt['submission'])
        self.assertEqual(before, (config, items))

    def test_single_segment_absent_or_false_carry_preserves_ordinary_initial_batch(self):
        config, items = fixture(1)
        omitted = build_continuous_workflow(config, items)
        explicit_false = build_continuous_workflow({**config, 'carry_in_first_frame': False}, items)
        self.assertEqual(omitted, explicit_false)
        graph = omitted[0]['prompt']
        self.assertEqual({'image': ['15', 0], 'batch_index': 0, 'length': 120}, graph['50']['inputs'])
        self.assertNotIn('52', graph)
        self.assertEqual(['15', 0], graph['17']['inputs']['images'])

    def test_segment_count_still_rejects_empty_or_more_than_hundred(self):
        for count in (0, 101):
            config, items = fixture(count) if count else ({'segments': []}, [])
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, '1..100'):
                build_continuous_workflow(config, items)

    def test_initial_carry_changes_only_editorial_splice_and_keeps_next_boundary(self):
        for mode in ('canonical_voicestudio', 'preserve_native'):
            config, items = fixture()
            for item in items:
                item['engine']['audio_mode'] = mode
            baseline, _ = build_continuous_workflow(config, items)
            config['carry_in_first_frame'] = True
            before = copy.deepcopy((config, items))
            wrapper, receipt = build_continuous_workflow(config, items)
            expected = copy.deepcopy(baseline['prompt'])
            expected['50']['inputs'].update(batch_index=1, length=119)
            expected['52'] = {'class_type': 'ImageBatch', 'inputs': {
                'image1': ['8', 0], 'image2': ['50', 0]}}
            for key, field in (('51', 'image'), ('53', 'image'), ('56', 'images')):
                expected[key]['inputs'][field] = ['52', 0]
            with self.subTest(mode=mode):
                self.assertEqual(expected, wrapper['prompt'])
                graph = wrapper['prompt']
                self.assertEqual(['8', 0], graph['9']['inputs']['image'])
                self.assertEqual(['51', 0], graph['1009']['inputs']['image'])
                self.assertEqual(['51', 0], graph['1052']['inputs']['image1'])
                self.assertEqual(119, graph['51']['inputs']['batch_index'])
                for offset in (0, 1000):
                    key = lambda value: str(offset + value)
                    self.assertEqual(124, graph[key(6)]['inputs']['length'])
                    self.assertEqual([key(15), 0], graph[key(17)]['inputs']['images'])
                    self.assertEqual([key(16), 0], graph[key(17)]['inputs']['audio'])
                    audio_node = key(7) if mode == 'canonical_voicestudio' else key(16)
                    self.assertEqual([audio_node, 0], graph[key(58)]['inputs']['audio'])
                first, second = receipt['segments']
                self.assertTrue(receipt['carry_in_first_frame'])
                self.assertTrue(first['carry_in_first_frame'])
                self.assertEqual(['8', 0], first['carry_in_source']['image'])
                self.assertEqual('outside.png', first['carry_in_source']['staged_asset'])
                self.assertEqual('pending_before_Run', first['carry_in_source']['actual_dimension_check'])
                self.assertEqual([864, 480], [first['carry_in_source']['expected_native_width'],
                                            first['carry_in_source']['expected_native_height']])
                self.assertIsNone(first['previous_editorial_last_image'])
                self.assertEqual(['51', 0], second['previous_editorial_last_image'])
                self.assertNotIn('carry_in_source', second)
                self.assertEqual(before, (config, items))

    def test_absent_and_false_carry_are_identical_including_provenance(self):
        config, items = fixture()
        omitted = build_continuous_workflow(config, items)
        explicit_false = build_continuous_workflow({**config, 'carry_in_first_frame': False}, items)
        self.assertEqual(omitted, explicit_false)
        self.assertNotIn('52', omitted[0]['prompt'])
        self.assertNotIn('carry_in_first_frame', omitted[1])

    def test_carry_requires_strict_boolean_and_lossless_png(self):
        config, items = fixture()
        for value in (None, 0, 1, 'true', [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'must be a boolean'):
                build_continuous_workflow({**config, 'carry_in_first_frame': value}, items)
        config['carry_in_first_frame'] = True
        config['segments'][0]['first_frame'] = 'boundary.jpg'
        with self.assertRaisesRegex(ValueError, 'lossless accepted-boundary PNG'):
            build_continuous_workflow(config, items)
        config['segments'][0].pop('first_frame')
        with self.assertRaisesRegex(ValueError, 'requires a staged first_frame'):
            build_continuous_workflow(config, items)

    def test_installed_schema_pass_keeps_actual_png_dimensions_pending(self):
        path = Path.cwd() / 'production-local/installed-object-info.json'
        if not path.is_file():
            self.skipTest('Installed schema snapshot unavailable')
        config, items = fixture()
        config['carry_in_first_frame'] = True
        _, receipt = build_continuous_workflow(config, items,
                                              json.loads(path.read_text(encoding='utf-8-sig')))
        self.assertEqual('passed', receipt['installed_schema_validation'])
        self.assertEqual('pending_before_Run', receipt['segments'][0]['carry_in_source']['actual_dimension_check'])
        self.assertIn('no resize or crop', receipt['segments'][0]['carry_in_source']['dimension_requirement'])


if __name__ == '__main__':
    unittest.main()
