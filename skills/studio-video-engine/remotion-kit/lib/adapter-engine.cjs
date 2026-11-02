#!/usr/bin/env node
'use strict';
// Engine-output adapter: maps what `jjv editorial build-config` WRITES (review-config.json + events.json, bound through the engine's build
// summary) onto the kit config (jjk-remotion-kit/config/v1). A swapped effect, a derived timeline, a music bed: all of it is read from the
// engine's records, so a change made only in boundaries.json + ending params needs no change here.
//
//   node lib/adapter-engine.cjs --review-config F --events F --receipt SUMMARY.json --episode-root DIR --episode-text FILE
//        [--allow-outside PATH]... [--label TEXT] [--waive-historical-dip ...] --out kit-config.json
//
// What the engine does not carry comes from the episode text file (jjk-remotion-kit/episode-text/v1; --episode-text is REQUIRED, this module has no default):
// intro and strings, Vietnamese captions, vocabulary card details and icons, the opening image, the music / ambience stems, and the disc layout
// when boundaries.json declares no ending.logo_disc_layout. Every path (engine records and episode text) is episode-relative, resolved against
// --episode-root, refused when it leaves the root unless named by --allow-outside, and hash-verified (a missing sha256 in the episode text is
// computed and listed in provenance.unbound_assets).

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {loadBuild, isBound, mapTransition, historicalDipWaivers, waiverOptions} = require('./build-binding.cjs');
const {probeClip} = require('./tailcheck.cjs');
const {wavSeconds} = require('./wavinfo.cjs');

const SHA_HEX = /^[0-9a-f]{64}$/;
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
const sameFile = (a, b) => (process.platform === 'win32' ? path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase() : path.resolve(a) === path.resolve(b));
const isStr = (v) => typeof v === 'string' && v.length > 0;
const BED_KEYS = {
  extend: 'extend', loop_start_s: 'loopStartS', loop_end_s: 'loopEndS', crossfade_frames: 'crossfadeFrames', duck_db: 'duckDb',
  duck_attack_frames: 'duckAttackFrames', duck_release_frames: 'duckReleaseFrames', duck_under: 'duckUnder',
};

function assertSame(label, a, b) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`adapter-engine: events.json and review-config.json disagree on ${label}`);
}

// ---- paths: episode-relative, inside the root, hash-verified ---------------------------------------------------------
function makeResolver({episodeRoot, allowOutside, verifyHashes}) {
  const root = path.resolve(episodeRoot);
  const cache = new Map();
  const unbound = [];
  const hashOf = (file) => {
    if (!cache.has(file)) cache.set(file, sha(file));
    return cache.get(file);
  };
  function resolve(ref, what, {record = true} = {}) {
    if (!ref || !isStr(ref.path)) throw new Error(`${what}: needs a path`);
    const abs = path.isAbsolute(ref.path) ? path.resolve(ref.path) : path.resolve(root, ref.path);
    const rel = path.relative(root, abs);
    const inside = rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
    if (!inside && !allowOutside.some((allowed) => sameFile(allowed, abs))) {
      throw new Error(`${what}: ${abs} is outside the episode root ${root} (name it with --allow-outside to use it)`);
    }
    if (!fs.existsSync(abs)) throw new Error(`${what}: file missing (${abs})`);
    if (ref.sha256 !== undefined && !SHA_HEX.test(String(ref.sha256))) throw new Error(`${what}: sha256 is not 64 hex characters`);
    const actual = verifyHashes || ref.sha256 === undefined ? hashOf(abs) : ref.sha256;
    if (ref.sha256 !== undefined && actual !== ref.sha256) throw new Error(`${what}: sha256 ${actual} differs from the recorded ${ref.sha256} (${abs})`);
    if (ref.sha256 === undefined && record) unbound.push({what, path: abs, sha256: actual});
    return {path: abs, sha256: actual};
  }
  return {resolve, unbound, root};
}

