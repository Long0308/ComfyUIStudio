#!/usr/bin/env node
'use strict';
// Generic master adapter (config-driven). Builds the kit config of the 4K master from:
//   - the receipt-bound review build (review config + events + receipt, read through lib/build-binding.cjs loadBuild),
//   - the master config (4K picture sources, 4K tails with receipts, master_contract),
//   - the episode text (intro and strings, caption line counts, ending numbers the build does not record, tail fade numbers).
// Every number comes from those files: no episode name, no literal frame count, no per-episode table. The kit output is the same
// shape the shared compositor reads (jjk-remotion-kit/config/v1), with the 4K bindings and the receipt checks of the master.
//
//   node lib/adapter-master.cjs --review-config F --events F --receipt F --episode-root DIR --episode-text F --master-config F
//        [--allow-outside P]... [--waive-historical-dip ...] [--preview] --out kit-master.json
//   const {adaptMasterKit} = require('./adapter-master.cjs');  adaptMasterKit(build, master, {episodeText, preview}) -> kit config
//
// Refuses unless master_ready === true and nothing is missing, EXCEPT with --preview (the explicit opt-in for stills / ranges).
// The kit says which it is: kit.mode === 'final' (every picture and tail bound to a receipt, nothing preview) or 'preview'. The renderer
// (render.cjs) refuses a 'preview' kit for a master render.
// Two input schemas, detected from the review config: the receipt-bound hand-built review build (review.total_frames), and the ENGINE's own
// build-config output (review.main_frames: `jjv editorial build-config`, receipt = its summary). The engine review side is mapped by
// lib/adapter-engine.cjs (its episode text: shotVi, cards, assets, ending.endLogoTail...); the 4K side is read from the master config,
// which `jjv edit master-config` produces from that same build. Both need --episode-text with a captionLines entry for every shot.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {loadBuild, isBound, mapTransition, canonicalType, historicalDipWaivers, waiverOptions} = require('./build-binding.cjs');
const {checkSegmentFile, checkTailFile} = require('./tailcheck.cjs');
const {verifyReceipt} = require('./receipts.cjs');

const FINAL_KINDS = new Set(['shot-final-4k', 'seam-variant-hf8']);

const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
const isStr = (v) => typeof v === 'string' && v.length > 0;
const isInt = (v) => Number.isInteger(v);

function need(value, what) {
  if (value === undefined || value === null) throw new Error(`${what} is required`);
  return value;
}

// ---- the episode text: every value the build does not carry ---------------------------------------------------------------
function requireText(text, review) {
  if (!text || typeof text !== 'object') throw new Error('episode text is required (intro, strings, caption lines, ending numbers)');
  if (!text.strings || !isStr(text.strings.cardsHeader) || !isStr(text.strings.cardsHeaderClosing)) throw new Error('episode text strings.cardsHeader and strings.cardsHeaderClosing are required');
  if (!text.intro || !isStr(text.intro.kicker) || !isStr(text.intro.pill) || !isStr(text.intro.footer) || !Array.isArray(text.intro.titleLines) || !text.intro.titleLines.length) {
    throw new Error('episode text intro {kicker, titleLines, pill, footer, mark} is required');
  }
  const E = review.motion.ending;
  if (!E || !E.iris || !E.logo_disc || !E.end_plate) throw new Error('review build: motion.ending needs iris, logo_disc and end_plate');
  const ending = text.ending;
  if (!ending) throw new Error('episode text ending {tailFromSeconds, discSlideStart, discSlideEnd, discSlideX, pillLeftX} is required');
  for (const key of ['discSlideStart', 'discSlideEnd', 'discSlideX', 'pillLeftX']) {
    if (!isInt(ending[key])) throw new Error(`episode text ending.${key} must be an integer`);
  }
  if (!(ending.tailFromSeconds >= 0)) throw new Error('episode text ending.tailFromSeconds is required (the music phrase replayed under the end card)');
  for (const s of review.dialogue) {
    if (!isStr(s.dialogue_vi)) throw new Error(`review build: ${s.id} has no dialogue_vi`);
  }
  for (const c of review.outro_cards) {
    if (!isStr(c.ipa) || !isStr(c.vi) || !isStr(c.example_en)) throw new Error(`review build: card ${c.term} needs ipa, vi and example_en`);
  }
}

