#!/usr/bin/env node
'use strict';
// ep04 4K master adapter: the SAME kit config as the review cut (adapter-v008.cjs) with the picture bindings swapped for the
// master-4k config's sources. Review and master therefore share one clock, one caption/icon/transition/ending set; the only
// differences are the bindings (4K sources) and the deliverable (scale 2, no label).
//
//   node adapter-master-v002.cjs [--master-config F] [--review-config F] [--events F] [--preview] --out kit-config-master.json
//   Refuses unless master_ready === true and missing_shots / missing_tails are empty; --preview is the explicit opt-in for stills.
//
// Master-config source kinds: ffconcat-preview (materialised stream-copy cache), preview-pending-slate,
// preview-upscaled-editorial, tail-only previews => bindings flagged `preview: true` (render.cjs refuses them for a full master
// and needs --preview for stills / ranges). shot-final-4k / seam-variant-hf8 / tail-core-4k are final.
// The kind lives on the segment OR nested under `restored` (the v001 staging bug): both are read here.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {adapt, loadBuild, waiverOptions} = require('./adapter-v008.cjs');
const {checkSegmentFile, checkTailFile} = require('../../lib/tailcheck.cjs');
const {verifyReceipt} = require('../../lib/receipts.cjs');

const WORKSPACE = path.resolve(__dirname, '../../../../../..');
const EDITORIAL = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const FINAL_KINDS = new Set(['shot-final-4k', 'seam-variant-hf8']);

const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));

// A "final" label is only a label: a final clip is bound to the receipt that attests its sha256. The receipt CONTENT is verified here
// and again by stage() (lib/receipts.cjs, shared): a text file that merely names a hash is not a receipt. A relabelled preview
// (kind edited to final, same file) has no such receipt and is refused.
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

const parseRate = (text) => {
  const [n, d] = String(text).split('/').map(Number);
  return d ? n / d : n;
};

