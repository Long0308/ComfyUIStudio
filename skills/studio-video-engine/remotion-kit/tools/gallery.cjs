#!/usr/bin/env node
'use strict';
// Transition gallery: renders every ready transition preset on ONE real shot pair and writes an HTML index (light theme only).
//
//   node tools/gallery.cjs --config KIT-CONFIG.json --browser PATH --workdir SCRATCH --out GALLERY-DIR
//        --boundary ID [--avail ID,ID,...] [--only a,b] [--jobs 1|2] [--no-render] [--no-html]
//
// A transition is a compositing layer applied AFTER the shot videos exist: every demo row below replaces ONLY the chosen boundary
// row of a real, already built kit config. No shot video is rendered, requested or changed; a preset whose tail handle is too short
// is never faked, its card carries the exact reason and no clip. The demo rows are NOT deliverable boundaries (continuity is set to
// 'agree' so a both-shots-visible preset can be SHOWN), and each clip carries a DEMO label on screen.
//
// CPU only: render.cjs (Remotion + SwiftShader). render.cjs is called through its command line only.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn, spawnSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');

const KIT = path.resolve(__dirname, '..');
const CATALOG_FILE = path.join(KIT, '..', 'schemas', 'transition-presets.json');

// internal / alias presets that are not a visual choice of their own: `dissolve` = crossfade, `wipe` = wipe_linear, the others are
// graphic boundaries (ending iris, intro bloom, card slides, end plate) or story-specific effects
const EXCLUDED = {
  none: 'no effect at all (a carry between two pixel-continuous clips)',
  dissolve: 'the same renderer as crossfade',
  wipe: 'the same renderer as wipe_linear',
  cloud: 'story-specific effect (milk cloud), not a general transition',
  bubble: 'story-specific effect (milk bubble), not a general transition',
  iris: 'the ending iris to the logo disc, owned by the ending',
  bloom: 'the intro bloom, owned by the intro',
  card_slide: 'card to card slide inside the vocabulary cards',
  plate_in: 'end plate entrance',
};
const REQUIRES_NEW_ANGLE = new Set(['whip', 'dip_white', 'light']); // renders_as / category that need a changed camera angle or scene
const MAX_CLIP_FRAMES = 60;
const LEAD = 12;
const TRAIL = 12;

const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const option = (args, name) => {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : undefined;
};

async function loadLib() {
  const presets = await import(pathToFileURL(path.join(KIT, 'src', 'presets.mjs')).href);
  const feasibility = await import(pathToFileURL(path.join(KIT, 'src', 'feasibility.mjs')).href);
  return {presets, feasibility};
}

function loadCatalog(file = CATALOG_FILE) {
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^﻿/u, ''));
}

// the entries of the gallery: one per ready preset, push_slide in its four directions
function variantsFor(catalog) {
  const out = [];
  for (const [name, preset] of Object.entries(catalog.presets)) {
    if (preset.status !== 'ready') continue;
    if (EXCLUDED[name]) continue;
    if (name === 'push_slide') {
      for (const [suffix, axis, direction, vi, en] of [
        ['left', 'x', 1, 'đẩy sang trái', 'push left'], ['right', 'x', -1, 'đẩy sang phải', 'push right'],
        ['up', 'y', 1, 'đẩy lên', 'push up'], ['down', 'y', -1, 'đẩy xuống', 'push down'],
      ]) out.push({key: `push_slide_${suffix}`, preset: name, params: {axis}, direction, variant: {en, vi}});
      continue;
    }
    const direction = preset.direction === 'required' ? (name === 'pan_motivated' ? -1 : 1) : 0;
    out.push({key: name, preset: name, params: {}, direction, variant: null});
  }
  return out;
}

// poster frame of a schedule (dip family) preset: the 'in' row whose weight is nearest 0.62, so the poster shows the effect over the
// picture instead of a flat colour (the peak itself is a flat frame)
function posterOffset(schedule) {
  const rows = schedule.filter((e) => e.shot === 'in');
  return rows.reduce((best, e) => (Math.abs(e.white - 0.62) < Math.abs(best.white - 0.62) ? e : best), rows[0]).t;
}

const idxOf = (list, id) => list.findIndex((t) => t.id === id);

