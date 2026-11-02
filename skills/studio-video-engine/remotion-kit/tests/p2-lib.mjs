// Helpers of the T-E45 P2 tests: a richer synthetic episode than smoke-lib (intro, four shots, icon event, two cards, end plate, theme /
// motion overrides) so every kind of config leaf the compositor reads exists, a stills harness that bundles ONCE and renders any
// config's frames through one browser, and the leaf-mutation property check of `segment_deps`.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {BROWSER, FONTS, KIT, PACKAGES, WORKSPACE, build, smokeRow} from './smoke-lib.mjs';
import {kitDeps, segmentsDoc} from './seg-fixture.mjs';
import {validateConfig, validateSources} from '../src/validate.mjs';
import {tailWindow} from '../src/picture-mode.mjs';

const require = createRequire(import.meta.url);
const dep = require('../lib/segdeps.cjs');
const {stage} = require('../lib/stage.cjs');

export const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
export const md5 = (file) => crypto.createHash('md5').update(fs.readFileSync(file)).digest('hex');
export const have = () => !(process.env.KIT_SKIP_RENDER_SMOKE === '1' || !fs.existsSync(BROWSER) || !fs.existsSync(path.join(PACKAGES, 'remotion', 'package.json')) || FONTS.some((f) => !fs.existsSync(f)));
export const clone = (v) => JSON.parse(JSON.stringify(v));

// intro 30 f, S1..S4 60 f each (f30..269), outro f270..359 (two 45 f cards), end card 360..389 with the plate from f340
export function richConfig(dir) {
  const {files, wav, png} = build(dir);
  const bind = (file) => ({path: file, sha256: sha(file)});
  const words = (start) => [{w: 'Hi', startF: start + 4, endF: start + 10, keyword: false}, {w: 'moon', startF: start + 14, endF: start + 24, keyword: true}];
  const shot = (id, start) => ({id, start, frames: 60, speechEndS: 1.5, vi: 'xin chao', captionLines: 1, words: words(start), segments: [{id, from: 0, frames: 60}]});
  const rows = [smokeRow('A', 'cut_push', 'S1', 'S2', 90), smokeRow('B', 'push_slide', 'S2', 'S3', 150), smokeRow('C', 'card_flip_3d', 'S3', 'S4', 210)];
  const card = (term, start) => ({term, ipa: '/x/', vi: `vi ${term}`, exampleEn: `${term} example.`, start, frames: 45});
  return {
    schema: 'jjk-remotion-kit/config/v1', id: 'p2-synthetic', fps: 30,
    timeline: {introFrames: 30, mainFrames: 360, endCardFrames: 30, outroStart: 270, outroFrames: 90},
    review: {label: 'P2 TEST'}, strings: {cardsHeader: 'Say it', cardsHeaderClosing: 'Bye'},
    intro: {kicker: 'Kicker', titleLines: ['Line one', 'Line two'], pill: 'Pill', footer: 'Footer', mark: 'none'},
    theme: {mint: '#DDF3D9', pink: '#FF2E7E'}, motion: {cards: {lead: 3}},
    shots: [shot('S1', 30), shot('S2', 90), shot('S3', 150), shot('S4', 210)],
    transitions: rows,
    icons: [{id: 'IC1', shot: 'S2', icon: 'tile.png', frame: 100, totalFrames: 20, holdFrames: 10, fadeFrames: 4}],
    ending: {plateStart: 340, speechEndFrame: 320, plateEn: 'Bye now', plateVi: 'Tam biet', tailFrom: 100},
    cards: [card('Alpha', 0), card('Beta', 45)],
    bindings: {
      opening: bind(png), logo: bind(png), music: bind(wav), fonts: {regular: FONTS[0], bold: FONTS[1]},
      shots: Object.fromEntries(['S1', 'S2', 'S3', 'S4'].map((id) => [id, {audio: bind(wav), segments: {[id]: bind(files[id])}}])),
      tails: Object.fromEntries(rows.filter((r) => r.tail).map((r) => [r.id, bind(files[`${r.from}tail`])])),
      icons: {'tile.png': bind(png)}, cards: [{icon: bind(png), audio: bind(wav)}, {icon: bind(png), audio: bind(wav)}],
    },
  };
}

// ---- leaves ----------------------------------------------------------------------------------------------------------------
export function leaves(value, prefix = []) {
  if (Array.isArray(value)) return value.flatMap((v, i) => leaves(v, [...prefix, i]));
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([k, v]) => leaves(v, [...prefix, k]));
  return [{path: prefix, value}];
}
export const leafName = (p) => p.map((x) => (typeof x === 'number' ? `[${x}]` : `.${x}`)).join('').replace(/^\./, '');
// class of a leaf: array indices collapsed
export const leafClass = (p) => p.map((x) => (typeof x === 'number' ? '[]' : `.${x}`)).join('').replace(/^\./, '');

export function mutateLeaf(config, p) {
  const next = clone(config);
  let at = next;
  for (const k of p.slice(0, -1)) at = at[k];
  const last = p[p.length - 1];
  const v = at[last];
  if (typeof v === 'number') at[last] = v + 1;
  else if (typeof v === 'boolean') at[last] = !v;
  else if (typeof v === 'string') at[last] = /^#[0-9a-f]{6}$/i.test(v) ? `${v.slice(0, 6)}${v[6] === '0' ? '1' : '0'}` : `${v}x`;
  else return null;
  return next;
}

