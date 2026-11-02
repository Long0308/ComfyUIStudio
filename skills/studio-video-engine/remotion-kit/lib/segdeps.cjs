'use strict';
// Dependency slice of a segment (T-E45 P2, spec 3.3): the part of the kit config a segment's PIXELS can depend on, and the node key
// built from it. A segment is re-rendered only when its key changes. Pure Node (the compositor functions it needs are INJECTED, like
// lib/segments.cjs): no Remotion, no React.
//
// The slice is CONSERVATIVE by construction and checked by a property test (tests/round14-p2-property.test.mjs): every leaf of the
// config that is NOT in a segment's slice is mutated and the segment's frames must stay byte-identical; a function that drops a leaf the
// compositor reads makes that test red (the "mutant must be killed" case).
//
//   video slice  = global (schema, fps, timeline, theme, motion, review label, clock, waivers) + the segment range
//                + the shots that intersect it (whole record) + the transitions whose effect window intersects it (resolved row, tail
//                numbers, schedule, overlay) + the icon events that intersect it (and the shot each one pops on) + the cards the segment
//                can show (+ the header strings, + a card meta {count, starts}) + intro / ending blocks when it reaches them
//                + the sha256 of EXACTLY the picture / tail / icon / opening / logo files its frames mount (never paths).
//   audio slice  = everything the one mix can depend on (stems, policy, dialogue and card WAVs, the clips' own audio tracks, all
//                timing) and nothing purely visual (strings, intro, icons, theme, review label, plate text).

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {videoUsage} = require('./segments.cjs');

const sha256Text = (text) => crypto.createHash('sha256').update(text).digest('hex');

