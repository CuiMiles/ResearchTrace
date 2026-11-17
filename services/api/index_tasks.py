"""Durable indexing after parsing, admitted under the existing queue limits."""
import json
import os
import time

from . import models, store


def after_parse(run, version_id, parse_id):
    if os.getenv('ENABLE_DENSE','true').lower()=='false' or os.getenv('RT_DISABLE_DENSE','false').lower()=='true':
        return {'status':'disabled','notice':'语义索引已关闭；原文和关键词检索可用。'}
    selected=os.getenv('RT_EMBED_PROVIDER','gemini')
    cloud=any(bool(key) for _,key in models.credentials()) and os.getenv('RT_PROVIDER_MODE','all') in ('all','embedding_only')
    provider='gemini' if selected in ('gemini','auto') and cloud else 'local' if selected in ('local','auto') and os.getenv('RT_RETRIEVAL_BASE') else None
    if provider is None:return {'status':'unavailable','notice':'索引服务未配置或本环境未获调用权限；原文和关键词检索可用。'}
    workspace=run['workspace'];key=f'parsed-index:{version_id}:{parse_id}'
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        parent=c.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(run['id'],workspace)).fetchone()
        if not parent or parent['status']=='cancelled':return {'status':'cancelled'}
        previous=c.execute('SELECT id,status,payload FROM runs WHERE workspace=? AND idempotency=?',(workspace,key)).fetchone()
        if previous:return {'status':previous['status'],'run_id':previous['id'],'generation_id':json.loads(previous['payload'])['generation_id']}
        if c.execute("SELECT count(*) FROM runs WHERE workspace=? AND kind='index' AND status IN ('queued','running','waiting_batch')",(workspace,)).fetchone()[0]>=100:
            return {'status':'unavailable','notice':'索引等待队列已满，可稍后从文献库发起；解析原文已保存。'}
        rid,gid,now=store.uid(),store.uid(),time.time()
        payload={'version_ids':[version_id],'provider':provider,'generation_id':gid,
                 'expected_parse_id':parse_id,'auto_index':True,'parent_run_id':run['id']}
        c.execute('INSERT INTO runs(id,workspace,kind,status,payload,idempotency,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                  (rid,workspace,'index','waiting_batch',json.dumps(payload),key,now,now))
    store.event(rid,'index_waiting_admission',{'parse_run_id':run['id'],'generation_id':gid,'provider':provider,
                'notice':'解析完成可阅读；语义索引为独立持久任务，按队列预算执行。'})
    return {'status':'waiting_batch','run_id':rid,'generation_id':gid,'provider':provider}


def admit():
    admitted=[]
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        total=c.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
        for row in c.execute("SELECT id,workspace,payload FROM runs WHERE kind='index' AND status='waiting_batch' AND json_extract(payload,'$.auto_index')=1 ORDER BY created LIMIT 100").fetchall():
            p=json.loads(row['payload'])
            parent=c.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(p['parent_run_id'],row['workspace'])).fetchone()
            if not parent or parent['status']=='cancelled':
                c.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=?",(time.time(),row['id']));continue
            if parent['status']!='completed' or total>=30:continue
            count=c.execute("SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')",(row['workspace'],)).fetchone()[0]
            if count>=6:continue
            c.execute("UPDATE runs SET status='queued',updated=? WHERE id=?",(time.time(),row['id']))
            admitted.append(row['id']);total+=1
    for rid in admitted:store.event(rid,'queued',{'notice':'索引已按全局30/工作区6任务上限入队；解析任务优先。'})
    return admitted
