// Catalog-driven transition renderers in the FIXED-TIMELINE OVERLAY model (never a TransitionSeries: the master clock does not move).
// Everything here is a PURE per-frame descriptor, no React, no clock, no random source (only seeded()):
//
//   descriptor(type, params, frames, direction, t) -> {out, in, overlay, perspectivePx?}
//     t = 0 .. frames-1, counted from the first frame of the window (from_boundary presets: t = global frame - boundary)
//     out = the OUTGOING picture (the shot's native tail layer), in = the INCOMING shot picture; each
//       {visible, opacity, tx, ty, scale, rotX, rotY, blurPx, brightness, clip}   tx / ty in px of the 1920x1080 design canvas, rot in
//       degrees, clip = null | {kind:'circle',cx,cy,r,soft} | {kind:'diamond',cx,cy,d,soft} | {kind:'polygon',points} | {kind:'rects',rects}
//     overlay = null (the dip family has its own dipDescriptor)
//
// Progress is u = t / (frames - 1): the OUTGOING picture is whole on the first frame, the INCOMING one is whole on the last frame
// (that frame equals the plain shot frame, so nothing pops when the window ends). auditSeries() proves that, and the one-shot / both-
// sides property, for any series; picture-mode.mjs runs it on the very descriptors the compositor draws.
import {PRESETS, resolveParams, seeded, easeInOut, easeOut} from './presets.mjs';

export const W = 1920;
export const H = 1080;
export const DESCRIPTOR_KINDS = ['cut_push', 'push_slide', 'zoom_through', 'zoom_out', 'iris_circle', 'iris_diamond', 'clock_wipe', 'blinds', 'blur_crossfade', 'focus_pull', 'card_flip_3d'];

const n0 = (v) => v + 0; // -0 -> 0
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const layer = (o = {}) => {
  const base = {visible: true, opacity: 1, tx: 0, ty: 0, scale: 1, rotX: 0, rotY: 0, blurPx: 0, brightness: 1, clip: null, ...o};
  for (const k of ['opacity', 'tx', 'ty', 'scale', 'rotX', 'rotY', 'blurPx', 'brightness']) base[k] = n0(base[k]);
  return base;
};
const GONE = () => layer({visible: false, opacity: 0});
const ease = (name, u) => (name === 'out' ? easeOut(u) : easeInOut(u));

export const kindOf = (type) => (PRESETS[type] ? PRESETS[type].renders_as : type);
// the outgoing tail is drawn ABOVE the incoming picture (it shrinks onto it); every other kind draws it below
export const outAbove = (type) => kindOf(type) === 'zoom_out';

// ---- geometry ----------------------------------------------------------------------------------------------------------------
const corners = [[0, 0], [W, 0], [W, H], [0, H]];
const maxCorner = (cx, cy, metric) => Math.max(...corners.map(([x, y]) => metric(x - cx, y - cy)));

// swept sector of a clock hand: from `startDeg` (0 = 12 o'clock) by `sweepDeg`, clockwise or not, hand at the canvas centre.
// polygon = centre, the boundary point of the start ray, every canvas corner the sweep passes, the boundary point of the end ray
// (at most 7 points), clipped to the canvas, so its area is the exact swept area.
export function clipPolygon(sweepDeg, startDeg = 0, clockwise = true) {
  const s = Math.max(0, Math.min(360, sweepDeg));
  if (s >= 360) return {kind: 'polygon', points: corners.map((p) => [...p])};
  const sign = clockwise ? 1 : -1;
  const [cx, cy] = [W / 2, H / 2];
  const rad = (deg) => (deg * Math.PI) / 180;
  const hit = (deg) => {
    const dx = Math.sin(rad(deg));
    const dy = -Math.cos(rad(deg));
    const k = Math.min(Math.abs(dx) > 1e-12 ? cx / Math.abs(dx) : Infinity, Math.abs(dy) > 1e-12 ? cy / Math.abs(dy) : Infinity);
    return [cx + k * dx, cy + k * dy];
  };
  const mod = (v) => ((v % 360) + 360) % 360;
  const passed = corners
    .map(([x, y]) => ({p: [x, y], rel: mod(sign * (Math.atan2(x - cx, -(y - cy)) * 180 / Math.PI - startDeg))}))
    .filter((c) => c.rel > 1e-9 && c.rel < s - 1e-9)
    .sort((a, b) => a.rel - b.rel);
  return {kind: 'polygon', points: [[cx, cy], hit(startDeg), ...passed.map((c) => c.p), hit(startDeg + sign * s)]};
}

