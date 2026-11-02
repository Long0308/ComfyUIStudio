// Round 4 (re-critic F1-F13). Each test was written to fail against the round-3 kit first.
import test from 'node:test';
import {withBound, withBoundMaster} from './builds.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {TYPE_TABLE, collectIssues} from '../src/validate.mjs';
import {resolveMotion} from '../src/presets.mjs';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const require = createRequire(import.meta.url);
const has = (issues, text) => issues.some((i) => i.includes(text));
const one = (t) => {
  const c = makeConfig();
  c.transitions = [t];
  return c;
};
const wipe = (over = {}) => ({id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree', tail: {startFrom: 3, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, ...over});

// ---------------------------------------------------------------------------------------------------- F1
test('F1: a tail-only transition needs a real outgoing shot whose end is the boundary (P05b, P06)', () => {
  assert.deepEqual(collectIssues(one(wipe())), []);
  for (const type of ['dissolve', 'cloud', 'bubble', 'wipe']) {
    const ghost = one(wipe({id: 'G', type, seed: 3, centre: [1, 1], from: 'NOWHERE'}));
    assert.ok(has(collectIssues(ghost), "'from' NOWHERE is not a shot or last segment"), `${type} accepted an unresolvable from`);
    const mid = one(wipe({id: 'M', type, seed: 3, centre: [1, 1], from: 'X2a'})); // ends at 130, not 90
    assert.ok(has(collectIssues(mid), 'is not the end of the outgoing shot'), `${type} accepted a from that ends elsewhere`);
  }
});

// ---------------------------------------------------------------------------------------------------- F3
test('F3: the whip extender strip must really cover the exposed side for every offset of the schedule', async () => {
  const {whipCoverage, whipSteps} = await import('../src/picture-mode.mjs');
  const c = makeConfig();
  assert.deepEqual(collectIssues(c), []);
  const motion = resolveMotion(c);
  const steps = whipSteps(c.transitions[0], motion);
  assert.equal(steps.length, 8);
  assert.ok(steps.every((s) => whipCoverage(s.offset, s.zoomK, motion).covered));
  const narrow = makeConfig({motion: {whip: {extenderWidth: 100}}});
  assert.ok(has(collectIssues(narrow), 'extender strip does not cover'), 'a too-narrow strip must be refused');
  const cov = whipCoverage(-720, 1, {...motion, whip: {...motion.whip, extenderWidth: 100}});
  assert.ok(!cov.covered && cov.gapPx > 0);
  // the rendered box is the one that was checked: WhipTiles throws instead of drawing an uncovered strip
  const src = fs.readFileSync(path.join(KIT, 'src', 'transitions.jsx'), 'utf8');
  assert.match(src, /whipCoverage\(/);
});

// ---------------------------------------------------------------------------------------------------- F4
test('F4: the master must match the kit clock (shot start/frames, segment frames, transition boundaries)', () => {
  const E = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
  const reviewCfg = path.join(E, 'review-hd-v008', 'config', 'review-config-v008.json');
  const masterCfg = path.join(E, 'master-4k-v002', 'config', 'master-config-v002.json');
  if (!fs.existsSync(reviewCfg) || !fs.existsSync(masterCfg)) return;
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
  const review = rd(reviewCfg);
  const events = rd(path.join(E, 'review-hd-v008', 'events-v008.json'));
  const master = {...rd(masterCfg), master_ready: true, missing_shots: [], missing_tails: []};
  const mutate = (fn) => {
    const m = structuredClone(master);
    fn(m);
    return m;
  };
  assert.throws(() => adaptMaster(review, events, mutate((m) => { m.dialogue[3].start_frame += 1; })), /clock differs.*start_frame/);
  assert.throws(() => adaptMaster(review, events, mutate((m) => { m.dialogue[3].duration_frames += 1; })), /clock differs.*duration_frames/);
  assert.throws(() => adaptMaster(review, events, mutate((m) => { m.dialogue[11].segments[1].delivery_frames += 5; })), /clock differs.*delivery_frames/);
  assert.throws(() => adaptMaster(review, events, mutate((m) => { m.dialogue[11].segments[1].relative_start_frame += 5; })), /clock differs.*relative_start_frame/);
  assert.throws(() => adaptMaster(review, events, mutate((m) => { m.motion.transitions.find((t) => t.type === 'whip').boundary += 2; })), /clock differs.*boundary/);
  assert.doesNotThrow(() => adaptMaster(review, events, master));
});

test('F4: segment clips are probed for frame count (strict for final sources, reported for previews)', () => {
  const {checkSegmentFile} = require(path.join(KIT, 'lib', 'tailcheck.cjs'));
  const ff = spawnSync('ffmpeg', ['-version'], {encoding: 'utf8'});
  if (ff.error) return;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-seg-'));
  try {
    const clip = path.join(dir, 's.mp4');
    const r = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=24', '-frames:v', '12', '-pix_fmt', 'yuv420p', clip], {encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    assert.ok(checkSegmentFile(clip, {fps: 30, frames: 15, label: 'ok'}).ok); // 15 delivery frames = ceil(12) native
    assert.throws(() => checkSegmentFile(clip, {fps: 30, frames: 20, label: 'short'}), /segment short/);
    const soft = checkSegmentFile(clip, {fps: 30, frames: 20, label: 'slate', strict: false});
    assert.equal(soft.ok, false);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- F5
function dipAt(peakT, firstWordRel) {
  const c = makeConfig();
  c.shots[1].words = [{w: 'Hi', startF: 90 + firstWordRel, endF: 90 + firstWordRel + 8, keyword: false}, {w: 'moon', startF: 90 + firstWordRel + 12, endF: 90 + firstWordRel + 20, keyword: true}];
  const schedule = [{t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'out_tail', white: 0.8}];
  const rest = [];
  for (let t = 2; t <= 8; t += 1) rest.push(t < peakT ? {t, shot: 'out_tail', white: 0.9} : t === peakT ? {t, shot: 'none', white: 1} : {t, shot: 'in', white: 0.5});
  // keep the out_tail rows contiguous from 0 (peak at t>=2)
  c.transitions = [{id: 'D', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: 9, direction: 0, start: 89, tail: {startFrom: 20, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, schedule: [...schedule, ...rest]}];
  c.transitions[0].frames = c.transitions[0].schedule.length;
  return c;
}

test('F5: the dip white peak must come before the incoming shot first spoken word', () => {
  const late = dipAt(3, 2); // peak B+3, first word B+2: the known v008 defect
  assert.ok(has(collectIssues(late), 'dip_peak_before_first_word'));
  const equal = dipAt(2, 2); // peak on the first word frame: still hides it
  assert.ok(has(collectIssues(equal), 'dip_peak_before_first_word'));
  assert.deepEqual(collectIssues(dipAt(2, 4)), []); // peak B+2, sparkle reach B+3, word B+4
});

test('F5: a recorded waiver keeps a historical config renderable and is reported, never silent', async () => {
  const {collectWaived} = await import('../src/validate.mjs');
  const c = dipAt(3, 2);
  assert.ok(has(collectIssues(c), 'dip_peak_before_first_word'));
  c.waivers = [{rule: 'dip_peak_before_first_word', transition: 'D', reason: 'historical reproduction', approved_by: 'test', approved_at: '2026-10-27', review_render_sha256: 'b'.repeat(64)}];
  assert.deepEqual(collectIssues(c), []);
  assert.equal(collectWaived(c).length, 1);
  const noReason = dipAt(3, 2);
  noReason.waivers = [{rule: 'dip_peak_before_first_word', transition: 'D', reason: ''}];
  assert.ok(has(collectIssues(noReason), 'waiver'));
});

test('F5: what the rules say about the real review builds (v008 late peak; later builds: sparkle burst reaches the first word)', async (t) => {
  const E = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
  if (!fs.existsSync(path.join(E, 'review-hd-v008'))) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
  const verdict = {};
  for (const v of ['v008', 'v009', 'v010', 'v011']) {
    const dir = path.join(E, `review-hd-${v}`);
    if (!fs.existsSync(path.join(dir, 'config', `review-config-${v}.json`))) continue;
    const kit = adapt(rd(path.join(dir, 'config', `review-config-${v}.json`)), rd(path.join(dir, `events-${v}.json`)));
    const issues = collectIssues(kit);
    verdict[v] = {peak: issues.filter((i) => i.includes('dip_peak_before_first_word')).length, sparkle: issues.filter((i) => i.includes('dip_sparkle_before_first_word')).length};
  }
  console.log(`# dip peak rule, issues per build: ${JSON.stringify(verdict)}`);
  assert.deepEqual(verdict.v008, {peak: 3, sparkle: 0}, 'v008 has three late peaks (T1010, T1310, T1610)');
  // the later builds put the peak one frame before the first word, but the sparkle burst (peak +- 1) still reaches the word frame
  for (const v of ['v009', 'v010']) if (v in verdict) assert.deepEqual(verdict[v], {peak: 0, sparkle: 3}, `${v}: sparkle reach`);
  // the build whose first words come later passes both rules
  if ('v011' in verdict) assert.deepEqual(verdict.v011, {peak: 0, sparkle: 0}, 'v011 passes');
});

// ---------------------------------------------------------------------------------------------------- F6
test('F6: --preview is only for stills / ranges in every mode (a full review render is refused too)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r4-'));
  const file = path.join(dir, 'c.json');
  fs.writeFileSync(file, JSON.stringify(makeConfig()));
  for (const mode of ['review', 'master']) {
    const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, '--mode', mode, '--preview', '--check-only'], {encoding: 'utf8'});
    assert.match(r.stderr, /never a full (master|film) render|limited to stills or a --range/, `${mode}: ${r.stderr.slice(0, 200)}`);
  }
  fs.rmSync(dir, {recursive: true, force: true});
});

// ---------------------------------------------------------------------------------------------------- F10
// F10 (TYPE_TABLE == the engine's TYPE_PROPERTIES, read as python source text) is replaced by tests/catalog-sync.test.mjs: the kit's table
// is derived from the catalog JSON, and a test loads the engine's own presets module and compares every preset.

// ---------------------------------------------------------------------------------------------------- F11
test('F11: engine row rules (even whip / bloom frames, dip frames == schedule length, none <=> 0 frames)', () => {
  const odd = makeConfig();
  odd.transitions[0].frames = 7;
  odd.transitions[0].outFrames = 3;
  odd.transitions[0].inFrames = 4;
  assert.ok(has(collectIssues(odd), 'whip needs an even frame count'));
  const bloomOdd = makeConfig();
  bloomOdd.transitions.push({id: 'B', type: 'bloom', boundary: 30, from: 'INTRO', to: 'X1', frames: 5, direction: 0, start: 28});
  assert.ok(has(collectIssues(bloomOdd), 'bloom needs an even frame count'));
  const dip = dipAt(2, 3);
  dip.transitions[0].frames = 8;
  assert.ok(has(collectIssues(dip), 'dip_white frames'));
  const none = makeConfig();
  none.transitions.push({id: 'N', type: 'none', boundary: 90, from: 'X1', to: 'X2a', frames: 3, direction: 0, start: 90});
  assert.ok(has(collectIssues(none), 'none needs frames 0'));
  const notNone = makeConfig();
  notNone.transitions[0].frames = 0;
  assert.ok(has(collectIssues(notNone), 'frames must be greater than 0'));
});

// ---------------------------------------------------------------------------------------------------- F12
test('F12: from / to of every transition name a real shot, segment or graphic (INTRO, OUTRO, CARD_<term>, END_PLATE, ENDLOGO)', () => {
  const c = makeConfig();
  c.transitions.push({id: 'CS', type: 'card_slide', boundary: 180, from: 'CARD_Moon', to: 'CARD_Sun', frames: 6, direction: -1, start: 180});
  c.transitions.push({id: 'PI', type: 'plate_in', boundary: 236, from: 'CARD_Star', to: 'END_PLATE', frames: 4, direction: 0, start: 236});
  assert.deepEqual(collectIssues(c), []);
  const bad = makeConfig();
  bad.transitions.push({id: 'CS', type: 'card_slide', boundary: 180, from: 'CARD_Moon', to: 'CARD_Nope', frames: 6, direction: -1, start: 180});
  assert.ok(has(collectIssues(bad), "'to' CARD_Nope is not a known shot, segment or graphic"));
  const bloom = makeConfig();
  bloom.transitions.push({id: 'B', type: 'bloom', boundary: 30, from: 'LOBBY', to: 'X1', frames: 6, direction: 0, start: 27});
  assert.ok(has(collectIssues(bloom), "'from' LOBBY is not a known shot, segment or graphic"));
  const plate = makeConfig();
  plate.transitions.push({id: 'PI', type: 'plate_in', boundary: 236, from: 'CARD_Star', to: 'SOMEWHERE', frames: 4, direction: 0, start: 236});
  assert.ok(has(collectIssues(plate), "'to' SOMEWHERE is not a known"));
});
