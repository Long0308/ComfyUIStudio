// Generic master adapter (lib/adapter-master.cjs): parity with the shipped ep04 master adapter, and proof that its numbers come from data.
// Reads the real ep04 build, master config and episode text (read-only). Nothing is rendered, nothing is written outside a scratch folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WORKSPACE = path.resolve(KIT, '../../../..');
const require = createRequire(import.meta.url);
const EDITORIAL = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const V008 = path.join(EDITORIAL, 'review-hd-v008');
const REVIEW = path.join(V008, 'config', 'review-config-v008.json');
const EVENTS = path.join(V008, 'events-v008.json');
const RECEIPT = path.join(V008, 'RECEIPT.json');
const MASTER = path.join(EDITORIAL, 'master-4k-v002', 'config', 'master-config-v002.json');
const TEXT = path.join(KIT, 'episodes', 'ep04', 'episode-text.json');
const EP04_MASTER = path.join(KIT, 'episodes', 'ep04', 'adapter-master-v002.cjs');
const GENERIC = path.join(KIT, 'lib', 'adapter-master.cjs');

for (const f of [REVIEW, EVENTS, RECEIPT, MASTER, TEXT, EP04_MASTER, GENERIC]) {
  assert.ok(fs.existsSync(f), `missing input: ${f}`);
}

const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const generic = require(GENERIC);
const ep04 = require(EP04_MASTER);
const {loadBuild} = require(path.join(KIT, 'lib', 'build-binding.cjs'));
// STRICT comparison (no JSON round trip): undefined, NaN, Infinity, a missing key or a different type on either side is a difference.
function strictDiff(a, b, prefix = '', out = []) {
  if (out.length >= 30) return out;
  for (const [name, v] of [['generic', a], ['ep04', b]]) {
    if (v === undefined) out.push(`${prefix || '/'}: ${name} is undefined`);
    else if (typeof v === 'number' && !Number.isFinite(v)) out.push(`${prefix || '/'}: ${name} is ${v}`);
    else if (['function', 'symbol', 'bigint'].includes(typeof v)) out.push(`${prefix || '/'}: ${name} holds a ${typeof v}`);
  }
  if (out.length) return out;
  if (typeof a !== typeof b || Array.isArray(a) !== Array.isArray(b) || (a === null) !== (b === null)) {
    out.push(`${prefix || '/'}: type generic=${a === null ? 'null' : typeof a} ep04=${b === null ? 'null' : typeof b}`);
    return out;
  }
  if (a === null || typeof a !== 'object') {
    if (!Object.is(a, b)) out.push(`${prefix || '/'}: generic=${JSON.stringify(a)?.slice(0, 120)} ep04=${JSON.stringify(b)?.slice(0, 120)}`);
    return out;
  }
  if (Array.isArray(a) && a.length !== b.length) out.push(`${prefix || '/'}: length generic=${a.length} ep04=${b.length}`);
  const ka = Object.keys(a);
  const kb = new Set(Object.keys(b));
  for (const k of ka) if (!kb.has(k)) out.push(`${prefix}/${k}: missing in ep04`);
  for (const k of kb) if (!Object.prototype.hasOwnProperty.call(a, k)) out.push(`${prefix}/${k}: missing in generic`);
  for (const k of ka) if (kb.has(k)) strictDiff(a[k], b[k], `${prefix}/${k}`, out);
  return out;
}

const build = loadBuild({reviewConfig: REVIEW, events: EVENTS, receipt: RECEIPT, episodeRoot: EDITORIAL});
const master = rd(MASTER);
const rawText = rd(TEXT);
// the episode text names the caption line count of every shot (the adapter refuses a missing one): the ep04 file names only the 2-line shot,
// so the parity run states the 1-line shots explicitly instead of letting the adapter default them
const fullCaptions = (t) => ({...t, captionLines: Object.fromEntries(build.review.dialogue.map((d) => [d.id, (t.captionLines || {})[d.id] || 1]))});
const text = fullCaptions(rawText);

