#!/usr/bin/env node
'use strict';
// Episode adapter: maps the ep04 review-hd-v008 build (review-config-v008.json + events-v008.json) onto the remotion-kit
// config schema (jjk-remotion-kit/config/v1). THIS file is the only place where ep04 numbers live (shot table, ending frames,
// pill position). The kit itself carries none. A new episode writes its own adapter, or builds the kit config directly.
//
//   node adapter-v008.cjs [--review-config F] [--events F] --out kit-config.json
//   const {adapt} = require('./adapter-v008.cjs');  adapt(reviewConfig, events) -> kit config (with .bindings)

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const WORKSPACE = path.resolve(__dirname, '../../../../../..');
const V008 = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial', 'review-hd-v008');

// ---- ep04 specifics that the v008 config only carries as prose or not at all -------------------------------------------
const SHOT_TABLE = { // the master clock (start frame, frames) every build must reproduce
  S01_A: [90, 150], S01_B: [240, 150], S02_A: [390, 160], S02_B: [550, 160], S03_A: [710, 175], S03_B: [885, 125],
  S04_A: [1010, 140], S04_B: [1150, 160], S05_A: [1310, 185], S05_B: [1495, 115], S06_A: [1610, 175], S06_B: [1785, 375],
};
const TWO_LINE_CAPTION_SHOTS = ['S06_B']; // the long closing line wraps to 2 English lines
const ENDING_EXTRA = {
  discSlideStart: 2152, // the full-size disc steps aside ...
  discSlideEnd: 2159,
  discSlideX: 520, // ... to this centre x: right edge 520 + 430 = 950 < the Creamy pill left edge
  pillLeftX: 988, // measured on the f2160 still (pill rect x >= 988)
  tailFromSeconds: 81.5, // music stem phrase replayed under the end card
};

const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
const bind = (b) => ({path: b.path, sha256: b.sha256});
const {loadBuild, isBound, mapTransition, canonicalType, historicalDipWaivers, waiverOptions} = require('../../lib/build-binding.cjs');

function assertSame(label, a, b) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`adapter: events-v008 and review-config disagree on ${label}`);
}

// First SPOKEN frame per shot from the word-timing document the review config names, when it carries the onset evidence
// (entries[*].onset_fix.new_start_frame: the first sustained / voiced onset measured on the bound WAV, not the unvoiced pre-roll).
// Absent (an older word timing) -> no evidence: the kit falls back to the caption start and says "caption-based".
function loadOnsetEvidence(review) {
  const none = {frames: {}, label: null};
  const ref = review.word_timing;
  // explicit refusals: a build that names no word timing, a file that is gone, or no recorded hash is NOT "no evidence"
  if (!ref || !ref.path) throw new Error('review config: word_timing is required (path + sha256 of the word-timing document)');
  if (!fs.existsSync(ref.path)) throw new Error(`review config: the word-timing file ${ref.path} is missing`);
  if (!ref.sha256) throw new Error('review config: word_timing.sha256 is required');
  if (sha(ref.path) !== ref.sha256) throw new Error(`word-timing file changed since the build (${ref.path})`);
  const doc = readJson(ref.path);
  const frames = {};
  for (const entry of doc.entries || []) {
    const f = entry.onset_fix && entry.onset_fix.new_start_frame;
    if (Number.isInteger(f)) frames[entry.id] = f;
  }
  return Object.keys(frames).length ? {frames, label: `${doc.schema} onset_fix, sha256 ${ref.sha256.slice(0, 12)}`} : none;
}

