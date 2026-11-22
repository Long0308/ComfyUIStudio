const fs=require('node:fs');const path=require('node:path');const root=path.resolve(__dirname,'..');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'text-content.json'),'utf8'));
const texts=Object.fromEntries(manifest.assets.map(a=>[a.id,{...a,markup:fs.readFileSync(path.join(root,a.svg),'utf8').replace(/<\?xml[^>]*>/,'')} ]));
const parts=JSON.parse(fs.readFileSync(path.join(root,'assets/mechanical/parts.json'),'utf8'));
for(const a of parts.parts)a.markup=fs.readFileSync(path.join(root,a.svg),'utf8');
fs.writeFileSync(path.join(__dirname,'content.js'),'window.WORKSHOP_CONTENT='+JSON.stringify({texts,parts})+';');
console.log('Bundled SVG outlines and native mechanical layers.');
