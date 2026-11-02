"""Finishing contract tests; mocked rendering never submits GPU or H3 jobs."""
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from http.server import ThreadingHTTPServer
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import finish_ui
import prepare_edit


def film_data():
    return {'duration': 3.06, 'fps': 24, 'mix': 'audio.wav',
            'clips': [{'id': str(i), 'file': f'{i}.mp4', 'start': i * 1.02, 'duration': 1.02} for i in range(3)],
            'dialogue': [{'id': 'line', 'text': 'Hello', 'start': .2, 'end': .8}],
            'repeat_cues': [], 'brand_events': [],
            'final_approval': {'accepted': False, 'preview_sha256': '', 'accepted_at': ''}}


class TimelineTests(unittest.TestCase):
    def test_absolute_boundaries_cover_former_rounding_gap(self):
        film = film_data()
        prepare_edit.validate_film(film)
        starts = [prepare_edit.frame(c['start'], 24) for c in film['clips']]
        ends = [prepare_edit.frame(c['start'] + c['duration'], 24) for c in film['clips']]
        self.assertEqual(starts, [0, 24, 49])
        self.assertEqual([b - a for a, b in zip(starts, ends)], [24, 25, 24])
        self.assertEqual(ends[:-1], starts[1:])

    def test_rejects_zero_frame_clip_and_gap(self):
        for mutate in (lambda f: f['clips'][0].update(duration=.001),
                       lambda f: f['clips'][1].update(start=1.04)):
            film = film_data()
            mutate(film)
            with self.assertRaises(ValueError):
                prepare_edit.validate_film(film)

    def test_rejects_zero_frame_caption(self):
        film = film_data()
        film['dialogue'][0].update(start=.1, end=.101)
        with self.assertRaisesRegex(ValueError, 'zero-frame'):
            prepare_edit.validate_film(film)

    def test_brand_must_be_dialogue_free_after_quantization(self):
        film = film_data()
        film['brand_events'] = [{'file': 'brand.mp4', 'start': 0, 'end': .21}]
        prepare_edit.validate_film(film)  # Both boundaries quantize to frame 5.
        film['brand_events'][0]['end'] = .24
        with self.assertRaisesRegex(ValueError, 'dialogue-free'):
            prepare_edit.validate_film(film)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        (self.project / 'src').mkdir()
        (self.project / 'public').mkdir()
        (self.project / 'remotion.config.ts').write_text('// fixture')
        film = film_data()
        prepare_edit.write_json(self.project / 'src' / 'film.json', film)
        for relative in ['audio.wav', '0.mp4', '1.mp4', '2.mp4']:
            (self.project / 'public' / relative).write_bytes(b'test fixture: never rendered')
        self.f = finish_ui.Finisher({'project_dir': str(self.project),
                                    'runtime': {k: sys.executable for k in ('node', 'renderer_cli', 'ffmpeg', 'ffprobe')},
                                    'comfy_url': 'http://127.0.0.1:8188'})

    def ready(self):
        self.f.preview.parent.mkdir()
        self.f.preview.write_bytes(b'mocked MP4: not media acceptance')
        self.f.state = {'draft_complete': True, 'qa': {'technical_pass': True},
                        'preview_sha256': prepare_edit.digest(self.f.preview), 'binding_sha256': self.f.binding()}

    def test_missing_failed_or_mutated_preview_cannot_approve(self):
        with self.assertRaises(ValueError):
            self.f.action('approve', '')
        self.ready()
        self.assertTrue(self.f.eligible())
        self.f.state['qa']['technical_pass'] = False
        self.assertFalse(self.f.eligible())
        self.f.state['qa']['technical_pass'] = True
        self.f.preview.write_bytes(b'changed')
        self.assertFalse(self.f.eligible())

    def test_source_or_render_code_change_invalidates_gate(self):
        self.ready()
        (self.project / 'public' / '0.mp4').write_bytes(b'changed source')
        self.assertFalse(self.f.eligible())
        self.f.state['binding_sha256'] = self.f.binding()
        (self.project / 'src' / 'Film.tsx').write_text('// changed renderer')
        self.assertFalse(self.f.eligible())

    def test_explicit_hash_acceptance_records_utc_and_starts_one_job(self):
        self.ready()
        with patch.object(self.f, 'queue_idle'), patch('finish_ui.threading.Thread') as thread:
            with self.assertRaises(ValueError):
                self.f.action('approve', 'wrong hash')
            self.f.action('approve', self.f.state['preview_sha256'])
            approval = self.f.film()['final_approval']
            self.assertTrue(approval['accepted'])
            self.assertTrue(approval['accepted_at'].endswith('+00:00'))
            self.assertEqual(approval['preview_sha256'], prepare_edit.digest(self.f.preview))
            thread.return_value.start.assert_called_once()
            with self.assertRaisesRegex(ValueError, 'already running'):
                self.f.action('draft')
        self.f.busy = False
        with self.assertRaisesRegex(ValueError, 'already accepted'):
            self.f.action('approve', self.f.state['preview_sha256'])

    def test_busy_comfy_prevents_acceptance(self):
        self.ready()
        with patch.object(self.f, 'queue_idle', side_effect=ValueError('Comfy busy')):
            with self.assertRaisesRegex(ValueError, 'busy'):
                self.f.action('approve', self.f.state['preview_sha256'])
        self.assertFalse(self.f.film()['final_approval']['accepted'])

    def test_source_change_during_queue_check_cannot_accept_old_preview(self):
        self.ready()
        old_hash = self.f.state['preview_sha256']
        def changed_source():
            (self.project / 'public' / '0.mp4').write_bytes(b'changed while queue request blocks')
        with patch.object(self.f, 'queue_idle', side_effect=changed_source), patch('finish_ui.threading.Thread') as thread:
            with self.assertRaisesRegex(ValueError, 'changed while checking'):
                self.f.action('approve', old_hash)
            thread.assert_not_called()
        self.assertFalse(self.f.film()['final_approval']['accepted'])
        self.assertNotIn('approval', self.f.state)

    def test_final_worker_rejects_change_during_second_queue_wait(self):
        self.ready()
        binding = self.f.state['binding_sha256']
        def changed_source():
            (self.project / 'public' / '0.mp4').write_bytes(b'changed before launch')
        with patch.object(self.f, 'queue_idle', side_effect=changed_source), patch.object(self.f, 'run') as run:
            self.f.worker('approve', binding)
            run.assert_not_called()
        self.assertIn('changed before rendering', self.f.state['last_error'])

    def test_local_http_serves_only_known_paths_and_rejects_foreign_posts(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), finish_ui.handler(self.f, 'http://127.0.0.1:1'))
        origin = f'http://127.0.0.1:{server.server_port}'
        server.RequestHandlerClass = finish_ui.handler(self.f, origin)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with urlopen(origin + '/') as response:
                html = response.read().decode()
                self.assertIn('Tạo bản nháp 720p', html)
                self.assertIn('Duyệt và render 1080p', html)
            with urlopen(origin + '/status') as response:
                self.assertFalse(json.load(response)['can_approve'])
            with self.assertRaises(HTTPError) as error:
                urlopen(origin + '/../../src/film.json')
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
            request = Request(origin + '/approve', data=b'{}', method='POST',
                              headers={'Origin': 'http://evil.example', 'Content-Type': 'application/json',
                                       'X-Finish-Token': self.f.token})
            with patch.object(self.f, 'action') as action:
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                action.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_short_decoded_audio_fails_even_if_probe_duration_claims_full_length(self):
        probe = {'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720, 'nb_read_frames': '73', 'avg_frame_rate': '24/1'},
                             {'codec_type': 'audio', 'duration': '3.06', 'start_time': '0'}], 'format': {'duration': '3.06'}}
        with patch.object(self.f, 'run', side_effect=[json.dumps(probe), '']), \
                patch('finish_ui.subprocess.run') as command:
            command.return_value.returncode = 0
            command.return_value.stderr = '[Parsed_ashowinfo] pts_time:0 rate:48000 nb_samples:48000'
            with self.assertRaisesRegex(ValueError, 'decoded audio does not cover'):
                self.f.qa(self.project / 'mock.mp4', 1280, 720)

    def test_prepare_rejects_missing_clip_or_mix_and_baseline(self):
        request = self.project / 'request.json'
        request.write_text('{}')
        settings = {'production_request': str(request), 'accepted_clips': [], 'canonical_mix': str(self.project / 'missing.wav')}
        segments = [{'segment_id': 'S01', 'start': 0, 'duration': 1}]
        with patch('prepare_edit.compile_project', return_value={'EDIT': {'segments': segments}}):
            with self.assertRaisesRegex(ValueError, 'Exactly one'):
                prepare_edit.prepare(settings)
            settings['accepted_clips'] = [{'segment_id': 'S01', 'accepted': True, 'engine': 'baseline', 'file': sys.executable}]
            with self.assertRaisesRegex(ValueError, 'baseline substitution'):
                prepare_edit.prepare(settings)
            settings['accepted_clips'][0]['engine'] = 'native_h3'
            with self.assertRaisesRegex(ValueError, 'existing absolute file'):
                prepare_edit.prepare(settings)


