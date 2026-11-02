// Round 9: events / config of a build are bound to the build's RECEIPT.json (or an engine build summary); labels say what is true.
import test from 'node:test';
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
const V8 = path.join(EDITORIAL, 'review-hd-v008');
const haveBuilds = fs.existsSync(path.join(V8, 'RECEIPT.json')) && fs.existsSync(path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const shaOf = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const adapterPath = path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs');

function copyBuild(dir, v = 'v008') {
  const src = path.join(EDITORIAL, `review-hd-${v}`);
  const files = {
    reviewConfig: path.join(dir, `review-config-${v}.json`),
    events: path.join(dir, `events-${v}.json`),
    receipt: path.join(dir, 'RECEIPT.json'),
  };
  fs.copyFileSync(path.join(src, 'config', `review-config-${v}.json`), files.reviewConfig);
  fs.copyFileSync(path.join(src, `events-${v}.json`), files.events);
  fs.copyFileSync(path.join(src, 'RECEIPT.json'), files.receipt);
  return files;
}

test('receipt binding: loadBuild accepts the build as recorded and refuses edits to events or config (even consistent edits to both)', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {loadBuild, adapt} = require(adapterPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-bind-'));
  try {
    const files = copyBuild(dir);
    const ok = loadBuild(files);
    assert.equal(ok.bound.receipt.sha256, shaOf(files.receipt));
    assert.equal(ok.bound.events_sha256, rd(files.receipt).events.sha256);
    const kit = adapt(ok.review, ok.events, {bound: ok.bound});
    assert.equal(kit.provenance.build_receipt.sha256, shaOf(files.receipt), 'the receipt sha256 is recorded in provenance');
    // the critic probe: raise tail_output_frames 3 -> 7 in BOTH events and config
    const review = rd(files.reviewConfig);
    const events = rd(files.events);
    review.motion.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 7;
    events.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 7;
    fs.writeFileSync(files.reviewConfig, JSON.stringify(review, null, 1));
    fs.writeFileSync(files.events, JSON.stringify(events, null, 1));
    assert.throws(() => loadBuild(files), /events file sha256 .* differs from the receipt/);
    // config only
    fs.copyFileSync(path.join(V8, 'events-v008.json'), files.events);
    assert.throws(() => loadBuild(files), /review config sha256 .* differs from the receipt/);
    // word timing hash named by the config must be the receipt's
    copyBuild(dir);
    const rc = rd(files.receipt);
    rc.word_timing.sha256 = 'a'.repeat(64);
    fs.writeFileSync(files.receipt, JSON.stringify(rc));
    assert.throws(() => loadBuild(files), /word_timing sha256 .* differs from the receipt/);
    // a receipt without the hashes is not a receipt
    fs.writeFileSync(files.receipt, JSON.stringify({status: 'x'}));
    assert.throws(() => loadBuild(files), /not a build receipt/);
    fs.writeFileSync(files.receipt, 'not json');
    assert.throws(() => loadBuild(files), /receipt .* is not JSON/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('receipt binding: adapt() without a receipt-bound build is refused', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt} = require(adapterPath);
  const review = rd(path.join(V8, 'config', 'review-config-v008.json'));
  const events = rd(path.join(V8, 'events-v008.json'));
  assert.throws(() => adapt(review, events), /receipt-bound build/);
  assert.throws(() => adapt(review, events, {bound: {}}), /receipt-bound build/);
});

test('receipt binding: the adapter CLI refuses a consistently tampered config + events pair', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-cli-'));
  try {
    const files = copyBuild(dir);
    const out = path.join(dir, 'kit.json');
    const run = () => spawnSync(process.execPath, [adapterPath, '--review-config', files.reviewConfig, '--events', files.events, '--receipt', files.receipt, '--out', out], {encoding: 'utf8'});
    const good = run();
    assert.equal(good.status, 0, good.stderr);
    assert.equal(rd(out).provenance.build_receipt.sha256, shaOf(files.receipt));
    const review = rd(files.reviewConfig);
    const events = rd(files.events);
    review.motion.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 7;
    events.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 7;
    fs.writeFileSync(files.reviewConfig, JSON.stringify(review, null, 1));
    fs.writeFileSync(files.events, JSON.stringify(events, null, 1));
    fs.rmSync(out);
    const bad = run();
    assert.notEqual(bad.status, 0);
    assert.match(bad.stderr, /differs from the receipt/);
    assert.ok(!fs.existsSync(out));
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('receipt binding: engine-built events are bound the same way, through the build summary the engine prints', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {loadBuild, adapt} = require(adapterPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-eng-'));
  try {
    const reviewConfig = path.join(dir, 'review-config.json');
    const events = path.join(dir, 'events.json');
    fs.copyFileSync(path.join(V8, 'config', 'review-config-v008.json'), reviewConfig);
    fs.copyFileSync(path.join(KIT, 'tests', 'fixtures', 'engine-events.json'), events);
    // the shape `jjv editorial build-config` prints (engine/editorial/cli.py): {ok, ..., outputs: {name: {path, sha256, bytes, written}}}
    const summary = path.join(dir, 'build-summary.json');
    fs.writeFileSync(summary, JSON.stringify({ok: true, dry_run: false, outputs: {
      'review-config.json': {path: reviewConfig, sha256: shaOf(reviewConfig), bytes: fs.statSync(reviewConfig).size, written: true},
      'events.json': {path: events, sha256: shaOf(events), bytes: fs.statSync(events).size, written: true},
    }}));
    const build = loadBuild({reviewConfig, events, receipt: summary});
    assert.equal(build.bound.receipt.kind, 'engine-build-summary');
    assert.ok(adapt(build.review, build.events, {bound: build.bound}).provenance.build_receipt.sha256 === shaOf(summary));
    const e = rd(events);
    e.transitions.find((x) => x.id === 'T1010').outgoing_tail = {...(e.transitions.find((x) => x.id === 'T1010').outgoing_tail || {}), tail_output_frames: 7};
    fs.writeFileSync(events, JSON.stringify(e));
    assert.throws(() => loadBuild({reviewConfig, events, receipt: summary}), /events file sha256 .* differs from the receipt/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('labels: events are "the build\'s events record (receipt-bound)", never "the engine record"; the dip label says not engine-verified', (t) => {
  const files = [
    path.join(KIT, 'README.md'), path.join(KIT, 'SKILL-SECTION-r10.md'),
    path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'), path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs'),
    path.join(KIT, 'episodes', 'ep04', 'rule_report.cjs'), path.join(KIT, 'src', 'validate.mjs'),
  ];
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8');
    assert.doesNotMatch(text, /engine (events )?record|ENGINE events record|engine's own tail_output_frames|approved later design/i, `${path.basename(f)} still names the events file as an engine record or claims an approval`);
  }
  const section = fs.readFileSync(path.join(KIT, 'SKILL-SECTION-r10.md'), 'utf8');
  assert.match(section, /receipt-bound/);
  assert.match(section, /engine-schedule mismatch \(later design, BRIEF v009; not engine-verified\)/);
  assert.match(section, /v009 and v010: 3 sparkle-reach issues each/);
  assert.match(section, /T1010, T1310, T1610/);
  if (!haveBuilds) return;
  const r = spawnSync(process.execPath, [path.join(KIT, 'episodes', 'ep04', 'rule_report.cjs')], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(r.stdout);
  assert.match(doc.v009.engine_schedule.label, /engine-schedule mismatch \(later design, BRIEF v009; not engine-verified\)/);
  assert.doesNotMatch(JSON.stringify(doc), /approved later design/);
  for (const v of ['v008', 'v009', 'v010', 'v011', 'v012']) assert.ok(doc[v].build_receipt && /^[0-9a-f]{64}$/.test(doc[v].build_receipt.sha256), `${v} rule report records the receipt sha256`);
});
