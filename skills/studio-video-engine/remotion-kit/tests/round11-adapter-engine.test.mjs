// Round 11 / T-E42 item 4: episodes/ep04/adapter-engine.cjs maps what `jjv editorial build-config` WRITES (review-config.json + events.json) onto the kit
// config. Every test builds with the REAL engine into a scratch directory (nothing under production-local is written).
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {pin} from './ep04-pin.mjs';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SKILL = path.resolve(KIT, '..');
const WORKSPACE = path.resolve(SKILL, '../../..');
const require = createRequire(import.meta.url);
const EP = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom');
const EDITORIAL = path.join(EP, 'editorial');
const LOGO = path.join(WORKSPACE, 'production-local', 'studio-app', 'logo-jenniejoy-kids.png');
const CLEAN_STEM = path.join(EP, '..', '03-drinking-milk', 'audio', 'music', 'milk-pentatonic-bed-48k-v1.wav');
const WORD_TIMING = path.join(EDITORIAL, 'word-timing-v003', 'WORD-TIMING-v003.json');
const have = pin.available && fs.existsSync(pin.boundaries) && fs.existsSync(WORD_TIMING) && fs.existsSync(path.join(SKILL, 'engine', 'editorial', 'presets_cli.py'));
const ADAPTER = path.join(KIT, 'episodes', 'ep04', 'adapter-engine.cjs');
const TEXT_FILE = path.join(KIT, 'episodes', 'ep04', 'episode-text.json');
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));
const shaOf = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const {collectIssues} = await import(pathToFileURL(path.join(KIT, 'src', 'validate.mjs')).href);
const feas = await import(pathToFileURL(path.join(KIT, 'src', 'feasibility.mjs')).href);
const music = await import(pathToFileURL(path.join(KIT, 'src', 'music-plan.mjs')).href);
const catalog = rd(path.join(SKILL, 'schemas', 'transition-presets.json'));

const SCRATCH = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r11a-'));
process.on('exit', () => fs.rmSync(SCRATCH, {recursive: true, force: true}));