const inPolygon = (x, y, pts) => {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
};
const inClip = (clip, x, y) => {
  if (clip === null) return true;
  if (clip.kind === 'circle') return (x - clip.cx) ** 2 + (y - clip.cy) ** 2 <= clip.r ** 2;
  if (clip.kind === 'diamond') return Math.abs(x - clip.cx) + Math.abs(y - clip.cy) <= clip.d;
  if (clip.kind === 'polygon') return inPolygon(x, y, clip.points);
  return clip.rects.some((r) => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
};

const GRID_X = 96;
const GRID_Y = 54;
// fraction of the canvas a layer covers (opacity-weighted): its transformed rectangle (scale, translate, the foreshortening of a flip)
// intersected with its clip, sampled on a fixed 96 x 54 grid, so deterministic. 0 for a hidden layer.
export function coverage(l) {
  if (!l.visible || !(l.opacity > 0)) return 0;
  const sc = l.scale === undefined ? 1 : l.scale;
  const fx = Math.abs(Math.cos(((l.rotY || 0) * Math.PI) / 180));
  const fy = Math.abs(Math.cos(((l.rotX || 0) * Math.PI) / 180));
  if (sc <= 0 || fx < 1e-9 || fy < 1e-9) return 0;
  let inside = 0;
  for (let j = 0; j < GRID_Y; j += 1) {
    const y = ((j + 0.5) * H) / GRID_Y;
    for (let i = 0; i < GRID_X; i += 1) {
      const x = ((i + 0.5) * W) / GRID_X;
      const lx = (x - W / 2 - (l.tx || 0)) / sc;
      const ly = (y - H / 2 - (l.ty || 0)) / sc;
      if (Math.abs(lx) <= (W / 2) * fx && Math.abs(ly) <= (H / 2) * fy && inClip(l.clip === undefined ? null : l.clip, lx / fx + W / 2, ly / fy + H / 2)) inside += 1;
    }
  }
  return (inside / (GRID_X * GRID_Y)) * l.opacity;
}

export const isWhole = (l) => l.visible && l.opacity === 1 && l.tx === 0 && l.ty === 0 && l.scale === 1 && l.rotX === 0 && l.rotY === 0
  && l.blurPx === 0 && l.brightness === 1 && l.clip === null;

// ---- the descriptors -----------------------------------------------------------------------------------------------------------
function resolved(type, params) {
  const preset = PRESETS[type] || Object.values(PRESETS).find((p) => p.renders_as === type);
  if (!preset) throw new Error(`descriptor: unknown transition ${type}`);
  return {preset, p: resolveParams(preset, params)};
}

export function descriptor(type, params, frames, direction, t) {
  if (!(Number.isInteger(frames) && frames >= 2)) throw new Error(`descriptor: ${type} needs at least 2 frames, got ${frames}`);
  if (!Number.isInteger(t) || t < 0 || t >= frames) return null;
  const {preset, p} = resolved(type, params);
  const kind = preset.renders_as;
  if (!DESCRIPTOR_KINDS.includes(kind)) throw new Error(`descriptor: ${preset.name || type} (renders_as ${kind}) has no descriptor renderer`);
  const last = t === frames - 1;
  // cut_push (the approved v013 push) divides by the window length: it reaches exactly 1.00 on the first frame AFTER the window,
  // which is the plain incoming picture; every other preset runs 0..1 over its window (last window frame = the finished state)
  const u = kind === 'cut_push' ? t / frames : t / (frames - 1);
  const out = {out: layer(), in: GONE(), overlay: null};
  switch (kind) {
    case 'cut_push': {
      const e = ease(p.ease, u);
      out.out = GONE();
      out.in = layer({scale: 1 + (p.scale_from - 1) * (1 - e)});
      break;
    }
    case 'push_slide': {
      const size = p.axis === 'y' ? H : W;
      const e = ease(p.ease, u);
      const dir = direction === -1 ? -1 : 1;
      const shift = (v) => (p.axis === 'y' ? {ty: v} : {tx: v});
      out.out = layer({...shift(-dir * size * e), visible: e < 1});
      out.in = layer({...shift(dir * size * (1 - e)), visible: e > 0});
      break;
    }
    case 'zoom_through': {
      const e = easeInOut(u);
      out.out = layer({scale: 1 + (p.scale_out - 1) * e, opacity: 1 - e, blurPx: p.blur_px * e, visible: e < 1});
      out.in = layer({scale: 1 - (1 - p.scale_in_from) * (1 - e), opacity: e, blurPx: p.blur_px * (1 - e), visible: e > 0});
      break;
    }
    case 'zoom_out': {
      const e = easeInOut(u);
      const fade = u < 0.75 ? 1 : 1 - (u - 0.75) / 0.25;
      out.out = layer({scale: 1 - (1 - p.scale_to) * e, opacity: clamp01(fade), visible: fade > 0});
      out.in = layer({scale: 1 + 0.06 * (1 - e)});
      break;
    }
    case 'iris_circle':
    case 'iris_diamond': {
      const e = easeInOut(u);
      const [cx, cy] = [p.centre_x * W, p.centre_y * H];
      const circle = kind === 'iris_circle';
      const full = maxCorner(cx, cy, circle ? Math.hypot : (dx, dy) => Math.abs(dx) + Math.abs(dy)) + p.softness_px;
      const size = full * e;
      const clip = circle ? {kind: 'circle', cx, cy, r: size, soft: p.softness_px} : {kind: 'diamond', cx, cy, d: size, soft: p.softness_px};
      out.in = layer({clip, visible: size > 0});
      break;
    }
    case 'clock_wipe': {
      const e = easeInOut(u);
      out.in = layer({clip: clipPolygon(360 * e, p.start_angle_deg, p.clockwise), visible: e > 0});
      break;
    }
    case 'blinds': {
      const e = easeInOut(u);
      const rects = Array.from({length: p.count}, (_, i) => (p.axis === 'v'
        ? {x: (i * W) / p.count, y: 0, w: (e * W) / p.count, h: H}
        : {x: 0, y: (i * H) / p.count, w: W, h: (e * H) / p.count}));
      out.in = layer({clip: {kind: 'rects', rects}, visible: e > 0});
      break;
    }
    case 'blur_crossfade': {
      const e = easeInOut(u);
      out.out = layer({blurPx: p.blur_px * e, visible: e < 1});
      out.in = layer({opacity: e, blurPx: p.blur_px * (1 - e), visible: e > 0});
      break;
    }
    case 'focus_pull': {
      const e = easeInOut(u);
      const fade = clamp01((e - 0.3) / 0.7);
      out.out = layer({blurPx: p.blur_px * e, scale: 1 + 0.05 * e, visible: e < 1});
      out.in = layer({opacity: fade, visible: fade > 0});
      break;
    }
    default: { // card_flip_3d: ONE face per frame, the faces switch where the half-length tail stops
      const half = Math.ceil(frames / 2);
      const key = p.axis === 'x' ? 'rotX' : 'rotY';
      if (t < half) out.out = layer({[key]: 90 * (t / half) ** 2});
      else {
        out.out = GONE();
        out.in = layer({[key]: -90 * (1 - (t - half + 1) / (frames - half)) ** 2});
      }
      out.perspectivePx = p.perspective_px;
    }
  }
  if (last && kind !== 'cut_push') {
    out.out = GONE();
    out.in = layer();
  } else if (t === 0 && kind !== 'cut_push') out.out = layer();
  return out;
}

export function descriptorSeries(type, params, frames, direction) {
  return Array.from({length: frames}, (_, t) => descriptor(type, params, frames, direction, t));
}

// Audit of one descriptor series. showsBoth=false (a one-shot preset): no frame may show both pictures. showsBoth=true: at least one
// frame does. Always: the outgoing picture is whole on the first frame (when there is one), the incoming picture is whole on the last
// frame and the outgoing one is gone there; the incoming coverage never falls and the outgoing never grows. Returns violations.
// settle: the incoming picture may stop one eased step short of whole on the last frame (cut_push: the plain picture starts on the frame
// after the window), as long as that last jump to 1.00 is no bigger than the previous in-window step (no visible pop).
export function auditSeries(series, {showsBoth, settle = false}) {
  const bad = [];
  let bothFrames = 0;
  let prevIn = -1;
  let prevOut = 2;
  series.forEach((d, i) => {
    const cin = coverage(d.in);
    const cout = coverage(d.out);
    if (d.out.visible && d.in.visible && cin > 0 && cout > 0) {
      bothFrames += 1;
      if (!showsBoth) bad.push(`f${i}: both pictures visible (a one-shot preset shows one picture per frame)`);
    }
    if (cin < prevIn - 1e-9) bad.push(`f${i}: incoming coverage falls (${prevIn.toFixed(3)} -> ${cin.toFixed(3)})`);
    if (cout > prevOut + 1e-9) bad.push(`f${i}: outgoing coverage grows (${prevOut.toFixed(3)} -> ${cout.toFixed(3)})`);
    prevIn = cin;
    prevOut = cout;
  });
  if (showsBoth && bothFrames === 0) bad.push('no frame shows both pictures (the preset claims shows_both)');
  const first = series[0];
  const last = series[series.length - 1];
  if ((showsBoth || first.out.visible) && !isWhole(first.out)) bad.push('the outgoing picture is not whole on the first frame');
  const prev = series.length > 1 ? series[series.length - 2].in.scale : Infinity;
  const settled = settle && last.in.visible && last.in.opacity === 1 && last.in.tx === 0 && last.in.ty === 0 && last.in.rotX === 0 && last.in.rotY === 0
    && last.in.blurPx === 0 && last.in.brightness === 1 && last.in.clip === null && last.in.scale >= 1 && last.in.scale - 1 <= prev - last.in.scale + 1e-12;
  if (!isWhole(last.in) && !settled) bad.push('the incoming picture is not whole on the last frame');
  if (last.out.visible) bad.push('the outgoing picture is still on screen on the last frame');
  return bad;
}

export function auditPreset(type, params, frames, direction) {
  const {preset} = resolved(type, params);
  return auditSeries(descriptorSeries(type, params, frames, direction), {showsBoth: preset.shows_both, settle: preset.renders_as === 'cut_push'});
}

// ---- dip family overlays -------------------------------------------------------------------------------------------------------
const WHITE = '#FFF8EC';
const luminance = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).reduce((s, v, k) => s + v * [0.299, 0.587, 0.114][k], 0);
const LEAK = {base: '#FFE9B8', tints: ['#FFB347', '#FF7A3D', '#FFF3C4']};
const BURN = {base: '#FFC37A', tints: ['#FF5A1F', '#E8350E', '#FFD27F']};

