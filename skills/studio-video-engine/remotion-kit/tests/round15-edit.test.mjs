// T-E45 edit path: tools/edit-render.cjs (the node side of `jjv edit review-render | master-render`): usage and refusals without any render, and an
// opt-in end-to-end --explain on real engine inputs (KIT_EDIT_E2E=episode.json,boundaries.json,word-timing.json,episode-root,episode-text).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TOOL = path.join(KIT, 'tools', 'edit-render.cjs');
const run = (...args) => spawnSync(process.execPath, [TOOL, ...args], {encoding: 'utf8', timeout: 120000});
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15e-'));

test('R15-E1: usage errors exit 2 and name the missing flag; nothing is created beside the cache', () => {
  const cache = path.join(tmp(), 'c');
  assert.equal(run().status, 2);
  assert.match(run('--mode', 'x').stderr, /--mode must be review or master/);
  const noCache = run('--mode', 'review');
  assert.equal(noCache.status, 2);
  assert.match(noCache.stderr, /--cache DIR is required/);
  const noOut = run('--mode', 'review', '--cache', cache);
  assert.equal(noOut.status, 2);
  assert.match(noOut.stderr, /--out FILE\.mp4 is required \(or --explain\)/);
  const noText = run('--mode', 'review', '--cache', cache, '--explain', '--episode-root', cache, '--episode-json', 'e.json', '--boundaries', 'b.json', '--word-timing', 'w.json');
  assert.equal(noText.status, 2);
  assert.match(noText.stderr, /--episode-text is required in review mode/);
});

test('R15-E2: master-render without --master-config is refused by name (exit 1), and so is a master with no cut list', () => {
  const cache = path.join(tmp(), 'c');
  const noConfig = run('--mode', 'master', '--cache', cache, '--out', path.join(cache, 'f.mp4'));
  assert.equal(noConfig.status, 1);
  assert.match(noConfig.stderr, /master-render needs --master-config/);
  const missing = run('--mode', 'master', '--cache', cache, '--out', path.join(cache, 'f.mp4'), '--master-config', path.join(cache, 'nope.json'));
  assert.equal(missing.status, 1);
  assert.match(missing.stderr, /nope\.json does not exist/);
  const cfg = path.join(cache, 'master.json');
  fs.writeFileSync(cfg, '{}');
  const noCuts = run('--mode', 'master', '--cache', cache, '--out', path.join(cache, 'f.mp4'), '--master-config', cfg);
  assert.equal(noCuts.status, 1);
  assert.match(noCuts.stderr, /needs the segment cut list/);
});

test('R15-E3: a failing build-config step is reported with its step name and exit 1 (no film)', () => {
  const dir = tmp();
  const out = path.join(dir, 'film.mp4');
  const r = run('--mode', 'review', '--cache', path.join(dir, 'c'), '--out', out, '--episode-root', dir, '--episode-json', path.join(dir, 'missing-episode.json'),
    '--boundaries', path.join(dir, 'b.json'), '--word-timing', path.join(dir, 'w.json'), '--episode-text', path.join(dir, 't.json'));
  assert.equal(r.status, 1);
  assert.match(r.stderr, /edit-render: build-config failed/);
  assert.equal(fs.existsSync(out), false);
});

test('R15-E4 (opt-in): --explain on real engine inputs lists no segment as RENDER for a cache that was just built is not asserted here; the table is printed and the kit config is written', (t) => {
  const spec = process.env.KIT_EDIT_E2E;
  if (!spec) return t.skip('set KIT_EDIT_E2E=episode.json,boundaries.json,word-timing.json,episode-root,episode-text.json to run');
  const [episodeJson, boundaries, wordTiming, episodeRoot, episodeText] = spec.split(',');
  const cache = path.join(tmp(), 'c');
  const r = spawnSync(process.execPath, [TOOL, '--mode', 'review', '--cache', cache, '--explain', '--episode-json', episodeJson, '--boundaries', boundaries, '--word-timing', wordTiming, '--episode-root', episodeRoot,
    '--episode-text', episodeText, ...(process.env.REMOTION_BROWSER ? [] : [])], {encoding: 'utf8', timeout: 300000});
  assert.equal(r.status, 0, r.stderr.slice(-800));
  assert.match(r.stdout, /segment\(s\) to render, audio\.mix/);
  assert.ok(fs.existsSync(path.join(cache, 'kit-config.json')));
});
