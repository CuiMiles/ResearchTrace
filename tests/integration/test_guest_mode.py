"""Guest access: isolated seeded spaces, light models only, capped and expiring.

No provider is contacted: model calls are replaced by recorders and the quota
ledger rows are written directly where a cap must be reached.
"""
import io
import time

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from services.api import documents, guest_mode, index_generations as idx, jobs, models, store
from services.api.embedding_providers import GeminiRetrievalProvider


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    store.migrate()
    with store.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,workspace TEXT NOT NULL,role TEXT NOT NULL,expires REAL NOT NULL)')
    store.execute('INSERT INTO workspaces VALUES(?,?,?)', ('template', 'Guest template', 1))
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(30, 700, 'We scale the dot products by one over the square root of dk.')
    pdf.save()
    upload = documents.upload_document('template', 'guest.pdf', buf.getvalue(), index_dense=False)
    jobs.work_once(pool='documents')

    def embed(texts, rid, task='RETRIEVAL_DOCUMENT'):
        return {'vectors': [[1.0] + [0.0] * 767 for _ in texts], 'model': 'gemini-embedding-001', 'dimension': 768}

    monkeypatch.setattr(models, 'embed', embed)
    idx.build('template', [upload['document']['id']], provider=GeminiRetrievalProvider())
    # A second, non-cloud generation in the template must not reach guests.
    with store.db() as c:
        c.execute('''INSERT INTO index_generations(id,workspace,model_id,revision,fingerprint,manifest,status,dimension,created)
                     VALUES('local-gen','template','nvidia/local-embed','r','f','{}','ready',4096,1)''')
    monkeypatch.setenv('RT_GUEST_MODE', 'true')
    monkeypatch.setenv('RT_GUEST_SEED_WORKSPACE', 'template')
    monkeypatch.setenv('RT_GUEST_MODEL_CHAIN', 'gemini-3.5-flash-lite')
    monkeypatch.setenv('RT_GUEST_DAILY_CALLS', '2')
    monkeypatch.setenv('RT_GUEST_GLOBAL_DAILY_CALLS', '3')
    monkeypatch.setenv('RT_MODEL_DEEP', 'gemini-4-hydrogen')
    return upload['document']['id']


def client():
    from services.api import app as api
    api.LOGIN_ATTEMPTS.clear()  # other tests' logins share this in-memory limiter
    return TestClient(api.app)


def guest_run(workspace, rid=None):
    rid = rid or store.uid()
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                  (rid, workspace, 'qa', 'running', '{}', time.time(), time.time()))
    return rid


def quota_row(rid, model='gemini-3.5-flash-lite'):
    store.execute('INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,output_tokens,status) VALUES(?,?,?,?,?,?,?,?,?)',
                  (store.uid(), 'p1', model, models.quota_day(), rid, time.time(), 10, 0, 'ok'))


def test_entrance_closed_by_default(seeded, monkeypatch):
    monkeypatch.setenv('RT_GUEST_MODE', 'false')
    with client() as http:
        assert http.get('/api/v1/auth/guest').json() == {'enabled': False}
        assert http.post('/api/v1/auth/guest').status_code == 404


def test_guest_gets_isolated_seed_with_cloud_index_only(seeded):
    with client() as http:
        info = http.get('/api/v1/auth/guest').json()
        assert info['enabled'] and info['models'] == ['gemini-3.5-flash-lite'] and info['daily_calls'] == 2
        created = http.post('/api/v1/auth/guest')
        assert created.status_code == 200 and created.json()['role'] == 'guest'
        workspace = created.json()['workspace']
        assert workspace != 'template'
        docs = http.get('/api/v1/documents').json()
        assert len(docs) == 1 and docs[0]['id'] != seeded
        models_copied = {r['model_id'] for r in store.rows('SELECT model_id FROM index_generations WHERE workspace=?', (workspace,))}
        assert models_copied == {'gemini-embedding-001'}
        status = http.get('/api/v1/guest/status').json()
        assert status['guest'] and status['remaining_calls'] == 2 and status['seeded_documents'] == 1
        caps = http.get('/api/v1/capabilities').json()
        assert caps['guest'] and caps['core_model'] == 'gemini-3.5-flash-lite'
        # Index administration stays with reviewers.
        assert http.post('/api/v1/indices/runs', json={'version_ids': [docs[0]['id']]}).status_code in (403, 422)
    assert store.rows('SELECT * FROM quota') == []


def test_guest_runs_use_only_the_guest_chain(seeded, monkeypatch):
    workspace, _ = guest_mode.create('client-a')
    rid = guest_run(workspace)
    asked = []

    def once(model, system, prompt, run_id, json_output=True, response_schema=None):
        asked.append(model)
        return {'text': '{}', 'model': model}

    monkeypatch.setattr(models, '_generate_once', once)
    models.generate('s', 'p', rid, role='deep')
    models.generate('s', 'p', rid, role='verify')
    assert asked == ['gemini-3.5-flash-lite', 'gemini-3.5-flash-lite']
    with pytest.raises(models.QuotaRefusal) as refused:
        models.reserve('p1', models.CORE, 10, rid)
    assert refused.value.code == 'guest_model'


