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
from typing import Literal
load_dotenv(Path(__file__).resolve().parents[2]/'.env')

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from .static_assets import PrecompressedStatic
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
from .upload_limits import UploadBodyLimit
app.add_middleware(UploadBodyLimit)

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
    if request.url.path.startswith('/api') and 'cache-control' not in response.headers:
        response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

def session(request:Request):
    token=request.cookies.get('rt_session','')
    data=one('SELECT workspace,role FROM sessions WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time()))
    if not data:
        raise HTTPException(401,'请使用本地配置的访问码登录')
    if data['role']=='reviewer':
        account=one('SELECT revoked,expires FROM review_accounts WHERE workspace=?',(data['workspace'],))
        if account and (account['revoked'] or account['expires']<=time.time()):
            raise HTTPException(401,'评审入口已到期或已撤销')
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
    v['local_index']=local_index_status(w,vid)
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
    from .reviewer_accounts import lookup_reviewer
    identity=lookup_reviewer(p.code)
    role='reviewer' if identity else None
    for name,label in ([] if identity else [('RT_ADMIN_CODE','admin'),('RT_ACCESS_CODE','reviewer')]):
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
    workspace=identity['workspace'] if identity else prior['workspace'] if prior else uid()
    execute('INSERT OR IGNORE INTO workspaces VALUES(?,?,?)',(workspace,'我的研究空间',time.time()))
    token=secrets.token_urlsafe(40)
    expires=min(time.time()+7*86400,identity['expires']) if identity else time.time()+7*86400
    execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),workspace,role,expires))
    response.set_cookie('rt_session',token,httponly=True,samesite='strict',secure=os.getenv('RT_SECURE_COOKIE','false')=='true',max_age=7*86400)
    return {'workspace':workspace,'role':role}

@app.get('/api/v1/auth/session')
def who(s=Depends(session)):
    return s

@app.get('/api/v1/capabilities')
def capabilities(s=Depends(session)):
    from .models import CORE,BATCH,credentials
    return {'model_configured':any(bool(key) for _,key in credentials()) and os.getenv('RT_PROVIDER_MODE','all') not in ('embedding_only','disabled'),
            'core_model':CORE,'batch_model':BATCH,'paid_fallback':False,'provider_mode':os.getenv('RT_PROVIDER_MODE','all')}

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

@app.get('/api/v1/readiness')
def judging_readiness(s=Depends(session)):
    from .readiness import inspect
    return inspect(s['workspace'])

@app.post('/api/v1/documents')
async def upload(files:list[UploadFile]=File(...),index_dense:bool=True,s=Depends(session)):
    from .batches import upload_batch
    result=await upload_batch(s['workspace'],files,index_dense=index_dense)
    result['documents']=[{**version(v['id'],s['workspace']),'duplicate':v.get('duplicate',False)} for v in result['documents']]
    return result

@app.get('/api/v1/batches/{batch_id}')
def get_import_batch(batch_id:str,s=Depends(session)):
    from .batches import get_batch
    return get_batch(s['workspace'],batch_id)

@app.get('/api/v1/batches')
def list_import_batches(s=Depends(session)):
    return rows('SELECT id,status,created,updated FROM import_batches WHERE workspace=? ORDER BY created DESC LIMIT 20',(s['workspace'],))

class BatchSelection(BaseModel):
    item_ids:list[str]|None=Field(default=None,max_length=50)

@app.post('/api/v1/batches/{batch_id}/cancel')
def cancel_import_batch(batch_id:str,p:BatchSelection=BatchSelection(),s=Depends(session)):
    from .batches import cancel_batch
    return cancel_batch(s['workspace'],batch_id,p.item_ids)

@app.post('/api/v1/batches/{batch_id}/resume')
def resume_import_batch(batch_id:str,p:BatchSelection=BatchSelection(),s=Depends(session)):
    from .batches import resume_batch
    return resume_batch(s['workspace'],batch_id,p.item_ids)

