'use strict';
// Reuse the configured kit compositions/assets; inject machine paths and keep writes under out.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const sha = p => crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');

async function main() {
  const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const {kit, workspace, packages, browser, props, out, work} = job;
  const entry = path.join(kit, 'src', 'index.jsx');
  const loader = path.join(__dirname, 'jsx_loader.cjs');
  if (fs.existsSync(out)) throw new Error(`Output exists: ${out}`);
  for (const file of [entry, loader, browser]) if (!fs.existsSync(file)) throw new Error(`Missing ${file}`);
  fs.mkdirSync(work, {recursive: false});
  process.env.TMP = work; process.env.TEMP = work; process.env.TMPDIR = work;
  const localRequire = createRequire(path.join(packages, 'remotion', 'package.json'));
  const {bundle} = localRequire('@remotion/bundler');
  const {selectComposition, renderMedia} = localRequire('@remotion/renderer');
  const started = Date.now();
  const serveUrl = await bundle({entryPoint: entry, outDir: path.join(work, 'bundle'),
    publicDir: path.join(kit, 'public'), rootDir: workspace, enableCaching: false,
    webpackOverride: webpack => ({...webpack, module: {...webpack.module,
      rules: (webpack.module?.rules || []).map(rule => rule?.test instanceof RegExp && rule.test.source === '\\.jsx?$'
        ? {...rule, use: [{loader, options: {packages}}]} : rule)}, resolve: {...webpack.resolve,
      modules: [packages, ...(webpack.resolve?.modules || ['node_modules'])]}})});
  const common = {browserExecutable: browser, chromiumOptions: {gl: 'swiftshader', disableWebSecurity: false}, logLevel: 'warn'};
  const composition = await selectComposition({serveUrl, id: 'EpisodeTitle', inputProps: props, ...common});
  await renderMedia({serveUrl, composition, inputProps: props, outputLocation: out, codec: 'h264',
    pixelFormat: 'yuv420p', crf: 16, concurrency: 2, muted: true, ...common});
  const result = {schema: 'jjv/brand-title-render/v1', output: out, output_sha256: sha(out),
    entry, entry_sha256: sha(entry), loader_sha256: sha(loader), renderer_sha256: sha(__filename),
    props, frames: composition.durationInFrames, fps: composition.fps,
    width: composition.width, height: composition.height, seconds: (Date.now() - started) / 1000,
    remotion_version: localRequire('remotion/package.json').version, gl: 'swiftshader'};
  fs.writeFileSync(`${out}.render-record.json`, JSON.stringify(result, null, 2));
  process.stdout.write(`${JSON.stringify(result)}\n`);
}
// Remotion's local server can keep the event loop alive after a browser launch error.
main().catch(error => {process.stderr.write(`${error.stack}\n`); process.exit(1);});
