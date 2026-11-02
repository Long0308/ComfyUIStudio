import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from validate_motion_plan import validate_motion_plan

class MotionTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((ROOT / 'tests/fixtures/motion-graphics.json').read_text(encoding='utf-8-sig'))

    def test_valid_creative_proposal(self):
        self.assertEqual(validate_motion_plan(self.plan), [])
        example = json.loads((ROOT / 'examples/motion-zoo-entry.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(validate_motion_plan(example), [])

    def test_24fps_local_global_and_rounding(self):
        shot = self.plan['shots'][0]
        shot['start_seconds'] = 2
        event = shot['events'][0]
        event.update(start_seconds=.1875, expected_local_start_frame=5, expected_global_start_frame=53)
        self.assertEqual(validate_motion_plan(self.plan), [])
        event['expected_local_start_frame'] = 6
        self.assertTrue(any('expected_local_start_frame' in e for e in validate_motion_plan(self.plan)))

    def test_30fps_is_not_hardcoded(self):
        self.plan['delivery']['fps'] = 30
        event = self.plan['shots'][0]['events'][0]
        event['expected_local_end_frame'] = 30
        self.assertEqual(validate_motion_plan(self.plan), [])
        event['expected_local_end_frame'] = 24
        self.assertTrue(validate_motion_plan(self.plan))

    def test_invalid_box_opacity(self):
        motion = self.plan['shots'][0]['events'][0]['motion']
        motion['start_box']['width'] = -1
        motion['opacity_end'] = 1.1
        errors = validate_motion_plan(self.plan)
        self.assertTrue(any('width' in e for e in errors))
        self.assertTrue(any('opacity_end' in e for e in errors))

    def test_shorthand_and_font(self):
        self.plan['shots'][0]['characters'][0]['eyes'] = 'same as previous'
        self.assertTrue(any('shortcut' in e for e in validate_motion_plan(self.plan)))
        self.plan['shots'][0]['characters'][0]['eyes'] = 'Large warm brown eyes with white highlights.'
        del self.plan['shots'][0]['layout']['font']
        self.assertTrue(any('font' in e for e in validate_motion_plan(self.plan)))

    def test_measurement_needs_source(self):
        self.plan['shots'][0]['events'][0]['motion']['evidence'] = 'measured'
        self.assertTrue(any('measured' in e for e in validate_motion_plan(self.plan)))

    def test_audio_hit_alignment(self):
        self.plan['shots'][0]['audio_cues'] = [dict(event_id='enter', source_file='cue.wav', source_transient_seconds=.2, source_duration_seconds=1, timeline_hit_seconds=.5, classification='planned_sfx', offset_seconds=.3)]
        self.assertEqual(validate_motion_plan(self.plan), [])
        self.plan['shots'][0]['audio_cues'][0]['offset_seconds'] = .4
        self.assertTrue(any('alignment' in e for e in validate_motion_plan(self.plan)))
        cue=self.plan['shots'][0]['audio_cues'][0]
        cue.update(timeline_hit_seconds=4.5, offset_seconds=4.3)
        self.assertTrue(any('linked event' in e for e in validate_motion_plan(self.plan)))

    def test_vfr_uses_recorded_pts(self):
        self.plan['sources'] = [dict(id='ref',file='ref.mp4',sha256='a'*64,width=320,height=180,fps_num=30,fps_den=1,duration_seconds=1,frame_count=3,variable_frame_rate=True,frame_pts_seconds=[0,.04,.11])]
        shot=self.plan['shots'][0]
        shot['reference_source_id']='ref'
        shot['source_events']=[dict(id='hit',classification='visual_estimate',frame_index=2,timestamp_seconds=.11)]
        self.assertEqual(validate_motion_plan(self.plan), [])
        shot['source_events'][0]['timestamp_seconds']=2/30
        self.assertTrue(any('PTS' in e for e in validate_motion_plan(self.plan)))

    def test_source_fps_separate_from_export_and_invalid_pts(self):
        self.plan['sources'] = [dict(id='ref',file='ref.mp4',sha256='a'*64,width=320,height=180,fps_num=30,fps_den=1,duration_seconds=1,frame_count=30)]
        shot=self.plan['shots'][0]
        shot['reference_source_id']='ref'
        shot['source_events']=[dict(id='hit',classification='measured',frame_index=15,timestamp_seconds=.5)]
        self.assertEqual(validate_motion_plan(self.plan), [])
        shot['source_events'][0]['timestamp_seconds']=15/24
        self.assertTrue(any('source FPS' in e for e in validate_motion_plan(self.plan)))
        self.plan['sources'][0]['frame_pts_seconds']=[0]
        self.assertTrue(any('PTS' in e for e in validate_motion_plan(self.plan)))

    def test_cli_returns_nonzero_invalid_and_review_needs_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            target=pathlib.Path(directory)/'invalid.json'; target.write_text('{}',encoding='utf-8')
            result=subprocess.run([sys.executable,str(ROOT/'scripts/validate_motion_plan.py'),str(target)],capture_output=True)
            self.assertNotEqual(result.returncode,0)
        self.plan['shots'][0]['review']['status']='reviewed'
        self.assertTrue(any('verified font' in e for e in validate_motion_plan(self.plan)))

    def test_malformed_inputs_return_errors(self):
        self.plan['delivery']['width'] = 10**400
        self.assertTrue(validate_motion_plan(self.plan))
        for value in (None, [], {}, {'schema_version':float('nan')}):
            self.assertTrue(validate_motion_plan(value))

    def test_analysis_rejects_existing_output(self):
        from analyze_reference import analyze_reference
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'source.mp4';source.write_bytes(b'fixture')
            with self.assertRaises(ValueError):
                analyze_reference(dict(source_file=str(source),output_dir=directory,windows=[]))

    def test_missing_evidence_and_insufficient_hold(self):
        del self.plan['shots'][0]['events'][0]['motion']['evidence']
        self.assertTrue(any('evidence' in e for e in validate_motion_plan(self.plan)))
        self.setUp()
        self.plan['shots'][0]['review']['minimum_reading_hold_seconds'] = 5
        self.assertTrue(any('reading hold' in e for e in validate_motion_plan(self.plan)))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local ffmpeg/ffprobe unavailable')
    def test_tiny_reference_extraction_actual_pts_and_no_overwrite(self):
        from analyze_reference import analyze_reference
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            source=root/'tiny.mp4'
            subprocess.run(['ffmpeg','-v','error','-nostdin','-n','-f','lavfi','-i','color=c=blue:s=64x36:r=12:d=1','-vf','setpts=PTS+2/TB','-fps_mode','passthrough','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True)
            config=dict(source_file=str(source),output_dir=str(root/'analysis'),windows=[dict(label='entry',start_frame=3,end_frame=5)])
            manifest=analyze_reference(config)
            self.assertEqual(manifest['source']['frame_count'],12)
            self.assertEqual(manifest['source']['width'],64)
            self.assertEqual(manifest['source']['start_pts_seconds'],2)
            self.plan['sources']=[manifest['source']]
            self.plan['shots'][0]['reference_source_id']=manifest['source']['id']
            self.plan['shots'][0]['source_events']=[dict(id='shifted',classification='measured',frame_index=3,timestamp_seconds=2.25)]
            self.assertEqual(validate_motion_plan(self.plan), [])
            window=[item for item in manifest['images'] if 'entry' in item['windows']]
            self.assertEqual([item['source_frame_index'] for item in window],[3,4,5])
            for item in manifest['images']:
                self.assertTrue((root/'analysis'/item['file']).is_file())
                self.assertEqual(item['source_pts_seconds'],manifest['source']['frame_pts_seconds'][item['source_frame_index']])
            with self.assertRaises(ValueError):
                analyze_reference(config)
            config['output_dir']=str(root/'invalid')
            config['windows'][0]['end_frame']=12
            with self.assertRaises(ValueError):
                analyze_reference(config)
            self.assertFalse((root/'invalid').exists())

if __name__ == '__main__':
    unittest.main()
