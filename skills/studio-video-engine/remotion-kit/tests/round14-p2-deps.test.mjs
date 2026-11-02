// T-E45 P2: node keys of segments (lib/segdeps.cjs) and the segment cache (lib/segcache.cjs) - no browser needed.
import test from 'node:test';
import {assert, dep, fs, kitDeps, os, path, richConfig, segmentsDoc, KIT, clone} from './p2-lib.mjs';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import crypto from 'node:crypto';

const require = createRequire(import.meta.url);
const cache = require('../lib/segcache.cjs');

const PINS = {kit: 'p', remotion: 'r', mode: 'review', scale: 1};
const ffmpegOk = !spawnSync('ffmpeg', ['-version']).error;
const key = (cfg, seg) => dep.nodeKey('video', dep.videoSlice(cfg, seg, {deps: kitDeps(cfg), mode: 'review'}), PINS);
const audioKey = (cfg) => dep.nodeKey('audio', dep.audioSlice(cfg, {mode: 'review'}), PINS);
const keysOf = (cfg, doc) => Object.fromEntries(doc.segments.map((s) => [s.id, key(cfg, s)]));
const changed = (a, b) => Object.keys(a).filter((id) => a[id] !== b[id]);
const touching = (doc, from, to) => doc.segments.filter((s) => s.start < to && from < s.end_exclusive).map((s) => s.id);
const setAt = (cfg, p, v) => {
  const next = clone(cfg);
  let at = next;
  for (const k of p.slice(0, -1)) at = at[k];
  at[p[p.length - 1]] = v;
  return next;
};

function setup(t) {
  if (!ffmpegOk) {
    t.skip('ffmpeg is not available');
    return null;
  }
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-p2deps-'));
  const config = richConfig(dir);
  const doc = segmentsDoc(config, {minFrames: 8});
  return {dir, config, doc, base: keysOf(config, doc)};
}

test('P2-D1: keys are deterministic, differ by pins and by range, and cover every part of the slice', async (t) => {
  const s = setup(t);
  if (!s) return;
  try {
    assert.deepEqual(keysOf(s.config, s.doc), s.base, 'same config, same keys');
    assert.equal(new Set(Object.values(s.base)).size, s.doc.segments.length, 'every segment has its own key');
    const seg = s.doc.segments[3];
    const slice = dep.videoSlice(s.config, seg, {deps: kitDeps(s.config), mode: 'review'});
    const k1 = dep.nodeKey('video', slice, PINS);
    assert.notEqual(k1, dep.nodeKey('video', slice, {...PINS, mode: 'master', scale: 2}), 'mode / scale are pins');
    assert.notEqual(k1, dep.nodeKey('video', slice, {...PINS, remotion: 'other'}), 'the Remotion version is a pin');
    assert.notEqual(k1, dep.nodeKey('audio', slice, PINS), 'a video key is not an audio key');
    // the range is in the slice: the same content cut elsewhere is another segment
    assert.notEqual(k1, key(s.config, {...seg, end_exclusive: seg.end_exclusive - 1}));
    // the review label is only in review slices, master slices carry none
    assert.equal('global.review' in dep.videoSlice(s.config, seg, {deps: kitDeps(s.config), mode: 'master'}).parts, false);
  } finally {
    fs.rmSync(s.dir, {recursive: true, force: true});
  }
});

