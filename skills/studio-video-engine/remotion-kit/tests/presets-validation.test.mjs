// T-E42: the kit validates every transition from its catalog entry (frames / params / direction / tail window / window mode /
// continuity / safe_for / dip family) and warns (never refuses) on same_framing + a visible transition.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CATALOG} from '../src/catalog.generated.mjs';
import {collectIssues, collectWarnings} from '../src/validate.mjs';
import {auditPictureLayers, tailWindow} from '../src/picture-mode.mjs';
import {resolveMotion} from '../src/presets.mjs';
import {PICTURE_LAYER, PLANNED, has, presetConfig, presetRow} from './preset-fixture.mjs';
import {makeConfig} from './fixture.mjs';

const spec = (name) => CATALOG.presets[name];
const withRow = (name, patch, over = {}) => {
  const c = presetConfig(name, over);
  Object.assign(c.transitions[0], patch);
  return c;
};

test('every picture-layer preset: its catalog defaults validate and pass the per-frame one-shot audit', () => {
  assert.ok(PICTURE_LAYER.length >= 22, `${PICTURE_LAYER.length} picture-layer presets`);
  for (const name of PICTURE_LAYER) {
    const c = presetConfig(name, name === 'dip_white_legacy' ? {params: {sparkles: false}} : {});
    assert.deepEqual(collectIssues(c), [], name);
    assert.deepEqual(auditPictureLayers(c, resolveMotion(c)), [], `${name} audit`);
  }
});

test('frames: below min / above max / odd for an even preset / the wrong fixed count are refused, per the catalog rule', () => {
  for (const name of PICTURE_LAYER) {
    const rule = spec(name).frames;
    const refused = [];
    if ('fixed' in rule) refused.push(...[rule.fixed + 1, Math.max(1, rule.fixed - 1)].filter((n) => !(name === 'dip_white' && n === 9))); // dip_white at 9 frames IS the legacy schedule
    else {
      refused.push(rule.max + 2, rule.min - 2 > 0 ? rule.min - 2 : rule.min - 1);
      if (rule.even) refused.push(rule.min + 1);
    }
    for (const frames of refused) {
      // a dip row WITH its own schedule is judged by that schedule, so test the catalog-default dips without one
      const c = presetConfig(name, {frames, row: {start: 90}});
      const issues = collectIssues(c);
      assert.ok(issues.some((i) => /frames|even|schedule/.test(i)), `${name}: frames ${frames} accepted (${issues.join(' | ')})`);
    }
  }
  // the old strings the earlier rounds pinned still hold
  assert.ok(has(collectIssues(presetConfig('whip', {frames: 7, row: {outFrames: 3, inFrames: 4}})), 'whip needs an even frame count'));
  assert.ok(has(collectIssues(presetConfig('pan_motivated', {frames: 7})), 'needs an even frame count'));
  assert.ok(has(collectIssues(presetConfig('push_slide', {frames: 3})), "outside push_slide's 8..30"));
});

test('params: unknown refused; out-of-range / wrong type / bad enum refused; defaults accepted', () => {
  for (const name of PICTURE_LAYER) {
    const params = spec(name).params;
    assert.ok(has(collectIssues(presetConfig(name, {params: {bogus: 1}})), "unknown param 'bogus'"), `${name} unknown param`);
    for (const [key, p] of Object.entries(params)) {
      if (p.required) continue;
      assert.deepEqual(collectIssues(presetConfig(name, {params: {[key]: p.default}, ...(name === 'dip_white_legacy' ? {} : {})}))
        .filter((i) => i.includes(`param '${key}'`)), [], `${name}.${key} default`);
      let bad = [];
      if (p.type === 'enum') bad = ['not-a-value'];
      else if (p.type === 'boolean') bad = ['yes', 1];
      else {
        bad = ['5'];
        if (p.max !== undefined) bad.push(p.max + 1);
        if (p.min !== undefined) bad.push(p.min - 1);
        if (p.type === 'integer') bad.push(p.default + 0.5);
      }
      for (const value of bad) {
        assert.ok(has(collectIssues(presetConfig(name, {params: {[key]: value}})), `param '${key}'`), `${name}.${key}=${JSON.stringify(value)} accepted`);
      }
    }
  }
});