@app.get('/api/v1/documents')
def documents(s=Depends(session)):
    found=rows('SELECT v.*,COALESCE(a.parse_id,v.id) active_parse_id FROM versions v LEFT JOIN active_parses a ON a.version_id=v.id WHERE v.workspace=? AND v.deleted=0 ORDER BY v.created DESC',(s['workspace'],))
    indexes=index_status_map(s['workspace'])
    for v in found:
        v.pop('path',None);v['metadata']=json.loads(v['metadata']);v['local_index']=indexes[v['id']]
        # The list is polled; full outlines (a 500-page book has hundreds of
        # entries) made it ~0.5 MB. The reader loads its own via /status.
        outline=v['metadata'].pop('outline',None)
        if outline is not None:
            v['metadata']['outline_count']=len(outline) if isinstance(outline,list) else 0
    return found

@app.get('/api/v1/documents/{vid}/status')
def status(vid:str,s=Depends(session)):
    v=version(vid,s['workspace'])
    return v

def local_index_status(workspace,vid):
    return index_status_map(workspace,[vid]).get(vid,{'status':'unindexed','semantic_ready':False,'indexed_blocks':0,'eligible_blocks':0})

def index_status_map(workspace,version_ids=None):
    # Use the exact chunker's Unicode whitespace policy. SQLite length(TEXT)
    # stops at an embedded NUL in some PDFs and undercounts valid source spans.
    if version_ids is not None and not version_ids:return {}
    scope=' AND version_id IN ('+','.join('?' for _ in version_ids)+')' if version_ids is not None else ''
    args=(workspace,*(version_ids or []));counts={}
    with db() as c:
        for row in c.execute("SELECT version_id,text FROM current_blocks WHERE workspace=? AND type NOT IN ('header','footer')"+scope,args):
            if row['text'].strip():counts[row['version_id']]=counts.get(row['version_id'],0)+1
    mode=os.getenv('RT_EMBED_PROVIDER','gemini');local=os.getenv('RT_LOCAL_EMBED_MODEL','nvidia/Nemotron-3.5-Embed-8B-BF16');cloud=os.getenv('GEMINI_EMBEDDING_MODEL','gemini-embedding-001')
    models=[cloud] if mode=='gemini' else [local,cloud] if mode=='auto' else [local]
    coverage=rows('''SELECT a.version_id,a.model_id,g.id generation_id,g.status,count(DISTINCT b.id) covered
       FROM active_retrieval_indices a JOIN index_generations g ON g.id=a.generation_id
       LEFT JOIN retrieval_chunks c ON c.generation_id=g.id AND c.version_id=a.version_id AND c.workspace=a.workspace
       LEFT JOIN retrieval_spans s ON s.chunk_id=c.id
       LEFT JOIN current_blocks b ON b.id=s.block_id AND b.workspace=a.workspace AND b.version_id=a.version_id
       WHERE a.workspace=?'''+scope.replace('version_id','a.version_id')+' GROUP BY a.version_id,a.model_id,g.id',args)
    lookup={(r['version_id'],r['model_id']):r for r in coverage};result={};pending={}
    for r in rows("SELECT id,status,payload FROM runs WHERE workspace=? AND kind='index' AND status IN ('queued','running','waiting_batch','failed','partial') ORDER BY created DESC",(workspace,)):
        payload=json.loads(r['payload'])
        for vid in payload.get('version_ids',[]):
            if vid not in pending:pending[vid]=r
    for v in rows('SELECT id FROM versions WHERE workspace=? AND deleted=0'+scope.replace('version_id','id'),args):
        providers=[];expected=counts.get(v['id'],0)
        for model in models:
            r=lookup.get((v['id'],model));covered=r['covered'] if r else 0
            ready=bool(r and r['status']=='ready' and covered==expected and expected>0)
            providers.append({'status':'ready' if ready else 'unindexed','generation_id':r['generation_id'] if r else None,'model_id':model,
                              'indexed_blocks':covered,'eligible_blocks':expected,'semantic_ready':ready})
        chosen=next((p for p in providers if p['semantic_ready']),providers[0])
        item={**chosen,'providers':providers}
        if not chosen['semantic_ready'] and v['id'] in pending:
            run=pending[v['id']]
            item.update(status=run['status'],pending_run_id=run['id'])
        result[v['id']]=item
    return result