test('the strict comparison itself catches undefined, NaN, Infinity, a missing key and a type change', () => {
  assert.deepEqual(strictDiff({a: 1, b: [1, {c: 'x'}]}, {a: 1, b: [1, {c: 'x'}]}), []);
  assert.ok(strictDiff({a: undefined}, {a: 1}).length, 'undefined on one side');
  assert.ok(strictDiff({a: undefined}, {a: undefined}).length, 'undefined on both sides is still not a value');
  assert.ok(strictDiff({a: NaN}, {a: NaN}).length, 'NaN');
  assert.ok(strictDiff({a: 1}, {a: Infinity}).length, 'Infinity');
  assert.ok(strictDiff({a: 1}, {}).length, 'a missing key');
  assert.ok(strictDiff({a: 1}, {a: '1'}).length, 'a type change');
  assert.ok(strictDiff({a: [1, 2]}, {a: [1]}).length, 'an array length');
});

test('PARITY ep04: generic master props strictly equal the shipped ep04 master adapter props (the one added key is the explicit mode)', () => {
  // the ep04 master is not ready (PREVIEW_ONLY), so both run with the explicit preview opt-in; the same inputs on both sides
  const {mode, ...a} = generic.adaptMasterKit(build, master, {episodeText: text, preview: true});
  const b = ep04.adaptMaster(build.review, build.events, master, {preview: true, bound: build.bound});
  assert.equal(mode, 'preview', 'the generic kit marks itself as a preview kit; the ep04 adapter predates the marker');
  const diffs = strictDiff(a, b);
  assert.deepStrictEqual(diffs, [], `generic differs from ep04 at:\n${diffs.join('\n')}`);
  console.log(`# parity ep04: ${Object.keys(a).length} top-level keys, ${JSON.stringify(a).length} bytes, 0 differing fields (strict, no JSON round trip)`);
});

test('the generic adapter refuses a master that is not ready unless the preview opt-in is given', () => {
  assert.throws(() => generic.adaptMasterKit(build, master, {episodeText: text}), /not ready/);
});

test('every shot must name its caption line count: a missing one is refused, not defaulted to 1', () => {
  const missing = {...text, captionLines: {...text.captionLines}};
  delete missing.captionLines.S01_A;
  assert.throws(() => generic.adaptMasterKit(build, master, {episodeText: missing, preview: true}), /captionLines\.S01_A/);
  assert.throws(() => generic.adaptMasterKit(build, master, {episodeText: {...text, captionLines: undefined}, preview: true}), /captionLines/);
  assert.throws(() => generic.adaptMasterKit(build, master, {episodeText: {...text, captionLines: {...text.captionLines, S01_A: 0}}, preview: true}), /captionLines\.S01_A/);
});

test('numbers come from the episode text and the build, not from a table in the adapter', () => {
  // change the caption line count and the iris-disc slide x in a COPY of the text: the output must follow
  const edited = JSON.parse(JSON.stringify(text));
  edited.captionLines = {...edited.captionLines, S01_A: 2};
  edited.ending = {...edited.ending, discSlideX: 515};
  const kit = generic.adaptMasterKit(build, master, {episodeText: edited, preview: true});
  assert.equal(kit.shots.find((s) => s.id === 'S01_A').captionLines, 2);
  assert.equal(kit.ending.discSlideX, 515);
  const base = generic.adaptMasterKit(build, master, {episodeText: text, preview: true});
  assert.equal(base.shots.find((s) => s.id === 'S01_A').captionLines, 1);
  assert.equal(base.ending.discSlideX, text.ending.discSlideX);
});

test('the shot clock table is derived from the build dialogue', () => {
  const kit = generic.adaptMasterKit(build, master, {episodeText: text, preview: true});
  for (const s of build.review.dialogue) {
    assert.deepEqual(kit.clock.shotTable[s.id], [s.start_frame, s.duration_frames]);
  }
  assert.equal(Object.keys(kit.clock.shotTable).length, build.review.dialogue.length);
});

test('a preview kit says so: mode "preview" (the renderer refuses it for a master)', () => {
  const kit = generic.adaptMasterKit(build, master, {episodeText: text, preview: true});
  assert.equal(kit.mode, 'preview');
});

