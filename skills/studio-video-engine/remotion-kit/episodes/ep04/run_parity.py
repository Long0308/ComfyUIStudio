#!/usr/bin/env python
"""Full parity run for the ep04 review cut and 4K master (CPU only, concurrency 1-2). Writes PARITY.json and PARITY.md.

  python -I run_parity.py --work SCRATCH_DIR --report-dir DIR [--pin | --update-regression] [--allow-stale]

Review: kit frames vs the ORIGINAL review compositor's lossless PNGs (render_review_v008.cjs --stills, run read-only into the
scratch dir with --out pointing at a dummy file, never --overwrite). Pass = identical md5 of the decoded RGBA pixels (PSNR inf).
Always compared as RGBA (alpha included). A missing change-detector pin FAILS before anything is rendered unless --pin (create) or
--update-regression (overwrite) is given. The historical dip waivers of the first build are produced by the adapters' explicit
--waive-historical-dip option; their approval fields come from the command line below (this runner supplies reproduction-only values).
Property checks (kit-vs-kit, e.g. the PREVIEW mark box) are reported separately and are not
parity: they never enter all_pass. Stale or CHANGED no-reference pins exit non-zero (stale only with --allow-stale it passes).
Master: kit 4K stills (master mode, --preview --drop-preview-mark under --reproduction-only, --stage-needed) vs the existing master stills of the master
build. Regression: stills that have no reference stay pinned by sha256 in master-regression.json (compared on later runs).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent.parent
WORKSPACE = KIT.parents[3]
EDITORIAL = WORKSPACE / 'production-local' / 'JennieJoyKids-Story' / '04-milk-and-mom' / 'editorial'
V008 = EDITORIAL / 'review-hd-v008'
MASTER = EDITORIAL / 'master-4k-v002'

REVIEW_STILLS = {  # frame -> original lossless still already in the v008 build (others are rendered by the original compositor)
    392: 'G2-whip-f392.png', 1013: 'T1010-f1013.png', 1314: 'T1310-f1314.png', 1615: 'T1610-f1615.png', 2160: 'G3-creamy-f2160.png',
    388: 'G2-whip-f388.png', 390: 'G2-whip-f390.png', 680: 'G1-karaoke-icon-f680.png', 2519: 'G3-endplate-f2519.png', 2579: 'G3-endlogo-f2579.png',
}
REVIEW_EXTRA = [45, 88, 1800, 2130, 2155, 2300, 2550]
WINDOWS = [(380, 400), (1005, 1020)]
MASTER_STILLS = {  # frame -> existing master still
    296: 'still-karaoke-icon-IC01-f296.png', 1013: 'still-dip-peak-T1010-f1013.png', 1010: 'still-dip-tail-T1010-f1010.png',
    390: 'still-whip-mid-T390-f390.png', 2155: 'still-disc-slide-f2155.png', 2160: 'still-creamy-card1-f2160.png', 2550: 'still-endcard-f2550.png',
}
MASTER_REGRESSION = [1011, 1012, 1311, 1611]  # T1010 tail frames 2-3 and one tail frame each of T1310 / T1610 (no reference stills exist)


BROWSER_REL = Path('.remotion') / 'chrome-headless-shell' / 'win64' / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe'


def find_browser():
    """The cached headless shell lives next to this episode's first review build; the kit itself never searches for one."""
    for env in ('REMOTION_BROWSER',):
        import os
        if os.environ.get(env) and Path(os.environ[env]).is_file():
            return os.environ[env]
    for d in sorted(EDITORIAL.glob('review-hd-v*')):
        candidate = d / BROWSER_REL
        if candidate.is_file():
            return str(candidate)
    raise SystemExit('no cached chrome-headless-shell found; set REMOTION_BROWSER')


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f'FAILED {" ".join(map(str, cmd))}\n{r.stdout[-800:]}\n{r.stderr[-1500:]}')
    return r.stdout + r.stderr