class IndexRequest(BaseModel):
    version_ids:list[str]=Field(min_length=1,max_length=100)
    generation_id:str|None=None
    provider:Literal['local','gemini']|None=None
    source_generation_id:str|None=None
    pack_cloud:bool=False
    chunks_only:bool=False
    activate:bool=True
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/indices/runs')
def build_index(p:IndexRequest,s=Depends(session)):
    # Ownership requires one bounded lookup, not 35 full-library index joins.
    ids=set(p.version_ids);marks=','.join('?' for _ in ids)
    found=rows('SELECT id FROM versions WHERE workspace=? AND deleted=0 AND id IN ('+marks+')',(s['workspace'],*ids))
    if len(found)!=len(ids):raise HTTPException(404,'文档不存在或无权限')
    return queue(s['workspace'],'index',p.model_dump(exclude={'idempotency_key'},exclude_none=True),p.idempotency_key)

@app.get('/api/v1/indices')
def index_status(s=Depends(session)):
    versions=rows('SELECT id FROM versions WHERE workspace=? AND deleted=0',(s['workspace'],))
    return {'versions':[{'version_id':v['id'],**local_index_status(s['workspace'],v['id'])} for v in versions],
            'generations':rows('SELECT id,model_id,revision,status,expected_blocks,covered_blocks,excluded_blocks,chunk_count,vector_count,dimension,created,activated,error FROM index_generations WHERE workspace=? ORDER BY created DESC',(s['workspace'],))}

@app.post('/api/v1/indices/{generation_id}/activate')
def activate_index(generation_id:str,s=Depends(session)):
    from .index_generations import activate_generation,generation_status
    activate_generation(s['workspace'],generation_id)
    return generation_status(s['workspace'],generation_id)

@app.get('/api/v1/documents/{vid}/file')
def pdf(vid:str,s=Depends(session)):
    version(vid,s['workspace'])
    v=one('SELECT path FROM versions WHERE id=?',(vid,))
    path=Path(v['path']).resolve()
    if not path.is_relative_to(DATA) or not path.is_file():
        raise HTTPException(404,'原文文件已缺失')
    # A version's bytes never change (versions are content-addressed), so the
    # browser may keep its own copy; 'private' keeps shared proxies out.
    return FileResponse(path,media_type='application/pdf',filename=vid+'.pdf',content_disposition_type='inline',
                        headers={'Cache-Control':'private, max-age=86400'})

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

@app.get('/api/v1/documents/{vid}/card')
def document_card(vid:str,s=Depends(session)):
    """Structured metadata of the active snapshot; every field names its source."""
    version(vid,s['workspace'])
    from .cards import get_card
    card=get_card(s['workspace'],vid)
    if card is None:
        return {'status':'missing','version_id':vid}
    return {'status':'ready',**card}

class CardRequest(BaseModel):
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/documents/{vid}/card')
def rebuild_card(vid:str,p:CardRequest,s=Depends(session)):
    """Queue a rebuild of the document card (live record lookup and one light-model call)."""
    version(vid,s['workspace'])
    return queue(s['workspace'],'card',{'version_id':vid},p.idempotency_key)

@app.get('/api/v1/documents/{vid}/outline')
def document_outline(vid:str,s=Depends(session)):
    """Hierarchical outline: PDF bookmarks when present, else numbered headings."""
    v=version(vid,s['workspace'])
    from .cards import get_card, outline_tree
    card=get_card(s['workspace'],vid)
    entries=(card or {}).get('outline')
    if entries is None:
        meta=v['metadata'] if isinstance(v['metadata'],dict) else json.loads(v['metadata'] or '{}')
        entries=[{**e,'level':e.get('level',1)} for e in meta.get('outline',[])]
    return {'source':'document_card' if card else 'legacy_headings','tree':outline_tree(entries)}

