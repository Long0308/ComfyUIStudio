// Fork F / gaps 1 + 3 in the engine adapter: engine builds select the approved v013 plate style ('v010') and carry the EndLogo audio-tail
// fades from the episode text key ending.endLogoTail (the engine records them as prose only). Built with the REAL engine into scratch.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {pin} from './ep04-pin.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const WORKSPACE = path.resolve(SKILL, '../../..');
const require = createRequire(import.meta.url);
const EP = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom');
const LOGO = path.join(WORKSPACE, 'production-local', 'studio-app', 'logo-jenniejoy-kids.png');
const WORD_TIMING = path.join(EP, 'editorial', 'word-timing-v003', 'WORD-TIMING-v003.json');
const have = pin.available && fs.existsSync(pin.boundaries) && fs.existsSync(WORD_TIMING);
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const TEXT = path.join(KIT, 'episodes', 'ep04', 'episode-text.json');
const {collectIssues} = await import(pathToFileURL(path.join(KIT, 'src', 'validate.mjs')).href);

const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r14a-'));
process.on('exit', () => fs.rmSync(SCRATCH, {recursive: true, force: true}));
let built;
function plain() {
  if (built) return built;
  const out = path.join(SCRATCH, 'out');
  fs.mkdirSync(out, {recursive: true});
  const r = spawnSync('python', ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', pin.episode,
    '--boundaries', pin.boundaries, '--word-timing', pin.wordTiming(), '--out', out, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, r.stderr.slice(-800));
  const receipt = path.join(SCRATCH, 'summary.json');
  fs.writeFileSync(receipt, r.stdout);
  built = {reviewConfig: path.join(out, 'review-config.json'), events: path.join(out, 'events.json'), receipt};
  return built;
}
function adapt(text) {
  const a = require(path.join(KIT, 'episodes', 'ep04', 'adapter-engine.cjs'));
  const b = plain();
  const loaded = a.loadBuild({reviewConfig: b.reviewConfig, events: b.events, receipt: b.receipt, episodeRoot: EP});
  return a.adaptEngine(loaded.review, loaded.events, {bound: loaded.bound, episodeRoot: EP, episodeText: text, allowOutside: [LOGO]});
}
const withEnding = (patch) => {
  const text = rd(TEXT);
  text.ending = {...text.ending, ...patch};
  return text;
};

test('R14-8: an engine build selects the approved v013 plate style (v010); episode text may name another known style; an unknown one is refused by validation', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const cfg = adapt(rd(TEXT));
  assert.equal(cfg.ending.plateStyle, 'v010');
  assert.deepEqual(collectIssues(cfg), []);
  assert.equal(adapt(withEnding({plateStyle: 'v008'})).ending.plateStyle, 'v008');
  assert.ok(collectIssues(adapt(withEnding({plateStyle: 'v999'}))).some((m) => /ending\.plateStyle/.test(m)));
});

test('R14-9: the EndLogo audio-tail fades come from episode text ending.endLogoTail and land in config.ending (tailFadeIn / tailFadeStart)', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const shipped = rd(TEXT).ending.endLogoTail;
  const a = adapt(rd(TEXT));
  assert.equal(a.ending.tailFadeIn, shipped.fadeInFrames);
  assert.equal(a.ending.tailFadeStart, shipped.fadeStartFrames);
  // the v013 values (fade in 4 f, hold to f30, fade out f30-f60)
  const v = adapt(withEnding({endLogoTail: {fadeInFrames: 4, fadeStartFrames: 30}}));
  assert.equal(v.ending.tailFadeIn, 4);
  assert.equal(v.ending.tailFadeStart, 30);
  assert.deepEqual(collectIssues(v), []);
});

test('R14-10: a missing or out-of-order endLogoTail is refused by the adapter, naming the key', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const gone = rd(TEXT);
  delete gone.ending.endLogoTail;
  assert.throws(() => adapt(gone), /ending\.endLogoTail/);
  assert.throws(() => adapt(withEnding({endLogoTail: {fadeInFrames: 40, fadeStartFrames: 30}})), /fadeInFrames <= fadeStartFrames/);
  assert.throws(() => adapt(withEnding({endLogoTail: {fadeInFrames: 4, fadeStartFrames: 60}})), /end card frames/);
  assert.throws(() => adapt(withEnding({endLogoTail: {fadeInFrames: 4.5, fadeStartFrames: 30}})), /ending\.endLogoTail/);
});
