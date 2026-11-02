"""Local finishing UI. A human click accepts the current verified 720p preview.

Run: python finish_ui.py /absolute/path/to/finish-config.json
Only explicit UI approval enables and starts the 1080p composition.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import threading
from urllib.request import urlopen
from urllib.parse import urlsplit

from prepare_edit import absolute_file, digest, frame, read_json, validate_film, write_json


PAGE = '''<!doctype html><html lang="vi"><meta charset="utf-8">
<title>JennieJoyKids — Duyệt phim</title><style>
body{font:18px system-ui;background:#f6f0e5;color:#244b48;max-width:950px;margin:40px auto;padding:20px}
button{font:inherit;padding:16px;border-radius:12px;margin:8px;cursor:pointer}video{width:100%;background:#162c2b}
button:disabled{cursor:default;opacity:.45}pre{white-space:pre-wrap}</style>
<h1>Duyệt phim JennieJoyKids</h1><p>Xem bản nháp 720p và kiểm tra lời thoại, chuyển cảnh, phụ đề.
Xuất 720p có thể nâng từ nguồn H3 480p.</p>
<video id="preview" controls preload="metadata"></video>
<p>Nhấn “Duyệt và render 1080p” xác nhận bạn chấp nhận đúng bản nháp đang hiển thị.</p>
<button id="draft">Tạo bản nháp 720p</button><button id="final" disabled>Duyệt và render 1080p</button>
<pre id="status" role="status" aria-live="polite"></pre><script>
const token=__TOKEN__;let shownHash='';
async function refresh(){const s=await fetch('/status').then(r=>r.json());
document.getElementById('status').textContent=JSON.stringify(s,null,2);
document.getElementById('draft').disabled=s.busy;
document.getElementById('final').disabled=!s.can_approve||s.busy;
if(s.preview_ready&&shownHash!==s.preview_sha256){shownHash=s.preview_sha256;
document.getElementById('preview').src='/preview.mp4?hash='+shownHash;}}
async function act(action){const r=await fetch('/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Finish-Token':token},
body:JSON.stringify({preview_sha256:shownHash})});if(!r.ok)alert(await r.text());await refresh();}
document.getElementById('draft').onclick=()=>act('draft');
document.getElementById('final').onclick=()=>act('approve');
refresh();setInterval(refresh,3000);</script></html>'''


class Finisher:
    def __init__(self, config):
        self.config = config
        self.project = Path(config['project_dir']).resolve()
        if not Path(config['project_dir']).is_absolute():
            raise ValueError('Absolute project_dir required')
        self.runtime = {key: str(absolute_file(config['runtime'][key])) for key in ('node', 'renderer_cli', 'ffmpeg', 'ffprobe')}
        address = urlsplit(config['comfy_url'])
        if address.scheme != 'http' or address.hostname not in ('127.0.0.1', 'localhost') or address.path not in ('', '/') or address.query or address.fragment:
            raise ValueError('comfy_url must identify the local Comfy server')
        self.lock = threading.Lock()
        self.busy = False
        self.message = 'Sẵn sàng. Chưa có bản nháp được kiểm tra.'
        self.token = secrets.token_urlsafe(32)
        self.state_path = self.project / 'finishing-status.json'
        self.state = read_json(self.state_path) if self.state_path.exists() else {}
        self.preview = self.project / 'renders' / 'JennieJoyKids-720p-English.mp4'
        self.final = self.project / 'renders' / 'JennieJoyKids-1080p-English.mp4'

    def film(self):
        film = read_json(self.project / 'src' / 'film.json')
        validate_film(film)
        return film

    def binding(self, film=None):
        film = self.film() if film is None else json.loads(json.dumps(film))
        film['final_approval'] = {'accepted': False, 'preview_sha256': '', 'accepted_at': ''}
        hasher = __import__('hashlib').sha256(json.dumps(film, sort_keys=True).encode())
        files = [c['file'] for c in film['clips']] + [film['mix']] + [b['file'] for b in film['brand_events']]
        for relative in files:
            source = (self.project / 'public' / relative).resolve()
            if not source.is_relative_to((self.project / 'public').resolve()):
                raise ValueError('Media path escapes public directory')
            hasher.update(digest(source).encode())
        # The reviewed preview also binds to all rendering code/settings.
        for source in sorted((self.project / 'src').rglob('*')):
            if source.is_file() and source.name != 'film.json':
                hasher.update(source.relative_to(self.project).as_posix().encode())
                hasher.update(digest(source).encode())
        hasher.update(digest(self.project / 'remotion.config.ts').encode())
        return hasher.hexdigest()

    def eligible(self):
        try:
            return (self.state.get('draft_complete') is True and self.state.get('qa', {}).get('technical_pass') is True
                    and self.preview.is_file() and self.preview.stat().st_size > 0
                    and digest(self.preview) == self.state.get('preview_sha256')
                    and self.binding() == self.state.get('binding_sha256'))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def status(self):
        with self.lock:
            ready = self.eligible()
            return {'busy': self.busy, 'message': self.message, 'preview_ready': ready,
                    'can_approve': ready and not self.state.get('approval'),
                    'preview_sha256': self.state.get('preview_sha256', ''),
                    'qa': self.state.get('qa'), 'approval': self.state.get('approval'),
                    'final_complete': self.state.get('final_complete', False)}

    def queue_idle(self):
        with urlopen(self.config['comfy_url'].rstrip('/') + '/queue', timeout=5) as response:
            queue = json.load(response)
        if not isinstance(queue.get('queue_running'), list) or not isinstance(queue.get('queue_pending'), list):
            raise ValueError('Comfy queue status is unavailable')
        if queue['queue_running'] or queue['queue_pending']:
            raise ValueError('Comfy GPU queue is busy; retry after it is idle')

    def run(self, argv):
        result = subprocess.run(argv, cwd=self.project, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', shell=False,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise ValueError((result.stderr or result.stdout)[-6000:])
        return result.stdout

    def qa(self, path, width, height):
        film = self.film()
        probe = json.loads(self.run([self.runtime['ffprobe'], '-v', 'error', '-count_frames', '-show_streams',
                                    '-show_format', '-of', 'json', str(path)]))
        videos = [s for s in probe['streams'] if s['codec_type'] == 'video']
        audios = [s for s in probe['streams'] if s['codec_type'] == 'audio']
        if len(videos) != 1 or not audios:
            raise ValueError('QA failed: one video and an audio track required')
        video = videos[0]
        numerator, denominator = map(int, video['avg_frame_rate'].split('/'))
        if (video['width'], video['height']) != (width, height) or int(video['nb_read_frames']) != frame(film['duration'], film['fps']) or numerator / denominator != film['fps']:
            raise ValueError('QA failed: wrong dimensions, fps or frame count')
        if abs(float(probe['format']['duration']) - film['duration']) > .06:
            raise ValueError('QA failed: wrong timeline duration')
        if abs(float(audios[0].get('start_time', 0))) > .06 or abs(float(audios[0]['duration']) - film['duration']) > .06:
            raise ValueError('QA failed: audio does not cover the complete timeline')
        self.run([self.runtime['ffmpeg'], '-v', 'error', '-xerror', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
        # Decode sample timestamps as well: container duration can conceal short or gapped audio.
        decoded = subprocess.run([self.runtime['ffmpeg'], '-v', 'info', '-xerror', '-copyts', '-i', str(path),
                                  '-map', '0:a:0', '-vn', '-af', 'ashowinfo', '-f', 'null', '-'],
                                 cwd=self.project, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                 shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if decoded.returncode:
            raise ValueError('QA failed: audio sample decode failed')
        blocks = []
        for line in decoded.stderr.splitlines():
            if 'ashowinfo' not in line:
                continue
            match = re.search(r'pts_time:(\S+).*?rate:(\d+).*?nb_samples:(\d+)', line)
            if match:
                start, rate, samples = float(match[1]), int(match[2]), int(match[3])
                blocks.append((start, start + samples / rate))
        blocks.sort()
        if not blocks or abs(blocks[0][0]) > .06:
            raise ValueError('QA failed: decoded audio start unavailable or incorrect')
        end = blocks[0][1]
        for start, stop in blocks[1:]:
            if start - end > .06:
                raise ValueError('QA failed: gap in decoded audio')
            end = max(end, stop)
        if abs(end - film['duration']) > .06:
            raise ValueError('QA failed: decoded audio does not cover timeline')
        return {'technical_pass': True, 'width': width, 'height': height, 'frames': int(video['nb_read_frames']),
                'strict_decode': 'passed', 'audio_coverage': {'method': 'decoded_ashowinfo', 'start': blocks[0][0], 'end': end},
                'checked_at': datetime.now(timezone.utc).isoformat()}

    def action(self, action, preview_hash=''):
        with self.lock:
            if self.busy:
                raise ValueError('A render job is already running')
            if action not in ('draft', 'approve'):
                raise ValueError('Unknown action')
            if action == 'approve' and (not self.eligible() or preview_hash != self.state.get('preview_sha256')):
                raise ValueError('A completed current 720p preview with successful QA must be reviewed first')
            if action == 'approve' and self.state.get('approval'):
                raise ValueError('This preview was already accepted; create a new draft to approve again')
            reviewed_binding = self.state.get('binding_sha256') if action == 'approve' else None
            # Check live queue before accepting or launching any render.
            self.queue_idle()
            film = self.film()
            binding = self.binding(film)
            if action == 'approve' and (binding != reviewed_binding or not self.eligible()
                                        or preview_hash != self.state.get('preview_sha256')):
                raise ValueError('Reviewed preview or edit changed while checking the queue; create and review a new draft')
            if action == 'draft':
                self.state = {}
                film['final_approval'] = {'accepted': False, 'preview_sha256': '', 'accepted_at': ''}
            else:
                approval = {'accepted': True, 'preview_sha256': preview_hash,
                            'accepted_at': datetime.now(timezone.utc).isoformat()}
                film['final_approval'] = approval
                self.state['approval'] = approval
            write_json(self.project / 'src' / 'film.json', film)
            write_json(self.state_path, self.state)
            self.busy = True
            self.message = 'Đang tạo bản nháp 720p…' if action == 'draft' else 'Đã duyệt bản nháp. Đang render 1080p…'
            threading.Thread(target=self.worker, args=(action, binding), daemon=True).start()

    def worker(self, action, binding):
        target = self.preview if action == 'draft' else self.final
        temporary = target.with_name(target.stem + '.rendering.mp4')
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.queue_idle()
            with self.lock:
                if self.binding() != binding or (action == 'approve' and not self.eligible()):
                    raise ValueError('Reviewed preview or edit changed before rendering; job rejected')
            self.run([self.runtime['node'], self.runtime['renderer_cli'], 'render', 'src/index.tsx',
                      'JennieJoyDraftEnglish' if action == 'draft' else 'JennieJoyFinalEnglish',
                      str(temporary), '--concurrency=1', '--overwrite'])
            qa = self.qa(temporary, 1280 if action == 'draft' else 1920, 720 if action == 'draft' else 1080)
            if self.binding() != binding:
                raise ValueError('Film/source binding changed during rendering; preview invalidated')
            temporary.replace(target)
            with self.lock:
                if action == 'draft':
                    self.state = {'draft_complete': True, 'qa': qa, 'preview_sha256': digest(target), 'binding_sha256': binding}
                else:
                    self.state.update({'final_complete': True, 'final_sha256': digest(target), 'final_qa': qa})
                self.message = 'Bản nháp 720p đã sẵn sàng để xem và duyệt.' if action == 'draft' else 'Đã hoàn tất phim 1080p.'
                write_json(self.state_path, self.state)
        except Exception as exc:
            with self.lock:
                self.message = f'Không hoàn tất: {exc}'
                self.state['last_error'] = str(exc)
                write_json(self.state_path, self.state)
        finally:
            with self.lock:
                self.busy = False


def handler(finisher, origin):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, payload, content_type='application/json'):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; media-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def valid_host(self):
            return self.headers.get('Host') == urlsplit(origin).netloc

        def do_GET(self):
            if not self.valid_host():
                self.respond(403, b'Invalid host')
                return
            url = urlsplit(self.path)
            if url.path == '/' and not url.query:
                self.respond(200, PAGE.replace('__TOKEN__', json.dumps(finisher.token)).encode(), 'text/html; charset=utf-8')
            elif url.path == '/status' and not url.query:
                self.respond(200, json.dumps(finisher.status(), ensure_ascii=False).encode())
            elif url.path == '/preview.mp4' and url.query == 'hash=' + finisher.state.get('preview_sha256', '') and finisher.eligible():
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', str(finisher.preview.stat().st_size))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with finisher.preview.open('rb') as source:
                    import shutil
                    shutil.copyfileobj(source, self.wfile)
            else:
                self.respond(404, b'Not found')

        def do_POST(self):
            if not self.valid_host() or self.headers.get('Origin') != origin or self.headers.get('X-Finish-Token') != finisher.token:
                self.respond(403, b'Cross-origin or unauthorized request')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 4096 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Invalid JSON body')
                if self.path not in ('/draft', '/approve'):
                    raise ValueError('Unknown action')
                data = json.loads(self.rfile.read(length))
                finisher.action(self.path[1:], data.get('preview_sha256', ''))
                self.respond(202, b'{"started":true}')
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.respond(409, json.dumps({'error': str(exc)}).encode())
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    config = read_json(args.config)
    finisher = Finisher(config)
    port = int(config.get('port', 3044))
    origin = f'http://127.0.0.1:{port}'
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(finisher, origin))
    print(f'Finishing UI: {origin}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()