function adapt(review, events, opts = {}) {
  const bound = opts.bound;
  if (!isBound(bound)) {
    throw new Error('adapt() needs a receipt-bound build: load the review config + events with loadBuild() (they are trusted only through the build receipt)');
  }
  if (review.issues && review.issues.length) throw new Error(`review config has issues: ${review.issues.join('; ')}`);
  const fps = review.fps;
  // the events document is the authored source of the motion layer: it must agree with what the config embeds
  const brief = (t) => ({id: t.id, type: canonicalType(t.type), boundary: t.boundary, schedule: t.schedule});
  assertSame('transitions', review.motion.transitions.map(brief), events.transitions.map(brief));
  const eventsById = new Map(events.transitions.map((t) => [t.id, t]));
  // The tail numbers the kit trusts (start / editorial / native / verified frames) come from the build's events record (receipt-bound).
  // The config copy must agree field by field, and both must have (or both lack) a tail: a raised tail_output_frames in either file
  // would otherwise widen the number of tail frames the kit may play.
  const TAIL_FIELDS = ['tail_output_frames', 'editorial_frames', 'native_frames', 'start_from_frame'];
  for (const t of review.motion.transitions) {
    const ev = (eventsById.get(t.id) || {}).outgoing_tail;
    if (!t.outgoing_tail && !ev) continue;
    if (!ev) throw new Error(`${t.id}: the config has an outgoing_tail but the events record has no outgoing_tail`);
    if (!t.outgoing_tail) throw new Error(`${t.id}: the events record has an outgoing_tail but the config has no outgoing_tail`);
    for (const key of TAIL_FIELDS) {
      if (ev[key] !== t.outgoing_tail[key]) throw new Error(`${t.id}: outgoing_tail.${key} ${t.outgoing_tail[key]} differs from the events record ${ev[key]}`);
    }
  }
  for (const [id, ev] of eventsById) {
    if (ev.outgoing_tail && !review.motion.transitions.some((t) => t.id === id)) throw new Error(`${id}: the events record has a transition the config lacks`);
  }
  assertSame('iris', review.motion.ending.iris, events.ending.iris);

  const introFrames = review.dialogue[0].start_frame;
  const outroStart = review.outro_cards[0].start_frame;
  const mainFrames = review.total_frames;
  const E = review.motion.ending;
  const ending = {
    irisStart: E.iris.start,
    irisClosed: E.iris.closed,
    irisCentre: E.iris.centre,
    irisEndRadius: E.iris.end_radius,
    discIn: E.logo_disc.in,
    discFadeStart: E.logo_disc.fade_start,
    discFadeFrames: E.logo_disc.fade_frames,
    discSlideStart: ENDING_EXTRA.discSlideStart,
    discSlideEnd: ENDING_EXTRA.discSlideEnd,
    discSlideX: ENDING_EXTRA.discSlideX,
    pillLeftX: ENDING_EXTRA.pillLeftX,
    plateStart: E.end_plate.start,
    speechEndFrame: E.end_plate.ice_cream_speech_end_frame,
    plateEn: E.end_plate.text_en,
    plateVi: E.end_plate.text_vi,
    tailFrom: Math.round(ENDING_EXTRA.tailFromSeconds * fps),
  };

  const onset = loadOnsetEvidence(review);
  const shots = review.dialogue.map((s) => ({
    id: s.id,
    start: s.start_frame,
    frames: s.duration_frames,
    speechEndS: s.speech_end_in_window_s,
    vi: s.dialogue_vi,
    captionLines: TWO_LINE_CAPTION_SHOTS.includes(s.id) ? 2 : 1,
    words: s.words.map((w) => ({w: w.w, startF: w.startF, endF: w.endF, keyword: Boolean(w.keyword)})),
    segments: s.segments.map((g) => ({id: g.source_id, from: g.relative_start_frame, frames: g.delivery_frames})),
    ...(onset.frames[s.id] !== undefined ? {speechOnsetF: onset.frames[s.id], onsetEvidence: onset.label} : {}),
  }));

  const bindings = {
    opening: bind(review.opening),
    logo: bind(review.logo),
    music: bind(review.mix.music),
    ambience: bind(review.mix.ambience_foley),
    shots: {},
    tails: {},
    icons: {},
    cards: review.outro_cards.map((c) => ({icon: bind(c.icon), audio: bind(c.audio)})),
  };
  for (const s of review.dialogue) {
    bindings.shots[s.id] = {audio: bind(s.audio), segments: {}};
    for (const g of s.segments) bindings.shots[s.id].segments[g.source_id] = bind(g);
  }
  for (const t of review.motion.transitions) {
    if (t.outgoing_tail) bindings.tails[t.id] = {path: t.outgoing_tail.native_path, sha256: t.outgoing_tail.native_sha256};
  }
  for (const ev of review.motion.icons) bindings.icons[ev.icon] = {path: ev.icon_path, sha256: ev.icon_sha256};

  const kitConfig = {
    provenance: {build_receipt: bound.receipt, config_sha256: bound.config_sha256, events_sha256: bound.events_sha256},
    schema: 'jjk-remotion-kit/config/v1',
    id: review.episode_id,
    fps,
    timeline: {introFrames, mainFrames, endCardFrames: review.end_hold_frames || 0, outroStart, outroFrames: mainFrames - outroStart},
    review: {label: review.label},
    clock: {shotTable: SHOT_TABLE},
    strings: {cardsHeader: 'Bé cùng đọc nhé! · Say it with me!', cardsHeaderClosing: 'Hẹn gặp lại bé nhé! · See you next time!'},
    intro: {
      kicker: 'JENNIEJOY KIDS',
      titleLines: ['Milk', 'and Mom'],
      pill: 'Cùng bé khám phá thế giới sữa',
      footer: '12 từ vựng · 12 cuộc trò chuyện nhỏ',
      mark: 'drop',
    },
    shots,
    transitions: review.motion.transitions.map((t) => mapTransition(t, (eventsById.get(t.id) || {}).continuity, (eventsById.get(t.id) || {}).outgoing_tail)),
    icons: review.motion.icons.map((ev) => ({
      id: ev.id, shot: ev.shot, icon: ev.icon, frame: ev.frame, totalFrames: ev.total_frames, holdFrames: ev.hold_frames, fadeFrames: ev.fade_frames,
    })),
    ending,
    cards: review.outro_cards.map((c) => ({
      term: c.term, ipa: c.ipa, vi: c.vi, exampleEn: c.example_en, start: c.relative_start_frame, frames: c.duration_frames,
    })),
    bindings,
  };
  // The earliest build has its dip-to-white peak AFTER the first spoken word of the incoming shot (known defect). The kit refuses
  // that; reproducing such a build needs an explicit waiver per violating transition, governed by approval fields.
  if (opts.historicalWaivers) kitConfig.waivers = historicalDipWaivers(kitConfig, opts.historicalWaivers);
  return kitConfig;
}

