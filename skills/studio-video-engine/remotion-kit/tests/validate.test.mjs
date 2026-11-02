import test from 'node:test';
import {withBound, withBoundMaster} from './builds.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {TRANSITION_TYPES, collectIssues, collectSourceIssues, validateConfig, totalFrames} from '../src/validate.mjs';
import {auditPictureLayers, pictureMode, transitionIndex, whipGeometry} from '../src/picture-mode.mjs';
import {DEFAULT_MOTION, deepMerge, resolveMotion, unknownKeys} from '../src/presets.mjs';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const W = {approved_by: 'test-suite', approved_at: '2026-10-27', review_render_sha256: 'a'.repeat(64)}; // explicit waiver approval fields
const has = (issues, text) => issues.some((i) => i.includes(text));

test('a synthetic episode with different numbers validates (the kit is not bound to ep04)', () => {
  const c = makeConfig();
  assert.deepEqual(collectIssues(c), []);
  assert.equal(totalFrames(c), 270);
});

test('clock: a gap, a wrong total and a mismatching clock table are refused', () => {
  const c = makeConfig();
  c.shots[1].start = 95;
  assert.ok(has(collectIssues(c), 'contiguous'));
  const d = makeConfig();
  d.timeline.mainFrames = 250;
  assert.ok(has(collectIssues(d), 'mainFrames'));
  const e = makeConfig({clock: {shotTable: {X1: [30, 60], X2: [90, 61]}}});
  assert.ok(has(collectIssues(e), 'master clock mismatch for X2'));
});

test('cloud / bubble / dissolve are refused without continuity agree, and refused without a tail even WITH it', () => {
  for (const type of ['cloud', 'bubble', 'dissolve', 'wipe']) {
    const c = makeConfig();
    c.transitions.push({id: 'T', type, boundary: 90, from: 'X1', to: 'X2a', frames: 6, direction: 1, start: 90, seed: 7, centre: [10, 10]});
    const t = c.transitions[c.transitions.length - 1];
    assert.ok(has(collectIssues(c), "continuity:'agree'"), `${type} accepted without continuity`);
    t.continuity = 'agree';
    assert.ok(has(collectIssues(c), 'needs an outgoing tail'), `${type} accepted with continuity but no tail (critic M2/M13)`);
    t.tail = {startFrom: 3, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12};
    assert.deepEqual(collectIssues(c).filter((i) => i.includes('continuity') || i.includes('tail')), [], `${type} refused with continuity agree + tail`);
  }
});

