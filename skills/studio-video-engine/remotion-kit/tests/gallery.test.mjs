// T-E42 gallery tool: every demo row it would render is a catalog-correct, validating row that fits the real handle, a preset whose
// handle is too short is skipped with the engine's reason (never faked), and the page is light-only with the required badges.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {collectIssues} from '../src/validate.mjs';
import {makeConfig} from './fixture.mjs';

const require = createRequire(import.meta.url);
const gallery = require('../tools/gallery.cjs');
const lib = await gallery.loadLib();
const catalog = gallery.loadCatalog();

// the synthetic episode with its whip row turned into the demo boundary B1, carrying a native tail handle of `have` frames
function base(have) {
  const c = makeConfig();
  const row = {id: 'B1', type: 'whip', boundary: 90, from: 'X1', to: 'X2a', frames: 8, direction: -1, start: 86, outFrames: 4, inFrames: 4};
  if (have > 0) row.tail = {startFrom: 0, editorialFrames: 0, fileFrames: have, nativeFps: 30, verifiedFrames: 1};
  c.transitions = c.transitions.map((t) => (t.id === 'W1' ? row : t));
  return c;
}

test('variants: every ready preset except the documented exclusions, push_slide in four directions', () => {
  const keys = gallery.variantsFor(catalog).map((v) => v.key);
  const ready = Object.entries(catalog.presets).filter(([, p]) => p.status === 'ready').map(([n]) => n);
  for (const name of ready) {
    if (gallery.EXCLUDED[name]) assert.ok(!keys.includes(name), `${name} is excluded`);
    else if (name === 'push_slide') for (const s of ['left', 'right', 'up', 'down']) assert.ok(keys.includes(`push_slide_${s}`));
    else assert.ok(keys.includes(name), `${name} has an entry`);
  }
  assert.equal(new Set(keys).size, keys.length);
});

test('with a 15-frame handle every demo row validates and fits the handle; frames never exceed the catalog default', () => {
  const config = base(15);
  let rows = 0;
  for (const v of gallery.variantsFor(catalog)) {
    const built = gallery.rowFor(catalog, v, config, 'B1', lib);
    if (built.skip) {
      assert.match(built.why, /no GPU work is requested/u, `${v.key}: skip reason`);
      continue;
    }
    rows += 1;
    assert.ok(built.row.frames <= lib.feasibility.defaultFrames(catalog.presets[v.preset]), `${v.key}: frames`);
    const cfg = gallery.configFor(config, built.row, `DEMO ${v.key}`);
    const issues = collectIssues(cfg).filter((i) => !i.includes('dip_sparkle_before_first_word')); // synthetic words start 4 f after the boundary
    assert.deepEqual(issues, [], v.key);
    // the row is exactly what the feasibility table says is playable
    const fit = lib.feasibility.presetAvailability(cfg, 'B1', {mode: 'review', catalog}).presets[v.preset];
    assert.equal(fit.available, true, `${v.key}: available at its chosen frames`);
    assert.ok(built.range[1] - built.range[0] + 1 <= 60, `${v.key}: clip <= 2 s`);
  }
  assert.ok(rows >= 20, `${rows} demo rows`);
});

test('a boundary without a handle: tail presets are skipped with the engine reason, tail-free presets still render', () => {
  const config = base(0);
  const by = Object.fromEntries(gallery.variantsFor(catalog).map((v) => [v.key, gallery.rowFor(catalog, v, config, 'B1', lib)]));
  assert.equal(by.crossfade.skip, true);
  assert.match(by.crossfade.why, /no GPU work is requested/u);
  assert.equal(by.cut_push.skip, undefined);
  assert.equal(by.whip.skip, undefined);
  assert.equal(by.dip_white.skip, true);
});

test('a short handle shrinks the frame count to the largest legal one that fits, and says so', () => {
  const config = base(8);
  const v = gallery.variantsFor(catalog).find((x) => x.key === 'crossfade');
  const built = gallery.rowFor(catalog, v, config, 'B1', lib);
  assert.equal(built.skip, undefined);
  assert.ok(built.row.frames < 12 && built.clamped === 12, `frames ${built.row.frames}`);
});

test('html: light only, required badges, no dark mode and no forbidden colours', () => {
  const rows = ['T1010', 'T1610'].map((id, i) => ({row: {id, boundary: 1000 + i, from: 'A', to: 'B', presets: Object.fromEntries(Object.keys(catalog.presets).map((n) => [n, i === 0
    ? {available: false, whyNot: `short handle for ${n}; no GPU work is requested`, needsTailFrames: 10, haveNativeFrames: 7}
    : {available: true, needsTailFrames: 0, haveNativeFrames: 15, reason: 'ok'}]))}}));
  const items = [
    {key: 'crossfade', preset: 'crossfade', variant: null, media: {clip: 'clips/crossfade.mp4', poster: 'posters/crossfade.png', frames: 12, range: [1, 30], tailFrames: 12}},
    {key: 'push_slide_left', preset: 'push_slide', variant: {en: 'push left', vi: 'đẩy sang trái'}, skip: 'tail handle too short'},
    {key: 'glitch', preset: 'glitch', variant: null, skip: 'planned: no renderer yet'},
  ];
  const html = gallery.buildHtml(catalog, items, rows, {episodeId: 'ep', pair: 'A → B (T1610)', demoBoundary: 'T1610'});
  assert.match(html, /dùng ngay, không cần GPU/u);
  assert.match(html, /cần thêm khung đuôi — phải chạy tails GPU/u);
  assert.match(html, /an toàn 1 shot/u);
  assert.match(html, /cần continuity agree/u);
  assert.match(html, /không dùng giữa hai ảnh/u);
  assert.match(html, /body\{margin:0;background:var\(--page\)/u);
  assert.doesNotMatch(html, /prefers-color-scheme|data-theme|dark/iu);
  for (const bad of ['#FFF8EC', '#FF6B00', '#FFB347', 'orange', 'beige', 'yellow']) assert.ok(!html.toLowerCase().includes(bad.toLowerCase()), bad);
});
