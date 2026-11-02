// Fork F / gap 2: the approved v013 push divides the frame by the window length (progress k/frames, ease-out cubic, 1.04 -> 1.00) and
// reaches exactly 1.00 only on the first frame AFTER the window. The kit used k/(frames-1) and so landed on 1.00 one frame early.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CATALOG} from '../src/catalog.generated.mjs';
import {auditPreset, auditSeries, coverage, descriptor, descriptorSeries} from '../src/catalog-render.mjs';
import {easeOut, resolveParams} from '../src/presets.mjs';

const params = resolveParams(CATALOG.presets.cut_push, {});

test('R14-1: cut_push progress is k/frames: the first frame is scale_from, frame k has 1 + (scale_from-1) * (1 - easeOut(k/frames))', () => {
  const frames = 12;
  const s = descriptorSeries('cut_push', params, frames, 0);
  assert.equal(s[0].in.scale, 1.04);
  for (let k = 0; k < frames; k += 1) {
    const want = 1 + (params.scale_from - 1) * (1 - easeOut(k / frames));
    assert.ok(Math.abs(s[k].in.scale - want) < 1e-12, `k=${k}: ${s[k].in.scale} vs ${want}`);
  }
  // v013 numbers: B+6 is 1.005 (cubic ease out at 0.5), B+11 is within 3e-5 of 1 but NOT 1: the plain picture starts at B+12
  assert.ok(Math.abs(s[6].in.scale - 1.005) < 1e-9);
  assert.ok(s[11].in.scale > 1 && s[11].in.scale < 1.0001, String(s[11].in.scale));
});

test('R14-2: the incoming picture settles monotonically, one picture per frame, and the audit accepts the series (last frame within the settle tolerance)', () => {
  for (const frames of [CATALOG.presets.cut_push.frames.min, 12, CATALOG.presets.cut_push.frames.max]) {
    const s = descriptorSeries('cut_push', params, frames, 0);
    s.forEach((d, i) => {
      assert.equal(d.out.visible, false, `f${i}: a cut_push shows exactly one picture`);
      if (i > 0) assert.ok(d.in.scale <= s[i - 1].in.scale, `f${i}: scale grew`);
    });
    assert.deepEqual(auditPreset('cut_push', params, frames, 0), [], `frames ${frames}`);
  }
});

test('R14-3: the audit still BITES for cut_push: a last frame that is still visibly zoomed is refused', () => {
  const s = descriptorSeries('cut_push', params, 12, 0);
  const broken = structuredClone(s);
  broken[11].in.scale = 1.01;
  assert.ok(auditSeries(broken, {showsBoth: false, settle: true}).some((v) => /incoming .* last frame/.test(v)));
  assert.ok(coverage(s[11].in) === 1);
  assert.equal(descriptor('cut_push', params, 12, 0, 12), null, 'outside the window there is no descriptor: the plain picture');
});
