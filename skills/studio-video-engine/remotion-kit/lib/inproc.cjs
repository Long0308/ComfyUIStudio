'use strict';
// In-process renderer of a segment build (T-E45 edit path). The first version of `--segments-build` ran one CHILD render.cjs per segment:
// every child staged every binding, bundled the compositor, launched a browser and selected the composition again, so a 2-segment edit
// paid ~10 s of fixed cost per segment and a cold 49-segment build spent most of its time in that overhead.
// This renderer does that work ONCE per build:
//   - ONE staging (only the shot videos the STALE segments mount, or every clip when the audio mix is stale: the mix render mounts the
//     whole film), hashes verified in flight / through the verified-hash cache,
//   - ONE webpack bundle, ONE browser, ONE selectComposition (the input props are identical for every segment; only frameRange differs),
//   - every segment through renderMedia with the same codec parameter set and the same render record the child produced.
// Nothing about WHAT is rendered changes: the same closed-GOP silent encode, the same record fields (the join and the cache read them), the
// same gates (receipts in master mode, tail / segment file checks, preview refusal).

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {stage, neededVideos} = require('./stage.cjs');
const segLib = require('./segments.cjs');
const records = require('./records.cjs');
const {wavSeconds} = require('./wavinfo.cjs');

const sha256File = (file) => segLib.sha256File ? segLib.sha256File(file) : crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

/**
 * @param {object} o
 *   remotion {bundle, openBrowser, selectComposition, renderMedia}, config, configPath, mode, scale, plan, deps, tailWindow, fonts, hashCache,
 *   entryPoint, rootDir, webpackOverride, browserFile, workdir, label, concurrency, staleRows [{id,start,end_exclusive}], audioStale, scriptSha, remotionVersion, command
 */