@app.get('/api/v1/documents/{vid}/search')
def search_document(vid:str,q:str=Query(default='',max_length=500),parse_id:str|None=None,s=Depends(session)):
    version(vid,s['workspace'])
    from .snapshots import selected_parse
    snap=selected_parse(s['workspace'],vid,parse_id)
    from .sparse_index import search
    hits,_=search(s['workspace'],[vid],q,limit=50,parse_id=snap['id'])
    return [block_decode(b) for b in hits]

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
        c.execute("UPDATE runs SET status='cancelled' WHERE workspace=? AND status IN ('queued','running','waiting_batch') AND payload LIKE ?",(s['workspace'],'%'+vid+'%'))
    return {'deleted':True,'history':'原引用保留不可用提示；不会指向其他版本'}

class Compare(BaseModel):
    left:str
    right:str

@app.post('/api/v1/versions/compare')
def compare(p:Compare,s=Depends(session)):
    from .documents import compare_versions
    version(p.left,s['workspace']);version(p.right,s['workspace'])
    return compare_versions(s['workspace'],p.left,p.right)

@app.post('/api/v1/versions/impact')
def version_note_impact(p:Compare,s=Depends(session)):
    from .version_impact import assess
    return assess(s['workspace'],p.left,p.right)

class Question(BaseModel):
    question:str=Field(min_length=1,max_length=6000)
    version_ids:list[str]=Field(min_length=1,max_length=20)
    idempotency_key:str=Field(min_length=8,max_length=150)
    # Conversation thread: earlier turns are read server-side from this workspace's runs.
    thread_id:str|None=Field(default=None,pattern=r'^[A-Za-z0-9_-]{8,64}$')

def ask(p,s,kind):
    for v in p.version_ids:
        version(v,s['workspace'])
    return queue(s['workspace'],kind,p.model_dump(exclude={'idempotency_key'},exclude_none=True),p.idempotency_key)

@app.get('/api/v1/chat/threads')
def chat_threads(s=Depends(session)):
    """Conversation threads derived from question runs that carry a thread_id."""
    found=rows("""SELECT json_extract(payload,'$.thread_id') AS thread_id,MIN(created) AS created,MAX(updated) AS updated,
                         COUNT(*) AS turns FROM runs WHERE workspace=? AND kind IN ('qa','agent')
                         AND json_extract(payload,'$.thread_id') IS NOT NULL GROUP BY 1 ORDER BY updated DESC LIMIT 50""",(s['workspace'],))
    for thread in found:
        first=one("""SELECT payload FROM runs WHERE workspace=? AND json_extract(payload,'$.thread_id')=?
                      ORDER BY created LIMIT 1""",(s['workspace'],thread['thread_id']))
        payload=json.loads(first['payload'])
        thread.update(title=payload['question'][:80],version_ids=payload['version_ids'])
    return found

@app.get('/api/v1/chat/threads/{thread_id}')
def chat_thread(thread_id:str,s=Depends(session)):
    ids=rows("""SELECT id FROM runs WHERE workspace=? AND kind IN ('qa','agent') AND json_extract(payload,'$.thread_id')=?
                 ORDER BY created""",(s['workspace'],thread_id))
    if not ids:
        raise HTTPException(404,'对话不存在或无权限')
    return {'thread_id':thread_id,'runs':[run_get(r['id'],s['workspace']) for r in ids[-30:]]}

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
    source_language:Literal['auto','en','zh']='auto'
    target_language:Literal['en','zh-Hans']='zh-Hans'
    glossary_version:str=Field(default='default',pattern=r'^[A-Za-z0-9._:-]{1,100}$')
    version_id:str
    parse_id:str|None=None
    block_ids:list[str]|None=Field(default=None,max_length=100)
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/translations')
def translation(p:Translation,s=Depends(session)):
    version(p.version_id,s['workspace'])
    return queue(s['workspace'],'translate',p.model_dump(exclude={'idempotency_key'},exclude_none=True),p.idempotency_key)