// every shot names its caption line count (no silent default of 1: a wrong count wraps or clips the caption)
function requireCaptionLines(text, review) {
  const lines = text && text.captionLines;
  if (!lines || typeof lines !== 'object') throw new Error('episode text captionLines is required: one integer line count (>= 1) per shot');
  for (const s of review.dialogue) {
    if (!isInt(lines[s.id]) || lines[s.id] < 1) throw new Error(`episode text captionLines.${s.id} is required (an integer >= 1)`);
  }
}

const isEngineReview = (review) => review.main_frames !== undefined || String(review.schema || '').startsWith('jjv/review-config/');

// the engine schema: the review side of the master is the engine review kit (adapter-engine), minus the review label
function engineReviewKit(build, text, opts) {
  if (!opts.episodeRoot) throw new Error('the engine build-config schema needs episodeRoot (the root its episode-relative paths resolve against)');
  const {adaptEngine} = require('./adapter-engine.cjs');
  const kit = adaptEngine(build.review, build.events, {
    bound: build.bound, episodeRoot: opts.episodeRoot, episodeText: text, allowOutside: opts.allowOutside || [], historicalWaivers: opts.historicalWaivers,
  });
  kit.clock = {shotTable: Object.fromEntries(build.review.dialogue.map((s) => [s.id, [s.start_frame, s.duration_frames]]))};
  return kit;
}

// first SPOKEN frame per shot from the word-timing document the build names (entries[*].onset_fix.new_start_frame)
function loadOnsetEvidence(review, episodeRoot) {
  const none = {frames: {}, label: null};
  const ref = review.word_timing;
  if (!ref || !ref.path) throw new Error('review config: word_timing is required (path + sha256 of the word-timing document)');
  if (!path.isAbsolute(ref.path) && !episodeRoot) throw new Error(`word_timing.path ${ref.path} is relative: pass episodeRoot`);
  const file = path.isAbsolute(ref.path) ? ref.path : path.resolve(episodeRoot, ref.path);
  if (!fs.existsSync(file)) throw new Error(`review config: the word-timing file ${file} is missing`);
  if (!ref.sha256) throw new Error('review config: word_timing.sha256 is required');
  if (sha(file) !== ref.sha256) throw new Error(`word-timing file changed since the build (${file})`);
  const doc = readJson(file);
  const frames = {};
  for (const entry of doc.entries || []) {
    const f = entry.onset_fix && entry.onset_fix.new_start_frame;
    if (isInt(f)) frames[entry.id] = f;
  }
  return Object.keys(frames).length ? {frames, label: `${doc.schema} onset_fix, sha256 ${ref.sha256.slice(0, 12)}`} : none;
}

