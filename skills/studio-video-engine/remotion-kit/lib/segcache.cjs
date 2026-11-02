'use strict';
// Segment cache + incremental build (T-E45 P2, spec 3.2 / 3.3). Pure Node, no Remotion: segments and the one audio mix are rendered by
// CHILD render.cjs runs (--segment / --audio-only), so one slow stage never holds the others and every segment is exactly what the
// ordinary segment render produces. A segment whose node key is already in the cache is not rendered (COMPLETE); a cache entry whose
// bytes no longer match its record is CORRUPT and the build REFUSES (it never joins a segment it cannot vouch for).
//
//   CACHE/composite.segment/<key>/{segment.mp4, segment.mp4.render-record.json, record.json}
//   CACHE/audio.mix/<key>/{mix.wav, mix.wav.render-record.json, record.json}
//   CACHE/last-run.json   the slices of the previous build (what a stale reason is computed against)

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const dep = require('./segdeps.cjs');
const {codecParams, sha256File} = require('./segments.cjs');

const SCHEMA = 'jjk-remotion-kit/segments-run/v1';
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
const sha256Buf = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

// pins: everything outside the config that decides the pixels (or the mix)
function buildPins({kitRoot, mode, scale, remotionVersion, browserFile, fonts, catalogFile, hashFile = sha256File}) {
  const src = path.join(kitRoot, 'src');
  const codec = codecParams({mode});
  const common = {
    remotion: remotionVersion,
    browser: browserFile && fs.existsSync(browserFile) ? hashFile(browserFile) : null,
    gl: 'swiftshader', mode, scale,
    catalog_sha256: catalogFile && fs.existsSync(catalogFile) ? hashFile(catalogFile) : null,
  };
  return {
    video: {
      ...common, kit_src_sha256: dep.sourceSha(src), codec: {...codec, ffmpegArgs: codec.ffmpegArgs},
      fonts: Object.fromEntries(Object.entries(fonts || {}).map(([k, f]) => [k, fs.existsSync(f) ? hashFile(f) : null])),
    },
    audio: {...common, kit_src_sha256: dep.sourceSha(src, {audio: true}), sample_rate: 48000},
  };
}

// ---- the cache -------------------------------------------------------------------------------------------------------------
const entryDir = (cache, kind, key) => path.join(cache, kind, key);

// COMPLETE | MISSING | CORRUPT for one cache entry (kind 'composite.segment' / 'audio.mix')
function lookup(cache, kind, key, fileName, hashFile = sha256File) {
  const dir = entryDir(cache, kind, key);
  const file = path.join(dir, fileName);
  const recordFile = path.join(dir, 'record.json');
  if (!fs.existsSync(recordFile) || !fs.existsSync(file)) return {status: 'MISSING', dir, file};
  let record;
  try {
    record = readJson(recordFile);
  } catch (error) {
    return {status: 'CORRUPT', dir, file, why: `record.json unreadable (${error.message})`};
  }
  if (record.key !== key) return {status: 'CORRUPT', dir, file, why: `record.json names key ${String(record.key).slice(0, 12)}, the folder is ${key.slice(0, 12)}`};
  const actual = hashFile(file);
  if (actual !== record.output_sha256) return {status: 'CORRUPT', dir, file, record, why: `${fileName} sha256 ${actual.slice(0, 12)} differs from its record ${String(record.output_sha256).slice(0, 12)}`};
  const renderRecord = `${file}.render-record.json`;
  if (!fs.existsSync(renderRecord)) return {status: 'CORRUPT', dir, file, record, why: `${fileName}.render-record.json is missing`};
  if (readJson(renderRecord).output_sha256 !== actual) return {status: 'CORRUPT', dir, file, record, why: `${fileName}.render-record.json attests another sha256`};
  return {status: 'COMPLETE', dir, file, record};
}

const lastRunFile = (cache) => path.join(cache, 'last-run.json');
function loadLastRun(cache) {
  try {
    return readJson(lastRunFile(cache));
  } catch {
    return null;
  }
}

// ---- planning --------------------------------------------------------------------------------------------------------------
/**
 * @param {object} config kit config (with the segment list already merged)
 * @param {{segments:Array}} plan planSegments() result
 * @param {{cache:string, mode:string, pins:{video,audio}, deps:object, force?:string[]}} opts
 */
