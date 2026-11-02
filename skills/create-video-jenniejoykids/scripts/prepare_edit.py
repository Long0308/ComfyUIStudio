"""Bind explicitly accepted native H3 sources to a portable, gated Remotion edit.

Input paths are absolute and supplied in JSON. This never generates media or renders.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

from compile_prompts import compile_project


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def absolute_file(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f'Expected existing absolute file: {value}')
    return path.resolve()


def frame(seconds, fps):
    # Match JavaScript Math.round for these nonnegative timeline values.
    return math.floor(seconds * fps + .5)


def validate_film(film):
    fps, duration = film['fps'], film['duration']
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid duration/fps')
    if not film['clips']:
        raise ValueError('No accepted native H3 clips bound')
    end = 0
    for clip in film['clips']:
        start, stop = clip['start'], clip['start'] + clip['duration']
        if not all(math.isfinite(n) for n in (start, stop)) or abs(start - end) > .00001 or frame(start, fps) != frame(end, fps) or frame(stop, fps) <= frame(start, fps):
            raise ValueError('Clips must have positive contiguous absolute frame boundaries')
        end = stop
    if abs(end - duration) > .00001 or frame(end, fps) != frame(duration, fps):
        raise ValueError('Clips must fill the entire film')
    for event in film['dialogue'] + film['repeat_cues'] + film['brand_events']:
        a, b = event['start'], event['end']
        if not all(math.isfinite(n) for n in (a, b)) or a < 0 or b > duration or frame(b, fps) <= frame(a, fps):
            raise ValueError('Invalid or zero-frame event')
    for line in film['dialogue']:
        if 'position' in line and (not isinstance(line['position'], str) or line['position'] not in ('top', 'bottom', 'top-left')):
            raise ValueError('Caption position must be top, bottom or top-left')
    brands = film['brand_events']
    for i, event in enumerate(brands):
        for other in film['dialogue'] + brands[i + 1:]:
            if frame(event['start'], fps) < frame(other['end'], fps) and frame(event['end'], fps) > frame(other['start'], fps):
                raise ValueError('Brand intervals must be dialogue-free and non-overlapping')


def srt_time(seconds):
    milliseconds = math.floor(seconds * 1000 + .5)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'


def prepare(config):
    request = read_json(absolute_file(config['production_request']))
    compiled = compile_project(request)
    segments = compiled['EDIT']['segments']
    positions = config.get('caption_positions', {})
    if not isinstance(positions, dict):
        raise ValueError('caption_positions must map dialogue IDs to top, bottom or top-left')
    dialogue_ids = {line['id'] for segment in segments for line in segment['dialogue']} if positions else set()
    for identifier, position in positions.items():
        if not isinstance(identifier, str) or identifier not in dialogue_ids:
            raise ValueError(f'Unknown caption_positions dialogue ID: {identifier}')
        if not isinstance(position, str) or position not in ('top', 'bottom', 'top-left'):
            raise ValueError('caption_positions values must be top, bottom or top-left')
    accepted = config['accepted_clips']
    if len(accepted) != len(segments) or len({c['segment_id'] for c in accepted}) != len(segments):
        raise ValueError('Exactly one accepted native H3 clip per production segment is required')
    sources = {}
    for clip in accepted:
        if clip.get('accepted') is not True or clip.get('engine') != 'native_h3':
            raise ValueError('Bind reviewed native_h3 sources; baseline substitution is forbidden')
        sources[clip['segment_id']] = absolute_file(clip['file'])
    if set(sources) != {segment['segment_id'] for segment in segments}:
        raise ValueError('Accepted source IDs do not match production segments')
    mix = absolute_file(config['canonical_mix'])
    brands = [(event, absolute_file(event['file'])) for event in config.get('brand_events', [])]
    runtime = {key: str(absolute_file(config['runtime'][key])) for key in ('node', 'renderer_cli', 'ffmpeg', 'ffprobe')}
    project = Path(config['project_dir'])
    if not project.is_absolute():
        raise ValueError('project_dir must be absolute')
    project = project.resolve()
    if (project / 'finish-config.json').exists() or (project / 'src' / 'film.json').exists():
        raise ValueError('Use a fresh project_dir to preserve previous previews and approvals')
    film = {'schema_version': '1.1', 'fps': config.get('fps', request['delivery']['fps']),
            'duration': max(s['start'] + s['duration'] for s in segments),
            'mix': 'audio/canonical-mix' + mix.suffix, 'clips': [], 'dialogue': [], 'repeat_cues': [],
            'brand_events': [], 'final_approval': {'accepted': False, 'preview_sha256': '', 'accepted_at': ''}}
    copies = [(mix, film['mix'])]
    for index, segment in enumerate(segments):
        source = sources[segment['segment_id']]
        relative = f'clips/accepted-{index:03}{source.suffix}'
        copies.append((source, relative))
        film['clips'].append({'id': segment['segment_id'], 'file': relative,
                              'start': segment['start'], 'duration': segment['duration']})
        film['dialogue'].extend({**line, 'position': positions[line['id']]}
                                if line['id'] in positions else line
                                for line in segment['dialogue'])
        film['repeat_cues'].extend(segment['repeat_cues'])
    for index, (event, source) in enumerate(brands):
        relative = f'brand/event-{index:03}{source.suffix}'
        copies.append((source, relative))
        film['brand_events'].append({'file': relative, 'start': event['start'], 'end': event['end'], 'text': ''})
    validate_film(film)
    template = Path(__file__).resolve().parents[1] / 'assets' / 'remotion-template'
    shutil.copytree(template, project, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', 'renders'))
    binding = []
    for source, relative in copies:
        target = project / 'public' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        binding.append({'source': str(source), 'file': relative, 'sha256': digest(target)})
    write_json(project / 'src' / 'film.json', film)
    (project / 'captions.srt').write_text('\n\n'.join(
        f"{i}\n{srt_time(line['start'])} --> {srt_time(line['end'])}\n{line['text']}"
        for i, line in enumerate(film['dialogue'], 1)) + '\n', encoding='utf-8')
    write_json(project / 'source-binding.json', binding)
    settings = {'schema_version': '1.0', 'project_dir': str(project), 'runtime': runtime,
                'comfy_url': config['comfy_url'], 'port': config.get('port', 3044)}
    write_json(project / 'finish-config.json', settings)
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(read_json(args.config)), ensure_ascii=False))


if __name__ == '__main__':
    main()
