// T-E45 P2 end to end through the REAL compositor (CPU, one child render per stale segment): `render.cjs --segments-build CACHE`.
// cold build -> unchanged rebuild (nothing renders, same film bytes) -> one plate string changed (only the plate segment renders) ->
// only the music stem changed (no segment renders, only the one audio mix, the video is the same frames) -> a flipped byte in a cached
// segment (the build REFUSES, no film) -> --force-segment repairs it. Skipped without a cached browser or with KIT_SKIP_RENDER_SMOKE=1.
import test from 'node:test';
import {assert, BROWSER, clone, fs, have, os, path, richConfig, segmentsDoc, KIT, sha} from './p2-lib.mjs';
import {spawnSync} from 'node:child_process';

const readJson = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));

test('P2-B1: incremental build: only stale segments render; unchanged = same bytes; audio change = no video render; a corrupt cache entry is refused', {timeout: 2400000}, async (t) => {
  if (!have()) return t.skip('no browser / Remotion packages / fonts, or KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-p2build-'));
  try {
    const config = richConfig(dir);
    const doc = segmentsDoc(config, {minFrames: 40});
    const ids = doc.segments.map((s) => s.id);
    assert.ok(ids.length >= 5 && ids.length <= 9, `unexpected segment count ${ids.length}`);
    const cacheDir = path.join(dir, 'cache');
    let n = 0;
    const kit = (cfg, args, expectOk = true) => {
      n += 1;
      const cfgFile = path.join(dir, `config-${n}.json`);
      const segFile = path.join(dir, `segments-${n}.json`);
      fs.writeFileSync(cfgFile, JSON.stringify(cfg));
      fs.writeFileSync(segFile, JSON.stringify(doc));
      const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--segments-file', segFile, '--segments-build', cacheDir, '--mode', 'review', '--browser', BROWSER, '--workdir', dir, '--build-concurrency', '1', ...args],
        {encoding: 'utf8', timeout: 1200000, maxBuffer: 1 << 26});
      if (expectOk) assert.equal(r.status, 0, `${r.stdout.slice(-800)}\n${r.stderr.slice(-1500)}`);
      return r;
    };
    const film = (name) => path.join(dir, `${name}.mp4`);

    // 1. cold build
    const cold = kit(config, ['--out', film('cold')]);
    const run1 = readJson(`${film('cold')}.segments-run.json`);
    assert.equal(run1.segments_rendered, ids.length);
    assert.equal(run1.audio.status, 'RENDER');
    const join1 = readJson(`${film('cold')}.join-record.json`);
    assert.equal(join1.proof.hashes_equal, true);
    assert.equal(join1.proof.compared, 390);
    assert.equal(join1.film.frames, 390);
    assert.equal(join1.from_cache, true);
    assert.match(cold.stdout, /segments rendered \d+, reused 0/);

    // 2. unchanged: nothing renders, byte-identical film
    const again = kit(config, ['--out', film('again')]);
    const run2 = readJson(`${film('again')}.segments-run.json`);
    assert.equal(run2.segments_rendered, 0);
    assert.deepEqual(run2.reused, ids);
    assert.equal(run2.audio.status, 'COMPLETE');
    assert.equal(sha(film('again')), sha(film('cold')), 'an unchanged rebuild reproduces the film byte for byte');
    assert.match(again.stdout, /segments rendered 0/);

    // 3. one plate string: --explain names the segments and the leaf; the build renders only those
    const plateChanged = clone(config);
    plateChanged.ending.plateEn = 'See you soon';
    const explain = kit(plateChanged, ['--explain']);
    const expected = doc.segments.filter((s) => s.end_exclusive > config.ending.plateStart).map((s) => s.id);
    const listed = explain.stdout.split('\n').filter((l) => /\bRENDER\b/.test(l) && /^seg-/.test(l)).map((l) => l.split(/\s+/)[0]);
    assert.deepEqual(listed, expected, explain.stdout);
    assert.match(explain.stdout, /ending\.plate\.plateEn/);
    const plate = kit(plateChanged, ['--out', film('plate')]);
    const run3 = readJson(`${film('plate')}.segments-run.json`);
    assert.deepEqual(run3.segments.filter((s) => s.status === 'RENDER').map((s) => s.id), expected);
    assert.equal(run3.segments_rendered, expected.length);
    assert.ok(run3.estimated_seconds_saved > 0);
    assert.notEqual(sha(film('plate')), sha(film('cold')));
    assert.equal(readJson(`${film('plate')}.join-record.json`).proof.hashes_equal, true);
    assert.match(plate.stdout, /reused \d+/);
    // the segments it did not render are the very cache entries of the first build
    for (const s of run3.segments.filter((x) => x.status === 'COMPLETE')) assert.equal(s.cache_entry, run1.segments.find((x) => x.id === s.id).cache_entry);

    // 4. only the music stem: no segment renders, the video frames are the same, only the audio mix is new
    const wav2 = path.join(dir, 'other-music.wav');
    assert.equal(spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=16000', '-t', '5', wav2]).status, 0);
    const music = clone(config);
    music.bindings.music = {path: wav2, sha256: sha(wav2)};
    const swapped = kit(music, ['--out', film('music')]);
    const run4 = readJson(`${film('music')}.segments-run.json`);
    assert.equal(run4.segments_rendered, 0, 'a music change renders no segment');
    assert.equal(run4.audio.status, 'RENDER');
    assert.equal(readJson(`${film('music')}.join-record.json`).film.framemd5_digest, join1.film.framemd5_digest, 'the video frames are untouched');
    assert.notEqual(readJson(`${film('music')}.join-record.json`).audio_join.mix_sha256, join1.audio_join.mix_sha256);
    assert.match(swapped.stdout, /segments rendered 0/);

    // 5. a flipped byte in a cached segment: refused, no film
    const victim = run1.segments[1];
    const file = path.join(victim.cache_entry, 'segment.mp4');
    const bytes = fs.readFileSync(file);
    bytes[Math.floor(bytes.length / 2)] ^= 0xff;
    fs.writeFileSync(file, bytes);
    const explainCorrupt = kit(config, ['--explain']);
    assert.match(explainCorrupt.stdout, new RegExp(`${victim.id}\\s.*CORRUPT`));
    const refused = kit(config, ['--out', film('refused')], false);
    assert.notEqual(refused.status, 0);
    assert.match(refused.stderr, new RegExp(`segment cache refused: ${victim.id}`));
    assert.equal(fs.existsSync(film('refused')), false, 'no film is written from a corrupt cache');
    // 6. --force-segment re-renders it; the film is the first build again
    kit(config, ['--out', film('repaired'), '--force-segment', victim.id]);
    const run6 = readJson(`${film('repaired')}.segments-run.json`);
    assert.deepEqual(run6.segments.filter((s) => s.status === 'RENDER').map((s) => s.id), [victim.id]);
    assert.equal(sha(film('repaired')), sha(film('cold')), 'the repaired cache reproduces the first film byte for byte');
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
