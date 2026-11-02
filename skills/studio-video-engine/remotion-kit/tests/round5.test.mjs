// Round 5 (re-critic items 1-8).
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
import {collectIssues, collectWaived} from '../src/validate.mjs';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const require = createRequire(import.meta.url);
const has = (issues, text) => issues.some((i) => i.includes(text));
const W = {approved_by: 'test-suite', approved_at: '2026-10-27', review_render_sha256: 'c'.repeat(64)};
const EDITORIAL = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const haveBuilds = fs.existsSync(path.join(EDITORIAL, 'review-hd-v008')) && fs.existsSync(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));

// ---------------------------------------------------------------------------------------------------- 1
function threeSegments() {
  const c = makeConfig();
  c.shots[1].segments = [{id: 'X2a', from: 0, frames: 20}, {id: 'X2m', from: 20, frames: 20}, {id: 'X2b', from: 40, frames: 20}];
  return c;
}

test('1: a picture side through a MIDDLE segment id still needs continuity agree (and uniqueness counts per edge segment)', () => {
  assert.deepEqual(collectIssues(threeSegments()), [], 'base fixture');
  const plate = threeSegments();
  plate.transitions.push({id: 'B3', type: 'plate_in', boundary: 110, from: 'X2m', to: 'END_PLATE', frames: 4, direction: 0, start: 110, shows_both: true});
  assert.ok(has(collectIssues(plate), 'B3: plate_in shows both sides in one frame and a picture shot is on one side'));
  const slide = threeSegments();
  slide.transitions.push({id: 'B1', type: 'card_slide', boundary: 110, from: 'CARD_Moon', to: 'X2m', frames: 6, direction: -1, start: 110});
  assert.ok(has(collectIssues(slide), 'B1: card_slide shows both sides in one frame and a picture shot is on one side'));
  const agreed = threeSegments();
  agreed.transitions.push({id: 'B3', type: 'plate_in', boundary: 110, from: 'X2m', to: 'END_PLATE', frames: 4, direction: 0, start: 110, continuity: 'agree'});
  assert.deepEqual(collectIssues(agreed), []);
  // two transitions into the SAME middle segment collide; carries into different segments do not
  const dup = threeSegments();
  dup.transitions.push({id: 'N1', type: 'none', boundary: 110, from: 'X2a', to: 'X2m', frames: 0, direction: 0, start: 110});
  dup.transitions.push({id: 'N2', type: 'none', boundary: 110, from: 'X2a', to: 'X2m', frames: 0, direction: 0, start: 110});
  assert.ok(has(collectIssues(dup), 'several incoming transitions (N1, N2)'));
  const fine = threeSegments();
  fine.transitions.push({id: 'N1', type: 'none', boundary: 110, from: 'X2a', to: 'X2m', frames: 0, direction: 0, start: 110});
  fine.transitions.push({id: 'N2', type: 'none', boundary: 130, from: 'X2m', to: 'X2b', frames: 0, direction: 0, start: 130});
  assert.deepEqual(collectIssues(fine), []);
});

// ---------------------------------------------------------------------------------------------------- 2
function lateDip() {
  const c = makeConfig();
  c.shots[1].words = [{w: 'Hi', startF: 92, endF: 100, keyword: false}, {w: 'moon', startF: 104, endF: 112, keyword: true}];
  const schedule = [{t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'out_tail', white: 0.8}, {t: 2, shot: 'out_tail', white: 0.9},
    {t: 3, shot: 'none', white: 1}, {t: 4, shot: 'in', white: 0.8}, {t: 5, shot: 'in', white: 0.5}];
  c.transitions = [{id: 'D', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 89, tail: {startFrom: 20, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, schedule}];
  c.waivers = [{rule: 'dip_peak_before_first_word', transition: 'D', reason: 'historical reproduction', ...W}];
  return c;
}

function render(args, config) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r5-'));
  const file = path.join(dir, 'c.json');
  fs.writeFileSync(file, JSON.stringify(config));
  const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, '--out', path.join(dir, 'o.mp4'), '--check-only', ...args], {encoding: 'utf8'});
  fs.rmSync(dir, {recursive: true, force: true});
  return r.stderr;
}