@app.get('/api/v1/translations/{vid}')
def translations(vid:str,parse_id:str|None=None,source_language:str='auto',target_language:str='zh-Hans',glossary_version:str='default',s=Depends(session)):
    version(vid,s['workspace'])
    from .translation_service import load_translations
    return load_translations(s['workspace'],vid,parse_id=parse_id,source_language=source_language,target_language=target_language,glossary_version=glossary_version)

@app.get('/api/v1/translations/{vid}/export')
def translation_export(vid:str,format:str='md',parse_id:str|None=None,source_language:str='auto',target_language:str='zh-Hans',glossary_version:str='default',s=Depends(session)):
    version(vid,s['workspace'])
    from .translation_service import export_translation
    text=export_translation(s['workspace'],vid,parse_id=parse_id,source_language=source_language,target_language=target_language,glossary_version=glossary_version,format=format)
    if format=='html':return HTMLResponse(text)
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
    if r['kind']=='reference_download':
        from .document_workflows import cancel_reference_downloads
        cancel_reference_downloads(s['workspace'],rid)
        return run_get(rid,s['workspace'])
    if r['payload'].get('batch_id') and r['payload'].get('batch_item_id'):
        from .batches import cancel_batch
        cancel_batch(s['workspace'],r['payload']['batch_id'],[r['payload']['batch_item_id']])
        return run_get(rid,s['workspace'])
    if r['status'] in ('queued','running','waiting_batch','waiting_children','failed','partial'):
        execute("UPDATE runs SET status='cancelled',updated=? WHERE id=?",(time.time(),rid))
        if r['kind'] in ('parse','parse_document','reparse'):
            execute("UPDATE parses SET status='cancelled' WHERE id=?",(r['payload'].get('parse_id',r['payload']['version_id']),))
    if r['kind']=='agent':
        from .tool_registry import ToolContext,cancel_tool_children
        cancel_tool_children(ToolContext(workspace=s['workspace'],run_id=rid))
    from .dependencies import cancel_owned_children
    cancel_owned_children(s['workspace'],rid)
    return run_get(rid,s['workspace'])

@app.post('/api/v1/runs/{rid}/resume')
def resume(rid:str,s=Depends(session)):
    r=run_get(rid,s['workspace'])
    if r['kind']=='reference_download':
        from .document_workflows import resume_reference_downloads
        resume_reference_downloads(s['workspace'],rid)
        return run_get(rid,s['workspace'])
    if r['payload'].get('batch_id') and r['payload'].get('batch_item_id'):
        from .batches import resume_batch
        resume_batch(s['workspace'],r['payload']['batch_id'],[r['payload']['batch_item_id']])
        return run_get(rid,s['workspace'])
    if r['kind']=='watch':
        raise HTTPException(409,'追踪检查请通过“立即检查”重试；不会将追踪任务加入解析队列')
    if r['status'] in ('cancelled','failed','partial') and one("SELECT 1 FROM quota WHERE run_id=? AND status IN ('reserved','unknown') LIMIT 1",(rid,)):
        raise HTTPException(409,'此任务有已发送但结果未知的请求，已保留计账；需核对上游回执，不能直接恢复重发。')
    if r['status'] in ('cancelled','failed','partial'):
        from .store import run_execution_lock
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            with run_execution_lock(rid) as acquired:
                if not acquired:
                    raise HTTPException(409,'任务正在释放资源，请稍后恢复；不会重复启动解析或模型请求')
                pending=c.execute("SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')",(s['workspace'],)).fetchone()[0]
                total=c.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
                if pending>=6 or total>=30:raise HTTPException(429,'队列已满，恢复请求尚未入队')
                current=c.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(rid,s['workspace'])).fetchone()
                if current['status'] in ('cancelled','failed','partial'):
                    c.execute("UPDATE runs SET status='queued',error=NULL,updated=? WHERE id=?",(time.time(),rid))
                    if r['kind'] in ('parse','parse_document','reparse'):
                        c.execute("UPDATE parses SET status='queued',error=NULL WHERE id=?",(r['payload'].get('parse_id',r['payload']['version_id']),))
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
    index_dense:bool=True
    metadata_only:bool=False

