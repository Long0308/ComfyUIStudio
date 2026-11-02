// T-E45 edit path: staging with ONE read (copy + digest in flight) and, with a verified-hash cache, no read at all for an unchanged file.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {FONTS} from './smoke-lib.mjs';
import {richConfig} from './p2-lib.mjs';
import {tailWindow} from '../src/picture-mode.mjs';

const require = createRequire(import.meta.url);
const {stage} = require('../lib/stage.cjs');
const {HashCache} = require('../lib/hashcache.cjs');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15-'));
const age = (file) => {
  const t = new Date(Date.now() - 3600 * 1000);
  fs.utimesSync(file, t, t);
};
function setup() {
  const dir = tmp();
  const config = richConfig(dir);
  const bindingFiles = [];
  const walk = (v) => {
    if (v && typeof v === 'object') {
      if (typeof v.path === 'string' && typeof v.sha256 === 'string') bindingFiles.push(v.path);
      Object.values(v).forEach(walk);
    }
  };
  walk(config.bindings);
  for (const f of new Set(bindingFiles)) age(f);
  return {dir, config};
}
const run = (config, extra = {}) => stage(config, {stagingDir: fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15-st-')), fonts: {regular: FONTS[0], bold: FONTS[1]}, tailWindow, ...extra});

test('R15-S1: staging verifies and copies in ONE read: hash stats say how many bytes were copied; tampering is refused by name', () => {
  const {config} = setup();
  const a = run(config);
  assert.ok(a.hashStats.files > 5 && a.hashStats.bytes_copied > 0 && a.hashStats.bytes_linked === 0);
  const clip = config.bindings.shots.S2.segments.S2;
  fs.appendFileSync(clip.path, 'tamper');
  assert.throws(() => run(config), /Input picture hash changed/);
});

test('R15-S2: with a verified-hash cache + link an unchanged file is neither read nor copied (stat identity), a second run hits for every file', () => {
  const {dir, config} = setup();
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  const first = run(config, {hashCache: cache, link: true});
  assert.ok(first.hashStats.bytes_linked > 0, 'same volume: files are hard-linked');
  assert.ok(first.hashStats.cache_misses > 0, 'the first run reads what it has never seen (a file bound twice is read once)');
  const second = run(config, {hashCache: cache, link: true});
  assert.equal(second.hashStats.cache_misses, 0, JSON.stringify(second.hashStats));
  assert.ok(second.hashStats.cache_hits >= second.hashStats.files - 3, JSON.stringify(second.hashStats));
  assert.ok(second.hashStats.bytes_not_read > 0);
  // the staged name is the source inode, so nothing was read to stage it
  const staged = path.join(second.publicDir, second.sources.shots.S1.segments.S1);
  assert.equal(fs.statSync(staged).ino, fs.statSync(config.bindings.shots.S1.segments.S1.path).ino);
});

test('R15-S3: GATE - a bound file that changed (new size) is a cache miss, is re-hashed and REFUSED, with or without link', () => {
  const {dir, config} = setup();
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  run(config, {hashCache: cache, link: true});
  fs.appendFileSync(config.bindings.shots.S3.segments.S3.path, 'x');
  assert.throws(() => run(config, {hashCache: cache, link: true}), /Input picture hash changed/);
  assert.throws(() => run(config, {hashCache: cache}), /Input picture hash changed/);
});

test('R15-S4: a missing bound file is refused by name (the clip probe, or the staging check)', () => {
  const {config} = setup();
  fs.rmSync(config.bindings.shots.S4.segments.S4.path);
  assert.throws(() => run(config), /ffprobe failed|missing/);
});
