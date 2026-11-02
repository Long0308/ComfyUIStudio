#!/usr/bin/env node
'use strict';
// remotion-kit renderer: review cut (scale 1, labelled) or 4K master (scale 2, no label) from ONE kit config.
// CPU only: Remotion + SwiftShader GL, no GPU, no ComfyUI, concurrency <= 2.
//
//   node render.cjs --config kit-config.json --mode review --out cut.mp4 [--overwrite]          full render
//   node render.cjs --config C --stills "name:frame,name:frame" --outdir D                       stills (PNG)
//   node render.cjs --config C --still N --out frame.png                                         one still
//   node render.cjs --config C --range A-B --out clip.mp4                                        partial render
//   node render.cjs --config C --range A-B --png-seq DIR                                         PNG sequence (parity checks)
//   --mode master  -> scale 2, no label (a label is refused);  --mode review -> scale 1, label = config.review.label
//   --comp Film|EndLogo  --scale N  --concurrency 1|2  --preview  --stage-needed  --browser PATH (or REMOTION_BROWSER)
//   --jsx-loader no-child  (in-process babel JSX loader for sandboxes that block esbuild's helper process)
//   --reproduction-only DIR  parity / reproduction runs only: every output must be inside DIR, the record is stamped, reproduction-only
//                          waivers are accepted; with --drop-preview-mark (stills only) the PREVIEW mark is omitted. --no-preview-mark no longer exists.
//   --check-only           validate config + bundle + select composition, render nothing
//   --list-presets [--boundary ID|FRAME] [--mode review|master] [--master-config F] [--catalog F]
//                          print, per boundary, which transition presets the bound tail handles can play (engine tail rule), then exit:
//                          no bundling, no browser, only --config. A transition is a compositing layer: changing one never re-renders a shot.
//   --segments-plan        print the segment plan (main + ending, or config.segments) and exit: no bundling, no browser
//   --segment ID           render ONE segment of the plan as SILENT closed-GOP video (one codec set for every segment, recorded); needs --out.
//                          Stages only the shot videos its frames really mount (an ending segment stages none). Join with tools/join-segments.cjs.
//   --segments-file F      the engine's segments.json (jjv/segments/v1) becomes config.segments (refused when its fps / total_frames differ from the config)
//   --segments-build CACHE [--out film.mp4] [--explain] [--force-segment ID[,ID]] [--build-concurrency 1|2]
//                          incremental build (T-E45 P2): each segment has a node key (its dependency slice + pins); a key already in CACHE is not
//                          rendered, the rest are (child --segment runs), the one audio mix is cached by its own key, then everything is joined by
//                          stream copy (tools/join-segments.cjs) and segments-run.json says which segments rendered and why. --explain computes
//                          and prints the table WITHOUT rendering. A cache entry that no longer matches its record is refused.
//   --audio-only           render the whole-film audio once as 48 kHz PCM wav (--out mix.wav); the audio is never cut at a segment join
//   --segments-build CACHE --out F [--segments-file S] [--explain] [--force-segment IDS] [--build-mode inproc|children] [--rehash-all] [--no-hash-cache] [--workdir D]
//                          incremental film: render only the stale segments (in-process: one staging, one bundle, one browser), join with the proof
//   --previous-record F    the record of an earlier render: this record then carries composite_only (no shot source changed vs F, or which did)

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {createRequire} = require('node:module');
const {pathToFileURL} = require('node:url');
const {stage, sha256} = require('./lib/stage.cjs');
const records = require('./lib/records.cjs');
const segments = require('./lib/segments.cjs');
const segcache = require('./lib/segcache.cjs');
const {probeClip} = require('./lib/tailcheck.cjs');
const {HashCache, NoCache} = require('./lib/hashcache.cjs');
const {makeInprocRenderer} = require('./lib/inproc.cjs');
const {verifyBindings} = require('./lib/verify-bindings.cjs');

const KIT = __dirname;
const WORKSPACE = path.resolve(KIT, '../../../..');
const PACKAGES = process.env.REMOTION_PACKAGES || path.join(WORKSPACE, 'jenniejoy-zoo-film', 'node_modules');
const ENTRY = path.join(KIT, 'src', 'index.jsx');

const option = (args, name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};

// Remotion must not download anything here: the cached headless shell is named by --browser or REMOTION_BROWSER (the kit does not
// scan any episode folder for one; an episode runner passes its own path).
function findBrowser(explicit) {
  const candidate = explicit || process.env.REMOTION_BROWSER;
  if (!candidate) throw new Error('no browser: pass --browser PATH or set REMOTION_BROWSER (a cached chrome-headless-shell; the kit never downloads or searches for one)');
  if (!fs.existsSync(candidate)) throw new Error(`browser not found: ${candidate}`);
  return candidate;
}

function defaultFonts(config) {
  const f = (config.bindings && config.bindings.fonts) || {};
  return {
    regular: f.regular || path.join(process.env.WINDIR || 'C:/Windows', 'Fonts', 'trebuc.ttf'),
    bold: f.bold || path.join(WORKSPACE, 'jenniejoy-zoo-film', 'hyperframes', 'vendor', 'trebucbd.ttf'),
  };
}

