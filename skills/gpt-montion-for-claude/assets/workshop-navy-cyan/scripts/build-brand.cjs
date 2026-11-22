/* Native layered artwork: supplied PNG bytes are embedded unchanged. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const asset = rel => fs.readFileSync(path.join(root, rel));
const data = rel => 'data:image/png;base64,' + asset(rel).toString('base64');
const hash = rel => crypto.createHash('sha256').update(asset(rel)).digest('hex');
const plate = 'assets/generated/A02-engineers-tablet.png';
const color = 'assets/brand/company-logo-full-color.png';
const white = 'assets/brand/company-logo-full-white.png';
const placements = [
  { id:'male-helmet', source:color, x:549, y:148, width:150, rotation:12 },
  { id:'female-helmet', source:color, x:875, y:252, width:145, rotation:8 },
  { id:'male-vest', source:white, x:548, y:652, width:120, rotation:8 },
  { id:'female-vest', source:white, x:994, y:725, width:135, rotation:-4 }
].map(p => ({...p, height:p.width * 633 / 1134}));
const layers = placements.map(p => `<image id="${p.id}" href="${data(p.source)}" x="${p.x}" y="${p.y}" width="${p.width}" height="${p.height}" preserveAspectRatio="xMidYMid meet" transform="rotate(${p.rotation} ${p.x + p.width/2} ${p.y + p.height/2})"/>`).join('\n');
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1332" height="1181" viewBox="0 0 1332 1181" role="img" aria-labelledby="brand-title">
<title id="brand-title">Newtecons engineers: clean reconstructed working plate with original logo artwork overlays</title>
<desc>Source raster artwork embedded unchanged. This SVG is a layered composition, not a vector conversion of the people or official logo. Tiny PPE tagline legibility depends on output scale.</desc>
<image id="engineers-base" href="${data(plate)}" width="1332" height="1181"/>
${layers}
</svg>\n`;
fs.writeFileSync(path.join(root,'assets/brand/A02-engineers-branded.svg'),svg);
fs.writeFileSync(path.join(root,'assets/brand/brand-placement.json'),JSON.stringify({
  schemaVersion:1,
  department:{header:'KHỐI CƠ ĐIỆN',replaceHeaderOnly:true,wardrobeDepartment:null},
  companyArtwork:'Fixed source PNG artwork; keep N, NEWTECONS, registered mark, rule and Build on trust intact.',
  canvas:{width:1332,height:1181},
  sources:[plate,color,white].map(file => ({file,sha256:hash(file)})),
  placements,
  limits:['Native layered SVG with original raster logo bytes; not an official vector master.','PPE logo is small at final video scale; source fidelity and microtext readability are separate checks.','No new department label is stamped onto wardrobe.'],
  producedBy:'node scripts/build-brand.cjs'
},null,2)+'\n');
console.log('Created self-contained A02-engineers-branded.svg and brand-placement.json');
