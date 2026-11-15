"""Real two-page MinerU cancellation/resume through HTTP, no provider requests.

Uses a self-authored raster derivative. Stops only the broker's owned job via
its cancellation route; monitors and old block hashes are retained as evidence.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from pypdf import PdfReader,PdfWriter
from services.api import store

OUT=ROOT/'evidence/ubuntu24/parser-recovery-20261116.json'
report={'status':'NOT RUN','provider_calls':0,'engine':'mineru','device':'cpu','derived_fixture':True,'official_original':False}
quota=store.rows('SELECT * FROM quota ORDER BY id')
start=time.monotonic();rid=None

def wait_for(fn,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.2)
    raise TimeoutError('Live parser recovery deadline exceeded')

def old_hash(vid):
    rows=store.rows('SELECT b.id,b.text,b.bbox FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND m.block_id IS NULL ORDER BY b.id',(vid,))
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()

try:
    source=ROOT/'.tools/parse-fixtures/scan-bilingual.pdf'
    writer=PdfWriter();page=PdfReader(source).pages[0]
    writer.add_page(page);writer.add_page(page);buf=io.BytesIO();writer.write(buf)
    data=buf.getvalue();report['input_sha256']=hashlib.sha256(data).hexdigest()
    cookie=json.loads((ROOT/'data/smoke-session.json').read_text())['cookie']
    with httpx.Client(base_url='http://127.0.0.1:18980',cookies={'rt_session':cookie},trust_env=False,timeout=30) as c:
        u=c.post('/api/v1/documents?index_dense=false',files={'files':('two-page-recovery.pdf',data)});u.raise_for_status();u=u.json();vid=u['documents'][0]['id']
        wait_for(lambda:c.get('/api/v1/runs/'+u['runs'][0]['id']).json()['status']=='completed',60)
        before=old_hash(vid)
        q=c.post(f'/api/v1/documents/{vid}/parses',json={'engine':'mineru','device':'cpu','idempotency_key':'cancel-resume-'+str(time.time_ns())});q.raise_for_status();q=q.json();rid=q['id'];pid=q['parse_id']
        report.update(version_id=vid,run_id=rid,parse_id=pid)
        # Wait for the *second* owned page runner to begin, not just UI progress.
        wait_for(lambda:store.one('SELECT parsed_pages FROM parses WHERE id=?',(pid,))['parsed_pages']==1,150)
        wait_for(lambda:len(list((ROOT/'data/parsing').glob('*/result.monitor.json')))>0,5)
        first=store.rows('SELECT * FROM blocks WHERE id IN (SELECT block_id FROM block_parses WHERE parse_id=?) ORDER BY id',(pid,))
        # A short interval lets the broker register page2 so cancellation exercises cleanup.
        time.sleep(.5)
        canceled=c.post('/api/v1/runs/'+rid+'/cancel');canceled.raise_for_status()
        immediate=c.post('/api/v1/runs/'+rid+'/resume')
        assert immediate.status_code in (200,409),immediate.status_code
        report['immediate_resume_http']=immediate.status_code
        def resume_when_released():
            r=c.post('/api/v1/runs/'+rid+'/resume')
            if r.status_code==409:return False
            r.raise_for_status();return r.json()
        if immediate.status_code==409:
            wait_for(resume_when_released,30)
        def finished():
            run=c.get('/api/v1/runs/'+rid).json()
            if run['status'] in ('failed','partial'):raise AssertionError(run.get('error') or run['status'])
            return run if run['status']=='completed' else None
        final=wait_for(finished,150)
        after=store.rows('SELECT * FROM blocks WHERE id IN (SELECT block_id FROM block_parses WHERE parse_id=?) ORDER BY id',(pid,))
        assert all(b in after for b in first),'Checkpointed first page changed after resume'
        assert old_hash(vid)==before
        assert final['result']['parsed_pages']==2
        hits=c.get(f'/api/v1/documents/{vid}/search',params={'q':'7189','parse_id':pid}).json()
        assert {b['page_index'] for b in hits}=={0,1}
        report.update(status='PASS',old_blocks_hash_before=before,old_blocks_hash_after=old_hash(vid),checkpoint_blocks=len(first),final_blocks=len(after),parsed_pages=2,final_result=final['result'])
    # Preserve only new, bounded parser monitors attributable to this test's period.
    monitors=[]
    for p in (ROOT/'data/parsing').glob('*/result.monitor.json'):
        if p.stat().st_mtime>=time.time()-(time.monotonic()-start)-1:
            d=json.loads(p.read_text());monitors.append(d)
    report['monitors']=monitors
    assert any(m.get('terminated_reason')=='Parser cancelled' for m in monitors),'No real parser cancellation monitor observed'
except Exception as exc:
    report.update(status='FAIL',error_type=type(exc).__name__,error=str(exc)[:350])
finally:
    report['elapsed_seconds']=time.monotonic()-start
    report['quota_unchanged']=quota==store.rows('SELECT * FROM quota ORDER BY id')
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='monitors'},ensure_ascii=False,indent=2))
raise SystemExit(0 if report['status']=='PASS' else 1)