function build(name, boundaries) {
  const dir = path.join(SCRATCH, name);
  fs.mkdirSync(dir, {recursive: true});
  const bfile = path.join(dir, 'boundaries.json');
  if (boundaries) fs.writeFileSync(bfile, JSON.stringify(boundaries));
  const out = path.join(dir, 'out');
  fs.mkdirSync(out, {recursive: true});
  const r = spawnSync('python', ['-I', path.join(SKILL, 'bin', 'jjv.py'), 'editorial', 'build-config', '--episode', pin.episode,
    '--boundaries', boundaries ? bfile : pin.boundaries, '--word-timing', pin.wordTiming(), '--out', out, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
  assert.equal(r.status, 0, r.stderr.slice(-800));
  const summary = path.join(dir, 'summary.json');
  fs.writeFileSync(summary, r.stdout);
  return {dir, reviewConfig: path.join(out, 'review-config.json'), events: path.join(out, 'events.json'), receipt: summary, episodeRoot: EP, summary: JSON.parse(r.stdout)};
}

// the "change set" is made ONLY by editing boundaries + ending params: derived timeline, the approved dip, a music bed, the disc layout
function derivedBoundaries() {
  const b = rd(pin.boundaries);
  for (const c of b.cards) {
    delete c.start_frame;
    delete c.duration_frames;
  }
  // logo_hold_frames is the STILL LOGO HOLD between the dialogue end (f2160) and card 1 (v013: 70 -> card 1 at f2230); the plate follows the last
  // card window; the slide / fade frames of the disc derive from the outro start, so the hand-written ones are removed
  Object.assign(b.ending, {derive_timeline: true, card_min_frames: 90, logo_hold_frames: 70});
  for (const key of ['start', 'last_frame', 'fixed_frames_after_speech']) delete b.ending.end_plate[key];
  for (const key of ['fade_start', 'slide_left', 'shrink', 'full_logo_frames']) delete b.ending.logo_disc[key];
  b.ending.music_bed = {extend: 'loop_phrase_crossfade', loop_start_s: 4, loop_end_s: 56, crossfade_frames: 30, duck_db: 14, duck_attack_frames: 4, duck_release_frames: 8, duck_under: 'words'};
  b.ending.logo_disc_layout = {slide_x: 520, pill_left_x: 988};
  for (const r of b.boundaries) {
    if (r.to_shot.startsWith('CARD_') || ['END_PLATE', 'ENDLOGO'].includes(r.to_shot)) delete r.frame;
    if (r.type === 'dip_white') delete r.frames; // the approved 8-row schedule instead of the legacy 9 rows
    if (r.type === 'iris') delete r.params.disc_fade_start_f;
  }
  return b;
}

let plainBuild;
let derivedBuild;
const plain = () => (plainBuild ||= build('plain'));
const derived = () => (derivedBuild ||= build('derived', derivedBoundaries()));
const adapter = () => require(ADAPTER);

function adapt(b, over = {}) {
  const a = adapter();
  const loaded = a.loadBuild({reviewConfig: b.reviewConfig, events: b.events, receipt: b.receipt, episodeRoot: EP});
  return a.adaptEngine(loaded.review, loaded.events, {bound: loaded.bound, episodeRoot: EP, episodeText: rd(TEXT_FILE), allowOutside: [LOGO], ...over});
}

test('4a: the real legacy build (9-frame dips, no timeline change) maps onto a kit config that validates with collectIssues; historical waivers are only made for a dip that violates the rule (none here)', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const cfg = adapt(plain());
  assert.deepEqual(collectIssues(cfg), [], 'the word timing v003 onsets come after the legacy peaks');
  const again = adapt(plain(), {historicalWaivers: {reproduction_only: true, review_render_sha256: 'a'.repeat(64)}});
  assert.deepEqual(again.waivers, [], 'nothing to waive: a waiver for a dip that passes would itself be refused as unused');
  assert.deepEqual(collectIssues(again), []);
  assert.deepEqual(cfg.transitions.filter((x) => x.type === 'dip_white').map((x) => [x.id, x.preset, x.frames]), [['T1010', 'dip_white_legacy', 9], ['T1310', 'dip_white_legacy', 9], ['T1610', 'dip_white_legacy', 9]]);
});

test('4b: preset type, params, schedule, overlay and the tail numbers are carried; verifiedFrames is the engine tail_output_frames', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const b = plain();
  const events = rd(b.events);
  const cfg = adapt(b);
  const dip = cfg.transitions.find((x) => x.id === 'T1010');
  const ev = events.transitions.find((x) => x.id === 'T1010');
  assert.equal(dip.type, 'dip_white');
  assert.equal(dip.preset, 'dip_white_legacy');
  assert.equal(dip.renders_as, 'dip_white');
  assert.deepEqual(dip.params, {sparkles: true});
  assert.deepEqual(dip.overlay, {kind: 'colour', colour: '#FFF8EC'});
  assert.equal(dip.schedule.length, 9);
  assert.deepEqual(dip.tail, {startFrom: ev.outgoing_tail.start_from_frame, editorialFrames: ev.outgoing_tail.editorial_frames, fileFrames: ev.outgoing_tail.native_frames, verifiedFrames: ev.outgoing_tail.tail_output_frames, nativeFps: 24});
  assert.equal(dip.incomingHiddenFrames, ev.incoming_hidden_frames);
  const whip = cfg.transitions.find((x) => x.id === 'T390');
  assert.equal(whip.outFrames, 4);
  assert.equal(whip.inFrames, 4);
  assert.deepEqual(whip.params, {});
  assert.equal(cfg.transitions.length, 28);
  // a tail record that the config and the events disagree on is refused (a raised tail_output_frames would widen what the kit may play)
  const a = adapter();
  const loaded = a.loadBuild({reviewConfig: b.reviewConfig, events: b.events, receipt: b.receipt, episodeRoot: EP});
  loaded.review.motion.transitions.find((x) => x.id === 'T1010').outgoing_tail.tail_output_frames = 99;
  assert.throws(() => a.adaptEngine(loaded.review, loaded.events, {bound: loaded.bound, episodeRoot: EP, episodeText: rd(TEXT_FILE), allowOutside: [LOGO]}), /T1010: outgoing_tail\.tail_output_frames 99 differs from the events record/);
});

