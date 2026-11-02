// What picture a dialogue shot shows on a given local frame. ONE pure function, used by the compositor (transitions.jsx)
// AND by the per-frame audit (validate.mjs), so the audit checks exactly what the renderer draws.
// Pure ESM, no React.
import {PRESETS, READY_PRESETS, easeInOut, easeOut, presetName, presetOf, rendersAs, resolveParams, scheduleOf, tailFrameCount} from './presets.mjs';
import {DESCRIPTOR_KINDS, descriptor, outAbove} from './catalog-render.mjs';

// transitions attach to a shot by shot id OR by the id of its first (incoming) / last (outgoing) segment
export function edgeIds(shot) {
  const segs = shot.segments;
  return {first: segs[0].id, last: segs[segs.length - 1].id};
}

export function transitionIndex(config) {
  const byTo = new Map();
  const byFrom = new Map();
  for (const t of config.transitions) {
    byTo.set(t.to, t);
    byFrom.set(t.from, t);
  }
  const incoming = (shot) => byTo.get(edgeIds(shot).first) || byTo.get(shot.id);
  const outgoing = (shot) => byFrom.get(shot.id) || byFrom.get(edgeIds(shot).last);
  return {incoming, outgoing};
}

export const dipEntry = (t, rel) => scheduleOf(t).find((e) => e.t === rel);
// number of local frames of the incoming shot that a dip schedule can touch (t = 0 .. max)
export const dipSpan = (t) => Math.max(...scheduleOf(t).map((e) => e.t)) + 1;
// Canonical transition types = the READY presets of the catalog (schemas/transition-presets.json, via catalog.generated.mjs): the same
// table as the engine (engine/editorial/presets.py). showsBoth = one frame can show the outgoing AND the incoming side; with a PICTURE
// SHOT on either side that needs continuity 'agree' (between two graphics, e.g. cards, it is allowed). tailOnly = starts on the boundary
// and plays the outgoing clip's native tail; tailFrames = how many output frames come from that tail (none | all | half | schedule).
// rendersAs = the renderer branch (aliases share one: crossfade/dissolve, wipe_linear/wipe, pan_motivated/whip, the dip family).
// drawn = the kit renders it from the shot layer (none / cut / card_slide / plate_in are informational: cards and the plate drive their
// own timing and a hard cut draws nothing).
const INFORMATIONAL = new Set(['none', 'cut', 'card_slide', 'plate_in']);
export const TYPE_TABLE = Object.fromEntries(READY_PRESETS.map((name) => {
  const p = PRESETS[name];
  return [name, {showsBoth: p.shows_both, tailOnly: p.tail_only, tailFrames: p.tail_frames, rendersAs: p.renders_as, drawn: !INFORMATIONAL.has(p.renders_as)}];
}));
export const TRANSITION_TYPES = Object.keys(TYPE_TABLE);
// picture-layer types that mount two shot pictures (the ones pictureMode can draw); they always have a picture shot on a side
export const NEEDS_CONTINUITY = TRANSITION_TYPES.filter((k) => TYPE_TABLE[k].showsBoth && TYPE_TABLE[k].drawn);

// the written params of a row with the catalog defaults filled in
export const paramsOf = (t) => resolveParams(presetOf(t), t.params);

