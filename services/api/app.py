import asyncio
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[2]/'.env')

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .store import ROOT, DATA, artifact, db, execute, migrate, one, rows, uid
from .jobs import bibliography, export_note, queue

@asynccontextmanager
async def lifespan(app):
    migrate()
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,workspace TEXT NOT NULL,role TEXT NOT NULL,expires REAL NOT NULL)')
    yield

app=FastAPI(title='ResearchTrace API',version='1.0.0',lifespan=lifespan)

@app.middleware('http')
async def security(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        host=request.headers.get('host')
        if origin and origin.split('://',1)[-1]!=host:
            return Response('Cross-origin write blocked',status_code=403)
    try:
        response=await call_next(request)
    except ValueError as e:
        return Response(json.dumps({'detail':str(e)[:250]},ensure_ascii=False),status_code=422,media_type='application/json')
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

def session(request:Request):
    token=request.cookies.get('rt_session','')
    data=one('SELECT workspace,role FROM sessions WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time()))
    if not data:
        raise HTTPException(401,'请使用本地配置的访问码登录')
    return data

def admin(s=Depends(session)):
    if s['role']!='admin':
        raise HTTPException(403,'需要管理员权限')
    return s

def version(vid,w):
    v=one('SELECT * FROM versions WHERE id=? AND workspace=? AND deleted=0',(vid,w))
    if not v:
        raise HTTPException(404,'文档不存在或无权限；历史证据可能已删除')
    v.pop('path',None);v['metadata']=json.loads(v['metadata'])
    a=one('SELECT parse_id FROM active_parses WHERE version_id=?',(vid,))
    v['active_parse_id']=a['parse_id'] if a else vid
    return v

def block_decode(b):
    b['bbox']=json.loads(b['bbox']) if isinstance(b['bbox'],str) else b['bbox']
    b['metadata']=json.loads(b.get('metadata') or '{}') if isinstance(b.get('metadata'),str) else b.get('metadata',{})
    return b

def run_get(rid,w):
    r=one('SELECT * FROM runs WHERE id=? AND workspace=?',(rid,w))
    if not r:
        raise HTTPException(404,'任务不存在或无权限')
    for k in ('payload','result','checkpoint'):
        r[k]=json.loads(r[k]) if r[k] else None
    r.pop('checkpoint',None)
    def annotate(value):
        if isinstance(value,dict):
            if value.get('block_id') and value.get('version_id'):
                from .snapshots import block_parse
                value.setdefault('parse_id',block_parse(value['block_id'],value['version_id']))
            for child in value.values():
                annotate(child)
        elif isinstance(value,list):
            for child in value: annotate(child)
    annotate(r['result'])
    r['steps']=rows('SELECT id,event,data,created FROM steps WHERE run_id=? ORDER BY id',(rid,))
    for step in r['steps']:
        step['data']=json.loads(step['data'])
    return r

class Login(BaseModel):
    code:str=Field(min_length=1,max_length=200)
    workspace:str|None=Field(default=None,max_length=100)

LOGIN_ATTEMPTS={}
@app.post('/api/v1/auth/login')
def login(p:Login,request:Request,response:Response):
    peer=request.client.host if request.client else 'unknown'
    recent=[t for t in LOGIN_ATTEMPTS.get(peer,[]) if t>time.time()-60]
    if len(recent)>=10:
        raise HTTPException(429,'登录尝试过多，请稍后再试')
    LOGIN_ATTEMPTS[peer]=recent+[time.time()]
    role=None
    for name,label in [('RT_ADMIN_CODE','admin'),('RT_ACCESS_CODE','reviewer')]:
        code=os.getenv(name,'')
        if code and hmac.compare_digest(p.code,code):
            role=label
    if not role:
        raise HTTPException(401,'访问码错误或尚未配置')
    # Workspace IDs are never accepted from an unauthenticated caller.
    prior=None
    try:
        prior=session(request)
    except HTTPException:
        pass
    workspace=prior['workspace'] if prior else uid()
    execute('INSERT OR IGNORE INTO workspaces VALUES(?,?,?)',(workspace,'我的研究空间',time.time()))
    token=secrets.token_urlsafe(40)
    execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),workspace,role,time.time()+7*86400))
    response.set_cookie('rt_session',token,httponly=True,samesite='strict',secure=os.getenv('RT_SECURE_COOKIE','false')=='true',max_age=7*86400)
    return {'workspace':workspace,'role':role}