test('4c: every binding is an absolute path inside the episode root (the logo only through an explicit allowance) and hash-verified', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const cfg = adapt(plain());
  const b = cfg.bindings;
  const all = [b.opening, b.logo, b.music, b.ambience, ...Object.values(b.tails), ...Object.values(b.icons), ...b.cards.flatMap((c) => [c.icon, c.audio]),
    ...Object.values(b.shots).flatMap((s) => [s.audio, ...Object.values(s.segments)])];
  assert.ok(all.length > 60);
  for (const x of all) {
    assert.ok(path.isAbsolute(x.path), x.path);
    assert.equal(shaOf(x.path), x.sha256, x.path);
    if (x !== b.logo) assert.ok(path.relative(EP, x.path) && !path.relative(EP, x.path).startsWith('..'), `${x.path} is inside the episode root`);
  }
  assert.equal(path.resolve(b.logo.path), path.resolve(LOGO));
  // without the allowance the logo (../../studio-app) escapes the root: refused
  assert.throws(() => adapt(plain(), {allowOutside: []}), /outside the episode root/);
  // a wrong hash in the episode text is refused
  const text = rd(TEXT_FILE);
  text.assets.opening.sha256 = '0'.repeat(64);
  assert.throws(() => adapt(plain(), {episodeText: text}), /assets\.opening: sha256 .* differs/);
  // a missing file is refused
  const text2 = rd(TEXT_FILE);
  text2.cards.Creamy.icon.path = 'assets3d/nothing.png';
  assert.throws(() => adapt(plain(), {episodeText: text2}), /cards\.Creamy\.icon: .* missing/);
});

test('4d: shots, words, onset evidence, icons and cards come from the engine config; the card windows are relative to the outro start', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const cfg = adapt(plain());
  assert.equal(cfg.timeline.introFrames, 90);
  assert.equal(cfg.timeline.outroStart, 2160);
  assert.equal(cfg.timeline.mainFrames, 2520);
  assert.equal(cfg.timeline.endCardFrames, 60);
  assert.equal(cfg.shots.length, 12);
  const s6 = cfg.shots.find((s) => s.id === 'S06_B');
  assert.deepEqual(s6.segments.map((g) => [g.id, g.from, g.frames]), [['S06_B1', 0, 150], ['S06_B2', 150, 175], ['S06_B3', 325, 50]]);
  assert.equal(s6.captionLines, 2);
  assert.ok(Number.isInteger(s6.speechOnsetF), 'the word-timing onset evidence is read');
  assert.equal(cfg.shots[0].speechOnsetF, 116);
  assert.ok(typeof s6.vi === 'string' && s6.vi.length > 10);
  assert.equal(cfg.cards.length, 12);
  assert.deepEqual([cfg.cards[0].start, cfg.cards[0].frames, cfg.cards[1].start], [0, 30, 30]);
  assert.equal(cfg.cards[0].ipa, '/ˈkriːmi/');
  assert.equal(cfg.icons.length, 19);
});

test('4e: the derived timeline (logo hold 70): 3314 main + 60 end card = 3374 frames, 12 cards of 90 frames from f2230, the plate at the end of the last card window, validates with collectIssues', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const d = derived();
  assert.equal(d.summary.total_frames, 3374);
  const cfg = adapt(d);
  assert.deepEqual(cfg.timeline, {introFrames: 90, mainFrames: 3314, endCardFrames: 60, outroStart: 2160, outroFrames: 1154});
  assert.deepEqual(cfg.cards.map((c) => [c.start, c.frames]), Array.from({length: 12}, (_, i) => [70 + 90 * i, 90]));
  assert.equal(cfg.ending.plateStart, 3310);
  assert.equal(cfg.ending.speechEndFrame, 3250.3);
  assert.equal(cfg.ending.discFadeStart, 2230);
  assert.equal(cfg.ending.tailFrom, 2445);
  assert.deepEqual([cfg.ending.discSlideStart, cfg.ending.discSlideEnd, cfg.ending.discSlideX, cfg.ending.pillLeftX], [2222, 2229, 520, 988], 'slide frames derive from the outro start (logo hold), x from ending.logo_disc_layout');
  assert.deepEqual(cfg.ending.irisCentre, [940, 570]);
  assert.deepEqual(collectIssues(cfg), []);
  const dip = cfg.transitions.find((x) => x.id === 'T1010');
  assert.equal(dip.preset, 'dip_white');
  assert.equal(dip.frames, 8);
  assert.equal(dip.tail.verifiedFrames, 1);
});