test('direction: a required direction is refused at 0; presets that ignore it accept 0', () => {
  for (const name of PICTURE_LAYER) {
    const issues = collectIssues(presetConfig(name, {direction: 0}));
    if (spec(name).direction === 'required') assert.ok(issues.some((i) => /direction (1 or -1|must be 1 or -1)/.test(i)), `${name} accepted direction 0`);
    else assert.deepEqual(issues.filter((i) => i.includes('direction')), [], name);
  }
  assert.ok(has(collectIssues(presetConfig('push_slide', {direction: 0})), 'push_slide needs direction 1 or -1'));
  assert.deepEqual(collectIssues(presetConfig('push_slide', {direction: -1})), []);
});

test('tail: every preset whose catalog tail_frames is not none needs a tail, and may not play more tail frames than verified', () => {
  for (const name of PICTURE_LAYER) {
    const c = presetConfig(name, name === 'dip_white_legacy' ? {params: {sparkles: false}} : {});
    const t = c.transitions[0];
    const rule = spec(name).tail_frames;
    if (rule === 'none') {
      assert.equal(tailWindow(t), null, `${name} plays no tail`);
      continue;
    }
    const w = tailWindow(t);
    assert.ok(w && w.frames > 0 && w.from === 90, `${name} tail window ${JSON.stringify(w)}`);
    if (rule === 'all') assert.equal(w.frames, t.frames, name);
    if (rule === 'half') assert.equal(w.frames, Math.ceil(t.frames / 2), name);
    const noTail = structuredClone(c);
    delete noTail.transitions[0].tail;
    assert.ok(has(collectIssues(noTail), 'needs an outgoing tail') || has(collectIssues(noTail), 'has no tail'), `${name} accepted without a tail`);
    if (w.frames < 2) continue; // one verified frame cannot be bound any lower
    const short = structuredClone(c);
    short.transitions[0].tail.verifiedFrames = w.frames - 1;
    assert.ok(has(collectIssues(short), `plays ${w.frames} tail frames but only ${w.frames - 1} were verified`), `${name} verified bound`);
  }
});

test('continuity: a both-sides preset between two pictures needs agree; one-shot presets do not', () => {
  for (const name of PICTURE_LAYER) {
    const c = presetConfig(name, name === 'dip_white_legacy' ? {params: {sparkles: false}} : {});
    c.transitions[0].continuity = 'mismatch';
    const issues = collectIssues(c);
    if (spec(name).shows_both) assert.ok(has(issues, "continuity:'agree'"), `${name} accepted a mismatch`);
    else assert.deepEqual(issues.filter((i) => i.includes('continuity')), [], `${name} one-shot preset needs no continuity`);
  }
});

test('window: the row start must be where the catalog window mode puts it; shows_both / renders_as / preset must agree with the catalog', () => {
  for (const name of PICTURE_LAYER) {
    const c = presetConfig(name, name === 'dip_white_legacy' ? {params: {sparkles: false}} : {});
    c.transitions[0].start += 3;
    assert.ok(has(collectIssues(c), 'start'), `${name} start accepted`);
  }
  assert.ok(has(collectIssues(withRow('push_slide', {shows_both: false})), 'shows_both false contradicts type push_slide'));
  assert.ok(has(collectIssues(withRow('push_slide', {renders_as: 'wipe'})), 'renders_as'));
  assert.ok(has(collectIssues(withRow('push_slide', {preset: 'blinds'})), 'preset'));
  assert.deepEqual(collectIssues(withRow('push_slide', {preset: 'push_slide', renders_as: 'push_slide', shows_both: true})), []);
});

test('planned presets are refused with the engine wording; unknown types name the canonical list', () => {
  assert.ok(PLANNED.length >= 3);
  for (const name of PLANNED) {
    const c = makeConfig();
    c.transitions[0] = {...c.transitions[0], type: name, frames: 12, start: 90, direction: 0};
    assert.ok(has(collectIssues(c), `preset '${name}' is planned, not implemented`), name);
  }
  const c = makeConfig();
  c.transitions[0].type = 'swirl';
  assert.ok(has(collectIssues(c), "unknown transition type 'swirl'"));
});

