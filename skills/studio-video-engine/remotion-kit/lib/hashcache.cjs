'use strict';
// Verified-hash cache (T-E45 P2, "cache chunk hashes"): the sha256 of a file is remembered under the file's stat identity, so verifying a
// binding whose bytes have not changed costs one stat() instead of reading the file (a 4K master core is gigabytes).
//
// Trust boundary (declared, tested): an entry is trusted when the file's {absolute path, size, mtime in nanoseconds, inode} equal the values
// recorded when it was hashed AND the file was already older than RACY_MS when it was hashed (the racy-timestamp rule of git's index: a file
// rewritten within one timestamp tick of being hashed could keep the same stat). A file whose CONTENT changes while size, mtime and inode are
// all restored is NOT detected: that is what `rehashAll` (CLI `--rehash-all`) is for, the audit path that ignores every entry and
// re-reads every byte. Anything else (new size, new mtime, replaced file) is a miss and the file is hashed again.
//
//   const cache = new HashCache({file: 'CACHE/hash-cache.json'});   // rehashAll: true = audit mode
//   cache.sha256(path)       -> hex      (hit: no read)
//   cache.save()             -> writes the file atomically (only when something changed)
//   cache.stats()            -> {hits, misses, racy, bytes_read, bytes_not_read, files}
//
// Pure Node, no Remotion. Streaming read: a file larger than 2 GB is hashed without being held in memory.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const SCHEMA = 'jjk-remotion-kit/hash-cache/v1';
const RACY_MS = 2000;
const CHUNK = 4 << 20;

// sha256 of a file by streaming (same digest as reading it whole)
function sha256Stream(file) {
  const h = crypto.createHash('sha256');
  const fd = fs.openSync(file, 'r');
  try {
    const buf = Buffer.allocUnsafe(CHUNK);
    for (;;) {
      const n = fs.readSync(fd, buf, 0, CHUNK, null);
      if (n === 0) break;
      h.update(n === CHUNK ? buf : buf.subarray(0, n));
    }
  } finally {
    fs.closeSync(fd);
  }
  return h.digest('hex');
}

// copy src to dest (streaming) and return the sha256 of the bytes that were written: ONE read verifies and stages
function copyHashed(src, dest) {
  const h = crypto.createHash('sha256');
  const from = fs.openSync(src, 'r');
  let to;
  try {
    to = fs.openSync(dest, 'w');
    const buf = Buffer.allocUnsafe(CHUNK);
    for (;;) {
      const n = fs.readSync(from, buf, 0, CHUNK, null);
      if (n === 0) break;
      const chunk = n === CHUNK ? buf : buf.subarray(0, n);
      h.update(chunk);
      let at = 0;
      while (at < n) at += fs.writeSync(to, chunk, at, n - at);
    }
  } finally {
    fs.closeSync(from);
    if (to !== undefined) fs.closeSync(to);
  }
  return h.digest('hex');
}

const identityOf = (file) => {
  const st = fs.statSync(file, {bigint: true});
  return {size: Number(st.size), mtime_ns: st.mtimeNs.toString(), ino: st.ino.toString()};
};

class HashCache {
  constructor({file = null, rehashAll = false} = {}) {
    this.file = file ? path.resolve(file) : null;
    this.rehashAll = Boolean(rehashAll);
    this.entries = {};
    this.memos = {};
    this.dirty = false;
    this.loadError = null;
    this.counts = {hits: 0, misses: 0, racy: 0, bytes_read: 0, bytes_not_read: 0};
    if (this.file && fs.existsSync(this.file)) {
      try {
        const doc = JSON.parse(fs.readFileSync(this.file, 'utf8').replace(/^﻿/u, ''));
        if (doc.schema !== SCHEMA || typeof doc.entries !== 'object' || doc.entries === null) throw new Error(`not a ${SCHEMA} document`);
        this.entries = doc.entries;
        this.memos = doc.memos && typeof doc.memos === 'object' ? doc.memos : {};
      } catch (error) {
        // an unreadable cache is an empty cache (never a source of truth): everything is hashed again and the file is rewritten
        this.loadError = error.message;
        this.entries = {};
        this.memos = {};
        this.dirty = true;
      }
    }
  }

  sha256(file) {
    const abs = path.resolve(file);
    if (!fs.existsSync(abs)) throw new Error(`cannot hash ${abs}: the file is missing`);
    const id = identityOf(abs);
    const e = this.entries[abs];
    if (!this.rehashAll && e && e.size === id.size && e.mtime_ns === id.mtime_ns && e.ino === id.ino) {
      if (e.racy) {
        this.counts.racy += 1; // hashed too soon after its last write: not trusted
      } else {
        this.counts.hits += 1;
        this.counts.bytes_not_read += id.size;
        return e.sha256;
      }
    }
    const hashedAtNs = BigInt(Date.now()) * 1000000n;
    const sha = sha256Stream(abs);
    this.counts.misses += 1;
    this.counts.bytes_read += id.size;
    // the identity after the read must equal the one before it, otherwise the file changed while it was hashed: remember nothing
    const after = identityOf(abs);
    if (after.size === id.size && after.mtime_ns === id.mtime_ns && after.ino === id.ino) {
      const age = Number(hashedAtNs - BigInt(id.mtime_ns)) / 1e6;
      this.entries[abs] = {...id, sha256: sha, hashed_at: new Date().toISOString(), ...(age < RACY_MS ? {racy: true} : {})};
      this.dirty = true;
    } else if (this.entries[abs]) {
      delete this.entries[abs];
      this.dirty = true;
    }
    return sha;
  }

  // a derived fact about CONTENT (e.g. the frame count of a clip), remembered under the content's sha256: it can never go stale
  memo(kind, sha, compute) {
    const bucket = (this.memos[kind] = this.memos[kind] || {});
    if (!this.rehashAll && Object.prototype.hasOwnProperty.call(bucket, sha)) {
      this.counts.memo_hits = (this.counts.memo_hits || 0) + 1;
      return bucket[sha];
    }
    bucket[sha] = compute();
    this.dirty = true;
    return bucket[sha];
  }

  stats() {
    return {...this.counts, files: Object.keys(this.entries).length, rehash_all: this.rehashAll, ...(this.loadError ? {load_error: this.loadError} : {})};
  }

  save() {
    if (!this.file || !this.dirty) return false;
    fs.mkdirSync(path.dirname(this.file), {recursive: true});
    const tmp = `${this.file}.tmp-${process.pid}`;
    fs.writeFileSync(tmp, `${JSON.stringify({schema: SCHEMA, saved: new Date().toISOString(), entries: this.entries, memos: this.memos})}\n`);
    fs.renameSync(tmp, this.file);
    this.dirty = false;
    return true;
  }
}

// a cache-less hasher with the same interface (stats count every byte as read)
class NoCache {
  constructor() {
    this.counts = {hits: 0, misses: 0, racy: 0, bytes_read: 0, bytes_not_read: 0};
  }
  memo(kind, sha, compute) {
    return compute();
  }
  sha256(file) {
    const abs = path.resolve(file);
    this.counts.misses += 1;
    this.counts.bytes_read += fs.statSync(abs).size;
    return sha256Stream(abs);
  }
  stats() {
    return {...this.counts, files: 0, rehash_all: false};
  }
  save() {
    return false;
  }
}

module.exports = {HashCache, NoCache, sha256Stream, copyHashed, SCHEMA, RACY_MS};
