// T-E45 edit path: the VIDEO slice must not carry what only the validator reads. `shots[].onsetEvidence` (a label naming the word-timing document the
// onset came from) and `shots[].speechOnsetF` (the first spoken frame the dip-peak rule compares against) are read by src/validate.mjs and by NO
// compositor component, so a one-word timing edit (a new word-timing document: a new label on EVERY shot) must stale only the shot whose words
// moved, not the whole film (the first measurement stale 23 of 49 segments for one word because of this label).
// Pure part: keys. Render part: every such leaf (and every other leaf outside the slice) leaves the frames byte-identical.
import test from 'node:test';
import {assert, dep, fs, kitDeps, openHarness, os, path, propertyCheck, richConfig, segmentsDoc, have, clone} from './p2-lib.mjs';

const PINS = {kit: 'test', remotion: 'test', mode: 'review', scale: 1};
const key = (cfg, seg) => dep.nodeKey('video', dep.videoSlice(cfg, seg, {deps: kitDeps(cfg), mode: 'review'}), PINS);

function withEvidence(dir) {
  const config = richConfig(dir);
  config.shots.forEach((s) => {
    s.speechOnsetF = s.start + 4;
    s.onsetEvidence = 'word-timing-A.json first RMS run';
  });
  return config;
}

test('R15-V1: onsetEvidence / speechOnsetF are not in any video slice; a moved word is (only the segments that show that shot)', () => {
  const config = withEvidence(fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15v-')));
  const doc = segmentsDoc(config, {minFrames: 40});
  const relabel = clone(config);
  relabel.shots.forEach((s) => { s.onsetEvidence = 'word-timing-B.json first RMS run'; s.speechOnsetF += 1; });
  for (const seg of doc.segments) assert.equal(key(relabel, seg), key(config, seg), `${seg.id}: a validator-only label made the segment stale`);
  const moved = clone(config);
  moved.shots[1].words[0].startF += 2; // shot S2 spans f90..149
  const stale = doc.segments.filter((seg) => key(moved, seg) !== key(config, seg)).map((seg) => seg.id);
  const showing = doc.segments.filter((seg) => seg.start < 150 && 90 < seg.end_exclusive).map((seg) => seg.id);
  assert.deepEqual(stale.sort(), showing.sort());
  assert.ok(stale.length >= 1 && stale.length <= 2, `${stale.length} segments stale for one word`);
});

test('R15-V2: rendered frames do not change with the validator-only leaves (property check on the shot segments, real compositor)', {timeout: 1200000}, async (t) => {
  if (!have()) return t.skip('no browser / Remotion packages / fonts, or KIT_SKIP_RENDER_SMOKE=1');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15v-'));
  const config = withEvidence(dir);
  const doc = segmentsDoc(config, {minFrames: 40});
  const harness = await openHarness(config, dir);
  try {
    const seg = doc.segments.find((s) => s.start <= 100 && 100 < s.end_exclusive);
    const result = await propertyCheck({harness, config, seg, pins: PINS});
    assert.equal(result.ok, true, `leaves outside the slice changed the pixels: ${result.offenders.join(', ')}`);
    // the two labels were among the mutated leaves (they must be outside the slice, accepted) and the frames stayed byte-identical
    const withLabels = clone(config);
    withLabels.shots.forEach((s) => { s.onsetEvidence = 'other'; s.speechOnsetF += 1; });
    const frames = [seg.start, seg.start + Math.floor((seg.end_exclusive - seg.start - 1) / 2), seg.end_exclusive - 1];
    assert.deepEqual(await harness.stills(withLabels, frames), result.baseline);
  } finally {
    await harness.close();
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
