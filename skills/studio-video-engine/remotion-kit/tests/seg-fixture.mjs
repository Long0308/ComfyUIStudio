// A stand-in for the engine's segments.json (jjv/segments/v1) built from a kit config: the cut points are the starts and ends of every
// effect window, the card starts, the intro / outro / plate / main end and the join of the ending. Used by the P2 tests and ad-hoc
// runs until (and next to) the engine writes the real file.
import {createRequire} from 'node:module';
import {tailVisibleAt, tailWindow, transitionIndex, pictureMode} from '../src/picture-mode.mjs';
import {resolveMotion, rendersAs, scheduleOf} from '../src/presets.mjs';
import {totalFrames} from '../src/validate.mjs';

const require = createRequire(import.meta.url);
const segments = require('../lib/segments.cjs');
const dep = require('../lib/segdeps.cjs');

export function kitDeps(config) {
  return {pictureMode, transitionIndex, tailWindow, tailVisibleAt, motion: resolveMotion(config), rendersAs, scheduleOf};
}

export function segmentsDoc(config, {minFrames = 1} = {}) {
  const deps = kitDeps(config);
  const total = totalFrames(config);
  const tl = config.timeline;
  const cuts = new Set([0, total]);
  const add = (f) => { if (Number.isInteger(f) && f > 0 && f < total) cuts.add(f); };
  if (tl.introFrames > 0) add(tl.introFrames);
  for (const t of config.transitions) {
    if (!(t.frames > 0)) continue;
    const span = dep.transitionSpan(t, deps);
    add(span.from);
    add(span.to);
  }
  for (const c of config.cards || []) { add(tl.outroStart + c.start); add(tl.outroStart + c.start + c.frames); }
  add(tl.outroStart);
  if (config.ending && Number.isInteger(config.ending.plateStart)) add(config.ending.plateStart);
  if (tl.endCardFrames > 0) add(tl.mainFrames);
  // the iris never closes to nothing: the ending starts at the first frame without shot video (the plan's own rule)
  if (config.ending && Number.isInteger(config.ending.irisStart) && tl.endCardFrames > 0) {
    const plan = segments.planSegments({...config, segments: undefined}, deps);
    if (plan.segments[1]) add(plan.segments[1].start);
  }
  const windows = segments.effectWindows(config, deps);
  const sorted = [...cuts].sort((a, b) => a - b).filter((c) => c === 0 || c === total || !windows.some((w) => c > w.from && c < w.to));
  // dropping a cut never makes a segment invalid: merge every segment shorter than minFrames into its neighbour
  let cutList = sorted;
  for (;;) {
    const i = cutList.findIndex((c, k) => k + 1 < cutList.length && cutList[k + 1] - c < minFrames);
    if (i < 0) break;
    cutList = cutList.filter((_, k) => k !== (i + 1 < cutList.length - 1 ? i + 1 : i));
  }
  const list = [];
  for (let i = 0; i + 1 < cutList.length; i += 1) {
    list.push({id: `seg-${String(list.length + 1).padStart(2, '0')}`, kind: 'span', start: cutList[i], end_exclusive: cutList[i + 1]});
  }
  return {
    schema: 'jjv/segments/v1', fps: config.fps, total_frames: total, main_frames: tl.mainFrames, cut_points: cutList.slice(1, -1),
    segments: list.map((s) => ({...s, frames: s.end_exclusive - s.start, shots_visible: config.shots.filter((x) => x.start < s.end_exclusive && s.start < x.start + x.frames).map((x) => x.id)})),
  };
}