function noChildWebpackOverride(webpack) {
  const loader = path.join(KIT, 'lib', 'jsx-loader-no-child.cjs');
  const rules = (webpack.module?.rules || []).map((rule) => (
    rule && rule.test instanceof RegExp && rule.test.source === '\\.jsx?$' ? {...rule, use: [{loader}]} : rule
  ));
  return {
    ...webpack,
    module: {...webpack.module, rules},
    resolve: {...webpack.resolve, modules: [PACKAGES, ...(webpack.resolve?.modules || ['node_modules'])]},
  };
}

function defaultWebpackOverride(webpack) {
  return {...webpack, resolve: {...webpack.resolve, modules: [PACKAGES, ...(webpack.resolve?.modules || ['node_modules'])]}};
}

// the preset catalog is the engine's single source of truth (schemas/transition-presets.json next to the kit's parent skill)
function loadCatalog(explicit) {
  const file = explicit ? path.resolve(explicit) : path.join(KIT, '..', 'schemas', 'transition-presets.json');
  if (!fs.existsSync(file)) return {file, catalog: null};
  return {file, catalog: JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/u, ''))};
}

// native frame rate of every bound tail file (ffprobe, no decode), for configs whose tail carries no nativeFps
function nativeFpsMap(config) {
  const map = {};
  for (const t of config.transitions || []) {
    const binding = t.tail && !t.tail.nativeFps && config.bindings && (config.bindings.tails || {})[t.id];
    const file = binding && (binding.materialized || binding).path;
    if (file && fs.existsSync(file)) {
      try {
        map[t.id] = probeClip(file).nativeFps;
      } catch (error) {
        process.stderr.write(`note: could not probe ${file} (${error.message.split('\n')[0]}); the tail frame rate is derived from the editorial cut\n`);
      }
    }
  }
  return map;
}

function parseRange(text, total) {
  const r = text.split('-').map(Number);
  if (r.length !== 2 || r.some((n) => !Number.isInteger(n)) || r[0] < 0 || r[1] < r[0] || r[1] >= total) throw new Error(`Invalid --range ${text} (film has ${total} frames)`);
  return r;
}

// the compositor functions the segment plan needs (picture mode, tail windows, resolved motion), injected into lib/segments.cjs
async function segmentDeps(config) {
  const pm = await import(pathToFileURL(path.join(KIT, 'src', 'picture-mode.mjs')).href);
  const presets = await import(pathToFileURL(path.join(KIT, 'src', 'presets.mjs')).href);
  return {
    pictureMode: pm.pictureMode, transitionIndex: pm.transitionIndex, tailWindow: pm.tailWindow, tailVisibleAt: pm.tailVisibleAt,
    motion: presets.resolveMotion(config), rendersAs: presets.rendersAs, scheduleOf: presets.scheduleOf, showsBoth: (t) => Boolean((pm.TYPE_TABLE[t.type] || pm.TYPE_TABLE[t.preset] || {}).showsBoth),
  };
}

// framemd5 md5 column of a file, for the segment record and the join
function frameHashes(file) {
  const fm = segments.framemd5(file);
  return {md5: fm.md5s, digest: fm.digest, frames: fm.md5s.length};
}


// the engine's segments.json -> config.segments (the cut list render.cjs already validates); the fps and the total must be the config's own
function mergeSegmentsFile(config, file, total) {
  if (config.segments !== undefined) throw new Error('the config already declares segments: --segments-file would be a second cut list');
  const doc = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
  if (typeof doc.schema !== 'string' || !doc.schema.startsWith('jjv/segments/')) throw new Error(`${file}: schema must be jjv/segments/v1 (got ${doc.schema})`);
  if (doc.fps !== config.fps) throw new Error(`${file}: fps ${doc.fps} differs from the config fps ${config.fps}`);
  if (doc.total_frames !== total) throw new Error(`${file}: total_frames ${doc.total_frames} differs from the config's ${total} frames`);
  if (!Array.isArray(doc.segments) || !doc.segments.length) throw new Error(`${file}: segments[] is empty`);
  return doc.segments.map(({id, kind, start, end_exclusive: endExclusive}) => ({id, kind, start, end_exclusive: endExclusive}));
}

