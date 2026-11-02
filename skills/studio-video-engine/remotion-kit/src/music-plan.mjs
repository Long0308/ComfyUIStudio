// Music bed PLAN: pure data, no React, no audio. The engine declares the policy (`ending.music_bed`); this turns it into what the compositor plays.
//   extend 'loop_phrase_crossfade': when the film is longer than the music stem, loop the phrase [loop_start_s, loop_end_s) of the stem. The first
//     segment plays the stem from its start up to loop_end; every later segment starts crossfade_frames before the previous one ends, at
//     loop_start - crossfade_frames in the stem, so at the join the earlier pass is exactly at loop_end and the new one exactly at loop_start (the
//     declared phrase boundary). The crossfade is linear in / linear out, so the two gains sum to 1 on every overlap frame. The last segment
//     ends with the film on a fade-out of crossfade_frames.
//   extend 'none': the stem plays once, as before; frames past its end are reported in `uncovered`, never looped silently.
//   duck_db / duck_attack_frames / duck_release_frames / duck_under 'words': the gain drops by duck_db under every word window (dialogue words and
//     card windows), ramping down over the attack frames before it and back over the release frames after it (linear in dB).
// A film that fits inside the stem is one segment. Frames are integers at the film fps; loop points are rounded to the nearest frame.
// The stem should be UNDUCKED: a stem with dialogue ducking baked in would be ducked twice and would repeat its baked windows when looped.

const KNOWN = {
  extend: 'extend', loop_start_s: 'loopStartS', loopStartS: 'loopStartS', loop_end_s: 'loopEndS', loopEndS: 'loopEndS',
  crossfade_frames: 'crossfadeFrames', crossfadeFrames: 'crossfadeFrames', duck_db: 'duckDb', duckDb: 'duckDb',
  duck_attack_frames: 'duckAttackFrames', duckAttackFrames: 'duckAttackFrames', duck_release_frames: 'duckReleaseFrames', duckReleaseFrames: 'duckReleaseFrames',
  duck_under: 'duckUnder', duckUnder: 'duckUnder',
};
const SNAKE = {
  loopStartS: 'loop_start_s', loopEndS: 'loop_end_s', crossfadeFrames: 'crossfade_frames', duckDb: 'duck_db',
  duckAttackFrames: 'duck_attack_frames', duckReleaseFrames: 'duck_release_frames', duckUnder: 'duck_under',
};
export const DEFAULTS = {crossfadeFrames: 30, duckAttackFrames: 4, duckReleaseFrames: 8};
const EXTENDS = ['loop_phrase_crossfade', 'none'];

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isInt = (v) => Number.isInteger(v);
const fail = (msg) => {
  throw new Error(`ending.music_bed: ${msg}`);
};

/** The declared policy in kit form (camelCase keys, only what was declared), accepting the engine's snake_case spelling. Throws on anything unknown. */
export function normaliseBed(raw) {
  if (raw === null || raw === undefined) return {extend: 'none'};
  if (typeof raw !== 'object' || Array.isArray(raw)) fail('must be an object');
  const bed = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!(key in KNOWN)) fail(`unknown key '${key}' (allowed: ${Object.keys(SNAKE).map((k) => SNAKE[k]).concat('extend').join(', ')})`);
    bed[KNOWN[key]] = value;
  }
  const name = (camel) => SNAKE[camel] || camel;
  if (!EXTENDS.includes(bed.extend)) fail(`extend must be one of ${JSON.stringify(EXTENDS)}, got ${JSON.stringify(bed.extend)}`);
  for (const key of ['loopStartS', 'loopEndS']) if (key in bed && !(isNum(bed[key]) && bed[key] >= 0)) fail(`${name(key)} must be a number >= 0, got ${JSON.stringify(bed[key])}`);
  for (const key of ['crossfadeFrames', 'duckAttackFrames', 'duckReleaseFrames']) if (key in bed && !(isInt(bed[key]) && bed[key] >= 0)) fail(`${name(key)} must be an integer >= 0, got ${JSON.stringify(bed[key])}`);
  if ('duckDb' in bed && !(isNum(bed.duckDb) && bed.duckDb > 0)) fail(`duck_db must be > 0 (dB of ducking), got ${JSON.stringify(bed.duckDb)}`);
  if ('duckUnder' in bed && bed.duckUnder !== 'words') fail(`duck_under must be 'words', got ${JSON.stringify(bed.duckUnder)}`);
  if (bed.extend === 'loop_phrase_crossfade') {
    if (!('loopStartS' in bed) || !('loopEndS' in bed)) fail('extend loop_phrase_crossfade needs loop_start_s and loop_end_s');
    if (bed.loopEndS <= bed.loopStartS) fail('loop_end_s must be greater than loop_start_s');
  }
  return bed;
}