def md5(path, vf=None):
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path)] + (['-vf', vf] if vf else []) + ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-']
    r = subprocess.run(cmd, capture_output=True, check=True)
    return hashlib.md5(r.stdout).hexdigest()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def psnr(a, b):
    r = subprocess.run(['ffmpeg', '-i', str(a), '-i', str(b), '-lavfi', 'psnr', '-f', 'null', '-'], capture_output=True, text=True)
    m = re.search(r'average:(\S+)', r.stderr)
    return None if m is None or m.group(1) == 'inf' else round(float(m.group(1)), 3)


def compare(rows, group, frame, a, b):
    same = md5(a) == md5(b)
    rows.append({'group': group, 'frame': frame, 'identical_rgba_md5': same, 'psnr_db': None if same else psnr(a, b), 'pass': same})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--work', required=True)
    ap.add_argument('--report-dir', required=True, help='where PARITY.md / PARITY.json / master-regression.json go (use a scratch dir; copy deliberately)')
    ap.add_argument('--pin', action='store_true', help='create the change-detector pin file when it is missing')
    ap.add_argument('--update-regression', action='store_true', help='overwrite the change-detector pins')
    ap.add_argument('--allow-stale', action='store_true', help='let stale change-detector pins pass (CHANGED never passes)')
    a = ap.parse_args()
    pin_check = Path(a.report_dir) / 'master-regression.json'
    if not pin_check.exists() and not (a.pin or a.update_regression):
        raise SystemExit(f'pin file {pin_check} is missing: copy the committed pins in, or pass --pin (create) / --update-regression (overwrite)')
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    report_dir = Path(a.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    node = 'node'
    browser = find_browser()
    repro = ['--browser', browser, '--reproduction-only', str(work)]  # every render output below lies inside the work dir
    cfg_review, cfg_master = work / 'kit-config-ep04.json', work / 'kit-config-master.json'
    # reproduction-only waivers state that they are NOT an approval: this runner invents no approval fields
    waive = ['--waive-historical-dip', '--waiver-reproduction-only', '--waiver-render', str(V008 / 'milk-and-mom-REVIEW-1080p30-native-upscaled-v008.mp4')]
    run([node, str(HERE / 'adapter-v008.cjs'), '--out', str(cfg_review)] + waive)
    run([node, str(HERE / 'adapter-master-v002.cjs'), '--preview', '--out', str(cfg_master)] + waive)
    rows = []

    # ---- review: kit vs original compositor ------------------------------------------------------------------------------
    frames = sorted(set(REVIEW_STILLS) | set(REVIEW_EXTRA))
    kit_dir = work / 'kit-review-stills'
    run([node, str(KIT / 'render.cjs'), '--config', str(cfg_review), '--stills', ','.join(f'f{f}:{f}' for f in frames), '--outdir', str(kit_dir), '--concurrency', '1'] + repro)
    need = [f for f in frames if f not in REVIEW_STILLS] + [f for lo, hi in WINDOWS for f in range(lo, hi + 1)]
    orig_dir = work / 'orig-stills'
    missing = [f for f in need if not (orig_dir / f'o{f}.png').exists()]
    if missing:
        run([node, str(V008 / 'render_review_v008.cjs'), '--stills', ','.join(f'o{f}:{f}' for f in missing), '--outdir', str(orig_dir),
             '--out', str(work / 'orig-dummy.mp4'), '--concurrency', '1'], cwd=str(V008))
    for f in frames:
        ref = V008 / 'stills' / REVIEW_STILLS[f] if f in REVIEW_STILLS else orig_dir / f'o{f}.png'
        compare(rows, 'review still', f, kit_dir / f'f{f}.png', ref)
    for lo, hi in WINDOWS:
        seq = work / f'kit-seq-{lo}-{hi}'
        run([node, str(KIT / 'render.cjs'), '--config', str(cfg_review), '--range', f'{lo}-{hi}', '--png-seq', str(seq), '--concurrency', '2'] + repro)
        for f in range(lo, hi + 1):
            compare(rows, f'review window {lo}-{hi}', f, seq / f'element-{f}.png', orig_dir / f'o{f}.png')

    # ---- master: kit 4K vs existing master stills -------------------------------------------------------------------------
    mdir = work / 'kit-master-stills'
    mframes = sorted(MASTER_STILLS)
    run([node, str(KIT / 'render.cjs'), '--config', str(cfg_master), '--mode', 'master', '--preview', '--drop-preview-mark', '--stage-needed',
         '--stills', ','.join(f'm{f}:{f}' for f in mframes), '--outdir', str(mdir), '--concurrency', '1'] + repro)
    for f in mframes:
        compare(rows, 'master still', f, mdir / f'm{f}.png', MASTER / 'stills' / MASTER_STILLS[f])
    rdir = work / 'kit-master-regression'
    run([node, str(KIT / 'render.cjs'), '--config', str(cfg_master), '--mode', 'master', '--preview', '--drop-preview-mark', '--stage-needed',
         '--stills', ','.join(f'm{f}:{f}' for f in MASTER_REGRESSION), '--outdir', str(rdir), '--concurrency', '1'] + repro)
    # no-reference CHANGE DETECTORS (not parity): pinned md5 of kit master stills that have no reference still, bound to the sha256
    # of the sources they depend on (master config + tail files). Source changed -> 'stale' (re-pin); same sources but different
    # pixels -> 'CHANGED'. They are reported but excluded from all_pass.
    cfg = json.loads(cfg_master.read_text(encoding='utf-8'))
    bound = {'pixel_hash': 'md5 of decoded RGBA', 'master_config_sha256': sha256(MASTER / 'config' / 'master-config-v002.json'),
             'tail_sha256': {k: v['sha256'] for k, v in cfg['bindings']['tails'].items()}}
    pin_file = report_dir / 'master-regression.json'
    now = {str(f): md5(rdir / f'm{f}.png') for f in MASTER_REGRESSION}
    if a.update_regression or (a.pin and not pin_file.exists()):
        pin_file.write_text(json.dumps({'note': 'NO-REFERENCE CHANGE DETECTORS, not parity: md5 of decoded RGBA pixels of kit master stills, bound to the source hashes below',
                                        'bound_to': bound, 'frames': now}, indent=1), encoding='utf-8')
        print('change-detector pins written')
    pinned = json.loads(pin_file.read_text(encoding='utf-8'))
    detectors = []
    for f in MASTER_REGRESSION:
        if pinned.get('bound_to') != bound:
            status = 'stale (sources changed or old pin format; re-pin with --update-regression)'
        else:
            status = 'unchanged' if pinned['frames'].get(str(f)) == now[str(f)] else 'CHANGED'
        detectors.append({'frame': f, 'status': status})
    # the PREVIEW mark: marked vs unmarked must be identical everywhere EXCEPT inside the mark box (top-right, 4K px)
    run([node, str(KIT / 'render.cjs'), '--config', str(cfg_master), '--mode', 'master', '--preview', '--stage-needed', '--still', '1010',
         '--out', str(work / 'kit-master-marked-f1010.png'), '--concurrency', '1'] + repro)
    marked, plain = work / 'kit-master-marked-f1010.png', mdir / 'm1010.png'
    rest_top = 'crop=3040:200:0:0'      # left part of the top strip
    rest_body = 'crop=3840:1960:0:200'  # everything below the strip
    box = 'crop=800:200:3040:0'         # the mark box region
    confined = md5(marked, rest_top) == md5(plain, rest_top) and md5(marked, rest_body) == md5(plain, rest_body)
    differs = md5(marked, box) != md5(plain, box)
    properties = [{'property': 'PREVIEW mark changes pixels only inside its box (kit-vs-kit, not parity)', 'frame': 1010, 'pass': bool(confined and differs)}]

    rule_doc = json.loads(run(['node', str(HERE / 'rule_report.cjs')]))
    out = {'all_pass': all(r['pass'] for r in rows), 'frames': len(rows), 'rows': rows, 'property_checks': properties, 'rule_report': rule_doc, 'change_detectors': detectors, 'change_detectors_note': 'no-reference change detectors, not parity; excluded from all_pass',
           'review_config_sha256': sha256(V008 / 'config' / 'review-config-v008.json'), 'master_config_sha256': sha256(MASTER / 'config' / 'master-config-v002.json')}
    (report_dir / 'PARITY.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    lines = ['# remotion-kit parity (generated by run_parity.py)', '', f"all_pass={out['all_pass']} frames={out['frames']}", '',
             '| group | frame | identical RGBA md5 | PSNR dB (if different) | pass |', '|---|---|---|---|---|']
    for r in rows:
        lines.append(f"| {r['group']} | {r['frame']} | {r['identical_rgba_md5']} | {r['psnr_db']} | {r['pass']} |")
    lines += ['', '## Property checks (kit-vs-kit, not parity, excluded from all_pass)', '', '| property | frame | pass |', '|---|---|---|']
    lines += [f"| {x['property']} | {x['frame']} | {x['pass']} |" for x in properties]
    lines += ['', '## What the kit rules say about each review build (adapted WITHOUT waivers)', '',
              '| build | dip peak issues | dip sparkle issues | other issues | first spoken frame evidence (dip targets) | engine dip schedule | waivers its adapter adds (option) |', '|---|---|---|---|---|---|---|']
    for build, doc in rule_doc.items():
        if 'adapter_error' in doc:
            lines.append(f"| {build} | adapter error | {doc['adapter_error']} | - |")
        else:
            sparkle = sum(1 for i in doc['issues'] if 'dip_sparkle_before_first_word' in i)
            other = len(doc['issues']) - doc['dip_peak_issues'] - sparkle
            evidence = '; '.join(sorted({('onset evidence' if x['basis'].startswith('onset') else 'caption-based') for x in doc.get('first_spoken', [])})) or '-'
            lines.append(f"| {build} | {doc['dip_peak_issues']} | {sparkle} | {other} | {evidence} | {doc['engine_schedule']['label'].split(':')[0]} ({', '.join(doc['engine_schedule']['mismatch']) or 'none'}) | {doc['waived_in_adapter']} |")
    lines += ['', '## No-reference change detectors (not parity, excluded from all_pass)', '',
              'Pinned md5 of kit master stills that have no reference still, bound to the sha256 of the master config and tail files.', '',
              '| frame | status |', '|---|---|'] + [f"| {d['frame']} | {d['status']} |" for d in detectors]
    (report_dir / 'PARITY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    groups = {}
    for r in rows:
        g = groups.setdefault(r['group'], [0, 0])
        g[0] += 1
        g[1] += 1 if r['pass'] else 0
    for g, (n, p) in groups.items():
        print(f'{g}: {p}/{n} pass')
    for d in detectors:
        print(f"change detector f{d['frame']}: {d['status']}")
    for x in properties:
        print(f"property check: {x['property']}: {'ok' if x['pass'] else 'FAILED'}")
    for build, doc in rule_doc.items():
        print(f"rule report {build}: dip_peak_issues={doc.get('dip_peak_issues')} issues={len(doc.get('issues', []))} {doc.get('adapter_error', '')}")
    bad_props = [x for x in properties if not x['pass']]
    changed = [d for d in detectors if d['status'] == 'CHANGED']
    stale = [d for d in detectors if d['status'].startswith('stale')]
    if changed:
        print('!!! CHANGE DETECTOR CHANGED for frames ' + ', '.join(str(d['frame']) for d in changed) + ' (same sources, different pixels)', file=sys.stderr)
    if stale:
        print('!!! CHANGE DETECTOR STALE for frames ' + ', '.join(str(d['frame']) for d in stale) + ': sources changed; re-pin with --update-regression', file=sys.stderr)
    print('ALL PASS (reference-based rows)' if out['all_pass'] else 'FAILURES')
    fail = (not out['all_pass']) or bool(bad_props) or bool(changed) or (bool(stale) and not a.allow_stale)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
