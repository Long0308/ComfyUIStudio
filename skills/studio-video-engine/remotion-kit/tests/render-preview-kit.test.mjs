// render.cjs refuses a kit config marked mode "preview" for a master render (a preview kit may only make stills / partial ranges with --preview).
// The gate runs right after the config is read, so these runs touch no media, no browser and no GPU.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const RENDER = path.join(KIT, 'render.cjs');

function run(config, extra) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-previewkit-'));
  try {
    const file = path.join(dir, 'kit.json');
    fs.writeFileSync(file, JSON.stringify(config));
    return spawnSync(process.execPath, [RENDER, '--config', file, ...extra], {encoding: 'utf8'});
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
}

test('a preview kit is refused for a master render (full film, --range, --segments-build)', () => {
  for (const extra of [['--mode', 'master', '--out', 'x.mp4'], ['--mode', 'master', '--range', '0-10', '--out', 'x.mp4'], ['--mode', 'master', '--segments-build', 'C', '--explain']]) {
    const r = run({mode: 'preview'}, extra);
    assert.notEqual(r.status, 0, extra.join(' '));
    assert.match(r.stderr, /kit config is marked mode "preview".*not a master/s, `${extra.join(' ')}: ${r.stderr}`);
  }
});

test('--preview lets a preview kit through this gate (stills / ranges); the run then fails later on the empty config, not on the gate', () => {
  const r = run({mode: 'preview'}, ['--mode', 'master', '--preview', '--stills', 'a:0', '--out', 'x.mp4']);
  assert.doesNotMatch(r.stderr, /marked mode "preview"/);
});

test('an unknown kit mode is refused', () => {
  const r = run({mode: 'draft'}, ['--mode', 'master', '--out', 'x.mp4']);
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /config\.mode must be "preview" or "final"/);
});

test('a final kit and a kit without a mode pass this gate', () => {
  for (const config of [{mode: 'final'}, {}]) {
    const r = run(config, ['--mode', 'master', '--out', 'x.mp4']);
    assert.doesNotMatch(r.stderr, /marked mode "preview"|config\.mode must be/);
  }
});
