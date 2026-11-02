// T-E45 edit path: the AUDIO slice (lib/segdeps.cjs audioSlice) is exactly what the one whole-film mix depends on.
//   - clips are muted in the compositor (`<OffthreadVideo muted>`): a clip that carries a loud audio track changes nothing in the mix, so
//     no picture / tail / transition row is in the audio slice (a transition effect never re-renders the mix);
//   - every config leaf OUTSIDE the slice is mutated (all at once, greedily) and the PCM mix must be BYTE-IDENTICAL;
//   - leaves INSIDE the slice (tail start, a dialogue WAV, a card WAV, the card windows) change the PCM and the key;
//   - MUTANT: a slice function that drops the end-tail part is caught by the same check, naming the leaf.
// Real compositor, CPU, one bundle + one browser per harness; skipped without a cached browser or with KIT_SKIP_RENDER_SMOKE=1.
import test from 'node:test';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import crypto from 'node:crypto';
import {assert, dep, fs, os, path, KIT, BROWSER, FONTS, PACKAGES, WORKSPACE, have, richConfig, mutateLeaf, leaves, leafName, clone} from './p2-lib.mjs';
import {validateConfig, validateSources} from '../src/validate.mjs';
import {tailWindow} from '../src/picture-mode.mjs';
import {selectMusicMode} from '../src/music-plan.mjs';

const require = createRequire(import.meta.url);
const {stage} = require('../lib/stage.cjs');
const PINS = {kit: 'test', remotion: 'test', mode: 'review', scale: 1};
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const ffmpeg = (args) => assert.equal(spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], {encoding: 'utf8'}).status, 0);
const audioKey = (cfg, sliceFn = dep.audioSlice) => dep.nodeKey('audio', sliceFn(cfg, {mode: 'review'}), PINS);

// the rich synthetic episode with AUDIBLE stems (different tones) and the end-tail fade numbers present as leaves
function audibleConfig(dir) {
  const config = richConfig(dir);
  const tone = (name, hz, seconds) => {
    const f = path.join(dir, `${name}.wav`);
    ffmpeg(['-f', 'lavfi', '-i', `sine=frequency=${hz}:sample_rate=48000:duration=${seconds}`, '-ac', '1', f]);
    return {path: f, sha256: sha(f)};
  };
  const b = config.bindings;
  b.music = tone('music', 220, 20);
  const dialogue = tone('dialogue', 330, 2);
  for (const id of Object.keys(b.shots)) b.shots[id].audio = dialogue;
  const card = tone('card', 550, 1.5);
  b.cards = b.cards.map((c) => ({...c, audio: card}));
  config.ending = {...config.ending, tailFadeIn: 4, tailFadeStart: 20};
  return config;
}

async function openAudioHarness(config, workDir) {
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
  let n = 0;
  return {
    valid(cfg) {
      try {
        validateConfig(cfg);
        validateSources(cfg, staged.sources, {partial: false});
        return true;
      } catch {
        return false;
      }
    },
    async pcm(cfg) {
      const {bindings, provenance, ...kitConfig} = cfg;
      const inputProps = {config: kitConfig, scale: 1, label: cfg.review.label, previewMark: null, sources: staged.sources, partial: false};
      const composition = await R.selectComposition({serveUrl, id: 'Film', inputProps, puppeteerInstance: browser, logLevel: 'error'});
      n += 1;
      const file = path.join(workDir, `mix-${n}.wav`);
      await R.renderMedia({serveUrl, composition, inputProps, codec: 'wav', sampleRate: 48000, outputLocation: file, puppeteerInstance: browser, logLevel: 'error', concurrency: 1});
      const hash = sha(file);
      fs.rmSync(file, {force: true});
      return hash;
    },
    close: () => browser.close({silent: true}),
  };
}