def test_guest_daily_and_shared_caps_count_every_call(seeded):
    first, _ = guest_mode.create('client-a')
    second, _ = guest_mode.create('client-b')
    rid = guest_run(first)
    quota_row(rid)
    quota_row(rid)
    with pytest.raises(models.QuotaRefusal) as own:
        models.reserve('p1', 'gemini-3.5-flash-lite', 10, rid)
    assert own.value.code == 'guest_daily'
    other = guest_run(second)
    quota_row(other)
    with pytest.raises(models.QuotaRefusal) as shared:
        models.reserve('p1', 'gemini-3.5-flash-lite', 10, other)
    assert shared.value.code == 'guest_global'
    assert guest_mode.status(second)['remaining_calls'] == 0


def test_guest_creation_is_rate_limited_per_client(seeded):
    for _ in range(3):
        guest_mode.create('same-client')
    with pytest.raises(guest_mode.GuestRefused) as refused:
        guest_mode.create('same-client')
    assert refused.value.status == 429


def test_guest_upload_cap_counts_only_own_papers(seeded, monkeypatch):
    monkeypatch.setenv('RT_GUEST_MAX_DOCUMENTS', '1')
    workspace, _ = guest_mode.create('client-a')
    guest_mode.check_upload(workspace, 1)
    with pytest.raises(guest_mode.GuestRefused):
        guest_mode.check_upload(workspace, 2)
    guest_mode.check_upload('template', 50)  # reviewers and owners are not limited here


def test_guest_retrieval_uses_gemini_index_not_local(seeded, monkeypatch):
    from services.api import embedding_providers, retrieval
    workspace, _ = guest_mode.create('client-a')
    version = store.one('SELECT id FROM versions WHERE workspace=?', (workspace,))['id']
    monkeypatch.setenv('RT_EMBED_PROVIDER', 'local')

    class NoLocal:
        def __init__(self, *a, **k):
            raise AssertionError('guests must not reach the local GPU service')

    monkeypatch.setattr(embedding_providers, 'LocalRetrievalProvider', NoLocal)
    monkeypatch.setattr(GeminiRetrievalProvider, 'embed',
                        lambda self, texts, task: {'vectors': [[1.0] + [0.0] * 767 for _ in texts],
                                                   'fingerprint': embedding_providers.fingerprint(self.descriptor())})
    found = retrieval.retrieve(workspace, [version], 'square root of dk')
    assert found['blocks'] and found['dense_index'].get('provider') == 'gemini'


def test_expired_guest_copy_is_purged_but_ledger_and_runs_stay(seeded):
    workspace, expires = guest_mode.create('client-a')
    rid = guest_run(workspace)
    quota_row(rid)
    store.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('h', workspace, 'guest', expires))
    assert store.one('SELECT count(*) n FROM blocks WHERE workspace=?', (workspace,))['n'] > 0
    assert guest_mode.purge_expired(now=expires + 1) == [workspace]
    for table in ('blocks', 'retrieval_chunks', 'index_generations', 'sessions'):
        assert store.one(f'SELECT count(*) n FROM {table} WHERE workspace=?', (workspace,))['n'] == 0
    assert store.one('SELECT count(*) n FROM versions WHERE workspace=? AND deleted=0', (workspace,))['n'] == 0
    assert store.one('SELECT count(*) n FROM runs WHERE id=?', (rid,))['n'] == 1
    assert store.one('SELECT count(*) n FROM quota WHERE run_id=?', (rid,))['n'] == 1
    # The template corpus is untouched.
    assert store.one("SELECT count(*) n FROM blocks WHERE workspace='template'")['n'] > 0
    assert guest_mode.purge_expired(now=expires + 1) == []