@app.get('/api/v1/auth/session')
def who(s=Depends(session)):
    return s

@app.get('/api/v1/capabilities')
def capabilities(s=Depends(session)):
    from .models import CORE,BATCH,credentials
    return {'model_configured':any(bool(key) for _,key in credentials()),'core_model':CORE,'batch_model':BATCH,'paid_fallback':False}

@app.post('/api/v1/auth/logout')
def logout(request:Request,response:Response,s=Depends(session)):
    execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get('rt_session','').encode()).hexdigest(),))
    response.delete_cookie('rt_session');return {'ok':True}

@app.get('/healthz')
def health():
    return {'status':'ok','service':'ResearchTrace'}

@app.get('/readyz')
def ready():
    return {'status':'ok' if one('SELECT 1 n') else 'unavailable'}

@app.post('/api/v1/documents')
async def upload(files:list[UploadFile]=File(...),index_dense:bool=True,s=Depends(session)):
    from .documents import upload_document
    if len(files)>10:
        raise HTTPException(413,'单次最多10个文件')
    docs=[];runs=[]
    for f in files:
        content=await f.read(50*1024*1024+1)
        if len(content)>50*1024*1024:
            raise HTTPException(413,'PDF 上限50MB')
        result=await asyncio.to_thread(upload_document,s['workspace'],f.filename or 'upload.pdf',content,index_dense=index_dense)
        v=result.get('document') or result
        if isinstance(v,dict) and v.get('id'):
            v=version(v['id'],s['workspace'])
        v['duplicate']=result.get('duplicate',False);docs.append(v)
        if result.get('run_id'):
            runs.append({'id':result['run_id'],'run_id':result['run_id'],'status':'queued'})
    return {'documents':docs,'runs':runs}

@app.get('/api/v1/documents')
def documents(s=Depends(session)):
    return [version(v['id'],s['workspace']) for v in rows('SELECT id FROM versions WHERE workspace=? AND deleted=0 ORDER BY created DESC',(s['workspace'],))]

@app.get('/api/v1/documents/{vid}/status')
def status(vid:str,s=Depends(session)):
    return version(vid,s['workspace'])

@app.get('/api/v1/documents/{vid}/file')
def pdf(vid:str,s=Depends(session)):
    version(vid,s['workspace'])
    v=one('SELECT path FROM versions WHERE id=?',(vid,))
    path=Path(v['path']).resolve()
    if not path.is_relative_to(DATA) or not path.is_file():
        raise HTTPException(404,'原文文件已缺失')
    return FileResponse(path,media_type='application/pdf',filename=vid+'.pdf',content_disposition_type='inline')

class ParseRequest(BaseModel):
    engine:str=Field(pattern='^(native|paddleocr|paddleocr_vl|mineru)$')
    device:str=Field(default='cpu',pattern='^(cpu|gpu)$')
    idempotency_key:str=Field(min_length=1,max_length=200)

@app.get('/api/v1/documents/{vid}/parses')
def parses(vid:str,s=Depends(session)):
    version(vid,s['workspace'])
    from .snapshots import list_parses
    return list_parses(s['workspace'],vid)

@app.post('/api/v1/documents/{vid}/parses')
def reparse(vid:str,p:ParseRequest,s=Depends(session)):
    version(vid,s['workspace'])
    from .snapshots import queue_parse
    return queue_parse(s['workspace'],vid,p.engine,p.device,p.idempotency_key)

@app.get('/api/v1/documents/{vid}/pages/{page_index}')
def page(vid:str,page_index:int,parse_id:str|None=None,s=Depends(session)):
    version(vid,s['workspace'])
    from .snapshots import selected_parse, snapshot_blocks
    snap=selected_parse(s['workspace'],vid,parse_id)
    p=one('SELECT * FROM pages WHERE version_id=? AND page_index=?',(vid,page_index)) if snap['id']==vid else one('SELECT * FROM parse_pages WHERE parse_id=? AND page_index=?',(snap['id'],page_index))
    if not p:
        raise HTTPException(404,'该页尚未解析或不存在')
    p['parse_id']=snap['id']
    p['blocks']=[block_decode(b) for b in snapshot_blocks(s['workspace'],vid,snap['id'],page_index=page_index)]
    return p

