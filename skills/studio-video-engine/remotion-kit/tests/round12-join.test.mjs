// T-E42 addendum / T-E45 P2: joining silent closed-GOP segments by stream copy, with the proof written to a join record.
// Synthetic ffmpeg segments (no Remotion): the join gate must pass a real join and go RED on every way a join can lie.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';

const require = createRequire(import.meta.url);
const segLib = require('../lib/segments.cjs');
const join = require('../tools/join-segments.cjs');
const HAVE_FFMPEG = !spawnSync('ffmpeg', ['-version']).error;
const sha = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const ff = (args) => {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
};
const PLAN_SHA = 'f'.repeat(64);

// one synthetic segment + the record render.cjs writes next to it
function makeSegment(dir, id, src, start, frames, over = {}) {
  const file = path.join(dir, `${id}.mp4`);
  ff(['-f', 'lavfi', '-i', `${src}=s=${over.size || '320x180'}:r=${over.fps || 30}`, '-frames:v', String(frames), '-c:v', 'libx264', '-crf', '18', '-pix_fmt', over.pix || 'yuv420p',
    '-g', String(frames), '-keyint_min', String(frames), '-sc_threshold', '0', '-flags', '+cgop', '-bf', '0', '-an', file]);
  const fm = segLib.framemd5(file);
  const record = {segment: {id, start, end_exclusive: start + frames, frames, plan_sha256: PLAN_SHA, plan_total: 65, uses_shot_video: false}, output: file, output_sha256: sha(file), framemd5: fm.md5s, framemd5_digest: fm.digest, ...(over.record || {})};
  fs.writeFileSync(`${file}.render-record.json`, JSON.stringify(record));
  return file;
}
const withDir = (fn) => async (t) => {
  if (!HAVE_FFMPEG) return t.skip('ffmpeg is not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-join-'));
  try { await fn(dir, t); } finally { fs.rmSync(dir, {recursive: true, force: true}); }
};
const pair = (dir, over = {}) => [makeSegment(dir, 'a', 'testsrc2', 0, 40, over.a), makeSegment(dir, 'b', 'mandelbrot', 40, 25, over.b)];
const refused = (promise, text) => assert.rejects(promise, (e) => e.message.includes(text), text);

test('R12-J1: a real join: H_film == concat(H_seg) element by element, pts continuous, frame count exact, both sides decode', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const out = path.join(dir, 'film.mp4');
  const rec = await join.joinSegments({segments: [a, b], out});
  assert.equal(rec.ok, true);
  assert.equal(rec.film.frames, 65);
  assert.equal(rec.proof.hashes_equal, true);
  assert.equal(rec.proof.compared, 65);
  assert.equal(rec.proof.pts_continuous, true);
  assert.equal(rec.proof.nb_read_frames, 65);
  assert.deepEqual(rec.proof.segment_first_pts_ok, [true, true]);
  assert.equal(rec.proof.decode_clean, true);
  assert.equal(rec.joins[0].join_frame, 40);
  assert.ok(fs.existsSync(`${out}.join-record.json`));
  assert.equal(JSON.parse(fs.readFileSync(`${out}.join-record.json`, 'utf8')).film.sha256, sha(out));
}));

test('R12-J2: RED CASE: one flipped byte in a segment after its render is refused, and no film is written', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const bytes = fs.readFileSync(b);
  bytes[Math.floor(bytes.length / 2)] ^= 0xff;
  fs.writeFileSync(b, bytes);
  const out = path.join(dir, 'film.mp4');
  await refused(join.joinSegments({segments: [a, b], out}), 'changed after its render');
  assert.ok(!fs.existsSync(out));
}));

test('R12-J3: the segments must share the stream parameters (size, fps, pix_fmt), naming the field', withDir(async (dir) => {
  await refused(join.joinSegments({segments: pair(dir, {b: {size: '480x270'}}), out: path.join(dir, 'f1.mp4')}), 'width');
  await refused(join.joinSegments({segments: pair(dir, {b: {fps: 25}}), out: path.join(dir, 'f2.mp4')}), 'r_frame_rate');
  await refused(join.joinSegments({segments: pair(dir, {b: {pix: 'yuv444p'}}), out: path.join(dir, 'f3.mp4')}), 'pix_fmt');
}));