def test_guest_sees_template_answers_as_saved_history_without_ledger(seeded):
    block_id = store.one('SELECT id FROM blocks WHERE version_id=? LIMIT 1', (seeded,))['id']
    parse_id = store.one('SELECT id FROM parses WHERE version_id=? LIMIT 1', (seeded,))['id']
    rid = store.uid()
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,result,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                  (rid, 'template', 'qa', 'completed',
                   f'{{"question": "why scale?", "version_ids": ["{seeded}"], "thread_id": "th-demo"}}',
                   f'{{"answer": "Scaling keeps softmax gradients usable.", "citations": [{{"version_id": "{seeded}", "block_id": "{block_id}"}}]}}',
                   time.time(), time.time()))
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                  (store.uid(), 'template', 'qa', 'failed', '{}', time.time(), time.time()))
    store.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (rid, 'answer', f'{{"run": "{rid}"}}', time.time()))
    store.execute('INSERT INTO claims(id,workspace,run_id,type,text) VALUES(?,?,?,?,?)', ('claim-1', 'template', rid, 'fact', 'Scaling.'))
    store.execute('INSERT INTO evidence(id,workspace,claim_id,version_id,block_id,page_index,quote,status) VALUES(?,?,?,?,?,?,?,?)',
                  ('ev-1', 'template', 'claim-1', seeded, block_id, 0, 'square root of dk', 'supported'))
    store.execute('INSERT INTO artifacts(id,workspace,run_id,kind,title,payload,created) VALUES(?,?,?,?,?,?,?)',
                  ('art-1', 'template', rid, 'outline', 'Saved outline', '{}', time.time()))
    store.execute('''INSERT INTO translation_cache(workspace,version_id,parse_id,block_id,source_language,target_language,
                     glossary_version,model,actual_model,text,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                  ('template', seeded, parse_id, block_id, 'en', 'zh-Hans', 'g1', 'gemini-4-hydrogen', 'gemini-4-hydrogen', '缩放', time.time()))
    quota_row(rid, 'gemini-4-hydrogen')
    ledger = store.one('SELECT count(*) n FROM quota')['n']
    template_runs = store.one("SELECT count(*) n FROM runs WHERE workspace='template'")['n']
    with client() as http:
        workspace = http.post('/api/v1/auth/guest').json()['workspace']
        guest_doc = http.get('/api/v1/documents').json()[0]['id']
        runs = store.rows('SELECT * FROM runs WHERE workspace=?', (workspace,))
        assert len(runs) == 1 and runs[0]['id'] != rid and runs[0]['status'] == 'completed'
        copy = runs[0]
        assert 'showcase_copy' in copy['payload'] and guest_doc in copy['payload'] and seeded not in copy['payload']
        assert seeded not in copy['result'] and block_id not in copy['result']
        assert http.get(f"/api/v1/runs/{copy['id']}").status_code == 200
        assert http.get(f'/api/v1/runs/{rid}').status_code in (403, 404)
        evidence = store.one('SELECT * FROM evidence WHERE workspace=?', (workspace,))
        assert evidence['version_id'] == guest_doc and evidence['quote'] == 'square root of dk'
        claim = store.one('SELECT * FROM claims WHERE id=?', (evidence['claim_id'],))
        assert claim['workspace'] == workspace and claim['run_id'] == copy['id']
        assert store.one('SELECT run_id FROM artifacts WHERE workspace=?', (workspace,))['run_id'] == copy['id']
        assert store.one('SELECT text FROM translation_cache WHERE workspace=? AND version_id=?', (workspace, guest_doc))['text'] == '缩放'
        assert store.one('SELECT count(*) n FROM steps WHERE run_id=?', (copy['id'],))['n'] == 1
        # Saved history is not new usage: the ledger is unchanged and the guest keeps the full allowance.
        assert store.one('SELECT count(*) n FROM quota')['n'] == ledger
        assert http.get('/api/v1/guest/status').json()['remaining_calls'] == 2
    expires = store.one('SELECT expires FROM guest_workspaces WHERE workspace=?', (workspace,))['expires']
    assert guest_mode.purge_expired(now=expires + 1) == [workspace]
    for table in ('runs', 'claims', 'evidence', 'artifacts', 'translation_cache'):
        assert store.one(f'SELECT count(*) n FROM {table} WHERE workspace=?', (workspace,))['n'] == 0
    assert store.one("SELECT count(*) n FROM runs WHERE workspace='template'")['n'] == template_runs


def test_deleted_template_versions_are_not_copied(seeded):
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(30, 700, 'An earlier upload that the reviewer later deleted.')
    pdf.save()
    gone = documents.upload_document('template', 'old.pdf', buf.getvalue(), index_dense=False)['document']['id']
    jobs.work_once(pool='documents')
    idx.build('template', [seeded, gone], provider=GeminiRetrievalProvider())
    store.execute('UPDATE versions SET deleted=1 WHERE id=?', (gone,))
    # Reparsed versions link every block to its parse; deleted versions keep those links.
    parse = store.one('SELECT id FROM parses WHERE version_id=?', (gone,))['id']
    for row in store.rows('SELECT id FROM blocks WHERE version_id=?', (gone,)):
        store.execute('INSERT OR IGNORE INTO block_parses VALUES(?,?)', (row['id'], parse))
    assert store.one('SELECT count(*) n FROM block_parses WHERE block_id IN (SELECT id FROM blocks WHERE version_id=?)', (gone,))['n'] > 0
    workspace, _ = guest_mode.create('client-deleted')
    assert store.one('SELECT count(*) n FROM versions WHERE workspace=?', (workspace,))['n'] == 1
    copied = {r['version_id'] for r in store.rows('SELECT version_id FROM retrieval_chunks WHERE workspace=?', (workspace,))}
    live = {r['id'] for r in store.rows('SELECT id FROM versions WHERE workspace=?', (workspace,))}
    assert copied and copied <= live
    indexed = {r['version_id'] for r in store.rows('SELECT version_id FROM active_retrieval_indices WHERE workspace=?', (workspace,))}
    assert indexed <= live