function makeInprocRenderer(o) {
  const {remotion, config, plan, mode, scale} = o;
  const timings = {stage: 0, bundle: 0, browser_and_select: 0, segments: 0, audio: 0, framemd5: 0};
  let ready = null;

  async function init() {
    const stagingDir = fs.mkdtempSync(path.join(o.workdir || os.tmpdir(), 'jjk-kit-'));
    let t = Date.now();
    // the frames the stale segments mount (the compositor's own pictureMode / tail windows decide); a stale mix needs every clip staged
    const frames = [];
    if (!o.audioStale) for (const r of o.staleRows) for (const f of segLib.videoFrames(config, o.deps, r.start, r.end_exclusive - 1)) frames.push(f);
    const staged = stage(config, {
      stagingDir, fonts: o.fonts, tailWindow: o.tailWindow, frames: o.audioStale ? undefined : frames, allowPreview: false, requireReceipts: mode === 'master',
      hashCache: o.hashCache || undefined, link: Boolean(o.hashCache),
    });
    timings.stage = (Date.now() - t) / 1000;
    t = Date.now();
    const serveUrl = await remotion.bundle({
      entryPoint: o.entryPoint, outDir: path.join(stagingDir, 'bundle'), publicDir: staged.publicDir, rootDir: o.rootDir, enableCaching: false, webpackOverride: o.webpackOverride,
    });
    timings.bundle = (Date.now() - t) / 1000;
    t = Date.now();
    const {bindings, provenance, ...kitConfig} = config; // the compositor never sees host paths
    const inputProps = {config: kitConfig, scale, label: o.label, previewMark: null, sources: staged.sources, partial: staged.partial};
    const chromiumOptions = {gl: 'swiftshader'};
    const browser = await remotion.openBrowser('chrome', {browserExecutable: o.browserFile, chromiumOptions, logLevel: 'error'});
    const total = config.timeline.mainFrames + config.timeline.endCardFrames;
    const composition = await remotion.selectComposition({serveUrl, id: 'Film', inputProps, puppeteerInstance: browser, logLevel: 'warn'});
    if (composition.durationInFrames !== total || composition.width !== 1920 * scale || composition.height !== 1080 * scale || composition.fps !== config.fps) {
      throw new Error(`composition contract mismatch ${JSON.stringify(composition)}`);
    }
    timings.browser_and_select = (Date.now() - t) / 1000;
    ready = {stagingDir, staged, serveUrl, inputProps, composition, browser, total};
    return ready;
  }

  const baseRecord = (r) => ({
    mode, scale, comp: 'Film', label: o.label, preview_mark: null, reproduction_only: null, config_path: o.configPath, config_sha256: sha256File(o.configPath),
    tail_checks: r.staged.tailChecks, segment_checks: r.staged.segmentChecks, waived: [], warnings: [], compositor_sha256: sha256File(o.entryPoint), render_script_sha256: o.scriptSha,
    remotion_version: o.remotionVersion, chromium_gl: 'swiftshader', concurrency: o.concurrency, gpu_used_deliberately: false, comfyui_called: false, build_mode: 'in-process',
    command: o.command,
  });

  // the staged inputs a segment really mounts: every audio / image input plus only the picture / tail clips its frames use
  function usedFor(r, row) {
    const need = neededVideos(config, segLib.videoFrames(config, o.deps, row.start, row.end_exclusive - 1), o.tailWindow);
    const labels = new Set([...need.segments].map((k) => `clip-${k.split('/')[1]}`).concat([...need.tails].map((id) => `tail-${id}`)));
    return r.staged.used.filter((u) => (u.role === 'picture' || u.role === 'tail' ? labels.has(u.label) : true));
  }

  return {
    async segment(row, tmpDir) {
      const r = ready || await init();
      const codec = segLib.codecParams({mode});
      const out = path.join(tmpDir, 'segment.mp4');
      const range = [row.start, row.end_exclusive - 1];
      const t0 = Date.now();
      await remotion.renderMedia({
        serveUrl: r.serveUrl, composition: r.composition, inputProps: r.inputProps, puppeteerInstance: r.browser, logLevel: 'warn', outputLocation: out,
        codec: codec.codec, pixelFormat: codec.pixelFormat, crf: codec.crf, colorSpace: codec.colorSpace, x264Preset: codec.x264Preset, muted: true, concurrency: o.concurrency,
        frameRange: range, ffmpegOverride: segLib.ffmpegOverride(codec),
      });
      const rendered = Date.now();
      const fm = segLib.framemd5(out);
      const used = usedFor(r, row);
      const seg = {...segLib.segmentRecord(plan, row.id, used), plan_total: plan.total};
      if (fm.md5s.length !== row.frames) throw new Error(`segment ${row.id}: ${fm.md5s.length} frames were encoded, the plan says ${row.frames}`);
      const shotSources = records.shotSources(used);
      const done = Date.now();
      const record = {
        ...baseRecord(r), staged_inputs: used, shot_sources: shotSources, shot_sources_sha256: records.shotSourcesDigest(shotSources),
        output: out, output_sha256: sha256File(out), frame_range: range,
        timing_seconds: {render: (rendered - t0) / 1000, framemd5: (done - rendered) / 1000, total: (done - t0) / 1000},
        segment: seg, codec: {...codec, ffmpegArgs: codec.ffmpegArgs}, framemd5: fm.md5s, framemd5_digest: fm.digest, silent: true, stream: segLib.probeStream(out),
      };
      fs.writeFileSync(`${out}.render-record.json`, `${JSON.stringify(record, null, 2)}\n`);
      timings.segments += (rendered - t0) / 1000;
      timings.framemd5 += (done - rendered) / 1000;
      return (done - t0) / 1000;
    },

    async audio(tmpDir) {
      const r = ready || await init();
      const out = path.join(tmpDir, 'mix.wav');
      const t0 = Date.now();
      await remotion.renderMedia({
        serveUrl: r.serveUrl, composition: r.composition, inputProps: r.inputProps, puppeteerInstance: r.browser, logLevel: 'warn', outputLocation: out, codec: 'wav', sampleRate: 48000,
        concurrency: o.concurrency,
      });
      const samples = Math.round(wavSeconds(out) * 48000);
      const spf = 48000 / config.fps;
      if (Math.abs(samples - r.total * spf) > spf) throw new Error(`audio-only render has ${samples} samples, the film needs ${r.total * spf}`);
      const record = {
        ...baseRecord(r), output: out, output_sha256: sha256File(out), frame_range: null, staged_inputs: r.staged.used,
        audio_only: {sample_rate: 48000, samples, expected_samples: r.total * spf, samples_per_frame: spf, total_frames: r.total},
        timing_seconds: {render: (Date.now() - t0) / 1000, total: (Date.now() - t0) / 1000},
      };
      fs.writeFileSync(`${out}.render-record.json`, `${JSON.stringify(record, null, 2)}\n`);
      timings.audio += (Date.now() - t0) / 1000;
      return (Date.now() - t0) / 1000;
    },

    info: () => ({...timings, staged_hash: ready ? ready.staged.hashStats : null, partial_staging: ready ? ready.staged.partial : null}),

    async close() {
      if (!ready) return;
      try {
        await ready.browser.close({silent: true});
      } finally {
        fs.rmSync(ready.stagingDir, {recursive: true, force: true});
      }
    },
  };
}

module.exports = {makeInprocRenderer};