// every leaf outside `bindings` (the compositor never sees them; a binding is tested by swapping the file) that is outside the audio slice
async function audioPropertyCheck({harness, config, sliceFn = dep.audioSlice}) {
  const baseKey = audioKey(config, sliceFn);
  const base = await harness.pcm(config);
  let acc = config;
  const accepted = [];
  let inSlice = 0;
  for (const leaf of leaves(config).filter((l) => !['provenance', 'bindings'].includes(l.path[0]))) {
    const candidate = mutateLeaf(acc, leaf.path);
    if (!candidate || !harness.valid(candidate)) continue;
    if (audioKey(candidate, sliceFn) !== baseKey) {
      inSlice += 1;
      continue;
    }
    acc = candidate;
    accepted.push(leaf.path);
  }
  const same = async (cfg) => (await harness.pcm(cfg)) === base;
  const out = {accepted: accepted.length, in_slice: inSlice, offenders: []};
  if (await same(acc)) return {...out, ok: true, base};
  const apply = (paths) => paths.reduce((cfg, p) => mutateLeaf(cfg, p), config);
  const search = async (paths) => {
    if (paths.length === 1) return paths;
    const half = Math.ceil(paths.length / 2);
    const found = [];
    for (const part of [paths.slice(0, half), paths.slice(half)]) if (part.length && !(await same(apply(part)))) found.push(...await search(part));
    return found.length ? found : paths;
  };
  return {...out, ok: false, offenders: (await search(accepted)).map(leafName)};
}