test('canonical type vocabulary: aliases are not accepted, shows_both must agree with the type table', () => {
  const c = makeConfig();
  c.transitions[0].type = 'dip';
  assert.ok(has(collectIssues(c), "unknown transition type 'dip'"));
  for (const alias of ['card-slide', 'plate-in']) {
    const d = makeConfig();
    d.transitions[0].type = alias;
    assert.ok(has(collectIssues(d), 'unknown transition type'), alias);
  }
  const e = makeConfig();
  e.transitions[0].shows_both = true; // a whip never shows both
  assert.ok(has(collectIssues(e), 'shows_both true contradicts type whip'));
  const f = makeConfig();
  f.transitions[0].shows_both = false;
  assert.deepEqual(collectIssues(f), []);
  const g = makeConfig();
  g.transitions.push({id: 'T', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 6, direction: 1, start: 90, tail: {startFrom: 1, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, shows_both: false, continuity: 'agree'});
  assert.ok(has(collectIssues(g), 'shows_both false contradicts type wipe'));
  const h = makeConfig();
  h.transitions[0].continuity = 'unknown';
  assert.deepEqual(collectIssues(h), []);
});

test('pictureMode throws if a both-shots transition reaches the renderer without continuity', () => {
  const c = makeConfig();
  const t = {id: 'T', type: 'cloud', boundary: 90, from: 'X1', to: 'X2a', frames: 6, direction: 1, start: 90, seed: 7};
  assert.throws(() => pictureMode({shot: c.shots[1], frame: 1, inT: t, outT: undefined, ending: c.ending, motion: resolveMotion(c)}), /continuity/);
});

function dipConfig(schedule) {
  const c = makeConfig();
  c.transitions.push({
    id: 'D1', type: 'dip_white', boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 89, tail: {startFrom: 20, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, schedule,
  });
  c.transitions = c.transitions.filter((t) => t.id !== 'W1');
  return c;
}
const GOOD_DIP = [
  {t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'out_tail', white: 0.8}, {t: 2, shot: 'none', white: 1},
  {t: 3, shot: 'in', white: 0.8}, {t: 4, shot: 'in', white: 0.4},
];

test('dip-to-white: a good schedule passes the per-frame audit; exactly one shot (or none) per frame', () => {
  const c = dipConfig(GOOD_DIP);
  assert.deepEqual(collectIssues(c), []);
  const motion = resolveMotion(c);
  assert.deepEqual(auditPictureLayers(c, motion), []);
  // count the visible shot pictures on every frame of the window by hand through pictureMode + tails
  const idx = transitionIndex(c);
  for (let f = 88; f < 98; f += 1) {
    const slot = c.shots.find((s) => f >= s.start && f < s.start + s.frames);
    const mode = pictureMode({shot: slot, frame: f - slot.start, inT: idx.incoming(slot), outT: idx.outgoing(slot), ending: c.ending, motion});
    const tail = f >= 90 && f < 92 ? 1 : 0;
    assert.ok((mode.kind === 'hidden' ? 0 : 1) + tail <= 1, `f${f} shows two shots`);
  }
});

test('dip-to-white: two shots in one schedule step, no white peak, or a tail without frames are refused', () => {
  const two = dipConfig([...GOOD_DIP.slice(0, 1), {t: 0, shot: 'out', white: 0.5}, {t: 0, shot: 'in', white: 0.6}, ...GOOD_DIP.slice(3)]);
  // a duplicated t with both out and in: the audit names the frame
  assert.ok(auditPictureLayers(two, resolveMotion(two)).some((v) => v.slot === 'dip-schedule'));
  const noPeak = dipConfig(GOOD_DIP.map((e) => (e.white === 1 ? {...e, white: 0.99} : e)));
  assert.ok(has(collectIssues(noPeak), 'pure-white'));
  const noTail = dipConfig(GOOD_DIP);
  delete noTail.transitions.find((t) => t.id === 'D1').tail;
  assert.ok(has(collectIssues(noTail), 'no tail'));
});

test('dip schedule timing: out only before the boundary, out_tail / in only from it (critic M3)', () => {
  const outAtZero = dipConfig(GOOD_DIP.map((e) => (e.t === 0 ? {...e, shot: 'out'} : e)));
  assert.ok(has(collectIssues(outAtZero), "schedule 'out' at t=0"));
  const tailBefore = dipConfig(GOOD_DIP.map((e) => (e.t === -1 ? {...e, shot: 'out_tail'} : e)));
  assert.ok(has(collectIssues(tailBefore), "'out_tail' at t=-1"));
  const inBefore = dipConfig([...GOOD_DIP, {t: -2, shot: 'in', white: 0.1}]);
  assert.ok(has(collectIssues(inBefore), "'in' at t=-2"));
  const noTail = dipConfig(GOOD_DIP);
  delete noTail.transitions.find((t) => t.id === 'D1').tail;
  assert.ok(has(collectIssues(noTail), 'out_tail frames but the transition has no tail'));
});

test('ending: speechEndFrame may not precede the last dialogue word or the last vocab word', () => {
  const c = makeConfig();
  c.ending.speechEndFrame = 120; // before the last vocab word starts (150 + 60 = 210)
  c.ending.plateStart = 236;
  assert.ok(has(collectIssues(c), 'before the last vocab word starts'));
  const d = makeConfig();
  d.shots[1].words[1].endF = 400;
  assert.ok(has(collectIssues(d), 'before the last dialogue word ends'));
});

test('the per-frame audit catches a real overlap (a dip schedule that puts the tail and the incoming shot on the same frame)', () => {
  // T-E42: a whip no longer mounts a tail (the catalog says tail_frames none), so the overlap is built from a dip schedule that lists
  // the outgoing tail AND the incoming shot on t=1
  const c = dipConfig([
    {t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'out_tail', white: 0.8}, {t: 1, shot: 'in', white: 0.9},
    {t: 2, shot: 'none', white: 1}, {t: 3, shot: 'in', white: 0.4},
  ]);
  const v = auditPictureLayers(c, resolveMotion(c));
  assert.ok(v.length > 0 && v.every((x) => x.layers === 2), JSON.stringify(v.slice(0, 2)));
  assert.ok(has(collectIssues(c), 'shot pictures at once'));
});

test('whip: one full copy of the shot; the flipped, stretched edge strip lies fully outside the shot rect for both directions', () => {
  const motion = resolveMotion(makeConfig());
  for (const offset of [-720, -5, 5, 720]) {
    const g = whipGeometry(offset, motion);
    const stripEnd = g.strip.left + g.strip.width;
    const outside = stripEnd <= g.shotRect.left || g.strip.left >= g.shotRect.left + g.shotRect.width;
    assert.ok(outside && g.outside, `strip overlaps the shot for offset ${offset}`);
    assert.equal(g.right, offset < 0);
  }
  // whip lengths beyond the preset arrays are refused
  const c = makeConfig();
  c.transitions[0].outFrames = 9;
  assert.ok(has(collectIssues(c), 'exceeds motion.whip'));
});

test('motion presets: defaults, overrides merge by leaf, unknown keys are errors, nothing is mutated', () => {
  const before = JSON.stringify(DEFAULT_MOTION);
  const c = makeConfig({motion: {caption: {fontEn: 50}, whip: {zoom: 1.1}}});
  const m = resolveMotion(c);
  assert.equal(m.caption.fontEn, 50);
  assert.equal(m.caption.fontVi, DEFAULT_MOTION.caption.fontVi);
  assert.equal(m.whip.zoom, 1.1);
  assert.deepEqual(m.whip.outOffset, DEFAULT_MOTION.whip.outOffset);
  assert.equal(JSON.stringify(DEFAULT_MOTION), before);
  assert.deepEqual(unknownKeys(DEFAULT_MOTION, {caption: {fontEm: 3}}), ['caption.fontEm']);
  assert.ok(has(collectIssues(makeConfig({motion: {bogus: 1}})), 'motion.bogus'));
  assert.equal(deepMerge({a: [1, 2]}, {a: [3]}).a.length, 1);
});

test('ending: logo disc must clear the vocab pill; plate must start after the last word', () => {
  const c = makeConfig();
  c.ending.discSlideX = 600; // 600 + 430 >= pillLeftX 900
  assert.ok(has(collectIssues(c), 'covers the first vocab pill'));
  const d = makeConfig();
  delete d.ending.pillLeftX;
  assert.ok(has(collectIssues(d), 'pillLeftX'));
  const e = makeConfig();
  e.ending.plateStart = 230; // before speechEndFrame 235.5
  assert.ok(has(collectIssues(e), 'would cover the word while spoken'));
});

test('sources: missing staged names are reported; partial mode tolerates null clips', () => {
  const c = makeConfig();
  const sources = {logo: 'l.png', music: 'm.wav', opening: null, fonts: {regular: 'r', bold: 'b'}, shots: {}, tails: {}, icons: {}, cards: []};
  assert.ok(collectSourceIssues(c, sources).length > 5);
  assert.deepEqual(collectSourceIssues(c, sources, {partial: true}), []);
});

function spawnRender(args, config) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-test-'));
  const file = path.join(dir, 'c.json');
  fs.writeFileSync(file, JSON.stringify(config));
  const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, ...args], {encoding: 'utf8'});
  fs.rmSync(dir, {recursive: true, force: true});
  return r;
}

