#!/usr/bin/env node
'use strict';
// `jjv edit review-render` / `jjv edit master-render` (engine/editorial/CLI-PATCH-edit.md): ONE command from the edited engine inputs to the film,
// re-rendering only what the edit touched.
//
//   node tools/edit-render.cjs --mode review --episode-root R --episode-json E --boundaries B --word-timing W --episode-text T
//        --cache C --out film.mp4 [--explain] [--browser PATH] [--workdir D] [--allow-outside PATH]...
//        [--build-concurrency 1|2] [--build-mode inproc|children] [--force-segment IDS] [--rehash-all] [--overwrite] [--jsx-loader no-child]
//   node tools/edit-render.cjs --mode master --master-config KITMASTER.json [--segments-file S.json | the engine inputs above] --cache C --out film.mp4 ...
//
// review:  jjv editorial build-config (engine: review-config.json + events.json + segments.json + the receipt-bound build summary)
//       -> lib/adapter-engine.cjs (engine records + episode text -> kit config, hash-verified bindings)
//       -> render.cjs --segments-build (stale segments only, one bundle / one browser, verified-hash cache, fast join with the framemd5 proof)
// master:  the master kit config (4K cores / seam / tails bound with receipts) is built by the master adapter once the master is ready; this tool does not
//          guess it: pass --master-config. The segment cut list comes from --segments-file, or from a build-config of the engine inputs.
// --explain prints which segments are stale and why, and renders nothing. Exit codes: 0 ok, 1 refused / failed (message on stderr), 2 usage.
// The run report (<out>.edit-run.json) lists every step, its command and seconds, the stale ids and the film sha256. CPU only.

const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const KIT = path.resolve(__dirname, '..');
const SKILL = path.resolve(KIT, '..');
const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};
const all = (name) => args.flatMap((a, i) => (a === name ? [args[i + 1]] : []));
const has = (name) => args.includes(name);

function usage(message) {
  if (message) process.stderr.write(`edit-render: ${message}\n`);
  process.stderr.write('usage: edit-render.cjs --mode review|master --cache DIR (--out FILE | --explain) [--episode-root R --episode-json F --boundaries F --word-timing F --episode-text F] [--master-config F] [--segments-file F]\n');
  process.exit(2);
}

function step(name, cmd, argv, {capture = false} = {}) {
  const t0 = Date.now();
  const r = spawnSync(cmd, argv, {encoding: 'utf8', maxBuffer: 1 << 28, stdio: capture ? ['ignore', 'pipe', 'pipe'] : ['ignore', 'inherit', 'inherit'], cwd: process.cwd()});
  const seconds = (Date.now() - t0) / 1000;
  const entry = {step: name, command: [cmd, ...argv].join(' '), seconds, exit: r.status};
  if (r.error) throw new Error(`${name}: could not run ${cmd} (${r.error.message})`);
  if (capture && r.stderr) process.stderr.write(r.stderr);
  if (r.status !== 0) {
    const tail = capture ? `${r.stdout.slice(-1200)}` : '';
    throw Object.assign(new Error(`${name} failed (exit ${r.status})${tail ? `: ${tail}` : ''}`), {entry});
  }
  return {entry, stdout: r.stdout || ''};
}

