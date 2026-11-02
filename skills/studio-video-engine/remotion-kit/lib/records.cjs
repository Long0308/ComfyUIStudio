'use strict';
// Render-record helpers. Every render record lists the sha256 of the SHOT SOURCES it was composited from (picture clips, tail clips, dialogue
// WAVs) and, given the previous record, says whether any of them changed. An effect change is a compositing change: the statement
// "composite-only: no shot source changed" is the proof that no shot video was re-rendered. Pure Node, no Remotion.

const fs = require('node:fs');
const crypto = require('node:crypto');

const SHOT_ROLES = ['picture', 'tail', 'dialogue'];

// the stable key of a staged source: role + the staged file name without its sequence number and extension (stage.cjs names files
// `NNN-<safe label>.<ext>`), so the same source has the same key in a record written before and after the label field existed
const stagedKey = (staged) => String(staged).replace(/^\d+-/, '').replace(/\.[^./]+$/, '');
const sha256Bytes = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');

/** @param {Array<object>} used the `used` list stage() returns @returns {Array<{role,label,key,source_path,source_sha256}>} sorted by key */
function shotSources(used) {
  return (used || [])
    .filter((u) => SHOT_ROLES.includes(u.role))
    .map((u) => ({role: u.role, label: u.label, key: `${u.role}:${stagedKey(u.staged)}`, source_path: u.source_path, source_sha256: u.source_sha256}))
    .sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

// one digest over the whole set (order independent), for a quick equality check between two records
function shotSourcesDigest(sources) {
  const rows = [...sources].map((s) => [s.key, s.source_sha256]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return sha256Bytes(JSON.stringify(rows));
}

function readPrevious(file) {
  if (!file || !fs.existsSync(file)) throw new Error(`previous record ${file} is missing`);
  const bytes = fs.readFileSync(file);
  let doc;
  try {
    doc = JSON.parse(bytes.toString('utf8').replace(/^﻿/u, ''));
  } catch (error) {
    throw new Error(`previous record ${file} is not JSON (${error.message.split('\n')[0]})`);
  }
  let sources;
  if (Array.isArray(doc.shot_sources)) sources = doc.shot_sources;
  else if (Array.isArray(doc.staged_inputs)) sources = shotSources(doc.staged_inputs); // a record from before shot_sources existed
  else throw new Error(`previous record ${file} has no shot_sources or staged_inputs: it cannot prove which shot sources it used`);
  return {sources, sha256: sha256Bytes(bytes), output_sha256: doc.output_sha256 || null, config_sha256: doc.config_sha256 || null};
}

/**
 * @param {Array<object>} current shotSources() of this run
 * @param {{previousRecord:string, partial?:boolean}} opts partial = this run staged only the sources its frames need (stills / --stage-needed)
 * @returns {{value:boolean, scope:'all'|'partial', previous:object, unchanged:number, changed:Array<{key,previous,current}>, statement:string}}
 */
function compositeOnly(current, {previousRecord, partial = false}) {
  const prev = readPrevious(previousRecord);
  const before = new Map(prev.sources.map((s) => [s.key || `${s.role}:${stagedKey(s.staged || '')}`, s.source_sha256]));
  const now = new Map(current.map((s) => [s.key, s.source_sha256]));
  const changed = [];
  let unchanged = 0;
  for (const [key, hash] of now) {
    if (!before.has(key)) changed.push({key, previous: null, current: hash});
    else if (before.get(key) !== hash) changed.push({key, previous: before.get(key), current: hash});
    else unchanged += 1;
  }
  // a partial run did not stage everything: a previous source it did not stage is not a change, only a full run can drop one
  if (!partial) for (const [key, hash] of before) if (!now.has(key)) changed.push({key, previous: hash, current: null});
  changed.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const value = changed.length === 0;
  const ref = `${prev.sha256.slice(0, 12)} (${previousRecord})`;
  const scope = partial ? 'partial' : 'all';
  const compared = partial ? ` (${now.size} of ${before.size} previous sources compared: partial staging)` : '';
  const short = (h) => (h ? h.slice(0, 12) : 'none');
  const statement = value
    ? `composite-only: no shot source changed vs ${ref}${compared}`
    : `NOT composite-only: ${changed.length} shot source(s) changed vs ${ref}${compared}: ${changed.map((c) => `${c.key} ${short(c.previous)} -> ${short(c.current)}`).join(', ')}`;
  return {
    value, scope, previous: {path: previousRecord, sha256: prev.sha256, output_sha256: prev.output_sha256, config_sha256: prev.config_sha256},
    unchanged, changed, statement,
  };
}

module.exports = {shotSources, shotSourcesDigest, compositeOnly, stagedKey, SHOT_ROLES};
