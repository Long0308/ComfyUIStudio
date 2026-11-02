// T-E42 end-to-end smoke: three new presets through the REAL compositor (render.cjs --stills, CPU, concurrency 1).
// Every shot is a solid colour, so a still tells which picture is where: cut_push (one picture, settles), push_slide (both pictures side by
// side on mid frames), card_flip_3d (exactly ONE face per frame). Skipped (with the reason) when ffmpeg, the Remotion packages or a cached
// headless browser are not there, or when KIT_SKIP_RENDER_SMOKE=1. The browser comes from REMOTION_BROWSER or the workspace's .remotion cache.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {BROWSER, FONTS, KIT, PACKAGES, build, config, decodePng, nearest, rowColours} from './smoke-lib.mjs';

test('render smoke: cut_push, push_slide and card_flip_3d through render.cjs --stills show the pictures the descriptors promise', (t) => {
  if (process.env.KIT_SKIP_RENDER_SMOKE === '1') return t.skip('KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  if (!fs.existsSync(BROWSER)) return t.skip(`no cached headless browser (${BROWSER}); set REMOTION_BROWSER`);
  if (!fs.existsSync(path.join(PACKAGES, 'remotion', 'package.json'))) return t.skip(`Remotion packages not found (${PACKAGES})`);
  if (FONTS.some((f) => !fs.existsSync(f))) return t.skip('fonts for the compositor are not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-smoke-'));
  try {
    const cfgFile = path.join(dir, 'config.json');
    fs.writeFileSync(cfgFile, JSON.stringify(config(build(dir))));
    const outdir = path.join(dir, 'stills');
    const frames = {a59: 59, a60: 60, b126: 126, c180: 180, c182: 182, c190: 190, c195: 195};
    const spec = Object.entries(frames).map(([name, f]) => `${name}:${f}`).join(',');
    const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--mode', 'review', '--stills', spec, '--outdir', outdir,
      '--concurrency', '1', '--browser', BROWSER, '--workdir', dir], {encoding: 'utf8', timeout: 600000, maxBuffer: 1 << 26});
    assert.equal(r.status, 0, `${r.stdout.slice(-600)}\n${r.stderr.slice(-1200)}`);
    const still = (name) => decodePng(path.join(outdir, `${name}.png`));
    const row = 300; // above the caption panel, clear of the review label
    // cut_push: one picture at a time, the incoming one from the boundary frame
    assert.deepEqual([...rowColours(still('a59'), row)], ['red']);
    assert.deepEqual([...rowColours(still('a60'), row)], ['green']);
    // push_slide, mid-window: the outgoing picture on one side, the incoming one on the other, both whole colours
    const mid = still('b126');
    assert.equal(nearest(mid.at(200, row)), 'green', 'outgoing picture on the left');
    assert.equal(nearest(mid.at(1720, row)), 'blue', 'incoming picture on the right');
    const midColours = rowColours(mid, row);
    assert.ok(midColours.has('green') && midColours.has('blue') && !midColours.has('red'), [...midColours].join());
    // card_flip_3d: ONE face per frame; the outgoing face first, the incoming face after the half-way switch
    for (const name of ['c180', 'c182']) assert.deepEqual([...rowColours(still(name), row)].filter((c) => c !== 'paper'), ['blue'], `${name} shows only the outgoing face`);
    for (const name of ['c190', 'c195']) assert.deepEqual([...rowColours(still(name), row)].filter((c) => c !== 'paper'), ['magenta'], `${name} shows only the incoming face`);
    assert.equal(nearest(still('c180').at(960, row)), 'blue');
    // the first flip frame is the whole outgoing picture (no paper at the edges), the late frames narrow it
    assert.ok(!rowColours(still('c180'), row).has('paper'), 'flat at the first flip frame');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