// The demo row for one variant on one boundary, or {skip, why}. `lib` = {presets, feasibility}.
function rowFor(catalog, variant, config, boundaryId, lib) {
  const {presets: P, feasibility: F} = lib;
  const preset = catalog.presets[variant.preset];
  const base = config.transitions[idxOf(config.transitions, boundaryId)];
  if (!base) throw new Error(`no boundary ${boundaryId} in the config`);
  const avail = F.presetAvailability(config, base, {mode: 'review', catalog}).presets[variant.preset];
  const wanted = F.defaultFrames(preset);
  const legal = F.candidateFrames(preset).filter((n) => n <= wanted);
  let frames = null;
  for (const n of legal.reverse()) {
    const t = {...base, frames: n};
    const fit = F.presetAvailability({...config, transitions: config.transitions.map((x) => (x === base ? {...t, preset: variant.preset, type: variant.preset} : x))}, boundaryId, {mode: 'review', catalog}).presets[variant.preset];
    if (fit.available) {
      frames = n;
      break;
    }
  }
  if (frames === null) return {skip: true, why: avail.whyNot || 'the bound tail handle is too short', avail};
  const params = P.resolveParams(preset, variant.params);
  const schedule = preset.schedule ? preset.schedule.map((r) => ({...r})) : undefined;
  const [start] = P.windowOf(preset, base.boundary, frames, params, schedule);
  const n = P.tailFrameCount(preset, frames, schedule);
  const row = {
    id: base.id, type: variant.preset, boundary: base.boundary, from: base.from, to: base.to, frames, direction: variant.direction, start,
    params, continuity: 'agree', shows_both: preset.shows_both, preset: variant.preset, renders_as: preset.renders_as,
  };
  if (preset.renders_as === 'whip') Object.assign(row, {outFrames: Math.floor(frames / 2), inFrames: Math.floor(frames / 2)});
  if (schedule) {
    row.schedule = schedule;
    if (preset.overlay) {
      row.overlay = {...preset.overlay};
      if (preset.overlay.kind === 'colour') row.whiteColour = preset.overlay.colour;
    }
    row.incomingHiddenFrames = schedule.filter((e) => e.t >= 0 && e.shot !== 'in').length;
  }
  if (n > 0) {
    if (!base.tail) return {skip: true, why: 'the boundary has no tail handle', avail};
    row.tail = {...base.tail, verifiedFrames: n};
  }
  const [wa, wb] = [start, P.windowOf(preset, base.boundary, frames, params, schedule)[1]];
  const from = Math.max(0, Math.min(wa, base.boundary) - LEAD);
  const to = Math.min(config.timeline.mainFrames + config.timeline.endCardFrames - 1, Math.max(wb, base.boundary) + TRAIL - 1, from + MAX_CLIP_FRAMES - 1);
  return {row, frames, clamped: frames < wanted ? wanted : null, range: [from, to], tailFrames: n, avail};
}

function configFor(config, row, label) {
  return {...config, review: {...(config.review || {}), label}, transitions: config.transitions.map((t) => (t.id === row.id ? row : t))};
}

