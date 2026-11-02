// Round 11 / T-E42 item 1: per-boundary FEASIBILITY. A transition is a compositing layer: choosing an effect never re-renders shot video,
// so every preset must say whether the handle the bound clips already have can play it (the engine tail rule, exactly), and a chosen tail
// preset with a missing or short handle must be REFUSED before any bundling, naming the boundary and the missing frames.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const catalog = JSON.parse(fs.readFileSync(path.join(SKILL, 'schemas', 'transition-presets.json'), 'utf8'));
const READY = Object.entries(catalog.presets).filter(([, p]) => p.status === 'ready').map(([name]) => name);
const feas = await import(pathToFileURL(path.join(KIT, 'src', 'feasibility.mjs')).href);

// A boundary X1 -> X2a with an outgoing tail handle: delivery 30 fps, native 24 fps, the editorial cut shows 60 delivery frames = 48 native
// frames of a 55-frame file, so 7 native tail frames remain (the first episode's real handles are 7 / 13 / 15).
const tail = (over = {}) => ({startFrom: 60, editorialFrames: 48, fileFrames: 55, nativeFps: 24, verifiedFrames: 3, ...over});
function withDip(over = {}) {
  const c = makeConfig();
  const name = over.preset || 'dip_white_legacy';
  const schedule = catalog.presets[name].schedule.map((e) => ({t: e.t, shot: e.shot, white: e.white}));
  c.transitions = [
    {id: 'D1', type: 'dip_white', preset: name, boundary: 90, from: 'X1', to: 'X2a', frames: schedule.length, direction: 0, start: 90 + Math.min(...schedule.map((e) => e.t)), schedule, tail: tail(over.tail || {})},
    {id: 'N1', type: 'none', boundary: 150, from: 'X2b', to: 'OUTRO', frames: 0, direction: 0, start: 150},
  ];
  return c;
}

test('1a: every ready preset gets {available, needsTailFrames, haveNativeFrames, reason, whyNot}; planned presets are not listed', () => {
  const r = feas.presetAvailability(withDip(), 'D1', {mode: 'review', catalog});
  assert.deepEqual(Object.keys(r.presets).sort(), [...READY].sort());
  for (const [name, row] of Object.entries(r.presets)) {
    for (const key of ['available', 'needsTailFrames', 'haveNativeFrames', 'reason', 'whyNot']) assert.ok(key in row, `${name}.${key}`);
    assert.equal(typeof row.available, 'boolean');
    assert.equal(row.whyNot === null, row.available, `${name}: whyNot is null exactly when available`);
  }
  assert.ok(!('glitch' in r.presets), 'a planned preset is not a choice');
});

test('1b: a 7-frame handle plays tail presets only up to 8 frames: the engine rule, ceil(4N/5) native frames and the last index', () => {
  const r = feas.presetAvailability(withDip(), 'D1', {mode: 'review', catalog});
  assert.equal(r.tail.haveNativeFrames, 7);
  const x = r.presets.crossfade; // default 12 frames, tail_frames "all": needs ceil(0.8 x 12) = 10
  assert.equal(x.available, false);
  assert.equal(x.needsTailFrames, 10);
  assert.equal(x.haveNativeFrames, 7);
  assert.equal(x.maxFrames, 8, 'the largest legal frame count that fits');
  assert.match(x.whyNot, /tail handle too short: 7 native tail frame\(s\) available, 10 needed for 12 frames/);
  assert.match(x.whyNot, /no GPU work is requested/);
  // the whole family of "all" presets behaves alike
  for (const [name, p] of Object.entries(catalog.presets)) {
    if (p.status !== 'ready' || p.tail_frames !== 'all') continue;
    assert.equal(r.presets[name].available, false, `${name} at its default frames needs more than 7`);
    assert.ok(r.presets[name].maxFrames === 8 || p.frames.min > 8, `${name} maxFrames ${r.presets[name].maxFrames}`);
  }
});