function main() {
  const mode = opt('--mode');
  if (!['review', 'master'].includes(mode)) usage('--mode must be review or master');
  const cache = opt('--cache');
  if (!cache) usage('--cache DIR is required (segments, audio mix, hash cache and the engine output live there)');
  const explain = has('--explain');
  const out = opt('--out');
  if (!explain && !out) usage('--out FILE.mp4 is required (or --explain)');
  const cacheDir = path.resolve(cache);
  fs.mkdirSync(cacheDir, {recursive: true});
  const report = {schema: 'jjk-remotion-kit/edit-run/v1', mode, started: new Date().toISOString(), steps: []};
  const python = process.env.PYTHON || 'python';
  const allowOutside = all('--allow-outside').flatMap((p) => ['--allow-outside', p]);
  const t0 = Date.now();

  let kitConfig;
  let segmentsFile = opt('--segments-file');
  const engineInputs = ['--episode-json', '--boundaries', '--word-timing'].every((f) => opt(f));

  if (mode === 'master') {
    if (!opt('--master-config')) throw new Error('master-render needs --master-config: the kit config of the master (4K cores, seam blends and tails bound with receipts), built by the master adapter after the master is ready; this tool does not guess it');
    kitConfig = path.resolve(opt('--master-config'));
    if (!fs.existsSync(kitConfig)) throw new Error(`--master-config ${kitConfig} does not exist`);
    if (!segmentsFile && !engineInputs) throw new Error('master-render needs the segment cut list: --segments-file, or the engine inputs (--episode-json --boundaries --word-timing) to build it');
  }
  if (mode === 'review' && !opt('--episode-text')) usage('--episode-text is required in review mode (intro, strings, captions, card details: the text the engine does not carry)');
  let engineOut = null;
  if (mode === 'review' || (!segmentsFile && engineInputs)) {
    for (const f of ['--episode-json', '--boundaries', '--word-timing', '--episode-root']) if (!opt(f)) usage(`${f} is required`);
    engineOut = path.join(cacheDir, 'engine', 'current');
    fs.rmSync(engineOut, {recursive: true, force: true});
    fs.mkdirSync(path.dirname(engineOut), {recursive: true});
    const built = step('build-config', python, ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', path.resolve(opt('--episode-json')), '--boundaries', path.resolve(opt('--boundaries')),
      '--word-timing', path.resolve(opt('--word-timing')), '--out', engineOut, ...allowOutside], {capture: true});
    report.steps.push(built.entry);
    const summary = path.join(cacheDir, 'engine', 'summary.json');
    fs.writeFileSync(summary, built.stdout);
    let doc;
    try {
      doc = JSON.parse(built.stdout);
    } catch (error) {
      throw new Error(`build-config printed no JSON summary (${error.message})`);
    }
    if (doc.ok === false) throw new Error(`build-config refused: ${doc.error}`);
    if (!segmentsFile) segmentsFile = path.join(engineOut, 'segments.json');
    if (!fs.existsSync(segmentsFile)) throw new Error(`the engine wrote no segments.json (${segmentsFile}): this engine predates the segment output`);
    if (mode === 'review') {
      if (!opt('--episode-text')) usage('--episode-text is required in review mode (intro, strings, captions, card details: the text the engine does not carry)');
      kitConfig = path.join(cacheDir, 'kit-config.json');
      const adapted = step('adapt', process.execPath, [path.join(KIT, 'lib', 'adapter-engine.cjs'), '--review-config', path.join(engineOut, 'review-config.json'), '--events', path.join(engineOut, 'events.json'),
        '--receipt', summary, '--episode-root', path.resolve(opt('--episode-root')), '--episode-text', path.resolve(opt('--episode-text')), ...allowOutside, '--out', kitConfig]);
      report.steps.push(adapted.entry);
    }
  }

  const pass = [];
  for (const f of ['--browser', '--workdir', '--build-concurrency', '--build-mode', '--force-segment', '--jsx-loader', '--catalog', '--label']) if (opt(f) !== undefined) pass.push(f, opt(f));
  for (const f of ['--rehash-all', '--no-hash-cache', '--overwrite', '--json']) if (has(f)) pass.push(f);
  const render = step(explain ? 'explain' : 'segments-build', process.execPath, [path.join(KIT, 'render.cjs'), '--config', kitConfig, '--segments-file', segmentsFile, '--segments-build', path.join(cacheDir, 'segments'),
    '--mode', mode, ...(explain ? ['--explain'] : ['--out', path.resolve(out)]), ...pass]);
  report.steps.push(render.entry);
  report.total_seconds = (Date.now() - t0) / 1000;
  report.kit_config = kitConfig;
  report.segments_file = segmentsFile;
  report.engine_out = engineOut;
  if (!explain) {
    const runFile = `${path.resolve(out)}.segments-run.json`;
    if (fs.existsSync(runFile)) {
      const run = JSON.parse(fs.readFileSync(runFile, 'utf8'));
      report.rendered = run.rendered;
      report.reused = run.reused.length;
      report.segments_rendered = run.segments_rendered;
      report.composite_only = run.composite_only || null;
      report.film = run.film;
      report.hash_cache = run.hash_cache || null;
    }
    fs.writeFileSync(`${path.resolve(out)}.edit-run.json`, `${JSON.stringify(report, null, 2)}\n`);
    process.stdout.write(`edit-render ${mode}: ${report.total_seconds.toFixed(1)} s total, segments rendered ${report.segments_rendered}, reused ${report.reused}; report ${path.resolve(out)}.edit-run.json\n`);
  } else {
    fs.writeFileSync(path.join(cacheDir, 'edit-explain.json'), `${JSON.stringify(report, null, 2)}\n`);
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`edit-render: ${error.message}\n`);
  process.exitCode = 1;
}