test('4f: the disc layout comes from ending.logo_disc_layout, else the episode text; with neither the adapter refuses and names the keys', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const text = rd(TEXT_FILE);
  delete text.ending.discSlideX;
  assert.throws(() => adapt(plain(), {episodeText: text}), /discSlideX .* ending\.logo_disc_layout\.slide_x or episode text ending\.discSlideX/);
  const cfg = adapt(derived(), {episodeText: text});
  assert.equal(cfg.ending.discSlideX, 520, 'the engine layout wins');
});

test('4g: the music bed policy is carried as config.music {stemSeconds, bed} (stem length read from the WAV) only when the engine declares one', (t) => {
  if (!have || !fs.existsSync(CLEAN_STEM)) return t.skip('episode engine inputs absent');
  assert.equal(adapt(plain()).music, undefined, 'no policy declared: the config is exactly as before');
  const text = rd(TEXT_FILE);
  text.assets.music = {path: path.relative(EP, CLEAN_STEM)};
  const cfg = adapt(derived(), {episodeText: text, allowOutside: [LOGO, CLEAN_STEM]});
  assert.equal(cfg.music.stemSeconds, 60);
  assert.deepEqual(music.normaliseBed(cfg.music.bed), music.normaliseBed(rd(derived().events).ending.music_bed));
  assert.equal(music.selectMusicMode(cfg), 'plan');
  assert.deepEqual(collectIssues(cfg), []);
  const p = music.planMusic({totalFrames: 3374, fps: cfg.fps, stemSeconds: cfg.music.stemSeconds, bed: cfg.music.bed, windows: music.wordWindows(cfg)});
  assert.deepEqual(p.segments.map((s) => [s.from, s.durationInFrames, s.startFromFrame, s.fadeIn, s.fadeOut]), [[0, 1680, 0, 0, 30], [1650, 1590, 90, 30, 30], [3210, 164, 90, 30, 30]]);
  assert.ok(cfg.provenance.unbound_assets.some((x) => x.what === 'assets.music'), 'an asset without a pre-recorded hash is listed as computed at adapt time');
});

test('4h: the episode text is required where the engine has none: a missing intro key, caption, card detail or string is refused naming it', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const mutate = (fn) => {
    const text = rd(TEXT_FILE);
    fn(text);
    return text;
  };
  assert.throws(() => adapt(plain(), {episodeText: mutate((x) => delete x.intro.kicker)}), /episode text intro\.kicker/);
  assert.throws(() => adapt(plain(), {episodeText: mutate((x) => delete x.strings.cardsHeader)}), /episode text strings\.cardsHeader/);
  assert.throws(() => adapt(plain(), {episodeText: mutate((x) => delete x.shotVi.S03_A)}), /episode text shotVi\.S03_A/);
  assert.throws(() => adapt(plain(), {episodeText: mutate((x) => delete x.cards.Cheese)}), /episode text cards\.Cheese/);
  assert.throws(() => adapt(plain(), {episodeText: mutate((x) => delete x.assets.music)}), /episode text assets\.music/);
  assert.throws(() => adapt(plain(), {episodeText: null}), /episode text is required/);
});

test('4i: only a receipt-bound build is adapted (a hand-built token is refused), and an engine build summary with edited bytes is refused by loadBuild', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const b = plain();
  const a = adapter();
  const loaded = a.loadBuild({reviewConfig: b.reviewConfig, events: b.events, receipt: b.receipt, episodeRoot: EP});
  assert.equal(loaded.bound.receipt.kind, 'engine-build-summary');
  assert.throws(() => a.adaptEngine(loaded.review, loaded.events, {bound: {...loaded.bound}, episodeRoot: EP, episodeText: rd(TEXT_FILE), allowOutside: [LOGO]}), /receipt-bound build/);
  assert.throws(() => a.adaptEngine(loaded.review, loaded.events, {episodeRoot: EP, episodeText: rd(TEXT_FILE), allowOutside: [LOGO]}), /receipt-bound build/);
  const copy = path.join(SCRATCH, 'edited-events.json');
  const ev = rd(b.events);
  ev.transitions[0].motivation = 'edited';
  fs.writeFileSync(copy, JSON.stringify(ev));
  assert.throws(() => a.loadBuild({reviewConfig: b.reviewConfig, events: copy, receipt: b.receipt, episodeRoot: EP}), /events file sha256 .* differs from the receipt/);
});