/** {bed, stemSeconds} from config.music (camelCase) or config.ending.musicBed, or null when the config declares no policy (the audio is then as before). */
export function musicPolicy(config) {
  const raw = (config.music && config.music.bed) || (config.ending && config.ending.musicBed);
  if (!raw) return null;
  const stemSeconds = config.music && config.music.stemSeconds;
  if (!(isNum(stemSeconds) && stemSeconds > 0)) throw new Error('a music bed policy needs config.music.stemSeconds (the music stem length in seconds)');
  return {bed: normaliseBed(raw), stemSeconds};
}

export const selectMusicMode = (config) => (musicPolicy(config) ? 'plan' : 'legacy');

/** Gain windows from the config: every dialogue word [startF, endF) and every card window, as merged, sorted global-frame ranges. */
export function wordWindows(config) {
  const raw = [];
  for (const shot of config.shots || []) {
    for (const w of shot.words || []) raw.push({from: w.startF, to: Math.max(w.endF, w.startF + 1)});
  }
  const outroStart = config.timeline ? config.timeline.outroStart : 0;
  for (const card of config.cards || []) raw.push({from: outroStart + card.start, to: outroStart + card.start + card.frames});
  return mergeWindows(raw);
}

export function mergeWindows(windows) {
  const sorted = windows.filter((w) => isNum(w.from) && isNum(w.to) && w.to > w.from).map((w) => ({from: w.from, to: w.to})).sort((a, b) => a.from - b.from);
  const out = [];
  for (const w of sorted) {
    const last = out[out.length - 1];
    if (last && w.from <= last.to) last.to = Math.max(last.to, w.to);
    else out.push(w);
  }
  return out;
}

/** Linear fade-in / fade-out gain of a segment at its local frame f. The overlap of two segments sums to exactly 1. */
export function segmentGain(seg, f) {
  const fadeIn = seg.fadeIn > 0 && f < seg.fadeIn ? f / seg.fadeIn : 1;
  const fadeOut = seg.fadeOut > 0 && f >= seg.durationInFrames - seg.fadeOut ? (seg.durationInFrames - f) / seg.fadeOut : 1;
  return Math.max(0, fadeIn * fadeOut);
}

function duckCurve(total, bed, windows) {
  const gains = new Float64Array(total).fill(1);
  if (!(bed.duckDb > 0)) return gains;
  const attack = bed.duckAttackFrames ?? DEFAULTS.duckAttackFrames;
  const release = bed.duckReleaseFrames ?? DEFAULTS.duckReleaseFrames;
  const depth = new Float64Array(total); // 0 = no ducking, 1 = the full duck_db
  const put = (g, d) => {
    if (g >= 0 && g < total && d > depth[g]) depth[g] = d;
  };
  for (const w of mergeWindows(windows || [])) {
    const from = Math.round(w.from);
    const to = Math.round(w.to);
    for (let g = from; g < to; g += 1) put(g, 1);
    for (let j = 1; j < attack; j += 1) put(from - j, (attack - j) / attack); // frame from - attack is 0, from - 1 the last ramp step
    for (let k = 1; k < release; k += 1) put(to - 1 + k, 1 - k / release); // the last word frame is 1, to - 1 + release is 0
  }
  for (let g = 0; g < total; g += 1) gains[g] = depth[g] === 0 ? 1 : 10 ** (-(bed.duckDb * depth[g]) / 20);
  return gains;
}

