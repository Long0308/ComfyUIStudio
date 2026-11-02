"""Optional display labels must not change execution inputs or read scripts."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_comfy_workflow import build_workflow
from build_continuous_workflow import build_continuous_workflow
from test_continuous_builder import fixture


def without_metadata(graph):
    return {key: {field: copy.deepcopy(value) for field, value in node.items() if field != '_meta'}
            for key, node in graph.items()}


class SceneMetadataTests(unittest.TestCase):
    def test_labels_do_not_change_pinned_native_execution_graph_or_open_script(self):
        config, items = fixture()
        base = config['segments'][0]
        original, original_receipt = build_workflow(base, items[0])
        annotated = {**base, 'scene_label': 'Scene 2A / S02_A',
                     'script_md': 'Z:/not-present/SCENE.md'}
        with patch.object(Path, 'read_text', side_effect=AssertionError('Metadata must not read a script')):
            wrapper, receipt = build_workflow(annotated, items[0])
        self.assertEqual(original['prompt'], without_metadata(wrapper['prompt']))
        self.assertNotIn('scene_label', original_receipt)
        self.assertNotIn('script_md', original_receipt)
        for node in ('6', '13', '14', '17', '18', '19'):
            self.assertTrue(wrapper['prompt'][node]['_meta']['title'].startswith('Scene 2A / S02_A — '))
            self.assertEqual('SCENE.md: Z:/not-present/SCENE.md', wrapper['prompt'][node]['_meta']['description'])
        self.assertEqual('Scene 2A / S02_A', receipt['scene_label'])
        self.assertEqual('Z:/not-present/SCENE.md', receipt['script_md'])

    def test_continuous_labels_remap_without_changing_any_inputs_or_links(self):
        config, items = fixture()
        base, _ = build_continuous_workflow(config, items)
        before = copy.deepcopy((config, items))
        for suffix, segment in zip(('A', 'B'), config['segments']):
            segment.update(scene_label=f'Scene 2{suffix} / S02_{suffix}', script_md='D:/film/SCENE.md')
        labeled, receipt = build_continuous_workflow(config, items)
        self.assertEqual(base['prompt'], without_metadata(labeled['prompt']))
        self.assertEqual(before[1], items)
        for offset, suffix in ((0, 'A'), (1000, 'B')):
            for node in (6, 13, 14, 18, 19, 54, 55, 56, 57):
                meta = labeled['prompt'][str(offset + node)]['_meta']
                self.assertTrue(meta['title'].startswith(f'Scene 2{suffix} / S02_{suffix} — '))
                self.assertEqual('SCENE.md: D:/film/SCENE.md', meta['description'])
        self.assertEqual(['Scene 2A / S02_A', 'Scene 2B / S02_B'], [item['scene_label'] for item in receipt['segments']])

    def test_invalid_metadata_rejected_and_independent_fields_supported(self):
        config, items = fixture()
        base = config['segments'][0]
        for field in ('scene_label', 'script_md'):
            for value in (None, False, '', '  ', 'x\ny', 'x\x00y', 'x\x7fy'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    build_workflow({**base, field: value}, items[0])
        labeled, receipt = build_workflow({**base, 'scene_label': 'Scene 2A'}, items[0])
        self.assertNotIn('description', labeled['prompt']['19']['_meta'])
        self.assertNotIn('script_md', receipt)
        linked, receipt = build_workflow({**base, 'script_md': 'SCENE.md'}, items[0])
        self.assertTrue(linked['prompt']['19']['_meta']['title'].startswith(items[0]['segment_id']))
        self.assertEqual(items[0]['segment_id'], receipt['scene_label'])


if __name__ == '__main__':
    unittest.main()
