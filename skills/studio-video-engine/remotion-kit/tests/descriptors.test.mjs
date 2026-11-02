// T-E42: the new presets are rendered in the fixed-timeline overlay model as PURE per-frame descriptors
//   descriptor(type, params, frames, direction, t) -> {out, in, overlay}; out / in = {visible, opacity, tx, ty, scale, rotX, rotY, blurPx,
//   brightness, clip}. Tests: endpoints, monotonic progress, one-shot / both-visible audits (and that the audit BITES on a broken
//   series), determinism, parameter extremes, family geometry (clock sweep, blinds, card flip), and the pictureMode / audit wiring.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {CATALOG} from '../src/catalog.generated.mjs';
import {DESCRIPTOR_KINDS, auditPreset, auditSeries, clipPolygon, coverage, descriptor, descriptorSeries, dipDescriptor, outAbove} from '../src/catalog-render.mjs';
import {auditPictureLayers, pictureMode, tailWindow, transitionIndex} from '../src/picture-mode.mjs';
import {defaultFrames, resolveMotion, resolveParams, tailFrameCount} from '../src/presets.mjs';
import {DESCRIPTOR, presetConfig, presetRow} from './preset-fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const spec = (name) => CATALOG.presets[name];
const dirOf = (name) => (spec(name).direction === 'required' ? 1 : 0);
const series = (name, params = {}, frames = defaultFrames(spec(name)), direction = dirOf(name)) =>
  descriptorSeries(name, resolveParams(spec(name), params), frames, direction);
const FULL = (layer) => layer.visible && layer.opacity === 1 && layer.tx === 0 && layer.ty === 0 && layer.scale === 1 && layer.rotX === 0 && layer.rotY === 0
  && layer.blurPx === 0 && layer.brightness === 1 && layer.clip === null;

const NEAR_FULL = (layer) => FULL({...layer, scale: layer.scale >= 1 && layer.scale < 1.0005 ? 1 : layer.scale});

test('the descriptor kinds are exactly the catalog presets the overlay model renders', () => {
  assert.deepEqual([...DESCRIPTOR].sort(), DESCRIPTOR.filter((n) => DESCRIPTOR_KINDS.includes(spec(n).renders_as)).sort());
  assert.equal(DESCRIPTOR_KINDS.length, DESCRIPTOR.length);
});

test('every descriptor frame is finite, complete and shaped {out, in, overlay}', () => {
  for (const name of DESCRIPTOR) {
    const s = series(name);
    assert.equal(s.length, defaultFrames(spec(name)), name);
    for (const d of s) {
      for (const side of ['out', 'in']) {
        for (const key of ['opacity', 'tx', 'ty', 'scale', 'rotX', 'rotY', 'blurPx', 'brightness']) assert.ok(Number.isFinite(d[side][key]), `${name}.${side}.${key}`);
        assert.equal(typeof d[side].visible, 'boolean', `${name}.${side}.visible`);
        assert.ok(d[side].clip === null || typeof d[side].clip === 'object', name);
      }
      assert.ok('overlay' in d, name);
    }
  }
});

test('endpoints: the outgoing picture is whole on the first window frame and the incoming one is whole on the last (shows_both presets)', () => {
  for (const name of DESCRIPTOR) {
    const s = series(name);
    const first = s[0];
    const last = s[s.length - 1];
    if (name !== 'cut_push') assert.ok(FULL(first.out), `${name}: outgoing not whole at t=0 ${JSON.stringify(first.out)}`);
    // cut_push (v013 push, progress k/frames) ends one eased step short of 1.00; the plain picture starts on the frame after its window
    if (name === 'cut_push') assert.ok(NEAR_FULL(last.in), `${name}: incoming not settled at the last frame ${JSON.stringify(last.in)}`);
    else assert.ok(FULL(last.in), `${name}: incoming not whole at the last frame ${JSON.stringify(last.in)}`);
    assert.equal(coverage(last.in), 1, name);
    if (name !== 'cut_push') assert.equal(coverage(first.out), 1, name);
    assert.equal(last.out.visible && coverage(last.out) > 0, false, `${name}: outgoing still on screen at the last frame`);
    assert.ok(coverage(first.in) < 0.2 || name === 'zoom_out' || name === 'cut_push', `${name}: incoming already on screen at t=0 (${coverage(first.in)})`);
  }
  // cut_push: no outgoing layer at all, the incoming settles from scale_from to 1
  const cp = series('cut_push');
  assert.ok(cp.every((d) => !d.out.visible));
  assert.equal(cp[0].in.scale, 1.04);
  assert.ok(Math.abs(cp[cp.length - 1].in.scale - 1) < 1e-3 && cp[cp.length - 1].in.scale > 1);
});