function planBuild(config, plan, opts) {
  const {cache, mode, pins, deps, force = [], hashFile = sha256File} = opts;
  const last = loadLastRun(cache);
  const rows = plan.segments.map((seg) => {
    const slice = dep.videoSlice(config, seg, {deps, mode});
    const key = dep.nodeKey('video', slice, pins.video);
    const found = lookup(cache, 'composite.segment', key, 'segment.mp4', hashFile);
    const prev = last && last.mode === mode ? (last.segments || {})[seg.id] : null;
    let status = found.status === 'COMPLETE' ? 'COMPLETE' : found.status === 'CORRUPT' ? 'CORRUPT' : 'RENDER';
    let reason = null;
    if (status === 'RENDER') reason = prev && prev.key === key ? 'cache entry missing (key unchanged)' : dep.staleReason(prev && prev.parts, slice.parts);
    if (status === 'CORRUPT') reason = `cache entry corrupt: ${found.why}`;
    if (force.includes(seg.id)) {
      status = 'RENDER';
      reason = `forced (--force-segment ${seg.id})`;
    }
    return {id: seg.id, kind: seg.kind, start: seg.start, end_exclusive: seg.end_exclusive, frames: seg.frames, key, status, reason, slice, dir: found.dir, recorded_seconds: found.record ? found.record.render_seconds : null, cache_status: found.status};
  });
  const aslice = dep.audioSlice(config, {mode});
  const akey = dep.nodeKey('audio', aslice, pins.audio);
  const afound = lookup(cache, 'audio.mix', akey, 'mix.wav', hashFile);
  const aprev = last && last.mode === mode ? last.audio : null;
  const audio = {
    key: akey, slice: aslice, dir: afound.dir, cache_status: afound.status, recorded_seconds: afound.record ? afound.record.render_seconds : null,
    status: afound.status === 'COMPLETE' ? 'COMPLETE' : afound.status === 'CORRUPT' ? 'CORRUPT' : 'RENDER',
    reason: afound.status === 'COMPLETE' ? null : afound.status === 'CORRUPT' ? `cache entry corrupt: ${afound.why}` : dep.staleReason(aprev && aprev.parts, aslice.parts),
  };
  return {rows, audio};
}

// printable table (explain / build): one line per segment
function formatTable(built) {
  const pad = (v, n) => String(v).padEnd(n);
  const lines = [`${pad('segment', 14)} ${pad('kind', 11)} ${pad('frames', 13)} ${pad('key', 12)} ${pad('status', 9)} why`];
  for (const r of built.rows) lines.push(`${pad(r.id, 14)} ${pad(r.kind, 11)} ${pad(`${r.start}-${r.end_exclusive - 1}`, 13)} ${pad(r.key.slice(0, 12), 12)} ${pad(r.status, 9)} ${r.reason || ''}`);
  lines.push(`${pad('audio.mix', 14)} ${pad('mix', 11)} ${pad('whole film', 13)} ${pad(built.audio.key.slice(0, 12), 12)} ${pad(built.audio.status, 9)} ${built.audio.reason || ''}`);
  const stale = built.rows.filter((r) => r.status !== 'COMPLETE').length;
  lines.push(`${stale} of ${built.rows.length} segment(s) to render, audio.mix ${built.audio.status === 'COMPLETE' ? 'cached' : 'to render'}`);
  return lines.join('\n');
}

