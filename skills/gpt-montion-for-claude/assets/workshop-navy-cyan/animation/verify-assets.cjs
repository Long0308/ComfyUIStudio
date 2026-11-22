const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'..');
function png(file){const b=fs.readFileSync(file);const w=b.readUInt32BE(16),h=b.readUInt32BE(20),depth=b[24],type=b[25];let pos=8,chunks=[];while(pos<b.length){const len=b.readUInt32BE(pos),tag=b.toString('ascii',pos+4,pos+8);if(tag==='IDAT')chunks.push(b.subarray(pos+8,pos+8+len));pos+=12+len;}
  const result={width:w,height:h,bitDepth:depth,colorType:type,sha256:crypto.createHash('sha256').update(b).digest('hex')};if(type!==6||depth!==8)return result;
  const raw=zlib.inflateSync(Buffer.concat(chunks)),stride=w*4,rows=Buffer.alloc(stride*h);let rp=0;
  const paeth=(a,b,c)=>{let p=a+b-c,pa=Math.abs(p-a),pb=Math.abs(p-b),pc=Math.abs(p-c);return pa<=pb&&pa<=pc?a:pb<=pc?b:c;};
  for(let y=0;y<h;y++){const filter=raw[rp++];for(let x=0;x<stride;x++){const a=x>=4?rows[y*stride+x-4]:0,u=y?rows[(y-1)*stride+x]:0,c=y&&x>=4?rows[(y-1)*stride+x-4]:0;const predict=[0,a,u,Math.floor((a+u)/2),paeth(a,u,c)][filter];rows[y*stride+x]=(raw[rp++]+predict)&255;}}
  let transparent=0,partial=0,opaque=0,x0=w,y0=h,x1=-1,y1=-1;for(let y=0;y<h;y++)for(let x=0;x<w;x++){const a=rows[y*stride+x*4+3];if(a===0)transparent++;else{if(a===255)opaque++;else partial++;x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);}}
  return {...result,alpha:{transparentPixels:transparent,partialPixels:partial,opaquePixels:opaque},contentBounds:{x:x0,y:y0,width:x1-x0+1,height:y1-y0+1},transparentCorners:[rows[3],rows[(w-1)*4+3],rows[(h-1)*stride+3],rows[h*stride-1]].every(a=>a===0)};
}
module.exports={png};
if(require.main===module){
const files=fs.readdirSync(path.join(root,'assets/mechanical')).filter(x=>x.endsWith('.png')).map(x=>'assets/mechanical/'+x).concat(['assets/generated/A05-cyan-ribbon.png','assets/generated/A06-network-lines.png','assets/brand/A02-engineers-branded.png']);
const assets=files.map(file=>({file,...png(path.join(root,file))}));
const report={verification:'Decoded actual Chrome PNG scanlines; native SVG illustrations rasterized without background',assets};
fs.writeFileSync(path.join(root,'evidence/motion-preview-assets.json'),JSON.stringify(report,null,2));
if(assets.some(a=>!a.alpha||a.alpha.transparentPixels===0))throw Error('Missing transparent pixels in required asset');
if(assets.filter(a=>a.file.startsWith('assets/mechanical/')).some(a=>a.contentBounds.x<2||a.contentBounds.y<2||a.contentBounds.x+a.contentBounds.width>a.width-2||a.contentBounds.y+a.contentBounds.height>a.height-2))throw Error('Mechanical artwork touches the raster canvas boundary');
console.log(JSON.stringify(assets.map(a=>({file:a.file,width:a.width,height:a.height,transparent:a.alpha.transparentPixels,bounds:a.contentBounds}))));
}
