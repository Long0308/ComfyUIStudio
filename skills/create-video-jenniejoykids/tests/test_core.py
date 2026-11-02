"""Behavioral contract tests; no external services or packages."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_request import (
    CANONICAL_EXPRESSIONS, character_generation_plan, validate_request,
    CHARACTER_FIELDS,
)
from compile_prompts import compile_project


def example(name='zoo-60s'):
    return json.loads((ROOT / 'examples' / (name + '.json')).read_text(encoding='utf-8'))


def split_example():
    data = example('expanded-education')
    parent = data['scenes'][0]
    first, second = copy.deepcopy(parent), copy.deepcopy(parent)
    first.update(id='SH01_A', start=0, duration=4, repeat_cues=[],
                 sfx=[{'at': .5, 'event': 'First segment gentle wood tap'}])
    second.update(id='SH01_B', start=4, duration=4, dialogue=[],
                  repeat_cues=[{'start': .4, 'end': 3, 'text': 'Circle — Your turn'}],
                  music='Second segment sparse soft bell music, no lyrics.',
                  sfx=[{'at': .3, 'event': 'Second segment quiet bell'}])
    second['script_tracking']['dialogue_ids'] = []
    first['continuity']['exit_state'] = 'Milo holds the circle steadily above the sage table'
    second['continuity']['entry_state'] = first['continuity']['exit_state']
    first['continuity']['previous_segment_id'] = ''
    second['continuity']['previous_segment_id'] = first['id']
    first['transition']['intent'] = 'Continue disk tracing gesture into the following segment.'
    second['transition']['intent'] = 'Settle the wooden disk then complete the closing hold.'
    first['subtitle']['style'] = 'First segment white caption on dark rounded band.'
    second['subtitle']['style'] = 'Second segment learning word on restrained teal band.'
    parent['subshots'] = [first, second]
    return data

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_reuse_library(root, directory, character_id):
    version = root / directory / '2026-10-18-v1'
    expressions = version / 'expressions'
    expressions.mkdir(parents=True, exist_ok=True)
    canonical = version / 'canonical.png'
    canonical.write_bytes((character_id + ' canonical').encode())
    icons = []
    expression_records = []
    for expression_id in sorted(CANONICAL_EXPRESSIONS):
        image = expressions / (expression_id + '.png')
        image.write_bytes((character_id + ' ' + expression_id).encode())
        icons.append({
            'asset_id': f'{character_id}.{expression_id}',
            'expression_id': expression_id,
            'png': f'expressions/{image.name}',
            'sha256': digest(image),
            'review_status': f'{character_id} reviewed in fixture',
            'user_approval': f'{character_id} approval status preserved',
        })
        expression_records.append({
            'expression_id': expression_id,
            'png': str(image),
            'sha256': digest(image),
            'review_status': f'{character_id} reviewed in fixture',
            'user_approval': f'{character_id} approval status preserved',
        })
    expression_manifest = version / 'manifest.json'
    expression_manifest.write_text(json.dumps({
        'character_id': character_id,
        'version': '2026-10-18-v1',
        'canonical': canonical.name,
        'canonical_sha256': digest(canonical),
        'canonical_approval': f'{character_id} recorded fixture status',
        'icons': icons,
    }), encoding='utf-8')
    return {
        'character_id': character_id,
        'source_version': '2026-10-18-v1',
        'canonical_png': str(canonical),
        'canonical_sha256': digest(canonical),
        'canonical_approval': f'{character_id} recorded fixture status',
        'expressions_manifest': str(expression_manifest),
        'expressions_manifest_sha256': digest(expression_manifest),
        'render_policy': 'reuse_existing_no_character_regeneration',
        'expressions': expression_records,
    }

def reuse_request(root):
    data = example('expanded-education')
    source = example('zoo-60s')
    alice = copy.deepcopy(next(c for c in source['characters'] if c['id'] == 'alice'))
    mother = copy.deepcopy(next(c for c in source['characters'] if c['id'] == 'mother'))
    data['characters'] = [alice, mother]
    for scene in data['scenes']:
        scene['characters'] = [copy.deepcopy(alice), copy.deepcopy(mother)]
        for line in scene['dialogue']:
            line['speaker'] = 'alice'
    records = [
        write_reuse_library(root, 'alice', 'alice'),
        write_reuse_library(root, 'mother', 'mom-alice'),
    ]
    manifest = root / 'REUSE-CAST.json'
    manifest.write_text(json.dumps({
        'schema': 'jenniejoy-episode-cast-reuse-v1',
        'characters': records,
    }), encoding='utf-8')
    data['image_engine'] = {
        'provider': 'ComfyUI',
        'execution': 'local',
        'model': 'test-local-image-model',
        'profile': 'test RTX local ComfyUI graph',
        'workflow': 'workflows/test-storyboard.api.json',
    }
    data['reference_policy']['sheet_requirements'] = {
        'plan_mode': 'reuse-only',
        'turnaround': [],
        'expressions': [],
        'poses': [],
    }
    data['cast_reuse'] = {
        'manifest_path': str(manifest),
        'manifest_sha256': digest(manifest),
        'characters': {'alice': 'alice', 'mother': 'mom-alice'},
    }
    return data

def mixed_reuse_request(root):
    data = reuse_request(root)
    data['project']['id'] = '04-milk-and-mom'
    milkmaid = copy.deepcopy(example('expanded-education')['characters'][0])
    milkmaid.update({
        'id': 'milkmaid',
        'name': 'Milkmaid',
        'age': 'Adult woman approximately twenty-five years old',
    })
    data['characters'].append(milkmaid)
    for scene in data['scenes']:
        scene['characters'].append(copy.deepcopy(milkmaid))
    data['reference_policy']['sheet_requirements'] = {
        'plan_mode': 'canonical-12',
        'turnaround': ['front', 'left', 'right'],
        'expressions': sorted(CANONICAL_EXPRESSIONS),
        'poses': ['scene-specific action references'],
    }
    return data


class CoreTests(unittest.TestCase):
    def test_complete_examples(self):
        for name in ('zoo-60s', 'expanded-education'):
            with self.subTest(name=name):
                self.assertEqual([], validate_request(example(name)))

    def assert_invalid(self, mutate):
        data = example()
        mutate(data)
        self.assertTrue(validate_request(data))
        with self.assertRaises(ValueError):
            compile_project(data)

    def test_name_only_character(self):
        self.assert_invalid(lambda d: d['scenes'][0]['characters'].__setitem__(0, 'Alice'))

    def test_missing_face_field(self):
        self.assert_invalid(lambda d: d['scenes'][0]['characters'][0].pop('eyes'))

    def test_clothing_drift(self):
        self.assert_invalid(lambda d: d['scenes'][1]['characters'][0].__setitem__('clothes', 'Green overalls and a plain cotton shirt'))

    def test_anatomical_bow_side_drift(self):
        self.assert_invalid(lambda d: d['scenes'][2]['characters'][0].__setitem__('marks_asymmetry', 'Bow and ponytail on anatomical LEFT'))

    def test_unknown_speaker(self):
        self.assert_invalid(lambda d: d['scenes'][0]['dialogue'][0].__setitem__('speaker', 'unresolved'))

    def test_duration_and_timing(self):
        for mutation in (
            lambda d: d['delivery'].__setitem__('duration', 61),
            lambda d: d['scenes'][1].__setitem__('start', 9),
            lambda d: d['scenes'][1].__setitem__('start', 11),
            lambda d: d['scenes'][0]['dialogue'][0].__setitem__('end', 30),
            lambda d: d['scenes'][0].__setitem__('duration', float('nan')),
            lambda d: d['delivery'].__setitem__('fps', True),
        ):
            self.assert_invalid(mutation)

    def test_description_shortcuts(self):
        for shortcut in ('same-as-previous', 'use-reference', 'Alice', '$ref registry.alice'):
            self.assert_invalid(lambda d: d['scenes'][0]['characters'][0].__setitem__('eyes', shortcut))

    def test_animal_requires_full_description(self):
        self.assert_invalid(lambda d: d['scenes'][2]['characters'][-1].pop('nose_beak'))

    def test_script_and_continuity_gate(self):
        self.assert_invalid(lambda d: d['scenes'][0]['script_tracking'].__setitem__('status', 'draft'))
        self.assert_invalid(lambda d: d['scenes'][1]['continuity'].__setitem__('entry_state', 'A completely unrelated classroom scene'))
        self.assert_invalid(lambda d: d['scenes'][0]['script_tracking'].__setitem__('dialogue_ids', []))

    def test_pinned_library_selections(self):
        self.assert_invalid(lambda d: d['image_style_library'].__setitem__('template_ids', ['invented-template']))
        self.assert_invalid(lambda d: d['image_style_library'].__setitem__('revision', '0' * 40))
        self.assert_invalid(lambda d: d['image_style_library'].__setitem__('styles', ['Imaginary Style']))

    def test_explicit_gaps_policy(self):
        data = example('expanded-education')
        data['scenes'][0]['start'] = 1
        data['delivery']['duration'] = 9
        self.assertTrue(validate_request(data))
        data['timeline_policy']['allow_gaps'] = True
        self.assertEqual([], validate_request(data))

    def test_reference_and_event_invariants(self):
        self.assert_invalid(lambda d: d['reference_policy'].__setitem__('immutable_sources', False))
        self.assert_invalid(lambda d: d['reference_policy']['sheet_requirements'].__setitem__('expressions', ['neutral'] * 6))
        self.assert_invalid(lambda d: d['scenes'][0]['sfx'][0].__setitem__('at', 11))

    def test_malformed_roots_return_errors(self):
        for value in (None, [], 12, {}, {'schema_version': '1.0'}):
            self.assertTrue(validate_request(value))

    def test_compile_has_all_unabridged_fields_and_no_mutation(self):
        data = example()
        before = copy.deepcopy(data)
        artifacts = compile_project(data)
        self.assertEqual(data, before)
        self.assertEqual(6, len(artifacts['VIDEO']))
        for stage in ('IMAGE', 'VIDEO'):
            for request, scene in zip(artifacts[stage], data['scenes']):
                self.assertEqual(request['characters'], scene['characters'])
                prompt_payload = json.loads(request['prompt'].split('\n', 1)[1])
                for actual, expected in zip(prompt_payload['characters'], scene['characters']):
                    for field in CHARACTER_FIELDS:
                        self.assertEqual(expected[field], actual[field])
                for field in ('setting', 'lighting', 'camera', 'action', 'dialogue'):
                    self.assertEqual(scene[field], prompt_payload[field])
                self.assertNotIn('Higgsfield', request['prompt'])
        self.assertFalse(artifacts['EDIT']['final']['render_allowed'])
        data['delivery']['final']['approval_status'] = 'accepted'
        self.assertTrue(compile_project(data)['EDIT']['final']['render_allowed'])

    def test_subshot_self_contained(self):
        data = example('expanded-education')
        scene = data['scenes'][0]
        sub = copy.deepcopy(scene)
        sub['id'] = 'SH01_A'
        scene['subshots'] = [sub]
        output = compile_project(data)
        self.assertEqual('SH01_A', output['VIDEO'][0]['segment_id'])
        self.assertEqual(scene['characters'], output['VIDEO'][0]['characters'])
        sub['characters'][0] = {'id': 'milo'}
        self.assertTrue(validate_request(data))

    def test_adjacent_subshot_continuity_and_parent_boundaries(self):
        self.assertEqual([], validate_request(split_example()))
        mutations = (
            lambda s: s[1]['continuity'].__setitem__('entry_state', 'Milo flies over an unrelated planet'),
            lambda s: s[0]['continuity'].__setitem__('entry_state', 'Milo opens an unrelated door'),
            lambda s: s[1]['continuity'].__setitem__('exit_state', 'Milo disappears into another planet'),
            lambda s: s[1]['continuity'].__setitem__('previous_scene_id', 'wrong_scene'),
            lambda s: s[1]['continuity'].__setitem__('previous_segment_id', 'wrong_segment'),
        )
        for mutate in mutations:
            data = split_example()
            mutate(data['scenes'][0]['subshots'])
            self.assertTrue(validate_request(data))

    def test_audio_edit_preserve_subshot_intents_with_global_offsets(self):
        data = split_example()
        before = copy.deepcopy(data)
        result = compile_project(data)
        self.assertEqual(before, data)
        for stage in ('AUDIO', 'EDIT'):
            segments = result[stage]['segments']
            self.assertEqual(['SH01_A', 'SH01_B'], [s['segment_id'] for s in segments])
            self.assertEqual([0, 4], [s['start'] for s in segments])
            self.assertEqual('SH01', segments[1]['scene_id'])
            self.assertEqual('global_seconds', segments[1]['timing_basis'])
            self.assertEqual(4.3, segments[1]['sfx'][0]['at'])
            self.assertEqual('Second segment quiet bell', segments[1]['sfx'][0]['event'])
            self.assertEqual((4.4, 7), (segments[1]['repeat_cues'][0]['start'], segments[1]['repeat_cues'][0]['end']))
            self.assertEqual((7.7, 8), (segments[1]['transition']['start'], segments[1]['transition']['end']))
            for i, shot in enumerate(data['scenes'][0]['subshots']):
                for field in ('music', 'subtitle', 'script_tracking', 'continuity'):
                    self.assertEqual(shot[field], segments[i][field])
                self.assertEqual(shot['transition']['intent'], segments[i]['transition']['intent'])

    def test_three_view_turnaround_variants(self):
        for views in (['front', 'left', 'right'], ['front', 'left', 'back'], ['front', 'right', 'back']):
            data = example()
            data['reference_policy']['sheet_requirements']['turnaround'] = views
            self.assertEqual([], validate_request(data))

    def test_reuse_cast_skips_alice_mother_character_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = reuse_request(Path(temporary))
            self.assertEqual([], validate_request(data))
            plan = character_generation_plan(data)
            self.assertEqual([], plan['generate'])
            self.assertEqual(
                {'alice': 'alice', 'mother': 'mom-alice'},
                {item['request_character_id']: item['library_character_id']
                 for item in plan['reuse']})
            artifacts = compile_project(data)
            self.assertEqual([], artifacts['character_generation']['generate'])
            self.assertEqual(data['image_engine'], artifacts['IMAGE'][0]['engine'])
            self.assertEqual([], json.loads(
                artifacts['IMAGE'][0]['prompt'].split('\n', 1)[1]
            )['character_generation']['generate'])

    def test_mixed_cast_requires_existing_bindings_and_only_generates_new_character(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = mixed_reuse_request(Path(temporary))
            self.assertEqual([], validate_request(data))
            artifacts = compile_project(data)
            self.assertEqual(['milkmaid'], artifacts['character_generation']['generate'])
            self.assertEqual(
                {'alice': 'alice', 'mother': 'mom-alice'},
                {item['request_character_id']: item['library_character_id']
                 for item in artifacts['character_generation']['reuse']})

            missing = copy.deepcopy(data)
            missing.pop('cast_reuse')
            errors = validate_request(missing)
            self.assertTrue(any('alice' in error and 'complete cast_reuse' in error
                                for error in errors))
            self.assertTrue(any('mother' in error and 'complete cast_reuse' in error
                                for error in errors))

            partial = copy.deepcopy(data)
            partial['cast_reuse']['characters'].pop('mother')
            errors = validate_request(partial)
            self.assertTrue(any('mother' in error and 'complete cast_reuse' in error
                                for error in errors))

    def test_reuse_mapping_rejects_swapped_known_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = reuse_request(Path(temporary))
            data['cast_reuse']['characters'] = {
                'alice': 'mom-alice',
                'mother': 'alice',
            }
            errors = validate_request(data)
            self.assertTrue(any('alice' in error and "expected identity 'alice'" in error
                                for error in errors))
            self.assertTrue(any('mother' in error and "expected identity 'mom-alice'" in error
                                for error in errors))

            legacy = copy.deepcopy(data)
            legacy['image_engine'] = example()['image_engine']
            errors = validate_request(legacy)
            self.assertTrue(any("expected identity 'mom-alice'" in error
                                for error in errors))

    def test_malformed_reuse_records_return_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = reuse_request(root)
            manifest_path = Path(data['cast_reuse']['manifest_path'])
            manifest = json.loads(manifest_path.read_text())
            manifest['characters'][0].pop('canonical_png')
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            data['cast_reuse']['manifest_sha256'] = digest(manifest_path)
            errors = validate_request(data)
            self.assertTrue(any('malformed record; missing canonical_png' in error
                                for error in errors))
            with self.assertRaises(ValueError):
                compile_project(data)

            data = reuse_request(root)
            data['cast_reuse']['characters']['mother'] = ['alice']
            errors = validate_request(data)
            self.assertTrue(any('cast_reuse.characters.mother: expected string' in error
                                for error in errors))
            with self.assertRaises(ValueError):
                compile_project(data)

    def test_expression_manifest_requires_exactly_twelve_unique_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = reuse_request(root)
            manifest_path = Path(data['cast_reuse']['manifest_path'])
            manifest = json.loads(manifest_path.read_text())
            alice_record = manifest['characters'][0]
            expression_path = Path(alice_record['expressions_manifest'])
            expression_manifest = json.loads(expression_path.read_text())
            expression_manifest['icons'].append(
                copy.deepcopy(expression_manifest['icons'][0]))
            expression_path.write_text(json.dumps(expression_manifest), encoding='utf-8')
            alice_record['expressions_manifest_sha256'] = digest(expression_path)
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            data['cast_reuse']['manifest_sha256'] = digest(manifest_path)
            errors = validate_request(data)
            self.assertTrue(any('exactly 12 unique canonical IDs' in error
                                for error in errors))
            with self.assertRaises(ValueError):
                compile_project(data)

    def test_compiled_bindings_preserve_recorded_review_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = reuse_request(Path(temporary))
            artifacts = compile_project(data)
            mother = next(item for item in artifacts['character_generation']['reuse']
                          if item['request_character_id'] == 'mother')
            self.assertEqual('mom-alice recorded fixture status',
                             mother['canonical_approval'])
            self.assertEqual(12, len(mother['expressions']))
            self.assertEqual(
                {'mom-alice reviewed in fixture'},
                {item['review_status'] for item in mother['expressions']})
            self.assertEqual(
                {'mom-alice approval status preserved'},
                {item['user_approval'] for item in mother['expressions']})
            prompt = json.loads(artifacts['IMAGE'][0]['prompt'].split('\n', 1)[1])
            prompt_mother = next(
                item for item in prompt['character_generation']['reuse']
                if item['request_character_id'] == 'mother')
            self.assertEqual(mother, prompt_mother)

    def test_compiler_fails_closed_if_validator_omits_reuse_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = mixed_reuse_request(Path(temporary))
            data.pop('cast_reuse')
            with patch('compile_prompts.validate_request', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'complete cast_reuse'):
                    compile_project(data)

    def test_reuse_hashes_bind_cast_and_canonical_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = reuse_request(root)
            data['cast_reuse']['manifest_sha256'] = '0' * 64
            self.assertTrue(any('cast_reuse.manifest_sha256: hash mismatch' in error
                                for error in validate_request(data)))

            data = reuse_request(root)
            manifest = json.loads(Path(data['cast_reuse']['manifest_path']).read_text())
            expression_manifest = Path(manifest['characters'][0]['expressions_manifest'])
            expression_manifest.write_bytes(b'tampered expression manifest')
            self.assertTrue(any('expression-manifest hash mismatch' in error
                                for error in validate_request(data)))

            data = reuse_request(root)
            manifest = json.loads(Path(data['cast_reuse']['manifest_path']).read_text())
            canonical = Path(manifest['characters'][0]['canonical_png'])
            canonical.write_bytes(b'tampered canonical')
            self.assertTrue(any('canonical hash mismatch' in error
                                for error in validate_request(data)))

    def test_new_character_uses_canonical_twelve_expression_plan(self):
        data = example('expanded-education')
        data['reference_policy']['sheet_requirements'] = {
            'plan_mode': 'canonical-12',
            'turnaround': ['front', 'left', 'right'],
            'expressions': sorted(CANONICAL_EXPRESSIONS),
            'poses': ['scene-specific action references'],
        }
        self.assertEqual([], validate_request(data))
        self.assertEqual(['milo'], compile_project(data)['character_generation']['generate'])
        data['reference_policy']['sheet_requirements']['expressions'] = [
            'happy', 'sad', 'angry', 'surprised', 'afraid', 'neutral']
        self.assertTrue(validate_request(data))

    def test_image_engine_is_explicit_and_never_defaults_to_cloud(self):
        local = example('expanded-education')
        local['image_engine'] = {
            'provider': 'ComfyUI',
            'execution': 'local',
            'model': 'selected-local-checkpoint',
            'profile': 'saved local ComfyUI workflow',
        }
        artifact = compile_project(local)['IMAGE'][0]
        self.assertEqual(local['image_engine'], artifact['engine'])
        self.assertNotEqual('GPT Image2', artifact['engine']['model'])

        missing = example('expanded-education')
        missing.pop('image_engine')
        self.assertTrue(any('image_engine: required' in error
                            for error in validate_request(missing)))
        with self.assertRaises(ValueError):
            compile_project(missing)

        legacy = example('expanded-education')
        self.assertEqual(legacy['image_engine'],
                         compile_project(legacy)['IMAGE'][0]['engine'])

    def test_audio_authority_matches_selected_mode(self):
        data = example()
        for mode, authority in (
                ('canonical_voicestudio', 'VoiceStudio canonical soundtrack'),
                ('preserve_native', 'Accepted native generated soundtrack')):
            data['engine']['audio_mode'] = mode
            audio = compile_project(data)['AUDIO']
            self.assertEqual(mode, audio['selected_mode'])
            self.assertEqual(authority, audio['authority'])
            self.assertIn('complete native audio as immutable source artifacts', audio['native_output_policy'])

    def test_twelve_exact_baseline_lines(self):
        expected = ['Mom, Dad, and me!', "Let's go to the zoo!", 'Look! A little bird.',
                    'Bird. A little bird.', 'I see a giraffe.', 'A tall giraffe!',
                    'Hello, little tiger!', 'Tiger. Hello, tiger!', 'Look! A panda.',
                    'Panda. A hungry panda.', 'Bye-bye, animals!', 'Bye-bye, zoo!']
        self.assertEqual(expected, [x['text'] for s in example()['scenes'] for x in s['dialogue']])


if __name__ == '__main__':
    unittest.main()
