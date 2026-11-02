// Test helper: adapt() / adaptMaster() require a receipt-bound build. Most adapter tests mutate parsed JSON clones and only care about the
// adapter logic, so they get the genuine, hash-verified `bound` of the first build through these wrappers; the binding itself (edited
// files, receipt hashes) is tested in round9.test.mjs through loadBuild() on real file copies.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const KIT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const EDITORIAL = path.resolve(KIT, '../../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
const cache = new Map();

export function boundFor(v = 'v008') {
  if (!cache.has(v)) {
    const dir = path.join(EDITORIAL, `review-hd-${v}`);
    const {loadBuild} = require(path.join(KIT, 'episodes', 'ep04', 'adapter-v008.cjs'));
    cache.set(v, loadBuild({reviewConfig: path.join(dir, 'config', `review-config-${v}.json`), events: path.join(dir, `events-${v}.json`), receipt: path.join(dir, 'RECEIPT.json')}).bound);
  }
  return cache.get(v);
}

export const withBound = (fn, v = 'v008') => (review, events, opts = {}) => fn(review, events, {bound: boundFor(v), ...opts});
export const withBoundMaster = (fn, v = 'v008') => (review, events, master, opts = {}) => fn(review, events, master, {bound: boundFor(v), ...opts});
