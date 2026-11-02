// Round 6 (re-critic F1-F7).
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
import {collectIssues, collectWaived, firstSpoken} from '../src/validate.mjs';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const require = createRequire(import.meta.url);
const has = (issues, text) => issues.some((i) => i.includes(text));
const EDITORIAL = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const haveBuilds = fs.existsSync(path.join(EDITORIAL, 'review-hd-v011')) && fs.existsSync(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
const sha256 = (data) => crypto.createHash('sha256').update(data).digest('hex');

// ---------------------------------------------------------------------------------------------------- F1
test('F1: staging re-reads receipt CONTENT: a text file that names the clip hash is not a receipt', () => {
  const {requireReceiptBinding} = require(path.join(KIT, 'lib', 'stage.cjs'));
  const {TAIL_MAP_SCHEMA} = require(path.join(KIT, 'lib', 'receipts.cjs'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-rc-'));
  try {
    const clip = path.join(dir, 'clip.mp4');
    fs.writeFileSync(clip, 'clip bytes');
    const clipSha = sha256(fs.readFileSync(clip));
    const make = (kind, doc, transition) => {
      const file = path.join(dir, `${kind}-${Math.random().toString(16).slice(2)}.json`);
      fs.writeFileSync(file, typeof doc === 'string' ? doc : JSON.stringify(doc));
      return {path: clip, sha256: clipSha, preview: false, receipt: {kind, path: file, sha256: sha256(fs.readFileSync(file)), binds: clipSha, transition}};
    };
    for (const kind of ['shot', 'seam', 'tail']) {
      const garbage = make(kind, `THIS IS NOT A RECEIPT ${clipSha}`, 'T1');
      assert.throws(() => requireReceiptBinding(garbage, 'picture', 'x'), /not a JSON receipt/, `${kind}: garbage text with the right hash was accepted`);
      const hollow = make(kind, {note: clipSha}, 'T1'); // JSON that merely mentions the hash
      assert.throws(() => requireReceiptBinding(hollow, 'picture', 'x'), /shot receipt status|seam-blend receipt schema|neither the tail map|tail map has/, `${kind}: hollow JSON accepted`);
    }
    assert.doesNotThrow(() => requireReceiptBinding(make('shot', {status: 'COMPLETED', sha256: clipSha, path: clip}), 'picture', 'x'));
    assert.throws(() => requireReceiptBinding(make('shot', {status: 'COMPLETED', sha256: clipSha, path: path.join(dir, 'other.mp4')}), 'picture', 'x'), /path is not the bound clip/);
    assert.throws(() => requireReceiptBinding(make('shot', {status: 'PENDING', sha256: clipSha, path: clip}), 'picture', 'x'), /not COMPLETED/);
    assert.doesNotThrow(() => requireReceiptBinding(make('seam', {schema: 'seam-blend-receipt/v002', output: {sha256: clipSha}}), 'picture', 'x'));
    assert.throws(() => requireReceiptBinding(make('seam', {schema: 'something/v9', output: {sha256: clipSha}}), 'picture', 'x'), /schema/);
    assert.doesNotThrow(() => requireReceiptBinding(make('tail', {schema: TAIL_MAP_SCHEMA, tails: [{transition: 'T1', clip_sha256: clipSha}, {transition: 'T2', clip_sha256: 'e'.repeat(64)}]}, 'T1'), 'tail', 'x'));
    assert.throws(() => requireReceiptBinding(make('tail', {schema: TAIL_MAP_SCHEMA, tails: [{transition: 'T2', clip_sha256: clipSha}]}, 'T1'), 'tail', 'x'), /tail map has 0 rows/);
    assert.throws(() => requireReceiptBinding(make('tail', {schema: TAIL_MAP_SCHEMA, tails: [{transition: 'T1', clip_sha256: clipSha}, {transition: 'T1', clip_sha256: clipSha}]}, 'T1'), 'tail', 'x'), /tail map has 2 rows/);
    assert.doesNotThrow(() => requireReceiptBinding(make('tail', {status: 'COMPLETED', sha256: clipSha}, 'T1'), 'tail', 'x'));
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- F2
function dipWithOnset(speechOnsetF, captionFirst) {
  const c = makeConfig();
  c.shots[1].words = [{w: 'Hi', startF: captionFirst, endF: captionFirst + 8, keyword: false}, {w: 'moon', startF: captionFirst + 24, endF: captionFirst + 32, keyword: true}];
  if (speechOnsetF !== undefined) {
    c.shots[1].speechOnsetF = speechOnsetF;
    c.shots[1].onsetEvidence = 'word-timing test onset_fix';
  }
  const schedule = [{t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'none', white: 1}, {t: 2, shot: 'in', white: 0.6}, {t: 3, shot: 'in', white: 0.3}];
  c.transitions = [{id: 'D', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 89, tail: {startFrom: 0, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, schedule}];
  return c;
}

test('F2: the first spoken frame comes from the onset evidence when present, from the caption start (said so) otherwise', () => {
  // caption starts on the unvoiced pre-roll (f92); the peak is f91, sparkle reach f92: caption-based refuses...
  const caption = collectIssues(dipWithOnset(undefined, 92));
  assert.ok(has(caption, 'dip_sparkle_before_first_word') && has(caption, 'caption start (caption-based)'), caption.join('|'));
  // ...but the measured voiced onset is f100: the same config passes
  assert.deepEqual(collectIssues(dipWithOnset(100, 92)), []);
  // evidence can also be stricter than the caption: onset f91 means the peak (f91) hides it
  const stricter = collectIssues(dipWithOnset(91, 100));
  assert.ok(has(stricter, 'dip_peak_before_first_word') && has(stricter, 'onset evidence (word-timing test onset_fix)'), stricter.join('|'));
  const shot = dipWithOnset(100, 92).shots[1];
  assert.deepEqual(firstSpoken(shot), {frame: 100, basis: 'onset evidence (word-timing test onset_fix)'});
  assert.equal(firstSpoken({words: [{startF: 7}, {startF: 3}]}).basis, 'caption start (caption-based)');
  const outside = dipWithOnset(500, 92);
  assert.ok(has(collectIssues(outside), 'speechOnsetF must be an integer inside the shot window'));
});

test('F2: the adapter carries the word-timing onset evidence (onset_fix) when the build names a word-timing file that has it', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const load = (v) => adapt(rd(path.join(EDITORIAL, `review-hd-${v}`, 'config', `review-config-${v}.json`)), rd(path.join(EDITORIAL, `review-hd-${v}`, `events-${v}.json`)));
  const withEvidence = load('v011');
  const s04a = withEvidence.shots.find((s) => s.id === 'S04_A');
  assert.equal(s04a.speechOnsetF, 1033);
  assert.match(s04a.onsetEvidence, /onset_fix/);
  assert.deepEqual(collectIssues(withEvidence), []);
  const noEvidence = load('v010');
  assert.equal(noEvidence.shots.find((s) => s.id === 'S04_A').speechOnsetF, undefined);
  assert.ok(has(collectIssues(noEvidence), 'caption start (caption-based)'));
});

// ---------------------------------------------------------------------------------------------------- F3
test('F3: master tail fields come from the master tail_source (first_native_index, native_editorial_frames, native_total_frames)', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const review = rd(path.join(EDITORIAL, 'review-hd-v008', 'config', 'review-config-v008.json'));
  const events = rd(path.join(EDITORIAL, 'review-hd-v008', 'events-v008.json'));
  const master = rd(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
  const kit = adaptMaster(review, events, master, {preview: true});
  const tails = Object.fromEntries(kit.transitions.filter((x) => x.tail).map((x) => [x.id, x.tail]));
  for (const t2 of master.motion.transitions.filter((x) => x.tail_source)) {
    const s = t2.tail_source;
    assert.deepEqual(tails[t2.id], {startFrom: t2.outgoing_tail.start_from_frame, editorialFrames: s.native_editorial_frames - s.first_native_index, fileFrames: s.native_total_frames - s.first_native_index, verifiedFrames: t2.outgoing_tail.tail_output_frames});
  }
  const lies = structuredClone(master);
  const ts = lies.motion.transitions.find((x) => x.tail_source).tail_source;
  ts.first_native_index = 0; // a full-length native clip: the editorial cut would sit at 100 inside the file, startFrom 0 no longer matches
  assert.throws(() => adaptMaster(review, events, lies, {preview: true}), /start_from_frame .* does not match/);
  const noFields = structuredClone(master);
  delete noFields.motion.transitions.find((x) => x.tail_source).tail_source.first_native_index;
  assert.throws(() => adaptMaster(review, events, noFields, {preview: true}), /lacks first_native_index/);
});

test('F3: a bound tail file must have exactly the frame count the config describes (a full native clip where a tail core is expected is refused)', () => {
  const {checkTailFile} = require(path.join(KIT, 'lib', 'tailcheck.cjs'));
  if (spawnSync('ffmpeg', ['-version'], {encoding: 'utf8'}).error) return;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-tf-'));
  try {
    const clip = path.join(dir, 'full.mp4');
    const r = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=24', '-frames:v', '12', '-pix_fmt', 'yuv420p', clip], {encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    const base = {fps: 30, startFrom: 0, n: 3, editorialFrames: 0};
    assert.ok(checkTailFile(clip, {...base, fileFrames: 12, label: 'ok'}).ok);
    assert.throws(() => checkTailFile(clip, {...base, fileFrames: 5, label: 'full'}), /has 12 frames, the config describes 5/);
    assert.ok(checkTailFile(clip, {...base, label: 'no-claim'}).ok, 'fileFrames stays optional for the generic kit');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- F4 / F5 / F7 (render gates)
function reproWaiverConfig() {
  const c = makeConfig();
  c.shots[1].words = [{w: 'Hi', startF: 92, endF: 100, keyword: false}, {w: 'moon', startF: 104, endF: 112, keyword: true}];
  const schedule = [{t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'out_tail', white: 0.8}, {t: 2, shot: 'out_tail', white: 0.9}, {t: 3, shot: 'none', white: 1}, {t: 4, shot: 'in', white: 0.8}];
  c.transitions = [{id: 'D', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 89, tail: {startFrom: 20, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, schedule}];
  c.waivers = [{rule: 'dip_peak_before_first_word', transition: 'D', reason: 'historical reproduction', reproduction_only: true, review_render_sha256: 'd'.repeat(64)}];
  return c;
}

function renderIn(args, config, {env = {}} = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r6-'));
  const file = path.join(dir, 'c.json');
  fs.writeFileSync(file, JSON.stringify(config));
  const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, '--check-only', ...args.map((a) => a.replace('@DIR', dir))], {encoding: 'utf8', env: {...process.env, REMOTION_BROWSER: '', ...env}});
  fs.rmSync(dir, {recursive: true, force: true});
  return r.stderr;
}

test('F4: --no-preview-mark is gone; --drop-preview-mark and reproduction-only waivers need --reproduction-only DIR with every output inside it', () => {
  const c = reproWaiverConfig();
  assert.deepEqual(collectIssues(c), [], 'a reproduction-only waiver is valid config');
  assert.equal(collectWaived(c)[0].reproduction_only, true);
  for (const mode of ['review', 'master']) {
    assert.match(renderIn(['--mode', mode, '--no-preview-mark', '--still', '100'], makeConfig()), /--no-preview-mark was removed/);
  }
  assert.match(renderIn(['--still', '100', '--out', '@DIR/o.png'], c), /reproduction-only waivers .* are not approvals: the render needs --reproduction-only DIR/);
  // reproduction dir given but the output is elsewhere / not given
  assert.match(renderIn(['--still', '100', '--out', path.join(os.tmpdir(), 'elsewhere.png'), '--reproduction-only', '@DIR'], c), /must be given and lie inside that directory/);
  assert.match(renderIn(['--still', '100', '--reproduction-only', '@DIR'], c), /must be given and lie inside that directory/);
  // inside: the gates pass (the run then stops at the missing browser: the kit searches for none)
  assert.match(renderIn(['--still', '100', '--out', '@DIR/o.png', '--reproduction-only', '@DIR'], c), /no browser: pass --browser PATH or set REMOTION_BROWSER/);
  // master mode still refuses reproduction waivers outside stills
  assert.match(renderIn(['--mode', 'master', '--range', '0-100', '--out', '@DIR/o.mp4', '--reproduction-only', '@DIR'], c), /refuses waived rules/);
});

test('F7: the kit does not search episode folders for a browser (flag or REMOTION_BROWSER only)', () => {
  const c = makeConfig();
  assert.match(renderIn(['--out', '@DIR/o.mp4'], c), /no browser: pass --browser PATH or set REMOTION_BROWSER/);
  assert.match(renderIn(['--out', '@DIR/o.mp4', '--browser', path.join(os.tmpdir(), 'no-such-browser.exe')], c), /browser not found/);
  const src = fs.readFileSync(path.join(KIT, 'render.cjs'), 'utf8');
  assert.doesNotMatch(src, /review-hd|JennieJoyKids-Story|readdirSync/);
});

// ---------------------------------------------------------------------------------------------------- F5
test('F5: approved_at must be a REAL calendar date; a reproduction-only waiver carries no approval fields', () => {
  const base = () => {
    const c = reproWaiverConfig();
    c.waivers = [{rule: 'dip_peak_before_first_word', transition: 'D', reason: 'x', approved_by: 'someone', approved_at: '2026-10-27', review_render_sha256: 'd'.repeat(64)}];
    return c;
  };
  assert.deepEqual(collectIssues(base()), []);
  for (const bad of ['2026-02-30', '2026-13-01', '2026-00-10', '2026-10-32', '27/10/2026', 'yesterday', '']) {
    const c = base();
    c.waivers[0].approved_at = bad;
    assert.ok(has(collectIssues(c), 'needs reason, review_render_sha256'), `approved_at ${JSON.stringify(bad)} accepted`);
  }
  const withTime = base();
  withTime.waivers[0].approved_at = '2026-10-27T10:30:00Z';
  assert.deepEqual(collectIssues(withTime), []);
  const leap = base();
  leap.waivers[0].approved_at = '2028-02-29';
  assert.deepEqual(collectIssues(leap), []);
  const notLeap = base();
  notLeap.waivers[0].approved_at = '2026-02-29';
  assert.ok(has(collectIssues(notLeap), 'needs reason, review_render_sha256'));
  // reproduction-only means "not an approval": approval fields next to it are refused
  const mixed = reproWaiverConfig();
  mixed.waivers[0].approved_by = 'someone';
  assert.ok(has(collectIssues(mixed), 'needs reason, review_render_sha256'));
});

test('F5: the ep04 adapter option --waiver-reproduction-only invents no approval fields', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const v8 = path.join(EDITORIAL, 'review-hd-v008');
  const kit = adapt(rd(path.join(v8, 'config', 'review-config-v008.json')), rd(path.join(v8, 'events-v008.json')), {historicalWaivers: {reproduction_only: true, review_render_sha256: 'a'.repeat(64)}});
  assert.equal(kit.waivers.length, 3);
  assert.ok(kit.waivers.every((w) => w.reproduction_only === true && w.approved_by === undefined && w.approved_at === undefined));
  assert.deepEqual(collectIssues(kit), []);
  const src = fs.readFileSync(path.join(KIT, 'episodes', 'ep04', 'run_parity.py'), 'utf8');
  assert.doesNotMatch(src, /approved-by|approved_by/);
  assert.match(src, /--waiver-reproduction-only/);
});

// ---------------------------------------------------------------------------------------------------- F7 / section
test('F7: numeric dip / shot literals (T10xx ids, 1010 / 1310 / 1610) are in the literal patterns and the kit has none', () => {
  const text = fs.readFileSync(path.join(KIT, 'tests', 'no-episode-literals.test.mjs'), 'utf8');
  assert.match(text, /1010\|1310\|1610/);
  assert.match(text, /T\\d\{3,4\}/);
});

test('section: older section files stay deleted (the current one is checked in round7)', () => {
  for (const old of ['r4', 'r5', 'r6']) assert.ok(!fs.existsSync(path.join(KIT, `SKILL-SECTION-${old}.md`)), old);
});
