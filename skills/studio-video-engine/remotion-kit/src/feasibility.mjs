// Per-boundary FEASIBILITY of every transition preset. Pure: nothing is rendered, probed or requested here.
//
// Principle: a transition is a compositing layer. Choosing or changing one never re-renders shot video, so a preset that plays the
// outgoing clip's native TAIL is only usable where the bound clip already holds those frames. The rule is the engine's tail rule
// (engine/editorial/transitions.py check_tail), implemented once in lib/tailcheck.cjs (tailFits) and reused here:
//   available = fileFrames - editorialFrames              native frames of the bound file after what the editorial cut uses
//   need      = ceil(4 N / 5)                             N = the preset's tail output frames
//   last      = ceil((startFrom + N - 1) * nativeFps / fps)   must be <= fileFrames - 1
// A boundary without tail data has a zero handle: only presets with tail_frames "none" are available there.
// The catalog (schemas/transition-presets.json) is passed in, never read here.
import tailcheck from '../lib/tailcheck.cjs';

const {tailFits} = tailcheck;

export const NO_GPU = 'no GPU work is requested; choose a preset without a tail or restore the tail separately';
const MODES = ['review', 'master'];

const isInt = (v) => Number.isInteger(v);

// the preset a config transition plays: the explicit `preset`, else the type, where the first build's 9-frame dip is the legacy schedule
export function presetNameOf(t) {
  if (t.preset) return t.preset;
  return t.type === 'dip_white' && t.frames === 9 ? 'dip_white_legacy' : t.type;
}

export const defaultFrames = (preset) => (preset.frames.fixed !== undefined ? preset.frames.fixed : preset.frames.default);

// every legal frame count, ascending (engine presets.candidate_frames)
export function candidateFrames(preset) {
  const rule = preset.frames;
  if (rule.fixed !== undefined) return [rule.fixed];
  const out = [];
  for (let n = rule.min; n <= rule.max; n += rule.even ? 2 : 1) out.push(n);
  return out;
}

// output frames that must come from the outgoing native tail (engine presets.tail_frames); `schedule` = the out_tail rows of the row in use
export function tailCount(preset, frames, schedule) {
  switch (preset.tail_frames) {
    case 'none': return 0;
    case 'all': return frames;
    case 'half': return Math.ceil(frames / 2);
    default: return (schedule || preset.schedule || []).filter((e) => e.shot === 'out_tail').length;
  }
}

function findTransition(config, ref) {
  const list = Array.isArray(config.transitions) ? config.transitions : [];
  if (ref && typeof ref === 'object') return ref;
  const text = String(ref);
  const hit = list.find((t) => t.id === text) || (/^\d+$/.test(text) ? list.find((t) => t.boundary === Number(text)) : undefined);
  if (!hit) throw new Error(`no boundary ${text} in the config (known: ${list.map((t) => t.id).join(', ')})`);
  return hit;
}

const hasTail = (t) => Boolean(t && t.tail && isInt(t.tail.startFrom) && isInt(t.tail.editorialFrames) && isInt(t.tail.fileFrames));

// native frame rate of a bound tail file: the config's own number, else one the caller measured (render.cjs probes the bound file), else
// derived from the editorial cut (it shows startFrom delivery frames from editorialFrames native frames), else assumed equal to delivery
function nativeFpsOf(config, t, nativeFps) {
  if (t.tail && Number.isFinite(t.tail.nativeFps) && t.tail.nativeFps > 0) return {value: t.tail.nativeFps, source: 'config tail.nativeFps'};
  const given = typeof nativeFps === 'function' ? nativeFps(t) : nativeFps && nativeFps[t.id];
  if (Number.isFinite(given) && given > 0) return {value: given, source: 'measured on the bound tail file'};
  if (t.tail && t.tail.editorialFrames > 0 && t.tail.startFrom > 0) return {value: (config.fps * t.tail.editorialFrames) / t.tail.startFrom, source: 'derived from the editorial cut'};
  return {value: config.fps, source: 'assumed equal to the delivery fps'};
}

function noHandleReason(config, t) {
  const shotIds = new Set();
  for (const s of config.shots || []) {
    shotIds.add(s.id);
    for (const g of s.segments || []) shotIds.add(g.id);
  }
  const why = shotIds.size && !shotIds.has(t.from) ? `'${t.from}' is not a shot, so it has no native tail` : 'no tail_clip is declared on this boundary';
  return `${why}; ${NO_GPU}`;
}

// can `preset` play `frames` frames on this boundary's handle? {ok, count, need, have, last, why}
function judge(config, t, preset, frames, schedule, fpsInfo) {
  const count = tailCount(preset, frames, schedule);
  if (count === 0) return {count, ok: true, need: 0, have: hasTail(t) ? t.tail.fileFrames - t.tail.editorialFrames : null};
  if (!hasTail(t)) return {count, ok: false, need: tailFits({frames: 0, nativeFps: 1, fps: 1, startFrom: 0, n: count, editorialFrames: 0}).needed, have: null, noHandle: true};
  const r = tailFits({frames: t.tail.fileFrames, nativeFps: fpsInfo.value, fps: config.fps, startFrom: t.tail.startFrom, n: count, editorialFrames: t.tail.editorialFrames});
  return {count, ok: r.ok, need: r.needed, have: r.available, last: r.lastIndex, problems: r.problems};
}

