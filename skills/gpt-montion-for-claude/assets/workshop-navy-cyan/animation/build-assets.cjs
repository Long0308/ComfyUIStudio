const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const out = path.join(root,'assets/mechanical');
fs.mkdirSync(out,{recursive:true});
const p=(x,y,z)=>[250+x*.86-y*.66,420+x*.31+y*.37-z];
const pts=a=>a.map(v=>p(...v).join(',')).join(' ');
const poly=(a,fill,stroke='#70cbe2')=>`<polygon points="${pts(a)}" fill="${fill}" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round"/>`;
function box(x,y,z,w,d,h,c=['#3d667b','#183d54','#274f64']) {return poly([[x,y,z+h],[x+w,y,z+h],[x+w,y+d,z+h],[x,y+d,z+h]],c[0])+poly([[x,y,z],[x+w,y,z],[x+w,y,z+h],[x,y,z+h]],c[1])+poly([[x+w,y,z],[x+w,y+d,z],[x+w,y+d,z+h],[x+w,y,z+h]],c[2]);}
const line=(a,stroke='#45d9f5',width=2)=>`<polyline points="${pts(a)}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"/>`;
const bolt=(x,y,z)=>{const q=p(x,y,z);return `<circle cx="${q[0]}" cy="${q[1]}" r="4" fill="#0b263d" stroke="#b6dfe8" stroke-width="1.5"/>`;};
const parts={};
parts['M01-base']=box(-24,-24,-30,750,350,26)+[20,180,360,540,700].map(x=>line([[x,0,-3],[x,300,-3]],'#588598',1)).join('')+[[0,0],[700,0],[0,300],[700,300]].map(a=>bolt(...a,0)).join('');
parts['M02-frame']=[[0,0],[700,0],[0,300],[700,300]].map(a=>box(...a,0,16,16,380)).join('')+box(0,0,365,716,16,15)+box(0,300,365,716,16,15)+box(0,0,365,16,316,15)+box(700,0,365,16,316,15);
parts['M03-duct']=box(24,100,274,650,110,72,['#9cb8c5','#486e83','#6e93a6'])+[120,240,360,480,600].map(x=>line([[x,100,274],[x,100,346],[x,210,346]],'#d4e8ed',2)).join('')+poly([[24,100,280],[24,210,280],[24,210,340],[24,100,340]],'#0c263a','#b7d6e1');
parts['M04-pipes']=[{y:45,z:245,c:'#36d5f4'},{y:72,z:218,c:'#72adc7'}].map(({y,z,c})=>line([[35,y,30],[35,y,z-22],[60,y,z],[640,y,z],[670,y,z-22],[670,y,60]],'#082a40',22)+line([[35,y,30],[35,y,z-22],[60,y,z],[640,y,z],[670,y,z-22],[670,y,60]],c,15)+[100,230,360,490,610].map(x=>line([[x,y-3,z-8],[x,y-3,z+8]],'#c1e4ea',3)).join('')).join('');
parts['M05-tray']=box(50,240,178,610,50,10,['#7297a8','#1c4e68','#375f77'])+box(50,240,188,610,4,20)+box(50,286,188,610,4,20)+Array.from({length:15},(_,i)=>box(65+i*40,244,190,5,42,4)).join('')+line([[70,260,201],[635,260,201]],'#39daf2',3);
parts['M06-control-panel']=box(480,-14,45,168,30,175,['#7797a9','#173c54','#315b71'])+poly([[495,-14,110],[632,-14,110],[632,-14,203],[495,-14,203]],'#0a2237','#88b7ce')+line([[508,-15,135],[528,-15,148],[550,-15,144],[573,-15,174],[614,-15,185]],'#48def7',3)+[513,548,583,617].map((x,i)=>bolt(x,-15,77+i%2*8)).join('');
function svg(body,id){return `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="800" viewBox="0 0 1000 800" role="img"><title>${id} · editable isometric MEP illustration</title>${body}</svg>`;}
for(const [id,body]of Object.entries(parts))fs.writeFileSync(path.join(out,id+'.svg'),svg(body,id));
fs.writeFileSync(path.join(out,'assembly-complete.svg'),svg(Object.values(parts).join(''),'assembled MEP module'));
const fixture=`<g fill="#244c63" stroke="#7bc5dc" stroke-width="2"><path d="M18 630H115L108 680H25Z"/><path d="M47 640L71 640 133 355 108 350Z"/><path d="M108 355L128 370 248 191 228 180Z"/><circle cx="60" cy="640" r="25"/><circle cx="120" cy="360" r="22"/><circle cx="238" cy="186" r="15"/><path d="M228 173v-25h-17v35m37-10v-25h17v35" fill="none" stroke-width="7"/></g>`;
fs.writeFileSync(path.join(out,'M07-fixture.svg'),svg(fixture,'Reusable two-joint assembly fixture; left reference pose'));
const gen=path.join(root,'assets/generated');
fs.writeFileSync(path.join(gen,'A05-cyan-ribbon.svg'),`<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><title>Persistent cyan ribbon</title><path d="M-40 875 C380 660 790 1080 1180 858 S1690 810 1960 680" fill="none" stroke="#0c7096" stroke-width="16" opacity=".22"/><path d="M-40 875 C380 660 790 1080 1180 858 S1690 810 1960 680" fill="none" stroke="#30d7f3" stroke-width="3"/></svg>`);
let network='';for(let r=0;r<4;r++)for(let c=0;c<9;c++){let x=90+c*210,y=700+r*94+(c%2)*23;network+=`<path d="M${x} ${y}l210 ${c%2?-23:23}m-210 ${c%2?23:-23}l105 94" stroke="#1989b2" stroke-width="1" fill="none"/><circle cx="${x}" cy="${y}" r="3" fill="#40d9f4"/>`;}
fs.writeFileSync(path.join(gen,'A06-network-lines.svg'),`<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><title>Decorative network, no measured activity</title><g opacity=".38">${network}</g></svg>`);
fs.writeFileSync(path.join(out,'parts.json'),JSON.stringify({status:'Native editable 2.5D isometric vector illustration; not extracted Revit geometry',viewBox:[0,0,1000,800],layerOrder:Object.keys(parts),parts:Object.keys(parts).map((id,i)=>({id,svg:`assets/mechanical/${id}.svg`,png:`assets/mechanical/${id}.png`,arrivalSeconds:5+i*.23,offset:[[0,125],[-85,-130],[95,-210],[-180,-40],[180,-100],[170,70]][i]}))},null,2));
console.log('Wrote six native SVG parts, complete assembly, A05 and A06.');