function main() {
  const args = process.argv.slice(2);
  const opt = (name, dflt) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : dflt;
  };
  const reviewPath = opt('--review-config', path.join(V008, 'config', 'review-config-v008.json'));
  const eventsPath = opt('--events', path.join(V008, 'events-v008.json'));
  const receiptPath = opt('--receipt', path.join(V008, 'RECEIPT.json'));
  const out = opt('--out');
  if (!out) throw new Error('--out <kit-config.json> is required');
  const build = loadBuild({reviewConfig: reviewPath, events: eventsPath, receipt: receiptPath, episodeRoot: opt('--episode-root')});
  const config = adapt(build.review, build.events, {historicalWaivers: waiverOptions(args, opt), bound: build.bound});
  config.provenance = {
    ...config.provenance,
    review_config: {path: reviewPath, sha256: build.bound.config_sha256}, // the hashes of the VERIFIED bytes, not a re-read
    events: {path: eventsPath, sha256: build.bound.events_sha256},
    adapter: {path: __filename, sha256: sha(__filename)},
  };
  fs.mkdirSync(path.dirname(path.resolve(out)), {recursive: true});
  fs.writeFileSync(out, `${JSON.stringify(config, null, 2)}\n`);
  process.stdout.write(`kit config written: ${out}\n`);
}

module.exports = {adapt, loadBuild, SHOT_TABLE, waiverOptions, historicalDipWaivers, mapTransition, isBound};
if (require.main === module) {
  try {
    main();
  } catch (error) {
    process.stderr.write(`adapter failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}