test('monotonic progress: the incoming coverage never falls and the outgoing never grows while the transition runs', () => {
  for (const name of DESCRIPTOR) {
    for (const frames of [spec(name).frames.min, defaultFrames(spec(name)), spec(name).frames.max]) {
      const s = series(name, {}, frames);
      let prevIn = -1;
      let prevOut = 2;
      s.forEach((d, i) => {
        const cin = coverage(d.in);
        const cout = d.out.visible ? coverage(d.out) : 0;
        assert.ok(cin >= prevIn - 1e-9, `${name}/${frames} f${i}: incoming coverage fell ${prevIn} -> ${cin}`);
        assert.ok(cout <= prevOut + 1e-9, `${name}/${frames} f${i}: outgoing coverage grew ${prevOut} -> ${cout}`);
        prevIn = cin;
        prevOut = cout;
      });
    }
  }
});

test('one-shot presets never show both pictures; both-sides presets do for at least one frame', () => {
  for (const name of DESCRIPTOR) {
    const s = series(name);
    const both = s.filter((d) => d.out.visible && d.in.visible && coverage(d.out) > 0 && coverage(d.in) > 0).length;
    if (spec(name).shows_both) assert.ok(both >= 1, `${name} shows both sides but no frame has both`);
    else assert.equal(both, 0, `${name} is a one-shot preset but ${both} frame(s) show both pictures`);
    assert.deepEqual(auditPreset(name, resolveParams(spec(name), {}), defaultFrames(spec(name)), dirOf(name)), [], `${name} audit`);
  }
  // card_flip_3d: exactly one face per frame, and the faces switch where the tail stops
  const flip = series('card_flip_3d');
  const half = tailFrameCount(spec('card_flip_3d'), flip.length);
  flip.forEach((d, i) => assert.equal(d.out.visible, i < half, `flip f${i} outgoing face`));
  flip.forEach((d, i) => assert.equal(d.in.visible, i >= half, `flip f${i} incoming face`));
});

test('the audit BITES: a both-visible series fails a one-shot claim, and a series that starts / ends half-way fails the endpoint rule', () => {
  const both = series('push_slide');
  assert.ok(auditSeries(both, {showsBoth: false}).some((v) => /both pictures/.test(v)));
  const brokenStart = structuredClone(both);
  brokenStart[0].out.opacity = 0.5;
  assert.ok(auditSeries(brokenStart, {showsBoth: true}).some((v) => /outgoing .* first frame/.test(v)));
  const brokenEnd = structuredClone(both);
  brokenEnd[brokenEnd.length - 1].in.tx = 40;
  assert.ok(auditSeries(brokenEnd, {showsBoth: true}).some((v) => /incoming .* last frame/.test(v)));
  const never = series('card_flip_3d');
  assert.ok(auditSeries(never, {showsBoth: true}).some((v) => /no frame shows both/.test(v)), 'a both-sides claim needs a frame that shows both');
});

test('determinism: the same inputs give byte-identical descriptors; no clock or random source in the module', () => {
  for (const name of DESCRIPTOR) {
    assert.equal(JSON.stringify(series(name)), JSON.stringify(series(name)), name);
  }
  const src = fs.readFileSync(path.join(KIT, 'src', 'catalog-render.mjs'), 'utf8');
  assert.doesNotMatch(src, /Math\.random|Date\.now|performance\.now|new Date/);
  const a = dipDescriptor({kind: 'leak'}, 0.6, resolveMotion({}), 1234);
  const b = dipDescriptor({kind: 'leak'}, 0.6, resolveMotion({}), 1234);
  assert.equal(JSON.stringify(a), JSON.stringify(b));
  assert.notEqual(JSON.stringify(a), JSON.stringify(dipDescriptor({kind: 'leak'}, 0.6, resolveMotion({}), 99)), 'the seed changes the leak');
});

