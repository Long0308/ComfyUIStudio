"""Read local film sources and make three-frame evidence; no GPU or ffmpeg."""
import hashlib
import json
import sys
from pathlib import Path
import av
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V2 = ROOT / 'production-local/JennieJoyKids-Story/Newtecons-TienDo-KichTinh-30s/REVIEW/2026-10-31-CHO-ANH-CHOT/26_DUYET_TUNG_CANH/v2'
FONT = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 22)

def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def frame(path, t):
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        c.seek(max(0, int(t / st.time_base)), stream=st, backward=True)
        last = None
        for f in c.decode(st):
            last = f
            if f.time >= t:
                break
        if last is None:
            raise ValueError(f'No decoded frame: {path} {t}')
        return last.to_image()

def tile(path):
    digest = sha(path)
    dest = HERE / 'source-tiles' / (path.stem + '-' + digest[:10] + '.png')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        duration = float(st.duration * st.time_base) if st.duration else c.duration / 1000000
        fps = float(st.average_rate)
        info = dict(duration=duration, width=st.width, height=st.height, fps=fps,
                    audio=bool(c.streams.audio))
    times = [0, max(0, (duration - 1/fps)/2), max(0, duration - 1/fps - .001)]
    if not dest.exists():
        sheet = Image.new('RGB', (2304, 478), '#18212d')
        draw = ImageDraw.Draw(sheet)
        for i, t in enumerate(times):
            im = frame(path, t)
            im.thumbnail((768, 432), Image.Resampling.LANCZOS)
            sheet.paste(im, (i*768+(768-im.width)//2, 35+(432-im.height)//2))
            draw.text((i*768+8, 7), f'{path.stem[:45]} | {t:.2f}s', font=FONT, fill='white')
        sheet.save(dest)
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest, tile=dest.relative_to(ROOT).as_posix(), sample_times=times, **info)

def main():
    edl = json.loads((ROOT/'docs/handoffs/EDL-DRAFT-V014-2026-11-01.json').read_text(encoding='utf-8-sig'))
    paths = list(V2.glob('*.mp4'))
    paths += [ROOT/s['media']['path'] for s in edl['timeline'] if s['media'].get('path') and s['media'].get('status') == 'approved']
    out = []
    for p in dict.fromkeys(paths):
        if p.name.startswith(('PREVIEW', 'OVERNIGHT')):
            continue
        try:
            out.append(tile(p))
            print(p.name, flush=True)
        except Exception as e:
            print('UNREADABLE', p, repr(e), flush=True)
    (HERE/'source-inventory.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
