// Round 11 / T-E42 item 2: every render record carries `shot_sources` (sha256 of every picture clip, tail clip and dialogue WAV that was staged)
// and, with --previous-record, `composite_only`: the proof that an effect change touched no shot video.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const records = require(path.join(KIT, 'lib', 'records.cjs'));
const {stage} = require(path.join(KIT, 'lib', 'stage.cjs'));
const sha = (x) => crypto.createHash('sha256').update(x).digest('hex');

// the `used` list stage() hands back: role + source_path + source_sha256 + staged name (+ label since round 11)
const used = (over = {}) => [
  {role: 'opening', source_path: '/e/open.png', source_sha256: sha('open'), staged: '000-opening.png', label: 'opening'},
  {role: 'dialogue', source_path: '/e/a.wav', source_sha256: sha('wav-a'), staged: '004-voice-s01-a.wav', label: 'voice-S01_A'},
  {role: 'picture', source_path: '/e/a.mp4', source_sha256: sha('clip-a'), staged: '005-clip-s01-a.mp4', label: 'clip-S01_A'},
  {role: 'tail', source_path: '/e/t.mp4', source_sha256: sha('tail-t'), staged: '006-tail-t90.mp4', label: 'tail-T90'},
  {role: 'vocabulary_icon', source_path: '/e/i.png', source_sha256: sha('icon'), staged: '007-icon-x.png', label: 'icon-x'},
  {role: 'font', source_path: '/f/t.ttf', source_sha256: sha('font'), staged: 'fonts/regular.ttf'},
  ...(over.extra || []),
].map((u) => (over.patch && over.patch[u.staged] ? {...u, ...over.patch[u.staged]} : u));

test('2a: shot_sources holds the sha256 of every picture clip, tail clip and dialogue WAV and nothing else (no icons, fonts, music, logo)', () => {
  const s = records.shotSources(used());
  assert.deepEqual(s.map((x) => x.role).sort(), ['dialogue', 'picture', 'tail']);
  const a = s.find((x) => x.role === 'picture');
  assert.equal(a.source_sha256, sha('clip-a'));
  assert.equal(a.key, 'picture:clip-s01-a', 'the key is role + the staged name without its sequence number and extension');
  assert.equal(a.source_path, '/e/a.mp4');
  assert.deepEqual(s.map((x) => x.key), [...s.map((x) => x.key)].sort(), 'canonical order');
  assert.match(records.shotSourcesDigest(s), /^[0-9a-f]{64}$/);
  assert.equal(records.shotSourcesDigest(s), records.shotSourcesDigest([...s].reverse()), 'the digest does not depend on the order');
});

function prevRecord(dir, sources, extra = {}) {
  const file = path.join(dir, 'prev.render-record.json');
  fs.writeFileSync(file, JSON.stringify({shot_sources: sources, output_sha256: sha('out'), config_sha256: sha('cfg'), ...extra}));
  return file;
}

