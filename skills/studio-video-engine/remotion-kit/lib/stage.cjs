'use strict';
// Staging: turn config.bindings ({path, sha256} per input, hash-verified) into the `sources` object the Film composition
// consumes (names under the bundle's public dir). Generic: no episode names. Pure Node, no Remotion.

const fs = require('node:fs');
const path = require('node:path');
const {checkSegmentFile, checkTailFile, probeClip} = require('./tailcheck.cjs');
const {verifyReceipt} = require('./receipts.cjs');
const {copyHashed, sha256Stream} = require('./hashcache.cjs');

// streaming digest (a 4K core is larger than a Buffer may be); same value as hashing the whole file
function sha256(file) {
  return sha256Stream(file);
}

// A final (non-preview) source must carry {receipt: {path, sha256, binds}}: the receipt file must still hash to receipt.sha256 and the
// output hash it attests (binds) must be the bound file's sha256. Used by stage() in master mode and by the tests.
// A FINAL (non-preview) source is exactly the attested file: `materialized` (a stream-copied preview cache) exists for previews only.
function requireFinalShape(binding, role, label) {
  if (!binding.preview && binding.materialized) {
    throw new Error(`final ${role} ${label}: a final source may not carry 'materialized' (finals stage exactly the attested bytes; only previews are materialized)`);
  }
}

function requireReceiptBinding(binding, role, label) {
  if (binding.preview) return true; // previews are marked and never final: no receipt
  const rc = binding.receipt;
  if (!rc || !rc.path || !rc.sha256 || !rc.binds || !rc.kind) throw new Error(`final ${role} ${label} has no receipt binding (master mode refuses an unattested final label)`);
  if (!fs.existsSync(rc.path)) throw new Error(`final ${role} ${label}: receipt ${rc.path} is missing or changed`);
  if (rc.binds !== binding.sha256) throw new Error(`final ${role} ${label}: receipt attests ${rc.binds}, not the bound file ${binding.sha256}`);
  // read the receipt ONCE: verifyReceipt checks its CONTENT (the same module the adapter used; a file that merely names the hash is not a
  // receipt) and returns the hash of those same bytes, which must be the recorded one
  const v = verifyReceipt({kind: rc.kind, path: rc.path, clipPath: binding.path, clipSha: binding.sha256, transition: rc.transition, label: `final ${role} ${label}`});
  if (v.sha256 !== rc.sha256) throw new Error(`final ${role} ${label}: receipt ${rc.path} is missing or changed`);
  return true;
}

const safe = (s) => String(s).replace(/[^a-z0-9]+/gi, '-').toLowerCase();

// Which video bindings a set of global frames needs (stills / short ranges of a 4K master must not copy every clip).
// tailWindow = picture-mode.mjs tailWindow (the single definition of where a tail plays; render.cjs imports and passes it)
function neededVideos(config, frames, tailWindow) {
  const need = {segments: new Set(), tails: new Set()};
  const near = (f, from, len) => f >= from && f < from + len;
  for (const f of frames) {
    for (const shot of config.shots) {
      if (near(f, shot.start, shot.frames)) for (const seg of shot.segments) need.segments.add(`${shot.id}/${seg.id}`);
    }
    for (const t of config.transitions) {
      const w = tailWindow(t);
      if (w && near(f, w.from, w.frames)) need.tails.add(t.id);
    }
  }
  return need;
}

/**
 * @param {object} config kit config (config.bindings required)
 * @param {{stagingDir:string, fonts:{regular:string,bold:string}, tailWindow:Function, frames?:number[], allowPreview?:boolean, requireReceipts?:boolean}} opts
 * `frames` given = stage only the videos those frames need (sources are then partial); audio and images are always staged.
 * `hashCache` (lib/hashcache.cjs HashCache) + `link: true`: an unchanged file is verified by its stat identity and hard-linked instead of read and copied.
 */
