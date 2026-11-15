"""Immutable parser revisions. Publication only switches the current index scope."""
import json
import time

from .store import db, event, one, rows, uid


def ensure_legacy(version):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO parses(id,version_id,workspace,engine,device,status,parsed_pages,page_count,created) VALUES(?,?,?,'native','cpu',?,?,?,?)",
                  (version['id'],version['id'],version['workspace'],version['status'],version['parsed_pages'],version['page_count'],version['created']))
        c.execute('INSERT OR IGNORE INTO active_parses VALUES(?,?)',(version['id'],version['id']))


def selected_parse(workspace,version_id,parse_id=None):
    v=one('SELECT * FROM versions WHERE workspace=? AND id=? AND deleted=0',(workspace,version_id))
    if not v:
        raise ValueError('文档不存在或无权限')
    ensure_legacy(v)
    parse_id=parse_id or one('SELECT parse_id FROM active_parses WHERE version_id=?',(version_id,))['parse_id']
    p=one('SELECT * FROM parses WHERE id=? AND version_id=? AND workspace=?',(parse_id,version_id,workspace))
    if not p:
        raise ValueError('解析快照不存在或无权限')
    return p


def list_parses(workspace,version_id):
    selected_parse(workspace,version_id)
    result=rows('SELECT p.*,p.id=a.parse_id AS active FROM parses p JOIN active_parses a ON a.version_id=p.version_id WHERE p.workspace=? AND p.version_id=? ORDER BY p.created DESC',(workspace,version_id))
    for p in result:
        p['active']=bool(p['active']);p['provenance']=json.loads(p['provenance'])
    return result


def queue_parse(workspace,version_id,engine,device,idempotency):
    selected_parse(workspace,version_id)
    if engine not in ('native','paddleocr','paddleocr_vl','mineru') or device not in ('cpu','gpu') or engine!='mineru' and device!='cpu':
        raise ValueError('不支持的解析器或设备组合')
    if not idempotency or len(idempotency)>200:
        raise ValueError('需要有效幂等键')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM runs WHERE workspace=? AND idempotency=?',(workspace,idempotency)).fetchone()
        if old:
            payload=json.loads(old['payload'])
            if old['kind']!='reparse' or any(payload.get(k)!=v for k,v in {'version_id':version_id,'engine':engine,'device':device}.items()):
                raise ValueError('幂等键已用于不同请求')
            return {'id':old['id'],'run_id':old['id'],'parse_id':payload['parse_id'],'status':old['status'],'reused':True}
        if c.execute("SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')",(workspace,)).fetchone()[0]>=6 or c.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]>=30:
            raise ValueError('队列已满，请等待或取消已有任务')
        v=c.execute('SELECT page_count FROM versions WHERE id=?',(version_id,)).fetchone()
        rid,pid,now=uid(),uid(),time.time()
        payload={'version_id':version_id,'parse_id':pid,'engine':engine,'device':device}
        c.execute('INSERT INTO parses(id,version_id,workspace,engine,device,status,page_count,created) VALUES(?,?,?,?,?,?,?,?)',(pid,version_id,workspace,engine,device,'queued',v['page_count'],now))
        c.execute('INSERT INTO runs(id,workspace,kind,status,payload,idempotency,created,updated) VALUES(?,?,?,?,?,?,?,?)',(rid,workspace,'reparse','queued',json.dumps(payload),idempotency,now,now))
    event(rid,'queued',{'tool':'parse_document','parse_id':pid,'engine':engine,'device':device})
    return {'id':rid,'run_id':rid,'parse_id':pid,'status':'queued'}


def snapshot_blocks(workspace,version_id,parse_id,page_index=None,offset=0,limit=None):
    p=selected_parse(workspace,version_id,parse_id)
    sql='SELECT b.*,COALESCE(m.parse_id,b.version_id) AS parse_id FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.workspace=? AND b.version_id=? AND COALESCE(m.parse_id,b.version_id)=?'
    args=[workspace,version_id,p['id']]
    if page_index is not None:
        sql+=' AND b.page_index=?';args.append(page_index)
    sql+=' ORDER BY b.page_index,b.reading_order'
    if limit is not None:
        sql+=' LIMIT ? OFFSET ?';args.extend([limit,offset])
    return rows(sql,args)



def block_parse(block_id,version_id):
    p=one('SELECT parse_id FROM block_parses WHERE block_id=?',(block_id,))
    return p['parse_id'] if p else version_id
