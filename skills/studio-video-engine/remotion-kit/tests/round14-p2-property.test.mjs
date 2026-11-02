// T-E45 P2, spec 3.3 gate: the dependency slice of a segment (lib/segdeps.cjs) is a CONSERVATIVE description of what its pixels depend on.
// Every leaf of the kit config outside a segment's slice is mutated (all at once, greedily; a leaf is kept only when the config still
// validates and the node key is unchanged) and the segment's first / middle / last frame must be BYTE-IDENTICAL to the unmutated render.
// The test must be able to go red: a slice function that drops a part the compositor reads ("mutant") is caught, naming the leaf.
// Real compositor, CPU, one bundle + one browser for the whole file; skipped without a cached browser or with KIT_SKIP_RENDER_SMOKE=1.
import test from 'node:test';
import {assert, dep, fs, kitDeps, openHarness, os, path, propertyCheck, richConfig, segmentsDoc, have, mutateLeaf, pinsFor, leaves, leafClass} from './p2-lib.mjs';

const PINS = pinsFor();
const sliceKey = (cfg, seg) => dep.nodeKey('video', dep.videoSlice(cfg, seg, {deps: kitDeps(cfg), mode: 'review'}), PINS);
const segAt = (doc, f) => doc.segments.find((s) => f >= s.start && f < s.end_exclusive);

test('P2-P1: every leaf outside a segment slice leaves its frames byte-identical; a slice that drops a part is killed', {timeout: 1800000}, async (t) => {
  if (!have()) return t.skip('no browser / Remotion packages / fonts, or KIT_SKIP_RENDER_SMOKE=1');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-p2prop-'));
  const config = richConfig(dir);
  const doc = segmentsDoc(config, {minFrames: 8});
  const wanted = {intro: 12, shot_span: 45, transition: 152, cards: 300, ending: 385};
  const segs = Object.fromEntries(Object.entries(wanted).map(([k, f]) => [k, segAt(doc, f)]));
  for (const [k, s] of Object.entries(segs)) assert.ok(s, `no segment at the frame chosen for ${k} (${JSON.stringify(doc.segments.map((x) => [x.id, x.start, x.end_exclusive]))})`);
  const harness = await openHarness(config, dir);
  try {
    const report = {};
    for (const [kind, seg] of Object.entries(segs)) {
      const result = await propertyCheck({harness, config, seg, pins: PINS});
      report[kind] = {id: seg.id, range: [seg.start, seg.end_exclusive], accepted: result.accepted, in_slice: result.in_slice, skipped_invalid: result.skipped_invalid};
      assert.equal(result.ok, true, `${kind} segment ${seg.id}: leaves outside the slice changed its pixels: ${result.offenders.join(', ')}`);
      assert.ok(result.accepted >= 30, `${kind}: only ${result.accepted} leaves were mutated outside the slice (the check would be vacuous)`);
    }
    process.stdout.write(`P2-P1 report ${JSON.stringify(report)}\n`);

    // NON-VACUITY: a leaf the compositor reads DOES change the pixels, and then it is in the slice (the key changes)
    const sensitive = [
      ['cards', ['theme', 'mint']],
      ['cards', ['strings', 'cardsHeader']],
      ['intro', ['intro', 'kicker']],
      ['ending', ['ending', 'plateEn']],
    ];
    for (const [kind, p] of sensitive) {
      const seg = segs[kind];
      const mutated = mutateLeaf(config, p);
      assert.notEqual(sliceKey(mutated, seg), sliceKey(config, seg), `${p.join('.')} must be in the ${kind} slice`);
      const frames = [seg.start, seg.start + Math.floor((seg.end_exclusive - seg.start - 1) / 2), seg.end_exclusive - 1];
      const [a, b] = [await harness.stills(config, frames), await harness.stills(mutated, frames)];
      assert.ok(a.some((h, i) => h !== b[i]), `${p.join('.')} did not change any pixel of ${kind}: the sensitivity case is vacuous`);
    }

    // MUTANT: drop one part from the slice -> the property test must go red and name the leaves
    const dropping = (name) => (cfg, seg, ctx) => {
      const slice = dep.videoSlice(cfg, seg, ctx);
      delete slice.parts[name];
      return slice;
    };
    const m1 = await propertyCheck({harness, config, seg: segs.cards, pins: PINS, sliceFn: dropping('global.theme')});
    assert.equal(m1.ok, false, 'mutant "theme dropped from the slice" survived');
    assert.ok(m1.offenders.some((o) => o.startsWith('theme.')), `theme leaves not named: ${m1.offenders.join(', ')}`);
    const m2 = await propertyCheck({harness, config, seg: segs.cards, pins: PINS, sliceFn: dropping('strings')});
    assert.equal(m2.ok, false, 'mutant "strings dropped from the slice" survived');
    assert.ok(m2.offenders.some((o) => o.startsWith('strings.')), `strings leaves not named: ${m2.offenders.join(', ')}`);
    const m3 = await propertyCheck({harness, config, seg: segs.ending, pins: PINS, sliceFn: dropping('ending.plate')});
    assert.equal(m3.ok, false, 'mutant "ending.plate dropped from the slice" survived');
    assert.ok(m3.offenders.some((o) => o.startsWith('ending.plate')), `plate leaves not named: ${m3.offenders.join(', ')}`);
    process.stdout.write(`P2-P1 mutants killed: theme -> ${m1.offenders.join(',')}; strings -> ${m2.offenders.join(',')}; plate -> ${m3.offenders.join(',')}\n`);
    // coverage of the leaf classes (collapsed array indices) the property test walked
    const classes = new Set(leaves(config).map((l) => leafClass(l.path)));
    assert.ok(classes.size >= 90, `only ${classes.size} leaf classes`);
  } finally {
    await harness.close();
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