test('2: waiver / preview gates hold for ranges that cover the film; --no-preview-mark is for stills only', () => {
  const c = lateDip();
  assert.deepEqual(collectIssues(c), [], 'the waived config is valid');
  const past = /bindings|Output|chrome|browser/; // gates passed: the run only fails later (no bindings in this synthetic config)
  assert.match(render(['--mode', 'master', '--range', '0-269'], c), /master-mode render \(full or --range\) refuses waived rules/);
  assert.match(render(['--mode', 'master', '--range', '10-40'], c), /refuses waived rules/);
  assert.match(render(['--mode', 'master'], c), /refuses waived rules/);
  assert.doesNotMatch(render(['--mode', 'master', '--still', '100'], c), /refuses waived rules/);
  assert.match(render(['--mode', 'master', '--still', '100'], c), past);
  assert.match(render(['--mode', 'review', '--preview', '--range', '0-269'], c), /does not cover the whole film|covers every frame is a full render|limited to stills or a --range/);
  assert.match(render(['--mode', 'review', '--preview', '--range', '0-300'], c), /outside|Invalid --range/);
  assert.doesNotMatch(render(['--mode', 'review', '--preview', '--range', '0-100'], c), /limited to stills/);
  for (const mode of ['review', 'master']) {
    assert.match(render(['--mode', mode, '--no-preview-mark', '--still', '100'], c), /--no-preview-mark was removed/);
  }
  assert.match(render(['--mode', 'review', '--no-preview-mark', '--range', '10-20'], c), /--no-preview-mark was removed/);
  assert.match(render(['--drop-preview-mark', '--still', '100'], c), /--drop-preview-mark needs --reproduction-only DIR and stills/);
});

// ---------------------------------------------------------------------------------------------------- 3
test('3: a waiver needs approved_by, approved_at, review_render_sha256; an unused waiver is refused; approvals are reported', () => {
  const ok = lateDip();
  assert.deepEqual(collectIssues(ok), []);
  const waived = collectWaived(ok);
  assert.equal(waived.length, 1);
  assert.deepEqual([waived[0].approved_by, waived[0].approved_at, waived[0].review_render_sha256], [W.approved_by, W.approved_at, W.review_render_sha256]);
  for (const [field, value] of [['approved_by', ''], ['approved_at', 'yesterday'], ['review_render_sha256', 'abc'], ['reason', '']]) {
    const c = lateDip();
    c.waivers[0][field] = value;
    const issues = collectIssues(c);
    assert.ok(has(issues, 'needs reason, review_render_sha256'), `${field}=${value}: ${issues.join('|')}`);
    assert.ok(has(issues, 'dip_peak_before_first_word'), 'the violation itself is not waived without a complete approval');
  }
  const unused = lateDip();
  unused.waivers.push({rule: 'dip_peak_before_first_word', transition: 'W1', reason: 'not violated', ...W});
  assert.ok(has(collectIssues(unused), 'waiver for rule dip_peak_before_first_word on W1 is unused'));
  const wrongRule = lateDip();
  wrongRule.waivers[0].rule = 'dip_sparkle_before_first_word';
  assert.ok(has(collectIssues(wrongRule), 'is unused'));
  const unknownRule = lateDip();
  unknownRule.waivers[0].rule = 'no_such_rule';
  assert.ok(has(collectIssues(unknownRule), 'names no waivable rule'));
});

test('3: the historical waivers come from an explicit adapter option, not from the schema string', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const v8 = path.join(EDITORIAL, 'review-hd-v008');
  const [review, events] = [rd(path.join(v8, 'config', 'review-config-v008.json')), rd(path.join(v8, 'events-v008.json'))];
  assert.match(review.schema, /v008/);
  const plain = adapt(review, events);
  assert.equal(plain.waivers, undefined, 'no option, no waivers');
  assert.ok(has(collectIssues(plain), 'dip_peak_before_first_word'));
  const waived = adapt(review, events, {historicalWaivers: W});
  assert.deepEqual(collectIssues(waived), []);
  assert.equal(waived.waivers.length, 3);
  assert.ok(waived.waivers.every((w) => w.approved_by === W.approved_by && w.review_render_sha256 === W.review_render_sha256));
  const incomplete = adapt(review, events, {historicalWaivers: {approved_by: 'x'}});
  assert.ok(has(collectIssues(incomplete), 'needs reason, review_render_sha256'));
});