test('P2-D2: a change makes exactly the segments that can show it stale', async (t) => {
  const s = setup(t);
  if (!s) return;
  try {
    const stale = (cfg) => changed(s.base, keysOf(cfg, s.doc));
    // widening the window to 14 frames also makes the segment after it stale (it now holds frames of the effect)
    const widened = setAt(s.config, ['transitions', 1, 'frames'], 14);
    const [old, wide] = [dep.transitionSpan(s.config.transitions[1], kitDeps(s.config)), dep.transitionSpan(widened.transitions[1], kitDeps(widened))];
    const cases = [
      ['a word of S2 (shot record)', setAt(s.config, ['shots', 1, 'words', 0, 'startF'], 95), touching(s.doc, 90, 150)],
      ['the push_slide row (old and new window)', widened, touching(s.doc, Math.min(old.from, wide.from), Math.max(old.to, wide.to))],
      ['the icon event', setAt(s.config, ['icons', 0, 'holdFrames'], 11), touching(s.doc, 100, 120)],
      ['intro text', setAt(s.config, ['intro', 'kicker'], 'Another'), touching(s.doc, 0, 30)],
      ['the plate text', setAt(s.config, ['ending', 'plateEn'], 'Other'), touching(s.doc, 340, 390)],
      ['the cards header string', setAt(s.config, ['strings', 'cardsHeader'], 'Other'), touching(s.doc, 270, 360)],
      ['the mix stem (audio only)', setAt(s.config, ['bindings', 'music', 'sha256'], '0'.repeat(64)), []],
      ['the end-card music tail position (audio only)', setAt(s.config, ['ending', 'tailFrom'], 101), []],
    ];
    for (const [what, cfg, expected] of cases) {
      const got = stale(cfg);
      assert.deepEqual(got, expected, `${what}: stale ${got} expected ${expected}`);
    }
    // a picture clip: only the segments that mount S3's video
    const clipStale = stale(setAt(s.config, ['bindings', 'shots', 'S3', 'segments', 'S3', 'sha256'], '1'.repeat(64)));
    assert.ok(clipStale.length > 0 && clipStale.length < s.doc.segments.length, `clip: ${clipStale}`);
    for (const id of clipStale) {
      const parts = dep.videoSlice(s.config, s.doc.segments.find((x) => x.id === id), {deps: kitDeps(s.config), mode: 'review'}).parts;
      assert.ok('file:picture:S3/S3' in parts, `${id} is stale but does not mount S3`);
    }
    // audio-only changes do not touch a video key but do touch the mix; purely visual changes do not touch the mix
    assert.notEqual(audioKey(setAt(s.config, ['bindings', 'music', 'sha256'], '0'.repeat(64))), audioKey(s.config));
    assert.notEqual(audioKey(setAt(s.config, ['ending', 'tailFrom'], 101)), audioKey(s.config));
    assert.equal(audioKey(setAt(s.config, ['strings', 'cardsHeader'], 'Other')), audioKey(s.config));
    assert.equal(audioKey(setAt(s.config, ['theme', 'mint'], '#000000')), audioKey(s.config));
    assert.equal(audioKey(setAt(s.config, ['shots', 1, 'vi'], 'khac')), audioKey(s.config));
    assert.equal(audioKey(setAt(s.config, ['ending', 'plateEn'], 'Other')), audioKey(s.config));
    // global leaves stale everything
    assert.equal(stale(setAt(s.config, ['theme', 'mint'], '#000000')).length, s.doc.segments.length);
    assert.equal(stale(setAt(s.config, ['review', 'label'], 'OTHER')).length, s.doc.segments.length);
  } finally {
    fs.rmSync(s.dir, {recursive: true, force: true});
  }
});

test('P2-D3: stale reasons name the changed leaf; an unchanged slice says the pins changed', async (t) => {
  const s = setup(t);
  if (!s) return;
  try {
    const seg = s.doc.segments.find((x) => x.start <= 100 && 100 < x.end_exclusive);
    const before = dep.videoSlice(s.config, seg, {deps: kitDeps(s.config), mode: 'review'}).parts;
    const after = dep.videoSlice(setAt(s.config, ['shots', 1, 'words', 0, 'startF'], 95), seg, {deps: kitDeps(s.config), mode: 'review'}).parts;
    assert.match(dep.staleReason(before, after), /shot:S2\.words\.0\.startF/);
    assert.match(dep.staleReason(null, after), /no previous record/);
    assert.match(dep.staleReason(before, before), /pins changed/);
  } finally {
    fs.rmSync(s.dir, {recursive: true, force: true});
  }
});

function fakeEntry(root, kind, key, fileName, bytes) {
  const dir = path.join(root, kind, key);
  fs.mkdirSync(dir, {recursive: true});
  const file = path.join(dir, fileName);
  fs.writeFileSync(file, bytes);
  const sha = crypto.createHash('sha256').update(bytes).digest('hex');
  fs.writeFileSync(path.join(dir, 'record.json'), JSON.stringify({key, output_sha256: sha, render_seconds: 7}));
  fs.writeFileSync(`${file}.render-record.json`, JSON.stringify({output_sha256: sha}));
  return file;
}