// ---- the review kit (the picture-free part of the master), built from the build + the episode text ---------------------
function reviewKitFromBuild(build, text, opts = {}) {
  const {review, events, bound} = build;
  if (!isBound(bound)) throw new Error('adaptMasterKit needs a receipt-bound build: load the review config + events with loadBuild()');
  if (review.issues && review.issues.length) throw new Error(`review config has issues: ${review.issues.join('; ')}`);
  if (isEngineReview(review)) throw new Error('reviewKitFromBuild maps the hand-built schema; adaptMasterKit routes the engine schema through adapter-engine');
  const fps = need(review.fps, 'review config fps');
  const brief = (t) => ({id: t.id, type: canonicalType(t.type), boundary: t.boundary, schedule: t.schedule});
  if (JSON.stringify(review.motion.transitions.map(brief)) !== JSON.stringify(events.transitions.map(brief))) {
    throw new Error('adapter: events and review-config disagree on transitions');
  }
  const eventsById = new Map(events.transitions.map((t) => [t.id, t]));
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
  if (JSON.stringify(review.motion.ending.iris) !== JSON.stringify(events.ending.iris)) throw new Error('adapter: events and review-config disagree on the iris');

  const E = review.motion.ending;
  const T = text.ending;
  const ending = {
    irisStart: E.iris.start,
    irisClosed: E.iris.closed,
    irisCentre: E.iris.centre,
    irisEndRadius: E.iris.end_radius,
    discIn: E.logo_disc.in,
    discFadeStart: E.logo_disc.fade_start,
    discFadeFrames: E.logo_disc.fade_frames,
    discSlideStart: T.discSlideStart,
    discSlideEnd: T.discSlideEnd,
    discSlideX: T.discSlideX,
    pillLeftX: T.pillLeftX,
    plateStart: E.end_plate.start,
    speechEndFrame: E.end_plate.ice_cream_speech_end_frame,
    plateEn: E.end_plate.text_en,
    plateVi: E.end_plate.text_vi,
    tailFrom: Math.round(T.tailFromSeconds * fps),
  };

  // caption line counts, shot clock table: from the build and the text, never from a table in this file
  const onset = loadOnsetEvidence(review, opts.episodeRoot);
  const captionLines = text.captionLines || {};
  const shots = review.dialogue.map((s) => ({
    id: s.id,
    start: s.start_frame,
    frames: s.duration_frames,
    speechEndS: s.speech_end_in_window_s,
    vi: s.dialogue_vi,
    captionLines: captionLines[s.id],
    words: s.words.map((w) => ({w: w.w, startF: w.startF, endF: w.endF, keyword: Boolean(w.keyword)})),
    segments: s.segments.map((g) => ({id: g.source_id, from: g.relative_start_frame, frames: g.delivery_frames})),
    ...(onset.frames[s.id] !== undefined ? {speechOnsetF: onset.frames[s.id], onsetEvidence: onset.label} : {}),
  }));

  const bind = (b) => ({path: b.path, sha256: b.sha256});
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

  const introFrames = review.dialogue[0].start_frame;
  const outroStart = review.outro_cards[0].start_frame;
  const mainFrames = review.total_frames;
  const kit = {
    provenance: {build_receipt: bound.receipt, config_sha256: bound.config_sha256, events_sha256: bound.events_sha256},
    schema: 'jjk-remotion-kit/config/v1',
    id: review.episode_id,
    fps,
    timeline: {introFrames, mainFrames, endCardFrames: review.end_hold_frames || 0, outroStart, outroFrames: mainFrames - outroStart},
    review: {label: review.label},
    clock: {shotTable: Object.fromEntries(review.dialogue.map((s) => [s.id, [s.start_frame, s.duration_frames]]))},
    strings: {cardsHeader: text.strings.cardsHeader, cardsHeaderClosing: text.strings.cardsHeaderClosing},
    intro: {...text.intro},
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
  if (opts.historicalWaivers) kit.waivers = historicalDipWaivers(kit, opts.historicalWaivers);
  return kit;
}

// ---- the picture side of the master -------------------------------------------------------------------------------------
const parseRate = (text) => {
  const [n, d] = String(text).split('/').map(Number);
  return d ? n / d : n;
};

function firstNativeIndex(source) {
  if (!isInt(source.first_native_index) || !isInt(source.native_editorial_frames) || !isInt(source.native_total_frames)) {
    throw new Error(`tail ${source.transition_id}: tail_source lacks first_native_index / native_editorial_frames / native_total_frames`);
  }
  return source.first_native_index;
}

// A "final" label is only a label: a final clip is bound to the receipt that attests its sha256 (content checked here and in stage())
function finalReceipt(segment, kind) {
  const id = segment.source_id;
  const restored = segment.restored || {};
  if (kind === 'shot-final-4k') {
    if (restored.final_sha256 !== segment.sha256 || restored.final_path !== segment.path) throw new Error(`${id}: final path / sha256 differ from the restored evidence (a relabelled source?)`);
    const file = path.join(path.dirname(segment.path), 'shot.json');
    const v = verifyReceipt({kind: 'shot', path: file, clipPath: segment.path, clipSha: segment.sha256, label: id});
    return {kind: 'shot', path: file, ...v};
  }
  const evidence = restored.variant_evidence || {};
  if (!evidence.receipt_path || !evidence.receipt_sha256) throw new Error(`${id}: ${kind} has no seam-blend receipt evidence`);
  const v = verifyReceipt({kind: 'seam', path: evidence.receipt_path, clipPath: segment.path, clipSha: segment.sha256, label: id});
  if (v.sha256 !== evidence.receipt_sha256) throw new Error(`${id}: seam-blend receipt hash differs from the evidence`);
  return {kind: 'seam', path: evidence.receipt_path, ...v};
}

function tailReceipt(transitionId, source) {
  if (!source.receipt) throw new Error(`tail ${transitionId}: a final tail core needs its receipt path (tail_source.receipt)`);
  const v = verifyReceipt({kind: 'tail', path: source.receipt, clipPath: source.path, clipSha: source.sha256, transition: transitionId, label: `tail ${transitionId}`});
  return {kind: 'tail', path: source.receipt, transition: transitionId, ...v};
}

function pictureBinding(segment) {
  const kind = segment.source_kind || (segment.restored && segment.restored.source_kind);
  if (!segment.available || !segment.path) throw new Error(`master source unavailable: ${segment.source_id}`);
  const preview = !FINAL_KINDS.has(kind);
  const out = {path: segment.path, sha256: segment.sha256, preview, kind};
  if (kind === 'ffconcat-preview') {
    const cache = segment.preview_materialized;
    if (!cache || !cache.path) throw new Error(`preview cache missing for ${segment.source_id}`);
    out.materialized = {path: cache.path, sha256: cache.sha256};
  }
  if (!preview) out.receipt = finalReceipt(segment, kind);
  return out;
}

// The master: same keys, same clock, same receipts as the review build. preview = explicit opt-in for stills / ranges.
function adaptMasterKit(build, master, opts = {}) {
  const {preview = false} = opts;
  const text = opts.episodeText;
  if (!preview) {
    if (master.master_ready !== true) throw new Error(`master config is not ready (master_ready=${master.master_ready}, status=${master.status}); pass preview for stills / ranges`);
    if ((master.missing_shots || []).length) throw new Error(`master config has missing shots: ${master.missing_shots.join(', ')}`);
    if ((master.missing_tails || []).length) throw new Error(`master config has missing 4K tails: ${master.missing_tails.join(', ')}`);
    if (master.build_mode === 'preview') throw new Error('master config build_mode is "preview" (written by the producer with --preview): a final master needs a config built without it');
  }
  const engine = isEngineReview(build.review);
  if (!engine) requireText(text, build.review);
  requireCaptionLines(text, build.review);
  const kit = engine ? engineReviewKit(build, text, opts) : reviewKitFromBuild(build, text, {historicalWaivers: opts.historicalWaivers, episodeRoot: opts.episodeRoot});
  delete kit.review; // the master has no on-screen label and its clock must equal the review clock
  const c = need(master.master_contract, 'master config master_contract');
  if (c.main_frames !== kit.timeline.mainFrames || c.end_card_frames !== kit.timeline.endCardFrames) throw new Error('master contract clock differs from the review clock');

  const clock = [];
  for (const m of master.dialogue) {
    const k = kit.shots.find((x) => x.id === m.id);
    if (!k) continue;
    if (m.start_frame !== k.start) clock.push(`${m.id} start_frame ${m.start_frame} != ${k.start}`);
    if (m.duration_frames !== k.frames) clock.push(`${m.id} duration_frames ${m.duration_frames} != ${k.frames}`);
    for (const g of m.segments) {
      const ks = k.segments.find((x) => x.id === g.source_id);
      if (!ks) continue;
      if (g.delivery_frames !== ks.frames) clock.push(`${m.id}/${g.source_id} delivery_frames ${g.delivery_frames} != ${ks.frames}`);
      if (g.relative_start_frame !== ks.from) clock.push(`${m.id}/${g.source_id} relative_start_frame ${g.relative_start_frame} != ${ks.from}`);
    }
  }
  for (const m of master.motion.transitions) {
    const k = kit.transitions.find((x) => x.id === m.id);
    if (!k) clock.push(`transition ${m.id} is not in the kit config`);
    else if (m.boundary !== k.boundary) clock.push(`transition ${m.id} boundary ${m.boundary} != ${k.boundary}`);
  }
  for (const k of kit.transitions) {
    if (!master.motion.transitions.some((m) => m.id === k.id)) clock.push(`transition ${k.id} is missing from the master`);
  }
  if (clock.length) throw new Error(`master clock differs from the kit config: ${clock.join('; ')}`);

  const keysOf = (pairs) => pairs.slice().sort().join(', ');
  const kitSegs = Object.entries(kit.bindings.shots).flatMap(([id, s]) => Object.keys(s.segments).map((k) => `${id}/${k}`));
  const masterSegs = master.dialogue.flatMap((s) => s.segments.map((g) => `${s.id}/${g.source_id}`));
  if (keysOf(kitSegs) !== keysOf(masterSegs)) {
    const missing = kitSegs.filter((k) => !masterSegs.includes(k));
    const extra = masterSegs.filter((k) => !kitSegs.includes(k));
    throw new Error(`master picture keys differ from the kit config: missing [${missing.join(', ')}] extra [${extra.join(', ')}]`);
  }
  const kitTailKeys = Object.keys(kit.bindings.tails);
  const masterTailKeys = master.motion.transitions.filter((t) => t.outgoing_tail).map((t) => t.id);
  if (keysOf(kitTailKeys) !== keysOf(masterTailKeys)) {
    throw new Error(`master tail keys [${masterTailKeys.join(', ')}] differ from the kit config [${kitTailKeys.join(', ')}]`);
  }
  for (const shot of master.dialogue) {
    for (const seg of shot.segments) kit.bindings.shots[shot.id].segments[seg.source_id] = pictureBinding(seg);
  }
  const reviewTails = kit.transitions.filter((t) => t.tail).map((t) => t.id).sort().join();
  const masterTails = master.motion.transitions.filter((t) => t.outgoing_tail).map((t) => t.id).sort().join();
  if (reviewTails !== masterTails) throw new Error(`tail transitions differ: review [${reviewTails}] vs master [${masterTails}]`);
  const nativeFpsText = c.native_restored_fps;
  for (const t of master.motion.transitions) {
    if (!t.outgoing_tail) continue;
    const s = t.tail_source;
    if (!s || !s.path) throw new Error(`no tail source for ${t.id}`);
    const ev = (build.events.transitions.find((x) => x.id === t.id) || {}).outgoing_tail;
    if (!ev) throw new Error(`${t.id}: the events record has no outgoing_tail`);
    for (const [masterKey, eventKey] of [['tail_output_frames', 'tail_output_frames'], ['editorial_frames', 'editorial_frames'], ['native_frames', 'native_frames'], ['review_start_from_frame', 'start_from_frame']]) {
      if (t.outgoing_tail[masterKey] !== ev[eventKey]) throw new Error(`${t.id}: master outgoing_tail.${masterKey} ${t.outgoing_tail[masterKey]} differs from the events record ${ev[eventKey]}`);
    }
    const tailPreview = s.kind !== 'tail-core-4k' || Boolean(s.preview_only_tail);
    kit.bindings.tails[t.id] = {path: s.path, sha256: s.sha256, preview: tailPreview, kind: s.kind, ...(tailPreview ? {} : {receipt: tailReceipt(t.id, s)})};
    if (!nativeFpsText) throw new Error('master_contract.native_restored_fps is required (no default is assumed)');
    const nativeFps = parseRate(nativeFpsText);
    const first = firstNativeIndex(s);
    const editorialInFile = s.native_editorial_frames - first;
    const sf = t.outgoing_tail.start_from_frame;
    if (!isInt(sf) || sf < 0) throw new Error(`master transition ${t.id} has no integer outgoing_tail.start_from_frame`);
    const expectStart = (editorialInFile * kit.fps) / nativeFps;
    if (Math.abs(expectStart - sf) > 1e-9) throw new Error(`master transition ${t.id}: start_from_frame ${sf} does not match (native_editorial_frames - first_native_index) * fps / nativeFps = ${expectStart}`);
    kit.transitions.find((x) => x.id === t.id).tail = {startFrom: sf, editorialFrames: editorialInFile, fileFrames: s.native_total_frames - first, verifiedFrames: ev.tail_output_frames};
  }
  if (!preview) {
    // a final master binds nothing that is a preview: every picture and every tail is a receipt-bound final
    const previews = [
      ...Object.entries(kit.bindings.shots).flatMap(([id, s]) => Object.entries(s.segments).filter(([, b]) => b.preview).map(([k]) => `${id}/${k}`)),
      ...Object.entries(kit.bindings.tails).filter(([, b]) => b.preview).map(([id]) => `tail ${id}`),
    ];
    if (previews.length) throw new Error(`a final master cannot bind a preview source: ${previews.join(', ')} (pass preview for stills / ranges)`);
  }
  kit.mode = preview ? 'preview' : 'final';
  return kit;
}

// Probes every bound tail file (frame count, native fps) and checks it holds the frames the transition plays.
async function verifyTails(kit, {probe} = {}) {
  const {tailWindow} = await import(pathToFileURL(path.join(__dirname, '..', 'src', 'picture-mode.mjs')).href);
  const results = [];
  for (const t of kit.transitions) {
    const w = tailWindow(t);
    if (!w) continue;
    const b = kit.bindings.tails[t.id];
    const file = (b.materialized || b).path;
    results.push({transition: t.id, ...checkTailFile(file, {fps: kit.fps, startFrom: t.tail.startFrom, n: w.frames, editorialFrames: t.tail.editorialFrames, fileFrames: t.tail.fileFrames, label: t.id, ...(probe ? {probe} : {})})});
  }
  return results;
}

// Probes every bound picture clip: final sources strictly, preview-only ones are reported, not refused.
function verifyPictures(kit, {probe} = {}) {
  const out = [];
  for (const shot of kit.shots) {
    for (const seg of shot.segments) {
      const b = kit.bindings.shots[shot.id].segments[seg.id];
      out.push({segment: `${shot.id}/${seg.id}`, preview: Boolean(b.preview),
        ...checkSegmentFile((b.materialized || b).path, {fps: kit.fps, frames: seg.frames, label: `${shot.id}/${seg.id}`, strict: !b.preview, ...(probe ? {probe} : {})})});
    }
  }
  return out;
}

function readInputs(args) {
  const opt = (name) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : undefined;
  };
  const inputs = {
    reviewPath: need(opt('--review-config'), '--review-config'),
    eventsPath: need(opt('--events'), '--events'),
    receiptPath: need(opt('--receipt'), '--receipt'),
    masterPath: need(opt('--master-config'), '--master-config'),
    textPath: need(opt('--episode-text'), '--episode-text'),
    out: need(opt('--out'), '--out'),
    episodeRoot: opt('--episode-root') ? path.resolve(opt('--episode-root')) : undefined,
    allowOutside: args.flatMap((a, i) => (a === '--allow-outside' ? [path.resolve(args[i + 1])] : [])),
    preview: args.includes('--preview'),
  };
  inputs.build = loadBuild({reviewConfig: inputs.reviewPath, events: inputs.eventsPath, receipt: inputs.receiptPath, episodeRoot: inputs.episodeRoot});
  inputs.episodeText = readJson(inputs.textPath);
  inputs.master = readJson(inputs.masterPath);
  inputs.historicalWaivers = waiverOptions(args, opt);
  return inputs;
}

