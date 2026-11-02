// T-E42 addendum through the REAL compositor (CPU, concurrency 1) on the synthetic solid-colour episode: two segments, the one audio mix,
// the join with its proof, byte-determinism of a re-rendered segment, and pixel parity of segment frames with the same frames of the
// full film (PNG, rgba). Skipped (with the reason) when ffmpeg, the Remotion packages or a cached browser are missing, or with
// KIT_SKIP_RENDER_SMOKE=1.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {BROWSER, FONTS, KIT, PACKAGES, build, config} from './smoke-lib.mjs';

const require = createRequire(import.meta.url);
const join = require('../tools/join-segments.cjs');
const sha = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const readJson = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));

test('R12-R1: render.cjs --segment / --audio-only / join: closed-GOP segments join framemd5-identical, audio is one mix, re-rendering a segment reproduces the film, pixels match the full film', async (t) => {
  if (process.env.KIT_SKIP_RENDER_SMOKE === '1') return t.skip('KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  if (!fs.existsSync(BROWSER)) return t.skip(`no cached headless browser (${BROWSER}); set REMOTION_BROWSER`);
  if (!fs.existsSync(path.join(PACKAGES, 'remotion', 'package.json'))) return t.skip(`Remotion packages not found (${PACKAGES})`);
  if (FONTS.some((f) => !fs.existsSync(f))) return t.skip('fonts for the compositor are not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-seg-'));
  try {
    const cfg = config(build(dir));
    cfg.segments = [{id: 'main', kind: 'main', start: 0, end_exclusive: 150}, {id: 'ending', kind: 'ending', start: 150, end_exclusive: 330}];
    const cfgFile = path.join(dir, 'config.json');
    fs.writeFileSync(cfgFile, JSON.stringify(cfg));
    const render = (...extra) => {
      const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--mode', 'review', '--concurrency', '1', '--browser', BROWSER, '--workdir', dir, ...extra],
        {encoding: 'utf8', timeout: 900000, maxBuffer: 1 << 26});
      assert.equal(r.status, 0, `${r.stdout.slice(-500)}\n${r.stderr.slice(-1500)}`);
      return r;
    };
    // the plan, with no browser
    const planRun = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--segments-plan'], {encoding: 'utf8'});
    assert.equal(planRun.status, 0, planRun.stderr);
    const plan = JSON.parse(planRun.stdout);
    assert.deepEqual(plan.segments.map((s) => [s.id, s.start, s.end_exclusive]), [['main', 0, 150], ['ending', 150, 330]]);

    const main = path.join(dir, 'main.mp4');
    const ending = path.join(dir, 'ending.mp4');
    const ending2 = path.join(dir, 'ending-again.mp4');
    render('--segment', 'main', '--out', main);
    render('--segment', 'ending', '--out', ending);
    render('--segment', 'ending', '--out', ending2);
    const rec = readJson(`${ending}.render-record.json`);
    assert.deepEqual([rec.segment.id, rec.segment.start, rec.segment.end_exclusive, rec.segment.plan_sha256], ['ending', 150, 330, plan.sha256]);
    assert.equal(rec.silent, true);
    assert.equal(rec.framemd5.length, 180);
    assert.equal(rec.codec.crf, 18);
    assert.equal(spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', main], {encoding: 'utf8'}).stdout.trim(), '', 'a segment is silent');
    // DETERMINISM: the same segment rendered twice is the same bytes
    assert.equal(sha(ending), sha(ending2));

    // the one audio mix: 330 frames x 1600 samples
    const mix = path.join(dir, 'mix.wav');
    render('--audio-only', '--out', mix);
    const audioRec = readJson(`${mix}.render-record.json`);
    assert.equal(audioRec.audio_only.sample_rate, 48000);
    assert.ok(Math.abs(audioRec.audio_only.samples - 330 * 1600) <= 1600, String(audioRec.audio_only.samples));

    const one = await join.joinSegments({segments: [main, ending], audio: mix, out: path.join(dir, 'film1.mp4')});
    const two = await join.joinSegments({segments: [main, ending2], audio: mix, out: path.join(dir, 'film2.mp4')});
    assert.equal(one.proof.hashes_equal, true);
    assert.equal(one.proof.compared, 330);
    assert.equal(one.film.sha256, two.film.sha256, 're-rendering the ending alone reproduces the joined film byte for byte');
    assert.equal(one.audio_join.join_sample, 150 * 1600);

    // pixel parity: ending-segment frames equal the same frames of the full film, rgba md5
    const segEnd = path.join(dir, 'png-end');
    const full = path.join(dir, 'png-full');
    const full2 = path.join(dir, 'png-full-tail');
    render('--segment', 'ending', '--png-seq', segEnd);
    render('--range', '150-152', '--png-seq', full);
    render('--range', '329-329', '--png-seq', full2);
    const png = (d, f) => sha(path.join(d, `element-${String(f).padStart(3, '0')}.png`));
    for (const f of [150, 151, 152]) assert.equal(png(segEnd, f), png(full, f), `frame ${f} (ending segment) equals the full film`);
    assert.equal(png(segEnd, 329), png(full2, 329));
    assert.notEqual(png(full2, 329), png(full, 150), 'the check separates two different frames');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
