// Generic master adapter, ENGINE schema: what `jjv editorial build-config` writes (review.main_frames, receipt = its summary) goes through
// the master adapter with a master config the producer (engine/edit/master_config.py) wrote from that same build. The build is made by the REAL
// engine into a scratch folder (nothing under production-local is written); the 4K cores and tails are fake files with real-shaped receipts.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {pin, EP} from './ep04-pin.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const WORKSPACE = path.resolve(SKILL, '../../..');
const require = createRequire(import.meta.url);
const TEXT = path.join(KIT, 'episodes', 'ep04', 'episode-text.json');
const LOGO = path.join(WORKSPACE, 'production-local', 'studio-app', 'logo-jenniejoy-kids.png');
const WORD_TIMING = path.join(EP, 'editorial', 'word-timing-v003', 'WORD-TIMING-v003.json');
const have = pin.available && fs.existsSync(WORD_TIMING) && fs.existsSync(LOGO) && fs.existsSync(TEXT);
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');
const generic = require(path.join(KIT, 'lib', 'adapter-master.cjs'));
const {loadBuild} = require(path.join(KIT, 'lib', 'build-binding.cjs'));

const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-master-engine-'));
process.on('exit', () => fs.rmSync(SCRATCH, {recursive: true, force: true}));

function engineBuild() {
  const out = path.join(SCRATCH, 'build');
  fs.mkdirSync(out, {recursive: true});
  const r = spawnSync('python', ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', pin.episode, '--boundaries', pin.boundaries,
    '--word-timing', pin.wordTiming(), '--out', out, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, r.stderr.slice(-800));
  const summary = path.join(SCRATCH, 'summary.json');
  fs.writeFileSync(summary, r.stdout);
  return {out, summary};
}

function produce(buildDir, extra) {
  const file = path.join(SCRATCH, `master-${extra.includes('--preview') ? 'preview' : 'final'}.json`);
  const r = spawnSync('python', ['-I', path.join(KIT, 'tests', 'engine_master_config.py'), SKILL, buildDir, EP, file, ...extra], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, `${r.stdout}\n${r.stderr.slice(-800)}`);
  return {file, summary: JSON.parse(r.stdout)};
}

// fake 4K cores (shot.json beside each) and a tail map attesting a fake core per outgoing tail, for the build's own segments and tails
function fakeFinals(review) {
  const runs = path.join(SCRATCH, 'runs');
  for (const shot of review.dialogue) {
    for (const seg of shot.segments) {
      const dir = path.join(runs, seg.shot);
      fs.mkdirSync(dir, {recursive: true});
      const file = path.join(dir, `${seg.shot}-core.mp4`);
      fs.writeFileSync(file, `fake core ${seg.shot}`);
      fs.writeFileSync(path.join(dir, 'shot.json'), JSON.stringify({status: 'COMPLETED', shot_id: seg.shot, path: file, sha256: sha256(fs.readFileSync(file)), frame_count: seg.native_frames}));
    }
  }
  const rows = [];
  for (const t of review.motion.transitions.filter((x) => x.outgoing_tail)) {
    const file = path.join(SCRATCH, `${t.id}-tail.mp4`);
    fs.writeFileSync(file, `fake tail ${t.id}`);
    const tail = t.outgoing_tail;
    rows.push({transition: t.id, clip: file, clip_sha256: sha256(fs.readFileSync(file)), native_first: tail.editorial_frames, frames: tail.native_frames - tail.editorial_frames});
  }
  const map = path.join(SCRATCH, 'MASTER-TAIL-MAP.json');
  fs.writeFileSync(map, JSON.stringify({schema: 'mam-r27-master-tail-map/v1', tails: rows}));
  return {runs, map};
}

const options = (build) => ({episodeRoot: EP, allowOutside: [LOGO], episodeText: fullText(build)});
let cached;
function world() {
  if (!cached) {
    const built = engineBuild();
    const loaded = loadBuild({reviewConfig: path.join(built.out, 'review-config.json'), events: path.join(built.out, 'events.json'), receipt: built.summary, episodeRoot: EP});
    cached = {built, loaded};
  }
  return cached;
}
function fullText(loaded) {
  const t = rd(TEXT);
  return {...t, captionLines: Object.fromEntries(loaded.review.dialogue.map((d) => [d.id, (t.captionLines || {})[d.id] || 1]))};
}

test('ENGINE schema, preview: the engine build + the producer\'s preview master config -> a preview kit with the master clock and the review pictures', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const {built, loaded} = world();
  assert.equal(loaded.review.main_frames !== undefined && loaded.review.total_frames, loaded.review.main_frames + loaded.review.end_hold_frames);
  const made = produce(built.out, ['--preview']);
  const master = rd(made.file);
  assert.equal(master.master_ready, made.summary.master_ready);
  const kit = generic.adaptMasterKit(loaded, master, {...options(loaded), preview: true});
  assert.equal(kit.mode, 'preview');
  assert.equal(kit.timeline.mainFrames, loaded.review.main_frames);
  assert.equal(kit.review, undefined, 'the master carries no review label');
  assert.deepEqual(Object.keys(kit.clock.shotTable), loaded.review.dialogue.map((d) => d.id));
  assert.equal(kit.shots.length, loaded.review.dialogue.length);
  // without the preview opt-in the same master config is refused (it is not ready), and the engine schema still requires the caption line counts
  assert.throws(() => generic.adaptMasterKit(loaded, master, options(loaded)), /not ready|build_mode/);
  const bad = fullText(loaded);
  delete bad.captionLines[loaded.review.dialogue[0].id];
  assert.throws(() => generic.adaptMasterKit(loaded, master, {...options(loaded), episodeText: bad, preview: true}), /captionLines\./);
  assert.throws(() => generic.adaptMasterKit(loaded, master, {...options(loaded), episodeRoot: undefined, preview: true}), /episodeRoot/);
});

test('ENGINE schema, final: producer with fake receipts -> a "final" kit, every picture and tail bound to its receipt', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const {built, loaded} = world();
  const finals = fakeFinals(loaded.review);
  const made = produce(built.out, ['--runs', finals.runs, '--tail-map', finals.map]);
  assert.equal(made.summary.master_ready, true);
  assert.equal(made.summary.build_mode, 'master');
  const kit = generic.adaptMasterKit(loaded, rd(made.file), options(loaded));
  assert.equal(kit.mode, 'final');
  const pictures = Object.values(kit.bindings.shots).flatMap((s) => Object.values(s.segments));
  assert.ok(pictures.length > 10);
  assert.ok(pictures.every((b) => b.preview === false && b.receipt && b.receipt.binds === b.sha256));
  const tails = Object.values(kit.bindings.tails);
  assert.ok(tails.length > 0 && tails.every((b) => b.preview === false && b.receipt && b.receipt.kind === 'tail'));
  const frames = new Map(kit.transitions.filter((x) => x.tail).map((x) => [kit.bindings.tails[x.id].path, x.tail.fileFrames]));
  assert.ok([...frames.values()].every((n) => Number.isInteger(n) && n > 0));
  // with the cores and tail map absent the producer REFUSES (naming them) instead of writing a half-ready config
  const refused = spawnSync('python', ['-I', path.join(KIT, 'tests', 'engine_master_config.py'), SKILL, built.out, EP, path.join(SCRATCH, 'never.json')], {encoding: 'utf8', cwd: WORKSPACE});
  assert.notEqual(refused.status, 0);
  assert.match(refused.stderr, /no final shot receipt/);
  assert.equal(fs.existsSync(path.join(SCRATCH, 'never.json')), false);
});