// canonical JSON: sorted keys, undefined dropped
function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(',')}]`;
  if (v && typeof v === 'object') {
    return `{${Object.keys(v).filter((k) => v[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}`;
  }
  return JSON.stringify(v === undefined ? null : v);
}

const hashOf = (value) => sha256Text(canon(value));
const isInt = Number.isInteger;

// the content identity of a binding: its sha256 (and whether it is a preview source), never its path
const bindSha = (b) => (b && b.sha256 ? `${b.sha256}${b.preview ? ':preview' : ''}` : null);

// shot keys only src/validate.mjs reads (the dip-peak rule's evidence): no compositor component draws them, so they are validated on every build (the whole
// config is validated first) but are NOT pixels: a new word-timing document relabels every shot and must not stale the film
const SHOT_VALIDATOR_ONLY_KEYS = new Set(['onsetEvidence', 'speechOnsetF']);
const pixelShot = (shot) => pick(shot, (k) => !SHOT_VALIDATOR_ONLY_KEYS.has(k));

// ending keys that only the audio mix reads, and the keys of the end plate (the rest belongs to the iris / logo disc block)
const ENDING_AUDIO_KEYS = new Set(['tailFrom', 'musicBed', 'tailFadeIn', 'tailFadeStart']);
const ENDING_PLATE_KEYS = new Set(['plateStart', 'speechEndFrame', 'plateEn', 'plateVi']);

function pick(obj, keep) {
  const out = {};
  for (const [k, v] of Object.entries(obj || {})) if (keep(k)) out[k] = v;
  return out;
}

// the frames a transition's effect can touch: its window, its tail window, a dip schedule, an iris to the end of the row
function transitionSpan(t, deps) {
  const start = t.start !== undefined ? t.start : t.boundary;
  let from = Math.min(start, t.boundary);
  let to = Math.max(start + (t.frames || 0), t.boundary + 1);
  if (isInt(t.end_exclusive)) to = Math.max(to, t.end_exclusive);
  const w = deps.tailWindow(t);
  if (w) {
    from = Math.min(from, w.from);
    to = Math.max(to, w.from + w.frames);
  }
  if (deps.rendersAs(t) === 'dip_white') {
    const sched = deps.scheduleOf(t) || [];
    const rels = sched.map((e) => e.t);
    if (rels.length) {
      from = Math.min(from, t.boundary + Math.min(...rels));
      to = Math.max(to, t.boundary + Math.max(...rels) + 1);
    }
    to = Math.max(to, t.boundary + ((deps.motion.dip && deps.motion.dip.peakFrames) || 0));
  }
  return {from, to};
}

const intersects = (aFrom, aTo, bFrom, bTo) => aFrom < bTo && bFrom < aTo;

// where the ending blocks start to matter (the disc / iris block, and the end plate)
function endingRanges(config) {
  const e = config.ending || {};
  const discKeys = ['irisStart', 'discIn', 'discSlideStart', 'discFadeStart'].map((k) => e[k]).filter(isInt);
  return {disc: discKeys.length ? Math.min(...discKeys) : null, plate: isInt(e.plateStart) ? e.plateStart : null};
}

/**
 * The video slice of one segment.
 * @param {object} config kit config
 * @param {{id,start,end_exclusive}} seg
 * @param {{deps:object}} ctx deps = {pictureMode, transitionIndex, tailWindow, tailVisibleAt, motion, rendersAs, scheduleOf}
 * @returns {{parts:Object<string,*>}} parts: name -> JSON value (the leaf-level diff of two slices names the changed leaf)
 */
function videoSlice(config, seg, ctx) {
  const {deps} = ctx;
  const mode = ctx.mode || 'review';
  const s = seg.start;
  const e = seg.end_exclusive;
  const tl = config.timeline;
  const bindings = config.bindings || {};
  const parts = {};
  parts.range = [s, e];
  parts['global.schema'] = config.schema;
  parts['global.fps'] = config.fps;
  parts['global.timeline'] = tl;
  parts['global.theme'] = config.theme || null;
  parts['global.motion'] = config.motion || null;
  parts['global.clock'] = config.clock || null;
  parts['global.waivers'] = config.waivers || null;
  if (mode === 'review') parts['global.review'] = config.review || null;

  // shots that intersect: the whole record (words, caption lines, segments, speech end ...)
  for (const shot of config.shots) if (intersects(shot.start, shot.start + shot.frames, s, e)) parts[`shot:${shot.id}`] = pixelShot(shot);
  // transitions whose effect window intersects
  for (const t of config.transitions) {
    const span = transitionSpan(t, deps);
    if (intersects(span.from, span.to, s, e)) parts[`transition:${t.id}`] = t;
  }
  // icon events (a pop can straddle a cut) and the shot each one pops on
  for (const ev of config.icons || []) {
    if (!intersects(ev.frame, ev.frame + ev.totalFrames, s, e)) continue;
    parts[`icon:${ev.id}`] = ev;
    const shot = config.shots.find((x) => x.id === ev.shot);
    if (shot) parts[`shot:${shot.id}`] = pixelShot(shot);
    parts[`file:icon:${ev.icon}`] = bindSha((bindings.icons || {})[ev.icon]);
  }
  // intro
  if (tl.introFrames > 0 && intersects(0, tl.introFrames, s, e)) {
    parts.intro = config.intro || null;
    parts['file:opening'] = bindSha(bindings.opening);
    parts['file:logo'] = bindSha(bindings.logo);
  }
  // cards: the outro block draws the header, counter and pips from the card list and the unit of each card it can show
  const cards = config.cards || [];
  if (cards.length && intersects(tl.outroStart, tl.outroStart + tl.outroFrames, s, e)) {
    const CARD = deps.motion.cards || {};
    parts.strings = config.strings || null;
    parts['cards.meta'] = {count: cards.length, windows: cards.map((c) => [c.start, c.frames])};
    cards.forEach((card, i) => {
      const isLast = i === cards.length - 1;
      const from = tl.outroStart + card.start - (CARD.lead || 0) - 1;
      const to = isLast ? Infinity : tl.outroStart + card.start + card.frames + (CARD.xfadeAfter || 0) + 1;
      if (intersects(from, to, s, e)) {
        parts[`card:${i}`] = card;
        parts[`file:card-icon:${i}`] = bindSha(((bindings.cards || [])[i] || {}).icon);
      }
    });
  }
  // ending: the iris / logo disc block, then the end plate (plate text lives only in segments that reach the plate)
  const ranges = endingRanges(config);
  const ending = config.ending || {};
  if (ranges.disc !== null && e > ranges.disc) {
    parts['ending.disc'] = pick(ending, (k) => !ENDING_AUDIO_KEYS.has(k) && !ENDING_PLATE_KEYS.has(k));
    parts['file:logo'] = bindSha(bindings.logo);
  }
  if (ranges.plate !== null && e > ranges.plate) {
    parts['ending.plate'] = pick(ending, (k) => ENDING_PLATE_KEYS.has(k));
    parts['file:logo'] = bindSha(bindings.logo);
  }
  if (tl.endCardFrames > 0 && e > tl.mainFrames) parts['file:logo'] = bindSha(bindings.logo);
  // the shot video files the segment's frames actually mount (an ending segment mounts none)
  const usage = videoUsage(config, deps, s, e - 1);
  for (const shot of config.shots) {
    if (!usage.shots.has(shot.id)) continue;
    for (const sg of shot.segments || []) {
      parts[`file:picture:${shot.id}/${sg.id}`] = bindSha((((bindings.shots || {})[shot.id] || {}).segments || {})[sg.id]);
    }
  }
  for (const id of usage.tails) parts[`file:tail:${id}`] = bindSha((bindings.tails || {})[id]);
  return {parts};
}

/**
 * The audio slice: exactly what the ONE whole-film mix reads (T-E45, derived from film.jsx / cards.jsx / music.jsx). Every clip the compositor
 * mounts is muted (`<OffthreadVideo muted>`), so no picture, tail or transition row is audio: a shot picture, a tail clip, a transition effect,
 * a caption, an icon, a colour or a string never re-renders the mix. What plays:
 *   - the music stem (+ policy) and the ambience stem, whole film;
 *   - one dialogue WAV per shot, inside that shot's Sequence (start, frames);
 *   - one WAV per vocabulary card, inside the outro Sequence (outroStart, outroFrames) at the card start;
 *   - the end-card music tail (legacy mode only): ending.tailFrom, the fade numbers, the main / end-card frame counts;
 *   - with a music bed POLICY (plan mode): the ducking windows, i.e. every dialogue word window and card window, so word timing is audio only then.
 * The music mode is the rule of src/music-plan.mjs selectMusicMode (a drift test compares the two).
 */
// plan mode = the config declares a music bed policy (music.bed or ending.musicBed), exactly selectMusicMode's rule
const musicModeOf = (config) => ((config.music && config.music.bed) || (config.ending && config.ending.musicBed) ? 'plan' : 'legacy');

function audioSlice(config, ctx) {
  const bindings = config.bindings || {};
  const tl = config.timeline;
  const plan = musicModeOf(config) === 'plan';
  const motionEnding = (config.motion && config.motion.ending) || {};
  const ending = config.ending || {};
  const parts = {};
  parts['global.fps'] = config.fps;
  parts['audio.timeline'] = {mainFrames: tl.mainFrames, endCardFrames: tl.endCardFrames, outroStart: tl.outroStart, outroFrames: tl.outroFrames};
  parts['audio.mode'] = `${ctx.mode || 'review'}:${plan ? 'plan' : 'legacy'}`;
  parts['audio.shots'] = config.shots.map((x) => ({id: x.id, start: x.start, frames: x.frames}));
  parts['audio.cards'] = (config.cards || []).map((c) => [c.start, c.frames]);
  parts.music = config.music || null;
  if (plan) parts['audio.words'] = config.shots.map((x) => (x.words || []).map((w) => [w.startF, w.endF]));
  else parts['audio.endTail'] = {tailFrom: ending.tailFrom, tailFadeIn: ending.tailFadeIn, tailFadeStart: ending.tailFadeStart, motionTailFadeIn: motionEnding.tailFadeIn, motionTailFadeStart: motionEnding.tailFadeStart};
  if (plan) parts['audio.musicBed'] = ending.musicBed || null;
  parts['file:music'] = bindSha(bindings.music);
  parts['file:ambience'] = bindSha(bindings.ambience);
  parts['file:dialogue'] = Object.fromEntries(config.shots.map((x) => [x.id, bindSha(((bindings.shots || {})[x.id] || {}).audio)]));
  parts['file:cards'] = (bindings.cards || []).map((c) => bindSha(c && c.audio));
  return {parts};
}

const hashParts = (parts) => Object.fromEntries(Object.entries(parts).map(([k, v]) => [k, hashOf(v)]));

/** node key = sha256(canonical {pins, part hashes}). `kind` separates a video key from an audio key of identical parts. */
function nodeKey(kind, slice, pins) {
  return hashOf({kind, pins, parts: hashParts(slice.parts)});
}

// sha256 over every file in the video-relevant kit source (audio-only files are in the audio pins, not here)
const AUDIO_ONLY_SRC = new Set(['music.jsx', 'music-plan.mjs', 'feasibility.mjs']);
function listFiles(dir, base = dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, {withFileTypes: true}).sort((a, b) => (a.name < b.name ? -1 : 1))) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...listFiles(full, base));
    else out.push(path.relative(base, full).split(path.sep).join('/'));
  }
  return out;
}
function sourceSha(srcDir, {audio = false} = {}) {
  const h = crypto.createHash('sha256');
  for (const rel of listFiles(srcDir)) {
    const isAudioFile = AUDIO_ONLY_SRC.has(rel);
    if (isAudioFile && !audio) continue;
    h.update(`${rel}\0`);
    h.update(fs.readFileSync(path.join(srcDir, rel)));
    h.update('\0');
  }
  return h.digest('hex');
}

// leaf-level diff of two part values: the paths whose value changed (capped), for the stale reason
function diffLeaves(a, b, prefix, out, cap = 6) {
  if (out.length >= cap) return;
  if (canon(a) === canon(b)) return;
  const bothObj = a && b && typeof a === 'object' && typeof b === 'object' && Array.isArray(a) === Array.isArray(b);
  if (!bothObj) {
    out.push(prefix);
    return;
  }
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
  for (const k of keys) diffLeaves(a[k], b[k], `${prefix}.${k}`, out, cap);
}

/** why a segment is stale: the parts (and leaf paths) that differ between the previous slice and this one */
function staleReason(previousParts, parts) {
  if (!previousParts) return 'no previous record for this segment';
  const names = [...new Set([...Object.keys(previousParts), ...Object.keys(parts)])];
  const out = [];
  for (const name of names) {
    if (canon(previousParts[name]) === canon(parts[name])) continue;
    if (!(name in previousParts)) out.push(`+${name}`);
    else if (!(name in parts)) out.push(`-${name}`);
    else diffLeaves(previousParts[name], parts[name], name, out);
  }
  return out.length ? `slice changed: ${out.slice(0, 8).join(', ')}${out.length > 8 ? ', ...' : ''}` : 'pins changed (kit source, remotion, browser, fonts, codec or mode)';
}

module.exports = {musicModeOf, canon, hashOf, bindSha, videoSlice, audioSlice, nodeKey, hashParts, sourceSha, staleReason, transitionSpan, endingRanges, ENDING_AUDIO_KEYS, ENDING_PLATE_KEYS};
