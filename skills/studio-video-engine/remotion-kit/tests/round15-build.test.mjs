// T-E45 edit path through the REAL compositor (CPU): the in-process segment build (one staging, one bundle, one browser) against the child-process build.
//   1. both build modes give the SAME segment files and the SAME film, byte for byte; timings are recorded;
//   2. one caption word moved (startF +2) re-renders <= 2 segments and not the audio mix (legacy music: word timing is not audio);
//   3. the run record says composite-only (no shot source changed) / which source changed, and carries hash-cache and timing numbers;
//   4. RED CASES: a cached segment tampered with the SAME size and a RESTORED mtime is invisible to the verified-hash cache but the join (film decoded
//      once, compared to the recorded frame hashes) still refuses it, and --rehash-all names it CORRUPT before anything renders.
// Skipped without a cached browser or with KIT_SKIP_RENDER_SMOKE=1.
import test from 'node:test';
import {assert, BROWSER, clone, fs, have, os, path, richConfig, segmentsDoc, KIT, sha} from './p2-lib.mjs';
import {spawnSync} from 'node:child_process';

const readJson = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));

test('R15-B1: in-process build == children build (bytes); one word moved re-renders <= 2 segments and no audio; composite-only record; tamper with restored mtime is refused', {timeout: 3000000}, async (t) => {
  if (!have()) return t.skip('no browser / Remotion packages / fonts, or KIT_SKIP_RENDER_SMOKE=1');
  if (spawnSync('ffmpeg', ['-version']).error) return t.skip('ffmpeg is not available');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15build-'));
  try {
    const config = richConfig(dir);
    const doc = segmentsDoc(config, {minFrames: 40});
    let n = 0;
    const kit = (cfg, cache, args, expectOk = true) => {
      n += 1;
      const cfgFile = path.join(dir, `config-${n}.json`);
      const segFile = path.join(dir, `segments-${n}.json`);
      fs.writeFileSync(cfgFile, JSON.stringify(cfg));
      fs.writeFileSync(segFile, JSON.stringify(doc));
      const r = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', cfgFile, '--segments-file', segFile, '--segments-build', cache, '--mode', 'review', '--browser', BROWSER, '--workdir', dir, '--build-concurrency', '1', ...args],
        {encoding: 'utf8', timeout: 1500000, maxBuffer: 1 << 26});
      if (expectOk) assert.equal(r.status, 0, `${r.stdout.slice(-800)}\n${r.stderr.slice(-1500)}`);
      return r;
    };
    const film = (name) => path.join(dir, `${name}.mp4`);
    const cacheA = path.join(dir, 'cache-inproc');
    const cacheB = path.join(dir, 'cache-children');

    // 1. both modes, cold
    kit(config, cacheA, ['--out', film('inproc'), '--build-mode', 'inproc']);
    kit(config, cacheB, ['--out', film('children'), '--build-mode', 'children']);
    const runA = readJson(`${film('inproc')}.segments-run.json`);
    const runB = readJson(`${film('children')}.segments-run.json`);
    assert.equal(runA.build_mode, 'in-process');
    assert.equal(runB.build_mode, 'children');
    assert.equal(sha(film('inproc')), sha(film('children')), 'the in-process build reproduces the child-process film byte for byte');
    for (const s of runA.segments) assert.equal(sha(path.join(s.cache_entry, 'segment.mp4')), sha(path.join(runB.segments.find((x) => x.id === s.id).cache_entry, 'segment.mp4')), `segment ${s.id} differs between build modes`);
    assert.ok(runA.timing_seconds.render > 0 && runB.timing_seconds.render > 0);
    process.stdout.write(`R15-B1 cold: in-process render ${runA.timing_seconds.render.toFixed(1)} s (${JSON.stringify(runA.timing_seconds.renderer)}), children ${runB.timing_seconds.render.toFixed(1)} s; join ${runA.timing_seconds.join.toFixed(1)} s\n`);
    const joinA = readJson(`${film('inproc')}.join-record.json`);
    assert.equal(joinA.proof.hashes_equal, true);
    assert.equal(joinA.proof.single_decode, true);
    assert.equal(joinA.proof.segments_decoded_again, 0);

    // 2. one word moves: the segments that show shot S2's caption render, the audio mix does not
    const moved = clone(config);
    moved.shots[1].words[0].startF += 2;
    const explain = kit(moved, cacheA, ['--explain']);
    assert.match(explain.stdout, /shots\.\d+|shot:S2/);
    kit(moved, cacheA, ['--out', film('moved')]);
    const run2 = readJson(`${film('moved')}.segments-run.json`);
    const touching = doc.segments.filter((s) => s.start < 150 && 90 < s.end_exclusive).map((s) => s.id);
    assert.deepEqual(run2.segments.filter((s) => s.status === 'RENDER').map((s) => s.id).sort(), touching.sort());
    assert.ok(run2.segments_rendered <= 2, `${run2.segments_rendered} segments rendered`);
    assert.equal(run2.audio.status, 'COMPLETE', 'a word timing change is not an audio change without a music bed policy');
    assert.equal(run2.composite_only.value, true, run2.composite_only.statement);
    assert.match(run2.composite_only.statement, /^composite-only: no shot source changed/);
    assert.ok(run2.hash_cache.hits > 0, JSON.stringify(run2.hash_cache));
    assert.equal(readJson(`${film('moved')}.join-record.json`).proof.hashes_equal, true);
    assert.notEqual(sha(film('moved')), sha(film('inproc')));

    // 3. a shot source (a clip) replaced: NOT composite-only, the record names it
    const clip = config.bindings.shots.S3.segments.S3;
    const alt = path.join(dir, 'S3-alt.mp4');
    assert.equal(spawnSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x336699:s=480x270:r=30', '-frames:v', '70', '-pix_fmt', 'yuv420p', alt]).status, 0);
    const swapped = clone(config);
    swapped.bindings.shots.S3.segments.S3 = {path: alt, sha256: sha(alt)};
    assert.notEqual(clip.sha256, swapped.bindings.shots.S3.segments.S3.sha256);
    kit(swapped, cacheA, ['--out', film('swapped')]);
    const run3 = readJson(`${film('swapped')}.segments-run.json`);
    assert.equal(run3.composite_only.value, false);
    assert.match(run3.composite_only.statement, /NOT composite-only: 1 shot source\(s\) changed: picture:S3\/S3/);

    // 4. tamper with the SAME size and a RESTORED mtime: the verified-hash cache trusts the stat identity (declared boundary) ...
    const victim = runA.segments[1];
    const file = path.join(victim.cache_entry, 'segment.mp4');
    // the entry must already be TRUSTED by the cache (a file hashed within seconds of its write is racy and re-read): age it, let one explain record it
    const aged = new Date(Date.now() - 3600 * 1000);
    fs.utimesSync(file, aged, aged);
    kit(config, cacheA, ['--explain']);
    const st = fs.statSync(file);
    const bytes = fs.readFileSync(file);
    bytes[Math.floor(bytes.length / 2)] ^= 0xff;
    fs.writeFileSync(file, bytes);
    fs.utimesSync(file, st.atime, st.mtime);
    const refusedByJoin = kit(config, cacheA, ['--out', film('blind')], false);
    assert.notEqual(refusedByJoin.status, 0, 'the tampered segment must not produce a film');
    assert.match(refusedByJoin.stderr, /join refused|framemd5|decode/i, refusedByJoin.stderr.slice(-600));
    assert.equal(fs.existsSync(film('blind')), false);
    // ... and --rehash-all (the audit path) reads every byte and names it before anything renders
    const audit = kit(config, cacheA, ['--explain', '--rehash-all']);
    assert.match(audit.stdout, new RegExp(`${victim.id}\\s.*CORRUPT`));
    const refusedAudit = kit(config, cacheA, ['--out', film('audit'), '--rehash-all'], false);
    assert.notEqual(refusedAudit.status, 0);
    assert.match(refusedAudit.stderr, new RegExp(`segment cache refused: ${victim.id}`));
    // repaired by --force-segment: the first film again
    kit(config, cacheA, ['--out', film('repaired'), '--force-segment', victim.id, '--rehash-all']);
    assert.equal(sha(film('repaired')), sha(film('inproc')));
  } finally {
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