// ---- the episode text --------------------------------------------------------------------------------------------------
function requireText(text, review) {
  if (!text || typeof text !== 'object') throw new Error('episode text is required (--episode-text FILE: intro, strings, captions, cards, assets)');
  const need = (value, key) => {
    if (!isStr(value)) throw new Error(`episode text ${key} is required`);
  };
  const strings = text.strings || {};
  need(strings.cardsHeader, 'strings.cardsHeader');
  need(strings.cardsHeaderClosing, 'strings.cardsHeaderClosing');
  const introFrames = review.dialogue[0].start_frame;
  if (introFrames > 0) {
    const intro = text.intro || {};
    for (const key of ['kicker', 'pill', 'footer']) need(intro[key], `intro.${key}`);
    if (!Array.isArray(intro.titleLines) || !intro.titleLines.length) throw new Error('episode text intro.titleLines is required');
    if (!['drop', 'none'].includes(intro.mark)) throw new Error("episode text intro.mark must be 'drop' or 'none'");
  }
  for (const shot of review.dialogue) need((text.shotVi || {})[shot.id], `shotVi.${shot.id}`);
  for (const card of review.outro_cards) {
    const c = (text.cards || {})[card.term];
    if (!c) throw new Error(`episode text cards.${card.term} is required (ipa, vi, exampleEn, icon)`);
    for (const key of ['ipa', 'vi', 'exampleEn']) need(c[key], `cards.${card.term}.${key}`);
    if (!c.icon || !c.icon.path) throw new Error(`episode text cards.${card.term}.icon is required`);
  }
  const assets = text.assets || {};
  if (introFrames > 0 && !assets.opening) throw new Error('episode text assets.opening is required (the intro shows it)');
  if (!assets.music) throw new Error('episode text assets.music is required (the music stem)');
}

// first SPOKEN frame per shot from the word-timing document (entries[*].onset_fix.new_start_frame), as the build adapters read it
function onsetEvidence(review, episodeRoot) {
  const ref = review.word_timing;
  if (!ref || !ref.path || !ref.sha256) throw new Error('review config: word_timing.path and word_timing.sha256 are required');
  const file = path.isAbsolute(ref.path) ? ref.path : path.resolve(episodeRoot, ref.path);
  if (!fs.existsSync(file)) throw new Error(`review config: the word-timing file ${file} is missing`);
  if (sha(file) !== ref.sha256) throw new Error(`word-timing file changed since the build (${file})`);
  const frames = {};
  const doc = readJson(file);
  for (const entry of doc.entries || []) {
    const f = entry.onset_fix && entry.onset_fix.new_start_frame;
    if (Number.isInteger(f)) frames[entry.id] = f;
  }
  return Object.keys(frames).length ? {frames, label: `${doc.schema} onset_fix, sha256 ${ref.sha256.slice(0, 12)}`} : {frames, label: null};
}

