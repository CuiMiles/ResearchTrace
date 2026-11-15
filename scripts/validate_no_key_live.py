"""Spawn only project-owned isolated no-key API+worker; never alter production .env."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import httpx
from services.parsing.guard import stop_session
out=ROOT/'evidence/ubuntu24';data=ROOT/'data'/('no-key-'+str(time.time_ns()));data.mkdir(mode=0o700)
s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
env=dict(os.environ,RT_HOST='127.0.0.1',RT_PORT=str(port),RT_DATA_DIR=str(data),RT_ACCESS_CODE='isolated-no-key-fixture',RT_ADMIN_CODE='isolated-admin-fixture',GEMINI_API_KEY='',GEMINI_API_KEY2='',RT_DISABLE_DENSE='true',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
for k in list(env):
 if ('API_KEY' in k or 'TOKEN' in k) and k not in ('GEMINI_API_KEY','GEMINI_API_KEY2'):env.pop(k,None)
report={'status':'NOT RUN','provider_calls':0,'data_directory':str(data.relative_to(ROOT)),'port':port};procs=[];logs=[]
try:
 for name,module in [('api','services.api.serve'),('worker','services.worker.main')]:
  f=(data/(name+'.log')).open('wb');logs.append(f)
  procs.append(subprocess.Popen([sys.executable,'-m',module],cwd=ROOT,env=env,stdout=f,stderr=f,start_new_session=True))
 with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=15) as c:
  for _ in range(60):
   try:
    if c.get('/healthz').status_code==200:break
   except httpx.ConnectError:pass
   time.sleep(.1)
  else:raise TimeoutError('isolated API startup')
  c.post('/api/v1/auth/login',json={'code':env['RT_ACCESS_CODE']}).raise_for_status()
  caps=c.get('/api/v1/capabilities');caps.raise_for_status();assert not caps.json()['model_configured']
  r=c.post('/api/v1/documents?index_dense=false',files={'files':('fresh-no-key.pdf',(ROOT/'evals/files/unseen_authored.pdf').read_bytes())});r.raise_for_status();u=r.json();vid=u['documents'][0]['id'];rid=u['runs'][0]['id']
  for _ in range(200):
   run=c.get('/api/v1/runs/'+rid).json()
   if run['status'] not in ('queued','running'):break
   time.sleep(.1)
  assert run['status']=='completed',run.get('error')
  assert c.get('/api/v1/documents/'+vid+'/file').status_code==200
  hits=c.get('/api/v1/documents/'+vid+'/search?q=records').json();assert hits
  assert c.get('/api/v1/documents/'+vid+'/pages/0').json()['blocks']
  chart=c.post('/api/v1/charts',files={'file':('fresh.csv',b'epoch,loss\n1,3\n2,2\n3,1\n')},data={'spec':json.dumps({'kind':'line','x':'epoch','y':['loss']})});chart.raise_for_status()
  report.update(status='PASS',checks=['fresh API and worker with blank provider keys','no-key capabilities explicit','new PDF parse and sparse index','authenticated PDF reading and page blocks','local source search','actual CSV chart'],capabilities=caps.json(),run_id=rid,version_id=vid)
 import sqlite3
 with sqlite3.connect(data/'researchtrace.sqlite') as db:assert db.execute('SELECT count(*) FROM quota').fetchone()[0]==0
except Exception as e:report.update(status='FAIL',error_type=type(e).__name__,error=str(e)[:250])
finally:
 for proc in procs:stop_session(proc)
 for f in logs:f.close()
 report['test_processes_reaped']=all(p.poll() is not None for p in procs)
 (out/'no-key-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False));raise SystemExit(0 if report['status']=='PASS' else 1)
