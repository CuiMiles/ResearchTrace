"""Concatenate MiniMax group audio and derive per-line / per-scene times from its subtitle files."""
import os, json,subprocess,re
SP=os.environ.get('RT_VIDEO_WORK', '/tmp/rt-video'); A=f'{SP}/v3/audio'
N=json.load(open('/home/dev/projects/ResearchTrace/scripts/video/narration_v3.json'))
GAP=0.55; LEAD=1.0
groups=sorted({s['group'] for s in N['scenes']})
def dur(f): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f]).decode())
off=LEAD; lines=[]; parts=[]
for g in groups:
    f=f'{A}/g{g:02d}.mp3'; d=dur(f); subs=json.load(open(f'{A}/g{g:02d}.subtitle.json'))
    mine=[(sc['id'],l) for sc in N['scenes'] if sc['group']==g for l in sc['lines']]
    norm=lambda z:re.sub(r'[\s，。、；：？！,.;:?!“”"]','',z)
    k=0
    for sid,l in mine:
        want=norm(l.get('say',l['sub'])); got='';first=subs[k]
        while got!=want:
            got+=norm(subs[k]['text']); last=subs[k]; k+=1
            assert len(got)<=len(want) and want.startswith(got),(g,want[:20],got[:20])
        lines.append({'scene':sid,'sub':l['sub'],'start':round(off+first['time_begin']/1000,3),'end':round(off+last['time_end']/1000,3)})
    assert k==len(subs)
    parts.append((f,off,d)); off+=d+GAP
total=round(off-GAP+1.6,3)
scenes=[]; ids=[s['id'] for s in N['scenes']]
for i,sid in enumerate(ids):
    ls=[l for l in lines if l['scene']==sid]
    start=0.0 if i==0 else round(ls[0]['start']-0.35,3)
    scenes.append({'id':sid,'kind':next(s['kind'] for s in N['scenes'] if s['id']==sid),'start':start,'lines':[{k:l[k] for k in ('sub','start','end')} for l in ls]})
for i,s in enumerate(scenes): s['end']=scenes[i+1]['start'] if i+1<len(scenes) else total
json.dump({'duration':total,'scenes':scenes},open(f'{SP}/v3/timeline.json','w'),ensure_ascii=False,indent=1)
# narration track: silence lead, groups at their offsets
filt=''.join(f'[{i}:a]aresample=48000,adelay={int(o*1000)}|{int(o*1000)}[a{i}];' for i,(f,o,d) in enumerate(parts))+''.join(f'[a{i}]' for i in range(len(parts)))+f'amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total},loudnorm=I=-16:TP=-1.5:LRA=11[out]'
cmd=['ffmpeg','-y','-v','error']+sum([['-i',f] for f,o,d in parts],[])+['-filter_complex',filt,'-map','[out]','-ac','1','-ar','48000',f'{SP}/v3/narration.wav']
subprocess.check_call(cmd)
print('total',total,'audio',round(dur(f'{SP}/v3/narration.wav'),2))
for s in scenes: print(s['id'],s['start'],round(s['end']-s['start'],1))
