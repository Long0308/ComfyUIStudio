"""Collect FFmpeg technical evidence from a JSON request; artistic gates stay pending."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import wave


def command(argv, timeout=600):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        return {'command': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'command': argv, 'exit_code': -1, 'stdout': '', 'stderr': str(exc),
                'error_type': type(exc).__name__}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def failed_report(source=None):
    return {'schema_version': '1.1', 'file': source, 'failures': [], 'errors': [],
            'technical_pass': False, 'acceptance': 'failed',
            'artistic_review': {k: 'pending' for k in ['character_identity', 'setting_continuity',
                'acting_and_foot_contact', 'lighting_and_palette', 'voice_identity', 'pronunciation',
                'lip_sync', 'music_sfx_balance', 'encoded_subtitles', 'transition_motivation']}}


def check_canonical(spec, expected_duration):
    """Verify source file hashes and exact source PCM at every declared placement."""
    stem = Path(spec['file']).resolve()
    provenance = Path(spec['provenance']).resolve()
    entries = json.loads(provenance.read_text(encoding='utf-8-sig'))
    if not isinstance(entries, list) or not entries:
        raise ValueError('canonical provenance must contain placements')
    with wave.open(str(stem), 'rb') as wav:
        rate, channels, width, frames = wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()
        pcm = wav.readframes(frames)
    if len(pcm) != frames * channels * width:
        raise ValueError('canonical WAV payload is truncated')
    if expected_duration is None or frames != round(expected_duration * rate):
        raise ValueError('canonical WAV has wrong sample count')
    intervals = []
    for entry in entries:
        source = Path(entry['source'])
        if not source.is_absolute():
            source = provenance.parent / source
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f"canonical source hash mismatch: {entry['source']}")
        with wave.open(str(source), 'rb') as wav:
            count = wav.getnframes()
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (rate, channels, width):
                raise ValueError('canonical source PCM format mismatch')
            payload = wav.readframes(count)
        duration, start = number(entry['duration']), number(entry['global_start'])
        if duration is None or start is None or start < 0 or abs(duration * rate - count) > 1:
            raise ValueError('invalid canonical placement metadata')
        offset = round(start * rate)
        end = offset + count
        if end > frames or any(offset < old_end and end > old_start for old_start, old_end in intervals):
            raise ValueError('canonical placement out of range or overlapping')
        intervals.append((offset, end))
        if len(payload) != count * channels * width or pcm[offset * channels * width:end * channels * width] != payload:
            raise ValueError('canonical placement PCM mismatch')
    return {'file': str(stem), 'provenance': str(provenance), 'samples': frames,
            'sample_rate': rate, 'verified_placements': len(entries)}


def inspect(config):
    report = failed_report()
    current_command = None
    try:
        source = str(Path(config['file']).resolve())
        report['file'] = source
        ffprobe, ffmpeg = config.get('ffprobe', 'ffprobe'), config.get('ffmpeg', 'ffmpeg')

        def run(argv):
            nonlocal current_command
            current_command = argv
            result = command(argv)
            if result['exit_code']:
                report['errors'].append(result)
                raise ValueError('media process failed')
            return result

        probe = run([ffprobe, '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', source])
        info = json.loads(probe['stdout'])
        report['probe'] = info
        if not isinstance(info, dict) or not isinstance(info.get('streams'), list):
            raise ValueError('probe must contain a streams array')
        videos = [s for s in info['streams'] if s['codec_type'] == 'video']
        audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
        failures = report['failures']
        expected = config.get('expected', {})
        duration = number(expected.get('duration'))
        if 'duration' in expected and (duration is None or duration <= 0):
            raise ValueError('expected duration must be finite and positive')
        if not videos:
            failures.append('missing video')
        if not audio and config.get('require_audio', True):
            failures.append('missing audio')
        if videos:
            for field in ['width', 'height']:
                if field in expected and videos[0].get(field) != expected[field]:
                    failures.append(f'wrong {field}')
            if 'frames' in expected:
                count = number(videos[0].get('nb_read_frames'))
                if count is None or count != expected['frames']:
                    failures.append('wrong or unavailable frame count')
            if duration is not None:
                actual = number(info.get('format', {}).get('duration'))
                if actual is None or abs(actual - duration) > .06:
                    failures.append('wrong or unavailable duration')
        report['strict_decode'] = run([ffmpeg, '-v', 'error', '-xerror', '-i', source,
            '-map', '0:v?', '-map', '0:a?', '-f', 'null', '-'])
        logs = report['measurements'] = {}
        if videos:
            logs['picture'] = run([ffmpeg, '-hide_banner', '-i', source, '-an', '-vf',
                'signalstats,metadata=print,blackdetect=d=0.1:pix_th=0.08,freezedetect=n=-55dB:d=1.5', '-f', 'null', '-'])
        if audio:
            logs['loudness'] = run([ffmpeg, '-hide_banner', '-i', source, '-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'])
            if duration is not None:
                # Observe decoded samples even when stream duration/rate is unavailable.
                # copyts preserves delayed timestamps instead of normalizing them to zero.
                measured = run([ffmpeg, '-hide_banner', '-v', 'info', '-xerror', '-copyts', '-i', source,
                    '-map', '0:a:0', '-vn', '-af', 'ashowinfo', '-f', 'null', '-'])
                logs['audio_decode'] = measured
                blocks = []
                for line in measured['stderr'].splitlines():
                    if 'ashowinfo' not in line:
                        continue
                    match = re.search(r'pts_time:(\S+).*?rate:(\d+).*?nb_samples:(\d+)', line)
                    if match:
                        start = number(match[1])
                        rate, samples = int(match[2]), int(match[3])
                        if start is not None and rate > 0 and samples > 0:
                            blocks.append((start, start + samples / rate, samples, rate))
                if not blocks:
                    failures.append('decoded audio coverage unavailable')
                else:
                    timeline_start = number(expected.get('start_time', 0))
                    if timeline_start is None:
                        raise ValueError('expected start_time must be finite')
                    ordered = sorted(blocks)
                    start, end = ordered[0][0], max(b[1] for b in ordered)
                    covered_end = ordered[0][1]
                    gaps = []
                    for block in ordered[1:]:
                        if block[0] - covered_end > .06:
                            gaps.append([covered_end, block[0]])
                        covered_end = max(covered_end, block[1])
                    report['audio_coverage'] = {'start': start, 'end': end, 'decoded_samples': sum(b[2] for b in blocks),
                        'gaps': gaps, 'method': 'decoded_ashowinfo',
                        'stream_start': audio[0].get('start_time'), 'stream_duration': audio[0].get('duration')}
                    if abs(start - timeline_start) > .06 or abs(end - (timeline_start + duration)) > .06 or gaps:
                        failures.append('audio does not cover expected timeline')
        if 'canonical_audio' in config:
            report['canonical_audio'] = check_canonical(config['canonical_audio'], duration)
        report['technical_pass'] = not failures
        report['acceptance'] = 'pending_artistic_review' if not failures else 'failed'
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, EOFError,
            wave.Error, subprocess.TimeoutExpired) as exc:
        report['failures'].append(f'{type(exc).__name__}: {exc}')
        report['errors'].append({'command': current_command, 'error_type': type(exc).__name__, 'error': str(exc)})
    return report


def write_report(path, report):
    """Replace the prior artifact only after a complete JSON report reaches disk."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        report = inspect(config)
    except (OSError, ValueError, TypeError) as exc:
        report = failed_report()
        report['failures'].append(f'{type(exc).__name__}: {exc}')
        report['errors'].append({'command': None, 'error_type': type(exc).__name__, 'error': str(exc)})
    write_report(args.out, report)
    print(json.dumps({'technical_pass': report['technical_pass'], 'report': str(args.out)}))
    raise SystemExit(0 if report['technical_pass'] else 1)


if __name__ == '__main__':
    main()