// --segments-build: node keys, explain, render what is stale, join. See lib/segcache.cjs and lib/inproc.cjs.
//   --build-mode inproc|children   inproc (default): ONE staging, ONE bundle, ONE browser for every stale segment; children: one render.cjs child per segment
//   --rehash-all                   audit: ignore the verified-hash cache, read and hash every byte again
//   --no-hash-cache                do not use / write CACHE/hash-cache.json at all
async function segmentsBuild({args, config, configPath, mode, scale, plan, deps, segmentsFile, catalogFile, tailWindow, collectWaived}) {
  const cache = path.resolve(option(args, '--segments-build'));
  const explainOnly = args.includes('--explain');
  const out = option(args, '--out');
  if (!explainOnly && !out) throw new Error('--segments-build needs --out FILE.mp4 (or --explain)');
  if (option(args, '--range') !== undefined || option(args, '--segment') !== undefined || args.includes('--audio-only') || option(args, '--stills') !== undefined) throw new Error('--segments-build builds the whole film: no --range / --segment / --audio-only / --stills');
  const buildMode = option(args, '--build-mode') || 'inproc';
  if (!['inproc', 'children'].includes(buildMode)) throw new Error('--build-mode must be inproc or children');
  const browser = findBrowser(option(args, '--browser'));
  const localRequire = createRequire(path.join(PACKAGES, 'remotion', 'package.json'));
  const hashCache = args.includes('--no-hash-cache') ? new NoCache() : new HashCache({file: path.join(cache, 'hash-cache.json'), rehashAll: args.includes('--rehash-all')});
  const hashFile = (f) => hashCache.sha256(f);
  const tHash = Date.now();
  const pins = segcache.buildPins({kitRoot: KIT, mode, scale, remotionVersion: localRequire('remotion/package.json').version, browserFile: browser, fonts: defaultFonts(config), catalogFile, hashFile});
  const force = (option(args, '--force-segment') || '').split(',').filter(Boolean);
  for (const id of force) if (!plan.segments.some((s) => s.id === id)) throw new Error(`--force-segment ${id}: not a segment of the plan (${plan.segments.map((s) => s.id).join(', ')})`);
  const built = segcache.planBuild(config, plan, {cache, mode, pins, deps, force, hashFile});
  const planSeconds = (Date.now() - tHash) / 1000;
  process.stdout.write(`${segcache.formatTable(built)}\n`);
  // --verify-bindings: every bound file hashes to its recorded sha256 (and, in master mode, every final carries its receipt) without staging anything;
  // with the verified-hash cache an unchanged 4K core costs a stat (--rehash-all is the audit path)
  if (args.includes('--verify-bindings')) {
    const v = verifyBindings(config, {hashCache, requireReceipts: mode === 'master'});
    process.stdout.write(`verify-bindings: ${v.verified}/${v.files} verified in ${v.seconds.toFixed(2)} s; hash cache ${v.hash_cache.hits} hit(s), ${v.hash_cache.misses} miss(es), ${(v.hash_cache.bytes_not_read / 1048576).toFixed(1)} MiB not read, ${(v.hash_cache.bytes_read / 1048576).toFixed(1)} MiB read\n`);
    if (v.problems.length) throw new Error(`bindings do not verify:\n - ${v.problems.join('\n - ')}`);
  }
  if (explainOnly) {
    hashCache.save();
    if (args.includes('--json')) {
      process.stdout.write(`${JSON.stringify({plan_sha256: plan.sha256, plan_seconds: planSeconds, hash_cache: hashCache.stats(), rows: built.rows.map(({slice, ...r}) => r), audio: (({slice, ...r}) => r)(built.audio)}, null, 2)}\n`);
    }
    return;
  }
  // the gates every ordinary render runs (render.cjs main): waivers, the review label, master scale, previews (stage refuses a preview binding)
  const waived = collectWaived(config);
  if (waived.some((w) => w.reproduction_only)) throw new Error(`reproduction-only waivers (${waived.filter((w) => w.reproduction_only).map((w) => `${w.rule}@${w.transition}`).join(', ')}) are not approvals: a segment build refuses them (use render.cjs --reproduction-only DIR on stills)`);
  if (waived.length && mode === 'master') throw new Error(`a master-mode build refuses waived rules (${waived.map((w) => `${w.rule}@${w.transition}`).join(', ')}); waivers exist only to reproduce a historical review cut`);
  for (const w of waived) process.stderr.write(`WAIVED ${w.rule} on ${w.transition}: ${w.reason} [approved_by ${w.approved_by} at ${w.approved_at}, review render ${w.review_render_sha256}]\n`);
  if (mode === 'master' && scale < 2) throw new Error('master mode needs scale >= 2');
  let label = null;
  if (mode === 'review') {
    label = option(args, '--label') || (config.review && config.review.label);
    if (!label) throw new Error('review mode needs config.review.label (G-LABEL)');
    if (config.review && config.review.label && label !== config.review.label) throw new Error('--label differs from config.review.label (G-LABEL)');
  } else if (option(args, '--label')) {
    throw new Error('the master carries no review label (G-LABEL)');
  }
  const buildConcurrency = Number(option(args, '--build-concurrency') || 2);
  if (![1, 2].includes(buildConcurrency)) throw new Error('--build-concurrency must be 1 or 2');
  const {joinSegments} = require('./tools/join-segments.cjs');
  const jsxNoChild = option(args, '--jsx-loader') === 'no-child';
  const common = {
    config, built, cache, out, overwrite: args.includes('--overwrite'), joinSegments, plan, mode, pins, segmentsFile, configFile: configPath, configSha: sha256(configPath), kitRoot: KIT,
    hashFile, sources: segcache.shotSourceMap(config), hashStats: () => hashCache.stats(), log: (line) => process.stderr.write(`${line}\n`),
  };
  let renderer = null;
  if (buildMode === 'inproc') {
    const remotion = {bundle: localRequire('@remotion/bundler').bundle, ...localRequire('@remotion/renderer')};
    renderer = makeInprocRenderer({
      remotion, config, configPath, mode, scale, plan, deps, tailWindow, fonts: defaultFonts(config), hashCache, entryPoint: ENTRY, rootDir: WORKSPACE,
      webpackOverride: jsxNoChild ? noChildWebpackOverride : defaultWebpackOverride, browserFile: browser, workdir: option(args, '--workdir'), label, concurrency: buildConcurrency,
      staleRows: built.rows.filter((r) => r.status === 'RENDER'), audioStale: built.audio.status === 'RENDER', scriptSha: sha256(__filename),
      remotionVersion: localRequire('remotion/package.json').version, command: `node render.cjs ${args.join(' ')}`,
    });
  }
  const pass = ['--workdir', '--catalog'].flatMap((f) => (option(args, f) !== undefined ? [f, option(args, f)] : []));
  if (option(args, '--jsx-loader') !== undefined) pass.push('--jsx-loader', option(args, '--jsx-loader'));
  const childCommon = ['--config', configPath, ...(segmentsFile ? ['--segments-file', segmentsFile] : []), '--mode', mode, '--scale', String(scale), '--concurrency', String(buildConcurrency), '--browser', browser, ...pass];
  try {
    const {run} = await segcache.runBuild({
      ...common, renderer,
      childArgs: (id, file) => [path.join(KIT, 'render.cjs'), ...childCommon, '--segment', id, '--out', file],
      audioChildArgs: (file) => [path.join(KIT, 'render.cjs'), ...childCommon, '--audio-only', '--out', file],
    });
    process.stdout.write(`built ${run.film.path}: ${run.film.frames} frames; segments rendered ${run.segments_rendered}, reused ${run.segments_reused}; audio.mix ${run.audio.status}; join proof H_film == H_seg; ~${run.estimated_seconds_saved}s of cached render time reused\n`);
    if (run.composite_only) process.stdout.write(`${run.composite_only.statement}\n`);
    const hs = hashCache.stats();
    process.stdout.write(`hash cache: ${hs.hits} hit(s), ${hs.misses} miss(es), ${(hs.bytes_not_read / 1048576).toFixed(1)} MiB not read, ${(hs.bytes_read / 1048576).toFixed(1)} MiB read${hs.rehash_all ? ' (--rehash-all audit)' : ''}\n`);
  } finally {
    hashCache.save();
  }
}