test('1c: presets without a tail are always available; the dip family needs only its out_tail rows (1 for dip_white, 3 for the legacy 9-row schedule)', () => {
  const r = feas.presetAvailability(withDip(), 'D1', {mode: 'review', catalog});
  for (const [name, p] of Object.entries(catalog.presets)) {
    if (p.status === 'ready' && p.tail_frames === 'none') {
      assert.equal(r.presets[name].available, true, name);
      assert.equal(r.presets[name].needsTailFrames, 0, name);
    }
  }
  assert.equal(r.presets.dip_white.needsTailFrames, 1);
  assert.equal(r.presets.dip_white_legacy.needsTailFrames, 3);
  assert.equal(r.presets.dip_white.available, true);
  assert.equal(r.presets.card_flip_3d.needsTailFrames, 8, 'half of the default 18 frames = 9, ceil(0.8 x 9) = 8');
});

test('1d: a boundary WITHOUT tail data has a zero handle: only tail_frames "none" presets are available, and the reason says why', () => {
  const r = feas.presetAvailability(withDip(), 'N1', {mode: 'review', catalog});
  assert.equal(r.tail, null);
  for (const [name, p] of Object.entries(catalog.presets)) {
    if (p.status !== 'ready') continue;
    const row = r.presets[name];
    assert.equal(row.available, p.tail_frames === 'none', `${name}`);
    assert.equal(row.haveNativeFrames, null, `${name}: no handle at all`);
    if (!row.available) assert.match(row.whyNot, /no tail_clip is declared on this boundary; no GPU work is requested/);
  }
  assert.ok(r.presets.dip_white.available === false, 'the dip needs its out_tail frame, so it needs a handle too');
});

test('1e: the boundary is found by transition id, by frame number or by numeric string; an unknown one is refused', () => {
  const c = withDip();
  for (const ref of ['D1', 90, '90', c.transitions[0]]) assert.equal(feas.presetAvailability(c, ref, {mode: 'review', catalog}).id, 'D1');
  assert.throws(() => feas.presetAvailability(c, 'T99999', {mode: 'review', catalog}), /no boundary/i);
  assert.throws(() => feas.presetAvailability(c, 90, {mode: 'weird', catalog}), /mode/);
});

test('1f: master mode reads the MASTER config tails: a preset available in review can be unavailable in master, and the table says so (master_covers)', () => {
  const review = withDip();
  const master = withDip({tail: {editorialFrames: 50, fileFrames: 55}}); // only 5 tail frames in the 4K tail core
  const r = feas.presetAvailability(review, 'D1', {mode: 'review', catalog, masterConfig: master});
  assert.equal(r.presets.dip_white_legacy.available, true);
  assert.equal(r.presets.dip_white_legacy.master_covers, true, '3 frames fit in 5');
  const wide = feas.presetAvailability(review, 'D1', {mode: 'review', catalog, masterConfig: withDip({tail: {editorialFrames: 54, fileFrames: 55}})});
  assert.equal(wide.presets.dip_white_legacy.available, true, 'review still plays it');
  assert.equal(wide.presets.dip_white_legacy.master_covers, false, '1 master tail frame < the 3 the legacy schedule needs');
  assert.match(wide.presets.dip_white_legacy.master_why_not, /1 native tail frame/);
  assert.equal(wide.presets.dip_white.master_covers, true, 'the approved dip needs 1');
  const m = feas.presetAvailability(master, 'D1', {mode: 'master', catalog});
  assert.equal(m.mode, 'master');
  assert.equal(m.presets.dip_white_legacy.available, true);
  assert.ok(!('master_covers' in m.presets.dip_white_legacy) || m.presets.dip_white_legacy.master_covers === m.presets.dip_white_legacy.available);
});

