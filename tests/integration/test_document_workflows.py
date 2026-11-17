"""Offline API/worker fixtures; the last test reads the two actual public PDFs.

No keys, live API, network, production DB, services or GPU are used.
"""
import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api import document_workflows as dw, store


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    dw.migrate_document_workflows()
    dw.migrate_document_workflows()
    now = time.time()
    with store.db() as c:
        for work, workspace in [('work', 'ws'), ('other', 'ws'), ('foreign', 'outside')]:
            c.execute('INSERT INTO works VALUES(?,?,?,?,?)', (work, workspace, 'Fixture work', 'arxiv:1234.56789', '{}'))
        for vid, work, ws, n in [('new', 'work', 'ws', 7), ('old', 'work', 'ws', 1), ('unknown', 'other', 'ws', None), ('private', 'foreign', 'outside', 9)]:
            c.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,label,identity,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (vid, ws, work, 'Fixture work', 'random-name.pdf', vid, '/never/read.pdf', 'ready', 'v'+str(n), 'arxiv:1234.56789', json.dumps({'arxiv_version': n}), now))
            c.execute('INSERT INTO parses(id,version_id,workspace,engine,device,status,page_count,created) VALUES(?,?,?,?,?,?,?,?)',
                      (vid, vid, ws, 'native', 'cpu', 'ready', 2, now))
            c.execute('INSERT INTO active_parses VALUES(?,?)', (vid, vid))
    def block(bid, text, kind='paragraph', markers=None, page=0, order=0, parse='old'):
        with store.db() as c:
            c.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      (bid, 'ws', 'old', page, '[0,0,1,1]', kind, order, text, 'fixture', 'native', json.dumps({'citation_markers': markers or []})))
            if parse != 'old':
                c.execute('INSERT INTO block_parses VALUES(?,?)', (bid, parse))
    block('h1', '1 Methods', 'heading', order=0)
    block('body1', 'We use [1] twice [1] and compare [2–3].', markers=['1', '2–3'], order=1)
    block('body2', 'Other observations [1, 2].', markers=['1, 2'], order=2)
    block('header', 'Header [1]', 'header', ['1'], order=3)
    block('h2', '2 Experiments', 'heading', order=4)
    block('body3', 'Baseline comparison [2].', markers=['2'], order=5)
    block('refs-heading', 'References', 'heading', order=6)
    for i in range(1, 4):
        block(f'bib{i}', f'[{i}] Author. Verified Fixture Title Number {i}. [1]', 'paragraph', ['1'], page=1, order=i)
        store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)',
                      (f'r{i}', 'ws', 'old', f'bib{i}', 1, str(i), f'[{i}] Author. Verified Fixture Title Number {i}.', f'arxiv:2345.6789{i}', json.dumps({'parse_id': 'old', 'block_ids': [f'bib{i}']})))
    from fastapi.responses import JSONResponse
    app = FastAPI()
    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse(status_code=422, content={'detail': str(exc)})
    app.include_router(dw.router)
    app.dependency_overrides[dw.auth] = lambda: {'workspace': 'ws', 'role': 'reviewer'}
    with TestClient(app) as client:
        yield client, block, tmp_path


def resolve(client, action='keep_newer', **extra):
    return client.post('/api/v1/versions/resolve', json={'incoming_version_id': 'old', 'existing_version_id': 'new',
        'work_id': 'work', 'action': action, 'idempotency_key': 'choice-'+action, **extra})


