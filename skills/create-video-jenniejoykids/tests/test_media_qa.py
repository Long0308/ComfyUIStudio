"""Regression evidence for delivery coverage and fail-closed report replacement."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'media_qa.py'
SPEC = importlib.util.spec_from_file_location('media_qa', SCRIPT)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class MediaQA(unittest.TestCase):
    def setUp(self):
        self.config = {'file': 'synthetic.mp4', 'expected': {'width': 1280, 'height': 720,
                       'frames': 1440, 'duration': 60}}
        self.info = {'streams': [{'codec_type': 'video', 'width': 1280, 'height': 720,
                      'nb_read_frames': '1440'}, {'codec_type': 'audio', 'duration': '60',
                      'start_time': '0'}], 'format': {'duration': '60'}}
        self.blocks = [(0, 1440000)]

    def fake_command(self, argv, timeout=600):
        stdout, stderr = '', ''
        if '-show_streams' in argv:
            stdout = json.dumps(self.info)
        if 'ashowinfo' in argv:
            stderr = '\n'.join(f'[Parsed_ashowinfo_0] n:0 pts:0 pts_time:{start} '
                               f'fmt:s16 channels:1 rate:24000 nb_samples:{samples}'
                               for start, samples in self.blocks)
        return {'command': argv, 'exit_code': 0, 'stdout': stdout, 'stderr': stderr}

    def inspect(self):
        with patch.object(qa, 'command', side_effect=self.fake_command):
            return qa.inspect(self.config)

    def test_complete_audio_passes_with_artistic_checks_pending(self):
        report = self.inspect()
        self.assertTrue(report['technical_pass'], report)
        self.assertEqual(report['audio_coverage']['decoded_samples'], 1440000)
        self.assertEqual(report['acceptance'], 'pending_artistic_review')
        self.assertEqual(set(report['artistic_review'].values()), {'pending'})

    def test_short_decoded_audio_fails_even_if_metadata_claims_sixty_seconds(self):
        self.blocks = [(0, 24000)]
        self.assertIn('audio does not cover expected timeline', self.inspect()['failures'])

    def test_offset_audio_fails(self):
        self.blocks = [(1, 1440000)]
        self.assertFalse(self.inspect()['technical_pass'])

    def test_internal_audio_gap_fails(self):
        self.blocks = [(0, 24000), (2, 1392000)]
        report = self.inspect()
        self.assertEqual(report['audio_coverage']['end'], 60)
        self.assertEqual(report['audio_coverage']['gaps'], [[1, 2]])
        self.assertFalse(report['technical_pass'])

    def test_missing_audio_metadata_uses_decoded_samples(self):
        self.info['streams'][1] = {'codec_type': 'audio'}
        report = self.inspect()
        self.assertTrue(report['technical_pass'], report)
        self.assertEqual(report['audio_coverage']['method'], 'decoded_ashowinfo')

    def test_unavailable_decode_evidence_fails(self):
        self.blocks = []
        self.assertFalse(self.inspect()['technical_pass'])

    def test_na_frame_count_is_a_failed_report(self):
        self.info['streams'][0]['nb_read_frames'] = 'N/A'
        report = self.inspect()
        self.assertFalse(report['technical_pass'])
        self.assertIn('wrong or unavailable frame count', report['failures'])

    def test_invalid_metadata_is_structured(self):
        for info in [None, [], {}, {'streams': [None]}, {'streams': [], 'format': None}]:
            with self.subTest(info=info):
                self.info = info
                report = self.inspect()
                self.assertFalse(report['technical_pass'])
                self.assertEqual(report['acceptance'], 'failed')

    def test_invalid_probe_json_records_failed_command(self):
        with patch.object(qa, 'command', return_value={'exit_code': 0, 'stdout': '{', 'stderr': ''}):
            report = qa.inspect(self.config)
        self.assertFalse(report['technical_pass'])
        self.assertIn('-show_streams', report['errors'][0]['command'])

    def test_missing_binary_and_timeout_are_structured(self):
        for error in [FileNotFoundError('missing binary'), subprocess.TimeoutExpired(['ffprobe'], 1)]:
            with self.subTest(error=error), patch.object(qa.subprocess, 'run', side_effect=error):
                report = qa.inspect(self.config)
                self.assertFalse(report['technical_pass'])
                self.assertEqual(report['errors'][0]['error_type'], type(error).__name__)
                self.assertEqual(report['errors'][0]['command'][0], 'ffprobe')

    def test_cli_replaces_stale_success_on_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            config, out = Path(directory) / 'request.json', Path(directory) / 'report.json'
            config.write_text(json.dumps(self.config), encoding='utf-8')
            out.write_text('{"technical_pass": true}', encoding='utf-8')
            with patch.object(sys, 'argv', [str(SCRIPT), str(config), '--out', str(out)]), \
                    patch.object(qa.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['ffprobe'], 1)), \
                    patch('builtins.print'), self.assertRaises(SystemExit) as status:
                qa.main()
            self.assertEqual(status.exception.code, 1)
            report = json.loads(out.read_text(encoding='utf-8'))
            self.assertFalse(report['technical_pass'])
            self.assertEqual(report['acceptance'], 'failed')
            self.assertEqual(set(Path(directory).iterdir()), {config, out})

    def test_cli_replaces_stale_success_on_bad_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config, out = Path(directory) / 'request.json', Path(directory) / 'report.json'
            config.write_text('{', encoding='utf-8')
            out.write_text('{"technical_pass": true}', encoding='utf-8')
            with patch.object(sys, 'argv', [str(SCRIPT), str(config), '--out', str(out)]), \
                    patch('builtins.print'), self.assertRaises(SystemExit):
                qa.main()
            self.assertEqual(json.loads(out.read_text())['acceptance'], 'failed')

    def test_cli_replaces_stale_success_on_missing_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            config, out = Path(directory) / 'request.json', Path(directory) / 'report.json'
            request = dict(self.config, ffprobe=str(Path(directory) / 'missing-ffprobe.exe'))
            config.write_text(json.dumps(request), encoding='utf-8')
            out.write_text('{"technical_pass": true}', encoding='utf-8')
            result = subprocess.run([sys.executable, str(SCRIPT), str(config), '--out', str(out)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(report['acceptance'], 'failed')
            self.assertEqual(report['errors'][0]['error_type'], 'FileNotFoundError')
            self.assertEqual(report['file'], str(Path(self.config['file']).resolve()))

    def test_cli_replaces_stale_success_on_bad_probe_metadata(self):
        for stdout in ['{', json.dumps({'streams': [{'codec_type': 'video', 'nb_read_frames': 'N/A'}],
                                       'format': {'duration': '60'}})]:
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as directory:
                config, out = Path(directory) / 'request.json', Path(directory) / 'report.json'
                config.write_text(json.dumps(self.config), encoding='utf-8')
                out.write_text('{"technical_pass": true}', encoding='utf-8')
                result = {'exit_code': 0, 'stdout': stdout, 'stderr': ''}
                with patch.object(sys, 'argv', [str(SCRIPT), str(config), '--out', str(out)]), \
                        patch.object(qa, 'command', return_value=result), patch('builtins.print'), \
                        self.assertRaises(SystemExit) as status:
                    qa.main()
                self.assertEqual(status.exception.code, 1)
                self.assertEqual(json.loads(out.read_text())['acceptance'], 'failed')

    def test_optional_canonical_checks_hash_samples_and_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, stem = root / 'line.wav', root / 'stem.wav'
            payload = b'\x01\x00' * 800
            for path, pcm in [(source, payload), (stem, b'\0' * 1600 + payload + b'\0' * 14400)]:
                with wave.open(str(path), 'wb') as handle:
                    handle.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    handle.writeframes(pcm)
            provenance = root / 'placements.json'
            entries = [{'source': 'line.wav', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'duration': .1, 'global_start': .1}]
            provenance.write_text(json.dumps(entries))
            spec = {'file': str(stem), 'provenance': str(provenance)}
            self.assertEqual(qa.check_canonical(spec, 1.1)['verified_placements'], 1)
            with self.assertRaisesRegex(ValueError, 'sample count'):
                qa.check_canonical(spec, 60)
            entries[0]['global_start'] = .2
            provenance.write_text(json.dumps(entries))
            with self.assertRaisesRegex(ValueError, 'PCM mismatch'):
                qa.check_canonical(spec, 1.1)
            entries[0]['sha256'] = 'wrong'
            provenance.write_text(json.dumps(entries))
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                qa.check_canonical(spec, 1.1)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools unavailable')
class FFmpegIntegration(unittest.TestCase):
    def test_sixty_second_video_with_full_truncated_and_delayed_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            for label, offset, length, passes in [('full', 0, 60, True), ('short', 0, 1, False),
                                                   ('delayed', 1, 59, False)]:
                with self.subTest(label=label):
                    media = Path(directory) / f'{label}.mkv'
                    argv = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=32x32:r=2:d=60',
                            '-itsoffset', str(offset), '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=24000:duration={length}',
                            '-c:v', 'ffv1', '-c:a', 'pcm_s16le', '-y', str(media)]
                    subprocess.run(argv, check=True, capture_output=True, timeout=60)
                    report = qa.inspect({'file': str(media), 'expected': {'width': 32, 'height': 32,
                                         'frames': 120, 'duration': 60}})
                    self.assertEqual(report['technical_pass'], passes, report['failures'])
                    self.assertAlmostEqual(report['audio_coverage']['start'], offset, places=2)
                    self.assertAlmostEqual(report['audio_coverage']['end'], offset + length, places=2)


if __name__ == '__main__':
    unittest.main()
