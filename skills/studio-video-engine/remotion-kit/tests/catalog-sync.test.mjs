// T-E42: the kit is driven by the transition-preset catalog (schemas/transition-presets.json).
//  - tools/sync-catalog.mjs generates src/catalog.generated.mjs from it; `--check` fails on drift (this test runs it);
//  - TYPE_TABLE is DERIVED from the catalog (every READY preset is a valid kit type);
//  - the catalog JSON, the generated kit data and the ENGINE's own preset module (when python is available) agree on
//    shows_both / tail_only / frames / params / schedule / tail frames / window for every preset.
// This replaces the old F10 test, which parsed the python TYPE_PROPERTIES source text.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {CATALOG, CATALOG_SOURCE_SHA256} from '../src/catalog.generated.mjs';
import {TRANSITION_TYPES, TYPE_TABLE, NEEDS_CONTINUITY} from '../src/picture-mode.mjs';
import {candidateFrames, defaultFrames, resolveParams, tailFrameCount, windowOf} from '../src/presets.mjs';
import {READY, PLANNED} from './preset-fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const CATALOG_FILE = path.join(SKILL, 'schemas', 'transition-presets.json');
const SYNC = path.join(KIT, 'tools', 'sync-catalog.mjs');
const readCatalog = () => JSON.parse(fs.readFileSync(CATALOG_FILE, 'utf8').replace(/^﻿/u, ''));

test('sync-catalog --check passes on the committed generated file', () => {
  const r = spawnSync(process.execPath, [SYNC, '--check'], {encoding: 'utf8'});
  assert.equal(r.status, 0, `${r.stdout}\n${r.stderr}`);
});

test('sync-catalog --check exits 1 on drift (and names the file to regenerate); generating into a scratch dir works', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-catalog-'));
  try {
    const doc = readCatalog();
    doc.presets.push_slide.frames.default = 13; // someone edited the catalog and did not regenerate
    const drifted = path.join(dir, 'drifted.json');
    fs.writeFileSync(drifted, JSON.stringify(doc));
    const r = spawnSync(process.execPath, [SYNC, '--check', '--catalog', drifted], {encoding: 'utf8'});
    assert.equal(r.status, 1, `${r.stdout}\n${r.stderr}`);
    assert.match(r.stderr + r.stdout, /drift/i);
    assert.match(r.stderr + r.stdout, /sync-catalog/);
    // a real generate (to --out) writes a file --check accepts
    const out = path.join(dir, 'gen.mjs');
    const g = spawnSync(process.execPath, [SYNC, '--out', out], {encoding: 'utf8'});
    assert.equal(g.status, 0, g.stderr);
    assert.equal(fs.readFileSync(out, 'utf8'), fs.readFileSync(path.join(KIT, 'src', 'catalog.generated.mjs'), 'utf8'));
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});

test('the generated module is the catalog: same data, source hash recorded', () => {
  const bytes = fs.readFileSync(CATALOG_FILE);
  // display text (label / when / kids_note) is left out of the generated module on purpose: the kit reads rules only
  const DISPLAY = ['label', 'when', 'kids_note'];
  const want = readCatalog();
  for (const preset of Object.values(want.presets)) for (const key of DISPLAY) delete preset[key];
  assert.deepEqual(JSON.parse(JSON.stringify(CATALOG)), want);
  assert.equal(CATALOG_SOURCE_SHA256, crypto.createHash('sha256').update(bytes).digest('hex'));
});

test('TYPE_TABLE is derived from the catalog: every READY preset is a valid kit type, planned ones are not', () => {
  assert.ok(READY.length >= 30, `${READY.length} ready presets`);
  assert.deepEqual([...TRANSITION_TYPES].sort(), [...READY].sort());
  for (const name of READY) {
    const p = CATALOG.presets[name];
    const row = TYPE_TABLE[name];
    assert.equal(row.showsBoth, p.shows_both, `${name} showsBoth`);
    assert.equal(row.tailOnly, p.tail_only, `${name} tailOnly`);
    assert.equal(row.tailFrames, p.tail_frames, `${name} tailFrames`);
    assert.equal(row.rendersAs, p.renders_as, `${name} rendersAs`);
  }
  for (const name of PLANNED) assert.equal(TYPE_TABLE[name], undefined, `${name} is planned, not a kit type`);
  // the picture-layer types that mount two pictures need continuity 'agree' (unchanged semantics)
  for (const name of NEEDS_CONTINUITY) assert.ok(TYPE_TABLE[name].showsBoth && TYPE_TABLE[name].drawn, name);
  assert.ok(NEEDS_CONTINUITY.includes('push_slide') && NEEDS_CONTINUITY.includes('cloud') && !NEEDS_CONTINUITY.includes('card_flip_3d'));
});

test('every ready preset has a renderer branch (renders_as is one the kit draws)', () => {
  const HANDLED = new Set(['none', 'cut', 'whip', 'dip_white', 'dissolve', 'wipe', 'cloud', 'bubble', 'iris', 'bloom', 'card_slide', 'plate_in',
    'cut_push', 'push_slide', 'zoom_through', 'zoom_out', 'iris_circle', 'iris_diamond', 'clock_wipe', 'blinds', 'blur_crossfade', 'focus_pull', 'card_flip_3d']);
  for (const name of READY) assert.ok(HANDLED.has(CATALOG.presets[name].renders_as), `${name} renders_as ${CATALOG.presets[name].renders_as} has no kit renderer`);
});

// ---- the kit's reading of the catalog == the engine's own presets module --------------------------------------------------
test('catalog vs the ENGINE preset module: shows_both / tail_only / frames / params / schedule / tail_frames / window agree for every ready preset', (t) => {
  const probe = path.join(KIT, 'tests', 'engine_presets_probe.py');
  const py = spawnSync('python', ['-I', probe, SKILL], {encoding: 'utf8', maxBuffer: 1 << 26});
  if (py.error || py.status !== 0) {
    if (py.error) return t.skip(`python unavailable (${py.error.code})`);
    assert.fail(`engine probe failed: ${py.stderr.slice(-600)}`);
  }
  const engine = JSON.parse(py.stdout);
  assert.deepEqual(Object.keys(engine).sort(), [...READY].sort(), 'engine and kit know the same ready presets');
  for (const name of READY) {
    const e = engine[name];
    const p = CATALOG.presets[name];
    assert.equal(e.shows_both, TYPE_TABLE[name].showsBoth, `${name} shows_both`);
    assert.equal(e.tail_only, TYPE_TABLE[name].tailOnly, `${name} tail_only`);
    assert.deepEqual(e.frames_rule, p.frames, `${name} frames rule`);
    assert.equal(e.default_frames, defaultFrames(p), `${name} default frames`);
    assert.deepEqual(e.candidates, candidateFrames(p), `${name} candidate frames`);
    assert.deepEqual(e.schedule, p.schedule === undefined ? null : p.schedule, `${name} schedule`);
    assert.equal(e.direction, p.direction, `${name} direction`);
    assert.equal(e.renders_as, TYPE_TABLE[name].rendersAs, `${name} renders_as`);
    const params = resolveParams(p, e.params_written || undefined);
    const wanted = p.window === 'iris' ? {...params, disc_fade_frames: 6} : params;
    assert.deepEqual(e.params, wanted, `${name} resolved params`);
    for (const n of e.candidates) {
      assert.equal(e.tail[String(n)], tailFrameCount(p, n), `${name} tail frames at ${n}`);
      assert.deepEqual(e.window_frames[String(n)], windowOf(p, 1000, n, wanted), `${name} window at ${n} frames`);
    }
  }
});