test('4j: the kit feasibility table agrees with the ENGINE (presets_cli) on the real handles T1010 / T1310 / T1610: same availability, needs, have, max frames and refusal text', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const cfg = adapt(plain());
  const handles = {};
  for (const id of ['T1010', 'T1310', 'T1610']) {
    const r = spawnSync('python', ['-I', path.join(SKILL, 'engine', 'editorial', 'presets_cli.py'), '--episode', pin.episode, '--boundaries', pin.boundaries,
      '--boundary', id, ...pin.outsideArgs], {encoding: 'utf8', cwd: WORKSPACE});
    assert.equal(r.status, 0, r.stderr.slice(-400));
    const engine = JSON.parse(r.stdout).boundaries[0];
    const kit = feas.presetAvailability(cfg, id, {mode: 'review', catalog});
    assert.deepEqual(Object.keys(kit.presets).sort(), Object.keys(engine.presets).sort(), id);
    for (const [name, e] of Object.entries(engine.presets)) {
      const k = kit.presets[name];
      assert.equal(k.available, e.available, `${id} ${name} available`);
      assert.equal(k.needsTailFrames, e.needs_tail_frames, `${id} ${name} needs`);
      assert.equal(k.haveNativeFrames, e.have_native_frames, `${id} ${name} have`);
      assert.equal(k.maxFrames, e.max_frames, `${id} ${name} max`);
      assert.equal(k.whyNot, e.reason, `${id} ${name} reason`);
    }
    handles[id] = kit.tail.haveNativeFrames;
    assert.equal(kit.presets.crossfade.maxFrames, {T1010: 8, T1310: 16, T1610: 18}[id]);
  }
  assert.deepEqual(handles, {T1010: 7, T1310: 13, T1610: 15});
  // a boundary without a tail clip: only the no-tail presets, with the engine's reason text
  const none = feas.presetAvailability(cfg, 'T240', {mode: 'review', catalog});
  assert.equal(none.tail, null);
  assert.equal(none.presets.crossfade.available, false);
  assert.equal(none.presets.cut.available, true);
  assert.match(none.presets.crossfade.whyNot, /^no tail_clip is declared on this boundary; no GPU work is requested/);
});

test('4k: the CLI writes the config and its provenance; render.cjs --list-presets prints the real handles; render.cjs --check-only passes on the derived-timeline build', (t) => {
  if (!have) return t.skip('episode engine inputs absent');
  const browser = process.env.REMOTION_BROWSER || [path.join(WORKSPACE, '.remotion', 'chrome-headless-shell', 'win64', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
    path.join(WORKSPACE, 'jenniejoy-zoo-film', 'node_modules', '.remotion', 'chrome-headless-shell', 'win64', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')].find((p) => fs.existsSync(p));
  const d = derived();
  const text = rd(TEXT_FILE);
  text.assets.music = {path: path.relative(EP, CLEAN_STEM)};
  const textFile = path.join(SCRATCH, 'episode-text-derived.json');
  fs.writeFileSync(textFile, JSON.stringify(text));
  const out = path.join(SCRATCH, 'kit-config-derived.json');
  const r = spawnSync(process.execPath, [ADAPTER, '--review-config', d.reviewConfig, '--events', d.events, '--receipt', d.receipt, '--episode-root', EP, '--episode-text', textFile,
    '--allow-outside', LOGO, '--allow-outside', CLEAN_STEM, '--out', out], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  const cfg = rd(out);
  assert.equal(cfg.provenance.adapter.sha256, shaOf(ADAPTER));
  assert.equal(cfg.provenance.episode_text.sha256, shaOf(textFile));
  assert.equal(cfg.provenance.build_receipt.kind, 'engine-build-summary');
  assert.deepEqual(collectIssues(cfg), []);
  const list = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', out, '--list-presets', '--boundary', 'T1010'], {encoding: 'utf8', env: {...process.env, REMOTION_BROWSER: ''}});
  assert.equal(list.status, 0, list.stderr);
  const row = JSON.parse(list.stdout).boundaries[0];
  assert.equal(row.tail.haveNativeFrames, 7);
  if (!browser) return t.skip('no cached chrome-headless-shell: --check-only not run');
  const check = spawnSync(process.execPath, [path.join(KIT, 'render.cjs'), '--config', out, '--mode', 'review', '--check-only', '--browser', browser], {encoding: 'utf8'});
  assert.equal(check.status, 0, check.stderr.slice(-1500));
  assert.match(check.stdout, /check-only ok: Film 1920x1080 3374 f @30/);
});