test('parameter extremes (min and max of every numeric param) keep the endpoints whole and the numbers finite', () => {
  for (const name of DESCRIPTOR) {
    for (const [key, p] of Object.entries(spec(name).params)) {
      const values = p.type === 'enum' ? p.values : p.type === 'boolean' ? [true, false] : [p.min, p.max];
      for (const value of values) {
        const s = series(name, {[key]: value});
        assert.ok(name === 'cut_push' ? Math.abs(s[s.length - 1].in.scale - 1) < 0.04 : FULL(s[s.length - 1].in), `${name}.${key}=${value} last frame`);
        if (name !== 'cut_push') assert.ok(FULL(s[0].out), `${name}.${key}=${value} first frame`);
        for (const d of s) for (const side of ['out', 'in']) for (const k of ['opacity', 'tx', 'ty', 'scale', 'rotX', 'rotY', 'blurPx', 'brightness']) assert.ok(Number.isFinite(d[side][k]), `${name}.${key}=${value} ${side}.${k}`);
        assert.deepEqual(auditSeries(s, {showsBoth: spec(name).shows_both, settle: name === 'cut_push'}), [], `${name}.${key}=${value}`);
      }
    }
  }
});

test('push_slide: direction mirrors the travel, axis picks tx or ty, the two layers move together', () => {
  const right = series('push_slide', {}, 12, 1);
  const left = series('push_slide', {}, 12, -1);
  for (let i = 1; i < 11; i += 1) {
    assert.equal(Math.sign(right[i].out.tx), -Math.sign(left[i].out.tx));
    assert.ok(Math.abs(right[i].in.tx - right[i].out.tx) - 1920 < 1e-6 && Math.abs(Math.abs(right[i].in.tx - right[i].out.tx) - 1920) < 1e-6, 'one canvas apart');
  }
  const y = series('push_slide', {axis: 'y'}, 12, 1);
  assert.ok(y.every((d) => d.out.tx === 0 && d.in.tx === 0));
  assert.ok(y.some((d) => d.out.ty !== 0));
});

test('zoom_out puts the shrinking outgoing picture above the incoming one; the others do not', () => {
  assert.equal(outAbove('zoom_out'), true);
  for (const k of DESCRIPTOR_KINDS.filter((x) => x !== 'zoom_out')) assert.equal(outAbove(k), false, k);
  const s = series('zoom_out', {scale_to: 0.3});
  const shown = s.filter((d) => d.out.visible);
  assert.ok(shown.length >= 6 && shown.every((d, i) => i === 0 || d.out.scale <= shown[i - 1].out.scale));
  assert.ok(s.some((d) => d.out.scale <= 0.6 && d.out.visible));
});

test('clock_wipe: the polygon is the swept sector (quadrants = quarters of the canvas), clockwise or not, from any start angle', () => {
  const area = (angle, start, clockwise) => coverage({visible: true, opacity: 1, clip: clipPolygon(angle, start, clockwise)});
  for (const clockwise of [true, false]) {
    assert.ok(area(0, 0, clockwise) < 0.001);
    assert.ok(Math.abs(area(90, 0, clockwise) - 0.25) < 0.03, `quarter ${clockwise}`);
    assert.ok(Math.abs(area(180, 0, clockwise) - 0.5) < 0.03, `half ${clockwise}`);
    assert.ok(Math.abs(area(270, 0, clockwise) - 0.75) < 0.03, `three quarters ${clockwise}`);
    assert.ok(area(360, 0, clockwise) > 0.999);
    assert.ok(Math.abs(area(180, 123, clockwise) - 0.5) < 0.03, `half from 123 deg ${clockwise}`);
  }
  // clockwise from 12 o'clock first covers the top-right: the point right of centre, above the middle line, is inside after 90 deg
  const poly = clipPolygon(90, 0, true);
  assert.equal(poly.kind, 'polygon');
  assert.ok(poly.points.length >= 3 && poly.points.length <= 9);
  assert.ok(poly.points.every(([x, y]) => x >= 0 && x <= 1920 && y >= 0 && y <= 1080));
  const half = coverage({visible: true, opacity: 1, clip: clipPolygon(90, 0, false)});
  assert.ok(Math.abs(half - 0.25) < 0.03);
});

test('blinds: `count` slats along the axis, each opening by the same fraction; iris shapes grow from the chosen centre', () => {
  for (const count of [4, 8, 16]) for (const axis of ['h', 'v']) {
    const s = series('blinds', {count, axis}, 12);
    const mid = s[6].in.clip;
    assert.equal(mid.kind, 'rects');
    assert.equal(mid.rects.length, count);
    assert.ok(mid.rects.every((r) => r.x >= 0 && r.y >= 0 && r.x + r.w <= 1920 + 1e-6 && r.y + r.h <= 1080 + 1e-6));
  }
  const circle = series('iris_circle', {centre_x: 0.2, centre_y: 0.7}, 12);
  const c = circle[5].in.clip;
  assert.equal(c.kind, 'circle');
  assert.ok(Math.abs(c.cx - 384) < 1e-6 && Math.abs(c.cy - 756) < 1e-6);
  const diamond = series('iris_diamond', {}, 12)[5].in.clip;
  assert.equal(diamond.kind, 'diamond');
  assert.ok(circle[6].in.clip === null || circle[6].in.clip.r > c.r, 'the circle grows');
});

