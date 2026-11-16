"""Wake scoped parent tasks only after their persisted children finish."""
import json
import time
from . import store

PENDING=('queued','running','waiting_batch','waiting_children')


def child_statuses(workspace,ids):
    result=[]
    for rid in list(dict.fromkeys(ids))[:10]:
        row=store.one('SELECT id,status,kind,result,error FROM runs WHERE id=? AND workspace=?',(rid,workspace))
        result.append(row or {'id':rid,'status':'missing','error':'子任务已不存在或不可访问'})
    return result


def cancel_owned_children(workspace,parent):
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(parent,workspace)).fetchone()
        if not row or row['status']!='cancelled':return
        conn.execute("UPDATE runs SET status='cancelled',updated=? WHERE workspace=? AND json_extract(payload,'$.parent_run_id')=? AND status IN ('queued','running','waiting_children','waiting_batch')",(time.time(),workspace,parent))


def wake_dependencies():
    awakened=[]
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        active=conn.execute("SELECT count(*) n FROM runs WHERE status IN ('queued','running')").fetchone()['n']
        if active>=30:return awakened
        for row in conn.execute("SELECT id,workspace,checkpoint FROM runs WHERE status='waiting_children' ORDER BY created LIMIT 100").fetchall():
            snap=json.loads(row['checkpoint'] or '{}')
            children=snap.get('waiting_children',[])[:10]
            if not children:continue
            states=[conn.execute('SELECT status FROM runs WHERE id=? AND workspace=?',(rid,row['workspace'])).fetchone() for rid in children]
            if any(child and child['status'] in PENDING for child in states):continue
            count=conn.execute("SELECT count(*) n FROM runs WHERE workspace=? AND status IN ('queued','running')",(row['workspace'],)).fetchone()['n']
            if count>=6:continue
            conn.execute("UPDATE runs SET status='queued',updated=? WHERE id=? AND status='waiting_children'",(time.time(),row['id']))
            awakened.append(row['id']);active+=1
            if active>=30:break
    return awakened