// ---- FINAL master mode (preview = false) with fake receipts and fake probes: nothing here is rendered or probed with ffprobe ----------------
const TAIL_MAP_SCHEMA = 'mam-r27-master-tail-map/v1';
const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');

// a final-ready copy of the real ep04 master config: every picture is a fake 4K core with a shot receipt next to it, every tail a fake core
// attested by a tail map. The numbers (frames, tail offsets) are the real ones, only the media are placeholders.
function finalMaster(dir) {
  const m = JSON.parse(JSON.stringify(master));
  m.master_ready = true;
  m.status = 'PREPARED_NOT_RENDERED';
  m.build_mode = 'master';
  m.missing_shots = [];
  m.missing_tails = [];
  for (const shot of m.dialogue) {
    for (const seg of shot.segments) {
      const folder = path.join(dir, 'runs', seg.source_id);
      fs.mkdirSync(folder, {recursive: true});
      const file = path.join(folder, `${seg.source_id}-core.mp4`);
      fs.writeFileSync(file, `fake core ${seg.source_id}`);
      const digest = sha256(fs.readFileSync(file));
      fs.writeFileSync(path.join(folder, 'shot.json'), JSON.stringify({status: 'COMPLETED', shot_id: seg.source_id, path: file, sha256: digest}));
      delete seg.preview_materialized;
      Object.assign(seg, {
        path: file, sha256: digest, available: true, preview_only: false, source_kind: 'shot-final-4k',
        restored: {status: 'COMPLETE', finalized: true, preview_only: false, source_kind: 'shot-final-4k', final_path: file, final_sha256: digest},
      });
    }
  }
  const rows = [];
  const mapFile = path.join(dir, 'MASTER-TAIL-MAP.json');
  for (const t of m.motion.transitions.filter((x) => x.outgoing_tail)) {
    const file = path.join(dir, `${t.id}-tail.mp4`);
    fs.writeFileSync(file, `fake tail ${t.id}`);
    const digest = sha256(fs.readFileSync(file));
    rows.push({transition: t.id, clip: file, clip_sha256: digest});
    for (const k of ['materialized', 'probe', 'reasons']) delete t.tail_source[k];
    Object.assign(t.tail_source, {kind: 'tail-core-4k', preview_only_tail: false, status: 'COMPLETE', path: file, sha256: digest, receipt: mapFile});
  }
  fs.writeFileSync(mapFile, JSON.stringify({schema: TAIL_MAP_SCHEMA, tails: rows}));
  return m;
}