test('1g: tailHandleIssues refuses a chosen tail preset with a missing or short handle, naming the boundary, the missing frames and "no GPU work is requested"', () => {
  assert.deepEqual(feas.tailHandleIssues(withDip(), {catalog}), [], 'a valid handle is clean');
  // short: the legacy schedule plays 3 tail frames, the file leaves 1
  const short = feas.tailHandleIssues(withDip({tail: {editorialFrames: 54}}), {catalog});
  assert.equal(short.length, 1);
  assert.match(short[0], /D1/);
  assert.match(short[0], /dip_white_legacy/);
  assert.match(short[0], /missing 2 native tail frame/);
  assert.match(short[0], /no GPU work is requested/);
  // missing: a tail preset with no tail data at all
  const c = withDip();
  delete c.transitions[0].tail;
  const none = feas.tailHandleIssues(c, {catalog});
  assert.equal(none.length, 1);
  assert.match(none[0], /D1/);
  assert.match(none[0], /missing 3 native tail frame/);
  assert.match(none[0], /no GPU work is requested/);
  // the last index can also run past the file even with enough frames after the cut
  const past = feas.tailHandleIssues(withDip({tail: {startFrom: 90}}), {catalog});
  assert.match(past[0] || '', /last tail frame index/);
  // a type the catalog does not know is left to validate.mjs (which refuses it as unknown)
  const legacy = withDip();
  legacy.transitions[0] = {...legacy.transitions[0], type: 'mystery_fx', preset: undefined, tail: undefined};
  assert.deepEqual(feas.tailHandleIssues(legacy, {catalog}), []);
});

// ---------------------------------------------------------------------------------------------------- the CLI
function cli(config, args, files = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11f-'));
  const file = path.join(dir, 'c.json');
  fs.writeFileSync(file, JSON.stringify(config));
  const extra = args.map((a) => files[a] ? (fs.writeFileSync(path.join(dir, a), JSON.stringify(files[a])), path.join(dir, a)) : a);
  const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, ...extra], {encoding: 'utf8', env: {...process.env, REMOTION_BROWSER: ''}});
  fs.rmSync(dir, {recursive: true, force: true});
  return r;
}

test('1h: render.cjs --list-presets prints the JSON table and exits: no bundling, no browser, only --config is needed', () => {
  const c = withDip(); // not a full valid config (no bindings, a dip peak that is late): the listing must not demand either
  const all = cli(c, ['--list-presets']);
  assert.equal(all.status, 0, all.stderr);
  const doc = JSON.parse(all.stdout);
  assert.equal(doc.mode, 'review');
  assert.deepEqual(doc.boundaries.map((b) => b.id), ['D1', 'N1']);
  assert.equal(doc.boundaries[0].presets.crossfade.available, false);
  const one = JSON.parse(cli(c, ['--list-presets', '--boundary', 'D1']).stdout);
  assert.deepEqual(one.boundaries.map((b) => b.id), ['D1']);
  const byFrame = JSON.parse(cli(c, ['--list-presets', '--boundary', '150']).stdout);
  assert.deepEqual(byFrame.boundaries.map((b) => b.id), ['N1']);
  assert.equal(byFrame.boundaries[0].tail, null);
  const bad = cli(c, ['--list-presets', '--boundary', 'T77777']);
  assert.notEqual(bad.status, 0);
  assert.match(bad.stderr, /no boundary/i);
});

test('1i: --list-presets --mode master --master-config adds master_covers from the master kit config', () => {
  const c = withDip();
  const master = withDip({tail: {editorialFrames: 54, fileFrames: 55}});
  const r = cli(c, ['--list-presets', '--boundary', 'D1', '--master-config', 'master.json'], {'master.json': master});
  assert.equal(r.status, 0, r.stderr);
  const row = JSON.parse(r.stdout).boundaries[0].presets.dip_white_legacy;
  assert.equal(row.available, true);
  assert.equal(row.master_covers, false);
});

test('1j: a chosen tail preset with a short handle is refused BEFORE bundling (render.cjs, any run), naming the boundary and the missing frames', () => {
  const base = withDip({preset: 'dip_white', tail: {editorialFrames: 55, fileFrames: 55}}); // the approved dip needs 1 tail frame, the file leaves 0
  const r = cli(base, ['--check-only']);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /D1/);
  assert.match(r.stderr, /missing 1 native tail frame/);
  assert.match(r.stderr, /no GPU work is requested/);
  assert.doesNotMatch(r.stderr, /no browser|browser not found/, 'it failed on the handle, before the browser was looked for');
});