export function pictureMode({shot, frame, inT, outT, ending, motion}) {
  const D = shot.frames;
  const outKind = outT && rendersAs(outT);
  const inKind = inT && rendersAs(inT);
  if (outKind === 'dip_white') {
    const e = dipEntry(outT, frame - D); // t = -1 for the last editorial frame
    if (e && e.shot === 'out') return {kind: 'dip', white: e.white, t: outT};
  }
  if (inKind === 'dip_white' && frame < dipSpan(inT)) {
    const e = dipEntry(inT, frame);
    if (!e || e.shot !== 'in') return {kind: 'hidden'}; // incoming hidden while the outgoing tail / white peak is on screen
    return {kind: 'dip', white: e.white, t: inT};
  }
  if (outKind === 'whip' && frame >= D - outT.outFrames) {
    const k = frame - (D - outT.outFrames);
    const W = motion.whip;
    return {kind: 'whip', offset: -outT.direction * W.outOffset[k], blur: W.outBlur[k], zoomK: W.outZoom[k], frame};
  }
  if (inKind === 'whip' && frame < inT.inFrames) {
    const W = motion.whip;
    return {kind: 'whip', offset: inT.direction * W.inOffset[frame], blur: W.inBlur[frame], zoomK: W.inZoom[frame], frame};
  }
  if (inKind === 'dissolve' && frame < inT.frames) {
    requireContinuity(inT);
    const curve = inT.curve !== undefined ? inT.curve : (inT.params || {}).curve;
    return {kind: 'dissolve', opacity: (curve === 'out' ? easeOut : easeInOut)(frame / inT.frames)};
  }
  if ((inKind === 'cloud' || inKind === 'bubble' || inKind === 'wipe') && frame < inT.frames) {
    requireContinuity(inT);
    const prm = paramsOf(inT);
    const centre = inT.centre || (inKind === 'bubble' ? [prm.centre_x * 1920, prm.centre_y * 1080] : undefined);
    const seed = Number.isInteger(inT.seed) ? inT.seed : inT.boundary;
    const spec = {kind: inKind === 'bubble' ? 'bubble' : 'cloud', straight: inKind === 'wipe', seed, dir: inT.direction, centre};
    return {kind: 'mask', spec, u: frame / (inT.frames - 1)};
  }
  if (inKind && DESCRIPTOR_KINDS.includes(inKind) && frame < inT.frames) {
    if (TYPE_TABLE[presetName(inT)].showsBoth) requireContinuity(inT);
    const d = descriptor(presetName(inT), paramsOf(inT), inT.frames, inT.direction, frame);
    // a card flip shows the outgoing face first (its tail layer); the incoming face only exists from the half-way switch on
    if (!d.in.visible) return {kind: 'hidden'};
    return {kind: 'desc', d: d.in, out: d.out, perspectivePx: d.perspectivePx, outAbove: outAbove(inKind), t: frame, transition: inT};
  }
  if (outKind === 'iris') {
    const g = shot.start + frame; // global frame
    if (g >= ending.discIn + 3) return {kind: 'backdrop'}; // the logo disc is opaque from here; the iris must not peek out behind it
    if (g >= ending.irisStart) {
      const u = easeInOut((g - ending.irisStart) / (ending.irisClosed - ending.irisStart));
      return {kind: 'iris', u};
    }
  }
  return {kind: 'plain'};
}

export function requireContinuity(t) {
  if (t.continuity !== 'agree') {
    throw new Error(
      `transition ${t.id} (${t.type}) shows both shots in one frame; it needs continuity:'agree' ` +
      "(placements proven identical, e.g. by comfyui-blender scene_layout continuity). Use whip / dip / bloom / cut instead.",
    );
  }
}

// The ONE definition of where a transition's outgoing native tail plays: {from, frames} in global frames, or null when it
// plays none. Used by TailLayers (compositor), the per-frame audit and staging (render.cjs hands this function to stage.cjs).
// Frames come from the catalog's tail_frames rule: none | all (the whole window) | half (ceil(frames/2)) | schedule (the out_tail
// rows). A schedule's out_tail rows are t = 0..n-1 (validated contiguous), so its window is boundary .. boundary+n-1.
export function tailWindow(t) {
  if (!t.tail) return null;
  const preset = presetOf(t);
  if (!preset) return null;
  const n = tailFrameCount(preset, t.frames, scheduleOf(t));
  if (n <= 0) return null;
  return {from: preset.tail_frames === 'schedule' ? t.boundary : t.start, frames: n};
}

// transitions whose outgoing native tail plays under the incoming shot / white layer
export function tailLayers(config) {
  const out = [];
  for (const t of config.transitions) {
    const w = tailWindow(t);
    if (w) out.push({t, from: w.from, frames: w.frames});
  }
  return out;
}

// Is the outgoing tail picture ON SCREEN on global frame f of its window? (the compositor draws it only then; a descriptor can take
// it off screen before the window ends, e.g. a push that has carried it out of the canvas)
export function tailVisibleAt(t, f) {
  const kind = rendersAs(t);
  if (!DESCRIPTOR_KINDS.includes(kind)) return true;
  const d = descriptor(presetName(t), paramsOf(t), t.frames, t.direction, f - t.start);
  return d !== null && d.out.visible;
}

