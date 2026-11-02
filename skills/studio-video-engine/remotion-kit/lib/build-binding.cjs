'use strict';
// Build binding shared by every adapter: the review config + events a build wrote are trusted only through the build's receipt
// (a hand-built RECEIPT.json or the summary `jjv editorial build-config` prints), plus the pieces every adapter needs when it maps a
// build's transitions onto the kit config. Episode-neutral: it names no episode, shot or frame.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// an older build used kebab / short type names; the kit and the engine use the canonical snake_case vocabulary
const TYPE_ALIASES = {dip: 'dip_white', 'card-slide': 'card_slide', 'plate-in': 'plate_in'};
const canonicalType = (type) => TYPE_ALIASES[type] || type;

function mapTransition(t, continuity, eventTail) {
  const out = {
    id: t.id, type: canonicalType(t.type), boundary: t.boundary, from: t.from, to: t.to, frames: t.frames, direction: t.direction, start: t.start,
  };
  if (t.out_frames !== undefined) out.outFrames = t.out_frames;
  if (t.in_frames !== undefined) out.inFrames = t.in_frames;
  if (t.schedule) out.schedule = t.schedule.map((e) => ({t: e.t, shot: e.shot, white: e.white}));
  if (t.curve) out.curve = t.curve;
  if (t.seed !== undefined) out.seed = t.seed;
  // tail numbers are read from the build's events record (receipt-bound); adapt() has already proven the config copy equal to it
  if (eventTail) out.tail = {startFrom: eventTail.start_from_frame, editorialFrames: eventTail.editorial_frames, fileFrames: eventTail.native_frames, verifiedFrames: eventTail.tail_output_frames};
  // continuity comes from the events document when it declares one (engine-built events do); v008 events do not
  if (continuity !== undefined) out.continuity = continuity;
  if (t.shows_both !== undefined) out.shows_both = t.shows_both;
  return out;
}

// ---- the build is bound to its receipt ------------------------------------------------------------------------------------------
// events-*.json is a BUILD artifact (the build script computes the tail numbers itself), not trusted engine output, and a pair of
// config + events can be edited consistently. The kit therefore trusts them only through the build's RECEIPT.json (or the summary an
// engine `jjv editorial build-config` run prints): the receipt records the sha256 of the review config and of the events file, and
// loadBuild() refuses unless the bytes on disk match. Each file is read ONCE (hash and parse come from the same bytes).
function readOnce(file, what) {
  if (!file || !fs.existsSync(file)) throw new Error(`${what} ${file} is missing`);
  const bytes = fs.readFileSync(file);
  return {bytes, sha256: crypto.createHash('sha256').update(bytes).digest('hex')};
}

function parseJson(bytes, file, what) {
  try {
    return JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/u, ''));
  } catch (error) {
    throw new Error(`${what} ${file} is not JSON (${error.message.split('\n')[0]})`);
  }
}

// The tokens loadBuild() hands out. A module-private set: only an object registered here passes adapt(), so a hand-built
// {receipt, config_sha256, events_sha256} (or a copy / clone of a real token) is refused.
const BOUND_TOKENS = new WeakSet();

const SHA_HEX = /^[0-9a-f]{64}$/;

// Two receipt shapes:
//   build receipt (RECEIPT.json of a hand-built review build): config.sha256, events.sha256 AND word_timing.sha256 (all three required)
//   engine build summary (stdout of `jjv editorial build-config`, engine/editorial/cli.py): {ok, ..., outputs: {'review-config.json':
//   {path, sha256, bytes, written}, 'events.json': {...}}}. The engine summary has no word-timing key, so the word-timing document is
//   checked against the config's own word_timing.sha256 and the file (see loadBuild).
function receiptHashes(doc, receipt) {
  if (doc && doc.config && doc.config.sha256 && doc.events && doc.events.sha256) {
    if (!doc.word_timing || !SHA_HEX.test(String(doc.word_timing.sha256 || ''))) throw new Error(`receipt ${receipt} has no word_timing.sha256 (a build receipt must bind the word timing too)`);
    return {kind: 'build-receipt', config: doc.config.sha256, events: doc.events.sha256, wordTiming: doc.word_timing.sha256};
  }
  const out = doc && doc.ok === true && doc.outputs;
  if (out && out['review-config.json'] && out['review-config.json'].sha256 && out['events.json'] && out['events.json'].sha256) {
    return {kind: 'engine-build-summary', config: out['review-config.json'].sha256, events: out['events.json'].sha256};
  }
  throw new Error('the receipt is not a build receipt (needs config.sha256 + events.sha256 + word_timing.sha256, or the engine build summary: ok + outputs[review-config.json | events.json].sha256)');
}

