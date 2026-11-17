"""A parsed upload remains usable while its separately owned index is queued."""
import io
import json

import httpx
import pytest
from reportlab.pdfgen import canvas

from services.api import documents, index_tasks, jobs, models, store


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    store.migrate()
    monkeypatch.setenv('GEMINI_API_KEY', 'controlled-offline-fixture')
    monkeypatch.setenv('RT_PROVIDER_MODE', 'all')
    monkeypatch.setenv('RT_EMBED_PROVIDER', 'gemini')
    store.execute('INSERT INTO workspaces VALUES(?,?,?)', ('w', 'Queue fixture', 1))
    calls = []

    def embed(texts, rid, task='RETRIEVAL_DOCUMENT'):
        calls.append((rid, len(texts)))
        return {'vectors': [[1.0]+[0.0]*767 for _ in texts], 'model': models.EMBED, 'dimension': 768}

    monkeypatch.setattr(models, 'embed', embed)
    monkeypatch.setattr(models, 'client', lambda: pytest.fail('Unexpected live request'))
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(30, 700, 'An unseen experiment trained with eight GPUs and retained source evidence.')
    pdf.save()
    uploaded = documents.upload_document('w', 'fresh-upload.pdf', buf.getvalue())
    return uploaded, calls


def parse(corpus):
    upload, calls = corpus
    assert jobs.work_once(pool='documents')
    parent = store.one('SELECT * FROM runs WHERE id=?', (upload['run_id'],))
    assert parent['status'] == 'completed'
    child = json.loads(parent['result'])['dense_index']
    return parent, child, calls


def test_new_upload_finishes_parse_before_index_then_indexes_once(corpus):
    parent, child, calls = parse(corpus)
    assert child['status'] == 'waiting_batch' and calls == []
    vid = json.loads(parent['payload'])['version_id']
    before = store.rows('SELECT id,text,bbox FROM current_blocks WHERE version_id=?', (vid,))
    assert store.one('SELECT status FROM versions WHERE id=?', (vid,))['status'] == 'ready'
    assert jobs.work_once(pool='documents')
    assert store.one('SELECT status FROM runs WHERE id=?', (child['run_id'],))['status'] == 'completed'
    assert calls == [(child['run_id'], 1)]
    from services.api.app import index_status_map
    assert index_status_map('w')[vid]['semantic_ready']
    assert store.rows('SELECT id,text,bbox FROM current_blocks WHERE version_id=?', (vid,)) == before
    again = index_tasks.after_parse(parent, vid, json.loads(parent['result'])['parse_id'])
    assert again['run_id'] == child['run_id'] and len(calls) == 1
    assert not jobs.work_once(pool='documents')


@pytest.mark.parametrize('limit', ['workspace', 'global'])
def test_admission_obeys_existing_queue_caps_without_losing_index(corpus, limit):
    parent, child, calls = parse(corpus)
    count = 6 if limit == 'workspace' else 30
    with store.db() as c:
        for i in range(count):
            c.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                      (f'busy-{i}', 'w' if limit == 'workspace' else f'other-{i}', 'qa', 'queued', '{}', 1, 1))
    assert index_tasks.admit() == [] and calls == []
    assert store.one('SELECT status FROM runs WHERE id=?', (child['run_id'],))['status'] == 'waiting_batch'
    store.execute("UPDATE runs SET status='completed' WHERE id='busy-0'")
    assert index_tasks.admit() == [child['run_id']]
    assert calls == []


def test_parent_cancellation_cancels_only_its_pending_index(corpus):
    parent, child, calls = parse(corpus)
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (parent['id'],))
    assert index_tasks.admit() == []
    assert store.one('SELECT status FROM runs WHERE id=?', (child['run_id'],))['status'] == 'cancelled'
    assert calls == []


def test_changed_parse_refuses_before_any_embedding(corpus):
    parent, child, calls = parse(corpus)
    vid = json.loads(parent['payload'])['version_id']
    store.execute('UPDATE active_parses SET parse_id=? WHERE version_id=?', ('different-parse', vid))
    assert jobs.work_once(pool='documents')
    task = store.one('SELECT status,error FROM runs WHERE id=?', (child['run_id'],))
    assert task['status'] == 'failed' and '快照已切换' in task['error']
    assert calls == [] and store.one('SELECT status FROM versions WHERE id=?', (vid,))['status'] == 'ready'


def test_exhausted_embedding_waits_for_real_reset_without_replay(corpus, monkeypatch):
    parent, child, calls = parse(corpus)
    original=models.embed

    def exhausted(*a, **kw):
        raise models.QuotaRefusal('Fixture daily exhausted', scope='global', code='model_daily')

    monkeypatch.setattr(models, 'embed', exhausted)
    assert jobs.work_once(pool='documents')
    pending=store.one('SELECT status,checkpoint FROM runs WHERE id=?', (child['run_id'],))
    assert pending['status'] == 'queued'
    resume_at=json.loads(pending['checkpoint'])['index_resume_after']
    assert not jobs.work_once(pool='documents') and calls==[]
    assert store.one('SELECT status FROM runs WHERE id=?', (parent['id'],))['status'] == 'completed'
    vid = json.loads(parent['payload'])['version_id']
    assert store.one('SELECT status FROM versions WHERE id=?', (vid,))['status'] == 'ready'
    from services.api.app import index_status_map
    status = index_status_map('w')[vid]
    assert not status['semantic_ready'] and status['status'] == 'queued'
    assert not store.rows('SELECT * FROM quota')
    monkeypatch.setattr(models,'embed',original)
    monkeypatch.setattr(jobs.time,'time',lambda:resume_at+1)
    assert jobs.work_once(pool='documents')
    assert store.one('SELECT status FROM runs WHERE id=?',(child['run_id'],))['status']=='completed'
    assert calls==[(child['run_id'],1)]


def test_token_metadata_cannot_clear_inference_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    monkeypatch.setenv('GEMINI_API_KEY', 'controlled-offline-fixture')
    project = models.credentials()[0][0]
    store.execute('INSERT INTO provider_state VALUES(?,?,?,?,?)', (project, models.EMBED, 'failed', 'HTTP 429 RESOURCE_EXHAUSTED', 1))
    monkeypatch.setattr(models, 'client', lambda: httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'totalTokens': 1200})), trust_env=False))
    result, _ = models.request(models.EMBED, 'countTokens', {'contents': [{'role': 'user', 'parts': [{'text': 'fixture'}]}]}, None, 0)
    assert result['totalTokens'] == 1200
    assert store.one('SELECT status FROM provider_state WHERE project=? AND model=?', (project, models.EMBED))['status'] == 'failed'
    assert store.one('SELECT status FROM provider_state WHERE project=? AND model=?', (project, models.EMBED+':countTokens'))['status'] == 'ok'
    assert store.one('SELECT units FROM quota_request_units')['units'] == 0