// ---- running ---------------------------------------------------------------------------------------------------------------
function runChild(nodeArgs, label, log) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, nodeArgs, {stdio: ['ignore', 'pipe', 'pipe']});
    let err = '';
    child.stdout.on('data', () => undefined);
    child.stderr.on('data', (d) => {
      err += d.toString();
      if (err.length > 20000) err = err.slice(-10000);
    });
    child.on('error', reject);
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${label} failed (exit ${code}): ${err.trim().split('\n').slice(-6).join(' | ')}`));
      if (log) log(`${label} done`);
    });
  });
}

// store a freshly rendered file under its key: temp folder -> rename (an entry is either whole or absent)
function storeEntry({cache, kind, key, fileName, tmpDir, recordExtra}) {
  const dest = entryDir(cache, kind, key);
  const file = path.join(tmpDir, fileName);
  const record = {schema: `${SCHEMA}/entry`, kind, key, file: fileName, output_sha256: sha256File(file), bytes: fs.statSync(file).size, created: new Date().toISOString(), ...recordExtra};
  fs.writeFileSync(path.join(tmpDir, 'record.json'), `${JSON.stringify(record, null, 2)}\n`);
  fs.mkdirSync(path.dirname(dest), {recursive: true});
  fs.rmSync(dest, {recursive: true, force: true});
  fs.renameSync(tmpDir, dest);
  return record;
}

/**
 * Render what is stale, refuse what is corrupt, join. Two ways to render, one result on disk:
 *   `renderer` {segment(row, tmpDir), audio(tmpDir), info(), close()} = the IN-PROCESS renderer (lib/inproc.cjs: one staging, one bundle, one browser), or
 *   `childArgs(id, file)` / `audioChildArgs(file)` = argv of a CHILD render.cjs per segment (the original path, kept as `--build-mode children`).
 * `hashFile` verifies cache entries (a verified-hash cache makes an unchanged entry cost a stat); `joinSegments` is tools/join-segments.cjs, called
 * in its fast mode (segments attested by sha256 + recorded frame hashes, the film decoded once).
 * `sources` {key: sha256} = the shot sources of this build (pictures, tails, dialogue WAVs); the previous build's map is in last-run.json, and the run
 * record says whether this build was COMPOSITE-ONLY (no shot source changed) or which changed.
 */
async function runBuild({config, built, cache, out, overwrite, joinSegments, childArgs, audioChildArgs, renderer, hashFile = sha256File, plan, mode, pins, segmentsFile, configFile, configSha, kitRoot, sources, hashStats, log = () => undefined}) {
  const corrupt = built.rows.filter((r) => r.status === 'CORRUPT').concat(built.audio.status === 'CORRUPT' ? [{id: 'audio.mix', reason: built.audio.reason}] : []);
  const started = Date.now();
  const rendered = [];
  // a segment is stored under the key computed from the kit source at the START of the build: if that source changed while it rendered,
  // the entry would carry a key it was not rendered under, so the build stops instead of storing it
  const sourceUnchanged = (what) => {
    if (kitRoot && dep.sourceSha(path.join(kitRoot, 'src')) !== pins.video.kit_src_sha256) throw new Error(`the kit source changed while ${what} was rendering: nothing was stored under the old key; run the build again`);
  };
  // CORRUPT is refused, never silently re-rendered: a cache that lies about itself is a finding, not a miss. --force-segment overrides a segment.
  const refused = corrupt.filter((r) => !(r.id !== 'audio.mix' && r.status === 'RENDER'));
  if (refused.length) throw new Error(`segment cache refused: ${refused.map((r) => `${r.id}: ${r.reason}`).join('; ')} (re-render with --force-segment ID, or delete the entry)`);
  fs.mkdirSync(cache, {recursive: true});
  try {
    for (const row of built.rows) {
      if (row.status !== 'RENDER') continue;
      const tmp = path.join(cache, 'composite.segment', `.tmp-${row.key.slice(0, 16)}-${process.pid}`);
      fs.rmSync(tmp, {recursive: true, force: true});
      fs.mkdirSync(tmp, {recursive: true});
      const t0 = Date.now();
      if (renderer) await renderer.segment(row, tmp);
      else await runChild(childArgs(row.id, path.join(tmp, 'segment.mp4')), `segment ${row.id}`, log);
      sourceUnchanged(`segment ${row.id}`);
      const seconds = (Date.now() - t0) / 1000;
      storeEntry({
        cache, kind: 'composite.segment', key: row.key, fileName: 'segment.mp4', tmpDir: tmp,
        recordExtra: {id: row.id, kind: row.kind, start: row.start, end_exclusive: row.end_exclusive, frames: row.frames, render_seconds: seconds, pins: pins.video, slice: row.slice.parts},
      });
      row.render_seconds = seconds;
      rendered.push(row.id);
      log(`rendered ${row.id} (${row.start}-${row.end_exclusive - 1}) in ${seconds.toFixed(1)}s`);
    }
    if (built.audio.status === 'RENDER') {
      const tmp = path.join(cache, 'audio.mix', `.tmp-${built.audio.key.slice(0, 16)}-${process.pid}`);
      fs.rmSync(tmp, {recursive: true, force: true});
      fs.mkdirSync(tmp, {recursive: true});
      const t0 = Date.now();
      if (renderer) await renderer.audio(tmp);
      else await runChild(audioChildArgs(path.join(tmp, 'mix.wav')), 'audio.mix', log);
      if (kitRoot && dep.sourceSha(path.join(kitRoot, 'src'), {audio: true}) !== pins.audio.kit_src_sha256) throw new Error('the kit source changed while the audio mix was rendering: nothing was stored under the old key; run the build again');
      const seconds = (Date.now() - t0) / 1000;
      storeEntry({cache, kind: 'audio.mix', key: built.audio.key, fileName: 'mix.wav', tmpDir: tmp, recordExtra: {render_seconds: seconds, pins: pins.audio, slice: built.audio.slice.parts}});
      built.audio.render_seconds = seconds;
      rendered.push('audio.mix');
    }
  } finally {
    if (renderer) await renderer.close();
  }
  const renderEnd = Date.now();
  // every file is verified again right before it is joined (the join re-verifies sha + the recorded frame hashes; the film is decoded once)
  const files = built.rows.map((r) => {
    const f = lookup(cache, 'composite.segment', r.key, 'segment.mp4', hashFile);
    if (f.status !== 'COMPLETE') throw new Error(`segment cache refused: ${r.id}: ${f.why || f.status}`);
    return f.file;
  });
  const mix = lookup(cache, 'audio.mix', built.audio.key, 'mix.wav', hashFile);
  if (mix.status !== 'COMPLETE') throw new Error(`segment cache refused: audio.mix: ${mix.why || mix.status}`);
  const joinStart = Date.now();
  const join = await joinSegments({segments: files, audio: mix.file, out, overwrite, fps: config.fps, cache: true, expectedTotal: plan.total, fast: {hashFile}});
  const finished = Date.now();
  const reused = built.rows.filter((r) => r.status === 'COMPLETE');
  const savedSeconds = reused.reduce((a, r) => a + (r.recorded_seconds || 0), 0) + (built.audio.status === 'COMPLETE' ? built.audio.recorded_seconds || 0 : 0);
  const last = loadLastRun(cache);
  const composite = sources ? compositeOnlyVsLast(sources, last && last.mode === mode ? last.sources : null) : null;
  const run = {
    schema: SCHEMA, mode, config: configFile, config_sha256: configSha, segments_file: segmentsFile || null, plan_sha256: plan.sha256, total_frames: plan.total,
    build_mode: renderer ? 'in-process' : 'children',
    segments: built.rows.map((r) => ({id: r.id, kind: r.kind, start: r.start, end_exclusive: r.end_exclusive, frames: r.frames, key: r.key, status: r.status, reason: r.reason, render_seconds: r.render_seconds === undefined ? null : r.render_seconds, cache_entry: r.dir})),
    audio: {key: built.audio.key, status: built.audio.status, reason: built.audio.reason, render_seconds: built.audio.render_seconds === undefined ? null : built.audio.render_seconds, cache_entry: built.audio.dir},
    rendered, reused: reused.map((r) => r.id), segments_rendered: rendered.filter((x) => x !== 'audio.mix').length, segments_reused: reused.length,
    estimated_seconds_saved: Math.round(savedSeconds * 10) / 10,
    ...(composite ? {composite_only: composite} : {}),
    film: {path: path.resolve(out), sha256: join.film.sha256, frames: join.film.frames}, join_record: `${path.resolve(out)}.join-record.json`,
    timing_seconds: {render: (renderEnd - started) / 1000, join_verify: (joinStart - renderEnd) / 1000, join: (finished - joinStart) / 1000, total: (finished - started) / 1000, ...(renderer ? {renderer: renderer.info()} : {})},
    ...(hashStats ? {hash_cache: hashStats()} : {}),
  };
  fs.writeFileSync(path.join(cache, 'segments-run.json'), `${JSON.stringify(run, null, 2)}\n`);
  fs.writeFileSync(`${path.resolve(out)}.segments-run.json`, `${JSON.stringify(run, null, 2)}\n`);
  fs.writeFileSync(lastRunFile(cache), `${JSON.stringify({
    schema: `${SCHEMA}/last`, mode, plan_sha256: plan.sha256,
    segments: Object.fromEntries(built.rows.map((r) => [r.id, {key: r.key, parts: r.slice.parts}])), audio: {key: built.audio.key, parts: built.audio.slice.parts}, sources: sources || null,
  })}\n`);
  return {run, join};
}

// the shot sources (pictures, tails, dialogue WAVs) of this build against the previous build: a build in which none changed is COMPOSITE-ONLY
function compositeOnlyVsLast(sources, previous) {
  if (!previous) return {value: null, statement: 'composite-only: unknown (no previous build in this cache)', unchanged: 0, changed: []};
  const keys = [...new Set([...Object.keys(previous), ...Object.keys(sources)])].sort();
  const changed = keys.filter((k) => previous[k] !== sources[k]).map((k) => (k in sources ? (k in previous ? `${k}: ${String(previous[k]).slice(0, 12)} -> ${String(sources[k]).slice(0, 12)}` : `+${k}`) : `-${k}`));
  return {
    value: changed.length === 0, unchanged: keys.length - changed.length, changed,
    statement: changed.length === 0 ? `composite-only: no shot source changed vs the previous build (${keys.length} sources compared)` : `NOT composite-only: ${changed.length} shot source(s) changed: ${changed.slice(0, 6).join('; ')}`,
  };
}

// {key: sha256} of every shot source the config binds: picture clips, tail clips, dialogue WAVs
function shotSourceMap(config) {
  const out = {};
  const b = config.bindings || {};
  for (const [shot, sb] of Object.entries(b.shots || {})) {
    if (sb.audio) out[`dialogue:${shot}`] = sb.audio.sha256;
    for (const [seg, binding] of Object.entries(sb.segments || {})) out[`picture:${shot}/${seg}`] = binding.sha256;
  }
  for (const [id, binding] of Object.entries(b.tails || {})) out[`tail:${id}`] = binding.sha256;
  return out;
}

module.exports = {SCHEMA, buildPins, lookup, planBuild, formatTable, runBuild, loadLastRun, entryDir, sha256Buf, shotSourceMap, compositeOnlyVsLast};