function stage(config, opts) {
  const b = config.bindings;
  if (!b) throw new Error('config.bindings is required for rendering');
  const publicDir = path.join(opts.stagingDir, 'public');
  const fontsDir = path.join(publicDir, 'fonts');
  fs.mkdirSync(fontsDir, {recursive: true});
  const used = [];
  let seq = 0;
  if (typeof opts.tailWindow !== 'function') throw new Error('stage needs opts.tailWindow (picture-mode.mjs tailWindow)');
  const only = opts.frames ? neededVideos(config, opts.frames, opts.tailWindow) : null;

  // hash accounting of this staging run: bytes read to verify / stage, bytes a verified-hash cache did not have to read
  const hashStats = {files: 0, bytes_copied: 0, bytes_linked: 0, cache_hits: 0, cache_misses: 0, bytes_not_read: 0};
  const hasher = opts.hashCache || null;
  const tryLink = (src, dest) => {
    if (!opts.link || !hasher) return false;
    try {
      fs.linkSync(src, dest); // same volume only: the staged name IS the source inode, nothing is read or written
      return true;
    } catch {
      return false;
    }
  };

  // the frame count / rate of a clip depends only on its content: with a hash cache it is remembered under the clip's sha256 (never re-probed)
  const probeOf = (binding) => (file) => (hasher && binding.sha256 ? hasher.memo('probe', binding.sha256, () => probeClip(file)) : probeClip(file));

  const copy = (binding, label, ext, role) => {
    if (binding.preview && !opts.allowPreview) {
      throw new Error(`preview-only source refused (${role} ${label}); pass --preview for stills / ranges, never for the master`);
    }
    requireFinalShape(binding, role, label);
    // a PREVIEW binding may point at a stream-copied cache of a concat list (`materialized`): both hashes are verified
    const target = binding.materialized || binding;
    // master mode: a final source is bound to the receipt that attests its sha256 (a "final" label alone is not evidence)
    if (opts.requireReceipts && !binding.preview && (role === 'picture' || role === 'tail')) requireReceiptBinding(binding, role, label);
    for (const f of binding.materialized ? [binding.path, target.path] : [binding.path]) {
      if (!f || !fs.existsSync(f)) throw new Error(`${binding.materialized && f === target.path ? 'Materialized' : 'Input'} ${role} missing: ${f}`);
    }
    const name = `${String(seq++).padStart(3, '0')}-${safe(label)}${ext}`;
    const dest = path.join(publicDir, name);
    // ONE read both stages and verifies (the digest of the bytes written); with a hash cache + link the unchanged file is neither read nor copied
    const before = hasher ? hasher.stats() : null;
    let stagedSha;
    if (tryLink(target.path, dest)) {
      stagedSha = hasher.sha256(target.path);
      hashStats.bytes_linked += fs.statSync(dest).size;
    } else {
      stagedSha = copyHashed(target.path, dest);
      hashStats.bytes_copied += fs.statSync(dest).size;
    }
    const sourceSha = binding.materialized ? (hasher ? hasher.sha256(binding.path) : sha256(binding.path)) : stagedSha;
    if (sourceSha !== binding.sha256) throw new Error(`Input ${role} hash changed: ${binding.path}`);
    if (binding.materialized && stagedSha !== target.sha256) throw new Error(`Materialized ${role} hash changed: ${target.path}`);
    // a final must be byte-identical to the attested sha256
    if (!binding.preview && stagedSha !== binding.sha256) throw new Error(`${role} ${label}: the staged file hash ${stagedSha} differs from the verified ${binding.sha256} (changed while staging?)`);
    if (hasher) {
      const after = hasher.stats();
      hashStats.cache_hits += after.hits - before.hits;
      hashStats.cache_misses += after.misses - before.misses;
      hashStats.bytes_not_read += after.bytes_not_read - before.bytes_not_read;
    }
    hashStats.files += 1;
    used.push({role, label, source_path: binding.path, source_sha256: sourceSha, staged: name, staged_from: target.path, staged_sha256: stagedSha, preview: Boolean(binding.preview)});
    return name;
  };

  const tailChecks = [];
  const segmentChecks = [];
  const sources = {fonts: {}, shots: {}, tails: {}, icons: {}, cards: []};
  sources.opening = b.opening ? copy(b.opening, 'opening', '.png', 'opening') : null;
  sources.logo = copy(b.logo, 'logo', '.png', 'logo');
  sources.music = copy(b.music, 'music', '.wav', 'music');
  sources.ambience = b.ambience ? copy(b.ambience, 'ambience', '.wav', 'ambience') : null;
  for (const shot of config.shots) {
    const sb = b.shots[shot.id];
    if (!sb) throw new Error(`bindings.shots.${shot.id} missing`);
    sources.shots[shot.id] = {audio: copy(sb.audio, `voice-${shot.id}`, '.wav', 'dialogue'), segments: {}};
    for (const seg of shot.segments) {
      const binding = sb.segments[seg.id];
      if (!binding) throw new Error(`bindings.shots.${shot.id}.segments.${seg.id} missing`);
      const staged = !only || only.segments.has(`${shot.id}/${seg.id}`);
      if (staged) {
        requireFinalShape(binding, 'picture', `${shot.id}/${seg.id}`);
        // the bound clip must hold the frames its window plays (strict for final sources, reported for preview-only ones)
        const probed = checkSegmentFile((binding.materialized || binding).path, {fps: config.fps, frames: seg.frames, label: `${shot.id}/${seg.id}`, strict: !binding.preview, probe: probeOf(binding.materialized || binding)});
        segmentChecks.push({segment: `${shot.id}/${seg.id}`, preview: Boolean(binding.preview), ...probed});
      }
      sources.shots[shot.id].segments[seg.id] = staged ? copy(binding, `clip-${seg.id}`, '.mp4', 'picture') : null;
    }
  }
  for (const t of config.transitions) {
    if (!t.tail) continue;
    const binding = (b.tails || {})[t.id];
    if (!binding) throw new Error(`bindings.tails.${t.id} missing`);
    // the bound tail file must really hold the frames the transition plays (last index + ceil(0.8 N) rule), staged or not
    const w = opts.tailWindow(t);
    requireFinalShape(binding, 'tail', t.id);
    const probed = checkTailFile((binding.materialized || binding).path, {fps: config.fps, startFrom: t.tail.startFrom, n: w.frames, editorialFrames: t.tail.editorialFrames, fileFrames: t.tail.fileFrames, label: t.id, probe: probeOf(binding.materialized || binding)});
    tailChecks.push({transition: t.id, ...probed});
    sources.tails[t.id] = !only || only.tails.has(t.id) ? copy(binding, `tail-${t.id}`, '.mp4', 'tail') : null;
  }
  for (const ev of config.icons) {
    if (!sources.icons[ev.icon]) {
      const binding = (b.icons || {})[ev.icon];
      if (!binding) throw new Error(`bindings.icons.${ev.icon} missing`);
      sources.icons[ev.icon] = copy(binding, `icon-${ev.icon.replace(/\.[a-z]+$/i, '')}`, '.png', 'vocabulary_icon');
    }
  }
  config.cards.forEach((card, i) => {
    const cb = (b.cards || [])[i];
    if (!cb) throw new Error(`bindings.cards[${i}] missing`);
    sources.cards.push({icon: copy(cb.icon, `card-${i}-${card.term}`, '.png', 'vocabulary_icon'), audio: copy(cb.audio, `vocab-${i}-${card.term}`, '.wav', 'vocabulary_audio')});
  });
  for (const [key, src] of Object.entries(opts.fonts)) {
    if (!fs.existsSync(src)) throw new Error(`Font unavailable: ${src}`);
    const name = `fonts/${key}.ttf`;
    fs.copyFileSync(src, path.join(publicDir, name));
    sources.fonts[key] = name;
    used.push({role: 'font', label: `font-${key}`, source_path: src, source_sha256: hasher ? hasher.sha256(src) : sha256(src), staged: name});
  }
  return {sources, used, publicDir, partial: Boolean(only), tailChecks, segmentChecks, hashStats};
}

module.exports = {stage, neededVideos, sha256, requireReceiptBinding};