// ---------------------------------------------------------------------------------------------------- 4
test('4: tail rule == engine check_tail on a 9-fps-pair grid with independent editorial / delivery values; editorialFrames is required', () => {
  const {tailFits} = require(path.join(KIT, 'lib', 'tailcheck.cjs'));
  const cases = [];
  const pairs = [[24, 30], [30, 30], [25, 30], [30, 24], [25, 24], [24, 25], [30, 25], [60, 30], [30, 60]]; // [native, delivery]
  for (const [native_fps, delivery_fps] of pairs) {
    for (const editorial of [0, 3, 8, 30]) {
      for (const delivery of [0, 3, 10, 30]) {
        for (const n of [1, 3, 5, 9, 17]) {
          // every native frame count from 0 to 45: this brackets the last used index (and the available-frames boundary) on both sides
          for (let native = 0; native <= 45; native += 1) cases.push({editorial, delivery, n, native, native_fps, delivery_fps});
        }
      }
    }
  }
  assert.equal(cases.length, 9 * 4 * 4 * 5 * 46);
  const py = spawnSync('python', ['-I', path.join(KIT, 'tests', 'engine_tail_verdicts.py')], {input: JSON.stringify(cases), encoding: 'utf8', maxBuffer: 1 << 28});
  assert.equal(py.status, 0, py.stderr.slice(-400));
  const engine = JSON.parse(py.stdout);
  let diff = 0;
  let boundary = 0;
  cases.forEach((c, i) => {
    const r = tailFits({frames: c.native, nativeFps: c.native_fps, fps: c.delivery_fps, startFrom: c.delivery, n: c.n, editorialFrames: c.editorial});
    if (r.ok !== engine[i]) diff += 1;
    if (Math.abs(c.native - 1 - r.lastIndex) <= 1) boundary += 1; // informative region: native frame count within 1 of the last index
  });
  assert.equal(diff, 0, `${diff} of ${cases.length} cases differ from the engine`);
  assert.ok(boundary > 500, `only ${boundary} cases around the last index`);
  assert.ok(engine.some(Boolean) && engine.some((v) => !v));
  const missing = makeConfig();
  missing.transitions = [{id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree', tail: {startFrom: 3}}];
  assert.ok(has(collectIssues(missing), 'tail.editorialFrames'));
});

// ---------------------------------------------------------------------------------------------------- 5
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

test('5: master finals are bound to receipts: a relabelled preview is refused, a real receipt binds, a changed receipt is refused', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const {requireReceiptBinding} = require(path.join(KIT, 'lib', 'stage.cjs'));
  const review = rd(path.join(EDITORIAL, 'review-hd-v008', 'config', 'review-config-v008.json'));
  const events = rd(path.join(EDITORIAL, 'review-hd-v008', 'events-v008.json'));
  const master = {...rd(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json')), master_ready: true, missing_shots: [], missing_tails: []};
  const relabel = structuredClone(master);
  const seg = relabel.dialogue[0].segments[0];
  seg.source_kind = 'shot-final-4k';
  seg.restored.source_kind = 'shot-final-4k';
  assert.throws(() => adaptMaster(review, events, relabel), /differ from the restored evidence|relabelled/);
  // a real final: file + shot receipt that attests it
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-final-'));
  try {
    const clip = path.join(dir, 'S01_A-core-3840x2160.mp4');
    fs.writeFileSync(clip, 'not really a video, only bytes for hashing');
    const clipSha = sha256(fs.readFileSync(clip));
    const receiptPath = path.join(dir, 'shot.json');
    fs.writeFileSync(receiptPath, JSON.stringify({status: 'COMPLETED', shot_id: 'S01_A', path: clip, sha256: clipSha, frame_count: 120}));
    const good = structuredClone(master);
    const g = good.dialogue[0].segments[0];
    Object.assign(g, {path: clip, sha256: clipSha, source_kind: 'shot-final-4k'});
    g.restored = {...g.restored, source_kind: 'shot-final-4k', final_path: clip, final_sha256: clipSha};
    const kit = adaptMaster(review, events, good);
    const binding = kit.bindings.shots.S01_A.segments.S01_A;
    assert.equal(binding.preview, false);
    assert.deepEqual([binding.receipt.path, binding.receipt.binds], [receiptPath, clipSha]);
    assert.doesNotThrow(() => requireReceiptBinding(binding, 'picture', 'S01_A'));
    // tampered receipt content (hash changed) and a receipt attesting another file
    fs.writeFileSync(receiptPath, JSON.stringify({status: 'COMPLETED', shot_id: 'S01_A', path: clip, sha256: clipSha, frame_count: 121}));
    assert.throws(() => requireReceiptBinding(binding, 'picture', 'S01_A'), /missing or changed/);
    assert.throws(() => requireReceiptBinding({...binding, receipt: {...binding.receipt, sha256: sha256(fs.readFileSync(receiptPath)), binds: 'f'.repeat(64)}}, 'picture', 'S01_A'), /attests/);
    assert.throws(() => requireReceiptBinding({path: clip, sha256: clipSha, preview: false}, 'picture', 'S01_A'), /no receipt binding/);
    assert.doesNotThrow(() => requireReceiptBinding({path: clip, sha256: clipSha, preview: true}, 'picture', 'S01_A'), 'previews need no receipt');
    // a receipt for a different clip: the adapter refuses
    fs.writeFileSync(receiptPath, JSON.stringify({status: 'COMPLETED', shot_id: 'S01_A', path: clip, sha256: 'e'.repeat(64)}));
    assert.throws(() => adaptMaster(review, events, good), /shot receipt sha256 differs from the clip/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- 6
test('6: the sparkle burst (peak +- peakSpan) may not reach the first spoken word (rule dip_sparkle_before_first_word)', () => {
  const c = lateDip();
  c.waivers = [];
  // schedule peak at t=3 (f93), first word f92: the peak rule fires, not the sparkle rule
  assert.ok(has(collectIssues(c), 'dip_peak_before_first_word') && !has(collectIssues(c), 'dip_sparkle'));
  c.shots[1].words[0].startF = 94; // peak f93 < 94 but 93 + peakSpan(1) >= 94
  const issues = collectIssues(c);
  assert.ok(has(issues, 'dip_sparkle_before_first_word') && !has(issues, 'dip_peak_before_first_word'), issues.join('|'));
  c.shots[1].words[0].startF = 95;
  c.shots[1].words[1].startF = 105;
  assert.deepEqual(collectIssues(c), []);
  const noSparkles = lateDip();
  noSparkles.waivers = [];
  noSparkles.shots[1].words[0].startF = 94;
  noSparkles.motion = {dip: {sparkles: 0}};
  assert.deepEqual(collectIssues(noSparkles), [], 'without sparkles the reach is 0');
  const widened = lateDip();
  widened.waivers = [];
  widened.shots[1].words[0].startF = 95;
  widened.motion = {dip: {peakSpan: 2}};
  assert.ok(has(collectIssues(widened), 'dip_sparkle_before_first_word'));
});

// ---------------------------------------------------------------------------------------------------- 7
test('7: run_parity refuses a missing pin before it renders anything unless --pin / --update-regression', () => {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-par-'));
  try {
    const r = spawnSync('python', ['-I', path.join(KIT, 'episodes', 'ep04', 'run_parity.py'), '--work', path.join(work, 'w'), '--report-dir', path.join(work, 'report')], {encoding: 'utf8', timeout: 60000});
    assert.notEqual(r.status, 0);
    assert.match(r.stderr + r.stdout, /pin file .* is missing|--pin/);
    assert.ok(!fs.existsSync(path.join(work, 'w', 'kit-review-stills')), 'nothing was rendered');
  } finally {
    fs.rmSync(work, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- 8
test('8: superseded section files are gone (the current one is checked in round6)', () => {
  assert.ok(!fs.existsSync(path.join(KIT, 'SKILL-SECTION-r4.md')));
  assert.ok(!fs.existsSync(path.join(KIT, 'SKILL-SECTION-r5.md')));
});
