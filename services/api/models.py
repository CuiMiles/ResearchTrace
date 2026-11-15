"""Native Gemini adapter with transactional, project-scoped quota accounting."""
import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from . import store
from .store import ROOT, db, event, one, rows, uid

load_dotenv(ROOT / '.env', override=False)
PACIFIC = ZoneInfo('America/Los_Angeles')
CORE = os.getenv('GEMINI_CORE_MODEL', 'gemini-4-hydrogen')
BATCH = os.getenv('GEMINI_BATCH_MODEL', 'gemini-3.5-flash-lite')
EMBED = os.getenv('GEMINI_EMBEDDING_MODEL', 'gemini-embedding-001')
BASE = 'https://generativelanguage.googleapis.com/v1beta'

class ModelError(Exception):
    pass

def quota_day(now=None):
    return datetime.fromtimestamp(now or time.time(), PACIFIC).date().isoformat()

def reset_at(now=None):
    dt = datetime.fromtimestamp(now or time.time(), PACIFIC)
    return datetime.combine(dt.date()+timedelta(days=1),datetime.min.time(),PACIFIC).timestamp()

def credentials():
    return [(os.getenv('GEMINI_PROJECT_1','gemini-shared'),os.getenv('GEMINI_API_KEY','')),
            (os.getenv('GEMINI_PROJECT_2','gemini-shared'),os.getenv('GEMINI_API_KEY2',''))]

def limits(model):
    if model == CORE:
        return (5,250000,20)
    if 'embedding' in model:
        return (100,30000,1000)
    return (15,250000,500)

def reserve(project,model,tokens,run_id,now=None):
    now = now or time.time()
    rpm,tpm,rpd=limits(model)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if run_id:
            run=c.execute('SELECT workspace,status FROM runs WHERE id=?',(run_id,)).fetchone()
            if run and run['status']=='cancelled':
                raise ModelError('任务已取消；没有发出新的模型请求')
        if tokens > min(tpm,96000):
            raise ModelError('上下文超过本次请求安全预算；请缩小范围')
        minute=c.execute('SELECT COUNT(*),COALESCE(SUM(input_tokens),0) FROM quota WHERE project=? AND model=? AND started>?',(project,model,now-60)).fetchone()
        daily=c.execute('SELECT COUNT(*) FROM quota WHERE project=? AND model=? AND day=?',(project,model,quota_day(now))).fetchone()[0]
        active=c.execute("SELECT COUNT(*) FROM quota WHERE project=? AND model=? AND status='reserved' AND started>?",(project,model,now-300)).fetchone()[0]
        if active >= 1 or minute[0]>=rpm or minute[1]+tokens>tpm:
            raise ModelError('项目分钟额度/并发预算不足，请稍后恢复任务')
        if daily>=rpd:
            raise ModelError('项目日额度已用尽；太平洋时间午夜复位')
        if model == CORE:
            # Global smoke budget persists across process restart; no automatic budget reset.
            total=c.execute('SELECT COUNT(*) FROM quota WHERE model=?',(CORE,)).fetchone()[0]
            if os.getenv('RT_SMOKE_MODE','true')=='true' and total>=int(os.getenv('HYDROGEN_SMOKE_LIMIT','4')):
                raise ModelError('Hydrogen 显式冒烟预算已用尽；管理员需配置后续预算')
            if os.getenv('RT_SMOKE_MODE','true')!='true' and daily>=int(os.getenv('HYDROGEN_RUNTIME_SOFT_RPD','16')):
                raise ModelError('Hydrogen 常规项目日软预算已用尽；保留关键演示额度，不自动继续')
            if run_id and run:
                used=c.execute('SELECT COUNT(*) FROM quota q JOIN runs r ON r.id=q.run_id WHERE q.model=? AND r.workspace=? AND q.day=?',(CORE,run['workspace'],quota_day(now))).fetchone()[0]
                if used>=int(os.getenv('HYDROGEN_SESSION_LIMIT','2')):
                    raise ModelError('本工作区 Hydrogen 日预算已用尽')
        qid=uid()
        c.execute('INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,status) VALUES(?,?,?,?,?,?,?,?)',(qid,project,model,quota_day(now),run_id,now,tokens,'reserved'))
        return qid

def client():
    return httpx.Client(proxy=os.getenv('GEMINI_PROXY') or None,timeout=httpx.Timeout(150,connect=15),trust_env=False)

def _choose(model):
    seen=set()
    for project,key in credentials():
        if not key or project in seen:
            continue
        seen.add(project)
        state=one('SELECT * FROM provider_state WHERE project=? AND model=?',(project,model))
        if state and state['status']=='disabled':
            continue
        yield project,key

