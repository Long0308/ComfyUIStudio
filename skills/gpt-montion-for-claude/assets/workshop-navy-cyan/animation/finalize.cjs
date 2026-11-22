const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'..'),out=path.join(root,'exports'),video=path.join(out,'workshop-ai-intro-1080p.mp4');
function run(binary,args){const r=spawnSync(binary,args,{encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error(`${binary} exit ${r.status}: ${r.stderr}`);return r.stdout;}
function probe(file){return JSON.parse(run('ffprobe',['-v','error','-show_streams','-show_format','-of','json',file]));}
const render=JSON.parse(fs.readFileSync(path.join(root,'evidence/motion-preview-render.json'),'utf8'));
if(render.mode!=='video'||render.resourceFailures.length||render.determinism.some(r=>!r.matchesFirst))throw Error('Final capture receipt is not valid');
const measurement=probe(video),stream=measurement.streams.find(s=>s.codec_type==='video');
if(stream.width!==1920||stream.height!==1080||stream.r_frame_rate!=='30/1'||Number(stream.nb_frames)!==600||Number(measurement.format.duration)!==20)throw Error('MP4 does not match the 1080p/30fps/600frame/20second contract');
run('ffmpeg',['-hide_banner','-loglevel','error','-xerror','-i',video,'-f','null','-']);
const clip=path.join(out,'mechanical-assembly-3s.mp4');
run('ffmpeg',['-hide_banner','-loglevel','error','-y','-ss','5','-i',video,'-t','3','-an','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',clip]);
fs.copyFileSync(path.join(out,'frame-0000.png'),path.join(out,'workshop-ai-intro-poster.png'));
fs.copyFileSync(path.join(out,'frame-0185.png'),path.join(out,'mechanical-assembly-poster.png'));
const receipt={status:'Encoded and full decoded successfully',video:'exports/workshop-ai-intro-1080p.mp4',sha256:crypto.createHash('sha256').update(fs.readFileSync(video)).digest('hex'),measurement,decodeExitCode:0,mechanicalClip:'exports/mechanical-assembly-3s.mp4',mechanicalClipMeasurement:probe(clip),audio:'No audio stream; silent preview',native4k:false,portrait:'Playable HTML and seven sampled 1080x1920 stills; no portrait MP4 claimed'};
fs.writeFileSync(path.join(root,'evidence/motion-preview-video.json'),JSON.stringify(receipt,null,2));
let removed=0;if(!process.argv.includes('--keep-frames')){for(let f=0;f<600;f++){const file=path.join(out,'frames',`${String(f).padStart(5,'0')}.png`);if(fs.existsSync(file)){fs.unlinkSync(file);removed++;}}}
console.log(JSON.stringify({video:receipt.video,width:stream.width,height:stream.height,fps:stream.r_frame_rate,frames:stream.nb_frames,duration:measurement.format.duration,size:measurement.format.size,decodeExitCode:0,removedFrameFiles:removed,sha256:receipt.sha256}));