test('FINAL master mode: ready master + fake receipts -> a "final" kit whose every picture and tail is a receipt-bound final; the injected probes pass', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-final-'));
  try {
    const fm = finalMaster(dir);
    const kit = generic.adaptMasterKit(build, fm, {episodeText: text});
    assert.equal(kit.mode, 'final');
    let pictures = 0;
    for (const shot of kit.shots) {
      for (const seg of shot.segments) {
        const b = kit.bindings.shots[shot.id].segments[seg.id];
        assert.equal(b.preview, false, `${shot.id}/${seg.id}`);
        assert.equal(b.receipt.kind, 'shot');
        assert.equal(b.receipt.binds, b.sha256);
        pictures += 1;
      }
    }
    const tails = Object.entries(kit.bindings.tails);
    assert.ok(pictures > 0 && tails.length > 0);
    for (const [id, b] of tails) {
      assert.equal(b.preview, false, id);
      assert.equal(b.receipt.kind, 'tail');
      assert.equal(b.receipt.binds, b.sha256);
    }
    // the injected probes stand in for ffprobe: a core holding at least the frames the window plays
    const probed = generic.verifyPictures(kit, {probe: () => ({frames: 100000, nativeFps: 24})});
    assert.equal(probed.length, pictures);
    assert.ok(probed.every((r) => r.ok && r.preview === false));
    const byFile = new Map(kit.transitions.filter((t) => t.tail).map((t) => [kit.bindings.tails[t.id].path, t.tail.fileFrames]));
    const tailProbes = await generic.verifyTails(kit, {probe: (file) => ({frames: byFile.get(file), nativeFps: 24})});
    assert.equal(tailProbes.length, tails.length);
    // a core that is too short is refused by the strict probe
    assert.throws(() => generic.verifyPictures(kit, {probe: () => ({frames: 1, nativeFps: 24})}), /native frames/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('FINAL master mode refuses what is not a final: a tampered receipt, a preview source, a preview-built master config', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-final-neg-'));
  try {
    const firstShot = master.dialogue[0].segments[0].source_id;
    // 1. a receipt that no longer attests the clip
    const tampered = finalMaster(dir);
    fs.writeFileSync(path.join(dir, 'runs', firstShot, 'shot.json'), JSON.stringify({status: 'COMPLETED', shot_id: firstShot, path: 'x', sha256: '0'.repeat(64)}));
    assert.throws(() => generic.adaptMasterKit(build, tampered, {episodeText: text}), /shot receipt sha256 differs/);
    // 2. a "ready" master that still binds a preview source
    const withPreview = finalMaster(dir);
    Object.assign(withPreview.dialogue[0].segments[0], {source_kind: 'ffconcat-preview', restored: {}, preview_materialized: master.dialogue[0].segments[0].preview_materialized});
    assert.throws(() => generic.adaptMasterKit(build, withPreview, {episodeText: text}), /preview source/);
    // 3. a master config the producer wrote in preview mode, even with master_ready flipped
    const built = finalMaster(dir);
    built.build_mode = 'preview';
    assert.throws(() => generic.adaptMasterKit(build, built, {episodeText: text}), /build_mode/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

// The CLI probes every bound tail with ffprobe, preview or not. A tail file that does not exist must stop it: exit 1, the missing file named
// on stderr, and NO output file. The inputs are a scratch copy of the real master config whose first tail points at a file that is not there,
// so the outcome does not depend on which ep04 media happen to be on this disk.
test('the CLI fails closed: exit 1, the missing file named, no kit file written', () => {
  const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-master-'));
  try {
    const gone = path.join(scratch, 'does-not-exist-T-tail.mp4');
    const broken = JSON.parse(JSON.stringify(master));
    const tail = broken.motion.transitions.find((t) => t.outgoing_tail).tail_source;
    for (const holder of [tail, tail.materialized].filter(Boolean)) holder.path = gone;
    const masterFile = path.join(scratch, 'master-config.json');
    const textFile = path.join(scratch, 'episode-text.json');
    fs.writeFileSync(masterFile, JSON.stringify(broken));
    fs.writeFileSync(textFile, JSON.stringify(text));
    const out = path.join(scratch, 'kit-master.json');
    const r = spawnSync(process.execPath, [GENERIC, '--review-config', REVIEW, '--events', EVENTS, '--receipt', RECEIPT,
      '--episode-root', EDITORIAL, '--episode-text', textFile, '--master-config', masterFile, '--preview', '--out', out], {encoding: 'utf8'});
    assert.equal(r.status, 1, `stdout: ${r.stdout}\nstderr: ${r.stderr}`);
    assert.ok(r.stderr.includes('master adapter failed:'), r.stderr);
    assert.ok(r.stderr.includes(gone), `the missing file must be named: ${r.stderr}`);
    assert.equal(fs.existsSync(out), false, 'a refused run must not write the kit file');
  } finally {
    fs.rmSync(scratch, {recursive: true, force: true});
  }
});

// The engine's own tail map schema (what `jjv seedvr2 tails assemble` writes) is accepted by lib/receipts.cjs TAIL_MAP_SCHEMAS.
test('the engine tail-map schema jjv/master-tail-map/v1 is accepted as a tail receipt', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-final-schema-'));
  try {
    const fm = finalMaster(dir);
    const file = fm.motion.transitions.find((t) => t.outgoing_tail).tail_source.receipt;
    const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
    fs.writeFileSync(file, JSON.stringify({...doc, schema: 'jjv/master-tail-map/v1'}));
    generic.adaptMasterKit(build, fm, {episodeText: text});
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
