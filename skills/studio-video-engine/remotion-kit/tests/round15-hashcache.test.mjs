// T-E45 edit path: the verified-hash cache (lib/hashcache.cjs). A hit costs a stat, never a read; a change in size / mtime is a miss; the
// one thing it cannot see (content changed with size AND mtime restored) is the declared trust boundary and is what --rehash-all audits.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {test} from 'node:test';

const require = createRequire(import.meta.url);
const {HashCache, NoCache, sha256Stream} = require('../lib/hashcache.cjs');

const ref = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'kit-hc-'));
// a file that is old enough for its hash to be trusted (the racy rule needs the mtime well before the hashing time)
function aged(file, content, ageSeconds = 3600) {
  fs.writeFileSync(file, content);
  const t = new Date(Date.now() - ageSeconds * 1000);
  fs.utimesSync(file, t, t);
}

test('R15-H1: second lookup is a HIT (no read), the digest equals a plain sha256, bytes_not_read counts the file', () => {
  const dir = tmp();
  const f = path.join(dir, 'clip.bin');
  const bytes = crypto.randomBytes(300000);
  aged(f, bytes);
  const cache = new HashCache({file: path.join(dir, 'hash-cache.json')});
  assert.equal(cache.sha256(f), ref(bytes));
  assert.deepEqual([cache.stats().hits, cache.stats().misses, cache.stats().bytes_read], [0, 1, 300000]);
  assert.equal(cache.sha256(f), ref(bytes));
  const s = cache.stats();
  assert.deepEqual([s.hits, s.misses, s.bytes_not_read, s.bytes_read], [1, 1, 300000, 300000]);
});

test('R15-H2: the cache survives a save / reload; an unreadable cache file is an empty cache (and says so)', () => {
  const dir = tmp();
  const f = path.join(dir, 'a.bin');
  aged(f, 'hello cache');
  const file = path.join(dir, 'hash-cache.json');
  const a = new HashCache({file});
  a.sha256(f);
  assert.equal(a.save(), true);
  const b = new HashCache({file});
  assert.equal(b.sha256(f), ref('hello cache'));
  assert.equal(b.stats().hits, 1);
  fs.writeFileSync(file, '{not json');
  const c = new HashCache({file});
  assert.ok(c.stats().load_error, 'the load error is reported');
  assert.equal(c.sha256(f), ref('hello cache'));
  assert.equal(c.stats().hits, 0, 'nothing is trusted from a broken cache');
});

test('R15-H3: GATE - a file whose size or mtime changed is a MISS and is hashed again', () => {
  const dir = tmp();
  const f = path.join(dir, 'a.bin');
  aged(f, 'first version');
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  cache.sha256(f);
  aged(f, 'second version, longer'); // new size
  assert.equal(cache.sha256(f), ref('second version, longer'));
  aged(f, 'second version, LONGER', 1800); // same size, new mtime
  assert.equal(cache.sha256(f), ref('second version, LONGER'));
  assert.equal(cache.stats().hits, 0);
  assert.equal(cache.stats().misses, 3);
});

test('R15-H4: DECLARED TRUST BOUNDARY - same size AND restored mtime is not detected; --rehash-all (audit) catches it and repairs the entry', () => {
  const dir = tmp();
  const f = path.join(dir, 'a.bin');
  aged(f, 'AAAAAAAA');
  const st = fs.statSync(f);
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  const honest = cache.sha256(f);
  fs.writeFileSync(f, 'BBBBBBBB'); // same size
  fs.utimesSync(f, st.atime, st.mtime); // mtime restored: the stat identity is unchanged
  assert.equal(cache.sha256(f), honest, 'the cache trusts the stat identity: it returns the old digest (this is the stated boundary)');
  const audit = new HashCache({file: path.join(dir, 'hc.json'), rehashAll: true});
  assert.equal(audit.sha256(f), ref('BBBBBBBB'), '--rehash-all reads every byte');
  assert.equal(audit.stats().hits, 0);
  assert.equal(audit.stats().rehash_all, true);
  audit.save();
  const after = new HashCache({file: path.join(dir, 'hc.json')});
  assert.equal(after.sha256(f), ref('BBBBBBBB'), 'the audit repaired the entry');
});

test('R15-H5: racy rule - a file hashed within seconds of its last write is not trusted on the next lookup', () => {
  const dir = tmp();
  const f = path.join(dir, 'fresh.bin');
  fs.writeFileSync(f, 'just written');
  const cache = new HashCache({file: path.join(dir, 'hc.json')});
  cache.sha256(f);
  cache.sha256(f);
  assert.equal(cache.stats().hits, 0);
  assert.equal(cache.stats().racy, 1);
});

test('R15-H6: streaming digest equals the whole-file digest across chunk boundaries; NoCache reads everything', () => {
  const dir = tmp();
  const f = path.join(dir, 'big.bin');
  const bytes = crypto.randomBytes((4 << 20) + 12345);
  fs.writeFileSync(f, bytes);
  assert.equal(sha256Stream(f), ref(bytes));
  const none = new NoCache();
  assert.equal(none.sha256(f), ref(bytes));
  none.sha256(f);
  assert.deepEqual([none.stats().hits, none.stats().bytes_read], [0, 2 * bytes.length]);
});

test('R15-H7: a missing file is refused by name', () => {
  assert.throws(() => new HashCache().sha256(path.join(tmp(), 'nope.bin')), /nope\.bin.*missing/);
});