test('render.cjs: label rule (master has none, review needs it), concurrency <= 2, master needs scale >= 2', () => {
  const c = makeConfig();
  let r = spawnRender(['--mode', 'master', '--label', 'REVIEW x', '--check-only'], c);
  assert.match(r.stderr, /master carries no review label/);
  const noLabel = makeConfig();
  delete noLabel.review;
  r = spawnRender(['--mode', 'review', '--check-only'], noLabel);
  assert.match(r.stderr, /needs config.review.label/);
  r = spawnRender(['--mode', 'review', '--label', 'something else', '--check-only'], c);
  assert.match(r.stderr, /differs from config.review.label/);
  r = spawnRender(['--concurrency', '3', '--check-only'], c);
  assert.match(r.stderr, /concurrency must be 1 or 2/);
  r = spawnRender(['--mode', 'master', '--scale', '1', '--check-only'], c);
  assert.match(r.stderr, /scale >= 2/);
  r = spawnRender(['--mode', 'master', '--preview', '--check-only'], c);
  assert.match(r.stderr, /limited to stills or a --range/);
});

test('ep04 adapter (skipped when the v008 build is absent): maps to a valid kit config on the frozen clock', async (t) => {
  const adapterPath = path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs');
  const {createRequire} = await import('node:module');
  const require = createRequire(import.meta.url);
  const {adapt: adaptRaw, SHOT_TABLE} = require(adapterPath);
  const adapt = withBound(adaptRaw);
  const v008 = path.resolve(KIT, '../../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial', 'review-hd-v008');
  const cfg = path.join(v008, 'config', 'review-config-v008.json');
  if (!fs.existsSync(cfg)) return t.skip('v008 build not present');
  const read = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
  const kit = adapt(read(cfg), read(path.join(v008, 'events-v008.json')), {historicalWaivers: W});
  assert.deepEqual(collectIssues(kit), []);
  assert.equal(totalFrames(kit), 2580);
  assert.deepEqual(Object.fromEntries(kit.shots.map((s) => [s.id, [s.start, s.frames]])), SHOT_TABLE);
  assert.equal(pathToFileURL(adapterPath).protocol, 'file:');
});

