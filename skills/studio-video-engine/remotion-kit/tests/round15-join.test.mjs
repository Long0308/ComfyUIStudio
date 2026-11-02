// T-E45 edit path: the FAST join of cached segments. Segments are attested by their sha256 (through the verified-hash cache) and their recorded
// frame hashes; the joined film is decoded ONCE and that single decode is the framemd5 proof, the frame count and the decoder-clean check.
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
const {HashCache} = require('../lib/hashcache.cjs');
const HAVE_FFMPEG = !spawnSync('ffmpeg', ['-version']).error;
const sha = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const ff = (args) => {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
};

function makeSegment(dir, id, src, start, frames, over = {}) {
  const file = path.join(dir, `${id}.mp4`);
  ff(['-f', 'lavfi', '-i', `${src}=s=320x180:r=30`, '-frames:v', String(frames), '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-g', String(frames), '-keyint_min', String(frames), '-sc_threshold', '0', '-flags', '+cgop', '-bf', '0', '-an', file]);
  const fm = segLib.framemd5(file);
  const record = {segment: {id, start, end_exclusive: start + frames, frames, plan_sha256: 'f'.repeat(64), plan_total: 65, uses_shot_video: false}, output: file, output_sha256: sha(file),
    framemd5: fm.md5s, framemd5_digest: fm.digest, stream: segLib.probeStream(file), ...(over.record || {})};
  fs.writeFileSync(`${file}.render-record.json`, JSON.stringify(record));
  const old = new Date(Date.now() - 3600 * 1000);
  fs.utimesSync(file, old, old);
  return file;
}
const withDir = (fn) => async (t) => {
  if (!HAVE_FFMPEG) return t.skip('ffmpeg is not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-j15-'));
  try { await fn(dir, t); } finally { fs.rmSync(dir, {recursive: true, force: true}); }
};
const pair = (dir, over = {}) => [makeSegment(dir, 'a', 'testsrc2', 0, 40, over.a), makeSegment(dir, 'b', 'mandelbrot', 40, 25, over.b)];
const refused = (promise, text) => assert.rejects(promise, (e) => e.message.includes(text), text);
const fastOf = (dir) => {
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  return {cache, fast: {hashFile: (f) => cache.sha256(f)}};
};

test('R15-J1: fast join: same film bytes as the strict join, ONE decode (segments_decoded_again 0), proof columns equal, nb_read_frames and decode_clean from that decode', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const {cache, fast} = fastOf(dir);
  const strict = await join.joinSegments({segments: [a, b], out: path.join(dir, 'strict.mp4'), cache: true, expectedTotal: 65});
  const quick = await join.joinSegments({segments: [a, b], out: path.join(dir, 'quick.mp4'), cache: true, expectedTotal: 65, fast});
  assert.equal(quick.proof.hashes_equal, true);
  assert.equal(quick.proof.compared, 65);
  assert.equal(quick.proof.nb_read_frames, 65);
  assert.equal(quick.proof.decode_clean, true);
  assert.equal(quick.proof.single_decode, true);
  assert.equal(quick.proof.segments_decoded_again, 0);
  assert.equal(quick.film.sha256, strict.film.sha256, 'the stream-copy film is byte-identical either way');
  assert.equal(quick.film.framemd5_digest, strict.film.framemd5_digest);
  assert.ok(cache.stats().misses >= 2);
  // second join: the segments are verified by stat identity, not read
  await join.joinSegments({segments: [a, b], out: path.join(dir, 'quick2.mp4'), cache: true, expectedTotal: 65, fast});
  assert.ok(cache.stats().hits >= 2, JSON.stringify(cache.stats()));
}));

test('R15-J2: RED CASE: a segment byte flipped after its render is refused by the fast join (the cache sees the new mtime), no film written', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const {fast} = fastOf(dir);
  await join.joinSegments({segments: [a, b], out: path.join(dir, 'ok.mp4'), cache: true, expectedTotal: 65, fast});
  const bytes = fs.readFileSync(b);
  bytes[Math.floor(bytes.length / 2)] ^= 0xff;
  fs.writeFileSync(b, bytes);
  const out = path.join(dir, 'film.mp4');
  await refused(join.joinSegments({segments: [a, b], out, cache: true, expectedTotal: 65, fast}), 'changed after its render');
  assert.ok(!fs.existsSync(out));
}));

test('R15-J3: RED CASE: a record whose framemd5 list lies (file sha unchanged) is NOT decoded per segment, but the film decode catches it', withDir(async (dir) => {
  const [a, b] = pair(dir);
  const rec = JSON.parse(fs.readFileSync(`${b}.render-record.json`, 'utf8'));
  rec.framemd5[3] = '0'.repeat(32);
  fs.writeFileSync(`${b}.render-record.json`, JSON.stringify(rec));
  const {fast} = fastOf(dir);
  const out = path.join(dir, 'film.mp4');
  await refused(join.joinSegments({segments: [a, b], out, cache: true, expectedTotal: 65, fast}), 'framemd5 column of the film differs');
  assert.ok(!fs.existsSync(out));
  assert.ok(fs.existsSync(`${out}.join-refused.json`));
}));

test('R15-J4: RED CASE: a recorded stream hint that does not match the real film is refused (one ffprobe of the film)', withDir(async (dir) => {
  const [a, b] = pair(dir);
  for (const f of [a, b]) {
    const rec = JSON.parse(fs.readFileSync(`${f}.render-record.json`, 'utf8'));
    rec.stream.width = 640;
    fs.writeFileSync(`${f}.render-record.json`, JSON.stringify(rec));
  }
  const {fast} = fastOf(dir);
  await refused(join.joinSegments({segments: [a, b], out: path.join(dir, 'film.mp4'), cache: true, expectedTotal: 65, fast}), 'stream differs from the recorded segment stream');
}));
