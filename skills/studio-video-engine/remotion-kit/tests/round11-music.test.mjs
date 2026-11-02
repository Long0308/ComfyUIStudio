// Round 11 / T-E42 item 3: the music bed POLICY. The engine declares `ending.music_bed` (extend by looping a phrase with a crossfade, duck under words);
// the kit plans it as pure data (music-plan.mjs) and renders the plan with Remotion <Audio> segments (music.jsx). No policy = the audio is exactly as before.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const plan = await import(pathToFileURL(path.join(KIT, 'src', 'music-plan.mjs')).href);

const FPS = 30;
const BED = {extend: 'loop_phrase_crossfade', loop_start_s: 4, loop_end_s: 56, crossfade_frames: 30, duck_db: 14, duck_attack_frames: 4, duck_release_frames: 8, duck_under: 'words'};
const WORDS = [{from: 100, to: 130}, {from: 400, to: 440}, {from: 1000, to: 1060}, {from: 3000, to: 3090}, {from: 3200, to: 3240}];
const make = (over = {}) => plan.planMusic({totalFrames: 3300, fps: FPS, stemSeconds: 60, bed: BED, windows: WORDS, ...over});
const stemPos = (seg, g) => seg.startFromFrame + (g - seg.from);
const inSeg = (seg, g) => g >= seg.from && g < seg.from + seg.durationInFrames;

test('3a: the loop plan covers EVERY frame of the film, starting with the stem from its first frame', () => {
  for (const total of [1801, 2520, 3300, 5000, 9000]) {
    const p = make({totalFrames: total});
    assert.equal(p.segments[0].from, 0);
    assert.equal(p.segments[0].startFromFrame, 0);
    assert.equal(p.segments[0].fadeIn, 0);
    for (let g = 0; g < total; g += 1) assert.ok(p.segments.some((s) => inSeg(s, g)), `total ${total}: frame ${g} has no music`);
    const last = p.segments[p.segments.length - 1];
    assert.equal(last.from + last.durationInFrames, total, `total ${total}: the last segment ends with the film`);
    assert.deepEqual(p.uncovered, []);
  }
});

test('3b: no gap and no overlap beyond the crossfade: neighbours overlap by exactly crossfade_frames and never more than two segments sound at once', () => {
  const p = make();
  const X = BED.crossfade_frames;
  assert.ok(p.segments.length >= 3, 'the 60 s stem loops at least twice for 110 s');
  for (let i = 1; i < p.segments.length; i += 1) {
    const prev = p.segments[i - 1];
    assert.equal(p.segments[i].from, prev.from + prev.durationInFrames - X, `segment ${i} starts X frames before the previous one ends`);
    assert.equal(p.segments[i].fadeIn, X);
    assert.equal(prev.fadeOut, X);
  }
  for (let g = 0; g < 3300; g += 1) {
    const n = p.segments.filter((s) => inSeg(s, g)).length;
    assert.ok(n === 1 || n === 2, `frame ${g}: ${n} segments`);
    if (n === 2) {
      const [a, b] = p.segments.filter((s) => inSeg(s, g));
      assert.ok(g >= b.from && g < b.from + X, `frame ${g}: a second segment only inside the crossfade window`);
      assert.ok(a.from < b.from);
    }
  }
});

test('3c: the crossfade sums to 1 on every overlap frame (linear in / linear out), so the bed has no dip and no bump at the seam', () => {
  const p = make();
  let overlapFrames = 0;
  for (let g = 0; g < 3300; g += 1) {
    const active = p.segments.filter((s) => inSeg(s, g));
    if (active.length < 2) continue;
    overlapFrames += 1;
    const sum = active.reduce((acc, s) => acc + plan.segmentGain(s, g - s.from), 0);
    assert.ok(Math.abs(sum - 1) < 1e-9, `frame ${g}: crossfade sums to ${sum}`);
  }
  assert.equal(overlapFrames, BED.crossfade_frames * (p.segments.length - 1));
  // outside the overlaps a segment is at full gain
  const mid = p.segments[1];
  assert.equal(plan.segmentGain(mid, Math.floor(mid.durationInFrames / 2)), 1);
});

test('3d: the loop joins at the DECLARED phrase boundary: at the join frame the earlier pass is at loop_end and the next one at loop_start', () => {
  const p = make();
  const X = BED.crossfade_frames;
  const loopStart = Math.round(BED.loop_start_s * FPS);
  const loopEnd = Math.round(BED.loop_end_s * FPS);
  for (let i = 1; i < p.segments.length; i += 1) {
    const prev = p.segments[i - 1];
    const next = p.segments[i];
    assert.equal(next.startFromFrame, loopStart - X, 'the new pass starts X frames before the loop start so the crossfade lands on the phrase boundary');
    const join = next.from + X; // the first frame at which the new pass is at full gain
    assert.equal(stemPos(next, join), loopStart);
    assert.equal(stemPos(prev, join), loopEnd, 'the earlier pass has reached loop_end exactly at the join');
  }
  assert.equal(p.bed.loopStartFrame, loopStart);
  assert.equal(p.bed.loopEndFrame, loopEnd);
});

