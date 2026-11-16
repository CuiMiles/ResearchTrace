"""Synthetic API migration/security checks; no provider requests."""
import io
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from services.api import app, documents, jobs, store

@pytest.fixture
def api(tmp_path,monkeypatch):
    for mod in (app,documents,store):monkeypatch.setattr(mod,'DATA',tmp_path)
    monkeypatch.setenv('RT_ACCESS_CODE','test-only-access')
    monkeypatch.setenv('RT_DISABLE_DENSE','true')
    monkeypatch.setattr(app,'LOGIN_ATTEMPTS',{})
    with TestClient(app.app) as c:
        c.post('/api/v1/auth/login',json={'code':'test-only-access'})
        yield c

def test_native_reparse_old_reader_idempotency_and_workspace(api):
    b=io.BytesIO();p=canvas.Canvas(b);p.drawString(40,700,'Snapshot evidence key HELLO42 persists in original.');p.save()
    u=api.post('/api/v1/documents?index_dense=false',files={'files':('new.pdf',b.getvalue())}).json()
    vid=u['documents'][0]['id'];jobs.work_once()
    before=api.get(f'/api/v1/documents/{vid}/pages/0').json()
    oldid=before['blocks'][0]['id']
    assert before['parse_id']==vid
    body={'engine':'native','device':'cpu','idempotency_key':'test-revision'}
    a=api.post(f'/api/v1/documents/{vid}/parses',json=body).json()
    assert api.post(f'/api/v1/documents/{vid}/parses',json=body).json()['id']==a['id']
    assert api.post(f'/api/v1/documents/{vid}/parses',json={**body,'engine':'mineru'}).status_code==422
    jobs.work_once()
    current=api.get(f'/api/v1/documents/{vid}/pages/0').json()
    assert current['parse_id']==a['parse_id'] and current['blocks'][0]['id']!=oldid
    assert api.get(f'/api/v1/documents/{vid}/pages/0?parse_id={vid}').json()==before
    found=api.get(f'/api/v1/documents/{vid}/search?q=HELLO42').json()
    assert found and all(b['parse_id']==a['parse_id'] for b in found)
    assert api.get(f'/api/v1/documents/{vid}/blocks?parse_id={vid}').json()[0]['id']==oldid
    assert api.get(f'/api/v1/documents/{vid}/pages/0?parse_id=unknown').status_code==422
    assert len(api.get(f'/api/v1/documents/{vid}/parses').json())==2
    assert store.one('SELECT count(*) n FROM quota')['n']==0
    api.cookies.clear();api.post('/api/v1/auth/login',json={'code':'test-only-access'})
    assert api.get(f'/api/v1/documents/{vid}/parses').status_code==404
    assert api.get(f'/api/v1/documents/{vid}/pages/0?parse_id={vid}').status_code==404