// ---- HTML --------------------------------------------------------------------------------------------------------------------------
const esc = (s) => String(s).replace(/[&<>"']/gu, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

function paramSummary(preset) {
  const f = preset.frames;
  const frames = f.fixed !== undefined ? `cố định ${f.fixed} f` : `mặc định ${f.default} f (${f.min}–${f.max}${f.even ? ', chẵn' : ''})`;
  const params = Object.entries(preset.params || {}).map(([k, s]) => {
    const vi = s.label && s.label.vi ? ` · ${s.label.vi}` : '';
    if (s.type === 'enum') return `${k} ∈ {${s.values.join(', ')}}${s.default !== undefined ? `, mặc định ${s.default}` : ''}${vi}`;
    if (s.type === 'boolean') return `${k} = ${s.default}${vi}`;
    return `${k} = ${s.default} (${s.min}–${s.max})${vi}`;
  });
  return {frames, params};
}

const CSS = `
:root{--page:#F7FAFD;--card:#FFFFFF;--ink:#0A2540;--muted:#5C6795;--accent:#0B4FD9;--line:#D5DFEE;--ok:#3E8914;--bad:#D00000;--okbg:#EAF5E1;--badbg:#FBE8E8;--accbg:#E6EEFC}
*{box-sizing:border-box}
html{background:var(--page)}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:19px;margin:34px 0 4px}
.sub{color:var(--muted);margin:0 0 16px}
.banner{background:var(--accbg);border:1px solid var(--accent);border-radius:12px;padding:14px 16px;margin:16px 0}
.banner b{color:var(--accent)}
.bar{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;position:sticky;top:0;z-index:5}
.bar label{display:flex;gap:6px;align-items:center;color:var(--ink)}
select,input[type=search]{font:inherit;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:8px;padding:6px 8px}
.count{margin-left:auto;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}
.media{position:relative;background:#E9EFF8;aspect-ratio:16/9}
.media video,.media img{width:100%;height:100%;object-fit:cover;display:block}
.nomedia{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:14px;text-align:center;color:var(--muted);font-size:13px}
.body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:8px}
.name{font:600 16px "Cascadia Mono",Consolas,monospace;color:var(--ink)}
.names{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline}
.vi{font-weight:600}
.en{color:var(--muted)}
.when{font-size:13.5px}
.when i{display:block;color:var(--muted);font-style:normal}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border-radius:999px;padding:2px 10px;font-size:12.5px;border:1px solid var(--line);background:#fff;color:var(--muted)}
.chip.ok{background:var(--okbg);border-color:var(--ok);color:var(--ok)}
.chip.bad{background:var(--badbg);border-color:var(--bad);color:var(--bad)}
.chip.acc{background:var(--accbg);border-color:var(--accent);color:var(--accent)}
.gpu{display:flex;flex-direction:column;gap:4px}
.gpu .chip{border-radius:8px;width:100%}
details{font-size:12.5px;color:var(--muted)}
details summary{cursor:pointer}
.meta{font-size:12.5px;color:var(--muted)}
.hidden{display:none!important}
.foot{margin-top:40px;color:var(--muted);font-size:13px}
select,input[type=search]{max-width:100%}
@media (max-width:520px){.grid{grid-template-columns:1fr}.count{margin-left:0;width:100%}.bar label{width:100%;flex-wrap:wrap}.bar select,.bar input[type=search]{flex:1;min-width:0}}
`;

const JS = `
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var cat=document.getElementById('f-cat'),safe=document.getElementById('f-safe'),avail=document.getElementById('f-avail'),q=document.getElementById('f-q'),count=document.getElementById('count');
  function apply(){
    var n=0;
    cards.forEach(function(c){
      var ok=true;
      if(cat.value&&c.dataset.cat!==cat.value)ok=false;
      if(safe.checked&&c.dataset.safe!=='1')ok=false;
      if(avail.checked&&c.dataset.avail!=='1')ok=false;
      var s=q.value.trim().toLowerCase();
      if(s&&c.dataset.text.indexOf(s)<0)ok=false;
      c.classList.toggle('hidden',!ok);
      if(ok)n++;
    });
    [].forEach.call(document.querySelectorAll('section.cat'),function(sec){
      var any=sec.querySelector('.card:not(.hidden)');
      sec.classList.toggle('hidden',!any);
    });
    count.textContent=n+' / '+cards.length;
  }
  [cat,safe,avail,q].forEach(function(el){el.addEventListener('input',apply);});
  apply();
  var vids=[].slice.call(document.querySelectorAll('video[data-src]'));
  function play(v){if(!v.src){v.src=v.dataset.src;}var p=v.play();if(p&&p.catch)p.catch(function(){});}
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){play(e.target);}else{e.target.pause();}});},{threshold:0.25});
    vids.forEach(function(v){io.observe(v);});
  }else{vids.forEach(play);}
})();
`;

function badgeGpu(boundary, entry) {
  if (!entry) return `<span class="chip">${esc(boundary.id)}: chưa tính</span>`;
  const head = `${esc(boundary.id)} · ${esc(boundary.from)} → ${esc(boundary.to)}`;
  if (entry.available) {
    const need = entry.needsTailFrames ? ` (cần ${entry.needsTailFrames}, có ${entry.haveNativeFrames})` : '';
    return `<span class="chip ok" title="${esc(entry.reason || '')}">${head}: dùng ngay, không cần GPU${need}</span>`;
  }
  return `<span class="chip bad" title="${esc(entry.whyNot || '')}">${head}: cần thêm khung đuôi — phải chạy tails GPU</span>`;
}

function cardHtml(catalog, item, boundaries) {
  const preset = catalog.presets[item.preset];
  const sum = paramSummary(preset);
  const cat = catalog.categories.find((c) => c.id === preset.category) || {en: preset.category, vi: preset.category};
  const planned = preset.status !== 'ready';
  const safeOne = preset.shows_both === false;
  const safety = planned
    ? '<span class="chip">sắp có (chưa dựng)</span>'
    : safeOne ? '<span class="chip ok">an toàn 1 shot — mỗi khung chỉ một cảnh</span>'
      : '<span class="chip acc">cần continuity agree — hai cảnh cùng hiện</span>';
  const distortion = planned && ['glitch', 'ripple', 'grid_dissolve'].includes(item.preset)
    ? '<span class="chip bad">không dùng giữa hai ảnh (méo / nhiễu)</span>' : '';
  const angle = !planned && (REQUIRES_NEW_ANGLE.has(preset.renders_as) || REQUIRES_NEW_ANGLE.has(preset.category))
    ? '<span class="chip">chỉ khi đổi góc máy / cảnh; cùng ghế → cut_push</span>' : '';
  const avail = planned ? [] : boundaries.map((b) => badgeGpu(b.row, b.row.presets[item.preset]));
  const t1 = boundaries[boundaries.length - 1].row.presets[item.preset];
  const availHere = Boolean(item.media) ? '1' : '0';
  const variant = item.variant ? ` <span class="chip">${esc(item.variant.vi)} · ${esc(item.variant.en)}</span>` : '';
  let media;
  if (item.media) {
    media = `<video muted loop playsinline preload="none" poster="${esc(item.media.poster)}" data-src="${esc(item.media.clip)}"></video>`;
  } else if (item.skip && !planned) {
    media = `<div class="nomedia">Không dựng được trên ${esc(boundaries[boundaries.length - 1].row.id)}: ${esc(item.skip)}</div>`;
  } else {
    media = '<div class="nomedia">Chưa có renderer (dự kiến). Hiệu ứng méo / nhiễu: không dùng giữa hai ảnh.</div>';
  }
  const text = [item.key, item.preset, preset.label.en, preset.label.vi, cat.en, cat.vi].join(' ').toLowerCase();
  const clipInfo = item.media
    ? `<div class="meta">clip: ${item.media.frames} f hiệu ứng${item.media.clamped ? ` (rút từ ${item.media.clamped} f cho vừa tay cầm đuôi)` : ''}, khung ${item.media.range[0]}–${item.media.range[1]}${item.media.tailFrames ? `, đuôi ${item.media.tailFrames} f` : ''}</div>`
    : '';
  return `<article class="card" data-cat="${esc(preset.category)}" data-safe="${safeOne && !planned ? 1 : 0}" data-avail="${availHere}" data-text="${esc(text)}">
  <div class="media">${media}</div>
  <div class="body">
    <div class="names"><span class="name">${esc(item.key)}</span>${variant}</div>
    <div class="names"><span class="vi">${esc(preset.label.vi)}</span><span class="en">${esc(preset.label.en)}</span></div>
    <div class="chips"><span class="chip">${esc(cat.vi)} · ${esc(cat.en)}</span>${safety}${distortion}${angle}</div>
    <div class="when">${esc(preset.when.vi)}<i>${esc(preset.when.en)}</i></div>
    <div class="meta">${esc(sum.frames)}${sum.params.length ? `<br>${sum.params.map(esc).join('<br>')}` : ''}</div>
    ${clipInfo}
    <div class="gpu">${avail.join('')}</div>
    ${t1 && !t1.available && t1.whyNot ? `<details><summary>vì sao không dựng được</summary>${esc(t1.whyNot)}</details>` : ''}
  </div>
</article>`;
}

function buildHtml(catalog, items, boundaries, meta) {
  const order = catalog.categories.map((c) => c.id);
  const sections = order.map((cid) => {
    const list = items.filter((it) => catalog.presets[it.preset].category === cid);
    if (!list.length) return '';
    const cat = catalog.categories.find((c) => c.id === cid);
    return `<section class="cat" data-cat="${esc(cid)}"><h2>${esc(cat.vi)} <span class="en">· ${esc(cat.en)}</span></h2><div class="grid">${list.map((it) => cardHtml(catalog, it, boundaries)).join('\n')}</div></section>`;
  }).join('\n');
  const catOptions = order.filter((cid) => items.some((it) => catalog.presets[it.preset].category === cid))
    .map((cid) => { const c = catalog.categories.find((x) => x.id === cid); return `<option value="${esc(cid)}">${esc(c.vi)} · ${esc(c.en)}</option>`; }).join('');
  const tableJson = JSON.stringify(Object.fromEntries(boundaries.map((b) => [b.row.id, b.row]))).replace(/</gu, '\\u003c');
  return `<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Thư viện chuyển cảnh</title>
<style>${CSS}</style>
</head>
<body>
<div class="wrap">
<h1>Thư viện chuyển cảnh</h1>
<p class="sub">${esc(meta.episodeId)} · cặp demo ${esc(meta.pair)} · ${items.filter((i) => i.media).length} hiệu ứng đã dựng, ${items.length} mục</p>
<div class="banner"><b>Nguyên tắc:</b> hiệu ứng chuyển cảnh là <b>lớp ghép (composite)</b> áp dụng <b>sau khi</b> video các shot đã có. Đổi hiệu ứng <b>không bao giờ</b> render lại video shot (H3 / SeedVR2): chỉ sửa một trường trong <code>boundaries.json</code>, rồi dựng lại cấu hình và render lớp ghép. Hiệu ứng cần phát khung đuôi của shot ra chỉ dùng được khi tay cầm đuôi đã có sẵn; nếu thiếu, engine từ chối và nói rõ thiếu bao nhiêu khung, không tự xin GPU.<br>Các clip dưới đây là <b>DEMO</b> trên một cặp thật (${esc(meta.pair)}), đặt continuity = agree để xem được cả hiệu ứng hiện hai cảnh; không phải ranh giới giao hàng.</div>
<div class="bar">
<label>Nhóm <select id="f-cat"><option value="">Tất cả</option>${catOptions}</select></label>
<label><input type="checkbox" id="f-safe"> chỉ an toàn 1 shot</label>
<label><input type="checkbox" id="f-avail"> chỉ dùng được ở ${esc(meta.demoBoundary)} (không cần GPU)</label>
<label><input type="search" id="f-q" placeholder="tìm theo tên"></label>
<span class="count" id="count"></span>
</div>
${sections}
<p class="foot">Bảng khả thi theo từng ranh giới: ${boundaries.map((b) => `<a href="availability-${esc(b.row.id)}.json">availability-${esc(b.row.id)}.json</a>`).join(' · ')} · bản ghi dựng: <a href="gallery-record.json">gallery-record.json</a>. Quy tắc tay cầm: cần ceil(4N/5) khung gốc ngoài phần dựng chính và khung gốc cuối nằm trong file; không bao giờ xin thêm GPU.</p>
</div>
<script type="application/json" id="availability">${tableJson}</script>
<script>${JS}</script>
</body>
</html>
`;
}

// ---- orchestration -----------------------------------------------------------------------------------------------------------------
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, ...opts});
  if (r.status !== 0) throw new Error(`${cmd} ${args.slice(0, 4).join(' ')} failed (${r.status}): ${(r.stderr || r.stdout || '').slice(-1500)}`);
  return r;
}