test('3e: the last pass never reads beyond the stem, and the film ends on a fade-out of the final segment', () => {
  for (const total of [1801, 2520, 3300, 4417, 9000]) {
    const p = make({totalFrames: total});
    for (const s of p.segments) assert.ok(stemPos(s, s.from + s.durationInFrames - 1) <= 60 * FPS - 1, `total ${total}: a segment reads past the stem`);
    const last = p.segments[p.segments.length - 1];
    assert.ok(last.fadeOut > 0 && last.fadeOut <= BED.crossfade_frames, 'a final fade-out so the cut at the end of the film is not abrupt');
    assert.equal(plan.segmentGain(last, last.durationInFrames - 1) < 1, true);
  }
});

test('3f: a film shorter than the stem is one segment (no loop)', () => {
  const p = make({totalFrames: 1500});
  assert.equal(p.segments.length, 1);
  assert.equal(p.segments[0].durationInFrames, 1500);
});

test('3g: ducking under words: full duck_db under every word frame, unity far from words, linear attack before and release after', () => {
  const p = make();
  const full = 10 ** (-BED.duck_db / 20);
  for (const w of WORDS) {
    for (let g = w.from; g < w.to; g += 1) assert.ok(Math.abs(p.duck(g) - full) < 1e-12, `frame ${g} under a word: ${p.duck(g)}`);
  }
  assert.equal(p.duck(0), 1);
  assert.equal(p.duck(2000), 1);
  assert.equal(p.duck(3299), 1);
  // attack: the 4 frames before a word walk down, monotonically, ending at the full duck on the word's first frame
  const w = WORDS[0];
  const attack = [w.from - 4, w.from - 3, w.from - 2, w.from - 1, w.from].map((g) => p.duck(g));
  assert.equal(attack[0], 1);
  for (let i = 1; i < attack.length; i += 1) assert.ok(attack[i] < attack[i - 1], `attack frame ${i}`);
  assert.ok(Math.abs(attack[4] - full) < 1e-12);
  // release: 8 frames after the word's last frame walk back up to 1
  const release = [];
  for (let k = 0; k <= 8; k += 1) release.push(p.duck(w.to - 1 + k));
  assert.ok(Math.abs(release[0] - full) < 1e-12);
  for (let i = 1; i < release.length; i += 1) assert.ok(release[i] > release[i - 1], `release frame ${i}`);
  assert.equal(release[8], 1);
  for (let g = 0; g < 3300; g += 1) assert.ok(p.duck(g) >= full - 1e-12 && p.duck(g) <= 1 + 1e-12);
  // two close words share one duck: the gap between them never rises above the ramps of either
  const close = plan.planMusic({totalFrames: 600, fps: FPS, stemSeconds: 60, bed: BED, windows: [{from: 100, to: 120}, {from: 124, to: 140}]});
  assert.ok(close.duck(122) <= close.duck(121) + 1e-12 || close.duck(122) < 1, 'a 4-frame gap is not a full release');
  assert.ok(close.duck(122) < 1);
});

test('3h: without words, or with extend "none" and no duck keys, the gain is exactly 1', () => {
  assert.equal(make({windows: []}).duck(500), 1);
  const none = plan.planMusic({totalFrames: 2000, fps: FPS, stemSeconds: 60, bed: {extend: 'none'}, windows: WORDS});
  assert.equal(none.duck(110), 1, 'no duck_db declared: nothing to duck');
});

test('3i: extend "none" plays the stem once (exactly as before) and reports the frames it cannot cover instead of looping silently', () => {
  const short = plan.planMusic({totalFrames: 3300, fps: FPS, stemSeconds: 60, bed: {extend: 'none'}, windows: []});
  assert.equal(short.segments.length, 1);
  assert.deepEqual(short.segments[0], {from: 0, durationInFrames: 1800, startFromFrame: 0, fadeIn: 0, fadeOut: 0});
  assert.deepEqual(short.uncovered, [{from: 1800, to: 3300}]);
  const long = plan.planMusic({totalFrames: 1500, fps: FPS, stemSeconds: 60, bed: {extend: 'none'}, windows: []});
  assert.deepEqual(long.segments[0], {from: 0, durationInFrames: 1500, startFromFrame: 0, fadeIn: 0, fadeOut: 0});
  assert.deepEqual(long.uncovered, []);
});

