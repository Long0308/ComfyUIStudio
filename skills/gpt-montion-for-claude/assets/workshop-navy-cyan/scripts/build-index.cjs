'use strict';
// Package inventory and a local HTML contact sheet. It never modifies images.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {png:measurePng} = require('../animation/verify-assets.cjs');
const root = path.resolve(__dirname, '..');
const read = rel => JSON.parse(fs.readFileSync(path.join(root,rel),'utf8'));
const text = read('text-content.json');
const parts = read('assets/mechanical/parts.json');
const recipes = read('prompts/ASSET-RECIPES.json');
const required = new Set(text.assets.flatMap(a=>[a.png,a.svg]));
for(const a of parts.parts) { required.add(a.png); required.add(a.svg); }
for(const f of ['assets/brand/A02-engineers-branded.svg','assets/brand/A02-engineers-branded.png','assets/brand/company-logo-full-color.png','assets/brand/company-logo-full-white.png','assets/brand/company-logo-horizontal.png','assets/brand/company-n-symbol.png','assets/generated/A02-engineers-tablet.png','assets/mechanical/M07-fixture.svg','assets/mechanical/M07-fixture.png','assets/mechanical/assembly-complete.svg','assets/mechanical/assembly-complete.png']) required.add(f);
for(const a of recipes.recipes) { required.add(a.output); if(a.finalUse) required.add(a.finalUse); }
required.add(recipes.reference);
const missing = [...required].filter(f=>!fs.existsSync(path.join(root,f)));
if(missing.length) throw Error('BLOCKED: missing required assets: '+missing.join(', '));
const walk = dir => fs.readdirSync(path.join(root,dir),{withFileTypes:true}).flatMap(e => e.isDirectory()?walk(dir+'/'+e.name):[dir+'/'+e.name]);
const files = walk('assets').filter(f => /\.(png|svg)$/.test(f));
const resources = files.map(file => {
  const b = fs.readFileSync(path.join(root,file));
  const ext = path.extname(file).slice(1);
  const t = text.assets.find(a => a.png===file || a.svg===file);
  let dimensions = ext==='png'?measurePng(path.join(root,file)):null;
  if(ext==='svg') {
    const tag=b.toString('utf8').match(/<svg\b[^>]*>/)[0];
    dimensions={width:Number(tag.match(/\bwidth="([\d.]+)"/)[1]),height:Number(tag.match(/\bheight="([\d.]+)"/)[1])};
  }
  return {...dimensions,file,format:ext,bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex'),
    category:file.split('/')[1],...(t?{textId:t.id,exactText:t.text,fontStyle:t.fontStyle,animationGroup:t.groupId}:{}),
    coordinateOrigin:'top-left',pivot:[0.5,0.5],
    detail:ext==='svg'?(file.includes('A02-')?'Embedded source raster layers; not vectorized people/logo':'Native vector outlines'):'Raster; actual pixel dimensions shown'};
});
const minutes = s => {const [h,m]=s.split(':').map(Number);return h*60+m;};
const canon = read('references/workshop-content.json');
let previous = canon.event.start;
const agenda = [];
for(const section of canon.sections) {
  if(section.start!==previous || minutes(section.end)<=minutes(section.start)) throw Error('Noncontiguous parent agenda: '+section.id);
  let childEnd=section.start;
  for(const child of section.children) {
    if(!child.start && !child.end) continue;
    if(child.start!==childEnd || minutes(child.end)>minutes(section.end) || minutes(child.end)<=minutes(child.start)) throw Error('Invalid child agenda: '+child.id);
    childEnd=child.end;
  }
  if(section.children.some(c => c.end) && childEnd!==section.end) throw Error('Child schedule leaves a gap: '+section.id);
  agenda.push({id:section.id,start:section.start,end:section.end,durationMinutes:minutes(section.end)-minutes(section.start)});
  previous=section.end;
}
if(previous!==canon.event.end) throw Error('Agenda end mismatch');
const manifest={schemaVersion:1,generatedAt:new Date().toISOString(),root:'.',
  primaryPeopleAsset:'assets/brand/A02-engineers-branded.svg',
  editableTextManifest:'text-content.json',textAnimationManifest:'text-animation.json',
  layerContract:'Mechanical parts use their complete common viewBox; stack at the same origin. Do not trim PNGs independently.',
  timing:{masterFps:60,masterFrames:1200,proofFps:30,proofFrames:600},
  sourceLimits:['Imagegen reconstructions are not pixel-exact extraction.','Source photographs are below 4K; SVG text and native mechanical graphics are scalable.','Tiny PPE tagline is preserved as source artwork but is not reliably legible at video scale.'],
  assets:resources};