function renderOne(job) {
  return new Promise((resolve) => {
    const started = Date.now();
    const args = [path.join(KIT, 'render.cjs'), '--config', job.configFile, '--mode', 'review', '--range', `${job.range[0]}-${job.range[1]}`,
      '--out', job.src, '--stage-needed', '--browser', job.browser, '--concurrency', '1'];
    const child = spawn(process.execPath, args, {stdio: ['ignore', 'pipe', 'pipe']});
    let log = '';
    child.stdout.on('data', (d) => { log += d; });
    child.stderr.on('data', (d) => { log += d; });
    child.on('close', (code) => {
      fs.writeFileSync(`${job.src}.log`, log);
      resolve({code, seconds: (Date.now() - started) / 1000, command: `node render.cjs ${args.slice(1).join(' ')}`, log});
    });
  });
}

function encode(job, outDir) {
  const clip = path.join(outDir, 'clips', `${job.key}.mp4`);
  const poster = path.join(outDir, 'posters', `${job.key}.png`);
  fs.mkdirSync(path.dirname(clip), {recursive: true});
  fs.mkdirSync(path.dirname(poster), {recursive: true});
  run('ffmpeg', ['-y', '-v', 'error', '-i', job.src, '-an', '-vf', 'scale=1280:-2:flags=lanczos', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '26', '-preset', 'medium',
    '-movflags', '+faststart', clip]);
  const mid = Math.max(0, job.boundary - job.range[0] + (job.peak !== undefined ? job.peak : Math.floor(job.frames / 2))); // the poster shows the peak of a dip, else mid-transition
  run('ffmpeg', ['-y', '-v', 'error', '-i', clip, '-vf', `trim=start_frame=${mid}:end_frame=${mid + 1},scale=640:-2:flags=lanczos`, '-frames:v', '1', poster]);
  return {clip: `clips/${job.key}.mp4`, poster: `posters/${job.key}.png`, clipFile: clip, posterFile: poster};
}