test('3j: a policy that cannot work is refused with the reason (no silent clamp)', () => {
  const bad = (bed, re, extra = {}) => assert.throws(() => plan.planMusic({totalFrames: 3300, fps: FPS, stemSeconds: 60, bed, windows: [], ...extra}), re);
  bad({...BED, loop_end_s: 70}, /loop_end_s .* beyond the stem/);
  bad({...BED, loop_end_s: 4}, /loop_end_s must be greater than loop_start_s/);
  bad({...BED, loop_start_s: 0.5}, /crossfade_frames 30 .* loop_start_s/);
  bad({...BED, crossfade_frames: 2000}, /crossfade_frames/);
  bad({extend: 'loop_phrase_crossfade'}, /loop_start_s and loop_end_s/);
  bad({...BED, extend: 'bounce'}, /extend must be/);
  bad({...BED, duck_db: 0}, /duck_db must be > 0/);
  bad({...BED, duck_under: 'music'}, /duck_under must be 'words'/);
  bad({...BED, mystery: 1}, /unknown key 'mystery'/);
  bad(BED, /stemSeconds/, {stemSeconds: 0});
  bad(BED, /totalFrames/, {totalFrames: 0});
});

test('3k: the kit reads the policy from config.music (camelCase) or config.ending.musicBed, and from the engine snake_case form', () => {
  const camel = {extend: 'loop_phrase_crossfade', loopStartS: 4, loopEndS: 56, crossfadeFrames: 30, duckDb: 14, duckAttackFrames: 4, duckReleaseFrames: 8, duckUnder: 'words'};
  assert.deepEqual(plan.normaliseBed(camel), plan.normaliseBed(BED));
  const c = makeConfig();
  assert.equal(plan.musicPolicy(c), null, 'no policy in the config');
  assert.equal(plan.selectMusicMode(c), 'legacy');
  c.music = {stemSeconds: 60, bed: camel};
  assert.equal(plan.selectMusicMode(c), 'plan');
  assert.equal(plan.musicPolicy(c).stemSeconds, 60);
  const d = makeConfig();
  d.ending.musicBed = camel;
  d.music = {stemSeconds: 60};
  assert.equal(plan.selectMusicMode(d), 'plan');
  const e = makeConfig();
  e.ending.musicBed = camel; // a policy without the stem length cannot be planned
  assert.throws(() => plan.musicPolicy(e), /stemSeconds/);
});

test('3l: word windows are the dialogue words plus the card windows, merged and sorted (global frames)', () => {
  const c = makeConfig(); // outroStart 150, cards at 0..30, 30..60, 60..90 of the outro
  const w = plan.wordWindows(c);
  assert.ok(w.every((x, i) => x.from < x.to && (i === 0 || x.from > w[i - 1].to)), 'sorted, non-empty, merged (no touching windows)');
  assert.ok(w.some((x) => x.from === 34 && x.to === 40), 'a dialogue word window (startF/endF of the first shot)');
  assert.ok(w.some((x) => x.from === 150 && x.to === 240), 'the three touching card windows merge into 150..240');
});

test('3m: the derived first-episode timeline: 3240 main frames + 60 end card = 3300 frames of music from a 60 s stem (numbers for the report)', () => {
  const p = make();
  const rows = p.segments.map((s, i) => `#${i} from ${s.from} dur ${s.durationInFrames} startFrom ${s.startFromFrame} fadeIn ${s.fadeIn} fadeOut ${s.fadeOut}`);
  console.log(`# music plan total 3300, stem 60 s, loop ${BED.loop_start_s}-${BED.loop_end_s} s, crossfade ${BED.crossfade_frames} f:\n#   ${rows.join('\n#   ')}`);
  assert.deepEqual(p.segments.map((s) => [s.from, s.durationInFrames, s.startFromFrame, s.fadeIn, s.fadeOut]), [[0, 1680, 0, 0, 30], [1650, 1590, 90, 30, 30], [3210, 90, 90, 30, 30]]);
});

// ---------------------------------------------------------------------------------------------------- film.jsx wiring
test('3n: film.jsx keeps the legacy audio lines byte-identical and mounts the plan only through selectMusicMode', () => {
  const film = fs.readFileSync(path.join(KIT, 'src', 'film.jsx'), 'utf8');
  assert.match(film, /<Audio src=\{staticFile\(sources\.music\)\} \/>/, 'the v008-parity music line is untouched');
  assert.match(film, /startFrom=\{ending\.tailFrom\}/, 'the legacy end-card tail is untouched');
  assert.match(film, /selectMusicMode\(config\)/);
  assert.match(film, /<MusicBed/);
  assert.ok(fs.existsSync(path.join(KIT, 'src', 'music.jsx')));
  const music = fs.readFileSync(path.join(KIT, 'src', 'music.jsx'), 'utf8');
  assert.match(music, /planMusic/);
  assert.match(music, /startFrom=\{seg\.startFromFrame\}/);
  assert.match(music, /segmentGain/);
});