function entryFor(config, t, name, preset, current, fpsInfo) {
  const frames = current === name ? t.frames : defaultFrames(preset);
  const schedule = current === name ? t.schedule : undefined;
  const j = judge(config, t, preset, frames, schedule, fpsInfo);
  const entry = {
    available: j.ok, frames, needsTailFrames: j.need, haveNativeFrames: j.have, maxFrames: null,
    category: preset.category, label: preset.label, reason: null, whyNot: null,
  };
  if (j.count === 0) {
    entry.maxFrames = candidateFrames(preset).slice(-1)[0];
    entry.reason = 'no tail needed: it plays only the pictures the editorial cut already uses';
    return entry;
  }
  const fits = hasTail(t) ? candidateFrames(preset).filter((n) => judge(config, t, preset, n, undefined, fpsInfo).ok) : [];
  entry.maxFrames = fits.length ? fits[fits.length - 1] : null;
  if (j.ok) {
    entry.reason = `plays ${j.count} native tail frame(s): needs ${j.need} beyond the cut, the handle has ${j.have}`;
    return entry;
  }
  entry.whyNot = j.noHandle
    ? noHandleReason(config, t)
    : `tail handle too short: ${j.have} native tail frame(s) available, ${j.need} needed for ${frames} frames (ceil(0.8 x ${j.count})), last native index used ${j.last}/${t.tail.fileFrames - 1}${fits.length ? `; at most ${entry.maxFrames} frames fit; ` : '; '}${NO_GPU}`;
  entry.reason = j.noHandle ? 'no tail handle on this boundary' : 'the handle is shorter than this preset needs';
  return entry;
}

/**
 * @param {object} config kit config (transitions[].tail carries the handle)
 * @param {string|number|object} ref transition id, boundary frame (number or numeric string) or the transition itself
 * @param {{mode?:'review'|'master', catalog:object, masterConfig?:object, nativeFps?:object|Function}} opts
 *   mode 'master': `config` is read as the MASTER kit config (its 4K tails). `masterConfig` given in review mode adds master_covers per preset.
 */
export function presetAvailability(config, ref, opts = {}) {
  const mode = opts.mode || 'review';
  if (!MODES.includes(mode)) throw new Error(`mode must be review or master (got ${mode})`);
  const {catalog} = opts;
  if (!catalog || !catalog.presets) throw new Error('presetAvailability needs the preset catalog (schemas/transition-presets.json)');
  const t = findTransition(config, ref);
  const current = presetNameOf(t);
  const fpsInfo = nativeFpsOf(config, t, opts.nativeFps);
  const master = opts.masterConfig ? ((opts.masterConfig.transitions || []).find((x) => x.id === t.id) || {id: t.id, from: t.from}) : null;
  const masterFps = master && nativeFpsOf(opts.masterConfig, master, opts.nativeFps);
  const presets = {};
  for (const [name, preset] of Object.entries(catalog.presets)) {
    if (preset.status !== 'ready') continue;
    const row = entryFor(config, t, name, preset, current, fpsInfo);
    if (master) {
      const m = entryFor(opts.masterConfig, master, name, preset, current, masterFps);
      row.master_covers = m.available;
      row.master_why_not = m.whyNot;
    }
    presets[name] = row;
  }
  return {
    id: t.id, boundary: t.boundary, from: t.from, to: t.to, mode,
    current: {type: t.type, preset: current, frames: t.frames},
    tail: hasTail(t)
      ? {startFrom: t.tail.startFrom, editorialFrames: t.tail.editorialFrames, fileFrames: t.tail.fileFrames, nativeFps: fpsInfo.value, nativeFpsSource: fpsInfo.source, haveNativeFrames: t.tail.fileFrames - t.tail.editorialFrames}
      : null,
    presets,
  };
}

/**
 * Refusals for the presets the config CHOSE: a tail preset whose handle is missing or short. One message per boundary, naming it, the
 * frames that are missing and that no GPU work is requested. Types the catalog does not know (the kit's own legacy names) are left to
 * validate.mjs, which already requires a tail for those.
 */
export function tailHandleIssues(config, {catalog, nativeFps} = {}) {
  if (!catalog || !catalog.presets) throw new Error('tailHandleIssues needs the preset catalog (schemas/transition-presets.json)');
  const issues = [];
  for (const t of config.transitions || []) {
    const name = presetNameOf(t);
    const preset = catalog.presets[name];
    if (!preset || preset.status !== 'ready') continue;
    const j = judge(config, t, preset, t.frames, t.schedule, nativeFpsOf(config, t, nativeFps));
    if (j.count === 0 || j.ok) continue;
    if (j.noHandle) {
      issues.push(`${t.id} (${name}): plays ${j.count} native tail frame(s) but the boundary has no tail handle: missing ${j.need} native tail frame(s); ${NO_GPU}`);
      continue;
    }
    const missing = Math.max(0, j.need - j.have);
    issues.push(`${t.id} (${name}): tail handle too short: ${missing > 0 ? `missing ${missing} native tail frame(s)` : 'the last native frame it needs is beyond the file'} (${j.problems.join('; ')}); ${NO_GPU}`);
  }
  return issues;
}
