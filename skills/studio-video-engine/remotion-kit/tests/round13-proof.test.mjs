// Round 13 / T-E42 proof: a logo hold (cards[0].start > 0 inside the outro block) must draw the plain backdrop only: no header, no pips.
// The compositor part is checked through REAL stills (CPU, concurrency 1) of a synthetic config; the engine part (one boundaries.json field
// changes exactly one kit-config row) lives in the second test and needs the real episode inputs.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {BROWSER, FONTS, KIT, PACKAGES, build, config} from './smoke-lib.mjs';

const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

function holdConfig(inputs, header) {
  const cfg = config(inputs);
  const bind = (file) => ({path: file, sha256: sha(file)});
  cfg.strings = {cardsHeader: header, cardsHeaderClosing: header};
  cfg.cards = [{term: 'Moon', ipa: '/muːn/', vi: 'mặt trăng', exampleEn: 'The moon is white.', start: 40, frames: 40}];
  cfg.bindings.cards = [{icon: bind(inputs.png), audio: bind(inputs.wav)}];
  return cfg;
}

test('R13-1: a logo hold before card 1 shows the backdrop only (no header, counter or pips); the header appears with the first card', (t) => {
  if (process.env.KIT_SKIP_RENDER_SMOKE === '1') return t.skip('KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  if (!fs.existsSync(BROWSER)) return t.skip(`no cached headless browser (${BROWSER}); set REMOTION_BROWSER`);
  if (!fs.existsSync(path.join(PACKAGES, 'remotion', 'package.json'))) return t.skip(`Remotion packages not found (${PACKAGES})`);
  if (FONTS.some((f) => !fs.existsSync(f))) return t.skip('fonts for the compositor are not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r13-'));
  try {
    const inputs = build(dir);
    const stills = {};
    for (const header of ['AAAA AAAA', 'BBBB BBBB']) {
      const cfgFile = path.join(dir, `config-${header[0]}.json`);
      fs.writeFileSync(cfgFile, JSON.stringify(holdConfig(inputs, header)));
      const outdir = path.join(dir, `stills-${header[0]}`);
      const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--mode', 'review', '--stills', 'hold:250,card:295', '--outdir', outdir,
        '--concurrency', '1', '--browser', BROWSER, '--workdir', dir], {encoding: 'utf8', timeout: 600000, maxBuffer: 1 << 26});
      assert.equal(r.status, 0, `${r.stdout.slice(-600)}\n${r.stderr.slice(-1200)}`);
      stills[header[0]] = {hold: sha(path.join(outdir, 'hold.png')), card: sha(path.join(outdir, 'card.png'))};
    }
    assert.notEqual(stills.A.card, stills.B.card, 'control: the header text IS drawn once card 1 is on screen');
    assert.equal(stills.A.hold, stills.B.hold, 'during the hold (frame 250 = outro start + 10, card 1 at +40) no header text is drawn');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('R13-2: render.cjs prints collectWarnings lines (WARNING: ...) to stderr and records them in the render record; a warning never refuses', (t) => {
  if (process.env.KIT_SKIP_RENDER_SMOKE === '1') return t.skip('KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  if (!fs.existsSync(BROWSER)) return t.skip(`no cached headless browser (${BROWSER}); set REMOTION_BROWSER`);
  if (!fs.existsSync(path.join(PACKAGES, 'remotion', 'package.json'))) return t.skip(`Remotion packages not found (${PACKAGES})`);
  if (FONTS.some((f) => !fs.existsSync(f))) return t.skip('fonts for the compositor are not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r13w-'));
  try {
    const cfg = config(build(dir));
    cfg.transitions[1].framing = 'same_framing'; // push_slide on a same-seat boundary
    const cfgFile = path.join(dir, 'config.json');
    fs.writeFileSync(cfgFile, JSON.stringify(cfg));
    const outdir = path.join(dir, 'stills');
    const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--mode', 'review', '--stills', 'a:10', '--outdir', outdir,
      '--concurrency', '1', '--browser', BROWSER, '--workdir', dir], {encoding: 'utf8', timeout: 600000, maxBuffer: 1 << 26});
    assert.equal(r.status, 0, `${r.stdout.slice(-600)}\n${r.stderr.slice(-1200)}`);
    assert.match(r.stderr, /WARNING: B: framing is same_framing but push_slide is a visible transition/);
    const record = JSON.parse(fs.readFileSync(path.join(outdir, '_stills-record.json'), 'utf8'));
    assert.equal(record.warnings.length, 1);
    assert.match(record.warnings[0], /^B: framing is same_framing/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---- R13-3: ONE boundaries.json field changes exactly one kit-config row (no code edit between the field and the render input) ------------
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {pin} from './ep04-pin.mjs';

const require = createRequire(import.meta.url);
const SKILL = path.resolve(KIT, '..');
const WORKSPACE = path.resolve(SKILL, '../../..');
const EP = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom');
const LOGO = path.join(WORKSPACE, 'production-local', 'studio-app', 'logo-jenniejoy-kids.png');
const WORD_TIMING = path.join(EP, 'editorial', 'word-timing-v003', 'WORD-TIMING-v003.json');
const have = pin.available && fs.existsSync(pin.boundaries) && fs.existsSync(WORD_TIMING);
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));

function engineBuild(dir, name, boundaries) {
  const out = path.join(dir, name, 'out');
  fs.mkdirSync(out, {recursive: true});
  const bfile = path.join(dir, name, 'boundaries.json');
  fs.writeFileSync(bfile, JSON.stringify(boundaries));
  const r = spawnSync('python', ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', pin.episode, '--boundaries', bfile,
    '--word-timing', pin.wordTiming(), '--out', out, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, r.stderr.slice(-800));
  const receipt = path.join(dir, name, 'summary.json');
  fs.writeFileSync(receipt, r.stdout);
  return {reviewConfig: path.join(out, 'review-config.json'), events: path.join(out, 'events.json'), receipt};
}

test('R13-3: changing ONE field (T1010 type dip_white -> cut_push) + build-config + adapter changes exactly the T1010 row of the kit config and still validates', async (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const adapter = require(path.join(KIT, 'episodes', 'ep04', 'adapter-engine.cjs'));
  const {collectIssues, collectWarnings} = await import(pathToFileURL(path.join(KIT, 'src', 'validate.mjs')).href);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r13f-'));
  try {
    const boundaries = rd(pin.boundaries);
    const edited = structuredClone(boundaries);
    const row = edited.boundaries.find((r) => r.frame === 1010);
    assert.equal(row.type, 'dip_white');
    row.type = 'cut_push'; // the ONE field
    const adapt = (name, b) => {
      const built = engineBuild(dir, name, b);
      const loaded = adapter.loadBuild({reviewConfig: built.reviewConfig, events: built.events, receipt: built.receipt, episodeRoot: EP});
      return adapter.adaptEngine(loaded.review, loaded.events, {bound: loaded.bound, episodeRoot: EP, episodeText: rd(path.join(KIT, 'episodes', 'ep04', 'episode-text.json')), allowOutside: [LOGO]});
    };
    const before = adapt('before', boundaries);
    const after = adapt('after', edited);
    assert.deepEqual(collectIssues(after), []);
    assert.deepEqual(collectWarnings(after), collectWarnings(before).filter((w) => !w.startsWith('T1010:')), 'the legacy-dip warning of T1010 goes away with the dip');
    const strip = (c) => {
      const {provenance, ...rest} = structuredClone(c);
      rest.transitions = rest.transitions.filter((x) => x.id !== 'T1010');
      delete rest.bindings.tails.T1010; // a cut_push plays no tail: its binding goes with the dip
      return rest;
    };
    assert.deepEqual(strip(after), strip(before), 'nothing but the T1010 row (and its tail binding) differs');
    const was = before.transitions.find((x) => x.id === 'T1010');
    const now = after.transitions.find((x) => x.id === 'T1010');
    assert.deepEqual([was.type, was.preset, Boolean(was.tail), Boolean(was.schedule)], ['dip_white', 'dip_white_legacy', true, true]);
    assert.deepEqual([now.type, now.preset, now.renders_as, Boolean(now.tail), Boolean(now.schedule)], ['cut_push', 'cut_push', 'cut_push', false, false]);
    assert.deepEqual(now.params, {scale_from: 1.04, ease: 'out'});
    assert.equal(now.start, now.boundary, 'a push starts on the boundary frame, one shot visible');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
