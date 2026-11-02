"""Production word timing for approved clips whose earlier receipt has QA failures."""
import json
from pathlib import Path
from faster_whisper import WhisperModel
from review_sources import ROOT, HERE, sha

if __name__=='__main__':
    model_path=Path('J:/2.Model-AI-Local/VoiceStudio/hf_cache/models--Systran--faster-whisper-large-v3/snapshots/edaa852ec7e145841d8ffdb056a99866b5f0a478')
    print('Loading local large-v3 CPU int8; threads8',flush=True)
    model=WhisperModel(str(model_path),device='cpu',compute_type='int8',cpu_threads=8,num_workers=1,local_files_only=True)
    print('Model loaded',flush=True)
    picks=json.loads((HERE/'picks.json').read_text(encoding='utf-8'))
    out=HERE/'refined-timing';out.mkdir(exist_ok=True)
    for slot in picks['slots']:
        if slot['shot'] not in ['S02_A','S03_A','S04_A']:continue
        path=ROOT/slot['audio_path']; digest=sha(path);dest=out/(slot['shot']+'-'+digest[:12]+'.json')
        if dest.exists():continue
        print('Transcribing',slot['shot'],flush=True)
        segments,info=model.transcribe(str(path),language='vi',beam_size=5,word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
        transcript=[];words=[]
        for seg in segments:
            transcript.append(seg.text)
            for w in seg.words or []:words.append(dict(word=w.word,start=w.start,end=w.end,probability=w.probability))
        result=dict(shot=slot['shot'],sha256=digest,source=str(path),model=str(model_path),device='cpu',compute_type='int8',cpu_threads=8,transcript=' '.join(transcript),words=words,reason='Earlier aggregate timing receipt FAIL; refine source-bound timing without prompt')
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Saved',slot['shot'],result['transcript'],flush=True)
