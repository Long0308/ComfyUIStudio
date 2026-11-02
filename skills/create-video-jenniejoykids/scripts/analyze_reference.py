"""Pin a local video, record decoded PTS and extract source-coordinate PNG evidence.

No visual measurements are inferred. Config is JSON with source_file, output_dir,
fps_overview (default 2), windows [{label,start_frame,end_frame}] (inclusive),
and optional ffmpeg / ffprobe executable paths. Output directory must not exist.
"""
import argparse
import bisect
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path


def _run(argv):
    return subprocess.run(argv, shell=False, check=True, capture_output=True, text=True, encoding='utf-8')


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def analyze_reference(config):
    """Create a fresh evidence directory; return the recorded manifest."""
    if not isinstance(config, dict):
        raise ValueError('config must be an object')
    source = Path(config['source_file']).expanduser().resolve(strict=True)
    output = Path(config['output_dir']).expanduser().resolve()
    if not source.is_file() or output.exists() or output == source or source in output.parents:
        raise ValueError('source must be a file; output must be a fresh directory')
    rate = config.get('fps_overview', 2)
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0 or rate > 60:
        raise ValueError('fps_overview must be > 0 and <= 60')
    windows = config.get('windows', [])
    if not isinstance(windows, list):
        raise ValueError('windows must be an array')
    labels = set()
    for window in windows:
        if not isinstance(window, dict) or not isinstance(window.get('label'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', window['label']):
            raise ValueError('window label must be a safe ASCII filename component')
        if window['label'].casefold() in labels:
            raise ValueError('duplicate window label')
        labels.add(window['label'].casefold())
        for key in ('start_frame', 'end_frame'):
            if isinstance(window.get(key), bool) or not isinstance(window.get(key), int) or window[key] < 0:
                raise ValueError('window frame indices must be nonnegative integers')
        if window['end_frame'] < window['start_frame']:
            raise ValueError('window end_frame precedes start_frame')
    ffprobe, ffmpeg = str(config.get('ffprobe', 'ffprobe')), str(config.get('ffmpeg', 'ffmpeg'))
    before_hash = _hash(source)
    probe = json.loads(_run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_format', '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time,pts_time,pkt_duration_time:stream:format', '-of', 'json', str(source)]).stdout)
    streams = probe.get('streams', [])
    if not streams:
        raise ValueError('source has no video stream')
    stream = streams[0]
    frames = probe.get('frames', [])
    pts = []
    for frame in frames:
        value = frame.get('best_effort_timestamp_time', frame.get('pts_time'))
        if value is None or not math.isfinite(float(value)):
            raise ValueError('every decoded frame must have a finite recorded PTS')
        pts.append(float(value))
    if not pts or any(a >= b for a, b in zip(pts, pts[1:])):
        raise ValueError('decoded frame PTS must be strictly increasing')
    for window in windows:
        if window['end_frame'] >= len(pts):
            raise ValueError('window exceeds actual decoded source frame count')
    numerator, denominator = map(int, stream['avg_frame_rate'].split('/'))
    if numerator <= 0 or denominator <= 0:
        raise ValueError('source needs a positive reported average frame rate')
    duration = float(stream.get('duration', probe.get('format', {}).get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('source needs a positive duration')
    overview = set()
    target = pts[0]
    while target <= pts[-1] + 1e-9:
        pos = bisect.bisect_left(pts, target)
        candidates = [x for x in (pos - 1, pos) if 0 <= x < len(pts)]
        overview.add(min(candidates, key=lambda index: (abs(pts[index] - target), index)))
        target += 1 / rate
    selected = set(overview)
    for window in windows:
        selected.update(range(window['start_frame'], window['end_frame'] + 1))
    # mkdir(exist_ok=False) also protects against a directory created after validation.
    output.mkdir(parents=True, exist_ok=False)
    images = output / 'frames'
    images.mkdir()
    mappings = []
    indices = sorted(selected)
    # Chunk exact selectors; short paths plus 150 terms stay well below Windows limits.
    for chunk_start in range(0, len(indices), 150):
        chunk = indices[chunk_start:chunk_start + 150]
        expression = '+'.join(f'eq(n\\,{index})' for index in chunk)
        pattern = images / f'chunk-{chunk_start:06d}-%06d.png'
        _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-noautorotate', '-i', str(source), '-map', '0:v:0', '-vf', 'select=' + expression, '-fps_mode', 'passthrough', '-start_number', '0', '-threads', '1', str(pattern)])
        for ordinal, index in enumerate(chunk):
            png = images / f'chunk-{chunk_start:06d}-{ordinal:06d}.png'
            if not png.is_file():
                raise ValueError(f'missing extracted frame {index}')
            destination = images / f'source-{index:08d}.png'
            png.rename(destination)
            mappings.append(dict(file=str(destination.relative_to(output)).replace('\\', '/'),source_frame_index=index,source_pts_seconds=pts[index],overview=index in overview,windows=[window['label'] for window in windows if window['start_frame'] <= index <= window['end_frame']]))
    if _hash(source) != before_hash:
        raise ValueError('source changed during analysis; output is incomplete evidence')
    intervals = [b - a for a, b in zip(pts, pts[1:])]
    variable = bool(intervals and max(intervals) - min(intervals) > .0001)
    manifest = dict(schema_version='1.0',source=dict(id=source.stem,file=str(source),sha256=before_hash,width=stream['width'],height=stream['height'],fps_num=numerator,fps_den=denominator,duration_seconds=duration,frame_count=len(pts),start_pts_seconds=pts[0],frame_pts_seconds=pts,variable_frame_rate=variable),coordinate_space='original_coded_source_pixels',autorotation_applied=False,rotation_metadata=dict(tags=stream.get('tags', {}),side_data_list=stream.get('side_data_list', [])),fps_overview=rate,windows=windows,images=mappings,visual_annotations_status='pending',ffprobe=probe)
    (output / 'reference-analysis.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    (output / 'REFERENCE.md').write_text('# Reference evidence\n\nMeasured metadata: SHA-256, coded dimensions, reported average FPS, decoded frame count and actual decoded frame PTS are in reference-analysis.json. PNGs use original coded coordinates; autorotation is disabled. Rotation metadata is retained.\n\nOverview selections use nearest recorded PTS. Window endpoints are inclusive source frame indices. Each image maps to its actual source index and PTS; extraction does not establish visual inspection.\n\nPending visual annotations: inspect the PNGs before describing bounding boxes, opacity, scale, overshoot, motion phases or audio transients. None is inferred by this tool. Voice identity and listening acceptance require separate human review.\n',encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    args = parser.parse_args()
    try:
        result = analyze_reference(json.loads(args.config.read_text(encoding='utf-8-sig')))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Reference analysis failed: {exc}\n')
    print(f"Recorded {result['source']['frame_count']} decoded frame PTS and {len(result['images'])} PNGs. Visual annotations pending.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
