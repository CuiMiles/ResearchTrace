"""Real HTTP ingest -> parser revision -> FTS -> exact source coordinates, no LLM calls."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from services.api import store
p=argparse.ArgumentParser();p.add_argument('--engine',choices=['paddleocr','mineru'],required=True);p.add_argument('--device',choices=['cpu','gpu'],default='cpu');p.add_argument('--file',required=True);p.add_argument('--query',default='7189');p.add_argument('--base',default='http://127.0.0.1:18980');args=p.parse_args()
report={'engine':args.engine,'device':args.device,'model_requests':0,'input_file':args.file,'input_sha256':hashlib.sha256(Path(args.file).read_bytes()).hexdigest()}
report_path=ROOT/f'evidence/ubuntu24/{args.engine}-{args.device}-product.json'
quota_before=store.rows('SELECT model,count(*) n FROM quota GROUP BY model')
cookie=json.loads((ROOT/'data/smoke-session.json').read_text())['cookie']

def wait(c,rid):
 for _ in range(4600):
  r=c.get('/api/v1/runs/'+rid);r.raise_for_status();run=r.json()
  if run['status'] not in ('queued','running'):return run
  time.sleep(.25)
 raise TimeoutError('Persistent parser run did not finish within test deadline')

try:
 with httpx.Client(base_url=args.base,trust_env=False,timeout=30,cookies={'rt_session':cookie}) as c:
  upload=c.post('/api/v1/documents?index_dense=false',files={'files':(Path(args.file).name,Path(args.file).read_bytes(),'application/pdf')});upload.raise_for_status();u=upload.json();vid=u['documents'][0]['id']
  if u['runs']:wait(c,u['runs'][0]['id'])
  report['version_id']=vid
  old=c.get(f'/api/v1/documents/{vid}/blocks?limit=500').json()
  q=c.post(f'/api/v1/documents/{vid}/parses',json={'engine':args.engine,'device':args.device,'idempotency_key':'live-parser-'+str(time.time_ns())});q.raise_for_status();job=q.json();report.update(run_id=job['id'],parse_id=job['parse_id'])
  started=time.monotonic();run=wait(c,job['id']);report['elapsed_seconds']=time.monotonic()-started
  report['run_status']=run['status'];report['error']=run.get('error');report['result']=run.get('result')
  if run['status']!='completed':
   report['status']='BLOCKED' if 'GPU accounting unavailable' in (run.get('error') or '') or 'WSL' in (run.get('error') or '') else 'FAIL'
  else:
   blocks=c.get(f'/api/v1/documents/{vid}/blocks?limit=500').json();assert blocks and all(b['source']==args.engine for b in blocks)
   assert all(b['parse_id']==job['parse_id'] for b in blocks)
   hits=c.get(f'/api/v1/documents/{vid}/search',params={'q':args.query}).json();assert hits, 'Query did not return OCR source evidence'
   chosen=hits[0];page=c.get(f'/api/v1/documents/{vid}/pages/{chosen["page_index"]}').json();assert any(b['id']==chosen['id'] for b in page['blocks'])
   report.update(status='PASS',blocks=blocks,query=args.query,located_block=chosen['id'],page_index=chosen['page_index'],bbox=chosen['bbox'])
  for b in old:
   current=store.one('SELECT text,bbox FROM blocks WHERE id=?',(b['id'],));assert current and current['text']==b['text'] and json.loads(current['bbox'])==b['bbox']
  report['prior_blocks_unchanged']=True
except Exception as exc:
 report['status']='FAIL';report['error_type']=type(exc).__name__;report['error']=str(exc)[:300]
finally:
 report['quota_unchanged']=quota_before==store.rows('SELECT model,count(*) n FROM quota GROUP BY model')
 report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='blocks'},ensure_ascii=False,indent=2))
raise SystemExit(0 if report['status']=='PASS' else 1)