def analyze(client, **body):
    response = client.post('/api/v1/documents/old/reference-analysis', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def dispatch(rid):
    run = store.one('SELECT * FROM runs WHERE id=?', (rid,))
    store.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
    result = dw.handle_document_run(run)
    if not store.cancelled(rid):
        store.execute('UPDATE runs SET status=?,result=? WHERE id=?', (result.get('status', 'completed'), json.dumps(result), rid))
    return result


def test_versions_keep_both_replace_preserve_history(fixture):
    client, _, _ = fixture
    options = client.get('/api/v1/versions/old/choices').json()
    assert options['newer_version_id'] == 'new'
    assert options['requires_choice'] and 'path' not in str(options)
    counts = {table: store.one(f'SELECT count(*) n FROM {table}')['n'] for table in ('versions', 'blocks', 'parses', 'refs')}
    response = resolve(client)
    assert response.status_code == 200
    assert response.json()['current_version_id'] == 'new'
    assert dw.retrieval_version_ids('ws', ['old', 'new']) == ['new']
    assert resolve(client).json()['reused']
    assert resolve(client, action='both').json()['excluded_version_ids'] == []
    assert dw.retrieval_version_ids('ws', ['old', 'new']) == ['old', 'new']
    assert resolve(client, action='replace').json()['current_version_id'] == 'old'
    assert dw.retrieval_version_ids('ws', ['old', 'new']) == ['old']
    assert counts == {table: store.one(f'SELECT count(*) n FROM {table}')['n'] for table in counts}
    assert store.one('SELECT deleted FROM versions WHERE id=?', ('new',))['deleted'] == 0
    assert store.one('SELECT count(*) n FROM quota')['n'] == 0


@pytest.mark.parametrize('changes,expected', [({'existing_version_id': 'private'}, 404),
    ({'existing_version_id': 'unknown'}, 409), ({'work_id': 'foreign'}, 409),
    ({'existing_version_id': 'old'}, 409), ({'unknown': True}, 422), ({'action': 'delete'}, 422)])
def test_version_scope_and_strict_schema(fixture, changes, expected):
    assert resolve(fixture[0], **changes).status_code == expected


def test_unknown_order_and_conflicting_idempotency(fixture):
    client = fixture[0]
    store.execute("UPDATE versions SET metadata='{}' WHERE id='old'")
    assert resolve(client).status_code == 409
    assert resolve(client, action='both').status_code == 200
    assert resolve(client, action='replace', idempotency_key='choice-both').status_code == 409
    assert client.get('/api/v1/versions/private/choices').status_code == 404
    with pytest.raises(Exception):
        dw.retrieval_version_ids('ws', ['private'])


def test_frequency_sections_and_no_bibliography_self_count(fixture):
    report = analyze(fixture[0])
    refs = {r['id']: r for r in report['references']}
    assert {rid: r['citation_count'] for rid, r in refs.items()} == {'r1': 3, 'r2': 3, 'r3': 1}
    assert refs['r2']['sections'] == {'1 Methods': 2, '2 Experiments': 1}
    assert refs['r1']['contexts'][0]['block_id'] == 'body1'
    assert all(not x['block_id'].startswith('bib') for r in refs.values() for x in r['contexts'])
    assert analyze(fixture[0])['id'] == report['id']
    assert fixture[0].get('/api/v1/documents/private/reference-analysis').status_code == 404
    assert store.one('SELECT count(*) n FROM reference_analyses')['n'] == 1


def test_snapshot_binding_and_partial_status(fixture):
    client, block, _ = fixture
    old = analyze(client)
    now = time.time()
    store.execute("INSERT INTO parses(id,version_id,workspace,engine,device,status,page_count,created) VALUES('p2','old','ws','native','cpu','partial',2,?)", (now,))
    store.execute("UPDATE active_parses SET parse_id='p2' WHERE version_id='old'")
    block('newbody', 'Different [1].', markers=['1'], parse='p2')
    store.execute("INSERT INTO refs VALUES('p2ref','ws','old','newbody',0,'1','Author. New snapshot.',NULL,?)", (json.dumps({'parse_id': 'p2', 'block_ids': []}),))
    new = analyze(client)
    assert new['parse_id'] == 'p2' and new['status'] == 'partial'
    assert new['id'] != old['id']
    historical = analyze(client, parse_id='old')
    assert historical['active_snapshot'] is False
    assert historical['references'] == old['references']
    assert client.post('/api/v1/documents/old/reference-analysis', json={'parse_id': 'private'}).status_code == 422


def test_marker_ranges_malformed_and_ambiguous(fixture):
    _, block, _ = fixture
    assert dw._marker_numbers('2–4, 9') == {'2', '3', '4', '9'}
    assert dw._marker_numbers('4-2') == set()
    assert dw._marker_numbers('1-99999') == set()
    store.execute("UPDATE refs SET marker='1' WHERE id='r2'")
    block('no-metadata', 'Unidentified [1] should not be counted.', order=2)
    report = dw.analyze_references('ws', 'old')
    assert report['ambiguous_marker_occurrences'] == 3
    assert next(r for r in report['references'] if r['id'] == 'r1')['citation_count'] == 0


def test_light_classification_once_bound_to_context(fixture, monkeypatch):
    from services.api import models
    client = fixture[0]
    report = analyze(client)
    calls = []
    def generate(system, prompt, rid, **kwargs):
        calls.append((system, json.loads(prompt), kwargs))
        return {'model': 'fixture-lite', 'text': json.dumps({'items': [
            {'ref_id': r['id'], 'label': 'background', 'context_block_ids': [r['contexts'][0]['block_id']]} for r in report['references']]})}
    monkeypatch.setattr(models, 'generate', generate)
    body = {'idempotency_key': 'classify-once'}
    run = client.post(f"/api/v1/reference-analyses/{report['id']}/classify", json=body).json()
    assert client.post(f"/api/v1/reference-analyses/{report['id']}/classify", json=body).json()['id'] == run['id']
    assert dispatch(run['id'])['status'] == 'completed'
    assert dispatch(run['id'])['classified'] == 3
    assert len(calls) == 1 and calls[0][2] == {'role': 'light', 'json_output': True, 'response_schema': dw.Classifications.model_json_schema()}
    assert '不可信数据' in calls[0][0]
    assert analyze(client)['references'][0]['classification']['model'] == 'fixture-lite'


def test_malformed_classification_is_not_rebilled(fixture, monkeypatch):
    from services.api import models
    report = analyze(fixture[0])
    calls = []
    monkeypatch.setattr(models, 'generate', lambda *a, **k: calls.append(1) or {'model': 'fixture', 'text': '{"items":[{"ref_id":"forged","label":"background","context_block_ids":["private"]}]}'})
    run = fixture[0].post(f"/api/v1/reference-analyses/{report['id']}/classify", json={'idempotency_key': 'bad-classification'}).json()
    for _ in range(2):
        with pytest.raises(ValueError): dispatch(run['id'])
    assert len(calls) == 1
    assert analyze(fixture[0])['classification_status'] == 'not_run'


def test_conflicting_duplicate_reference_is_uncertain_and_receipt_reused(fixture, monkeypatch):
    from services.api import models
    report = analyze(fixture[0]);calls = []
    items = [{'ref_id': r['id'], 'label': 'background', 'context_block_ids': [r['contexts'][0]['block_id']]} for r in report['references']]
    items.append({**items[0], 'label': 'method_dependency'})
    monkeypatch.setattr(models, 'generate', lambda *a, **k: calls.append(1) or {'model': 'fixture-lite', 'text': json.dumps({'items': items})})
    run = fixture[0].post(f"/api/v1/reference-analyses/{report['id']}/classify", json={'idempotency_key': 'conflicting-classification'}).json()
    assert dispatch(run['id'])['classified'] == 3
    result = analyze(fixture[0])['references'][0]['classification']
    assert result['label'] == 'uncertain' and result['context_block_ids'] == []
    assert '冲突' in result['reason']
    assert dispatch(run['id'])['classified'] == 3 and calls == [1]


def test_unknown_model_request_never_replayed(fixture, monkeypatch):
    from services.api import models
    report = analyze(fixture[0])
    run = fixture[0].post(f"/api/v1/reference-analyses/{report['id']}/classify", json={'idempotency_key': 'unknown-model'}).json()
    dw._save_step(run['id'], 'classification', 'started')
    monkeypatch.setattr(models, 'generate', lambda *a, **k: pytest.fail('unknown request replayed'))
    assert dispatch(run['id'])['status'] == 'partial'


def test_batched_classifier_keeps_received_first_batch_and_never_replays_unknown(fixture, monkeypatch):
    from services.api import models
    report = analyze(fixture[0])
    queued = fixture[0].post(f"/api/v1/reference-analyses/{report['id']}/classify", json={'idempotency_key': 'batch-classify'}).json()
    run = store.one('SELECT * FROM runs WHERE id=?', (queued['id'],))
    run['payload'] = json.loads(run['payload'])
    entries = [{'ref_id': str(i), 'reference_text': 'fixture', 'contexts': []} for i in range(13)]
    calls = []
    def generate(system, prompt, rid, **kwargs):
        refs = json.loads(prompt)['references'];calls.append(len(refs))
        if len(refs) == 1:raise models.ModelError('fixture indeterminate send')
        return {'model': 'fixture-lite', 'text': json.dumps({'items': [{'ref_id': r['ref_id'], 'label': 'uncertain', 'context_block_ids': []} for r in refs]})}
    monkeypatch.setattr(models, 'generate', generate)
    assert dw._classification_responses(run, report, entries)[0] is None
    assert calls == [12, 1]
    assert dw._step(run['id'], 'classification:0')['status'] == 'received'
    assert dw._classification_responses(run, report, entries)[0] is None
    assert calls == [12, 1]


def queue_batch(client, report, **extra):
    p = {'mode': 'top', 'top_n': 2, 'max_items': 20, 'index_dense': False, 'idempotency_key': 'batch-refs', **extra}
    response = client.post(f"/api/v1/reference-analyses/{report['id']}/downloads", json=p)
    assert response.status_code == 200, response.text
    return response.json()['id']


def test_download_parent_children_resume_and_bounds(fixture, monkeypatch):
    from services.api import research
    from services.api.dependencies import wake_dependencies
    client = fixture[0]
    report = analyze(client)
    calls = []
    def imported(workspace, paper, **kwargs):
        calls.append((workspace, paper, kwargs))
        return {'metadata_only': False, 'document': {'id': 'download-fixture'}, 'fulltext_status': 'fixture PDF imported'}
    monkeypatch.setattr(research, 'import_paper', imported)
    rid = queue_batch(client, report)
    assert queue_batch(client, report) == rid
    assert dispatch(rid)['status'] == 'waiting_children'
    assert store.one("SELECT count(*) n FROM runs WHERE kind='reference_import'")['n'] == 1
    child = dw.download_status('ws', rid)['items'][0]['child_run_id']
    assert client.post(f'/api/v1/reference-downloads/{rid}/cancel', json={}).status_code == 200
    assert store.one('SELECT status FROM runs WHERE id=?', (child,))['status'] == 'cancelled'
    assert len(calls) == 0
    assert client.post(f'/api/v1/reference-downloads/{rid}/resume', json={}).status_code == 200
    dispatch(child)
    dispatch(rid)
    state = dw.download_status('ws', rid)
    second = state['items'][1]['child_run_id']
    assert second and second != child
    dispatch(second)
    assert rid in wake_dependencies()
    result = dispatch(rid)
    assert result['status'] == 'completed' and result['truncated']
    assert result['selected_count'] == 2 and len(calls) == 2
    assert all(c[2] == {'index_dense': False} for c in calls)
    assert client.post(f"/api/v1/reference-analyses/{report['id']}/downloads", json={'mode': 'all', 'max_items': 21, 'idempotency_key': 'over-cap'}).status_code == 422
    assert client.get('/api/v1/reference-downloads/no-such').status_code == 404


def test_download_unknown_not_resent_and_failure_visible(fixture, monkeypatch):
    from services.api import research
    client = fixture[0]
    report = analyze(client)
    rid = queue_batch(client, report, top_n=1)
    dispatch(rid)
    child = dw.download_status('ws', rid)['items'][0]['child_run_id']
    store.execute("UPDATE reference_download_items SET status='importing' WHERE child_run_id=?", (child,))
    monkeypatch.setattr(research, 'import_paper', lambda *a, **k: pytest.fail('unknown import resent'))
    assert dispatch(child)['status'] == 'partial'
    assert dispatch(rid)['status'] == 'partial'
    assert dw.download_status('ws', rid)['counts'] == {'unknown': 1}
    assert client.post(f'/api/v1/reference-downloads/{rid}/resume', json={}).status_code == 200
    assert dispatch(rid)['status'] == 'partial'


def test_title_ambiguity_no_arbitrary_import(fixture, monkeypatch):
    from services.api import research
    client = fixture[0]
    store.execute('UPDATE refs SET target_identity=NULL')
    report = analyze(client)
    searches = []
    monkeypatch.setattr(research, 'search_papers', lambda *a, **k: searches.append(k) or {'results': [
        {'identity': f'arxiv:{i}', 'title': 'Verified Fixture Title Number 2', 'source': 'fixture'} for i in ['1111.22222', '2222.33333']], 'errors': []})
    monkeypatch.setattr(research, 'import_paper', lambda *a, **k: pytest.fail('ambiguous result imported'))
    rid = queue_batch(client, report, top_n=1)
    dispatch(rid)
    child = dw.download_status('ws', rid)['items'][0]['child_run_id']
    dispatch(child)
    state = dw.download_status('ws', rid)
    assert state['items'][0]['status'] == 'needs_selection'
    assert searches == [{'sources': ['arxiv', 'crossref'], 'limit': 3}]


def test_soft_excluded_history_and_worker_dispatch_extension(fixture):
    resolve(fixture[0])
    assert dw.analyze_references('ws', 'old')['references']
    assert dw.handle_document_run({'kind': 'not-owned'}) is None
    assert set(dw.RUN_KINDS) == {'reference_classify', 'reference_download', 'reference_import'}


def test_real_public_v7_v1_renamed_and_reference_counts(fixture, monkeypatch):
    """Actual public core PDFs, locally parsed without edits to their source bytes."""
    from services.api import documents
    monkeypatch.setattr(documents, 'DATA', fixture[2])
    root = Path(__file__).resolve().parents[2]
    versions = []
    for name, renamed in [('1706.03762v7.pdf', 'zeta-new.pdf'), ('1706.03762v1.pdf', 'alpha-old.pdf')]:
        source = root / 'evals/pdfs/core' / name
        assert source.is_file(), f'public test PDF missing: {source}'
        with source.open('rb') as stream:
            uploaded = documents.upload_document_file('real-fixture', renamed, stream, index_dense=False)
        run = store.one('SELECT * FROM runs WHERE id=?', (uploaded['run_id'],))
        parsed = documents.parse_document(run)
        assert parsed['parsed_pages'] >= 10
        versions.append(uploaded['document']['id'])
    opts = dw.version_choices('real-fixture', versions[1])
    assert opts['newer_version_id'] == versions[0] and opts['requires_choice']
    compared = documents.compare_versions('real-fixture', *versions)
    assert compared['same_work'] and sum(compared['counts'][k] for k in ('added', 'deleted', 'modified')) > 0
    report = dw.analyze_references('real-fixture', versions[0])
    assert report['reference_count'] >= 30
    assert sum(r['citation_count'] for r in report['references']) > 20
    bib = {r['block_id'] for r in store.rows('SELECT block_id FROM refs WHERE version_id=?', (versions[0],))}
    assert all(x['block_id'] not in bib for r in report['references'] for x in r['contexts'])
    assert store.one('SELECT count(*) n FROM quota')['n'] == 0


def test_metadata_only_is_partial_and_never_claims_download(fixture, monkeypatch):
    from services.api import research
    client = fixture[0]
    report = analyze(client)
    monkeypatch.setattr(research, 'import_paper', lambda *a, **k: {'metadata_only': True, 'work_id': 'meta', 'fulltext_status': '没有可访问全文'})
    rid = queue_batch(client, report, top_n=1)
    dispatch(rid)
    child = dw.download_status('ws', rid)['items'][0]['child_run_id']
    assert dispatch(child)['status'] == 'partial'
    result = dispatch(rid)
    assert result['status'] == 'partial' and result['counts'] == {'metadata_only': 1}
    assert result['items'][0]['result']['version_id'] is None


def test_cancellation_of_own_parse_never_cancels_existing_parse(fixture, monkeypatch):
    from services.api import research
    client = fixture[0]
    report = analyze(client)
    existing = 'pre-existing-parse'
    now = time.time() - 100
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                  (existing, 'ws', 'parse', 'queued', '{}', now, now))
    created = []
    def imported(w, paper, **kw):
        rid = 'owned-parse-' + str(len(created))
        if not created:
            now = time.time()
            store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                          (rid, 'ws', 'parse', 'queued', '{}', now, now))
        else:
            rid = existing
        created.append(rid)
        return {'metadata_only': False, 'run_id': rid, 'document': {'id': 'imported-version'}, 'fulltext_status': 'fixture'}
    monkeypatch.setattr(research, 'import_paper', imported)
    rid = queue_batch(client, report)
    dispatch(rid)
    child = dw.download_status('ws', rid)['items'][0]['child_run_id']
    dispatch(child)
    dispatch(rid)
    second = dw.download_status('ws', rid)['items'][1]['child_run_id']
    dispatch(second)
    dw.cancel_reference_downloads('ws', rid)
    assert store.one('SELECT status FROM runs WHERE id=?', (created[0],))['status'] == 'cancelled'
    assert store.one('SELECT status FROM runs WHERE id=?', (existing,))['status'] == 'queued'
    dw.resume_reference_downloads('ws', rid)
    assert dispatch(rid)['status'] == 'waiting_children'
    assert store.one('SELECT status FROM runs WHERE id=?', (created[0],))['status'] == 'queued'
    assert len(created) == 2  # No PDF download repeated during parse recovery.



def test_download_scope_and_all_bound_are_explicit(fixture):
    client, _, _ = fixture
    report = analyze(client)
    for i in range(4, 26):
        report['references'].append(dict(report['references'][0], id=f'r{i}', rank=i))
    report['reference_count'] = len(report['references'])
    store.execute('UPDATE reference_analyses SET report=? WHERE id=?', (json.dumps(report), report['id']))
    rid = queue_batch(client, report, mode='all')
    result = dispatch(rid)
    assert result['selected_count'] == 20 and result['total_references'] == 25 and result['truncated'] is True
    assert len(result['items']) == 20
    # Authenticated scope is from the server dependency, not caller input.
    client.app.dependency_overrides[dw.auth] = lambda: {'workspace': 'outside', 'role': 'reviewer'}
    assert client.get(f'/api/v1/reference-downloads/{rid}').status_code == 404
    assert client.post(f'/api/v1/reference-downloads/{rid}/cancel', json={}).status_code == 404
    assert client.post(f'/api/v1/reference-downloads/{rid}/resume', json={}).status_code == 404
    assert client.post(f"/api/v1/reference-analyses/{report['id']}/downloads", json={'idempotency_key': 'forged-access'}).status_code == 404