@app.get('/api/v1/documents/{vid}/blocks')
def blocks(vid:str,offset:int=0,limit:int=100,page_index:int|None=None,parse_id:str|None=None,s=Depends(session)):
    version(vid,s['workspace']);limit=max(1,min(limit,500));offset=max(0,offset)
    from .snapshots import snapshot_blocks, selected_parse
    snap=selected_parse(s['workspace'],vid,parse_id)
    items=snapshot_blocks(s['workspace'],vid,snap['id'],page_index=page_index,offset=offset,limit=limit)
    return [block_decode(b) for b in items]

@app.get('/api/v1/documents/{vid}/references')
def references(vid:str,parse_id:str|None=None,s=Depends(session)):
    version(vid,s['workspace'])
    from .snapshots import selected_parse
    snap=selected_parse(s['workspace'],vid,parse_id)
    return rows("SELECT * FROM refs WHERE workspace=? AND version_id=? AND COALESCE(json_extract(metadata,'$.parse_id'),version_id)=?",(s['workspace'],vid,snap['id']))

@app.get('/api/v1/documents/{vid}/search')
def search_document(vid:str,q:str=Query(default='',max_length=500),parse_id:str|None=None,s=Depends(session)):
    import re
    version(vid,s['workspace'])
    from .snapshots import selected_parse
    snap=selected_parse(s['workspace'],vid,parse_id)
    terms=re.findall(r'[\wβγδ]+',q,re.UNICODE)[:30]
    if not terms:
        return []
    match=' OR '.join('"'+t.replace('"','""')+'"'+('*' if t.isascii() and len(t)>1 else '') for t in terms)
    return [block_decode(b) for b in rows('SELECT b.*,COALESCE(m.parse_id,b.version_id) AS parse_id FROM block_fts JOIN blocks b ON b.id=block_fts.id LEFT JOIN block_parses m ON m.block_id=b.id WHERE block_fts MATCH ? AND b.workspace=? AND b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? ORDER BY bm25(block_fts) LIMIT 50',(match,s['workspace'],vid,snap['id']))]

