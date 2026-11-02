'use strict';
// Receipt CONTENT checks, shared by the adapter (at adapt time) and by stage() (at staging time, which re-reads the receipt).
// A final master source is trusted only through a receipt that really says it attests this clip:
//   kind 'shot' : shot receipt (shot.json): status COMPLETED, path = the clip, sha256 = the clip's sha256
//   kind 'seam' : seam-blend receipt: a known schema and output.sha256 = the clip's sha256
//   kind 'tail' : tail receipt: either the tail map (schema + exactly one row for this transition whose clip_sha256 is the clip's)
//                 or a single COMPLETED receipt whose sha256 is the clip's
// A text file that merely contains a hash is not a receipt. Pure Node, no Remotion.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const SEAM_SCHEMAS = ['seam-blend-receipt/v001', 'seam-blend-receipt/v002'];
const TAIL_MAP_SCHEMA = 'mam-r27-master-tail-map/v1';
// the first episode's hand-made map and the engine's `jjv seedvr2 tails assemble` output (same row shape)
const TAIL_MAP_SCHEMAS = [TAIL_MAP_SCHEMA, 'jjv/master-tail-map/v1'];
const KINDS = ['shot', 'seam', 'tail'];

const sha256File = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

// ONE read: the hash and the parsed document come from the same bytes (no window between "hash checked" and "content checked")
function readDoc(file, what) {
  if (!file || !fs.existsSync(file)) throw new Error(`${what}: receipt missing (${file})`);
  const bytes = fs.readFileSync(file);
  try {
    return {doc: JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/u, '')), sha256: crypto.createHash('sha256').update(bytes).digest('hex')};
  } catch (error) {
    throw new Error(`${what}: ${file} is not a JSON receipt (${error.message.split('\n')[0]})`);
  }
}

/**
 * @param {{kind:string, path:string, clipPath:string, clipSha:string, transition?:string, label?:string}} spec
 * @returns {{sha256:string, binds:string}} receipt FILE hash and the output hash the receipt attests (always === clipSha)
 */
function verifyReceipt({kind, path: file, clipPath, clipSha, transition, label}) {
  const what = label || 'final source';
  if (!KINDS.includes(kind)) throw new Error(`${what}: unknown receipt kind '${kind}'`);
  const {doc, sha256} = readDoc(file, what);
  if (doc === null || typeof doc !== 'object') throw new Error(`${what}: ${file} is not a receipt object`);
  if (kind === 'shot') {
    if (doc.status !== 'COMPLETED') throw new Error(`${what}: shot receipt status is ${doc.status}, not COMPLETED`);
    if (doc.sha256 !== clipSha) throw new Error(`${what}: shot receipt sha256 differs from the clip`);
    if (!doc.path || path.resolve(String(doc.path)) !== path.resolve(clipPath)) throw new Error(`${what}: shot receipt path is not the bound clip`);
  } else if (kind === 'seam') {
    if (!SEAM_SCHEMAS.includes(doc.schema)) throw new Error(`${what}: seam-blend receipt schema ${doc.schema} not in ${SEAM_SCHEMAS.join(', ')}`);
    if (!doc.output || doc.output.sha256 !== clipSha) throw new Error(`${what}: seam-blend receipt output.sha256 differs from the clip`);
  } else if (TAIL_MAP_SCHEMAS.includes(doc.schema)) {
    const rows = (doc.tails || []).filter((r) => r.transition === transition && r.clip_sha256 === clipSha);
    if (rows.length !== 1) throw new Error(`${what}: the tail map has ${rows.length} rows for ${transition} with this clip sha256 (need exactly 1)`);
  } else if (doc.status !== 'COMPLETED' || doc.sha256 !== clipSha) {
    throw new Error(`${what}: tail receipt is neither the tail map nor a COMPLETED receipt for this clip`);
  }
  return {sha256, binds: clipSha};
}

module.exports = {verifyReceipt, SEAM_SCHEMAS, TAIL_MAP_SCHEMA, TAIL_MAP_SCHEMAS, KINDS, sha256File};
