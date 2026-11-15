"""Real local HTTP parser revision acceptance; explicitly spends no provider quota."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from services.api import store

base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18980'
out=ROOT/'evidence/ubuntu24';out.mkdir(parents=True,exist_ok=True)
report={'base':base,'cases':[],'model_requests':0}

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def wait(c,rid):
    for _ in range(600):
        r=c.get('/api/v1/runs/'+rid);r.raise_for_status();run=r.json()
        if run['status'] not in ('queued','running'):
            assert run['status']=='completed',run.get('error')
            return run
        time.sleep(.2)
    raise TimeoutError('parse did not finish')

quota_before=store.rows('SELECT model,count(*) n,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens FROM quota GROUP BY model')
session=json.loads((ROOT/'data/smoke-session.json').read_text())
with httpx.Client(base_url=base,trust_env=False,timeout=30,cookies={'rt_session':session['cookie']}) as c:
    versions=c.get('/api/v1/documents');versions.raise_for_status()
    v=next(v for v in versions.json() if v['status']=='ready' and v['page_count']<=16)
    vid=v['id'];snapshots=c.get(f'/api/v1/documents/{vid}/parses').json();old=next(p for p in snapshots if p['active'])['id']
    original=c.get(f'/api/v1/documents/{vid}/blocks?parse_id={old}&limit=500').json()
    result=c.post(f'/api/v1/documents/{vid}/parses',json={'engine':'native','device':'cpu','idempotency_key':'native-live-'+str(time.time_ns())});result.raise_for_status();job=result.json()
    wait(c,job['id'])
    after=c.get(f'/api/v1/documents/{vid}/blocks?parse_id={old}&limit=500').json()
    assert original==after
    active=c.get(f'/api/v1/documents/{vid}/parses').json()
    assert next(p for p in active if p['active'])['id']==job['parse_id']
    assert c.get(f'/api/v1/documents/{vid}/pages/0?parse_id={old}').json()['parse_id']==old
    report['cases'].append({'case':'native immutable revision via HTTP','status':'PASS','version_id':vid,'source_sha256':v['sha256'],'old_parse':old,'new_parse':job['parse_id'],'old_blocks_hash_before':digest(original),'old_blocks_hash_after':digest(after),'old_block_count':len(original),'run_id':job['id']})
    pdf=ROOT/'evals/files/unseen_authored.pdf'
    r=c.post('/api/v1/documents?index_dense=false',files={'files':('new-ubuntu24-measurement.pdf',pdf.read_bytes(),'application/pdf')});r.raise_for_status();u=r.json();nv=u['documents'][0]['id']
    wait(c,u['runs'][0]['id'])
    hits=c.get(f'/api/v1/documents/{nv}/search?q=records').json();assert hits
    page=c.get(f'/api/v1/documents/{nv}/pages/{hits[0]["page_index"]}').json();assert any(b['id']==hits[0]['id'] for b in page['blocks'])
    report['cases'].append({'case':'new self-authored PDF import search source location without dense spend','status':'PASS','source_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'official_original':False,'version_id':nv,'located_block':hits[0]['id'],'physical_page_index':hits[0]['page_index']})
    invalid=c.post('/api/v1/documents?index_dense=false',files={'files':('broken.pdf',b'%PDF-broken','application/pdf')})
    assert invalid.status_code==422
    report['cases'].append({'case':'new damaged input','status':'PASS','observed_http_status':invalid.status_code})
quota_after=store.rows('SELECT model,count(*) n,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens FROM quota GROUP BY model')
assert quota_before==quota_after
report['quota_before']=quota_before;report['quota_after']=quota_after
(out/'live-native-snapshots.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