test('2b: composite-only is stated only when EVERY shot source hash is identical to the previous record', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11r-'));
  try {
    const prev = prevRecord(dir, records.shotSources(used()));
    const co = records.compositeOnly(records.shotSources(used()), {previousRecord: prev});
    assert.equal(co.value, true);
    assert.equal(co.unchanged, 3);
    assert.deepEqual(co.changed, []);
    assert.equal(co.previous.path, prev);
    assert.equal(co.previous.sha256, sha(fs.readFileSync(prev)));
    assert.equal(co.statement, `composite-only: no shot source changed vs ${co.previous.sha256.slice(0, 12)} (${prev})`);
    // one clip changed
    const edited = records.shotSources(used({patch: {'005-clip-s01-a.mp4': {source_sha256: sha('clip-a-v2')}}}));
    const c2 = records.compositeOnly(edited, {previousRecord: prev});
    assert.equal(c2.value, false);
    assert.equal(c2.unchanged, 2);
    assert.equal(c2.changed.length, 1);
    assert.deepEqual(c2.changed[0], {key: 'picture:clip-s01-a', previous: sha('clip-a'), current: sha('clip-a-v2')});
    assert.match(c2.statement, /NOT composite-only/);
    assert.match(c2.statement, /picture:clip-s01-a/);
    assert.doesNotMatch(c2.statement, /^composite-only: no shot source changed/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('2c: a source that appeared or disappeared is a change too (a swapped clip set is not composite-only)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11r-'));
  try {
    const prev = prevRecord(dir, records.shotSources(used()));
    const more = records.shotSources(used({extra: [{role: 'picture', source_path: '/e/b.mp4', source_sha256: sha('clip-b'), staged: '008-clip-s02-a.mp4', label: 'clip-S02_A'}]}));
    const added = records.compositeOnly(more, {previousRecord: prev});
    assert.equal(added.value, false);
    assert.deepEqual(added.changed.map((c) => [c.key, c.previous, c.current]), [['picture:clip-s02-a', null, sha('clip-b')]]);
    const fewer = records.shotSources(used()).filter((x) => x.role !== 'tail');
    const dropped = records.compositeOnly(fewer, {previousRecord: prev});
    assert.equal(dropped.value, false);
    assert.deepEqual(dropped.changed.map((c) => [c.key, c.current]), [['tail:tail-t90', null]]);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('2d: a PARTIAL staging (stills / ranges with --stage-needed) compares only the sources it staged and says so', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11r-'));
  try {
    const prev = prevRecord(dir, records.shotSources(used()));
    const subset = records.shotSources(used()).filter((x) => x.role === 'picture');
    const co = records.compositeOnly(subset, {previousRecord: prev, partial: true});
    assert.equal(co.value, true);
    assert.equal(co.scope, 'partial');
    assert.equal(co.unchanged, 1);
    assert.match(co.statement, /^composite-only: no shot source changed vs .*\(1 of 3 previous sources compared: partial staging\)$/);
    const full = records.compositeOnly(records.shotSources(used()), {previousRecord: prev});
    assert.equal(full.scope, 'all');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('2e: a previous record from before this field existed is read through its staged_inputs (same keys); a record with neither is refused', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11r-'));
  try {
    const old = path.join(dir, 'old.json');
    fs.writeFileSync(old, JSON.stringify({staged_inputs: used().map(({label, ...rest}) => rest), output_sha256: sha('o')}));
    const co = records.compositeOnly(records.shotSources(used()), {previousRecord: old});
    assert.equal(co.value, true, 'staged_inputs of an older record yield the same keys');
    const nothing = path.join(dir, 'nothing.json');
    fs.writeFileSync(nothing, JSON.stringify({mode: 'review'}));
    assert.throws(() => records.compositeOnly(records.shotSources(used()), {previousRecord: nothing}), /no shot_sources or staged_inputs/);
    assert.throws(() => records.compositeOnly(records.shotSources(used()), {previousRecord: path.join(dir, 'gone.json')}), /previous record .* missing/);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('2f: stage() gives every staged source a label, so the keys are stable across runs', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11s-'));
  try {
    const w = (name, text) => {
      const f = path.join(dir, name);
      fs.writeFileSync(f, text);
      return {path: f, sha256: sha(text)};
    };
    const font = path.join(dir, 'f.ttf');
    fs.writeFileSync(font, 'font');
    const config = {
      fps: 30, shots: [], transitions: [], icons: [], cards: [],
      bindings: {logo: w('logo.png', 'logo'), music: w('m.wav', 'music'), shots: {}, tails: {}, icons: {}, cards: []},
    };
    const r = stage(config, {stagingDir: path.join(dir, 'stage'), fonts: {regular: font, bold: font}, tailWindow: () => null});
    for (const u of r.used) assert.equal(typeof u.label, 'string', `${u.role} has a label`);
    assert.deepEqual(r.used.filter((u) => u.role !== 'font').map((u) => u.label), ['logo', 'music']);
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