// first native index of the bound tail file (inside the original native clip); required: it fixes where the editorial cut sits in the file
function s_first(source) {
  if (!Number.isInteger(source.first_native_index) || !Number.isInteger(source.native_editorial_frames) || !Number.isInteger(source.native_total_frames)) {
    throw new Error(`tail ${source.transition_id}: tail_source lacks first_native_index / native_editorial_frames / native_total_frames`);
  }
  return source.first_native_index;
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

// preview = true is the explicit opt-in for stills / ranges from a master config that is not ready (preview sources).
// adaptMaster itself does structure, clock and receipt checks only; the media PROBES (tail files, picture clips) run in this adapter's
// CLI (verifyTails / verifyPictures) and again in lib/stage.cjs when render.cjs stages the sources.
function adaptMaster(review, events, master, {preview = false, historicalWaivers, bound} = {}) {
  if (!preview) {
    if (master.master_ready !== true) throw new Error(`master config is not ready (master_ready=${master.master_ready}, status=${master.status}); pass preview for stills / ranges`);
    if ((master.missing_shots || []).length) throw new Error(`master config has missing shots: ${master.missing_shots.join(', ')}`);
    if ((master.missing_tails || []).length) throw new Error(`master config has missing 4K tails: ${master.missing_tails.join(', ')}`);
  }
  const kit = adapt(review, events, {historicalWaivers, bound});
  // the master has no on-screen label (G-LABEL) and its clock must equal the review clock
  delete kit.review;
  const c = master.master_contract;
  if (c.main_frames !== kit.timeline.mainFrames || c.end_card_frames !== kit.timeline.endCardFrames) throw new Error('master contract clock differs from the review clock');
  // the master clock must be the kit clock: shot windows, segment windows and transition boundaries, not just the keys
  const clock = [];
  for (const m of master.dialogue) {
    const k = kit.shots.find((x) => x.id === m.id);
    if (!k) continue; // key mismatches are reported below
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
  // the master must supply EXACTLY the pictures the kit config plays: same shot/segment keys, same tail keys (a dropped
  // segment would otherwise keep its review clip, an extra one would be ignored)
  const keysOf = (pairs) => pairs.sort().join(', ');
  const kitSegs = Object.entries(kit.bindings.shots).flatMap(([id, s]) => Object.keys(s.segments).map((k) => `${id}/${k}`));
  const masterSegs = master.dialogue.flatMap((s) => s.segments.map((g) => `${s.id}/${g.source_id}`));
  if (keysOf([...kitSegs]) !== keysOf([...masterSegs])) {
    const missing = kitSegs.filter((k) => !masterSegs.includes(k));
    const extra = masterSegs.filter((k) => !kitSegs.includes(k));
    throw new Error(`master picture keys differ from the kit config: missing [${missing.join(', ')}] extra [${extra.join(', ')}]`);
  }
  const kitTailKeys = Object.keys(kit.bindings.tails);
  const masterTailKeys = master.motion.transitions.filter((t) => t.outgoing_tail).map((t) => t.id);
  if (keysOf([...kitTailKeys]) !== keysOf([...masterTailKeys])) {
    throw new Error(`master tail keys [${masterTailKeys.join(', ')}] differ from the kit config [${kitTailKeys.join(', ')}]`);
  }
  for (const shot of master.dialogue) {
    for (const seg of shot.segments) kit.bindings.shots[shot.id].segments[seg.source_id] = pictureBinding(seg);
  }
  const reviewTails = kit.transitions.filter((t) => t.tail).map((t) => t.id).sort().join();
  const masterTails = master.motion.transitions.filter((t) => t.outgoing_tail).map((t) => t.id).sort().join();
  if (reviewTails !== masterTails) throw new Error(`tail transitions differ: review [${reviewTails}] vs master [${masterTails}]`);
  for (const t of master.motion.transitions) {
    if (!t.outgoing_tail) continue;
    const s = t.tail_source;
    if (!s || !s.path) throw new Error(`no tail source for ${t.id}`);
    // the master's own record of the tail must agree with the build's events record (receipt-bound): raising tail_output_frames in the
    // master config cannot widen what the kit may play (verifiedFrames below is the events value, never the master's)
    const ev = (events.transitions.find((x) => x.id === t.id) || {}).outgoing_tail;
    if (!ev) throw new Error(`${t.id}: the events record has no outgoing_tail`);
    for (const [masterKey, eventKey] of [['tail_output_frames', 'tail_output_frames'], ['editorial_frames', 'editorial_frames'], ['native_frames', 'native_frames'], ['review_start_from_frame', 'start_from_frame']]) {
      if (t.outgoing_tail[masterKey] !== ev[eventKey]) throw new Error(`${t.id}: master outgoing_tail.${masterKey} ${t.outgoing_tail[masterKey]} differs from the events record ${ev[eventKey]}`);
    }
    const tailPreview = s.kind !== 'tail-core-4k' || Boolean(s.preview_only_tail);
    kit.bindings.tails[t.id] = {path: s.path, sha256: s.sha256, preview: tailPreview, kind: s.kind, ...(tailPreview ? {} : {receipt: tailReceipt(t.id, s)})};
    // the 4K tail file is its own clip. Everything comes from the MASTER config: start_from_frame, and the position of the editorial cut
    // INSIDE the bound file = native_editorial_frames - first_native_index; the file must hold native_total - first_native_index frames.
    if (!master.master_contract.native_restored_fps) throw new Error('master_contract.native_restored_fps is required (no default is assumed)');
    const nativeFps = parseRate(master.master_contract.native_restored_fps);
    const first = s_first(s);
    const editorialInFile = s.native_editorial_frames - first;
    const sf = t.outgoing_tail.start_from_frame;
    if (!Number.isInteger(sf) || sf < 0) throw new Error(`master transition ${t.id} has no integer outgoing_tail.start_from_frame`);
    const expectStart = (editorialInFile * kit.fps) / nativeFps;
    if (Math.abs(expectStart - sf) > 1e-9) throw new Error(`master transition ${t.id}: start_from_frame ${sf} does not match (native_editorial_frames - first_native_index) * fps / nativeFps = ${expectStart}`);
    kit.transitions.find((x) => x.id === t.id).tail = {startFrom: sf, editorialFrames: editorialInFile, fileFrames: s.native_total_frames - first, verifiedFrames: ev.tail_output_frames};
  }
  return kit;
}

async function main() {
  const args = process.argv.slice(2);
  const opt = (name, dflt) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : dflt;
  };
  const v008 = path.join(EDITORIAL, 'review-hd-v008');
  const masterPath = opt('--master-config', path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json'));
  const reviewPath = opt('--review-config', path.join(v008, 'config', 'review-config-v008.json'));
  const eventsPath = opt('--events', path.join(v008, 'events-v008.json'));
  const receiptPath = opt('--receipt', path.join(v008, 'RECEIPT.json'));
  const out = opt('--out');
  if (!out) throw new Error('--out is required');
  const build = loadBuild({reviewConfig: reviewPath, events: eventsPath, receipt: receiptPath, episodeRoot: opt('--episode-root')});
  const kit = adaptMaster(build.review, build.events, readJson(masterPath), {preview: args.includes('--preview'), historicalWaivers: waiverOptions(args, opt), bound: build.bound});
  await verifyTails(kit);
  if (!args.includes('--preview')) verifyPictures(kit); // a real master config: every picture clip is probed too
  kit.provenance = {
    ...kit.provenance,
    master_config: {path: masterPath, sha256: sha(masterPath)},
    review_config: {path: reviewPath, sha256: build.bound.config_sha256}, // the hashes of the VERIFIED bytes, not a re-read
    events: {path: eventsPath, sha256: build.bound.events_sha256},
    adapter: {path: __filename, sha256: sha(__filename)},
  };
  fs.mkdirSync(path.dirname(path.resolve(out)), {recursive: true});
  fs.writeFileSync(out, `${JSON.stringify(kit, null, 2)}\n`);
  process.stdout.write(`kit master config written: ${out}\n`);
}

// Probes every bound tail file (frame count, native fps) and checks it holds the frames the transition plays.
async function verifyTails(kit) {
  const {tailWindow} = await import(pathToFileURL(path.join(__dirname, '..', '..', 'src', 'picture-mode.mjs')).href);
  const results = [];
  for (const t of kit.transitions) {
    const w = tailWindow(t);
    if (!w) continue;
    const b = kit.bindings.tails[t.id];
    const file = (b.materialized || b).path;
    results.push({transition: t.id, ...checkTailFile(file, {fps: kit.fps, startFrom: t.tail.startFrom, n: w.frames, editorialFrames: t.tail.editorialFrames, fileFrames: t.tail.fileFrames, label: t.id})});
  }
  return results;
}

// Probes every bound picture clip: final sources must hold the native frames their window plays (strict); preview-only ones
// (slates, concat previews) are reported, not refused.
function verifyPictures(kit) {
  const out = [];
  for (const shot of kit.shots) {
    for (const seg of shot.segments) {
      const b = kit.bindings.shots[shot.id].segments[seg.id];
      out.push({segment: `${shot.id}/${seg.id}`, preview: Boolean(b.preview),
        ...checkSegmentFile((b.materialized || b).path, {fps: kit.fps, frames: seg.frames, label: `${shot.id}/${seg.id}`, strict: !b.preview})});
    }
  }
  return out;
}

module.exports = {adaptMaster, verifyTails, verifyPictures, finalReceipt, tailReceipt};
if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`master adapter failed: ${error.message}\n`);
    process.exitCode = 1;
  });
}