function endingFrom(E, text, fps, endCardFrames) {
  const layout = E.logo_disc_layout || {};
  const fromText = (text.ending || {});
  const pick = (layoutKey, textKey, what) => {
    if (layout[layoutKey] !== undefined) return layout[layoutKey];
    if (fromText[textKey] !== undefined) return fromText[textKey];
    throw new Error(`ending.${what} is not declared: set ending.logo_disc_layout.${layoutKey} or episode text ending.${textKey}`);
  };
  const out = {};
  if (E.iris) {
    Object.assign(out, {irisStart: E.iris.start, irisClosed: E.iris.closed, irisCentre: E.iris.centre, irisEndRadius: E.iris.end_radius});
    if (E.logo_disc) {
      if (layout.disc_in !== undefined && layout.disc_in !== E.logo_disc.in) throw new Error(`ending.logo_disc_layout.disc_in ${layout.disc_in} differs from logo_disc.in ${E.logo_disc.in}`);
      Object.assign(out, {
        discIn: E.logo_disc.in, discFadeStart: E.logo_disc.fade_start, discFadeFrames: E.logo_disc.fade_frames,
        discSlideStart: pick('slide_start', 'discSlideStart', 'discSlideStart'), discSlideEnd: pick('slide_end', 'discSlideEnd', 'discSlideEnd'),
        discSlideX: pick('slide_x', 'discSlideX', 'discSlideX'), pillLeftX: pick('pill_left_x', 'pillLeftX', 'pillLeftX'),
      });
    }
  }
  if (E.end_plate) {
    Object.assign(out, {plateStart: E.end_plate.start, speechEndFrame: E.end_plate.speech_end_frame, plateEn: E.end_plate.text_en, plateVi: E.end_plate.text_vi});
    // engine builds follow the approved v013 plate (scrim from 0.4, logo gated until plate clock 2, 8 f ease-out); episode text may name another style
    out.plateStyle = fromText.plateStyle !== undefined ? fromText.plateStyle : 'v010';
  }
  if (endCardFrames > 0) {
    if (!(fromText.tailFromSeconds >= 0)) throw new Error('episode text ending.tailFromSeconds is required (the music phrase replayed under the end card)');
    out.tailFrom = Math.round(fromText.tailFromSeconds * fps);
    // the engine records the tail fades as prose only ("fade in 6 f / out f20-f60"), so the numbers come from the episode text:
    // endLogoTail {fadeInFrames, fadeStartFrames}: gain 0 -> 1 over fadeInFrames, hold to fadeStartFrames, fade out to the last end-card frame
    const tail = fromText.endLogoTail;
    const okInt = (v) => Number.isInteger(v) && v >= 0;
    if (!tail || !okInt(tail.fadeInFrames) || !okInt(tail.fadeStartFrames)) {
      throw new Error('episode text ending.endLogoTail {fadeInFrames, fadeStartFrames} is required (integers; the music phrase fades in, holds, fades out over the end card)');
    }
    if (!(tail.fadeInFrames <= tail.fadeStartFrames && tail.fadeStartFrames < endCardFrames)) {
      throw new Error(`episode text ending.endLogoTail must satisfy fadeInFrames <= fadeStartFrames < end card frames (${endCardFrames}); got ${tail.fadeInFrames}, ${tail.fadeStartFrames}`);
    }
    Object.assign(out, {tailFadeIn: tail.fadeInFrames, tailFadeStart: tail.fadeStartFrames});
  }
  return out;
}

function checkTailRecords(review, events) {
  const FIELDS = ['tail_output_frames', 'editorial_frames', 'native_frames', 'start_from_frame'];
  const byId = new Map(events.transitions.map((t) => [t.id, t]));
  for (const t of review.motion.transitions) {
    const ev = (byId.get(t.id) || {}).outgoing_tail;
    if (!t.outgoing_tail && !ev) continue;
    if (!ev) throw new Error(`${t.id}: the config has an outgoing_tail but the events record has no outgoing_tail`);
    if (!t.outgoing_tail) throw new Error(`${t.id}: the events record has an outgoing_tail but the config has no outgoing_tail`);
    for (const key of FIELDS) {
      if (ev[key] !== t.outgoing_tail[key]) throw new Error(`${t.id}: outgoing_tail.${key} ${t.outgoing_tail[key]} differs from the events record ${ev[key]}`);
    }
  }
  for (const [id, ev] of byId) {
    if (ev.outgoing_tail && !review.motion.transitions.some((t) => t.id === id)) throw new Error(`${id}: the events record has a transition the config lacks`);
  }
}

/**
 * @param {object} review review-config.json  @param {object} events events.json  (both from loadBuild)
 * @param {{bound:object, episodeRoot:string, episodeText:object, allowOutside?:string[], historicalWaivers?:object, label?:string, verifyHashes?:boolean}} opts
 */