test('R15-A1: the music-mode rule of the audio slice is the compositor\'s own selectMusicMode (drift guard)', () => {
  const base = richConfig(fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15a-')));
  const variants = [base, {...clone(base), music: {stemSeconds: 20, bed: {extend: 'none'}}}, {...clone(base), music: {stemSeconds: 20}, ending: {...base.ending, musicBed: {extend: 'none'}}}, {...clone(base), music: {stemSeconds: 20}}];
  for (const v of variants) assert.equal(dep.musicModeOf(v), selectMusicMode(v), JSON.stringify([v.music, v.ending && v.ending.musicBed]));
});

test('R15-A2: pure slice facts: transitions, pictures, tails, captions, icons, colours and strings are NOT audio; stems, dialogue / card WAVs, windows and the tail ARE', () => {
  const cfg = audibleConfig(fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15a-')));
  const set = (p, v, base = cfg) => {
    const next = clone(base);
    let at = next;
    for (const x of p.slice(0, -1)) at = at[x];
    at[p[p.length - 1]] = v;
    return next;
  };
  const same = [
    [['transitions', 0, 'frames'], 9], [['transitions', 1, 'params'], {x: 1}], [['transitions', 1, 'tail', 'startFrom'], 5], [['shots', 1, 'vi'], 'khac'],
    [['icons', 0, 'frame'], 101], [['theme', 'mint'], '#000000'], [['strings', 'cardsHeader'], 'Other'], [['ending', 'plateEn'], 'Other'], [['intro', 'kicker'], 'K2'], [['review', 'label'], 'L2'],
    [['shots', 1, 'words', 0, 'startF'], 99], // legacy music: word timing is not audio
    [['bindings', 'shots', 'S2', 'segments', 'S2', 'sha256'], '1'.repeat(64)], [['bindings', 'tails', 'B', 'sha256'], '2'.repeat(64)],
  ];
  for (const [p, v] of same) assert.equal(audioKey(set(p, v)), audioKey(cfg), `${p.join('.')} must not be in the audio slice`);
  const differs = [
    [['ending', 'tailFrom'], 1234], [['ending', 'tailFadeIn'], 9], [['cards', 1, 'start'], 40], [['cards', 0, 'frames'], 20], [['shots', 2, 'start'], 151], [['timeline', 'mainFrames'], 361],
    [['timeline', 'outroStart'], 271], [['fps'], 25], [['bindings', 'cards', 0, 'audio', 'sha256'], '0'.repeat(64)], [['bindings', 'shots', 'S2', 'audio', 'sha256'], '1'.repeat(64)],
    [['bindings', 'music', 'sha256'], '3'.repeat(64)],
  ];
  for (const [p, v] of differs) assert.notEqual(audioKey(set(p, v)), audioKey(cfg), `${p.join('.')} must be in the audio slice`);
  // with a music bed POLICY the ducking follows every word window: word timing is audio then
  const plan = set(['music'], {stemSeconds: 20, bed: {extend: 'none'}});
  assert.notEqual(audioKey(set(['shots', 1, 'words', 0, 'startF'], 99, plan)), audioKey(plan));
  assert.notEqual(audioKey(plan), audioKey(cfg), 'the music mode is part of the key');
});

test('R15-A3: the audio mix does not depend on any config leaf outside the slice (PCM byte-identical), a clip with a LOUD audio track changes nothing, the slice leaves do; a dropped part is killed', {timeout: 1800000}, async (t) => {
  if (!have()) return t.skip('no browser / Remotion packages / fonts, or KIT_SKIP_RENDER_SMOKE=1');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15a-'));
  const config = audibleConfig(dir);
  const harness = await openAudioHarness(config, dir);
  try {
    const res = await audioPropertyCheck({harness, config});
    process.stdout.write(`R15-A3 report ${JSON.stringify({accepted: res.accepted, in_slice: res.in_slice})}\n`);
    assert.equal(res.ok, true, `leaves outside the audio slice changed the mix: ${res.offenders.join(', ')}`);
    assert.ok(res.accepted >= 60, `only ${res.accepted} leaves mutated outside the slice (vacuous)`);
    const base = res.base;

    // sensitivity: slice leaves change the PCM (and the key)
    for (const [p, v] of [[['ending', 'tailFrom'], 130], [['ending', 'tailFadeStart'], 12]]) {
      const m = clone(config);
      m[p[0]][p[1]] = v;
      assert.notEqual(audioKey(m), audioKey(config));
      assert.notEqual(await harness.pcm(m), base, `${p.join('.')} did not change the mix: the sensitivity case is vacuous`);
    }

    // the clips' own audio is muted: re-encode every picture clip with a loud tone, the mix stays byte-identical
    const loud = clone(config);
    for (const shotId of Object.keys(loud.bindings.shots)) {
      for (const [segId, binding] of Object.entries(loud.bindings.shots[shotId].segments)) {
        const f = path.join(dir, `loud-${shotId}-${segId}.mp4`);
        ffmpeg(['-i', binding.path, '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000', '-shortest', '-c:v', 'copy', '-c:a', 'aac', f]);
        loud.bindings.shots[shotId].segments[segId] = {path: f, sha256: sha(f)};
      }
    }
    const loudHarness = await openAudioHarness(loud, path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'kit-r15a-')), '.'));
    try {
      assert.equal(await loudHarness.pcm(loud), base, 'a picture clip with an audible audio track changed the mix: clips are NOT muted, the slice must include them');
    } finally {
      await loudHarness.close();
    }
    assert.equal(audioKey(loud), audioKey(config), 'the loud clips are different files but not in the audio slice');

    // MUTANT: the end-tail part dropped from the slice -> the check goes red and names the leaf
    const dropping = (name) => (cfg, ctx) => {
      const slice = dep.audioSlice(cfg, ctx);
      delete slice.parts[name];
      return slice;
    };
    const m1 = await audioPropertyCheck({harness, config, sliceFn: dropping('audio.endTail')});
    assert.equal(m1.ok, false, 'mutant "audio.endTail dropped" survived');
    assert.ok(m1.offenders.some((o) => o.startsWith('ending.tail')), `tail leaves not named: ${m1.offenders.join(', ')}`);
    const m2 = await audioPropertyCheck({harness, config, sliceFn: dropping('audio.timeline')});
    assert.equal(m2.ok, false, 'mutant "audio.timeline dropped" survived');
    assert.ok(m2.offenders.some((o) => o.startsWith('timeline.')), `timeline leaves not named: ${m2.offenders.join(', ')}`);
    process.stdout.write(`R15-A3 mutants killed: endTail -> ${m1.offenders.join(',')}; timeline -> ${m2.offenders.join(',')}\n`);
  } finally {
    await harness.close();
    fs.rmSync(dir, {recursive: true, force: true});
  }
});