class ProductionScriptTests(unittest.TestCase):
    @staticmethod
    def load_script(name):
        path = Path('D:/23.JennieHomeSchool/03 Voice/production-local') / (name + '.py')
        if not path.is_file():
            raise unittest.SkipTest('Commissioning workspace scripts are unavailable on this machine')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_audio_rerun_preserves_existing_stems_final_and_provenance(self):
        audio = self.load_script('prepare_audio')
        for final_payload in (b'complete prior final', b'partial WAV'):
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder) / 'version-01'
                output.mkdir()
                originals = {'final-mix.wav': final_payload, 'music-original.wav': b'old music',
                             'soundtrack-provenance.json': b'old provenance'}
                for name, payload in originals.items():
                    (output / name).write_bytes(payload)
                config = Path(folder) / 'config.json'
                config.write_text(json.dumps({'output': str(output), 'production_request': 'changed-or-missing-input.json'}))
                with patch.object(sys, 'argv', ['prepare_audio.py', str(config)]), patch.object(audio, 'pcm') as pcm:
                    with self.assertRaisesRegex(ValueError, 'new versioned'):
                        audio.main()
                    pcm.assert_not_called()
                self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, originals)

    def test_monitor_success_and_failed_terminal_histories(self):
        monitor = self.load_script('monitor_job')
        for succeeded in (False, True):
            with self.subTest(succeeded=succeeded), tempfile.TemporaryDirectory() as folder:
                history = {'test-prompt': {'status': {'status_str': 'success' if succeeded else 'error',
                           'completed': succeeded, 'messages': [] if succeeded else [['execution_error', {'exception_message': 'OOM'}]]}}}
                with patch.object(monitor.subprocess, 'check_output', return_value='1024, 8192, 0'), \
                        patch.object(monitor.urllib.request, 'urlopen'), patch.object(monitor.json, 'load', return_value=history):
                    config = {'output': folder, 'comfy_url': 'http://127.0.0.1:8188', 'prompt_id': 'test-prompt'}
                    if succeeded:
                        monitor.main(config)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'without verified successful'):
                            monitor.main(config)
                metrics = json.loads((Path(folder) / 'metrics.json').read_text())
                self.assertTrue(metrics['terminal'])
                self.assertEqual(metrics['success'], succeeded)
                self.assertEqual(metrics['complete'], succeeded)
                self.assertEqual(json.loads((Path(folder) / 'history.json').read_text()), history)


if __name__ == '__main__':
    unittest.main()