function adaptEngine(review, events, opts = {}) {
  if (!isBound(opts.bound)) throw new Error('adaptEngine() needs a receipt-bound build: load the review config + events with loadBuild() (they are trusted only through the build receipt)');
  if (!opts.episodeRoot) throw new Error('adaptEngine() needs episodeRoot (the root every episode-relative path resolves against)');
  if (review.issues && review.issues.length) throw new Error(`review config has issues: ${review.issues.join('; ')}`);
  const text = opts.episodeText;
  requireText(text, review);
  const fps = review.fps;
  const brief = (t) => ({id: t.id, type: t.type, preset: t.preset, boundary: t.boundary, frames: t.frames, params: t.params, schedule: t.schedule, overlay: t.overlay});
  assertSame('transitions', review.motion.transitions.map(brief), events.transitions.map(brief));
  const E = review.motion.ending;
  for (const key of ['iris', 'music_bed', 'logo_disc_layout']) assertSame(`ending.${key}`, E[key], (events.ending || {})[key]);
  checkTailRecords(review, events);

  const files = makeResolver({episodeRoot: opts.episodeRoot, allowOutside: opts.allowOutside || [], verifyHashes: opts.verifyHashes !== false});
  const bind = (ref, what) => files.resolve(ref, what);
  const eventsById = new Map(events.transitions.map((t) => [t.id, t]));
  const introFrames = review.dialogue[0].start_frame;
  // timeline.outroStart is where the dialogue ends = the start of the outro block; a logo hold (derived timeline, ending.logo_hold_frames)
  // is the gap between it and card 1, so cards[0].start is the hold and every card start stays relative to the block
  const lastShot = review.dialogue[review.dialogue.length - 1];
  const outroStart = lastShot.start_frame + lastShot.duration_frames;
  if (review.outro_cards[0].start_frame < outroStart) throw new Error(`adapter-engine: card 1 starts at f${review.outro_cards[0].start_frame}, before the dialogue ends (f${outroStart})`);
  const mainFrames = review.main_frames;
  const endCardFrames = review.end_hold_frames || 0;
  const onset = onsetEvidence(review, opts.episodeRoot);

  const shots = review.dialogue.map((s) => {
    const words = s.words.map((w) => ({w: w.w, startF: w.startF, endF: w.endF, keyword: Boolean(w.keyword)}));
    const speechEnd = Math.max(...words.map((w) => w.endF));
    return {
      id: s.id, start: s.start_frame, frames: s.duration_frames, speechEndS: Math.round(((speechEnd - s.start_frame) / fps) * 1000) / 1000,
      vi: text.shotVi[s.id], captionLines: (text.captionLines || {})[s.id] || 1, words,
      segments: s.segments.map((g) => ({id: g.shot, from: g.start_frame - s.start_frame, frames: g.duration_frames})),
      ...(onset.frames[s.id] !== undefined ? {speechOnsetF: onset.frames[s.id], onsetEvidence: onset.label} : {}),
    };
  });

  const assets = text.assets;
  const bindings = {
    opening: assets.opening ? bind(assets.opening, 'assets.opening') : undefined,
    logo: bind(E.logo, 'ending.logo'),
    music: bind(assets.music, 'assets.music'),
    ambience: assets.ambience ? bind(assets.ambience, 'assets.ambience') : undefined,
    shots: {}, tails: {}, icons: {}, cards: [],
  };
  if (text.fonts) bindings.fonts = {regular: bind(text.fonts.regular, 'fonts.regular').path, bold: bind(text.fonts.bold, 'fonts.bold').path};
  for (const key of Object.keys(bindings)) if (bindings[key] === undefined) delete bindings[key];
  for (const s of review.dialogue) {
    bindings.shots[s.id] = {audio: bind(s.timing_audio, `dialogue ${s.id} audio`), segments: {}};
    for (const g of s.segments) bindings.shots[s.id].segments[g.shot] = bind(g.clip, `segment ${g.shot} clip`);
  }
  const tailFps = {};
  for (const t of review.motion.transitions) {
    if (!t.outgoing_tail) continue;
    const bound = bind({path: t.outgoing_tail.native_path, sha256: t.outgoing_tail.native_sha256}, `${t.id} tail clip`);
    bindings.tails[t.id] = bound;
    const probe = probeClip(bound.path);
    if (probe.frames !== t.outgoing_tail.native_frames) throw new Error(`${t.id}: the tail clip has ${probe.frames} frames, the engine recorded ${t.outgoing_tail.native_frames} (${bound.path})`);
    tailFps[t.id] = probe.nativeFps;
  }
  for (const ev of review.motion.icons) bindings.icons[ev.icon] = bind({path: ev.icon_path, sha256: ev.icon_sha256}, `icon ${ev.icon}`);
  for (const c of review.outro_cards) {
    bindings.cards.push({icon: bind(text.cards[c.term].icon, `cards.${c.term}.icon`), audio: bind(c.audio, `card ${c.term} audio`)});
  }

  const transitions = review.motion.transitions.map((t) => {
    const ev = eventsById.get(t.id) || {};
    const out = mapTransition(t, ev.continuity, ev.outgoing_tail);
    Object.assign(out, {preset: t.preset, renders_as: t.renders_as, params: t.params || {}});
    if (t.overlay) out.overlay = t.overlay;
    if (t.white_colour) out.whiteColour = t.white_colour;
    if (t.incoming_hidden_frames !== undefined) out.incomingHiddenFrames = t.incoming_hidden_frames;
    if (out.tail) out.tail = {...out.tail, nativeFps: tailFps[t.id]};
    return out;
  });

  const kit = {
    provenance: {
      build_receipt: opts.bound.receipt, config_sha256: opts.bound.config_sha256, events_sha256: opts.bound.events_sha256, unbound_assets: files.unbound,
    },
    schema: 'jjk-remotion-kit/config/v1',
    id: review.episode_id,
    fps,
    timeline: {introFrames, mainFrames, endCardFrames, outroStart, outroFrames: mainFrames - outroStart},
    review: {label: opts.label || (text.review && text.review.label) || review.label},
    strings: {cardsHeader: text.strings.cardsHeader, cardsHeaderClosing: text.strings.cardsHeaderClosing},
    ...(introFrames > 0 ? {intro: {...text.intro}} : {}),
    shots,
    transitions,
    icons: review.motion.icons.map((ev) => ({id: ev.id, shot: ev.shot, icon: ev.icon, frame: ev.frame, totalFrames: ev.total_frames, holdFrames: ev.hold_frames, fadeFrames: ev.fade_frames})),
    ending: endingFrom(E, text, fps, endCardFrames),
    cards: review.outro_cards.map((c) => ({
      term: c.term, ipa: text.cards[c.term].ipa, vi: text.cards[c.term].vi, exampleEn: text.cards[c.term].exampleEn, start: c.start_frame - outroStart, frames: c.duration_frames,
    })),
    bindings,
  };
  if (E.music_bed) {
    const bed = {};
    for (const [key, value] of Object.entries(E.music_bed)) bed[BED_KEYS[key]] = value;
    kit.music = {stemSeconds: Math.round(wavSeconds(bindings.music.path) * 1e6) / 1e6, bed};
  }
  if (opts.historicalWaivers) kit.waivers = historicalDipWaivers(kit, opts.historicalWaivers);
  return kit;
}

