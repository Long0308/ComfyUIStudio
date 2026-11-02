"""Carry existing word timing through documented H3 silence padding, hash-bound."""
import json
import wave
from pathlib import Path
from review_sources import ROOT, HERE, sha

DEST = HERE/'bound-timing'
DEST.mkdir(exist_ok=True)

def read(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))

def bind(shot, prep_path, receipt_path):
    prep, receipt = read(prep_path), read(receipt_path)
    entry = receipt.get('selected', receipt)
    original, padded = Path(prep['original_wav']['path']), Path(prep['wav']['path'])
    expected = entry['sha256']
    if sha(original) != expected or expected != prep['original_wav']['sha256'] or sha(padded) != prep['wav']['sha256']:
        raise ValueError('H3 and timing hash chain mismatch')
    lead = prep.get('lead_silence_s', prep.get('head_silence_s', 0))
    with wave.open(str(original),'rb') as f:
        params, original_pcm = f.getparams(), f.readframes(f.getnframes())
    with wave.open(str(padded),'rb') as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (params.framerate, params.nchannels, params.sampwidth):
            raise ValueError('H3 padding changed PCM format')
        padded_pcm = f.readframes(f.getnframes())
    offset = round(lead*params.framerate)*params.nchannels*params.sampwidth
    if padded_pcm[offset:offset+len(original_pcm)] != original_pcm:
        raise ValueError('Original PCM is not bit-exact at H3 lead offset')
    words=[]
    for w in entry['words']:
        words.append(dict(word=w.get('word',w.get('w')), start=float(w.get('start',w.get('s')))+lead, end=float(w.get('end',w.get('e')))+lead))
    result=dict(shot=shot,sha256=sha(padded),words=words,method='existing_large_v3_words_plus_H3_padding',
                original_sha256=expected,preparation_sha256=sha(ROOT/prep_path),receipt_sha256=sha(ROOT/receipt_path),
                padding_seconds=lead,original_pcm_bit_exact_verified=True,post_trim=False)
    target=DEST/(shot+'.json')
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return str(padded.relative_to(ROOT)).replace('\\','/'),str(target.relative_to(ROOT)).replace('\\','/')

specs={
 'S05_FEMALE_THANKS':('docs/media-stage/S05-TRIO-FIX-V001/S05F_THANKS_R2/preparation.json','docs/media-stage/S05-TRIO-FIX-V001/S05F_THANKS_R2/best-take.json'),
 'S07_PRE':('docs/media-stage/S07-LINES-H3-V002/PRE/preparation.json','docs/media-stage/S07-LINES-V002/S07_PRE_take3.receipt.json'),
 'S07_A':('docs/media-stage/S07-LINES-H3-V002/A/preparation.json','docs/media-stage/S07-LINES-V002/S07_A_take1.receipt.json')}
if __name__=='__main__':
    picks=read('docs/media-stage/OVERNIGHT-2K-CUT-V001/picks.json')
    for s in picks['slots']:
        if s['shot'] in specs:
            audio,timing=bind(s['shot'],*specs[s['shot']])
            s.update(audio_path=audio,timing_receipt=timing)
            print('Bound existing timing to actual H3 padded WAV',s['shot'])
    (HERE/'picks.json').write_text(json.dumps(picks,ensure_ascii=False,indent=2),encoding='utf-8')
