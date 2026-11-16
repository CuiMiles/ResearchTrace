"""Fixture model generation only: verifies live registry wiring without any provider calls."""
import io
import json
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from services.api import app,documents,jobs,models,store

@pytest.fixture
def api(tmp_path,monkeypatch):
 for mod in (app,documents,store):monkeypatch.setattr(mod,'DATA',tmp_path)
 monkeypatch.setenv('RT_ACCESS_CODE','test-only-code');monkeypatch.setenv('RT_DISABLE_DENSE','true')
 def fixture_generate(system,prompt,rid,core=True, role=None, **_):
  core = core if role is None else role != 'light'  # role-based routing
  evidence=json.loads(prompt)['evidence'];b=next(b for b in evidence if 'eight' in b['text'])
  return {'text':json.dumps({'answer':'Fixture response only','claims':[{'text':'Fixture reports eight GPUs','type':'source_fact','evidence':[{'block_id':b['id'],'quote':b['text']}]}]}),'model':'UNIT_TEST_NO_PROVIDER','usage':{}}
 monkeypatch.setattr(models,'generate',fixture_generate)
 with TestClient(app.app) as c:
  c.post('/api/v1/auth/login',json={'code':'test-only-code'});yield c

def test_agent_tools_catalog_pipeline_checkpoint_and_cancel(api):
 r=api.get('/api/v1/agent/tools');assert r.status_code==200
 assert r.json()['max_steps']==10 and len(r.json()['tools'])==11
 p=io.BytesIO();c=canvas.Canvas(p);c.drawString(40,700,'The fixture paper reports eight GPUs in training.');c.save()
 u=api.post('/api/v1/documents?index_dense=false',files={'files':('new.pdf',p.getvalue())}).json();jobs.work_once();vid=u['documents'][0]['id']
 run=api.post('/api/v1/agent/runs',json={'question':'Explain eight GPUs and graph source relationships','version_ids':[vid],'idempotency_key':'tool-wiring-new'}).json()
 jobs.work_once();result=api.get('/api/v1/runs/'+run['id']).json()
 assert result['status']=='partial',result.get('error')
 assert result['result']['claims'][0]['review']['status']=='not_checked'
 assert result['result']['answer_segments'][0]['claim_ids']==['claim-1']
 assert result['result']['model']=='UNIT_TEST_NO_PROVIDER'
 names=[s['data']['tool'] for s in result['steps'] if s['event']=='tool_finished']
 assert 'retrieve_evidence' in names and 'build_citation_graph' in names
 snap=json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?',(run['id'],))['checkpoint'])
 assert 'tool_registry' in snap and 'retrieval' in snap and 'model_response' in snap
 assert store.one('SELECT count(*) n FROM quota')['n']==0
 q=api.post('/api/v1/agent/runs',json={'question':'Queued only','version_ids':[vid],'idempotency_key':'cancel-tool-parent'}).json()
 assert api.post('/api/v1/runs/'+q['id']+'/cancel').status_code==200
 assert store.one('SELECT status FROM runs WHERE id=?',(q['id'],))['status']=='cancelled'