// kit.mode (set by lib/adapter-master.cjs): "preview" = at least one source is a stand-in (stills / ranges only), "final" = every source is receipt-bound.
// A preview kit is refused for a master render unless --preview (which itself refuses a full render, see below).
function refusePreviewKit(config, mode, preview) {
  if (config.mode === undefined) return;
  if (!['preview', 'final'].includes(config.mode)) throw new Error(`config.mode must be "preview" or "final" (got ${JSON.stringify(config.mode)})`);
  if (mode === 'master' && config.mode === 'preview' && !preview) {
    throw new Error('this kit config is marked mode "preview" (it binds preview sources or was built with the adapter preview opt-in): it is not a master; render stills or a partial --range with --preview, or build a final kit');
  }
}

async function main() {
  const args = process.argv.slice(2);
  const configPath = path.resolve(option(args, '--config') || '');
  if (!option(args, '--config') || !fs.existsSync(configPath)) throw new Error('--config <kit-config.json> is required');
  const mode = option(args, '--mode') || 'review';
  if (!['review', 'master'].includes(mode)) throw new Error('--mode must be review or master');
  const scale = Number(option(args, '--scale') || (mode === 'master' ? 2 : 1));
  const concurrency = Number(option(args, '--concurrency') || 2);
  if (![1, 2].includes(concurrency)) throw new Error('--concurrency must be 1 or 2 (CPU-only renderer)');
  const compId = option(args, '--comp') || 'Film';
  const preview = args.includes('--preview');
  const overwrite = args.includes('--overwrite');
  const stillsArg = option(args, '--stills');
  const stillArg = option(args, '--still');
  const segmentId = option(args, '--segment');
  const audioOnly = args.includes('--audio-only');
  if (segmentId !== undefined && option(args, '--range') !== undefined) throw new Error('--segment and --range both choose frames: use one');
  if (audioOnly && (segmentId !== undefined || option(args, '--range') !== undefined || stillsArg || stillArg || option(args, '--png-seq'))) throw new Error('--audio-only renders the whole film audio: it takes no --segment / --range / --stills / --png-seq');
  let rangeArg = option(args, '--range');
  const pngSeq = option(args, '--png-seq');
  let partialRun = Boolean(stillsArg || stillArg || rangeArg);

  const config = JSON.parse(fs.readFileSync(configPath, 'utf8').replace(/^\uFEFF/u, ''));
  refusePreviewKit(config, mode, preview);
  const {validateConfig, totalFrames, collectWaived, collectWarnings} = await import(pathToFileURL(path.join(KIT, 'src', 'validate.mjs')).href);
  const {tailWindow} = await import(pathToFileURL(path.join(KIT, 'src', 'picture-mode.mjs')).href);
  const feasibility = await import(pathToFileURL(path.join(KIT, 'src', 'feasibility.mjs')).href);
  const loaded = loadCatalog(option(args, '--catalog'));
  if (args.includes('--list-presets')) {
    if (!loaded.catalog) throw new Error(`preset catalog not found: ${loaded.file}`);
    const masterFile = option(args, '--master-config');
    const masterConfig = masterFile ? JSON.parse(fs.readFileSync(path.resolve(masterFile), 'utf8').replace(/^\uFEFF/u, '')) : undefined;
    const boundary = option(args, '--boundary');
    const refs = boundary !== undefined ? [boundary] : (config.transitions || []).map((t) => t.id);
    const nativeFps = {...nativeFpsMap(config), ...(masterConfig ? nativeFpsMap(masterConfig) : {})};
    const table = refs.map((ref) => feasibility.presetAvailability(config, ref, {mode, catalog: loaded.catalog, masterConfig, nativeFps}));
    process.stdout.write(`${JSON.stringify({
      config: configPath, mode, fps: config.fps, catalog: loaded.file, master_config: masterFile ? path.resolve(masterFile) : null, rule: 'a preset that plays the outgoing tail needs ceil(4N/5) native frames beyond the editorial cut and its last index inside the file; no GPU work is ever requested', boundaries: table,
    }, null, 2)}\n`);
    return;
  }
  validateConfig(config);
  const segmentsFileArg = option(args, '--segments-file');
  if (segmentsFileArg !== undefined) config.segments = mergeSegmentsFile(config, path.resolve(segmentsFileArg), totalFrames(config));
  // warnings (e.g. a visible transition on a same_framing boundary) never refuse a render: they are printed and recorded
  const warnings = collectWarnings(config);
  for (const w of warnings) process.stderr.write(`WARNING: ${w}\n`);
  // a chosen tail preset with a missing or short handle is refused here, before any bundling, naming the boundary and the missing frames
  if (loaded.catalog) {
    const handleIssues = feasibility.tailHandleIssues(config, {catalog: loaded.catalog, nativeFps: nativeFpsMap(config)});
    if (handleIssues.length) throw new Error(`transition tail handles:\n - ${handleIssues.join('\n - ')}`);
  } else {
    process.stderr.write(`note: preset catalog not found (${loaded.file}); the tail-handle precheck was skipped, stage() still probes every bound tail file\n`);
  }
  if (option(args, '--segments-build') !== undefined) {
    const plan = segments.planSegments(config, await segmentDeps(config));
    await segmentsBuild({args, config, configPath, mode, scale, plan, deps: await segmentDeps(config), segmentsFile: segmentsFileArg === undefined ? null : path.resolve(segmentsFileArg), catalogFile: loaded.file, tailWindow, collectWaived});
    return;
  }
  const wantsPlan = args.includes('--segments-plan') || segmentId !== undefined;
  const plan = wantsPlan ? segments.planSegments(config, await segmentDeps(config)) : null;
  if (args.includes('--segments-plan')) {
    const deps = await segmentDeps(config);
    const withVideo = plan.segments.map((s) => ({...s, shot_video_frames: segments.videoFrames(config, deps, s.start, s.end_exclusive - 1).length}));
    process.stdout.write(`${JSON.stringify({...plan, segments: withVideo, config: configPath, codec: segments.codecParams({mode}), audio: 'one mix for the whole film (render.cjs --audio-only), never cut at a join', samples_per_frame: segments.SAMPLES_PER_SECOND / config.fps}, null, 2)}
`);
    return;
  }
  let segment = null;
  if (segmentId !== undefined) {
    segment = plan.segments.find((x) => x.id === segmentId);
    if (!segment) throw new Error(`unknown segment ${segmentId} (the plan has: ${plan.segments.map((x) => x.id).join(', ')})`);
    if (!option(args, '--out') && !option(args, '--png-seq')) throw new Error('--segment needs --out FILE.mp4 (or --png-seq DIR for the pixel-parity check)');
    rangeArg = `${segment.start}-${segment.end_exclusive - 1}`;
    partialRun = true;
    // --within A-B (PNG sequences only): a few frames of the segment, for the pixel-parity check against the same frames of the full film
    const within = option(args, '--within');
    if (within !== undefined) {
      if (!pngSeq) throw new Error('--within A-B only applies to --segment with --png-seq');
      const [a, b] = within.split('-').map(Number);
      if (!Number.isInteger(a) || !Number.isInteger(b) || a < segment.start || b >= segment.end_exclusive || b < a) throw new Error(`--within ${within} must lie inside segment ${segment.id} (f${segment.start}-${segment.end_exclusive - 1})`);
      rangeArg = within;
      segment = {...segment, start: a, end_exclusive: b + 1, frames: b - a + 1, within: true};
    }
  }
  if (audioOnly && !option(args, '--out')) throw new Error('--audio-only needs --out FILE.wav');
  const previousRecord = option(args, '--previous-record');
  if (previousRecord !== undefined && !fs.existsSync(path.resolve(previousRecord))) throw new Error(`--previous-record ${previousRecord}: previous record is missing`);
  const waived = collectWaived(config);
  const total = compId === 'EndLogo' ? config.timeline.endCardFrames : totalFrames(config);
  // What counts as a FULL render for every gate: no partial option at all, or a --range that covers the whole film. Stills are the
  // only partial runs that may use preview sources without the PREVIEW mark, or waivers in master mode.
  const isStills = Boolean(stillsArg || stillArg);
  const range = rangeArg ? parseRange(rangeArg, total) : null;
  const coversFilm = Boolean(range && range[0] === 0 && range[1] >= total - 1);
  const fullRender = !isStills && (!range || coversFilm);
  const reproDir = option(args, '--reproduction-only') ? path.resolve(option(args, '--reproduction-only')) : null;
  if (waived.some((w) => w.reproduction_only) && !reproDir) {
    throw new Error(`reproduction-only waivers (${waived.filter((w) => w.reproduction_only).map((w) => `${w.rule}@${w.transition}`).join(', ')}) are not approvals: the render needs --reproduction-only DIR (outputs inside DIR)`);
  }
  if (waived.length && mode === 'master' && !isStills) {
    throw new Error(`a master-mode render (full or --range) refuses waived rules (${waived.map((w) => `${w.rule}@${w.transition}`).join(', ')}); waivers exist only to reproduce a historical review cut, master stills for parity are the one exception`);
  }
  for (const w of waived) {
    process.stderr.write(`WAIVED ${w.rule} on ${w.transition}: ${w.reason} [${w.reproduction_only ? 'REPRODUCTION ONLY, not an approval' : `approved_by ${w.approved_by} at ${w.approved_at}`}, review render ${w.review_render_sha256}]\n`);
  }

  // G-LABEL: a review cut carries exactly config.review.label on screen; the master carries none
  let label = null;
  if (compId === 'Film') {
    if (mode === 'review') {
      label = option(args, '--label') || (config.review && config.review.label);
      if (!label) throw new Error('review mode needs config.review.label (G-LABEL)');
      if (config.review && config.review.label && label !== config.review.label) throw new Error('--label differs from config.review.label (G-LABEL)');
    } else if (option(args, '--label')) {
      throw new Error('the master carries no review label (G-LABEL)');
    }
  }
  if (mode === 'master' && scale < 2) throw new Error('master mode needs scale >= 2');
  if (preview && fullRender) throw new Error('--preview is limited to stills or a --range clip that does not cover the whole film (a range covering every frame is a full render), in every mode');
  if (args.includes('--drop-preview-mark') && !(option(args, '--reproduction-only') && isStills)) throw new Error('--drop-preview-mark needs --reproduction-only DIR and stills (--stills / --still)');
  if (args.includes('--no-preview-mark')) throw new Error('--no-preview-mark was removed: a preview carries its PREVIEW mark; parity runs use --reproduction-only DIR (stills, outputs inside DIR, record stamped)');
  if (rangeArg && !option(args, '--out') && !pngSeq) throw new Error('--range needs --out or --png-seq (a partial render is not the film)');

  const frames = [];
  if (stillsArg) for (const item of stillsArg.split(',')) frames.push(Number(item.split(':')[1]));
  if (stillArg !== undefined) frames.push(Number(stillArg));
  if (range) for (let f = range[0]; f <= range[1]; f += 1) frames.push(f);
  for (const f of frames) if (!Number.isInteger(f) || f < 0 || f >= total) throw new Error(`frame ${f} outside 0..${total - 1}`);
  const stageNeeded = args.includes('--stage-needed') || Boolean(segment);
  // a segment stages only the shot videos its frames really mount (the compositor's own pictureMode / tail windows decide), so an ending
  // segment stages NO shot video; a plain --range / stills keep the frame-window rule
  const stageFrames = segment ? segments.videoFrames(config, await segmentDeps(config), segment.start, segment.end_exclusive - 1) : frames;
  if (stageNeeded && !partialRun && !segment) throw new Error('--stage-needed only applies to stills / --range');

  const defaultOut = path.join(process.cwd(), `${config.id}-${mode}-${scale === 1 ? '1080p' : `${1080 * scale}p`}.mp4`);
  const out = path.resolve(option(args, '--out') || defaultOut);
  if (!partialRun && !args.includes('--check-only') && fs.existsSync(out) && !overwrite) throw new Error(`Output exists: ${out}; pass --overwrite`);

  if (reproDir) {
    const inside = (target) => {
      const rel = path.relative(reproDir, path.resolve(target));
      return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
    };
    const targets = [stillsArg ? (option(args, '--outdir') || path.join(process.cwd(), 'stills')) : null, pngSeq, option(args, '--out')].filter(Boolean);
    if (!partialRun) targets.push(out);
    if (!targets.length || targets.some((t) => !inside(t))) throw new Error(`--reproduction-only ${reproDir}: every output (--outdir / --out / --png-seq) must be given and lie inside that directory`);
  }
  const browser = findBrowser(option(args, '--browser'));
  const localRequire = createRequire(path.join(PACKAGES, 'remotion', 'package.json'));
  const remotion = {bundle: localRequire('@remotion/bundler').bundle, ...localRequire('@remotion/renderer')};
  const stagingDir = fs.mkdtempSync(path.join(option(args, '--workdir') || os.tmpdir(), 'jjk-kit-'));
  const started = Date.now();
  try {
    const {sources, used, publicDir, partial, tailChecks, segmentChecks} = stage(config, {
      stagingDir, fonts: defaultFonts(config), tailWindow, frames: stageNeeded ? stageFrames : undefined, allowPreview: preview, requireReceipts: mode === 'master',
    });
    // the shot sources this render composites, and (given the previous record) whether any of them changed: the proof of a composite-only change
    const shotSources = records.shotSources(used);
    const composite = previousRecord !== undefined ? records.compositeOnly(shotSources, {previousRecord: path.resolve(previousRecord), partial}) : null;
    if (composite) process.stderr.write(`${composite.statement}\n`);
    const jsxNoChild = option(args, '--jsx-loader') === 'no-child';
    const serveUrl = await remotion.bundle({
      entryPoint: ENTRY, outDir: path.join(stagingDir, 'bundle'), publicDir, rootDir: WORKSPACE, enableCaching: false,
      webpackOverride: jsxNoChild ? noChildWebpackOverride : defaultWebpackOverride,
    });
    const {bindings, provenance, ...kitConfig} = config; // the compositor never sees host paths
    // preview-only sources (stills / ranges only) are marked on screen so a preview can never pass for a master
    const hasPreview = used.some((u) => u.preview);
    const markSuppressed = Boolean(reproDir && isStills && args.includes('--drop-preview-mark')); // only reproduction stills inside the parity work dir, on request
    const previewMark = hasPreview && !markSuppressed ? 'PREVIEW SOURCES - NOT MASTER' : null;
    const inputProps = {config: kitConfig, scale, label, previewMark, sources, partial};
    const chromiumOptions = {gl: 'swiftshader'};
    const composition = await remotion.selectComposition({serveUrl, id: compId, inputProps, logLevel: 'warn', browserExecutable: browser, chromiumOptions});
    if (composition.durationInFrames !== total || composition.width !== 1920 * scale || composition.height !== 1080 * scale || composition.fps !== config.fps) {
      throw new Error(`composition contract mismatch ${JSON.stringify(composition)}`);
    }
    if (args.includes('--check-only')) {
      process.stdout.write(`check-only ok: ${compId} ${composition.width}x${composition.height} ${composition.durationInFrames} f @${composition.fps}\n`);
      return;
    }
    const baseRecord = {
      mode, scale, comp: compId, label, preview_mark: previewMark,
      reproduction_only: reproDir ? {dir: reproDir, preview_mark_suppressed: markSuppressed} : null, config_path: configPath, config_sha256: sha256(configPath),
      tail_checks: tailChecks, segment_checks: segmentChecks, waived, warnings, compositor_sha256: sha256(ENTRY), render_script_sha256: sha256(__filename),
      remotion_version: localRequire('remotion/package.json').version, chromium_gl: 'swiftshader', concurrency,
      gpu_used_deliberately: false, comfyui_called: false, staged_inputs: used, command: `node render.cjs ${args.join(' ')}`,
      shot_sources: shotSources, shot_sources_sha256: records.shotSourcesDigest(shotSources), ...(composite ? {composite_only: composite} : {}),
    };
    const common = {serveUrl, composition, inputProps, chromiumOptions, logLevel: 'warn', browserExecutable: browser};

    if (stillsArg) {
      const outdir = path.resolve(option(args, '--outdir') || path.join(process.cwd(), 'stills'));
      fs.mkdirSync(outdir, {recursive: true});
      const made = [];
      for (const item of stillsArg.split(',')) {
        const [name, fr] = item.split(':');
        const file = path.join(outdir, `${name}.png`);
        const t = Date.now();
        await remotion.renderStill({...common, output: file, frame: Number(fr), imageFormat: 'png'});
        made.push({name, frame: Number(fr), file, sha256: sha256(file), seconds: (Date.now() - t) / 1000});
      }
      fs.writeFileSync(path.join(outdir, '_stills-record.json'), `${JSON.stringify({...baseRecord, made, timing_seconds: {total: (Date.now() - started) / 1000}}, null, 2)}\n`);
      process.stdout.write(`stills done: ${made.length}\n`);
      return;
    }
    if (stillArg !== undefined) {
      fs.mkdirSync(path.dirname(out), {recursive: true});
      const tStill = Date.now();
      await remotion.renderStill({...common, output: out, frame: Number(stillArg), imageFormat: 'png'});
      fs.writeFileSync(`${out}.render-record.json`, `${JSON.stringify({
        ...baseRecord, frame: Number(stillArg), output: out, output_sha256: sha256(out),
        timing_seconds: {render: (Date.now() - tStill) / 1000, total: (Date.now() - started) / 1000},
      }, null, 2)}\n`);
      process.stdout.write(`still done: ${out}\n`);
      return;
    }
    if (pngSeq) {
      const dir = path.resolve(pngSeq);
      fs.mkdirSync(dir, {recursive: true});
      // renderFrames writes element-<absolute frame>.png (lossless PNG, no video encode)
      await remotion.renderFrames({
        ...common, outputDir: dir, imageFormat: 'png', frameRange: range, concurrency, onStart: () => undefined,
        onFrameUpdate: () => undefined,
      });
      fs.writeFileSync(path.join(dir, '_render-record.json'), `${JSON.stringify({...baseRecord, frame_range: range, timing_seconds: {total: (Date.now() - started) / 1000}}, null, 2)}\n`);
      process.stdout.write(`png sequence done: ${dir}\n`);
      return;
    }
    fs.mkdirSync(path.dirname(out), {recursive: true});
    const partialFile = `${out}.partial.${audioOnly ? 'wav' : 'mp4'}`;
    fs.rmSync(partialFile, {force: true});
    const tRender = Date.now();
    let lastLogged = -1;
    const onProgress = ({renderedFrames}) => {
      if (renderedFrames - lastLogged >= 200) {
        lastLogged = renderedFrames;
        process.stderr.write(`rendered ${renderedFrames}/${range ? range[1] - range[0] + 1 : total} t=${((Date.now() - tRender) / 1000).toFixed(0)}s\n`);
      }
    };
    const codec = segment ? segments.codecParams({mode}) : null;
    // the one audio mix of the film: 48 kHz PCM, 1600 samples per 30 fps frame, rendered once and never cut at a segment join
    if (audioOnly) {
      await remotion.renderMedia({...common, outputLocation: partialFile, codec: 'wav', sampleRate: 48000, concurrency, onProgress});
    } else if (segment) {
      // SILENT video, one codec parameter set for every segment of the film (tools/join-segments.cjs refuses segments that differ)
      await remotion.renderMedia({
        ...common, outputLocation: partialFile, codec: codec.codec, pixelFormat: codec.pixelFormat, crf: codec.crf, colorSpace: codec.colorSpace, x264Preset: codec.x264Preset,
        muted: true, concurrency, frameRange: range, onProgress, ffmpegOverride: segments.ffmpegOverride(codec),
      });
    } else {
      await remotion.renderMedia({
        ...common, outputLocation: partialFile, codec: 'h264', pixelFormat: 'yuv420p', crf: mode === 'master' ? 16 : 18, concurrency,
        audioCodec: 'aac', sampleRate: 48000, enforceAudioTrack: true, ...(range ? {frameRange: range} : {}), onProgress,
      });
    }
    fs.renameSync(partialFile, out);
    const finished = Date.now();
    const record = {
      ...baseRecord, output: out, output_sha256: sha256(out), frame_range: range,
      timing_seconds: {bundle_and_select: (tRender - started) / 1000, render: (finished - tRender) / 1000, total: (finished - started) / 1000},
    };
    if (segment) {
      const hashes = frameHashes(out);
      Object.assign(record, {
        segment: {...segments.segmentRecord(plan, segment.id, used), plan_total: plan.total}, codec: {...codec, ffmpegArgs: codec.ffmpegArgs},
        framemd5: hashes.md5, framemd5_digest: hashes.digest, silent: true, stream: segments.probeStream(out),
      });
      if (hashes.frames !== segment.frames) throw new Error(`segment ${segment.id}: ${hashes.frames} frames were encoded, the plan says ${segment.frames}`);
    }
    if (audioOnly) {
      const {wavSeconds} = require('./lib/wavinfo.cjs');
      const samples = Math.round(wavSeconds(out) * 48000);
      Object.assign(record, {audio_only: {sample_rate: 48000, samples, expected_samples: total * (48000 / config.fps), samples_per_frame: 48000 / config.fps, total_frames: total}});
      if (Math.abs(samples - total * (48000 / config.fps)) > 48000 / config.fps) throw new Error(`audio-only render has ${samples} samples, the film needs ${total * (48000 / config.fps)}`);
    }
    fs.writeFileSync(`${out}.render-record.json`, `${JSON.stringify(record, null, 2)}\n`);
    process.stdout.write(`done ${out} in ${record.timing_seconds.render.toFixed(1)}s\n`);
  } finally {
    fs.rmSync(stagingDir, {recursive: true, force: true});
  }
}

main().catch((error) => {
  process.stderr.write(`render failed: ${error.stack || error.message}\n`);
  process.exitCode = 1;
});
