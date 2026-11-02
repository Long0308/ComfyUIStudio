// Round 8: tail.verifiedFrames is bound to the build's events record (receipt-bound); receipts are read once; engine-schedule mismatch is visible.
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

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const require = createRequire(import.meta.url);
const EDITORIAL = path.resolve(SKILL, '../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const haveBuilds = fs.existsSync(path.join(EDITORIAL, 'review-hd-v010')) && fs.existsSync(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
const build = (v) => ({
  review: rd(path.join(EDITORIAL, `review-hd-${v}`, 'config', `review-config-${v}.json`)),
  events: rd(path.join(EDITORIAL, `review-hd-${v}`, `events-${v}.json`)),
});

test('binding: the review adapter takes tail.verifiedFrames from the events record and refuses a config that disagrees with it', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt: adaptRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
  const adapt = withBound(adaptRaw);
  for (const v of ['v008', 'v010']) {
    const {review, events} = build(v);
    const kit = adapt(review, events);
    for (const tr of kit.transitions.filter((x) => x.tail)) {
      const record = events.transitions.find((x) => x.id === tr.id).outgoing_tail;
      assert.equal(tr.tail.verifiedFrames, record.tail_output_frames, `${v} ${tr.id}`);
      assert.equal(tr.tail.editorialFrames, record.editorial_frames);
      assert.equal(tr.tail.fileFrames, record.native_frames);
    }
  }
  const {review, events} = build('v008');
  const tamperedConfig = structuredClone(review);
  tamperedConfig.motion.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 9;
  assert.throws(() => adapt(tamperedConfig, events), /T1010: outgoing_tail\.tail_output_frames .* differs from the events record/);
  const tamperedEvents = structuredClone(events);
  tamperedEvents.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 9;
  assert.throws(() => adapt(review, tamperedEvents), /T1010: outgoing_tail\.tail_output_frames .* differs from the events record/);
  for (const key of ['editorial_frames', 'native_frames', 'start_from_frame']) {
    const c = structuredClone(review);
    c.motion.transitions.find((x) => x.id === 'T1310').outgoing_tail[key] += 1;
    assert.throws(() => adapt(c, events), new RegExp(`T1310: outgoing_tail\\.${key} .* differs from the events record`), key);
  }
  const noRecord = structuredClone(events);
  delete noRecord.transitions.find((x) => x.id === 'T1610').outgoing_tail;
  assert.throws(() => adapt(review, noRecord), /T1610: .*events record has no outgoing_tail/);
  const extra = structuredClone(review);
  delete extra.motion.transitions.find((x) => x.id === 'T1610').outgoing_tail;
  assert.throws(() => adapt(extra, events), /T1610: .*(no outgoing_tail|differs from the events record)/);
});

test('binding: the master adapter refuses a master tail record that disagrees with the events record', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adaptMaster: adaptMasterRaw} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'));
  const adaptMaster = withBoundMaster(adaptMasterRaw);
  const {review, events} = build('v008');
  const master = rd(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
  const kit = adaptMaster(review, events, master, {preview: true});
  for (const tr of kit.transitions.filter((x) => x.tail)) {
    assert.equal(tr.tail.verifiedFrames, events.transitions.find((x) => x.id === tr.id).outgoing_tail.tail_output_frames);
  }
  for (const [key, bump] of [['tail_output_frames', 4], ['editorial_frames', 1], ['native_frames', 1], ['review_start_from_frame', 5]]) {
    const m = structuredClone(master);
    m.motion.transitions.find((x) => x.id === 'T1010').outgoing_tail[key] += bump;
    assert.throws(() => adaptMaster(review, events, m, {preview: true}), new RegExp(`T1010: master outgoing_tail\\.${key} .* differs from the events record`), key);
  }
});

test('G3: a receipt is read ONCE per binding check (the content check and the hash come from the same bytes)', () => {
  const {requireReceiptBinding} = require(path.join(KIT, 'lib', 'stage.cjs'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-once-'));
  const realRead = fs.readFileSync;
  try {
    const clip = path.join(dir, 'c.mp4');
    fs.writeFileSync(clip, 'clip');
    const clipSha = crypto.createHash('sha256').update(fs.readFileSync(clip)).digest('hex');
    const rcPath = path.join(dir, 'shot.json');
    fs.writeFileSync(rcPath, JSON.stringify({status: 'COMPLETED', sha256: clipSha, path: clip}));
    const rcSha = crypto.createHash('sha256').update(fs.readFileSync(rcPath)).digest('hex');
    const binding = {path: clip, sha256: clipSha, preview: false, receipt: {kind: 'shot', path: rcPath, sha256: rcSha, binds: clipSha}};
    let reads = 0;
    fs.readFileSync = function patched(file, ...rest) {
      if (path.resolve(String(file)) === path.resolve(rcPath)) reads += 1;
      return realRead.call(this, file, ...rest);
    };
    assert.doesNotThrow(() => requireReceiptBinding(binding, 'picture', 'x'));
    assert.equal(reads, 1, `the receipt was read ${reads} times`);
    // a receipt that changes content keeps failing (hash from the same single read)
    fs.writeFileSync(rcPath, JSON.stringify({status: 'COMPLETED', sha256: clipSha, path: clip, note: 'edited'}));
    assert.throws(() => requireReceiptBinding(binding, 'picture', 'x'), /missing or changed/);
  } finally {
    fs.readFileSync = realRead;
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('G2: the rule report compares every build dip schedule with the engine presets (T-E42: the catalog holds the 9-row legacy and the approved 8-row schedule)', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const r = spawnSync(process.execPath, [path.join(KIT, 'episodes', 'ep04', 'rule_report.cjs')], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(r.stdout);
  assert.deepEqual(doc.v008.engine_schedule.mismatch, [], 'the earliest build is the engine legacy schedule');
  assert.deepEqual(Object.values(doc.v008.engine_schedule.matched), ['dip_white_legacy', 'dip_white_legacy', 'dip_white_legacy']);
  assert.deepEqual(doc.v008.engine_schedule.engine_presets, {dip_white_legacy: {rows: 9, tail_frames: 3}, dip_white: {rows: 8, tail_frames: 1}});
  if (doc.v009) assert.deepEqual(doc.v009.engine_schedule.mismatch.sort(), ['T1010', 'T1310', 'T1610'], 'v009 used its own schedule, equal to neither preset');
  for (const v of ['v010', 'v011', 'v012']) {
    if (!doc[v]) continue;
    assert.deepEqual(doc[v].engine_schedule.mismatch, [], v);
    assert.ok(Object.values(doc[v].engine_schedule.matched).every((m) => m === 'dip_white'), `${v}: the approved 8-row design is now an engine preset`);
  }
});

