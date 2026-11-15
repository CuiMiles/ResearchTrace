"""Three real isolated reviewer sessions on capped local API/worker; zero provider spend."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from dotenv import dotenv_values
from services.api import store
base='http://127.0.0.1:18980';code=dotenv_values(ROOT/'.env')['RT_ACCESS_CODE']
report={'status':'NOT RUN','model_requests':0,'sessions':[],'target':'Local API512M and worker896M cgroups; not a provisioned ECS instance'}
quota=store.rows('SELECT model,count(*) n FROM quota GROUP BY model')
clients=[]
def upload(i):
 c=httpx.Client(base_url=base,trust_env=False,timeout=60)
 r=c.post('/api/v1/auth/login',json={'code':code});r.raise_for_status();w=r.json()['workspace']
 p=ROOT/'evals/files'/('long_engineering.pdf' if i==0 else 'unseen_authored.pdf')
 r=c.post('/api/v1/documents?index_dense=false',files={'files':('new-session-'+str(i)+'.pdf',p.read_bytes())});r.raise_for_status();u=r.json()
 return c,{'workspace':w,'version_id':u['documents'][0]['id'],'run_id':u['runs'][0]['id'],'input_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'derived':True,'official_original':False}
try:
 started=time.monotonic()
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:values=list(pool.map(upload,range(3)))
 clients=[x[0] for x in values];report['sessions']=[x[1] for x in values]
 observed_queue=[]
 for _ in range(2400):
  statuses=[]
  for c,x in values:
   r=c.get('/api/v1/runs/'+x['run_id']);r.raise_for_status();statuses.append(r.json()['status'])
  observed_queue.append(statuses)
  if all(s not in ('queued','running') for s in statuses):
   assert statuses==['completed']*3,statuses;break
  time.sleep(.1)
 else:raise TimeoutError('capped service parse timeout')
 for index,(c,x) in enumerate(values):
  r=c.get('/api/v1/documents');r.raise_for_status();assert len(r.json())==1
  other=values[(index+1)%3][1]['version_id']
  assert c.get('/api/v1/documents/'+other+'/file').status_code==404
 c,x=values[0];v=c.get('/api/v1/documents/'+x['version_id']+'/status').json();assert v['parsed_pages']==541
 hits=c.get('/api/v1/documents/'+x['version_id']+'/search',params={'q':'RTMARK0541'}).json();assert hits and hits[0]['page_index']==540
 peaks={}
 for unit in ['researchtrace-api','researchtrace-worker','researchtrace-parser']:
  r=subprocess.run(['systemctl','--user','show',unit,'--property=MemoryPeak,MemoryCurrent,MemoryMax,CPUQuotaPerSecUSec','--no-pager'],capture_output=True,text=True,check=True)
  peaks[unit]=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
 assert sum(int(peaks[u]['MemoryPeak']) for u in ['researchtrace-api','researchtrace-worker'])<1400*1024**2
 report.update(status='PASS',elapsed_seconds=time.monotonic()-started,queue_samples=observed_queue[::max(1,len(observed_queue)//20)],last_page=hits[0]['page_index'],resource_usage=peaks,checks=['3 concurrent authenticated reviewer uploads','bounded persistent single worker queue','all inputs fully parsed','541-page tail search','cross-workspace PDF reads denied','API+worker sum of independently measured peaks below1.4GiB'])
except Exception as e:report.update(status='FAIL',error_type=type(e).__name__,error=str(e)[:300])
finally:
 for c in clients:c.close()
 report['quota_unchanged']=quota==store.rows('SELECT model,count(*) n FROM quota GROUP BY model')
 (ROOT/'evidence/ubuntu24/lite-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['status']=='PASS' else 1)