test('P2-D4: the cache: COMPLETE is reused, a flipped byte is CORRUPT and refused, --force-segment re-renders, last-run names the reason', async (t) => {
  const s = setup(t);
  if (!s) return;
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-p2cache-'));
  try {
    const plan = {segments: s.doc.segments.map((x) => ({...x})), sha256: 'x', total: s.doc.total_frames};
    const pins = {video: PINS, audio: PINS};
    const opts = {cache: root, mode: 'review', pins, deps: kitDeps(s.config)};
    let built = cache.planBuild(s.config, plan, opts);
    assert.ok(built.rows.every((r) => r.status === 'RENDER'));
    const victim = built.rows[2];
    const file = fakeEntry(root, 'composite.segment', victim.key, 'segment.mp4', Buffer.from('segment bytes'));
    built = cache.planBuild(s.config, plan, opts);
    assert.equal(built.rows[2].status, 'COMPLETE');
    assert.equal(built.rows[2].recorded_seconds, 7);
    assert.equal(built.rows.filter((r) => r.status === 'COMPLETE').length, 1);
    // flip one byte: the entry no longer matches its record
    const bytes = fs.readFileSync(file);
    bytes[3] ^= 0xff;
    fs.writeFileSync(file, bytes);
    built = cache.planBuild(s.config, plan, opts);
    assert.equal(built.rows[2].status, 'CORRUPT');
    assert.match(built.rows[2].reason, /sha256 .* differs from its record/);
    // the build refuses it, naming the segment, before any child runs
    await assert.rejects(cache.runBuild({
      config: s.config, built, cache: root, out: path.join(root, 'film.mp4'), joinSegments: async () => assert.fail('joined a corrupt cache'), childArgs: () => assert.fail('rendered before refusing'),
      audioChildArgs: () => assert.fail('rendered before refusing'), plan, mode: 'review', pins, configFile: 'c', configSha: 'c',
    }), /segment cache refused: seg-03/);
    // --force-segment turns CORRUPT into a render
    built = cache.planBuild(s.config, plan, {...opts, force: [victim.id]});
    assert.equal(built.rows[2].status, 'RENDER');
    assert.match(built.rows[2].reason, /forced/);
    // last-run: the reason of a stale segment is computed against the previous slices
    fs.writeFileSync(path.join(root, 'last-run.json'), JSON.stringify({mode: 'review', segments: Object.fromEntries(built.rows.map((r) => [r.id, {key: r.key, parts: r.slice.parts}])), audio: {key: 'k', parts: built.audio.slice.parts}}));
    const next = cache.planBuild(setAt(s.config, ['shots', 1, 'words', 0, 'startF'], 95), plan, opts);
    const stale = next.rows.filter((r) => r.status === 'RENDER' && /words/.test(r.reason || ''));
    assert.ok(stale.length >= 1 && stale.every((r) => /shot:S2\.words\.0\.startF/.test(r.reason)), next.rows.map((r) => r.reason).join(' | '));
    assert.match(cache.formatTable(next), /to render/);
  } finally {
    fs.rmSync(root, {recursive: true, force: true});
    fs.rmSync(s.dir, {recursive: true, force: true});
  }
});

test('P2-D5: master mode: mode / scale / crf / Remotion version / catalog enter the key; a master key differs from the review key', () => {
  const catalogFile = path.join(KIT, '..', 'schemas', 'transition-presets.json');
  const mk = (mode, scale, remotionVersion) => cache.buildPins({kitRoot: KIT, mode, scale, remotionVersion, browserFile: null, fonts: {}, catalogFile});
  const review = mk('review', 1, '4.0.0');
  const master = mk('master', 2, '4.0.0');
  assert.equal(review.video.codec.crf, 18);
  assert.equal(master.video.codec.crf, 16);
  assert.notDeepEqual(review.video, master.video);
  assert.notEqual(review.video.kit_src_sha256, review.audio.kit_src_sha256, 'the audio pin also covers the audio-only sources, the video pin does not');
  assert.notDeepEqual(review.video, mk('review', 1, '4.0.1').video);
  assert.equal(review.video.catalog_sha256.length, 64);
  assert.equal(dep.sourceSha(path.join(KIT, 'src')).length, 64);
});

test('P2-D6: --segments-file: a file for another fps / length / schema, or a cut inside a both-pictures window, is refused (CLI, no browser)', async (t) => {
  const s = setup(t);
  if (!s) return;
  try {
    const cfgFile = path.join(s.dir, 'config.json');
    fs.writeFileSync(cfgFile, JSON.stringify(s.config));
    let n = 0;
    const run = (doc) => {
      n += 1;
      const f = path.join(s.dir, `seg-${n}.json`);
      fs.writeFileSync(f, JSON.stringify(doc));
      return spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--segments-file', f, '--segments-plan'], {encoding: 'utf8'});
    };
    const ok = run(s.doc);
    assert.equal(ok.status, 0, ok.stderr);
    assert.equal(JSON.parse(ok.stdout).source, 'config');
    assert.equal(JSON.parse(ok.stdout).segments.length, s.doc.segments.length);
    assert.match(run({...s.doc, fps: 24}).stderr, /fps 24 differs from the config fps 30/);
    assert.match(run({...s.doc, total_frames: s.doc.total_frames + 1}).stderr, /total_frames .* differs/);
    assert.match(run({...s.doc, schema: 'x'}).stderr, /schema must be jjv\/segments\/v1/);
    // a cut inside push_slide (shows both pictures) is refused by the same declared-segment rules as config.segments
    const bad = clone(s.doc);
    const w = dep.transitionSpan(s.config.transitions[1], kitDeps(s.config));
    const i = bad.segments.findIndex((x) => x.start <= w.from && w.to <= x.end_exclusive);
    assert.ok(i >= 0);
    const mid = w.from + 3;
    const cutSeg = bad.segments[i];
    bad.segments.splice(i, 1, {...cutSeg, end_exclusive: mid}, {...cutSeg, id: 'extra', start: mid});
    const refused = run(bad);
    assert.notEqual(refused.status, 0, 'a cut inside a shows_both window was accepted');
    assert.match(refused.stderr, /falls inside the effect window/);
  } finally {
    fs.rmSync(s.dir, {recursive: true, force: true});
  }
});