// the same two gates the Film composition runs on mount: the config, and the config against the staged sources
const validOnly = (config, sources) => {
  try {
    validateConfig(config);
    validateSources(config, sources, {partial: false});
    return true;
  } catch {
    return false;
  }
};

// ---- the stills harness: ONE bundle + ONE browser for any number of configs / frames --------------------------------------------
export async function openHarness(config, workDir) {
  const localRequire = createRequire(path.join(PACKAGES, 'remotion', 'package.json'));
  const {bundle} = localRequire('@remotion/bundler');
  const R = localRequire('@remotion/renderer');
  fs.mkdirSync(path.join(workDir, 'stage'), {recursive: true});
  const staged = stage(config, {stagingDir: path.join(workDir, 'stage'), fonts: {regular: FONTS[0], bold: FONTS[1]}, tailWindow});
  const serveUrl = await bundle({
    entryPoint: path.join(KIT, 'src', 'index.jsx'), outDir: path.join(workDir, 'bundle'), publicDir: staged.publicDir, rootDir: WORKSPACE, enableCaching: false,
    webpackOverride: (webpack) => ({...webpack, resolve: {...webpack.resolve, modules: [PACKAGES, ...(webpack.resolve?.modules || ['node_modules'])]}}),
  });
  const browser = await R.openBrowser('chrome', {browserExecutable: BROWSER, chromiumOptions: {gl: 'swiftshader'}, logLevel: 'error'});
  let counter = 0;
  return {
    valid: (cfg) => validOnly(cfg, staged.sources),
    async stills(cfg, frames) {
      const {bindings, provenance, ...kitConfig} = cfg;
      const inputProps = {config: kitConfig, scale: 1, label: cfg.review.label, previewMark: null, sources: staged.sources, partial: false};
      const composition = await R.selectComposition({serveUrl, id: 'Film', inputProps, puppeteerInstance: browser, logLevel: 'error'});
      const out = [];
      for (const frame of frames) {
        counter += 1;
        const file = path.join(workDir, `still-${counter}.png`);
        await R.renderStill({serveUrl, composition, inputProps, frame, output: file, imageFormat: 'png', puppeteerInstance: browser, logLevel: 'error'});
        out.push(md5(file));
        fs.rmSync(file, {force: true});
      }
      return out;
    },
    async close() {
      await browser.close({silent: true});
    },
  };
}

// ---- the property check ----------------------------------------------------------------------------------------------------
/**
 * Mutate EVERY leaf of the config that is not in the segment's slice (all at once, greedily: a mutation is kept only if the config
 * still validates and the node key stays the same) and render the segment's first / middle / last frame: the frames must be
 * byte-identical to the unmutated render. A failure is bisected to the leaf paths responsible.
 * `sliceFn(config, seg, ctx)` is the function under test (default segdeps.videoSlice); the mutant test injects one that drops a part.
 */
export async function propertyCheck({harness, config, seg, pins, sliceFn = dep.videoSlice, baseline}) {
  const deps = kitDeps(config);
  const keyOf = (cfg) => dep.nodeKey('video', sliceFn(cfg, seg, {deps: kitDeps(cfg), mode: 'review'}), pins);
  const baseKey = keyOf(config);
  const frames = [seg.start, seg.start + Math.floor((seg.end_exclusive - seg.start - 1) / 2), seg.end_exclusive - 1];
  const base = baseline || await harness.stills(config, frames);
  const accepted = [];
  let acc = config;
  let skippedInvalid = 0;
  let inSlice = 0;
  for (const leaf of leaves(config).filter((l) => l.path[0] !== 'provenance')) {
    const candidate = mutateLeaf(acc, leaf.path);
    if (!candidate) continue;
    if (!harness.valid(candidate)) {
      skippedInvalid += 1;
      continue;
    }
    if (keyOf(candidate) !== baseKey) {
      inSlice += 1;
      continue;
    }
    acc = candidate;
    accepted.push(leaf.path);
  }
  const same = (cfg) => harness.stills(cfg, frames).then((got) => got.every((h, i) => h === base[i]));
  const out = {segment: seg.id, frames, accepted: accepted.length, in_slice: inSlice, skipped_invalid: skippedInvalid, offenders: [], baseline: base};
  if (await same(acc)) return {...out, ok: true};
  // bisect: the smallest set of accepted mutations that changes a pixel
  const apply = (paths) => paths.reduce((cfg, p) => mutateLeaf(cfg, p), config);
  const search = async (paths) => {
    if (paths.length === 1) return paths;
    const half = Math.ceil(paths.length / 2);
    const [a, b] = [paths.slice(0, half), paths.slice(half)];
    const found = [];
    if (a.length && !(await same(apply(a)))) found.push(...await search(a));
    if (b.length && !(await same(apply(b)))) found.push(...await search(b));
    return found.length ? found : paths;
  };
  return {...out, ok: false, offenders: (await search(accepted)).map(leafName)};
}

export function pinsFor() {
  return {kit: 'test', remotion: 'test', mode: 'review', scale: 1};
}

export {dep, kitDeps, segmentsDoc, os, assert, fs, path, pathToFileURL, KIT, BROWSER, FONTS, PACKAGES, WORKSPACE, build};
