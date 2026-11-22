/* No render state is accumulated: pixels depend only on integer frame and aspect. */
(() => {
  'use strict';
  const C=window.WORKSHOP_CONTENT, portrait=document.body.dataset.aspect==='portrait';
  const W=portrait?1080:1920,H=portrait?1920:1080,FPS=30,END=600;
  const clamp=(v,a=0,b=1)=>Math.min(b,Math.max(a,v));
  const ease=v=>1-Math.pow(1-clamp(v),3);
  const smooth=v=>{v=clamp(v);return v*v*(3-2*v);};
  const img=(src,x,y,w,h,extra='')=>`<image href="../${src}" x="${x}" y="${y}" width="${w}" height="${h}" preserveAspectRatio="xMidYMid meet" ${extra}/>`;
  const inner=markup=>markup.replace(/^.*?<svg[^>]*>/s,'').replace(/<\/svg>\s*$/,'');
  const group=(body,opacity=1,transform='')=>`<g opacity="${clamp(opacity)}" transform="${transform}">${body}</g>`;
  const text=(id,x,y,w,t,entry=0,ready=false)=>{
    const windows={T01_WORKSHOP:[[0,2],[16,20]],T02_AI:[[0,2],[16,20]],T04_FIELD_APPLICATION:[[2,8]],T33_DASHBOARD_HOOK:[[8,11]],T34_AI_BIM_HOOK:[[11,13]],T05_RESPONSIBLE_AI:[[13,16]],T06_DATE:[[16,20]],T07_LOCATION:[[16,20]],T08_TIME:[[16,20]]};
    if(windows[id]&&!windows[id].some(([a,b])=>t>=a&&t<b))return '';
    const a=C.texts[id];if(!a)throw Error(`Missing text-content asset ${id}`);
    const h=w*a.height/a.width,p=ready?1:ease((t-entry)/.4);
    return `<svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="0 0 ${a.width} ${a.height}" overflow="hidden" aria-label="${a.text}"><g opacity="${p}" transform="translate(0 ${(1-p)*a.height*.34})">${inner(a.markup)}</g></svg>`;
  };
  function header(t){const x=portrait?56:80,y=portrait?45:40;return `<rect x="${x}" y="${y}" width="380" height="148" rx="4" fill="#fff"/>`+img('assets/brand/company-logo-horizontal.png',x+20,y+20,340,108)+text('T03_DEPARTMENT',portrait?610:1440,portrait?80:65,portrait?380:370,t,0,true);}
  function title(t,y=240,ready=true){return text('T01_WORKSHOP',portrait?90:100,y,portrait?900:1320,t,ready?0:16,ready)+text('T02_AI',portrait?600:1450,portrait?y+145:y-20,portrait?370:300,t,ready?0:16.06,ready);}
  function hero(t){return img('references/navy-cyan-canvas-source.png',portrait?-390:0,portrait?780:410,portrait?1900:1920,portrait?634:640)+title(t,portrait?350:235);}
  function engineer(t){let p=ease((t-2)/.7);return img('assets/brand/A02-engineers-branded.svg',portrait?70:970,portrait?650:345,portrait?940:800,portrait?834:710,`transform="translate(${(1-p)*(portrait?0:80)} ${(1-p)*35})" opacity="${p}"`);}
  function fixture(t,right=false){const entry=right?5.9:5.42,retract=right?6.65:6.18,visible=smooth((t-entry+.2)/.2)*(1-smooth((t-retract)/.38));if(visible<=0)return '';const progress=smooth((t-entry)/.22)*(1-smooth((t-retract)/.38)),part=ease((t-(right?5.92:5.46))/.6),bx=right?980:20,by=650,ex=right?900:105,ey=right?440:370,tx=(right?650:220)+(right?180:95)*(1-part),ty=(right?430:180)-(right?100:210)*(1-part),wx=bx+(tx-bx)*progress,wy=by-45+(ty-by+45)*progress,clampGap=10-6*smooth((t-entry-.16)/.15)*(1-smooth((t-retract)/.15));
    return `<g opacity="${visible}" stroke-linejoin="round"><path d="M${bx-40} 662h80l-8 44h-64Z" fill="#153c54" stroke="#7cc5d9" stroke-width="2"/><path d="M${bx} ${by}L${ex} ${ey}L${wx} ${wy}" fill="none" stroke="#0a2439" stroke-width="34"/><path d="M${bx} ${by}L${ex} ${ey}L${wx} ${wy}" fill="none" stroke="#396d86" stroke-width="23"/><path d="M${bx-4} ${by}L${ex-4} ${ey}L${wx-4} ${wy}" fill="none" stroke="#8abacb" stroke-width="3"/>${[[bx,by,25],[ex,ey,22],[wx,wy,14]].map(([cx,cy,r])=>`<circle cx="${cx}" cy="${cy}" r="${r}" fill="#153b53" stroke="#87c4d7" stroke-width="3"/><circle cx="${cx}" cy="${cy}" r="5" fill="#42d1ea"/>`).join('')}<path d="M${wx-clampGap} ${wy-3}v-24h-12v15m${clampGap*2+12} 9v-24h12v15" fill="none" stroke="#a5d2dd" stroke-width="6"/></g>`;
  }
  function mechanical(t,x,y,w,complete=false){const body=C.parts.parts.map((a,i)=>{const p=complete?1:ease((t-(5+i*.23))/.6);const micro=complete?0:Math.sin(clamp((t-5-i*.23-.5)/.17)*Math.PI)*3;return group(inner(a.markup),p,`translate(${a.offset[0]*(1-p)} ${a.offset[1]*(1-p)+micro})`);}).join('');let locks='';for(let i=0;i<4;i++){const p=complete?1:smooth((t-6.65-i*.07)/.16),lx=95+i*235,ly=671;locks+=`<g transform="translate(${lx} ${ly})"><rect x="-12" y="${-10-14*(1-p)}" width="32" height="13" rx="2" fill="#557f93" stroke="#a0c6d5" stroke-width="1.5"/><path d="M-8 -3h22" stroke="#71e0f2" stroke-width="2" opacity="${p}"/><circle cx="3" cy="-3" r="2" fill="#dbfaff"/></g>`;}const activate=complete?0:Math.sin(clamp((t-7.1)/.65)*Math.PI);return `<svg x="${x}" y="${y}" width="${w}" height="${w*.8}" viewBox="0 0 1000 800" overflow="hidden">${complete?'':fixture(t)+fixture(t,true)}${body}${locks}<path d="M90 728H890" stroke="#3bddf5" stroke-width="${1+activate*2}" opacity="${.15+activate*.45}"/><path d="M694 468v-52h-78" stroke="#6ce5f5" fill="none" stroke-width="3" pathLength="1" stroke-dasharray="1" stroke-dashoffset="${1-clamp((t-7.1)/.45)}" opacity="${complete?0:activate}"/></svg>`;}
  function fieldTitle(t){return text('T04_FIELD_APPLICATION',portrait?65:110,portrait?385:210,portrait?950:1540,t,2);}
  function scene2(t){return engineer(t)+fieldTitle(t);}
  function scene3(t){return mechanical(t,portrait?0:520,portrait?640:350,portrait?1080:860)+fieldTitle(t);}
  function dashboard(t){const p=ease((t-8)/.6);return text('T33_DASHBOARD_HOOK',portrait?70:110,portrait?360:210,portrait?940:1450,t,8)+img('assets/generated/A04-dashboard-panels.png',portrait?25:370,portrait?620:290,portrait?1030:1200,portrait?755:880,`transform="translate(${(1-p)*80} ${(1-p)*35})" opacity="${p}"`);}
  function connection(t){const p=ease((t-11)/.4);const a=portrait?[35,820,490,435]:[170,350,620,550],b=portrait?[475,800,610]:[1000,310,760];const y=portrait?1320:850;return text('T34_AI_BIM_HOOK',portrait?160:110,portrait?360:210,portrait?760:760,t,11)+img('assets/brand/A02-engineers-branded.svg',...a)+mechanical(t,...b,true)+`<path d="M${portrait?260:600} ${y}C${portrait?400:780} ${y+70} ${portrait?600:950} ${y+70} ${portrait?820:1200} ${y}" fill="none" stroke="#36cce9" stroke-width="3" pathLength="1" stroke-dasharray="1" stroke-dashoffset="${1-p}"/><circle cx="${(portrait?260:600)+(portrait?560:600)*p}" cy="${y+Math.sin(p*Math.PI)*45}" r="5" fill="#b7f1fa" opacity="${Math.sin(p*Math.PI)}"/>`;}
  function responsible(t){return group(mechanical(t,portrait?40:650,portrait?1070:390,portrait?1000:1000,true),.16)+text('T05_RESPONSIBLE_AI',portrait?70:150,portrait?650:430,portrait?940:1620,t,13);}
  function ending(t){let entry=16;return title(t,portrait?440:285,false)+text('T06_DATE',portrait?100:110,portrait?1090:760,portrait?410:380,t,entry)+text('T07_LOCATION',portrait?100:600,portrait?1230:760,portrait?760:580,t,entry+.05)+text('T08_TIME',portrait?100:1310,portrait?1385:760,portrait?580:460,t,entry+.1);}
  const scenes=[{a:0,b:2,fn:hero},{a:2,b:5,fn:scene2},{a:5,b:8,fn:scene3},{a:8,b:11,fn:dashboard},{a:11,b:13,fn:connection},{a:13,b:16,fn:responsible},{a:16,b:20,fn:ending}];
  window.renderFrame=function(frame){frame=clamp(Math.round(frame),0,END-1);const t=frame/FPS;
    let body='';for(let i=0;i<scenes.length;i++){const s=scenes[i];if(t<s.a||t>=s.b+.2)continue;const alpha=t<s.b?1:1-smooth((t-s.b)/.2);body+=group(s.fn(t),alpha);}
    const ribbonY=portrait?650:0;
    document.getElementById('stage').innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs><radialGradient id="bg"><stop stop-color="#123c58"/><stop offset="1" stop-color="#04172c"/></radialGradient><linearGradient id="veil" x2="0" y2="1"><stop stop-color="#061c32" stop-opacity=".93"/><stop offset="1" stop-color="#061c32" stop-opacity=".6"/></linearGradient></defs><rect width="${W}" height="${H}" fill="url(#bg)"/>${img('assets/generated/A01-site-background.png',0,portrait?780:290,W,portrait?1100:790,'opacity=".12"')}<rect width="${W}" height="${H}" fill="url(#veil)"/><g opacity=".32" transform="translate(${Math.sin(t*.3)*10} ${ribbonY})">${img('assets/generated/A06-network-lines.svg',0,0,W,portrait?1080:H)}</g><g transform="translate(${Math.sin(t*.5)*16} ${ribbonY})">${img('assets/generated/A05-cyan-ribbon.svg',0,0,W,portrait?1080:H)}</g>${body}${header(t)}<path d="M${portrait?80:110} ${H-85}H${W-(portrait?80:110)}" stroke="#3b9cba" stroke-width="1" opacity=".3"/></svg>`;
    document.getElementById('seek').value=frame;document.getElementById('time').value=`${t.toFixed(2)} / 20s`;window.currentFrame=frame;return {frame,time:t,width:W,height:H,scene:scenes.findIndex(s=>t>=s.a&&t<s.b)+1};
  };
  // Wall-clock playback selects frames only. Rendering never reads this clock.
  let playing=false,origin=0,originFrame=0,rafId=0;
  function stop(){playing=false;cancelAnimationFrame(rafId);rafId=0;document.getElementById('play').textContent='Play';}
  function playback(now){rafId=0;if(!playing)return;const f=originFrame+Math.floor((now-origin)*FPS/1000);window.renderFrame(f);if(f>=END-1){stop();return;}rafId=requestAnimationFrame(playback);}
  document.getElementById('play').onclick=()=>{if(playing){stop();return;}cancelAnimationFrame(rafId);playing=true;document.getElementById('play').textContent='Pause';origin=performance.now();originFrame=window.currentFrame;rafId=requestAnimationFrame(playback);};
  document.getElementById('restart').onclick=()=>{stop();window.renderFrame(0);};
  document.getElementById('seek').oninput=e=>{stop();window.renderFrame(Number(e.target.value));};
  if(new URLSearchParams(location.search).has('capture'))document.body.classList.add('capture');
  window.renderFrame(Number(new URLSearchParams(location.search).get('frame'))||0);
  window.workshopMeta={fps:FPS,frames:END,width:W,height:H,source:'Native SVG mechanical illustration; static source photographs; decorative data; silent preview'};
})();
