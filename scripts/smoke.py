"""Real new-input smoke. Never mocks or silently replaces upstream answers."""
import argparse
import json
import sys
import time
from pathlib import Path
import httpx
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
p=argparse.ArgumentParser()
p.add_argument('--live',action='store_true')
p.add_argument('--max-hydrogen-calls',type=int,default=4)
p.add_argument('--pdf',default='evals/files/b90f732e.pdf')
p.add_argument('--question',default='What beta1 and beta2 optimizer values, GPU hardware/count, and training time are reported? Distinguish base and big models and provide exact source quotations.')
args=p.parse_args()
if not args.live:
    raise SystemExit('NOT RUN: add --live to authorize real API calls within configured project budget.')
if not 1<=args.max_hydrogen_calls<=4:
    raise SystemExit('Initial live smoke accepts1–4calls total. Separate quality evaluation requires a separate explicit budget.')
values=dotenv_values(root/'.env')
if not values.get('GEMINI_API_KEY'):
    raise SystemExit('BLOCKED: no server-side model credential configured.')
session_path=root/'data/smoke-session.json'
session=json.loads(session_path.read_text()) if session_path.exists() else {}
with httpx.Client(base_url='http://127.0.0.1:'+values.get('RT_PORT','18970'),trust_env=False,timeout=90,cookies={'rt_session':session.get('cookie','')}) as c:
    if c.get('/api/v1/auth/session').status_code!=200:
        auth=c.post('/api/v1/auth/login',json={'code':values['RT_ADMIN_CODE']});auth.raise_for_status()
        session={'cookie':c.cookies.get('rt_session'),'workspace':auth.json()['workspace']}
        session_path.write_text(json.dumps(session));session_path.chmod(0o600)
    report=c.get('/api/v1/admin/providers');report.raise_for_status()
    if report.json()['hydrogen_total_used']>=args.max_hydrogen_calls:
        raise SystemExit('BLOCKED: explicit Hydrogen smoke limit reached; no request sent.')
    path=root/args.pdf
    upload=c.post('/api/v1/documents',files={'files':('unseen-renamed.pdf',path.read_bytes(),'application/pdf')});upload.raise_for_status()
    vid=upload.json()['documents'][0]['id']
    for _ in range(900):
        state=c.get('/api/v1/documents/'+vid+'/status').json()
        if state['parsed_pages']==state['page_count']:
            break
        time.sleep(1)
    else:
        raise SystemExit('FAIL: parsing did not complete within15minutes.')
    from hashlib import sha256
    idem='smoke-'+sha256((vid+args.question).encode()).hexdigest()[:40]
    run=c.post('/api/v1/qa/runs',json={'question':args.question,'version_ids':[vid],'idempotency_key':idem});run.raise_for_status()
    rid=run.json()['id']
    for _ in range(1200):
        result=c.get('/api/v1/runs/'+rid).json()
        if result['status'] not in ('queued','running'):
            break
        time.sleep(1)
    out=root/'evidence/smoke_latest.json'
    out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print('Run:',rid,'status:',result['status'],'reused:',run.json().get('reused',False),'evidence:',out)
    if result['status']!='completed':
        raise SystemExit('FAIL: '+str(result.get('error')))
    print('Actual model:',result['result'].get('model'),'usage:',result['result'].get('usage'))