async function pool(jobs, size, fn) {
  const results = new Array(jobs.length);
  let next = 0;
  await Promise.all(Array.from({length: Math.min(size, jobs.length)}, async () => {
    while (next < jobs.length) {
      const i = next;
      next += 1;
      results[i] = await fn(jobs[i], i);
    }
  }));
  return results;
}

async function main() {
  const args = process.argv.slice(2);
  const configFile = path.resolve(option(args, '--config') || '');
  if (!option(args, '--config') || !fs.existsSync(configFile)) throw new Error('--config <kit-config.json> is required');
  const browser = option(args, '--browser') || process.env.REMOTION_BROWSER;
  const workdir = path.resolve(option(args, '--workdir') || '');
  const outDir = path.resolve(option(args, '--out') || '');
  if (!option(args, '--workdir') || !option(args, '--out')) throw new Error('--workdir and --out are required');
  const boundaryId = option(args, '--boundary');
  if (!boundaryId) throw new Error('--boundary <transition id> is required (the boundary whose handle the demo renders use; pick the one with the longest tail handle)');
  const availIds = (option(args, '--avail') || boundaryId).split(',');
  const jobsN = Number(option(args, '--jobs') || 1);
  if (![1, 2].includes(jobsN)) throw new Error('--jobs must be 1 or 2');
  const only = option(args, '--only') ? new Set(option(args, '--only').split(',')) : null;
  const noRender = args.includes('--no-render');
  if (!noRender && !browser) throw new Error('--browser PATH (or REMOTION_BROWSER) is required for rendering');
  fs.mkdirSync(workdir, {recursive: true});
  fs.mkdirSync(outDir, {recursive: true});

  const lib = await loadLib();
  const catalog = loadCatalog();
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^﻿/u, ''));

  // availability tables through the render CLI (no bundling, no browser)
  const boundaries = [];
  for (const id of availIds) {
    const r = run(process.execPath, [path.join(KIT, 'render.cjs'), '--config', configFile, '--mode', 'review', '--list-presets', '--boundary', id]);
    const parsed = JSON.parse(r.stdout);
    const row = parsed.boundaries[0];
    fs.writeFileSync(path.join(outDir, `availability-${id}.json`), `${JSON.stringify(parsed, null, 2)}\n`);
    boundaries.push({row});
  }
  const demo = boundaries.find((b) => b.row.id === boundaryId);
  if (!demo) throw new Error(`--avail must include ${boundaryId}`);
  // the demo boundary is listed last (its row drives the "available here" filter)
  boundaries.sort((a, b) => (a.row.id === boundaryId) - (b.row.id === boundaryId) || a.row.boundary - b.row.boundary);

  const all = variantsFor(catalog);
  const picked = all.filter((v) => !only || only.has(v.key));
  const items = [];
  const jobs = [];
  for (const v of picked) {
    const built = rowFor(catalog, v, config, boundaryId, lib);
    const item = {key: v.key, preset: v.preset, variant: v.variant};
    if (built.skip) {
      item.skip = built.why;
    } else {
      const cfgFile = path.join(workdir, 'configs', `${v.key}.json`);
      fs.mkdirSync(path.dirname(cfgFile), {recursive: true});
      fs.writeFileSync(cfgFile, `${JSON.stringify(configFor(config, built.row, `DEMO ${boundaryId} · ${v.key}`), null, 2)}\n`);
      jobs.push({key: v.key, built, configFile: cfgFile, range: built.range, src: path.join(workdir, 'src', `${v.key}.mp4`), browser, boundary: built.row.boundary, frames: built.frames, peak: built.row.schedule ? posterOffset(built.row.schedule) : undefined, item});
      item.pending = true;
    }
    items.push(item);
  }
  for (const [name, preset] of Object.entries(catalog.presets)) {
    if (preset.status === 'planned' && !only) items.push({key: name, preset: name, variant: null, skip: 'planned: no renderer yet'});
  }

  const record = {
    tool: 'remotion-kit/tools/gallery.cjs', base_config: configFile, base_config_sha256: sha256(configFile), boundary: boundaryId, catalog_sha256: sha256(CATALOG_FILE),
    note: 'composite-only: every demo row replaces only the boundary row of a built config; no shot video was rendered or requested',
    excluded: EXCLUDED, presets: {},
  };
  if (!noRender) {
    fs.mkdirSync(path.join(workdir, 'src'), {recursive: true});
    await pool(jobs, jobsN, async (job) => {
      if (fs.existsSync(job.src) && args.includes('--reuse')) return;
      const r = await renderOne(job);
      job.render = r;
      process.stderr.write(`${job.key}: render exit ${r.code} in ${r.seconds.toFixed(0)}s\n`);
    });
  }
  const cpuStart = Date.now();
  for (const job of jobs) {
    const entry = {frames: job.frames, clamped_from: job.built.clamped, range: job.range, config: job.configFile, config_sha256: sha256(job.configFile), availability: job.built.avail, command: job.render ? job.render.command : null, render_seconds: job.render ? job.render.seconds : null};
    if (fs.existsSync(job.src)) {
      const enc = encode(job, outDir);
      job.item.media = {clip: enc.clip, poster: enc.poster, frames: job.frames, clamped: job.built.clamped, range: job.range, tailFrames: job.built.tailFrames};
      Object.assign(entry, {source_mp4_sha256: sha256(job.src), clip: enc.clip, clip_sha256: sha256(enc.clipFile), poster: enc.poster, poster_sha256: sha256(enc.posterFile)});
    } else {
      job.item.skip = `render did not produce a clip${job.render && job.render.code ? ` (exit ${job.render.code})` : ' (not rendered in this run)'}`;
      entry.error = job.item.skip;
    }
    delete job.item.pending;
    record.presets[job.key] = entry;
  }
  for (const item of items) {
    if (item.skip && !record.presets[item.key]) record.presets[item.key] = {skipped: item.skip};
    else if (item.skip) record.presets[item.key].skipped = item.skip;
  }
  record.encode_seconds = (Date.now() - cpuStart) / 1000;
  fs.writeFileSync(path.join(outDir, 'gallery-record.json'), `${JSON.stringify(record, null, 2)}\n`);
  if (!args.includes('--no-html')) {
    const meta = {episodeId: config.id, pair: `${demo.row.from} → ${demo.row.to} (${demo.row.id})`, demoBoundary: demo.row.id};
    fs.writeFileSync(path.join(outDir, 'index.html'), buildHtml(catalog, items, boundaries, meta));
  }
  process.stdout.write(`gallery done: ${items.filter((i) => i.media).length} clips, ${items.filter((i) => i.skip).length} skipped, in ${outDir}\n`);
}

module.exports = {variantsFor, rowFor, configFor, buildHtml, loadLib, loadCatalog, EXCLUDED, CATALOG_FILE};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`gallery failed: ${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}