async function cli(args) {
  const x = readInputs(args);
  const kit = adaptMasterKit(x.build, x.master, {preview: x.preview, episodeText: x.episodeText, episodeRoot: x.episodeRoot, allowOutside: x.allowOutside, historicalWaivers: x.historicalWaivers});
  // a real master config: every bound picture clip is probed (strictly for final sources) and every tail is probed against its window
  const probes = {pictures: x.preview ? null : verifyPictures(kit), tails: await verifyTails(kit)};
  kit.provenance = {
    ...kit.provenance,
    master_config: {path: x.masterPath, sha256: sha(x.masterPath)},
    review_config: {path: x.reviewPath, sha256: x.build.bound.config_sha256},
    events: {path: x.eventsPath, sha256: x.build.bound.events_sha256},
    episode_text: {path: x.textPath, sha256: sha(x.textPath)},
    probes,
    adapter: {path: __filename, sha256: sha(__filename)},
  };
  fs.mkdirSync(path.dirname(path.resolve(x.out)), {recursive: true});
  fs.writeFileSync(x.out, `${JSON.stringify(kit, null, 2)}
`);
  process.stdout.write(`kit master config written: ${x.out}
`);
}

module.exports = {adaptMasterKit, reviewKitFromBuild, verifyTails, verifyPictures, finalReceipt, tailReceipt};
if (require.main === module) {
  cli(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`master adapter failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
