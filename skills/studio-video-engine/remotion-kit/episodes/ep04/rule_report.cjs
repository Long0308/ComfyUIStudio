#!/usr/bin/env node
'use strict';
// What the kit's rules say about each review build (v008 .. latest): the config is adapted WITHOUT waivers and validated.
// Prints one JSON document on stdout: {build: {issues: [...], dip_peak_issues: n, waived_in_adapter: n, first_spoken: [{transition, first_spoken_frame, basis}]}}.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {adapt, loadBuild} = require('./adapter-v008.cjs');

const EDITORIAL = path.resolve(__dirname, '../../../../../..', 'production-local', 'JennieJoyKids-Story', '04-milk-and-mom', 'editorial');
// the engine's dip schedules: the preset catalog (schemas/transition-presets.json) holds the approved 8-row `dip_white` and the first build's 9-row `dip_white_legacy`
function engineSchedules() {
  const catalog = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'schemas', 'transition-presets.json'), 'utf8'));
  const rows = (name) => catalog.presets[name].schedule.map((e) => ({t: e.t, shot: e.shot, white: e.white}));
  return {dip_white_legacy: rows('dip_white_legacy'), dip_white: rows('dip_white')};
}
const rd = (f) => JSON.parse(fs.readFileSync(f, 'utf8').replace(/^﻿/u, ''));

(async () => {
  const {collectIssues, firstSpoken} = await import(pathToFileURL(path.join(__dirname, '..', '..', 'src', 'validate.mjs')).href);
  const out = {};
  for (const dir of fs.readdirSync(EDITORIAL).filter((d) => /^review-hd-v\d+$/.test(d) && Number(d.slice('review-hd-v'.length)) >= 8).sort()) {
    const v = dir.replace('review-hd-', '');
    const cfg = path.join(EDITORIAL, dir, 'config', `review-config-${v}.json`);
    const ev = path.join(EDITORIAL, dir, `events-${v}.json`);
    if (!fs.existsSync(cfg) || !fs.existsSync(ev)) continue;
    try {
      const build = loadBuild({reviewConfig: cfg, events: ev, receipt: path.join(EDITORIAL, dir, 'RECEIPT.json')}); // receipt-bound or refused
      const kit = adapt(build.review, build.events, {bound: build.bound});
      const waived = (kit.waivers || []).length;
      const issues = collectIssues({...kit, waivers: []});
      const basis = kit.transitions.filter((t) => t.type === 'dip_white').map((t) => {
        const target = kit.shots.find((x) => x.id === t.to || x.segments[0].id === t.to);
        const spoken = firstSpoken(target);
        return {transition: t.id, first_spoken_frame: spoken.frame, basis: spoken.basis};
      });
      const eng = engineSchedules();
      const key = (rows) => JSON.stringify(rows.map((e) => [e.t, e.shot, e.white]));
      const dips = kit.transitions.filter((t) => t.type === 'dip_white');
      const matched = Object.fromEntries(dips.map((t) => [t.id, Object.keys(eng).find((name) => key(eng[name]) === key(t.schedule)) || null]));
      const mismatch = dips.filter((t) => !matched[t.id]).map((t) => t.id);
      const engine_schedule = {
        engine_presets: Object.fromEntries(Object.entries(eng).map(([name, rows]) => [name, {rows: rows.length, tail_frames: rows.filter((e) => e.shot === 'out_tail').length}])), matched, mismatch,
        label: mismatch.length ? 'engine-schedule mismatch (later design, BRIEF v009; not engine-verified): the build uses its own dip schedule, equal to neither engine preset (dip_white_legacy, dip_white)' : 'every dip schedule equals an engine preset (dip_white_legacy = the first build, dip_white = the approved 8-row design)',
      };
      out[v] = {build_receipt: kit.provenance.build_receipt, engine_schedule, issues, dip_peak_issues: issues.filter((i) => i.includes('dip_peak_before_first_word')).length, waived_in_adapter: waived, first_spoken: basis};
    } catch (error) {
      out[v] = {adapter_error: error.message.slice(0, 160)};
    }
  }
  process.stdout.write(`${JSON.stringify(out, null, 1)}\n`);
})();
