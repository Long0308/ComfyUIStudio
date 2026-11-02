// Round 7 (re-critic): finals stage exactly the attested bytes; engine-verified tail length; required fileFrames; explicit refusals.
import test from 'node:test';
import {withBound, withBoundMaster} from './builds.mjs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {collectIssues} from '../src/validate.mjs';
import {tailWindow} from '../src/picture-mode.mjs';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const require = createRequire(import.meta.url);
const has = (issues, text) => issues.some((i) => i.includes(text));
const EDITORIAL = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const haveBuilds = fs.existsSync(path.join(EDITORIAL, 'review-hd-v011')) && fs.existsSync(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const haveFfmpeg = !spawnSync('ffmpeg', ['-version'], {encoding: 'utf8'}).error;

// ---------------------------------------------------------------------------------------------------- GAP (materialized finals)
function stageFixture(dir) {
  const write = (name, text) => {
    const file = path.join(dir, name);
    fs.writeFileSync(file, text);
    return {path: file, sha256: sha(file)};
  };
  const clip = (name, frames) => {
    const file = path.join(dir, name);
    const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', `testsrc=size=64x64:rate=24:duration=${frames / 24}`, '-frames:v', String(frames), '-pix_fmt', 'yuv420p', file], {encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    return {path: file, sha256: sha(file)};
  };
  const config = makeConfig();
  config.transitions = [{id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree',
    tail: {startFrom: 0, editorialFrames: 0, fileFrames: 12, verifiedFrames: 12}}];
  config.ending = {plateStart: 236, speechEndFrame: 235.5, plateEn: 'The end', plateVi: 'Het', tailFrom: 100};
  assert.deepEqual(collectIssues(config), []);
  const clipA = clip('clipA.mp4', 60);
  const clipB = clip('clipB.mp4', 61);
  const tailA = clip('tailA.mp4', 12);
  const tailB = clip('tailB.mp4', 13);
  const receipt = (target, kind = 'shot', transition) => {
    const doc = write(`rc-${path.basename(target.path)}.json`, JSON.stringify({status: 'COMPLETED', sha256: target.sha256, path: target.path}));
    return {kind, path: doc.path, sha256: doc.sha256, binds: target.sha256, transition};
  };
  const finalOf = (target) => ({...target, preview: false, receipt: receipt(target)});
  const wav = write('a.wav', 'wav');
  const png = write('i.png', 'png');
  const bindings = {
    opening: png, logo: png, music: wav, ambience: null,
    shots: {X1: {audio: wav, segments: {X1: finalOf(clipA)}}, X2: {audio: wav, segments: {X2a: finalOf(clipA), X2b: finalOf(clipA)}}},
    tails: {WP: finalOf(tailA)},
    icons: {'moon.png': png},
    cards: config.cards.map(() => ({icon: png, audio: wav})),
  };
  const fonts = {regular: write('r.ttf', 'f').path, bold: write('b.ttf', 'f').path};
  return {config: {...config, bindings}, fonts, clipA, clipB, tailA, tailB};
}

function runStage(dir, mutate, extra = {}) {
  const {stage} = require(path.join(KIT, 'lib', 'stage.cjs'));
  const fx = stageFixture(dir);
  const bindings = structuredClone(fx.config.bindings);
  mutate(bindings, fx);
  return {fx, ...stage({...fx.config, bindings}, {stagingDir: path.join(dir, 'stage'), fonts: fx.fonts, tailWindow, requireReceipts: true, ...extra})};
}

test('GAP: a FINAL picture / tail binding may not carry `materialized` (finals stage exactly the attested bytes)', (t) => {
  if (!haveFfmpeg) return t.skip('no ffmpeg');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-gap-'));
  try {
    // control: a valid final stages the attested file
    const ok = runStage(dir, () => {});
    const picture = ok.used.filter((u) => u.role === 'picture');
    assert.ok(picture.length === 3 && picture.every((u) => u.staged_sha256 === ok.fx.clipA.sha256 && u.preview === false));
    // the attack: valid receipt for clipA, but `materialized` points at clipB
    assert.throws(() => runStage(dir, (b, fx) => { b.shots.X2.segments.X2a.materialized = {path: fx.clipB.path, sha256: fx.clipB.sha256}; }), /final .*materialized/);
    assert.throws(() => runStage(dir, (b, fx) => { b.tails.WP.materialized = {path: fx.tailB.path, sha256: fx.tailB.sha256}; }), /final .*materialized/);
    // a PREVIEW binding may still be materialized (a stream-copied concat cache), and says so in the record
    const pv = runStage(dir, (b, fx) => {
      b.shots.X2.segments.X2a = {path: fx.clipA.path, sha256: fx.clipA.sha256, preview: true, materialized: {path: fx.clipB.path, sha256: fx.clipB.sha256}};
    }, {allowPreview: true});
    assert.ok(pv.used.some((u) => u.preview && u.staged_from.endsWith('clipB.mp4')));
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('GAP: the staged bytes of a final are re-hashed against the attested sha256', (t) => {
  if (!haveFfmpeg) return t.skip('no ffmpeg');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-gap2-'));
  try {
    const ok = runStage(dir, () => {});
    for (const u of ok.used.filter((x) => x.role === 'picture' || x.role === 'tail')) {
      const staged = path.join(ok.publicDir, u.staged);
      assert.equal(sha(staged), u.staged_sha256);
      assert.equal(u.staged_sha256, u.source_sha256, 'a final is byte-identical to the attested file');
    }
    // a file changed between the receipt check and the copy cannot be staged: requireHash fails before the copy
    assert.throws(() => runStage(dir, (b, fx) => { fs.appendFileSync(fx.clipA.path, 'x'); }), /hash changed|receipt/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- 1 verified tail length
function dipWith(outTailRows, tail) {
  const c = makeConfig();
  const schedule = [{t: -1, shot: 'out', white: 0.2}];
  for (let k = 0; k < outTailRows; k += 1) schedule.push({t: k, shot: 'out_tail', white: 0.4 + 0.1 * k});
  schedule.push({t: outTailRows, shot: 'none', white: 1}, {t: outTailRows + 1, shot: 'in', white: 0.6}, {t: outTailRows + 2, shot: 'in', white: 0.3});
  c.shots[1].words = [{w: 'Hi', startF: 108, endF: 112, keyword: false}, {w: 'moon', startF: 116, endF: 120, keyword: true}];
  c.transitions = [{id: 'D', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 89, tail, schedule}];
  return c;
}

test('1: the number of outgoing tail frames a transition plays may not exceed what the engine verified (tail.verifiedFrames)', () => {
  const base = {startFrom: 0, editorialFrames: 0, fileFrames: 30};
  assert.deepEqual(collectIssues(dipWith(3, {...base, verifiedFrames: 3})), []);
  assert.deepEqual(collectIssues(dipWith(1, {...base, verifiedFrames: 3})), [], 'playing fewer frames than verified is safe');
  const tooLong = collectIssues(dipWith(4, {...base, verifiedFrames: 3}));
  assert.ok(has(tooLong, 'plays 4 tail frames but only 3 were verified'), tooLong.join('|'));
  assert.ok(has(collectIssues(dipWith(3, base)), 'tail.verifiedFrames'), 'verifiedFrames is required');
  const wipe = makeConfig();
  wipe.transitions = [{id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree', tail: {...base, verifiedFrames: 10}}];
  assert.ok(has(collectIssues(wipe), 'plays 12 tail frames but only 10 were verified'));
  assert.deepEqual(tailWindow(dipWith(3, {...base, verifiedFrames: 3}).transitions[0]), {from: 90, frames: 3});
});

test('1: engine alignment for dip_white: kit rule == engine check_tail on a dip row, and the first-episode adapters take verifiedFrames from the events record of the build', (t) => {
  const {tailFits} = require(path.join(KIT, 'lib', 'tailcheck.cjs'));
  // a 9-frame dip_white row resolves to the engine's legacy preset (the first build's schedule): its out_tail rows come from the catalog
  const legacy = JSON.parse(fs.readFileSync(path.join(SKILL, 'schemas', 'transition-presets.json'), 'utf8')).presets.dip_white_legacy;
  const engineTail = legacy.schedule.filter((r) => r.shot === 'out_tail').length;
  assert.equal(engineTail, 3, 'the engine dip schedule has 3 out_tail rows');
  const cases = [];
  for (const [native_fps, delivery_fps] of [[24, 30], [30, 30], [25, 30], [24, 24], [60, 30]]) {
    for (const editorial of [0, 3, 8, 30]) for (const delivery of [0, 3, 10, 30]) {
      for (let native = 0; native <= 45; native += 1) cases.push({type: 'dip_white', editorial, delivery, n: 9, native, native_fps, delivery_fps});
    }
  }
  const py = spawnSync('python', ['-I', path.join(KIT, 'tests', 'engine_tail_verdicts.py')], {input: JSON.stringify(cases), encoding: 'utf8', maxBuffer: 1 << 28});
  assert.equal(py.status, 0, py.stderr.slice(-400));
  const engine = JSON.parse(py.stdout);
  let diff = 0;
  cases.forEach((c, i) => {
    const kit = tailFits({frames: c.native, nativeFps: c.native_fps, fps: c.delivery_fps, startFrom: c.delivery, n: engineTail, editorialFrames: c.editorial}).ok;
    if (kit !== engine[i]) diff += 1;
  });
  assert.equal(diff, 0, `${diff} of ${cases.length} dip_white cases differ from the engine`);
  assert.ok(engine.some(Boolean) && engine.some((v) => !v));
  if (!haveBuilds) return;
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const v8 = path.join(EDITORIAL, 'review-hd-v008');
  const [review, events] = [rd(path.join(v8, 'config', 'review-config-v008.json')), rd(path.join(v8, 'events-v008.json'))];
  const kit = adapt(review, events);
  for (const tr of kit.transitions.filter((x) => x.tail)) {
    // bound to the events record of the build (the engine's own tail_output_frames), not to a constant
    assert.equal(tr.tail.verifiedFrames, events.transitions.find((x) => x.id === tr.id).outgoing_tail.tail_output_frames, `${tr.id} verifiedFrames`);
    assert.equal(tr.tail.verifiedFrames, engineTail, 'and the earliest build equals the engine dip schedule');
  }
  const master = rd(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
  const mk = adaptMaster(review, events, master, {preview: true});
  assert.ok(mk.transitions.filter((x) => x.tail).every((x) => x.tail.verifiedFrames === events.transitions.find((e) => e.id === x.id).outgoing_tail.tail_output_frames));
});

// ---------------------------------------------------------------------------------------------------- 2 fileFrames required
test('2: tail.fileFrames is required for every tail', () => {
  const c = makeConfig();
  c.transitions = [{id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree', tail: {startFrom: 0, editorialFrames: 0, verifiedFrames: 12}}];
  assert.ok(has(collectIssues(c), 'tail.fileFrames'));
  c.transitions[0].tail.fileFrames = 20;
  assert.deepEqual(collectIssues(c), []);
});

// ---------------------------------------------------------------------------------------------------- 3 / 4 explicit refusals
test('3: the master adapter refuses a master config without native_restored_fps (no silent default)', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const review = rd(path.join(EDITORIAL, 'review-hd-v008', 'config', 'review-config-v008.json'));
  const events = rd(path.join(EDITORIAL, 'review-hd-v008', 'events-v008.json'));
  const master = rd(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
  assert.doesNotThrow(() => adaptMaster(review, events, master, {preview: true}));
  const noFps = structuredClone(master);
  delete noFps.master_contract.native_restored_fps;
  assert.throws(() => adaptMaster(review, events, noFps, {preview: true}), /native_restored_fps/);
});

test('4: the review adapter refuses a missing word-timing file, missing sha256 or missing reference (no silent "no evidence")', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const v = path.join(EDITORIAL, 'review-hd-v011');
  const review = rd(path.join(v, 'config', 'review-config-v011.json'));
  const events = rd(path.join(v, 'events-v011.json'));
  assert.doesNotThrow(() => adapt(review, events));
  const mutate = (fn) => {
    const r = structuredClone(review);
    fn(r);
    return r;
  };
  assert.throws(() => adapt(mutate((r) => { r.word_timing.path = path.join(os.tmpdir(), 'no-such-word-timing.json'); }), events), /word-timing file .* is missing/);
  assert.throws(() => adapt(mutate((r) => { delete r.word_timing.sha256; }), events), /word_timing.sha256 is required/);
  assert.throws(() => adapt(mutate((r) => { delete r.word_timing; }), events), /word_timing is required/);
  assert.throws(() => adapt(mutate((r) => { r.word_timing.sha256 = 'a'.repeat(64); }), events), /word-timing file changed/);
});

// ---------------------------------------------------------------------------------------------------- 5 docs / section
test('5: stale flag names and counts are gone from the docs', () => {
  const parity = fs.readFileSync(path.join(KIT, 'episodes', 'ep04', 'run_parity.py'), 'utf8');
  assert.doesNotMatch(parity, /--no-preview-mark/);
  assert.match(parity, /--reproduction-only/);
  const tailcheck = fs.readFileSync(path.join(KIT, 'lib', 'tailcheck.cjs'), 'utf8');
  assert.doesNotMatch(tailcheck, /four fps pairs/);
  assert.match(tailcheck, /nine fps pairs/);
  assert.ok(!fs.existsSync(path.join(KIT, 'SKILL-SECTION-r6.md')));
});