def request(model,method,body,run_id,estimate):
    # Conservative 1 token per UTF-8 byte reserve; correct with actual usage.
    # No implicit retries, no alternate key from same project, no paid fallback.
    chosen=next(_choose(model),None)
    if not chosen:
        raise ModelError('模型未配置或已停用；无可用免费路由')
    project,key=chosen
    qid=None
    for attempt in range(15):
        try:
            qid=reserve(project,model,estimate,run_id)
            break
        except ModelError as exc:
            if '分钟额度' not in str(exc) or attempt==14:
                raise
            if run_id and attempt==0:
                event(run_id,'quota_wait',{'project':project,'model':model,'message':'等待项目分钟窗口；尚未发送请求，不消耗请求次数'})
            time.sleep(5)
    if qid is None:
        raise ModelError('未能预留项目额度')
    if run_id:
        event(run_id,'model_request',{'model':model,'project':project,'reserved_input_tokens':estimate,'method':method})
    result=None
    status='unknown'
    detail=''
    usage={}
    try:
        with client() as c:
            response=c.post(f'{BASE}/models/{model}:{method}',headers={'x-goog-api-key':key},json=body)
        if response.status_code!=200:
            try:
                error=response.json().get('error',{})
                category=error.get('status','HTTP_ERROR')
                message=error.get('message','')
            except ValueError:
                category='INVALID_RESPONSE'
                message=''
            if 'FreeTierOnly' in message or response.status_code in (401,403,404):
                status='disabled'
            else:
                status='failed'
            # Only controlled categories exposed, never raw upstream URL/body/headers.
            detail=f'HTTP {response.status_code} {category}'
            raise ModelError(f'{model} {detail}；请求已记账，无自动付费兜底')
        result=response.json()
        usage=result.get('usageMetadata',{})
        trace_dir=store.DATA/'traces';trace_dir.mkdir(exist_ok=True,mode=0o700)
        trace_path=trace_dir/(qid+'.json')
        trace_path.write_text(json.dumps({'model_requested':model,'quota_id':qid,'received_at':time.time(),'response':result},ensure_ascii=False))
        trace_path.chmod(0o600)
        result['_quota_id']=qid
        status='ok'
        return result,project
    except httpx.HTTPError:
        detail='网络超时或传输失败；上游消耗未知，保留预留账目'
        raise ModelError(detail) from None
    except ValueError:
        status='failed'
        detail='上游 JSON 无效'
        raise ModelError(detail) from None
    finally:
        with db() as c:
            c.execute('UPDATE quota SET status=?,input_tokens=?,output_tokens=?,usage=? WHERE id=?',(status,int(usage.get('promptTokenCount',estimate)),int(usage.get('candidatesTokenCount',0))+int(usage.get('thoughtsTokenCount',0)),json.dumps(usage),qid))
            c.execute('INSERT OR REPLACE INTO provider_state VALUES(?,?,?,?,?)',(project,model,status,detail,time.time()))

def generate(system,prompt,run_id,core=True):
    model=CORE if core else BATCH
    text_bytes=len((system+prompt).encode())
    payload={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'user','parts':[{'text':prompt}]}],
             'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':16384 if core else 8192}}
    data,project=request(model,'generateContent',payload,run_id,text_bytes+1024)
    candidates=data.get('candidates',[])
    if not candidates or candidates[0].get('finishReason')!='STOP':
        reason=candidates[0].get('finishReason','EMPTY') if candidates else 'EMPTY'
        with db() as c:
            c.execute("UPDATE quota SET status='failed_output' WHERE id=?",(data.get('_quota_id'),))
        raise ModelError(f'模型输出未完整结束（{reason}）；未发布为完成结果')
    text=''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]) if not p.get('thought'))
    if not text:
        raise ModelError('模型未返回可用内容')
    return {'text':text,'model':data.get('modelVersion',model),'requested_model':model,'usage':data.get('usageMetadata',{}),'project':project}

def embed(texts,run_id,task='RETRIEVAL_DOCUMENT'):
    if not texts:
        return {'vectors':[],'model':EMBED,'dimension':0}
    if len(texts)>32:
        raise ModelError('embedding batch 超过32条')
    requests=[{'model':f'models/{EMBED}','content':{'parts':[{'text':t}]},'taskType':task,'outputDimensionality':768} for t in texts]
    data,_=request(EMBED,'batchEmbedContents',{'requests':requests},run_id,sum(len(t.encode()) for t in texts)+128)
    vectors=[x['values'] for x in data.get('embeddings',[])]
    if len(vectors)!=len(texts) or not vectors or any(len(x)!=len(vectors[0]) for x in vectors):
        raise ModelError('embedding 返回数量或维度不符')
    return {'vectors':vectors,'model':EMBED,'dimension':len(vectors[0])}

def provider_report():
    projects=list(dict.fromkeys(p for p,k in credentials() if k))
    return {'configured':bool(projects),'paid_fallback':False,'reset_at':reset_at(),'remaining_balance':'未知；下列是本应用本地账目，其他业务用量未知',
        'projects':projects,'models':[{'model':m,'rpm':limits(m)[0],'tpm':limits(m)[1],'rpd':limits(m)[2]} for m in (CORE,BATCH,EMBED)],
        'status':rows('SELECT * FROM provider_state'),'usage':rows('SELECT project,model,day,COUNT(*) calls,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens FROM quota GROUP BY project,model,day'),
        'hydrogen_total_used':one('SELECT COUNT(*) n FROM quota WHERE model=?',(CORE,))['n'],'hydrogen_budget':int(os.getenv('HYDROGEN_SMOKE_LIMIT','4')),
        'mode':'smoke' if os.getenv('RT_SMOKE_MODE','true')=='true' else 'interactive','runtime_soft_rpd':int(os.getenv('HYDROGEN_RUNTIME_SOFT_RPD','16'))}
