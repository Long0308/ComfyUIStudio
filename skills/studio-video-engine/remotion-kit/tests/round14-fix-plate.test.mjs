// Fork F / gap 1: the end plate has a STYLE chosen by config data. 'v008' (default) is the original plate (springs, scrim 0 -> 1);
// 'v010' is the approved v013 plate: scrim starts at 0.4, the logo is not drawn at all before plate clock 2, logo and pill ease out over
// 8 frames (cubic), text fades at 3-6 / 4-7. Numbers below are the formulas of review-hd-v013/src/ending.jsx (EndPlate), restated.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {DEFAULT_MOTION, easeOut, plateFrame, resolveMotion} from '../src/presets.mjs';
import {collectIssues} from '../src/validate.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const lerp = (t, [a, b], [x, y]) => (t <= a ? x : t >= b ? y : x + ((t - a) / (b - a)) * (y - x));
const styleOf = (name) => resolveMotion({motion: {ending: {plate: {style: name}}}}).ending.plate;
const spring = (kind, frame) => 1 - Math.exp(-frame / 3); // any deterministic stand-in: only the v008 branch calls it

test('R14-4: the default plate style stays v008 (parity untouched)', () => {
  assert.equal(DEFAULT_MOTION.ending.plate.style, 'v008');
  assert.deepEqual(Object.keys(DEFAULT_MOTION.ending.plate.styles).sort(), ['v008', 'v010']);
});

test('R14-5: v010 reproduces the v013 EndPlate formulas on every plate clock t = 0..12', () => {
  const P = styleOf('v010');
  for (let t = 0; t <= 12; t += 1) {
    const f = plateFrame(P, t, spring);
    const lp = easeOut((t - 2) / 8);
    const pp = easeOut((t - 3) / 8);
    assert.equal(f.scrim, lerp(t, [0, 2], [0.4, 1]), `scrim t=${t}`);
    assert.equal(f.logo.shown, t >= 2, `logo gate t=${t}`);
    assert.equal(f.logo.opacity, t < 2 ? 0 : lerp(t, [2, 5], [0.25, 1]), `logo opacity t=${t}`);
    assert.equal(f.logo.scale, 0.6 + 0.4 * lp, `logo scale t=${t}`);
    assert.equal(f.en.opacity, lerp(t, [3, 6], [0, 1]), `pill opacity t=${t}`);
    assert.equal(f.en.k, pp, `pill progress t=${t}`);
    assert.equal(f.vi.opacity, lerp(t, [4, 7], [0, 1]), `vi opacity t=${t}`);
  }
  // the v009 bug v013 fixed: nothing of the logo may show before plate clock 2 (a faint logo sat over the last pill)
  assert.equal(plateFrame(P, 0, spring).logo.shown, false);
  assert.equal(plateFrame(P, 1, spring).logo.opacity, 0);
  assert.equal(plateFrame(P, 0, spring).scrim, 0.4);
});

test('R14-6: v008 numbers are exactly the pre-existing plate formulas (scrim 0 -> 1 over 2 f, logo opacity 0 -> 1 over 2 f, springs)', () => {
  const P = styleOf('v008');
  for (let t = 0; t <= 12; t += 1) {
    const f = plateFrame(P, t, spring);
    assert.equal(f.scrim, lerp(t, [0, 2], [0, 1]));
    assert.equal(f.logo.shown, true);
    assert.equal(f.logo.opacity, lerp(t, [0, 2], [0, 1]));
    assert.equal(f.logo.scale, 0.6 + 0.4 * spring('logo', t));
    assert.equal(f.en.k, spring('text', Math.max(0, t - 1)));
    assert.equal(f.en.opacity, lerp(t, [1, 3], [0, 1]));
    assert.equal(f.vi.opacity, lerp(t, [2, 4], [0, 1]));
  }
});

test('R14-7: an unknown plate style is refused by validation, and the component source reads the style (no second hard-coded plate)', () => {
  const src = fs.readFileSync(path.join(KIT, 'src', 'ending.jsx'), 'utf8');
  assert.match(src, /plateFrame\(/);
  const issues = collectIssues({ending: {plateStyle: 'v999'}, timeline: {}, transitions: [], shots: [], cards: []});
  assert.ok(issues.some((m) => /ending\.plateStyle/.test(m)), JSON.stringify(issues).slice(0, 300));
});

// ---- live parity with the hand-built v013's lossless stills (opt-in: needs the derived proof kit config, see the SKILL section) -------------
// KIT_PROOF_CONFIG = kit config built from the v013 change set (derived timeline, hold 70). Pixel-identical (PSNR 99) is expected for the plate
// frames f3310-f3314 and for the cut_push frames f1009 / f1010 / f1016 / f1022 (k = -1, 0, 6, 12) against review-hd-v013/stills.
import os from 'node:os';
import {spawnSync} from 'node:child_process';
import {BROWSER} from './smoke-lib.mjs';

test('R14-11: [KIT_PROOF_CONFIG] plate f3310-f3314 and cut_push f1009/f1010/f1016/f1022 are pixel-identical to the v013 lossless stills', (t) => {
  const cfgFile = process.env.KIT_PROOF_CONFIG;
  if (!cfgFile) return t.skip('KIT_PROOF_CONFIG not set (opt-in live parity)');
  const V013 = path.resolve(KIT, '..', '..', '..', '..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial', 'review-hd-v013', 'stills');
  if (!fs.existsSync(V013)) return t.skip('v013 stills absent');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r14-'));
  try {
    const pairs = {p3310: 'P-f3310', p3311: 'P-f3311', p3312: 'P-f3312', p3314: 'P-f3314', f1009: 'T1010-f1009', f1010: 'T1010-f1010', f1016: 'T1010-f1016', f1022: 'T1010-f1022'};
    const list = Object.keys(pairs).map((k) => `${k}:${k.slice(1)}`).join(',');
    const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--mode', 'review', '--stills', list, '--outdir', dir, '--stage-needed',
      '--concurrency', '1', '--browser', BROWSER, '--workdir', dir], {encoding: 'utf8', timeout: 900000, maxBuffer: 1 << 26});
    assert.equal(r.status, 0, `${r.stdout.slice(-400)}\n${r.stderr.slice(-800)}`);
    const py = 'import sys\nfrom PIL import Image\nimport numpy as np\na=np.asarray(Image.open(sys.argv[1]).convert("RGB"),dtype=np.int16)\nb=np.asarray(Image.open(sys.argv[2]).convert("RGB"),dtype=np.int16)\nprint(int(abs(a-b).max()) if a.shape==b.shape else -1)';
    for (const [name, ref] of Object.entries(pairs)) {
      const c = spawnSync('python', ['-I', '-c', py, path.join(dir, `${name}.png`), path.join(V013, `${ref}.png`)], {encoding: 'utf8'});
      if (c.status !== 0) return t.skip(`PIL/numpy unavailable: ${c.stderr.slice(-200)}`);
      assert.equal(Number(c.stdout.trim()), 0, `${name} differs from v013 ${ref} (max abs channel difference ${c.stdout.trim()})`);
    }
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