/**
 * @param {{totalFrames:number, fps:number, stemSeconds:number, bed:object, windows?:Array<{from:number,to:number}>}} spec
 * @returns {{segments:Array<{from,durationInFrames,startFromFrame,fadeIn,fadeOut}>, duck:(frame:number)=>number, uncovered:Array<{from,to}>, bed:object, stemFrames:number}}
 */
export function planMusic({totalFrames, fps, stemSeconds, bed, windows = []}) {
  if (!(isInt(totalFrames) && totalFrames > 0)) throw new Error(`totalFrames must be a positive integer (got ${totalFrames})`);
  if (!(isNum(fps) && fps > 0)) throw new Error(`fps must be a positive number (got ${fps})`);
  if (!(isNum(stemSeconds) && stemSeconds > 0)) throw new Error(`stemSeconds must be a positive number (got ${stemSeconds})`);
  const policy = normaliseBed(bed);
  const stemFrames = Math.floor(stemSeconds * fps + 1e-9);
  const crossfade = policy.crossfadeFrames ?? DEFAULTS.crossfadeFrames;
  const resolved = {...policy, crossfadeFrames: crossfade, stemFrames};
  const gains = duckCurve(totalFrames, policy, windows);
  const duck = (frame) => (frame >= 0 && frame < totalFrames ? gains[Math.floor(frame)] : 1);
  const segments = [];
  let uncovered = [];

  if (policy.extend === 'none') {
    segments.push({from: 0, durationInFrames: Math.min(totalFrames, stemFrames), startFromFrame: 0, fadeIn: 0, fadeOut: 0});
    if (totalFrames > stemFrames) uncovered = [{from: stemFrames, to: totalFrames}];
    return {segments, duck, uncovered, bed: resolved, stemFrames};
  }

  const loopStart = Math.round(policy.loopStartS * fps);
  const loopEnd = Math.round(policy.loopEndS * fps);
  if (loopEnd > stemFrames) fail(`loop_end_s ${policy.loopEndS} is beyond the stem (${stemSeconds} s)`);
  if (loopEnd <= loopStart) fail('loop_end_s must be greater than loop_start_s (after rounding to frames)');
  if (crossfade > loopStart) fail(`crossfade_frames ${crossfade} is longer than the ${loopStart} frames before loop_start_s (the crossfade reads the stem from loop_start_s - crossfade_frames)`);
  const phrase = loopEnd - loopStart;
  if (crossfade > phrase) fail(`crossfade_frames ${crossfade} is longer than the loop phrase (${phrase} frames)`);
  Object.assign(resolved, {loopStartFrame: loopStart, loopEndFrame: loopEnd});

  if (totalFrames <= stemFrames) {
    // the stem is long enough: no loop, the film ends on a short fade
    segments.push({from: 0, durationInFrames: totalFrames, startFromFrame: 0, fadeIn: 0, fadeOut: Math.min(crossfade, totalFrames)});
    return {segments, duck, uncovered, bed: resolved, stemFrames};
  }
  segments.push({from: 0, durationInFrames: loopEnd, startFromFrame: 0, fadeIn: 0, fadeOut: crossfade}); // reaches loop_end at global frame loopEnd
  let reach = loopEnd; // the global frame at which the latest segment is at loop_end
  while (reach < totalFrames) {
    const from = reach - crossfade;
    const natural = reach + phrase; // where this pass reaches loop_end again
    if (totalFrames <= natural) {
      const durationInFrames = totalFrames - from;
      segments.push({from, durationInFrames, startFromFrame: loopStart - crossfade, fadeIn: crossfade, fadeOut: Math.min(crossfade, durationInFrames)});
      break;
    }
    segments.push({from, durationInFrames: natural - from, startFromFrame: loopStart - crossfade, fadeIn: crossfade, fadeOut: crossfade});
    reach = natural;
  }
  return {segments, duck, uncovered, bed: resolved, stemFrames};
}