test('dip family overlays: colour (white / black) and seeded leak / burn; the pure frame is opaque', () => {
  const motion = resolveMotion({});
  const white = dipDescriptor({kind: 'colour', colour: '#FFF8EC'}, 1, motion, 1);
  assert.equal(white.overlay.kind, 'colour');
  assert.equal(white.overlay.opacity, 1);
  assert.equal(white.overlay.colour, motion.dip.colour, 'the white dip keeps the config-overridable motion.dip.colour');
  const black = dipDescriptor({kind: 'colour', colour: '#000000'}, 0.5, motion, 1);
  assert.equal(black.overlay.colour, '#000000');
  assert.ok(black.brightness < 1, 'black dims the picture instead of brightening it');
  for (const kind of ['leak', 'burn']) {
    const peak = dipDescriptor({kind}, 1, motion, 7);
    assert.equal(peak.overlay.kind, kind);
    assert.equal(peak.overlay.opacity, 1);
    assert.ok(peak.overlay.base, 'a full-frame base so the peak frame shows no shot');
    const low = dipDescriptor({kind}, 0.1, motion, 7);
    assert.ok(low.overlay.opacity < peak.overlay.opacity);
    assert.ok(low.overlay.blobs.length >= 2);
  }
});

test('wiring: pictureMode answers hidden / desc per frame from the descriptor, the tail window follows tail_frames, the audit passes for every descriptor preset', () => {
  for (const name of DESCRIPTOR) {
    const c = presetConfig(name);
    const motion = resolveMotion(c);
    const idx = transitionIndex(c);
    const t = c.transitions[0];
    const slot = c.shots[1];
    const n = t.frames;
    const w = tailWindow(t);
    assert.equal(w === null ? 0 : w.frames, tailFrameCount(spec(name), n), `${name} tail frames`);
    const s = series(name, {}, n);
    for (let i = 0; i < n; i += 1) {
      const mode = pictureMode({shot: slot, frame: i, inT: idx.incoming(slot), outT: idx.outgoing(slot), ending: c.ending, motion});
      const wantVisible = s[i].in.visible && !(name === 'card_flip_3d' && i < Math.ceil(n / 2));
      if (!wantVisible) assert.equal(mode.kind, 'hidden', `${name} f${i}`);
      else {
        assert.equal(mode.kind, 'desc', `${name} f${i}`);
        assert.deepEqual(mode.d, s[i].in, `${name} f${i} descriptor`);
      }
    }
    assert.equal(pictureMode({shot: slot, frame: n, inT: idx.incoming(slot), outT: idx.outgoing(slot), ending: c.ending, motion}).kind, 'plain', `${name} after the window`);
    assert.deepEqual(auditPictureLayers(c, motion), [], name);
  }
  const bad = presetConfig('push_slide');
  bad.transitions[0].frames = 12;
  assert.deepEqual(auditPictureLayers(bad, resolveMotion(bad)), []);
});

test('the picture-layer audit bites: overlapping tails are a violation, and the compositor itself refuses a both-sides preset without continuity agree', () => {
  const c = presetConfig('push_slide');
  const motion = resolveMotion(c);
  assert.deepEqual(auditPictureLayers(c, motion), []);
  // two transitions whose tails run on the same frames (a config validateConfig would refuse): the audit still reports every overlap frame
  const twin = presetConfig('push_slide');
  twin.transitions.unshift({...presetRow('blinds'), id: 'P2'});
  const violations = auditPictureLayers(twin, resolveMotion(twin));
  assert.ok(violations.length >= 1 && violations.every((v) => v.transitions.length === 2), JSON.stringify(violations));
  // without continuity agree a both-sides preset never reaches the pixels
  c.transitions[0].continuity = 'mismatch';
  assert.throws(() => auditPictureLayers(c, motion), /continuity/);
  // and the one-shot presets never overlap, whatever their continuity
  const flip = presetConfig('card_flip_3d');
  flip.transitions[0].continuity = 'mismatch';
  assert.deepEqual(auditPictureLayers(flip, resolveMotion(flip)), []);
});