// What one frame of a dip schedule looks like, from its `white` weight: the picture exposure / blur, and the overlay drawn over it.
// kind colour: a flat colour (white keeps the config-overridable motion.dip.colour; a dark colour dims the picture instead of
// brightening it); kind leak / burn: seeded radial blobs (screen blend) that grow with the weight over a base that is OPAQUE at the
// pure frame, so the peak frame shows no shot. seed = the boundary frame (same inputs, same pixels).
export function dipDescriptor(overlay, white, motion, seed) {
  const d = motion.dip;
  if (overlay.kind === 'colour') {
    const colour = overlay.colour === WHITE ? d.colour : overlay.colour;
    const dark = luminance(colour) < 80;
    return {brightness: dark ? 1 - 0.6 * white : 1 + d.brightness * white, blurPx: white * d.blur, overlay: {kind: 'colour', colour, opacity: white}};
  }
  const look = overlay.kind === 'burn' ? BURN : LEAK;
  const rnd = seeded(seed);
  const blobs = look.tints.map((colour) => ({x: 200 + rnd() * 1500, y: 150 + rnd() * 700, r: (300 + rnd() * 300) * (0.5 + white), colour}));
  return {
    brightness: 1 + 0.5 * white,
    blurPx: white * d.blur * 0.5,
    overlay: {kind: overlay.kind, opacity: white, base: look.base, baseOpacity: white ** 2, blobs, blend: 'screen'},
  };
}
