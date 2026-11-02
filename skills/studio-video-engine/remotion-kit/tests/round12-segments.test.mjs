// T-E42 addendum: the ending as its own segment. Pure plan tests (no Remotion, no ffmpeg): the segment plan covers the film exactly, the
// default cut is the first frame after which no shot video is mounted (decision: the MAIN segment owns the iris), explicit cuts are
// validated, and the video-frame set that decides staging is what the compositor really mounts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import {makeConfig} from './fixture.mjs';

const require = createRequire(import.meta.url);
const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const seg = require('../lib/segments.cjs');
const pm = await import(pathToFileURL(path.join(KIT, 'src', 'picture-mode.mjs')).href);
const presets = await import(pathToFileURL(path.join(KIT, 'src', 'presets.mjs')).href);
const deps = (config) => ({pictureMode: pm.pictureMode, transitionIndex: pm.transitionIndex, tailWindow: pm.tailWindow, tailVisibleAt: pm.tailVisibleAt, motion: presets.resolveMotion(config), rendersAs: presets.rendersAs, showsBoth: (t) => Boolean((pm.TYPE_TABLE[t.type] || {}).showsBoth)});
const TOTAL = 270;

test('R12-1: an iris ending gives main + ending, covering [0,total) exactly, cut at the first frame with no shot video (discIn + 3)', () => {
  const c = makeConfig();
  const plan = seg.planSegments(c, deps(c));
  assert.equal(plan.total, TOTAL);
  assert.deepEqual(plan.segments.map((s) => [s.id, s.kind, s.start, s.end_exclusive, s.frames]), [['main', 'main', 0, 147, 147], ['ending', 'ending', 147, 270, 123]]);
  assert.equal(plan.source, 'ending');
  assert.match(plan.sha256, /^[0-9a-f]{64}$/);
  // exact cover, no overlap, no gap
  let at = 0;
  for (const s of plan.segments) { assert.equal(s.start, at); at = s.end_exclusive; }
  assert.equal(at, TOTAL);
});

test('R12-2: the plan sha changes with the cut and is stable for the same cut', () => {
  const c = makeConfig();
  const a = seg.planSegments(c, deps(c));
  const b = seg.planSegments(makeConfig(), deps(c));
  assert.equal(a.sha256, b.sha256);
  const moved = makeConfig();
  moved.ending.discIn = 145; moved.ending.discSlideStart = 146;
  assert.notEqual(seg.planSegments(moved, deps(moved)).sha256, a.sha256);
});

test('R12-3: no iris ending and no declared segments = one segment (the whole film), no join', () => {
  const c = makeConfig();
  c.transitions = c.transitions.filter((t) => t.type !== 'iris');
  delete c.ending.irisStart;
  const plan = seg.planSegments(c, deps(c));
  assert.deepEqual(plan.segments.map((s) => [s.id, s.start, s.end_exclusive]), [['main', 0, TOTAL]]);
  assert.equal(plan.source, 'single');
});

test('R12-4: the frames that need shot video stop at the cut; none lies in the ending segment', () => {
  const c = makeConfig();
  const plan = seg.planSegments(c, deps(c));
  const ending = plan.segments.find((s) => s.id === 'ending');
  assert.deepEqual(seg.videoFrames(c, deps(c), ending.start, ending.end_exclusive - 1), []);
  const main = plan.segments.find((s) => s.id === 'main');
  const need = seg.videoFrames(c, deps(c), main.start, main.end_exclusive - 1);
  assert.ok(need.includes(146) && need.includes(30) && !need.includes(147));
  assert.ok(!need.includes(10), 'the intro is not shot video');
});

test('R12-5: declared segments are validated: contiguous, exact cover, unique ids, frames >= 1', () => {
  const c = makeConfig();
  const ok = [{id: 'a', kind: 'main', start: 0, end_exclusive: 100}, {id: 'b', kind: 'main', start: 100, end_exclusive: 147}, {id: 'e', kind: 'ending', start: 147, end_exclusive: 270}];
  c.segments = ok;
  assert.deepEqual(seg.planSegments(c, deps(c)).segments.map((s) => s.id), ['a', 'b', 'e']);
  const bad = (mutate, text) => {
    const d = makeConfig();
    d.segments = structuredClone(ok);
    mutate(d.segments);
    assert.throws(() => seg.planSegments(d, deps(d)), (e) => e.message.includes(text), text);
  };
  bad((s) => { s[1].start = 101; }, 'gap');
  bad((s) => { s[1].start = 99; }, 'overlap');
  bad((s) => { s[2].end_exclusive = 269; }, 'do not end at');
  bad((s) => { s[0].start = 1; }, 'must start at 0');
  bad((s) => { s[1].id = 'a'; }, 'duplicate');
  bad((s) => { s[1].end_exclusive = 100; s[2].start = 100; }, 'frames');
});

test('R12-6: a cut inside the iris window or inside a both-pictures window is refused with the transition named', () => {
  const c = makeConfig();
  c.segments = [{id: 'm', kind: 'main', start: 0, end_exclusive: 135}, {id: 'e', kind: 'ending', start: 135, end_exclusive: 270}];
  assert.throws(() => seg.planSegments(c, deps(c)), (e) => /cut at f135/.test(e.message) && /I1/.test(e.message));
  const d = makeConfig();
  d.transitions[0] = {...d.transitions[0], type: 'dissolve', frames: 8, start: 90, continuity: 'agree'};
  d.segments = [{id: 'm', kind: 'main', start: 0, end_exclusive: 93}, {id: 'e', kind: 'ending', start: 93, end_exclusive: 270}];
  assert.throws(() => seg.planSegments(d, deps(d)), (e) => /cut at f93/.test(e.message) && /W1/.test(e.message)); // inside the dissolve window 90..97
});

test('R12-7: a segment record names its range and the plan sha, and uses_shot_video is derived from the staged sources', () => {
  const c = makeConfig();
  const plan = seg.planSegments(c, deps(c));
  const ending = plan.segments[1];
  const rec = seg.segmentRecord(plan, 'ending', [{role: 'logo'}, {role: 'dialogue'}]);
  assert.deepEqual([rec.id, rec.start, rec.end_exclusive, rec.frames, rec.plan_sha256, rec.uses_shot_video], ['ending', ending.start, ending.end_exclusive, ending.frames, plan.sha256, false]);
  assert.equal(seg.segmentRecord(plan, 'main', [{role: 'picture'}]).uses_shot_video, true);
  assert.equal(seg.segmentRecord(plan, 'main', [{role: 'tail'}]).uses_shot_video, true);
  assert.throws(() => seg.segmentRecord(plan, 'nope', []), /unknown segment/);
});

test('R12-8: the codec set is one constant shared by every segment', () => {
  const a = seg.codecParams({mode: 'review'});
  const b = seg.codecParams({mode: 'master'});
  assert.equal(a.codec, 'h264'); assert.equal(a.pixelFormat, 'yuv420p'); assert.equal(a.crf, 18); assert.equal(b.crf, 16);
  assert.equal(a.muted, true);
  assert.deepEqual({...a, crf: 0}, {...b, crf: 0});
  assert.ok(a.x264.includes('open-gop=0') || a.ffmpegArgs.join(' ').includes('cgop'));
});