// Per-frame audit of picture layers over the whole film. A frame that mounts more than one SHOT picture (a dialogue slot that is
// visible + an outgoing tail that is on screen) is only legal when every tail active on it belongs to a both-sides preset (shows_both)
// with continuity 'agree'; a one-shot preset (dip family, card flip, cut push) may never overlap. Returns violations (empty = pass).
export function auditPictureLayers(config, motion) {
  const idx = transitionIndex(config);
  const tails = tailLayers(config);
  const total = config.timeline.mainFrames + config.timeline.endCardFrames;
  const violations = [];
  const dips = config.transitions.filter((t) => rendersAs(t) === 'dip_white');
  for (let f = 0; f < total; f += 1) {
    let slotVisible = 0;
    const slot = config.shots.find((s) => f >= s.start && f < s.start + s.frames);
    let mode = null;
    if (slot) {
      mode = pictureMode({shot: slot, frame: f - slot.start, inT: idx.incoming(slot), outT: idx.outgoing(slot), ending: config.ending, motion});
      slotVisible = mode.kind === 'hidden' ? 0 : 1;
    }
    const activeTails = tails.filter((l) => f >= l.from && f < l.from + l.frames && tailVisibleAt(l.t, f));
    const layers = slotVisible + activeTails.length;
    if (layers <= 1) continue;
    const bad = activeTails.filter((l) => l.t.continuity !== 'agree' || !(presetOf(l.t) || {}).shows_both);
    if (bad.length || activeTails.length > 1) {
      violations.push({frame: f, layers, transitions: activeTails.map((l) => l.t.id), slot: slot ? slot.id : null});
    }
  }
  // dip family: the schedule itself may never list two shots (or the same t twice) for one frame
  for (const t of dips) {
    const perT = new Map();
    for (const e of scheduleOf(t)) {
      const row = perT.get(e.t) || {out: 0, inc: 0, n: 0};
      row.out += e.shot === 'out' || e.shot === 'out_tail' ? 1 : 0;
      row.inc += e.shot === 'in' ? 1 : 0;
      row.n += 1;
      perT.set(e.t, row);
    }
    for (const [rel, row] of perT) {
      if (row.out + row.inc > 1 || row.n > 1) violations.push({frame: t.boundary + rel, layers: row.out + row.inc, transitions: [t.id], slot: 'dip-schedule'});
    }
  }
  return violations;
}

// Whip geometry: the moving layer is ONE full copy of the shot. The side exposed by the translation is filled by a strip made
// of the shot's own edge columns, flipped and stretched horizontally (smeared edge pixels, not a recognisable second picture);
// that strip lies entirely OUTSIDE the shot rect, so it can never overlap a second copy of the characters. WhipTiles in
// transitions.jsx takes its box from this function and asserts the strip stays outside the shot rect.
// Every (offset, zoomK) pair a whip transition draws, out frames then in frames (the schedule the renderer indexes).
export function whipSteps(t, motion) {
  const W = motion.whip;
  const steps = [];
  for (let k = 0; k < t.outFrames; k += 1) steps.push({phase: 'out', k, offset: -t.direction * W.outOffset[k], zoomK: W.outZoom[k]});
  for (let k = 0; k < t.inFrames; k += 1) steps.push({phase: 'in', k, offset: t.direction * W.inOffset[k], zoomK: W.inZoom[k]});
  return steps;
}

// Does the extender strip really cover the side the translation exposes? Everything is in the moved layer's coordinates:
// the layer is scaled by z about the canvas centre then translated by `offset`, so the shot's right edge lands at
// R = c + z*(W - c) + offset and the right strip (container x = W .. W+extenderWidth) at R .. R + z*extenderWidth; the left
// side mirrors. covered = the strip reaches the canvas border; gapPx = how many pixels stay uncovered.
export function whipCoverage(offset, zoomK, motion, canvasWidth = 1920) {
  const z = 1 + (motion.whip.zoom - 1) * zoomK;
  const c = canvasWidth / 2;
  const strip = z * motion.whip.extenderWidth;
  if (offset < 0) {
    const edge = c + z * (canvasWidth - c) + offset; // shot right edge on the canvas
    const gapPx = Math.max(0, canvasWidth - (edge + strip));
    return {side: 'right', edge, gapPx, covered: gapPx <= 0};
  }
  const edge = c + z * (0 - c) + offset; // shot left edge on the canvas
  const gapPx = Math.max(0, edge - strip);
  return {side: 'left', edge, gapPx, covered: gapPx <= 0};
}

export function whipGeometry(offset, motion, canvasWidth = 1920) {
  const W = motion.whip.extenderWidth;
  const right = offset < 0; // picture moved left -> the right side is exposed
  const left = right ? canvasWidth : -W;
  const strip = {left, width: W};
  const shotRect = {left: 0, width: canvasWidth};
  const outside = strip.left + strip.width <= shotRect.left || strip.left >= shotRect.left + shotRect.width;
  return {right, strip, shotRect, outside};
}