function runCli(args, {adapterFile = __filename, defaultEpisodeText} = {}) {
  const opt = (name, dflt) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : dflt;
  };
  const all = (name) => args.flatMap((a, i) => (a === name ? [path.resolve(args[i + 1])] : []));
  const need = (name, dflt) => {
    const v = opt(name, dflt);
    if (!v) throw new Error(`${name} is required`);
    return v;
  };
  const reviewPath = need('--review-config');
  const eventsPath = need('--events');
  const receiptPath = need('--receipt');
  const episodeRoot = path.resolve(need('--episode-root'));
  const textPath = need('--episode-text', defaultEpisodeText);
  const out = need('--out');
  const build = loadBuild({reviewConfig: reviewPath, events: eventsPath, receipt: receiptPath, episodeRoot});
  const config = adaptEngine(build.review, build.events, {
    bound: build.bound, episodeRoot, episodeText: readJson(textPath), allowOutside: all('--allow-outside'), label: opt('--label'), historicalWaivers: waiverOptions(args, opt),
  });
  config.provenance = {
    ...config.provenance,
    review_config: {path: reviewPath, sha256: build.bound.config_sha256},
    events: {path: eventsPath, sha256: build.bound.events_sha256},
    episode_text: {path: textPath, sha256: sha(textPath)},
    episode_root: episodeRoot,
    adapter: {path: adapterFile, sha256: sha(adapterFile)},
    ...(adapterFile !== __filename ? {adapter_lib: {path: __filename, sha256: sha(__filename)}} : {}),
  };
  fs.mkdirSync(path.dirname(path.resolve(out)), {recursive: true});
  fs.writeFileSync(out, `${JSON.stringify(config, null, 2)}
`);
  process.stdout.write(`kit config written: ${out}
`);
}

function cli(args, options) {
  try {
    runCli(args, options);
  } catch (error) {
    process.stderr.write(`adapter failed: ${error.message}
`);
    process.exitCode = 1;
  }
}

module.exports = {adaptEngine, loadBuild, runCli, cli};
if (require.main === module) cli(process.argv.slice(2));