test('safe_for: a graphics-only preset between two pictures and a picture-only preset between two cards are refused', () => {
  const slide = presetConfig('card_slide', {frames: 6});
  assert.ok(has(collectIssues(slide), 'graphic boundaries only'));
  const cards = makeConfig();
  cards.transitions.push({id: 'CF', type: 'crossfade', boundary: 180, from: 'CARD_Moon', to: 'CARD_Sun', frames: 12, direction: 0, start: 180, continuity: 'agree'});
  assert.ok(has(collectIssues(cards), 'picture shots only'));
});

test('dip family: schedule from the catalog (or the config), one pure frame, peak / sparkle before the first spoken word, sparkles:false means reach 0', () => {
  for (const name of ['dip_white', 'dip_black', 'light_leak', 'film_burn']) {
    const peakT = spec(name).schedule.find((r) => r.white === 1).t; // all four peak on B+1
    const sparkleDefault = spec(name).params.sparkles.default;
    const at = (firstWord, params) => {
      const c = presetConfig(name, {params});
      c.shots[1].speechOnsetF = 90 + firstWord;
      c.shots[1].onsetEvidence = 'test onset';
      return collectIssues(c);
    };
    assert.ok(has(at(peakT, {}), 'dip_peak_before_first_word'), `${name} peak on the first word`);
    assert.deepEqual(at(peakT + 3, {}), [], `${name} peak clear`);
    const edge = at(peakT + 1, {});
    if (sparkleDefault) {
      assert.ok(has(edge, 'dip_sparkle_before_first_word'), `${name} sparkle burst reaches the word`);
      assert.deepEqual(at(peakT + 1, {sparkles: false}), [], `${name} sparkles:false => reach 0`);
    } else {
      assert.deepEqual(edge, [], `${name} no sparkles by default => reach 0`);
      assert.ok(has(at(peakT + 1, {sparkles: true}), 'dip_sparkle_before_first_word'), `${name} sparkles:true`);
    }
  }
  // a config record's own schedule wins (historic builds), and its length is the frame count
  const c = presetConfig('dip_white');
  c.transitions[0].schedule = [{t: -1, shot: 'out', white: 0.3}, {t: 0, shot: 'out_tail', white: 0.6}, {t: 1, shot: 'none', white: 1}, {t: 2, shot: 'in', white: 0.5}];
  c.transitions[0].frames = 4;
  c.transitions[0].start = 89;
  assert.deepEqual(collectIssues(c), []);
  c.transitions[0].frames = 8;
  assert.ok(has(collectIssues(c), 'dip_white frames 8 must equal its schedule length 4'));
});

test('collectWarnings: same_framing + a visible transition warns (never refuses); cut_push / cut do not; the legacy dip says so', () => {
  const warn = (name, framing, params) => {
    const c = presetConfig(name, {params});
    if (framing) c.transitions[0].framing = framing;
    assert.deepEqual(collectIssues(c).filter((i) => i.includes('framing')), [], `${name}: framing is never a refusal`);
    return collectWarnings(c);
  };
  for (const name of ['dip_white', 'pan_motivated', 'whip', 'push_slide', 'light_leak', 'crossfade', 'card_flip_3d']) {
    const w = warn(name, 'same_framing');
    assert.equal(w.length, 1, `${name}: ${JSON.stringify(w)}`);
    assert.match(w[0], /framing is same_framing but .* is a visible transition/);
  }
  assert.deepEqual(warn('cut_push', 'same_framing'), []);
  assert.deepEqual(warn('push_slide', 'new_angle'), []);
  assert.deepEqual(warn('push_slide', undefined), []);
  const legacy = warn('dip_white_legacy', undefined, {sparkles: false});
  assert.ok(legacy.some((w) => w.includes('legacy 9-frame dip_white schedule')));
  assert.deepEqual(collectWarnings(makeConfig()), []);
});

test('presetRow is catalog-correct for every ready preset (sanity of the fixture itself)', () => {
  for (const [name, p] of Object.entries(CATALOG.presets)) {
    if (p.status !== 'ready') continue;
    const row = presetRow(name);
    assert.equal(row.type, name);
    assert.ok(Number.isInteger(row.start));
  }
});