function loadBuild({reviewConfig, events, receipt, episodeRoot}) {
  const cfgFile = readOnce(reviewConfig, 'review config');
  const evFile = readOnce(events, 'events file');
  const rcFile = readOnce(receipt, 'receipt');
  let rcDoc;
  try {
    rcDoc = JSON.parse(rcFile.bytes.toString('utf8').replace(/^\uFEFF/u, ''));
  } catch (error) {
    throw new Error(`receipt ${receipt} is not JSON (${error.message.split('\n')[0]})`);
  }
  const expected = receiptHashes(rcDoc, receipt);
  if (evFile.sha256 !== expected.events) throw new Error(`events file sha256 ${evFile.sha256} differs from the receipt ${expected.events} (${events})`);
  if (cfgFile.sha256 !== expected.config) throw new Error(`review config sha256 ${cfgFile.sha256} differs from the receipt ${expected.config} (${reviewConfig})`);
  const review = parseJson(cfgFile.bytes, reviewConfig, 'review config');
  const wt = review.word_timing;
  if (!wt || !SHA_HEX.test(String(wt.sha256 || ''))) throw new Error('review config has no word_timing.sha256');
  if (expected.kind === 'build-receipt') {
    if (wt.sha256 !== expected.wordTiming) throw new Error(`word_timing sha256 ${wt.sha256} named by the review config differs from the receipt ${expected.wordTiming}`);
  } else {
    // engine summary: no word-timing key, so check the word-timing document itself against the hash the config names
    if (!wt.path) throw new Error('review config has no word_timing.path');
    if (!path.isAbsolute(wt.path) && !episodeRoot) throw new Error(`word_timing.path ${wt.path} is relative: pass episodeRoot (the episode root the engine resolved it against)`);
    const wtFile = path.isAbsolute(wt.path) ? wt.path : path.resolve(episodeRoot, wt.path);
    const wtBytes = readOnce(wtFile, 'word-timing file');
    if (wtBytes.sha256 !== wt.sha256) throw new Error(`word-timing file sha256 ${wtBytes.sha256} differs from the config's word_timing.sha256 ${wt.sha256} (${wtFile})`);
  }
  const bound = Object.freeze({
    receipt: Object.freeze({path: receipt, sha256: rcFile.sha256, kind: expected.kind}), config_sha256: cfgFile.sha256, events_sha256: evFile.sha256,
  });
  BOUND_TOKENS.add(bound);
  return {review, events: parseJson(evFile.bytes, events, 'events file'), bound};
}

// opts.historicalWaivers = {approved_by, approved_at, review_render_sha256}: EXPLICIT opt-in to reproduce a build whose dip-to-white
// peak is late (a known defect). Without it the config is refused by the kit. The approval fields are not invented here: the
// caller must supply them (a waiver without all of them is an issue).
function historicalDipWaivers(kit, approval) {
  const waivers = [];
  for (const t of kit.transitions.filter((x) => x.type === 'dip_white')) {
    const peak = t.schedule.find((e) => e.white === 1);
    const target = kit.shots.find((s) => s.id === t.to || s.segments[0].id === t.to);
    const firstWord = Number.isInteger(target.speechOnsetF) ? target.speechOnsetF : Math.min(...target.words.map((w) => w.startF));
    if (t.boundary + peak.t >= firstWord) {
      waivers.push({
        rule: 'dip_peak_before_first_word', transition: t.id,
        reason: `historical reproduction: peak f${t.boundary + peak.t} vs first spoken frame f${firstWord} (known defect, hid the first spoken frames)`,
        review_render_sha256: approval.review_render_sha256,
        ...(approval.reproduction_only ? {reproduction_only: true} : {approved_by: approval.approved_by, approved_at: approval.approved_at}),
      });
    }
  }
  return waivers;
}

// --waive-historical-dip (--waiver-approved-by NAME --waiver-approved-at YYYY-MM-DD | --waiver-reproduction-only) (--waiver-render-sha256 HEX | --waiver-render FILE)
function waiverOptions(args, opt) {
  if (!args.includes('--waive-historical-dip')) return undefined;
  const render = opt('--waiver-render');
  const review_render_sha256 = opt('--waiver-render-sha256') || (render ? sha(render) : undefined);
  // --waiver-reproduction-only: a parity / reproduction run states that it is NOT an approval (no approved_by / approved_at is invented)
  if (args.includes('--waiver-reproduction-only')) return {reproduction_only: true, review_render_sha256};
  return {approved_by: opt('--waiver-approved-by'), approved_at: opt('--waiver-approved-at'), review_render_sha256};
}

const isBound = (bound) => Boolean(bound) && BOUND_TOKENS.has(bound); // for adapters that map a build shape of their own

module.exports = {loadBuild, isBound, mapTransition, canonicalType, historicalDipWaivers, waiverOptions};
