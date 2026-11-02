// A PINNED copy of the engine inputs of the first episode, for tests that run the REAL `jjv editorial build-config`.
// Production inputs (engine/episode.json, DELIVERY-CONTRACT.json, boundaries.json) change while an episode is being produced; a test must not
// depend on them. The fixtures under tests/fixtures/ep04-pinned/ are the copies the tests were written against (2580-frame contract, plain
// boundaries). The media they reference is reached through a scratch episode root made of HARD LINKS to the real files (same volume, no copy, nothing
// under production-local is written or changed): the engine resolves real paths, so a hard-linked tree behaves exactly like an episode folder and
// records episode-relative paths (a junction would resolve to the real folder and make every path look "outside the root").
//
// Layout (<workspace>/.remotion/ep04-pin-cache/<fixtures sha>/production-local/): JennieJoyKids-Story/04-milk-and-mom/{engine,DELIVERY-CONTRACT.json,audio,clips,...}
// and studio-app/logo-*.png (a copy, so the boundaries' relative logo path `../../studio-app/...` resolves inside the pin; name it with --allow-outside).
// The cache must be on the same volume as the episode folder (KIT_PIN_DIR may relocate it); otherwise the pin is reported unavailable and the tests skip.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KIT = path.resolve(HERE, '..');
const WORKSPACE = path.resolve(KIT, '../../../..');
export const EP = path.join(WORKSPACE, 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom');
const REAL_LOGO = path.join(WORKSPACE, 'production-local', 'studio-app', 'logo-jenniejoy-kids.png');
const FIXTURES = path.join(HERE, 'fixtures', 'ep04-pinned');
const FILES = ['episode.json', 'boundaries.json', 'shots.json', 'mouth-boxes.json'];
// what the engine reads from the episode folder: every top-level folder except these (the cut builds, tools and workflows are not inputs); editorial only
// contributes the word-timing documents
const SKIP_TOP = new Set(['engine', 'editorial', 'workflows', 'tools', 'handoffs']);

function digest(list) {
  const h = crypto.createHash('sha256');
  for (const b of list) h.update(b);
  return h.digest('hex').slice(0, 12);
}

function removeTree(dir) {
  fs.rmSync(dir, {recursive: true, force: true}); // hard links only: unlinking never touches the real file
}

function linkTree(from, to) {
  fs.mkdirSync(to, {recursive: true});
  for (const entry of fs.readdirSync(from, {withFileTypes: true})) {
    const src = path.join(from, entry.name);
    const dst = path.join(to, entry.name);
    if (entry.isDirectory()) linkTree(src, dst);
    else if (entry.isFile()) fs.linkSync(src, dst);
  }
}

function build() {
  if (!fs.existsSync(EP) || !fs.existsSync(REAL_LOGO)) return {available: false, reason: 'episode folder absent'};
  const fixtureFiles = [...FILES.map((f) => path.join(FIXTURES, f)), path.join(FIXTURES, 'DELIVERY-CONTRACT.json')];
  if (fixtureFiles.some((f) => !fs.existsSync(f))) return {available: false, reason: 'fixtures/ep04-pinned is incomplete'};
  const stamp = digest(fixtureFiles.map((f) => fs.readFileSync(f)));
  const base = process.env.KIT_PIN_DIR || path.join(WORKSPACE, '.remotion', 'ep04-pin-cache');
  const final = path.join(base, stamp);
  const top = path.join(final, 'production-local');
  const root = path.join(top, 'JennieJoyKids-Story', '04-milk-and-mom');
  const done = path.join(root, '.pin-complete');
  if (!fs.existsSync(done)) {
    // test files run in parallel processes: build in a private directory, then move it into place (the loser of the race discards its copy)
    const mine = path.join(base, `${stamp}.build-${process.pid}`);
    removeTree(mine);
    const myTop = path.join(mine, 'production-local');
    const myRoot = path.join(myTop, 'JennieJoyKids-Story', '04-milk-and-mom');
    try {
      fs.mkdirSync(path.join(myRoot, 'engine'), {recursive: true});
      fs.mkdirSync(path.join(myTop, 'studio-app'), {recursive: true});
      for (const f of FILES) fs.copyFileSync(path.join(FIXTURES, f), path.join(myRoot, 'engine', f));
      fs.copyFileSync(path.join(FIXTURES, 'DELIVERY-CONTRACT.json'), path.join(myRoot, 'DELIVERY-CONTRACT.json'));
      fs.copyFileSync(REAL_LOGO, path.join(myTop, 'studio-app', path.basename(REAL_LOGO)));
      for (const entry of fs.readdirSync(EP, {withFileTypes: true})) {
        if (!entry.isDirectory() || SKIP_TOP.has(entry.name)) continue;
        linkTree(path.join(EP, entry.name), path.join(myRoot, entry.name));
      }
      for (const entry of fs.readdirSync(path.join(EP, 'editorial'), {withFileTypes: true})) {
        if (entry.isDirectory() && entry.name.startsWith('word-timing-')) linkTree(path.join(EP, 'editorial', entry.name), path.join(myRoot, 'editorial', entry.name));
      }
      fs.writeFileSync(path.join(myRoot, '.pin-complete'), stamp);
    } catch (error) {
      removeTree(mine);
      return {available: false, reason: `could not hard-link the episode folder into ${base} (${error.code || error.message}); set KIT_PIN_DIR to a directory on the same volume`};
    }
    try {
      fs.renameSync(mine, final);
    } catch {
      removeTree(mine);
      for (let i = 0; i < 100 && !fs.existsSync(done); i += 1) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 100);
      if (!fs.existsSync(done)) return {available: false, reason: 'could not build the episode pin'};
    }
  }
  const logo = path.join(top, 'studio-app', path.basename(REAL_LOGO));
  return {
    available: true, reason: null, root, episode: path.join(root, 'engine', 'episode.json'), boundaries: path.join(root, 'engine', 'boundaries.json'), logo,
    // arguments every build-config / presets_cli call needs: the shared logo sits outside the episode root
    outsideArgs: ['--allow-outside', logo],
    // the word-timing document INSIDE the pin (the engine records an outside file by name only): pin.wordTiming('v003')
    wordTiming: (version = 'v003') => path.join(root, 'editorial', `word-timing-${version}`, `WORD-TIMING-${version}.json`),
  };
}

export const pin = build();
