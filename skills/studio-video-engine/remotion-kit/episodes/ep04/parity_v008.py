#!/usr/bin/env python
"""Parity check: kit renders vs the decoded frames of the v008 export (or any reference mp4).

usage: python -I parity_v008.py --ref REF.mp4 --work DIR [--kit-stills DIR --stills f392:392,...]
                                [--kit-seq DIR:A-B ...] [--base-stills DIR:name=frame,...] --report OUT.json
Per frame: PSNR (ffmpeg psnr filter, all planes) and the md5 of the decoded RGB pixels of both sides.
Pass criterion per frame: PSNR >= --min-db (default 40) or identical pixel md5.
Kit PNG-sequence files are named element-<frame>.png (Remotion imageSequence); stills <name>.png.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def extract(ref, frame, out):
    r = run(['ffmpeg', '-v', 'error', '-y', '-i', ref, '-vf', f'select=eq(n\\,{frame})', '-fps_mode', 'passthrough', '-frames:v', '1', str(out)])
    if r.returncode != 0 or not Path(out).exists():
        raise SystemExit(f'extract f{frame} failed: {r.stderr}')


def psnr(a, b):
    r = run(['ffmpeg', '-i', str(a), '-i', str(b), '-lavfi', 'psnr', '-f', 'null', '-'])
    m = re.search(r'average:(\S+)', r.stderr)
    if not m:
        raise SystemExit(f'psnr failed: {r.stderr[-400:]}')
    return float('inf') if m.group(1) == 'inf' else float(m.group(1))


def pixel_md5(path):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True)
    return hashlib.md5(r.stdout).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--kit-stills')
    ap.add_argument('--stills', default='')
    ap.add_argument('--kit-seq', action='append', default=[])
    ap.add_argument('--kit-mp4', action='append', default=[], help='kit.mp4:A-B  (a --range A-B mp4 render; decoded frame i = A + i)')
    ap.add_argument('--pair', action='append', default=[], help='label|frame|kit.png|lossless_ref.png (kit still vs the original compositor still)')
    ap.add_argument('--min-db', type=float, default=40.0)
    ap.add_argument('--report', required=True)
    a = ap.parse_args()
    work = Path(a.work)
    (work / 'ref').mkdir(parents=True, exist_ok=True)
    rows = []

    def compare(label, frame, kit_png):
        ref_png = work / 'ref' / f'ref_f{frame}.png'
        if not ref_png.exists():
            extract(a.ref, frame, ref_png)
        db = psnr(kit_png, ref_png)
        same = pixel_md5(kit_png) == pixel_md5(ref_png)
        rows.append({'set': label, 'frame': frame, 'psnr_db': None if db == float('inf') else round(db, 3), 'identical': same, 'pass': same or db >= a.min_db})

    if a.kit_stills and a.stills:
        for item in a.stills.split(','):
            name, fr = item.split(':')
            compare('stills', int(fr), Path(a.kit_stills) / f'{name}.png')
    for spec in a.kit_seq:
        d, rng = spec.rsplit(':', 1)
        lo, hi = map(int, rng.split('-'))
        for f in range(lo, hi + 1):
            cand = [Path(d) / f'element-{f}.png', Path(d) / f'element-{f:04d}.png', Path(d) / f'element-{f:05d}.png']
            png = next((c for c in cand if c.exists()), None)
            if png is None:
                raise SystemExit(f'missing kit frame {f} in {d}')
            compare(f'seq {lo}-{hi}', f, png)
    for spec in a.kit_mp4:
        mp4, rng = spec.rsplit(':', 1)
        lo, hi = map(int, rng.split('-'))
        for f in range(lo, hi + 1):
            png = work / 'kitmp4' / f'{Path(mp4).stem}_f{f}.png'
            png.parent.mkdir(parents=True, exist_ok=True)
            if not png.exists():
                extract(mp4, f - lo, png)
            compare(f'mp4 {lo}-{hi}', f, png)
    for spec in a.pair:
        label, frame, kit, ref = spec.split('|', 3)
        db = psnr(kit, ref)
        same = pixel_md5(kit) == pixel_md5(ref)
        rows.append({'set': label, 'frame': int(frame), 'psnr_db': None if db == float('inf') else round(db, 3), 'identical': same, 'pass': same or db >= a.min_db})
    Path(a.report).write_text(json.dumps({'min_db': a.min_db, 'rows': rows, 'all_pass': all(r['pass'] for r in rows)}, indent=1), encoding='utf-8')
    print(f"{'set':14} {'frame':>6} {'psnr_db':>9} identical pass")
    for r in rows:
        print(f"{r['set']:14} {r['frame']:>6} {str(r['psnr_db']):>9} {str(r['identical']):9} {r['pass']}")
    worst = min((r['psnr_db'] if r['psnr_db'] is not None else 999) for r in rows)
    print(f'frames={len(rows)} worst_psnr={worst} all_pass={all(r["pass"] for r in rows)}')
    return 0 if all(r['pass'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