class OutlineEntry(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    page_index:int=Field(ge=0)
    block_id:str|None=None

class PatchDoc(BaseModel):
    title:str|None=Field(default=None,max_length=500)
    tags:list[str]|None=None
    work_id:str|None=None
    outline:list[OutlineEntry]|None=Field(default=None,max_length=2000)

@app.patch('/api/v1/documents/{vid}')
def patch_document(vid:str,p:PatchDoc,s=Depends(session)):
    v=version(vid,s['workspace']);meta=v['metadata']
    if p.title:
        execute('UPDATE versions SET title=? WHERE id=?',(p.title,vid))
    if p.tags is not None:
        meta['tags']=p.tags[:30];execute('UPDATE versions SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),vid))
    if p.outline is not None:
        if v['status'] not in ('ready','partial'):
            raise HTTPException(409,'请等待当前解析阶段完成后修正目录')
        for item in p.outline:
            if item.block_id is None:
                first=one('SELECT id FROM current_blocks WHERE version_id=? AND workspace=? AND page_index=? ORDER BY reading_order LIMIT 1',(vid,s['workspace'],item.page_index))
                if first:
                    item.block_id=first['id']
            if not one('SELECT id FROM current_blocks WHERE id=? AND version_id=? AND workspace=? AND page_index=?',(item.block_id,vid,s['workspace'],item.page_index)):
                raise HTTPException(422,'目录项必须指向此版本的真实段落和物理页')
        meta['outline']=[item.model_dump() for item in p.outline];meta['outline_manual']=True
        execute('UPDATE versions SET metadata=? WHERE id=?',(json.dumps(meta,ensure_ascii=False),vid))
    if p.work_id:
        if not one('SELECT id FROM works WHERE id=? AND workspace=?',(p.work_id,s['workspace'])):
            raise HTTPException(404,'作品不存在')
        execute('UPDATE versions SET work_id=? WHERE id=?',(p.work_id,vid))
    return version(vid,s['workspace'])

@app.delete('/api/v1/documents/{vid}')
def delete_document(vid:str,s=Depends(session)):
    version(vid,s['workspace'])
    with db() as c:
        c.execute('DELETE FROM block_fts WHERE id IN (SELECT id FROM blocks WHERE workspace=? AND version_id=?)',(s['workspace'],vid))
        c.execute('DELETE FROM embeddings WHERE workspace=? AND version_id=?',(s['workspace'],vid))
        c.execute('UPDATE versions SET deleted=1 WHERE id=?',(vid,))
        c.execute("UPDATE runs SET status='cancelled' WHERE workspace=? AND status IN ('queued','running') AND payload LIKE ?",(s['workspace'],'%'+vid+'%'))
    return {'deleted':True,'history':'原引用保留不可用提示；不会指向其他版本'}

class Compare(BaseModel):
    left:str
    right:str

@app.post('/api/v1/versions/compare')
def compare(p:Compare,s=Depends(session)):
    from .documents import compare_versions
    version(p.left,s['workspace']);version(p.right,s['workspace'])
    return compare_versions(s['workspace'],p.left,p.right)

class Question(BaseModel):
    question:str=Field(min_length=1,max_length=6000)
    version_ids:list[str]=Field(min_length=1,max_length=20)
    idempotency_key:str=Field(min_length=8,max_length=150)

def ask(p,s,kind):
    for v in p.version_ids:
        version(v,s['workspace'])
    return queue(s['workspace'],kind,p.model_dump(exclude={'idempotency_key'}),p.idempotency_key)

@app.post('/api/v1/qa/runs')
def qa(p:Question,s=Depends(session)):
    return ask(p,s,'qa')

@app.get('/api/v1/agent/tools')
def agent_tools(s=Depends(session)):
    from .tool_registry import tool_schemas
    return {'tools':tool_schemas(),'max_steps':10,'provider_budget':0,'notice':'Registered tools have JSON schemas and workspace checks. New core synthesis remains subject to the persistent model quota.'}

@app.post('/api/v1/agent/runs')
def agent(p:Question,s=Depends(session)):
    return ask(p,s,'agent')

class Translation(BaseModel):
    version_id:str
    block_ids:list[str]|None=Field(default=None,max_length=100)
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/translations')
def translation(p:Translation,s=Depends(session)):
    version(p.version_id,s['workspace'])
    return queue(s['workspace'],'translate',p.model_dump(exclude={'idempotency_key'}),p.idempotency_key)

@app.get('/api/v1/translations/{vid}')
def translations(vid:str,s=Depends(session)):
    version(vid,s['workspace'])
    return rows('SELECT block_id,text,model FROM translations WHERE workspace=? AND version_id=?',(s['workspace'],vid))

@app.get('/api/v1/translations/{vid}/export')
def translation_export(vid:str,format:str='md',s=Depends(session)):
    v=version(vid,s['workspace'])
    bs=rows('SELECT b.text source,t.text,t.model,b.page_index FROM current_blocks b LEFT JOIN translations t ON t.block_id=b.id AND t.workspace=b.workspace WHERE b.version_id=? AND b.workspace=? ORDER BY b.page_index,b.reading_order',(vid,s['workspace']))
    text='# '+v['title']+'\n\n'
    for b in bs:
        text+=f"\n原文 p.{b['page_index']+1}\n\n{b['source']}\n\n译文（{b['model'] or '未完成'}）\n\n{b['text'] or '[尚未翻译]'}\n\n"
    if format=='html':
        return HTMLResponse('<!doctype html><meta charset="utf-8"><pre style="white-space:pre-wrap">'+html.escape(text)+'</pre>')
    return Response(text,media_type='text/markdown',headers={'Content-Disposition':'attachment; filename="translation.md"'})

@app.get('/api/v1/runs')
def runs(summary:bool=True,s=Depends(session)):
    if not summary:
        return [run_get(r['id'],s['workspace']) for r in rows('SELECT id FROM runs WHERE workspace=? ORDER BY created DESC LIMIT 40',(s['workspace'],))]
    result=rows('SELECT id,kind,status,payload,error,created,updated FROM runs WHERE workspace=? ORDER BY created DESC LIMIT 40',(s['workspace'],))
    for r in result:
        r['payload']=json.loads(r['payload']);r['result']=None;r['steps']=[]
    return result

@app.get('/api/v1/runs/{rid}')
def get_run(rid:str,s=Depends(session)):
    return run_get(rid,s['workspace'])

@app.get('/api/v1/runs/{rid}/events')
async def events(rid:str,request:Request,after:int=0,s=Depends(session)):
    run_get(rid,s['workspace'])
    try:
        after=max(after,int(request.headers.get('last-event-id','0')))
    except ValueError:
        raise HTTPException(422,'无效事件序号')
    async def stream():
        seq=after
        while not await request.is_disconnected():
            for step in rows('SELECT * FROM steps WHERE run_id=? AND id>? ORDER BY id',(rid,seq)):
                seq=step['id']
                yield 'id: '+str(seq)+'\nevent: step\ndata: '+json.dumps({'id':seq,'event':step['event'],'data':json.loads(step['data']),'created':step['created']},ensure_ascii=False)+'\n\n'
            status=one('SELECT status FROM runs WHERE id=?',(rid,))['status']
            if status not in ('queued','running'):
                yield 'event: done\ndata: '+json.dumps({'status':status})+'\n\n';break
            yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

@app.post('/api/v1/runs/{rid}/cancel')
def cancel(rid:str,s=Depends(session)):
    r=run_get(rid,s['workspace'])
    if r['status'] in ('queued','running','failed','partial'):
        execute("UPDATE runs SET status='cancelled',updated=? WHERE id=?",(time.time(),rid))
        if r['kind'] in ('parse','parse_document','reparse'):
            execute("UPDATE parses SET status='cancelled' WHERE id=?",(r['payload'].get('parse_id',r['payload']['version_id']),))
    if r['kind']=='agent':
        from .tool_registry import ToolContext,cancel_tool_children
        cancel_tool_children(ToolContext(workspace=s['workspace'],run_id=rid))
    return run_get(rid,s['workspace'])

@app.post('/api/v1/runs/{rid}/resume')
def resume(rid:str,s=Depends(session)):
    r=run_get(rid,s['workspace'])
    if r['status'] in ('cancelled','failed','partial'):
        execute("UPDATE runs SET status='queued',error=NULL,updated=? WHERE id=?",(time.time(),rid))
        if r['kind'] in ('parse','parse_document','reparse'):
            execute("UPDATE parses SET status='queued',error=NULL WHERE id=?",(r['payload'].get('parse_id',r['payload']['version_id']),))
    return run_get(rid,s['workspace'])

class Search(BaseModel):
    query:str=Field(min_length=1,max_length=1000)
    sources:list[str]|None=None
    limit:int=Field(default=10,ge=1,le=30)

@app.post('/api/v1/search')
async def search(p:Search,s=Depends(session)):
    from .research import search_papers
    return await asyncio.to_thread(search_papers,s['workspace'],p.query,p.sources,p.limit)

class Import(BaseModel):
    paper:dict

@app.post('/api/v1/search/import')
async def import_paper(p:Import,s=Depends(session)):
    from .research import import_paper
    return await asyncio.to_thread(import_paper,s['workspace'],p.paper)

class Feedback(BaseModel):
    identity:str=Field(max_length=500)
    value:int=Field(ge=-1,le=1)

@app.post('/api/v1/feedback')
def feedback(p:Feedback,s=Depends(session)):
    execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?)',(s['workspace'],p.identity,p.value));return {'ok':True}

class Watch(BaseModel):
    query:str=Field(min_length=1,max_length=1000)
    enabled:bool=False
    interval_hours:float=Field(default=24,ge=1,le=8760)

@app.post('/api/v1/watch-queries')
def watch(p:Watch,s=Depends(session)):
    wid=uid();execute('INSERT INTO watches(id,workspace,query,enabled,interval_hours,next_check) VALUES(?,?,?,?,?,?)',(wid,s['workspace'],p.query,int(p.enabled),p.interval_hours,time.time()+p.interval_hours*3600))
    return one('SELECT * FROM watches WHERE id=?',(wid,))

@app.get('/api/v1/watch-queries')
def watches(s=Depends(session)):
    return rows('SELECT * FROM watches WHERE workspace=?',(s['workspace'],))

@app.post('/api/v1/watch-queries/{wid}/check')
async def check(wid:str,s=Depends(session)):
    from .research import check_watch
    if not one('SELECT id FROM watches WHERE id=? AND workspace=?',(wid,s['workspace'])):
        raise HTTPException(404,'查询不存在')
    return await asyncio.to_thread(check_watch,s['workspace'],wid)

class WatchPatch(BaseModel):
    enabled:bool

@app.patch('/api/v1/watch-queries/{wid}')
def patch_watch(wid:str,p:WatchPatch,s=Depends(session)):
    if not execute('UPDATE watches SET enabled=? WHERE id=? AND workspace=?',(int(p.enabled),wid,s['workspace'])):
        raise HTTPException(404,'查询不存在')
    return {'enabled':p.enabled}

@app.post('/api/v1/graphs')
def graph(s=Depends(session)):
    from .research import build_graph
    return build_graph(s['workspace'])

class Audit(BaseModel):
    version_id:str
    block_id:str
    question:str=Field(min_length=1,max_length=1500)
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/ideas/audits')
def audit(p:Audit,s=Depends(session)):
    version(p.version_id,s['workspace'])
    if not one('SELECT id FROM blocks WHERE id=? AND version_id=? AND workspace=?',(p.block_id,p.version_id,s['workspace'])):
        raise HTTPException(404,'建议原文不存在')
    return queue(s['workspace'],'audit',p.model_dump(exclude={'idempotency_key'}),p.idempotency_key)

@app.post('/api/v1/charts')
async def chart(file:UploadFile=File(...),spec:str=Form('{}'),s=Depends(session)):
    from .charts import create_chart
    content=await file.read(5*1024*1024+1)
    if len(content)>5*1024*1024:
        raise HTTPException(413,'CSV 上限5MB')
    return await asyncio.to_thread(create_chart,s['workspace'],file.filename or 'data.csv',content,json.loads(spec))

@app.get('/api/v1/artifacts')
def artifacts(s=Depends(session)):
    rs=rows('SELECT * FROM artifacts WHERE workspace=? ORDER BY created DESC',(s['workspace'],))
    for r in rs:
        r['payload']=json.loads(r['payload'])
    return rs

@app.get('/api/v1/artifacts/{aid}')
def get_artifact(aid:str,s=Depends(session)):
    a=one('SELECT * FROM artifacts WHERE id=? AND workspace=?',(aid,s['workspace']))
    if not a:
        raise HTTPException(404,'产物不存在或无权限')
    a['payload']=json.loads(a['payload']);return a

@app.get('/api/v1/artifacts/{aid}/files/{name}')
def get_artifact_file(aid:str,name:str,s=Depends(session)):
    from .charts import artifact_file
    try:
        path=artifact_file(s['workspace'],aid,name)
    except (ValueError,FileNotFoundError):
        raise HTTPException(404,'文件不存在或无权限')
    return FileResponse(path)

@app.get('/api/v1/artifacts/{aid}/export')
def export_artifact(aid:str,format:str='md',s=Depends(session)):
    a=get_artifact(aid,s)
    a['payload']['bibliography']=bibliography(s['workspace'],a['payload'])
    if format=='bib':
        text=''
        clean=lambda x:str(x).replace('{','').replace('}','').replace('\\','')
        for entry in a['payload']['bibliography']:
            text+='@article{rt'+entry['version_id']+',\n title={'+clean(entry['title'])+'},\n url={'+clean(entry['url'])+'}'
            if entry['identity'].startswith('doi:'):
                text+=',\n doi={'+clean(entry['identity'][4:])+'}'
            if entry.get('author'):
                text+=',\n author={'+clean(entry['author'])+'}'
            text+='\n}\n'
        return Response(text,media_type='application/x-bibtex')
    text=export_note(a['payload'],a['title'],format)
    return Response(text,media_type='text/html' if format=='html' else 'text/markdown',headers={'Content-Disposition':f'attachment; filename="research-note.{"html" if format=="html" else "md"}"'})

@app.get('/api/v1/admin/providers')
def providers(s=Depends(admin)):
    from .models import provider_report
    return provider_report()

@app.get('/api/v1/admin/acceptance')
def admin_acceptance(s=Depends(admin)):
    from .acceptance_report import build_acceptance_report
    return build_acceptance_report()

@app.get('/api/v1/admin/evidence-file')
def admin_evidence_file(path:str=Query(...,min_length=1),s=Depends(admin)):
    from .acceptance_report import MEDIA_TYPES, resolve_evidence_file
    target=resolve_evidence_file(path)
    if not target:
        raise HTTPException(404,'证据文件不存在或不允许访问')
    headers={'X-Content-Type-Options':'nosniff'}
    if target.suffix.lower()=='.svg':
        headers['Content-Security-Policy']='sandbox'
    return FileResponse(target,media_type=MEDIA_TYPES[target.suffix.lower()],headers=headers)

dist=ROOT/'apps/web/dist'
app.mount('/assets',StaticFiles(directory=dist/'assets',check_dir=False),name='assets')
app.mount('/vendor',StaticFiles(directory=dist/'vendor',check_dir=False),name='vendor')

@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'):
        raise HTTPException(404,'未知 API')
    index=dist/'index.html'
    if not index.exists():
        return HTMLResponse('<h1>ResearchTrace API ready</h1><p>Frontend build pending. See /docs.</p>',status_code=503)
    return FileResponse(index)