// ---- master adapter -----------------------------------------------------------------------------------------------
const EDITORIAL = path.resolve(KIT, '../../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const REVIEW_CFG = path.join(EDITORIAL, 'review-hd-v008', 'config', 'review-config-v008.json');
const EVENTS = path.join(EDITORIAL, 'review-hd-v008', 'events-v008.json');
const MASTER_CFG = path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json');
const readJ = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const haveMaster = fs.existsSync(REVIEW_CFG) && fs.existsSync(MASTER_CFG);

test('master adapter: tail.startFrom comes from the MASTER config for every tail transition (critic H1)', async (t) => {
  if (!haveMaster) return t.skip('ep04 builds not present');
  const {createRequire} = await import('node:module');
  const {adaptMaster: adaptMasterRaw} = createRequire(import.meta.url)(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const master = readJ(MASTER_CFG);
  const review = readJ(REVIEW_CFG);
  const kit = adaptMaster(review, readJ(EVENTS), master, {preview: true, historicalWaivers: W});
  const wanted = master.motion.transitions.filter((x) => x.outgoing_tail);
  assert.ok(wanted.length >= 3);
  for (const m of wanted) {
    const got = kit.transitions.find((x) => x.id === m.id).tail.startFrom;
    assert.equal(got, m.outgoing_tail.start_from_frame, `${m.id} startFrom`);
    const reviewStart = review.motion.transitions.find((x) => x.id === m.id).outgoing_tail.start_from_frame;
    if (m.outgoing_tail.start_from_frame !== reviewStart) assert.notEqual(got, reviewStart, `${m.id} kept the review tail start`);
  }
  assert.deepEqual(collectIssues(kit), []);
  assert.equal(kit.review, undefined);
});

test('master adapter: refuses unless master_ready and nothing missing; preview is an explicit opt-in (critic M-2)', async (t) => {
  if (!haveMaster) return t.skip('ep04 builds not present');
  const {createRequire} = await import('node:module');
  const {adaptMaster: adaptMasterRaw} = createRequire(import.meta.url)(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const review = readJ(REVIEW_CFG);
  const events = readJ(EVENTS);
  const master = readJ(MASTER_CFG);
  assert.throws(() => adaptMaster(review, events, master), /not ready|missing/);
  const readyButMissing = {...structuredClone(master), master_ready: true};
  assert.throws(() => adaptMaster(review, events, readyButMissing), /missing/);
  const tailsMissing = {...structuredClone(master), master_ready: true, missing_shots: []};
  assert.throws(() => adaptMaster(review, events, tailsMissing), /missing 4K tails/);
  const allGood = {...structuredClone(master), master_ready: true, missing_shots: [], missing_tails: []};
  assert.doesNotThrow(() => adaptMaster(review, events, allGood));
  const noStart = structuredClone(allGood);
  delete noStart.motion.transitions.find((x) => x.outgoing_tail).outgoing_tail.start_from_frame;
  assert.throws(() => adaptMaster(review, events, noStart), /start_from_frame/);
});

test('an engine-built events.json (jjv editorial build-config) validates through the ep04 adapter', async (t) => {
  if (!haveMaster) return t.skip('ep04 builds not present');
  const {createRequire} = await import('node:module');
  const {adapt: adaptRaw} = createRequire(import.meta.url)(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  const engineEvents = readJ(path.join(KIT, 'tests', 'fixtures', 'engine-events.json'));
  assert.equal(engineEvents.schema, 'jjv/events/v1');
  assert.ok(engineEvents.transitions.some((x) => x.type === 'dip_white') && engineEvents.transitions.some((x) => x.type === 'card_slide'));
  const kit = adapt(readJ(REVIEW_CFG), engineEvents, {historicalWaivers: W});
  assert.deepEqual(collectIssues(kit), []);
  const types = new Set(kit.transitions.map((x) => x.type));
  for (const type of types) assert.ok(TRANSITION_TYPES.includes(type), type);
  assert.ok(kit.transitions.filter((x) => x.type === 'dip_white').every((x) => x.continuity === 'mismatch'));
  // the same kit config from the older v008 events differs only in the continuity declarations
  const old = adapt(readJ(REVIEW_CFG), readJ(EVENTS), {historicalWaivers: W});
  const strip = (c) => ({...c, transitions: c.transitions.map(({continuity, ...rest}) => rest)});
  assert.deepEqual(strip(kit), strip(old));
});

// ---- round 3: anchoring, contiguity, adjacency, uniqueness, tail files -------------------------------------------------
const wipe = (over = {}) => ({id: 'WP', type: 'wipe', boundary: 90, from: 'X1', to: 'X2a', frames: 12, direction: 1, start: 90, continuity: 'agree', tail: {startFrom: 3, editorialFrames: 0, fileFrames: 30, verifiedFrames: 12}, ...over});
const withTransition = (t) => {
  const c = makeConfig();
  c.transitions = [t];
  return c;
};

test('anchoring: a tail-only transition needs an integer start equal to its boundary and to the incoming shot start (P1, P2)', () => {
  const noStart = wipe();
  delete noStart.start;
  assert.ok(has(collectIssues(withTransition(noStart)), 'start must be an integer'));
  const early = withTransition(wipe({start: 84}));
  assert.ok(has(collectIssues(early), 'must start on its boundary'));
  const wrongBoundary = withTransition(wipe({boundary: 84, start: 84}));
  assert.ok(has(collectIssues(wrongBoundary), 'is not the start of the incoming shot'));
  assert.deepEqual(collectIssues(withTransition(wipe())), []);
  const whipOff = makeConfig();
  whipOff.transitions[0].boundary = 91;
  assert.ok(has(collectIssues(whipOff), 'is not the start of the incoming shot'));
  const irisOff = makeConfig();
  irisOff.transitions[1].boundary = 149;
  assert.ok(has(collectIssues(irisOff), 'is not the end of the outgoing shot'));
});

test('dip out_tail rows must be contiguous from t=0 (P3), and tailWindow is the single window definition', async () => {
  const gap = dipConfig([{t: -1, shot: 'out', white: 0.2}, {t: 0, shot: 'out_tail', white: 0.5}, {t: 1, shot: 'none', white: 1},
    {t: 2, shot: 'out_tail', white: 0.9}, {t: 3, shot: 'in', white: 0.8}, {t: 4, shot: 'in', white: 0.4}]);
  assert.ok(has(collectIssues(gap), 'contiguous t=0..n-1'));
  const {tailWindow, tailLayers} = await import('../src/picture-mode.mjs');
  const good = dipConfig(GOOD_DIP);
  const d1 = good.transitions.find((t) => t.id === 'D1');
  assert.deepEqual(tailWindow(d1), {from: 90, frames: 2});
  assert.deepEqual(tailLayers(good).map((l) => [l.t.id, l.from, l.frames]), [['D1', 90, 2]]);
  assert.deepEqual(tailWindow(wipe()), {from: 90, frames: 12});
});

test('engine alignment: card_slide and plate_in show both sides; continuity is only needed next to a picture shot (M3)', () => {
  const cards = makeConfig();
  cards.transitions.push({id: 'CS', type: 'card_slide', boundary: 180, from: 'CARD_Moon', to: 'CARD_Sun', frames: 6, direction: -1, start: 180, shows_both: true});
  cards.transitions.push({id: 'PI', type: 'plate_in', boundary: 236, from: 'CARD_Star', to: 'END_PLATE', frames: 4, direction: 0, start: 236, shows_both: true, continuity: 'unknown'});
  assert.deepEqual(collectIssues(cards), [], 'between two graphics a both-sides type is allowed without continuity');
  const next = makeConfig();
  next.transitions.push({id: 'PS', type: 'plate_in', boundary: 90, from: 'X1', to: 'END_PLATE', frames: 4, direction: 0, start: 90, shows_both: true});
  assert.ok(has(collectIssues(next), "picture shot is on one side; it needs continuity:'agree'"));
  const slide = makeConfig();
  slide.transitions.push({id: 'CS', type: 'card_slide', boundary: 180, from: 'CARD_Moon', to: 'CARD_Sun', frames: 6, direction: 0, start: 180});
  assert.ok(has(collectIssues(slide), 'card_slide needs direction 1 or -1'));
  const falsy = makeConfig();
  falsy.transitions.push({id: 'CS', type: 'card_slide', boundary: 180, from: 'CARD_Moon', to: 'CARD_Sun', frames: 6, direction: -1, start: 180, shows_both: false});
  assert.ok(has(collectIssues(falsy), 'shows_both false contradicts type card_slide'));
});

test('uniqueness: one incoming and one outgoing transition per shot (P4); direction required for cloud / wipe (L2)', () => {
  const c = makeConfig();
  c.transitions.push({...c.transitions[0], id: 'WB', direction: 1});
  assert.ok(has(collectIssues(c), 'several incoming transitions (W1, WB)'));
  assert.ok(has(collectIssues(c), 'several outgoing transitions'));
  const viaAlias = makeConfig();
  viaAlias.transitions.push({id: 'N', type: 'none', boundary: 90, from: 'X1', to: 'X2', frames: 0, direction: 0, start: 90}); // shot id alias of X2a
  assert.ok(has(collectIssues(viaAlias), 'several incoming transitions'));
  const noDir = withTransition(wipe());
  delete noDir.transitions[0].direction;
  assert.ok(has(collectIssues(noDir), 'wipe needs direction 1 or -1'));
  const cloud = withTransition({...wipe({id: 'CL', type: 'cloud', seed: 5}), direction: 0});
  assert.ok(has(collectIssues(cloud), 'cloud needs direction 1 or -1'));
});

test('ending.plateStart requires an end card (L5)', () => {
  const c = makeConfig();
  c.timeline.endCardFrames = 0;
  assert.ok(has(collectIssues(c), 'plateStart is set but timeline.endCardFrames is 0'));
});

test('tail files: the bound clip must hold the frames the transition plays (engine rule, editorialFrames input)', async () => {
  const {createRequire} = await import('node:module');
  const {tailFits, checkTailFile} = createRequire(import.meta.url)(path.join(KIT, 'lib', 'tailcheck.cjs'));
  assert.ok(tailFits({frames: 107, nativeFps: 24, fps: 30, startFrom: 125, n: 3, editorialFrames: 100}).ok);
  const shortFile = tailFits({frames: 101, nativeFps: 24, fps: 30, startFrom: 125, n: 3, editorialFrames: 100});
  assert.ok(!shortFile.ok && shortFile.problems.some((x) => x.includes('beyond the file')));
  assert.ok(!tailFits({frames: 2, nativeFps: 24, fps: 30, startFrom: 0, n: 3, editorialFrames: 0}).ok); // needs ceil(2.4) = 3
  assert.ok(tailFits({frames: 3, nativeFps: 24, fps: 30, startFrom: 0, n: 3, editorialFrames: 0}).ok);
  const ff = spawnSync('ffmpeg', ['-version'], {encoding: 'utf8'});
  if (ff.error) return;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-tail-'));
  try {
    const clip = path.join(dir, 'c.mp4');
    const r = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=24', '-frames:v', '5', '-pix_fmt', 'yuv420p', clip], {encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    assert.ok(checkTailFile(clip, {fps: 30, startFrom: 0, n: 3, editorialFrames: 0, label: 'ok'}).ok);
    assert.throws(() => checkTailFile(clip, {fps: 30, startFrom: 0, n: 9, editorialFrames: 0, label: 'short'}), /tail short/);
    assert.throws(() => checkTailFile(clip, {fps: 30, startFrom: 20, n: 3, editorialFrames: 0, label: 'late'}), /beyond the file/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('master adapter: the master must supply exactly the kit picture and tail keys (M4); its tail files hold the frames', async (t) => {
  if (!haveMaster) return t.skip('ep04 builds not present');
  const {createRequire} = await import('node:module');
  const {adaptMaster: adaptMasterRaw, verifyTails} = createRequire(import.meta.url)(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const review = readJ(REVIEW_CFG);
  const events = readJ(EVENTS);
  const master = {...structuredClone(readJ(MASTER_CFG)), master_ready: true, missing_shots: [], missing_tails: []};
  const dropped = structuredClone(master);
  const s = dropped.dialogue.find((x) => x.id === 'S06_B');
  s.segments = s.segments.filter((g) => g.source_id !== 'S06_B3');
  assert.throws(() => adaptMaster(review, events, dropped), /missing \[S06_B\/S06_B3\]/);
  const extra = structuredClone(master);
  extra.dialogue[0].segments.push({...extra.dialogue[0].segments[0], source_id: 'S01_A_extra'});
  assert.throws(() => adaptMaster(review, events, extra), /extra \[S01_A\/S01_A_extra\]/);
  const noTail = structuredClone(master);
  delete noTail.motion.transitions.find((x) => x.outgoing_tail).outgoing_tail;
  assert.throws(() => adaptMaster(review, events, noTail), /tail transitions differ|tail keys/);
  const kit = adaptMaster(review, events, master);
  const probed = await verifyTails(kit);
  assert.equal(probed.length, 3);
  assert.ok(probed.every((p) => p.ok && p.firstIndex === 0));
});