@app.post('/api/v1/search/import')
async def import_paper(p:Import,s=Depends(session)):
    from .research import import_paper
    return await asyncio.to_thread(import_paper,s['workspace'],p.paper,index_dense=p.index_dense,metadata_only=p.metadata_only)

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
    search_query:str|None=Field(default=None,min_length=1,max_length=350)
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/ideas/audits')
def audit(p:Audit,s=Depends(session)):
    version(p.version_id,s['workspace'])
    if not one('SELECT id FROM blocks WHERE id=? AND version_id=? AND workspace=?',(p.block_id,p.version_id,s['workspace'])):
        raise HTTPException(404,'建议原文不存在')
    return queue(s['workspace'],'audit',p.model_dump(exclude={'idempotency_key'}),p.idempotency_key)

class AuditRevalidation(BaseModel):
    model_config={'extra':'forbid'}
    idempotency_key:str=Field(min_length=8,max_length=150)

@app.post('/api/v1/ideas/audits/{rid}/revalidate')
def revalidate_audit(rid:str,p:AuditRevalidation,s=Depends(session)):
    run_get(rid,s['workspace'])
    from .future_work import queue_revalidation
    try:
        return queue_revalidation(s['workspace'],rid,p.idempotency_key)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None

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

class ReviewerCreate(BaseModel):
    label:str=Field(min_length=1,max_length=120)
    days:int=Field(default=7,ge=1,le=90)
    workspace_id:str|None=Field(default=None,min_length=1,max_length=100)
    seed_workspace_id:str|None=Field(default=None,min_length=1,max_length=100)

@app.get('/api/v1/admin/reviewer-workspaces')
def review_workspace_choices(include_bound:bool=False,s=Depends(admin)):
    from .reviewer_accounts import available_workspaces
    return available_workspaces(include_bound=include_bound)

@app.get('/api/v1/admin/reviewers')
def list_review_accounts(s=Depends(admin)):
    from .reviewer_accounts import list_reviewers
    return list_reviewers()

@app.post('/api/v1/admin/reviewers')
def create_review_account(p:ReviewerCreate,s=Depends(admin)):
    from .reviewer_accounts import create_reviewer
    return create_reviewer(p.label,p.days,p.workspace_id,p.seed_workspace_id)

@app.post('/api/v1/admin/reviewers/{account_id}/revoke')
def revoke_review_account(account_id:str,s=Depends(admin)):
    from .reviewer_accounts import revoke_reviewer
    result=revoke_reviewer(account_id)
    if result is None:raise HTTPException(404,'评审入口不存在')
    return result

@app.get('/api/v1/admin/providers')
def providers(s=Depends(admin)):
    from .models import provider_report
    return provider_report()

@app.get('/api/v1/admin/acceptance')
def admin_acceptance(s=Depends(admin)):
    from .acceptance_report import build_acceptance_report
    return build_acceptance_report()

@app.get('/api/v1/admin/workflow')
def admin_workflow(s=Depends(admin)):
    from .workflow_report import build_workflow_report
    return build_workflow_report()

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

from . import recommendations as recommendation_api
recommendation_api.register(session)
app.include_router(recommendation_api.router)
from .text_translation import router as text_translation_router
app.include_router(text_translation_router)
from .document_workflows import router as document_workflow_router
app.include_router(document_workflow_router)
from .writing_workflows import router as writing_workflow_router
app.include_router(writing_workflow_router)

dist=ROOT/'apps/web/dist'
app.mount('/assets',PrecompressedStatic(directory=dist/'assets',immutable=True),name='assets')
app.mount('/vendor',PrecompressedStatic(directory=dist/'vendor',immutable=False),name='vendor')

@app.get('/{path:path}')
def frontend(path:str):
    if path.startswith('api/'):
        raise HTTPException(404,'未知 API')
    index=dist/'index.html'
    if not index.exists():
        return HTMLResponse('<h1>ResearchTrace API ready</h1><p>Frontend build pending. See /docs.</p>',status_code=503)
    return FileResponse(index)
