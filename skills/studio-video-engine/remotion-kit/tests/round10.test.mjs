// Round 10: the REAL engine build summary is accepted; the bound token is unforgeable; provenance comes from verified bytes; receipts need word_timing.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {pin} from './ep04-pin.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const WORKSPACE = path.resolve(SKILL, '../../..');
const require = createRequire(import.meta.url);
const EP = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom');
const EDITORIAL = path.join(EP, 'editorial');
const V8 = path.join(EDITORIAL, 'review-hd-v008');
const adapterPath = path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs');
const haveBuilds = fs.existsSync(path.join(V8, 'RECEIPT.json'));
const haveEngineInputs = pin.available && fs.existsSync(pin.boundaries) && fs.existsSync(path.join(EDITORIAL, 'word-timing-v001', 'WORD-TIMING-v001.json'));
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const shaOf = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');

// ---------------------------------------------------------------------------------------------------- the real engine summary
function runEngine(outDir) {
  const r = spawnSync('python', ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', pin.episode,
    '--boundaries', pin.boundaries, '--word-timing', pin.wordTiming('v001'),
    '--out', outDir, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, r.stderr.slice(-600));
  return r.stdout;
}

test('engine summary: the REAL `jjv editorial build-config` stdout (hashes nested under "outputs") binds the build; edits are refused', (t) => {
  if (!haveEngineInputs) return t.skip('episode engine inputs absent');
  const {loadBuild} = require(adapterPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-real-'));
  try {
    const out = path.join(dir, 'out');
    fs.mkdirSync(out);
    const stdout = runEngine(out); // a real build into scratch: writes review-config.json + events.json there only
    const summary = path.join(dir, 'summary.json');
    fs.writeFileSync(summary, stdout);
    const doc = JSON.parse(stdout);
    assert.ok(doc.outputs && doc.outputs['events.json'] && !doc['events.json'], 'the engine nests the hashes under outputs');
    const files = {reviewConfig: path.join(out, 'review-config.json'), events: path.join(out, 'events.json'), receipt: summary, episodeRoot: EP};
    const build = loadBuild(files);
    assert.equal(build.bound.receipt.kind, 'engine-build-summary');
    assert.equal(build.bound.events_sha256, doc.outputs['events.json'].sha256);
    assert.equal(build.bound.receipt.sha256, shaOf(summary));
    // edit events: refused
    const eventsBytes = fs.readFileSync(files.events);
    const e = rd(files.events);
    e.transitions[0].note = 'edited';
    fs.writeFileSync(files.events, JSON.stringify(e));
    assert.throws(() => loadBuild(files), /events file sha256 .* differs from the receipt/);
    fs.writeFileSync(files.events, eventsBytes);
    assert.doesNotThrow(() => loadBuild(files));
    // the engine summary has no word-timing key: the config's word_timing.sha256 is checked against the file itself
    const fakeRoot = path.join(dir, 'root');
    fs.mkdirSync(path.join(fakeRoot, 'editorial', 'word-timing-v001'), {recursive: true});
    fs.writeFileSync(path.join(fakeRoot, 'editorial', 'word-timing-v001', 'WORD-TIMING-v001.json'), 'tampered');
    assert.throws(() => loadBuild({...files, episodeRoot: fakeRoot}), /word-timing file sha256 .* differs from the config/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('engine summary: the engine word-timing document is checked against the config word_timing.sha256 (needs the episode root for its relative path)', (t) => {
  if (!haveEngineInputs) return t.skip('episode engine inputs absent');
  const {loadBuild} = require(adapterPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-real2-'));
  try {
    const out = path.join(dir, 'out');
    fs.mkdirSync(out);
    const stdout = runEngine(out);
    const summary = path.join(dir, 'summary.json');
    fs.writeFileSync(summary, stdout);
    const base = {reviewConfig: path.join(out, 'review-config.json'), events: path.join(out, 'events.json'), receipt: summary};
    assert.throws(() => loadBuild(base), /episodeRoot/, 'a relative word_timing.path needs the episode root');
    assert.doesNotThrow(() => loadBuild({...base, episodeRoot: EP}));
    const root = path.join(dir, 'root');
    fs.mkdirSync(path.join(root, 'editorial', 'word-timing-v001'), {recursive: true});
    assert.throws(() => loadBuild({...base, episodeRoot: root}), /word-timing file .* is missing/);
    fs.writeFileSync(path.join(root, 'editorial', 'word-timing-v001', 'WORD-TIMING-v001.json'), 'tampered');
    assert.throws(() => loadBuild({...base, episodeRoot: root}), /word-timing file sha256 .* differs from the config/);
    // the flat shape the earlier round accepted never existed in the engine output and is refused now
    fs.writeFileSync(path.join(dir, 'flat.json'), JSON.stringify({'review-config.json': {sha256: shaOf(base.reviewConfig)}, 'events.json': {sha256: shaOf(base.events)}}));
    assert.throws(() => loadBuild({...base, receipt: path.join(dir, 'flat.json'), episodeRoot: EP}), /not a build receipt/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- unforgeable token
test('token: a forged or copied `bound` object is refused; only the object loadBuild returned is accepted', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {adapt, loadBuild} = require(adapterPath);
  const review = rd(path.join(V8, 'config', 'review-config-v008.json'));
  const events = rd(path.join(V8, 'events-v008.json'));
  const build = loadBuild({reviewConfig: path.join(V8, 'config', 'review-config-v008.json'), events: path.join(V8, 'events-v008.json'), receipt: path.join(V8, 'RECEIPT.json')});
  assert.doesNotThrow(() => adapt(review, events, {bound: build.bound}));
  const forged = {receipt: {path: 'x', sha256: 'a'.repeat(64), kind: 'build-receipt'}, config_sha256: 'b'.repeat(64), events_sha256: 'c'.repeat(64)};
  assert.throws(() => adapt(review, events, {bound: forged}), /receipt-bound build/);
  assert.throws(() => adapt(review, events, {bound: {...build.bound}}), /receipt-bound build/);
  assert.throws(() => adapt(review, events, {bound: structuredClone(build.bound)}), /receipt-bound build/);
  assert.throws(() => adapt(review, events, {bound: JSON.parse(JSON.stringify(build.bound))}), /receipt-bound build/);
  assert.ok(Object.isFrozen(build.bound), 'the token cannot be edited after loadBuild');
});

// ---------------------------------------------------------------------------------------------------- provenance from verified bytes
test('provenance: the CLI records the hashes of the VERIFIED bytes, not hashes recomputed by re-reading the files', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  for (const file of ['adapter-v008.cjs', 'adapter-master-v002.cjs']) {
    const text = fs.readFileSync(path.join(KIT, 'episodes', 'ep04', file), 'utf8');
    assert.doesNotMatch(text, /sha\(reviewPath\)|sha\(eventsPath\)/, `${file} re-reads the build files for provenance`);
    assert.match(text, /build\.bound\.config_sha256|build\.bound\.events_sha256|kit\.provenance\.config_sha256/);
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-prov-'));
  try {
    const out = path.join(dir, 'kit.json');
    const r = spawnSync(process.execPath, [adapterPath, '--out', out], {encoding: 'utf8'});
    assert.equal(r.status, 0, r.stderr);
    const k = rd(out);
    assert.equal(k.provenance.review_config.sha256, shaOf(path.join(V8, 'config', 'review-config-v008.json')));
    assert.equal(k.provenance.events.sha256, shaOf(path.join(V8, 'events-v008.json')));
    assert.equal(k.provenance.review_config.sha256, k.provenance.config_sha256);
    assert.equal(k.provenance.events.sha256, k.provenance.events_sha256);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- word_timing required
test('receipt: a build receipt without word_timing.sha256, or a config without word_timing, is refused (no silently skipped check)', (t) => {
  if (!haveBuilds) return t.skip('builds absent');
  const {loadBuild} = require(adapterPath);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-wt-'));
  try {
    const files = {reviewConfig: path.join(dir, 'c.json'), events: path.join(dir, 'e.json'), receipt: path.join(dir, 'r.json')};
    fs.copyFileSync(path.join(V8, 'config', 'review-config-v008.json'), files.reviewConfig);
    fs.copyFileSync(path.join(V8, 'events-v008.json'), files.events);
    const receipt = rd(path.join(V8, 'RECEIPT.json'));
    fs.writeFileSync(files.receipt, JSON.stringify(receipt));
    assert.doesNotThrow(() => loadBuild(files));
    const noWt = structuredClone(receipt);
    delete noWt.word_timing;
    fs.writeFileSync(files.receipt, JSON.stringify(noWt));
    assert.throws(() => loadBuild(files), /receipt .* has no word_timing\.sha256/);
    const noSha = structuredClone(receipt);
    delete noSha.word_timing.sha256;
    fs.writeFileSync(files.receipt, JSON.stringify(noSha));
    assert.throws(() => loadBuild(files), /has no word_timing\.sha256/);
    // the config side: the receipt names a word timing hash, the config names none
    const cfg = rd(files.reviewConfig);
    delete cfg.word_timing.sha256;
    fs.writeFileSync(files.reviewConfig, JSON.stringify(cfg));
    const rc = structuredClone(receipt);
    rc.config.sha256 = shaOf(files.reviewConfig);
    fs.writeFileSync(files.receipt, JSON.stringify(rc));
    assert.throws(() => loadBuild(files), /review config has no word_timing\.sha256/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------------------------------------------- wording / section
test('wording: no test title calls the events file an engine record; the round-10 section exists and the older ones are gone', () => {
  for (const f of ['round7.test.mjs', 'round8.test.mjs', 'validate.test.mjs', 'round6.test.mjs', 'round5.test.mjs', 'round4.test.mjs']) {
    const titles = [...fs.readFileSync(path.join(KIT, 'tests', f), 'utf8').matchAll(/^(?:test|\/\/)[^\n]*$/gm)].map((m) => m[0]).join('\n');
    assert.doesNotMatch(titles, /engine (events )?record/i, `${f} names the events file as an engine record`);
  }
  for (const old of ['r4', 'r5', 'r6', 'r7', 'r8', 'r9']) assert.ok(!fs.existsSync(path.join(KIT, `SKILL-SECTION-${old}.md`)), old);
  const text = fs.readFileSync(path.join(KIT, 'SKILL-SECTION-r10.md'), 'utf8');
  assert.match(text, /outputs/);
  assert.match(text, /no word-timing key/);
  assert.match(text, /unforgeable|module-private/);
});