test('R12-J4: records must describe one plan, contiguous in order (plan sha, start = frames so far)', withDir(async (dir) => {
  const [a, b] = pair(dir, {b: {record: {segment: {id: 'b', start: 40, end_exclusive: 65, frames: 25, plan_sha256: 'e'.repeat(64), plan_total: 65}}}});
  await refused(join.joinSegments({segments: [a, b], out: path.join(dir, 'f.mp4')}), 'plan_sha256');
  const [a2, b2] = pair(dir, {b: {record: {segment: {id: 'b', start: 41, end_exclusive: 66, frames: 25, plan_sha256: PLAN_SHA, plan_total: 65}}}});
  await refused(join.joinSegments({segments: [a2, b2], out: path.join(dir, 'g.mp4')}), 'starts at f41');
  const [a3, b3] = pair(dir);
  fs.rmSync(`${b3}.render-record.json`);
  await refused(join.joinSegments({segments: [a3, b3], out: path.join(dir, 'h.mp4')}), 'render record');
}));

test('R12-J5: the recorded framemd5 must equal the segment as it is now (a re-encoded file with the same name is caught)', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const rec = JSON.parse(fs.readFileSync(`${b}.render-record.json`, 'utf8'));
  rec.framemd5[3] = '0'.repeat(32); // the record lies about frame 3; sha256 of the file is still right
  fs.writeFileSync(`${b}.render-record.json`, JSON.stringify(rec));
  await refused(join.joinSegments({segments: [a, b], out: path.join(dir, 'f.mp4')}), 'framemd5');
}));

test('R12-J6: audio is one mix, not cut at the join: join frame/sample recorded, mix length checked against the film', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const wav = path.join(dir, 'mix.wav');
  ff(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', String(65 / 30), '-ac', '2', '-c:a', 'pcm_s16le', wav]);
  const rec = await join.joinSegments({segments: [a, b], audio: wav, out: path.join(dir, 'film.mp4')});
  assert.equal(rec.audio_join.policy, 'single timeline mix, not cut at the join');
  assert.equal(rec.audio_join.samples_per_frame, 1600);
  assert.deepEqual([rec.audio_join.join_frame, rec.audio_join.join_sample], [40, 64000]);
  assert.equal(rec.audio_join.mix_sha256, sha(wav));
  assert.ok(rec.audio_join.pcm_of_film_vs_mix_slack_samples <= 1600, String(rec.audio_join.pcm_of_film_vs_mix_slack_samples));
  assert.equal(rec.proof.hashes_equal, true);
  const short = path.join(dir, 'short.wav');
  ff(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '1', '-ac', '2', '-c:a', 'pcm_s16le', short]);
  await refused(join.joinSegments({segments: [a, b], audio: short, out: path.join(dir, 'x.mp4')}), 'mix');
}));

test('R12-J7: the join is deterministic: the same inputs give a byte-identical film', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const wav = path.join(dir, 'mix.wav');
  ff(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', String(65 / 30), '-ac', '2', '-c:a', 'pcm_s16le', wav]);
  const one = await join.joinSegments({segments: [a, b], audio: wav, out: path.join(dir, 'one.mp4')});
  const two = await join.joinSegments({segments: [a, b], audio: wav, out: path.join(dir, 'two.mp4')});
  assert.equal(one.film.sha256, two.film.sha256);
}));

test('R12-J8: the hash comparison itself goes red when one element differs, or the length does', () => {
  const h = ['a', 'b', 'c'];
  assert.deepEqual(join.compareHashes([['a', 'b'], ['c']], h), {equal: true, compared: 3, firstDifference: null});
  assert.deepEqual(join.compareHashes([['a', 'b'], ['x']], h), {equal: false, compared: 3, firstDifference: 2});
  assert.equal(join.compareHashes([['a', 'b']], h).equal, false);
});
