"""Contiguous video guide conditioning; offline graph construction only."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_comfy_workflow import build_workflow
from build_continuous_workflow import build_continuous_workflow
from compile_prompts import compile_project


def serialize(item):
    payload = json.loads(item['prompt'].split('\n', 1)[1])
    for field in payload:
        payload[field] = copy.deepcopy(item[field])
    item['prompt'] = 'Expanded visual scene\n' + json.dumps(payload, ensure_ascii=False)


def fixtures():
    project = json.loads((ROOT / 'examples/zoo-60s.json').read_text(encoding='utf-8'))
    original = compile_project(project)['VIDEO'][0]
    items, segments = [], []
    for index in range(2):
        item = copy.deepcopy(original)
        item.update(segment_id=f'clip-{index}', start=index * 5, duration=5)
        item['dialogue'] = item['dialogue'][:1]
        item['action'] = 'Walk straight ahead while off-screen voiceover is reserved for later editorial.'
        item['continuity'].update(entry_state=f'position-{index}', exit_state=f'position-{index + 1}')
        serialize(item)
        segment = {'segment_id': item['segment_id'], 'editorial_frames': 120,
                   'reference_images': ['family.png'], 'reference_audio': 'alice-identity.wav',
                   'guide_audio': f'alice-original-{index}.wav',
                   'dialogue_presentation': 'voiceover', 'native_speech_conditioning': False,
                   'output_prefix': f'Film/clip-{index}'}
        if index == 0:
            segment['first_frame'] = 'outside.png'
        items.append(item)
        segments.append(segment)
    return {'segments': segments}, items


class VideoGuideTests(unittest.TestCase):
    def test_full_clip_uses_contiguous_frames_original_latent_and_no_clip_audio(self):
        config, items = fixtures()
        segment = config['segments'][0]
        segment['guide_clips'] = [{'video': 'walk-A.mkv', 'frame_idx': 0, 'frames': 124}]
        before = copy.deepcopy((config, items))
        wrapper, receipt = build_workflow(segment, items[0])
        graph = wrapper['prompt']
        self.assertEqual('walk-A.mkv', graph['100']['inputs']['file'])
        self.assertEqual(['100', 0], graph['101']['inputs']['video'])
        self.assertEqual({'image': ['101', 0], 'batch_index': 0, 'length': 124}, graph['102']['inputs'])
        self.assertEqual(['102', 0], graph['103']['inputs']['image'])
        self.assertEqual(['9', 0], graph['103']['inputs']['positive'])
        self.assertEqual(['6', 1], graph['103']['inputs']['latent'])
        self.assertEqual(0, graph['103']['inputs']['frame_idx'])
        self.assertEqual(['103', 0], graph['10']['inputs']['conditioning'])
        self.assertFalse(any(value in (['101', 1], ['101', 2]) for node in graph.values()
                             for value in node['inputs'].values()))
        self.assertNotIn('audio', graph['103']['inputs'])
        self.assertEqual(['15', 0], graph['17']['inputs']['images'])
        self.assertEqual(['16', 0], graph['17']['inputs']['audio'])
        self.assertEqual(['19', 0], graph['6']['inputs']['prompt'])
        self.assertEqual('103', receipt['first_extra_guide_node'])
        clip = receipt['clip_guides'][0]
        self.assertEqual('pending', clip['source_preflight']['status'])
        self.assertEqual(24, clip['source_preflight']['required_fps'])
        self.assertEqual(124, clip['source_preflight']['minimum_source_frames'])
        enabled, _ = build_workflow({**segment, 'native_speech_conditioning': True}, items[0])
        self.assertEqual(['7', 0], enabled['prompt']['9']['inputs']['audio'])
        self.assertNotIn('audio', enabled['prompt']['103']['inputs'])
        self.assertFalse(any(value == ['101', 1] for node in enabled['prompt'].values()
                             for value in node['inputs'].values()))
        self.assertEqual(before, (config, items))

    def test_mixed_dense_guides_are_chronological_without_id_collision(self):
        config, items = fixtures()
        segment = config['segments'][0]
        segment['guide_frames'] = [{'image': f'pose-{at}.png', 'frame_idx': at} for at in (10, 60, 119)]
        segment['guide_clips'] = [{'video': 'motion-A.mkv', 'frame_idx': 0, 'frames': 124},
                                 {'video': 'motion-B.mkv', 'frame_idx': 24, 'frames': 90}]
        graph, receipt = build_workflow(segment, items[0])
        graph = graph['prompt']
        chain = receipt['guide_chain']
        self.assertEqual([0, 0, 10, 24, 60, 119], [entry['frame_idx'] for entry in chain])
        self.assertEqual(['frame_zero', 'clip', 'image', 'clip', 'image', 'image'], [entry['kind'] for entry in chain])
        previous = ['6', 0]
        for entry in chain:
            node = graph[entry['guide_node']]
            self.assertEqual(previous, node['inputs']['positive'])
            self.assertEqual(['6', 1], node['inputs']['latent'])
            previous = [entry['guide_node'], 0]
        self.assertEqual(previous, graph['10']['inputs']['conditioning'])
        self.assertTrue(all(int(node) < 1000 for node in graph))
        self.assertEqual(len(graph), len(set(graph)))

    def test_rejects_bad_shapes_bounds_paths_and_order(self):
        config, items = fixtures()
        base = config['segments'][0]
        bad = [
            None, {}, [None],
            *[[{'video': 'x.mkv', 'frame_idx': 0, 'frames': value}]
              for value in (0, 4, 6, 123, 141, True, 124.0)],
            *[[{'video': 'x.mkv', 'frame_idx': value, 'frames': 5}]
              for value in (-1, 120, True, 0.0)],
            [{'video': '../x.mkv', 'frame_idx': 0, 'frames': 5}],
            [{'video': 'C:\\x.mkv', 'frame_idx': 0, 'frames': 5}],
            [{'video': 'x.mkv', 'frame_idx': 0, 'frames': 5, 'audio': True}],
            [{'video': 'x.mkv', 'frame_idx': 24, 'frames': 5}, {'video': 'y.mkv', 'frame_idx': 0, 'frames': 5}],
            [{'video': 'x.mkv', 'frame_idx': 0, 'frames': 5}, {'video': 'y.mkv', 'frame_idx': 0, 'frames': 5}],
        ]
        for clips in bad:
            with self.subTest(clips=clips), self.assertRaises(ValueError):
                build_workflow({**base, 'guide_clips': clips}, items[0])
        for start, frames in ((0, 124), (24, 90), (119, 5)):
            with self.subTest(start=start, frames=frames):
                build_workflow({**base, 'guide_clips': [{'video': 'x.mkv', 'frame_idx': start, 'frames': frames}]}, items[0])
        build_workflow({**base, 'guide_clips': []}, items[0])

    def test_combined_node_budget_caps_ids_below_thousand(self):
        config, items = fixtures()
        source = items[0]
        source['duration'] = 15
        serialize(source)
        base = config['segments'][0]
        clips = [{'video': f'clip-{index}.mkv', 'frame_idx': index, 'frames': 5} for index in range(225)]
        graph, _ = build_workflow({**base, 'guide_clips': clips}, source)
        self.assertEqual('MiniMaxH3AddGuide', graph['prompt']['999']['class_type'])
        self.assertNotIn('1000', graph['prompt'])
        with self.assertRaisesRegex(ValueError, 'node-ID budget'):
            build_workflow({**base, 'guide_clips': clips,
                            'guide_frames': [{'image': 'last.png', 'frame_idx': 350}]}, source)

    def test_clip_only_b_inserts_incoming_frame_zero_before_clip_and_retains_all_outputs(self):
        config, items = fixtures()
        config['segments'][0]['guide_clips'] = [{'video': 'walk-A.mkv', 'frame_idx': 0, 'frames': 124}]
        config['segments'][1]['guide_clips'] = [{'video': 'walk-B.mkv', 'frame_idx': 24, 'frames': 90}]
        standalone, standalone_receipt = build_workflow(config['segments'][1], items[1])
        self.assertNotIn('9', standalone['prompt'])
        self.assertIsNone(standalone_receipt['frame_zero_guide_node'])
        wrapper, receipt = build_continuous_workflow(config, items)
        graph = wrapper['prompt']
        self.assertEqual(['51', 0], graph['1009']['inputs']['image'])
        self.assertEqual(['1006', 0], graph['1009']['inputs']['positive'])
        self.assertEqual(['1009', 0], graph['1103']['inputs']['positive'])
        self.assertEqual(['1103', 0], graph['1010']['inputs']['conditioning'])
        self.assertEqual(['1006', 1], graph['1103']['inputs']['latent'])
        self.assertEqual(['1007', 0], graph['1058']['inputs']['audio'])
        self.assertEqual(['1016', 0], graph['1017']['inputs']['audio'])
        self.assertEqual(['1017', 0], graph['1018']['inputs']['video'])
        self.assertEqual(['51', 0], graph['1052']['inputs']['image1'])
        self.assertEqual(['1019', 0], graph['1006']['inputs']['prompt'])
        second = receipt['segments'][1]
        self.assertEqual('1103', second['first_extra_guide_node'])
        self.assertEqual(['1009', '1103'], [entry['guide_node'] for entry in second['guide_chain']])
        self.assertEqual('1100', second['clip_guides'][0]['video_node'])
        self.assertEqual('1101', second['clip_guides'][0]['components_node'])

    def test_actual_installed_object_schema_accepts_video_guide_graph(self):
        path = Path.cwd() / 'production-local/installed-object-info.json'
        if not path.is_file():
            self.skipTest('Installed Comfy schema fixture not present')
        config, items = fixtures()
        config['segments'][0]['guide_clips'] = [{'video': 'walk-A.mkv', 'frame_idx': 0, 'frames': 124}]
        config['segments'][1]['guide_clips'] = [{'video': 'walk-B.mkv', 'frame_idx': 24, 'frames': 90}]
        _, receipt = build_continuous_workflow(config, items, json.loads(path.read_text(encoding='utf-8-sig')))
        self.assertEqual('passed', receipt['installed_schema_validation'])
        self.assertEqual('pending', receipt['segments'][1]['clip_guides'][0]['source_preflight']['status'])


if __name__ == '__main__':
    unittest.main()
