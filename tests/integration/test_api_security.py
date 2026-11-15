import io
import json
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from services.api import app as module, store, documents

@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(module,'DATA',tmp_path)
    monkeypatch.setattr(documents,'DATA',tmp_path)
    monkeypatch.setenv('RT_ACCESS_CODE','fixture-reviewer')
    monkeypatch.setenv('RT_ADMIN_CODE','fixture-admin')
    with TestClient(module.app) as c:
        yield c

def pdf_bytes():
    f=io.BytesIO();p=canvas.Canvas(f);p.drawString(40,700,'Unseen fixture paper with 8 GPUs.');p.save();return f.getvalue()

def test_auth_workspace_pdf_artifact_run_isolation(api):
    assert api.get('/api/v1/documents').status_code==401
    assert api.post('/api/v1/auth/login',json={'code':'bad'}).status_code==401
    assert api.post('/api/v1/auth/login',json={'code':'fixture-reviewer'}).status_code==200
    assert api.get('/api/v1/admin/providers').status_code==403
    upload=api.post('/api/v1/documents',files={'files':('fresh.pdf',pdf_bytes(),'application/pdf')})
    assert upload.status_code==200,upload.text
    result=upload.json();vid=result['documents'][0]['id'];rid=result['runs'][0]['id']
    assert api.get(f'/api/v1/documents/{vid}/file').headers['content-type']=='application/pdf'
    first_session=api.cookies.get('rt_session')
    api.cookies.clear()
    # A supplied workspace ID cannot impersonate another workspace.
    original=api.post('/api/v1/auth/login',json={'code':'fixture-reviewer','workspace':result['documents'][0]['workspace']}).json() if 'workspace' in result['documents'][0] else api.post('/api/v1/auth/login',json={'code':'fixture-reviewer','workspace':'forged'})
    assert api.get(f'/api/v1/documents/{vid}/file').status_code==404
    assert api.get(f'/api/v1/runs/{rid}').status_code==404
    api.cookies.set('rt_session',first_session)
    # Explicitly set cookie for the test client domain to restore session.
    api.cookies.clear();api.cookies.set('rt_session',first_session,domain='testserver.local',path='/')
    assert api.delete(f'/api/v1/documents/{vid}').status_code==200
    assert api.get(f'/api/v1/documents/{vid}/file').status_code==404

def test_invalid_upload_csrf_and_admin_redaction(api):
    api.post('/api/v1/auth/login',json={'code':'fixture-admin'})
    assert api.post('/api/v1/documents',files={'files':('fake.pdf',b'not a pdf')}).status_code==422
    assert api.post('/api/v1/graphs',json={},headers={'origin':'https://evil.example'}).status_code==403
    providers=api.get('/api/v1/admin/providers')
    assert providers.status_code==200
    assert 'AIza' not in providers.text
    assert providers.json()['paid_fallback'] is False

def test_schema_and_idempotency_sse_read_does_not_queue(api):
    api.post('/api/v1/auth/login',json={'code':'fixture-reviewer'})
    u=api.post('/api/v1/documents',files={'files':('new.pdf',pdf_bytes())}).json()
    vid=u['documents'][0]['id']
    p={'question':'What hardware?','version_ids':[vid],'idempotency_key':'same-idempotency'}
    a=api.post('/api/v1/qa/runs',json=p).json();b=api.post('/api/v1/qa/runs',json=p).json()
    assert a['id']==b['id']
    api.post('/api/v1/runs/'+a['id']+'/cancel')
    stream=api.get('/api/v1/runs/'+a['id']+'/events').text
    assert 'event: done' in stream
    assert store.one("SELECT count(*) n FROM runs WHERE kind='qa'")['n']==1
    assert '/api/v1/documents' in api.get('/openapi.json').json()['paths']

def test_outline_correction_is_scoped_and_preserves_original(api,monkeypatch):
    from services.api import retrieval
    monkeypatch.setattr(retrieval,'index_dense',lambda *a:{'status':'UNIT_FIXTURE_NO_MODEL'})
    api.post('/api/v1/auth/login',json={'code':'fixture-reviewer'})
    uploaded=api.post('/api/v1/documents',files={'files':('outline.pdf',pdf_bytes())}).json()
    vid=uploaded['documents'][0]['id'];rid=uploaded['runs'][0]['id']
    documents.parse_document(store.one('SELECT * FROM runs WHERE id=?',(rid,)))
    original=store.one('SELECT id,text FROM blocks WHERE version_id=? ORDER BY reading_order',(vid,))
    out=api.patch('/api/v1/documents/'+vid,json={'outline':[{'title':'人工修正的目录','page_index':0,'block_id':None}]})
    assert out.status_code==200,out.text
    assert out.json()['metadata']['outline'][0]['block_id']==original['id']
    assert store.one('SELECT text FROM blocks WHERE id=?',(original['id'],))['text']==original['text']
    assert api.patch('/api/v1/documents/'+vid,json={'outline':[{'title':'伪造','page_index':0,'block_id':'other-workspace-block'}]}).status_code==422
    assert api.get('/api/v1/documents/'+vid+'/search',params={'q':'GPU'}).json()
