"""Per-line caption binding; fake media is copied but never rendered."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from compile_prompts import compile_project
from prepare_edit import prepare, validate_film
from test_finishing import film_data


class CaptionPositionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        request = json.loads((ROOT / 'examples/zoo-60s.json').read_text(encoding='utf-8'))
        self.compiled = compile_project(request)
        self.request = self.folder / 'request.json'
        self.request.write_text(json.dumps(request), encoding='utf-8')
        self.clip = self.folder / 'fixture.mp4'
        self.clip.write_bytes(b'Unit test placeholder; never media acceptance or rendered.')
        self.mix = self.folder / 'fixture.wav'
        self.mix.write_bytes(b'Unit test canonical placeholder; never played or rendered.')

    def config(self, name):
        return {'production_request': str(self.request), 'project_dir': str(self.folder / name),
                'canonical_mix': str(self.mix), 'comfy_url': 'http://127.0.0.1:8188',
                'accepted_clips': [{'segment_id': segment['segment_id'], 'file': str(self.clip),
                                    'accepted': True, 'engine': 'native_h3'}
                                   for segment in self.compiled['EDIT']['segments']],
                'runtime': {key: sys.executable for key in ('node', 'renderer_cli', 'ffmpeg', 'ffprobe')}}

    def bind(self, config):
        prepare(config)
        folder = Path(config['project_dir'])
        return json.loads((folder / 'src/film.json').read_text(encoding='utf-8')), (folder / 'captions.srt').read_bytes()

    def test_absent_and_empty_mapping_emit_identical_films_and_srt(self):
        absent, absent_srt = self.bind(self.config('absent'))
        empty, empty_srt = self.bind({**self.config('empty'), 'caption_positions': {}})
        self.assertEqual(absent, empty)
        self.assertEqual(absent_srt, empty_srt)
        self.assertTrue(all('position' not in line for line in absent['dialogue']))

    def test_only_mapped_line_gets_position_without_changing_media_words_or_clock(self):
        original_request = self.request.read_bytes()
        original_clip, original_mix = self.clip.read_bytes(), self.mix.read_bytes()
        baseline, srt = self.bind(self.config('baseline'))
        first_id = baseline['dialogue'][0]['id']
        for position in ('top', 'bottom', 'top-left'):
            config = {**self.config(position), 'caption_positions': {first_id: position}}
            before = copy.deepcopy(config)
            film, output_srt = self.bind(config)
            expected = copy.deepcopy(baseline)
            expected['dialogue'][0]['position'] = position
            self.assertEqual(expected, film)
            self.assertEqual(srt, output_srt)
            self.assertTrue(all('position' not in line for line in film['dialogue'][1:]))
            self.assertEqual(original_mix, (Path(config['project_dir']) / 'public/audio/canonical-mix.wav').read_bytes())
            self.assertEqual(before, config)
        self.assertEqual(original_request, self.request.read_bytes())
        self.assertEqual(original_clip, self.clip.read_bytes())
        self.assertEqual(original_mix, self.mix.read_bytes())

    def test_unknown_ids_mapping_types_and_position_types_fail_before_outputs(self):
        identifier = self.compiled['EDIT']['segments'][0]['dialogue'][0]['id']
        bad = [None, False, [], 'top', {'unknown-line': 'top'}, {'': 'top'}, {1: 'top'},
               *[{identifier: value} for value in (False, True, 0, 1, None, {}, [], '', 'middle', 'TOP')]]
        for index, mapping in enumerate(bad):
            config = {**self.config(f'invalid-{index}'), 'caption_positions': mapping}
            with self.subTest(mapping=mapping), self.assertRaisesRegex(ValueError, 'caption_positions'):
                prepare(config)
            self.assertFalse(Path(config['project_dir']).exists())

    def test_python_film_contract_rejects_invalid_explicit_position(self):
        for position in ('top', 'bottom', 'top-left'):
            film = film_data()
            film['dialogue'][0]['position'] = position
            validate_film(film)
        for value in (False, True, None, 0, [], {}, 'middle'):
            film = film_data()
            film['dialogue'][0]['position'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Caption position'):
                validate_film(film)


if __name__ == '__main__':
    unittest.main()
