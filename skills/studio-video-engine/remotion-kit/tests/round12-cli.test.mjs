// render.cjs segment options that need no browser: the plan printout and the refusals that come before any bundling.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {makeConfig} from './fixture.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const run = (cfg, ...args) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-cli-'));
  try {
    const file = path.join(dir, 'c.json');
    fs.writeFileSync(file, JSON.stringify(cfg));
    return spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', file, ...args], {encoding: 'utf8'});
  } finally { fs.rmSync(dir, {recursive: true, force: true}); }
};

test('R12-C1: --segments-plan prints the plan with the shot-video frame count per segment, without a browser', () => {
  const r = run(makeConfig(), '--segments-plan');
  assert.equal(r.status, 0, r.stderr);
  const plan = JSON.parse(r.stdout);
  assert.deepEqual(plan.segments.map((s) => [s.id, s.start, s.end_exclusive, s.shot_video_frames > 0]), [['main', 0, 147, true], ['ending', 147, 270, false]]);
  assert.equal(plan.codec.crf, 18);
  assert.equal(plan.samples_per_frame, 1600);
});

test('R12-C2: refusals before any bundling: unknown segment, --segment with --range, --segment without --out, --audio-only with a range', () => {
  const c = makeConfig();
  assert.match(run(c, '--segment', 'nope', '--out', 'x.mp4').stderr, /unknown segment nope/);
  assert.match(run(c, '--segment', 'main', '--range', '0-5', '--out', 'x.mp4').stderr, /use one/);
  assert.match(run(c, '--segment', 'main').stderr, /needs --out/);
  assert.match(run(c, '--audio-only', '--range', '0-5', '--out', 'x.wav').stderr, /whole film audio/);
  assert.match(run(c, '--audio-only').stderr, /needs --out/);
});
