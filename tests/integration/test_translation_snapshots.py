"""Fake translation provider verifies immutable source scoping, not live quality."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from services.api import app,documents,jobs,models,snapshots,store


@pytest.fixture
def api(tmp_path,monkeypatch):
    for mod in (app,documents,store): monkeypatch.setattr(mod,'DATA',tmp_path)
    monkeypatch.setattr(app,'LOGIN_ATTEMPTS',{})
    monkeypatch.setenv('RT_ACCESS_CODE','test-fixture-only')
    monkeypatch.setenv('RT_DISABLE_DENSE','true')
    def translate(system,prompt,rid,core=False, role=None, **_):
        core = core if role is None else role != 'light'  # role-based routing
        assert core is False
        blocks=json.loads(prompt)
        return {'text':json.dumps({'translations':[{'block_id':b['block_id'],'text':'译文 '+b['text']} for b in blocks]}),'model':'FIXTURE_NO_API'}
    monkeypatch.setattr(models,'generate',translate)
    with TestClient(app.app) as c:
        c.post('/api/v1/auth/login',json={'code':'test-fixture-only'}).raise_for_status()
        f=io.BytesIO();pdf=canvas.Canvas(f);pdf.drawString(40,700,'The immutable original translation source.');pdf.save()
        u=c.post('/api/v1/documents?index_dense=false',files={'files':('source.pdf',f.getvalue())}).json()
        jobs.work_once()
        yield c,u['documents'][0]['id']


def reparse_direct(vid,w):
    q=snapshots.queue_parse(w,vid,'native','cpu','new-native-revision')
    documents.parse_document(store.one('SELECT * FROM runs WHERE id=?',(q['id'],)))
    # This test executed parsing itself so its queue entry must not rerun.
    store.execute("UPDATE runs SET status='completed' WHERE id=?",(q['id'],))
    return q['parse_id']


def test_queued_translation_and_idempotent_retry_keep_original_snapshot(api):
    c,vid=api
    w=c.get('/api/v1/auth/session').json()['workspace']
    body={'version_id':vid,'idempotency_key':'translate-before-reparse'}
    queued=c.post('/api/v1/translations',json=body);assert queued.status_code==200
    rid=queued.json()['id']
    assert json.loads(store.one('SELECT payload FROM runs WHERE id=?',(rid,))['payload'])['parse_id']==vid
    new_parse=reparse_direct(vid,w)
    retry=c.post('/api/v1/translations',json=body)
    assert retry.status_code==200 and retry.json()['id']==rid
    jobs.work_once()
    run=c.get('/api/v1/runs/'+rid).json()
    assert run['status']=='completed',run['error']
    assert run['result']['parse_id']==vid and run['result']['translated']==run['result']['total']==1
    assert not store.rows('SELECT t.* FROM translations t JOIN block_parses bp ON bp.block_id=t.block_id WHERE bp.parse_id=?',(new_parse,))
    export=c.get(f'/api/v1/translations/{vid}/export?parse_id={vid}')
    assert export.status_code==200 and '译文 The immutable original' in export.text
    current=c.get(f'/api/v1/translations/{vid}/export')
    assert '[尚未翻译]' in current.text
    assert c.get(f'/api/v1/translations/{vid}/export?parse_id=foreign').status_code==422
    # A distinct new translation counts only the new revision, not the older cache.
    nxt=c.post('/api/v1/translations',json={**body,'idempotency_key':'translate-new-revision'}).json()
    jobs.work_once()
    result=c.get('/api/v1/runs/'+nxt['id']).json()['result']
    assert result['translated']==result['total']==1 and result['parse_id']==new_parse
    assert store.one('SELECT count(*) n FROM quota')['n']==0


def test_translation_rejects_blocks_from_another_revision(api):
    c,vid=api;w=c.get('/api/v1/auth/session').json()['workspace']
    original=c.get(f'/api/v1/documents/{vid}/blocks').json()[0]['id']
    new=reparse_direct(vid,w)
    q=c.post('/api/v1/translations',json={'version_id':vid,'parse_id':new,'block_ids':[original],'idempotency_key':'reject-mixed-revision'}).json()
    jobs.work_once();run=c.get('/api/v1/runs/'+q['id']).json()
    assert run['status']=='failed' and '解析快照' in run['error']
    assert store.one('SELECT count(*) n FROM translations')['n']==0