fs.writeFileSync(path.join(root,'asset-manifest.json'),JSON.stringify(manifest,null,2)+'\n');
fs.writeFileSync(path.join(root,'evidence/image-inventory.json'),JSON.stringify({generatedAt:new Date().toISOString(),method:'Read actual PNG scanlines through shared native PNG reader; source pixels never modified',assets:resources.filter(a=>a.format==='png')},null,2)+'\n');
fs.writeFileSync(path.join(root,'evidence/agenda-verification.json'),JSON.stringify({generatedAt:new Date().toISOString(),contiguous:true,eventDurationMinutes:minutes(canon.event.end)-minutes(canon.event.start),sections:agenda,part2Children:'No individual time slots specified in canonical; none invented.',scope:'Consistency of saved source; not organizer confirmation.'},null,2)+'\n');
const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const card = a => `<article><a href="${esc(a.file)}"><div class="art ${a.category==='brand'&&!a.file.includes('A02')?'brand':''}"><img src="${esc(a.file)}" alt="${esc(a.exactText||path.basename(a.file))}" loading="lazy"></div></a><div class="caption"><strong>${esc(a.textId||path.basename(a.file))}</strong><span>${a.width} × ${a.height} · ${a.format.toUpperCase()}</span>${a.exactText?`<p>${esc(a.exactText)}</p>`:''}<a href="${esc(a.file)}">Mở tệp</a></div></article>`;
const pictures=resources.filter(a=>a.format==='png'&&a.category!=='text'&&a.file!=='assets/generated/A02-engineers-tablet.png');
const letters=resources.filter(a=>a.format==='svg'&&a.category==='text');
const html=`<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Workshop AI · Asset kit</title><style>
*{box-sizing:border-box}body{margin:0;background:#fff;color:#0a2540;font:16px/1.55 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:40px 24px}header{border-bottom:1px solid #dce5ee;padding-bottom:24px;margin-bottom:24px}h1{font-size:clamp(30px,5vw,56px);margin:8px 0}p{max-width:90ch}nav{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}a{color:#0b4fd9}nav a{padding:10px 16px;background:#edf4ff;border:1px solid #c4d9f6;text-decoration:none;border-radius:5px}a:focus-visible{outline:3px solid #0b4fd9;outline-offset:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}article{border:1px solid #d9e1ea;border-radius:8px;overflow:hidden}.art{height:245px;background:#06233b;display:grid;place-items:center;padding:16px}.art.brand{background:linear-gradient(115deg,#f5f8fc 50%,#0b2945 50%)}.art img{max-width:100%;max-height:100%;object-fit:contain}.caption{padding:16px}.caption strong,.caption span{display:block;overflow-wrap:anywhere}.caption span{font-size:13px;color:#526a80}.caption p{font-size:14px}h2{margin-top:42px}.note{padding:16px;border-left:4px solid #0b4fd9;background:#f4f8ff}video{max-width:100%;max-height:75vh;background:#061829}code{overflow-wrap:anywhere}</style></head><body><main>
<header><p>NEWTECONS · KHỐI CƠ ĐIỆN · 14.11.2026</p><h1>Workshop AI — bộ ảnh và chuyển động</h1><p>Navy–Cyan, lắp ráp theo từng cụm: đến vị trí → căn chỉnh → khóa → kích hoạt. Ảnh, bộ phận cơ khí, logo và chữ có lớp riêng để tiếp tục dựng với Claude.</p><nav><a href="animation/index.html">Chạy bản ngang 16:9</a><a href="animation/portrait.html">Chạy bản dọc 9:16</a><a href="prompts/CLAUDE-MOTION-INTRO.md">Prompt bàn giao Claude</a><a href="README.md">Hướng dẫn</a><a href="asset-manifest.json">Manifest tệp</a></nav></header>
<video controls preload="metadata" poster="exports/frame-0000.png" src="exports/workshop-ai-intro-1080p.mp4">Mở video MP4 trong thư mục exports.</video>
<p class="note">Bản xem thử: 20 giây, 1920 × 1080, 30 fps. Bộ phận cơ khí là minh họa vector 2.5D. Ảnh người tái dựng từ mẫu, không phải cắt pixel tuyệt đối. Chữ và vector có thể xuất lại ở 4K; ảnh nguồn không được coi là native 4K.</p>
<h2>Ảnh và bộ phận riêng</h2><div class="grid">${pictures.map(card).join('')}</div>
<h2>${letters.length} lớp chữ — SVG nét và PNG nền trong suốt</h2><p>Hiệu ứng theo nguyên câu giữ toàn bộ dấu tiếng Việt. Các mục agenda bổ sung dành cho phần tiếp theo, không nhồi vào intro 20 giây.</p><div class="grid">${letters.map(card).join('')}</div>
<h2>Kiểm tra và nguồn</h2><nav><a href="evidence/independent-text-audit.md">Audit chữ độc lập</a><a href="evidence/agenda-verification.json">Thời gian cha/con</a><a href="references/REFERENCE-STATUS.md">Tiến độ thư mục tham khảo</a><a href="prompts/ASSET-RECIPES.json">Công thức ảnh</a></nav></main></body></html>`;
fs.writeFileSync(path.join(root,'index.html'),html);
console.log(JSON.stringify({assets:resources.length,pictureCards:pictures.length,textPairs:letters.length,agendaMinutes:150}));
