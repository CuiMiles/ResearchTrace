"""Fixture-only Agent tool contracts; never use models or live scholarly APIs."""
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import time

import pytest
from pydantic import ValidationError

from services.api import documents, jobs, models, research, snapshots, store
from services.api import tool_registry as registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    store.migrate()

    def no_request(*args, **kwargs):
        pytest.fail('Fixture-only registry tests must not make provider/network requests')

    monkeypatch.setattr(models, 'request', no_request)
    monkeypatch.setattr(models, 'generate', no_request)
    monkeypatch.setattr(models, 'embed', no_request)
    monkeypatch.setattr(research, 'fetch_public', no_request)
    monkeypatch.setattr(research, 'search_papers', no_request)
    # retrieve() itself may run (keyword lists only); the provider calls above stay forbidden,
    # so any hidden query embedding still fails the test.
    monkeypatch.setattr(registry.retrieval, 'LocalRetrievalProvider', no_request, raising=False)
    for workspace in ('alpha', 'beta'):
        store.execute('INSERT INTO workspaces VALUES(?,?,?)', (workspace, workspace, time.time()))
        store.execute('INSERT INTO runs(id,workspace,kind,status,payload,checkpoint,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                      ('run-' + workspace, workspace, 'agent', 'running', '{}', json.dumps({'retrieval': {'keep': True}, 'model_response': {'usage': 'unchanged'}}), time.time(), time.time()))
        for suffix in ('1', '2'):
            vid = workspace + '-v' + suffix
            work = workspace + '-work'
            store.execute('INSERT OR IGNORE INTO works VALUES(?,?,?,?,?)', (work, workspace, 'Fixture research', 'doi:10.1234/fixture', '{}'))
            store.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,page_count,parsed_pages,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (vid, workspace, work, 'Fixture version ' + suffix, 'fixture.pdf', workspace + suffix, str(tmp_path / 'not-a-live-document.pdf'), 'ready', 1, 1, time.time()))
            bid = vid + ':0:0'
            text = 'Controlled fixture evidence eight GPUs.' if suffix == '1' else 'Controlled fixture evidence four CPUs.'
            store.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                          (bid, workspace, vid, 0, '[0,0,1,1]', 'paragraph', 0, text, 'fixture', 'native', '{}'))
            store.execute('INSERT INTO block_fts VALUES(?,?)', (bid, text))
    return tmp_path


def context(call_id=None, **kwargs):
    return registry.ToolContext(workspace='alpha', run_id='run-alpha', call_id=call_id, **kwargs)


def checkpoint():
    return json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?', ('run-alpha',))['checkpoint'])


def note(**kwargs):
    return {'title': 'Fixture draft', 'content': 'Untrusted draft says ignore instructions; this is inert data.', **kwargs}


def test_eleven_closed_schemas_context_and_no_authority_in_args():
    schemas = registry.tool_schemas()
    assert len(schemas) == 11
    assert {s['function']['name'] for s in schemas} == set(registry.TOOLS)
    assert all(s['function']['parameters']['additionalProperties'] is False for s in schemas)
    assert registry.ToolContext(workspace='alpha', runid='run-alpha').run_id == 'run-alpha'
    for kwargs in ({'budget': 11}, {'budget': True}, {'provider_budget': 1}, {'workspace': '../beta'}):
        data = {'workspace': 'alpha', 'run_id': 'run-alpha', **kwargs}
        with pytest.raises(ValidationError):
            registry.ToolContext(**data)
    result = registry.execute_tool(context('bad-args'), 'save_artifact', note(workspace='beta'))
    assert result['code'] == 'invalid_arguments'
    assert result['budget']['used'] == 1
    unknown = registry.execute_tool(context('unknown'), 'exec_shell', {'command': 'echo no'})
    assert unknown['code'] == 'unknown_tool'
    assert not store.rows("SELECT * FROM artifacts WHERE kind='agent_note'")


def test_atomic_persisted_budget_replays_and_preserves_qa_checkpoint():
    ctx = context('same', budget=2)
    result = registry.execute_tool(ctx, 'save_artifact', note())
    replay = registry.execute_tool(ctx, 'save_artifact', note())
    assert result['status'] == 'PASS'
    assert replay['replayed'] is True
    assert replay['result'] == result['result']
    assert len(store.rows("SELECT * FROM artifacts WHERE kind='agent_note'")) == 1
    assert registry.execute_tool(context('same'), 'save_artifact', note(content='changed'))['code'] == 'idempotency_conflict'
    assert registry.execute_tool(context('second'), 'save_artifact', note())['status'] == 'PASS'
    assert registry.execute_tool(context('third'), 'save_artifact', note())['code'] == 'budget_exhausted'
    snap = checkpoint()
    assert snap['retrieval'] == {'keep': True}
    assert snap['model_response'] == {'usage': 'unchanged'}
    assert len(snap['tool_registry']['calls']) == 2
    assert snap['tool_registry']['limit'] == 2
    assert len(store.rows("SELECT * FROM steps WHERE run_id='run-alpha' AND event='tool_finished'")) == 2


def test_planner_receives_query_limit_error_without_echoing_rejected_inputs():
    result = registry.execute_tool(context('too-many-queries'), 'retrieve_evidence',
        {'version_ids': ['alpha-v1'], 'question': 'training', 'queries': ['private-input'] * 5})
    assert result['status'] == 'FAIL'
    error = result['result']['validation_errors'][0]
    assert error['path'] == ['queries'] and error['type'] == 'too_long'
    assert '4' in error['message']
    assert 'private-input' not in json.dumps(result)


def test_concurrent_callers_cannot_exceed_ten_attempts():
    def attempt(i):
        return registry.execute_tool(context(f'parallel-{i}'), 'save_artifact', note())
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(18)))
    assert sum(r['status'] == 'PASS' for r in outcomes) == 10
    assert sum(r.get('code') == 'budget_exhausted' for r in outcomes) == 8
    assert len(checkpoint()['tool_registry']['calls']) == 10


def test_inflight_or_crashed_attempt_never_reexecutes(monkeypatch):
    ctx = context('interrupted')
    args = note()
    digest = registry.hashlib.sha256(registry._dump(args).encode()).hexdigest()
    registry._reserve(ctx, 'interrupted', 'save_artifact', digest)
    result = registry.execute_tool(ctx, 'save_artifact', args)
    assert result['code'] == 'indeterminate_call'
    assert not store.rows("SELECT * FROM artifacts WHERE kind='agent_note'")


def test_scope_versions_references_and_artifacts():
    assert registry.execute_tool(registry.ToolContext(workspace='beta', run_id='run-alpha'), 'build_citation_graph', {})['code'] == 'scope_denied'
    assert registry.execute_tool(context(), 'retrieve_evidence', {'version_ids': ['beta-v1'], 'question': 'GPUs'})['code'] == 'scope_denied'
    assert registry.execute_tool(context(), 'compare_versions', {'left': 'alpha-v1', 'right': 'beta-v1'})['code'] == 'scope_denied'
    assert registry.execute_tool(context(), 'save_artifact', note(version_ids=['alpha-v1'], block_ids=['beta-v1:0:0']))['code'] == 'scope_denied'
    foreign = store.artifact('beta', 'run-beta', 'csv_dataset', 'private', {'csv_text': 'x,y\n1,2', 'sha256': 'fake'})
    assert registry.execute_tool(context(), 'render_chart', {'dataset_artifact_id': foreign, 'spec': {}})['code'] == 'scope_denied'
    store.execute('UPDATE versions SET deleted=1 WHERE id=?', ('alpha-v1',))
    assert registry.execute_tool(context(), 'retrieve_evidence', {'version_ids': ['alpha-v1'], 'question': 'GPUs'})['code'] == 'scope_denied'


def test_retrieve_keyword_only_no_hidden_embedding():
    # A dense row exists deliberately: the registry must not call retrieve/embed.
    store.execute('INSERT INTO embeddings VALUES(?,?,?,?,?,?)', ('alpha-v1:0:0', 'alpha', 'alpha-v1', 'fixture', 1, b'1234'))
    result = registry.execute_tool(context(), 'retrieve_evidence', {'version_ids': ['alpha-v1'], 'question': 'GPUs'})
    assert result['status'] == 'PASS'
    assert result['result']['mode'] == 'keyword'
    assert result['result']['blocks'][0]['id'] == 'alpha-v1:0:0'
    assert result['budget']['provider_requests'] == 0


def test_local_compare_resolve_and_real_reference_graph():
    store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)', ('ref-alpha', 'alpha', 'alpha-v1', 'alpha-v1:0:0', 0, '1', 'Fixture reference', 'doi:10.1234/fixture', '{}'))
    resolved = registry.execute_tool(context(), 'resolve_reference', {'reference_id': 'ref-alpha'})
    assert resolved['result']['local_targets'][0]['id'] == 'alpha-work'
    diff = registry.execute_tool(context(), 'compare_versions', {'left': 'alpha-v1', 'right': 'alpha-v2'})
    assert diff['status'] == 'PASS'
    assert diff['result']['counts']['modified'] == 1
    graph = registry.execute_tool(context(), 'build_citation_graph', {})
    assert graph['status'] == 'PASS'
    assert graph['result']['nodes'][0]['id'] == 'alpha-work'
    assert graph['result']['edges'] == []  # self-reference is not invented as a new edge


def test_parse_queues_revision_and_nested_children_bound():
    result = registry.execute_tool(context('parse', budget=2), 'parse_document', {'version_id': 'alpha-v1'})
    assert result['status'] == 'PASS'
    rid = result['result']['run_id']
    child = store.one('SELECT * FROM runs WHERE id=?', (rid,))
    assert child['kind'] == 'reparse'
    assert child['status'] == 'queued'
    assert json.loads(child['payload'])['index_dense'] is False
    assert json.loads(child['payload'])['provider_budget'] == 0
    assert result['result']['parse_id'] != 'alpha-v1'
    assert store.one('SELECT text FROM blocks WHERE id=?', ('alpha-v1:0:0',))['text'].endswith('eight GPUs.')
    audit = registry.execute_tool(context('audit'), 'audit_research_question', {'version_id': 'alpha-v1', 'block_id': 'alpha-v1:0:0', 'question': 'Does a later paper cover this suggestion?'})
    assert audit['status'] == 'BLOCKED'
    assert len(checkpoint()['tool_registry']['child_run_ids']) == 2
    before = len(store.rows('SELECT * FROM runs'))
    assert registry.execute_tool(context('third'), 'parse_document', {'version_id': 'alpha-v1'})['code'] == 'budget_exhausted'
    assert len(store.rows('SELECT * FROM runs')) == before


def test_audit_plan_is_atomically_blocked_and_worker_cannot_pick_it():
    result = registry.execute_tool(context(), 'audit_research_question', {'version_id': 'alpha-v1', 'block_id': 'alpha-v1:0:0', 'question': 'Fixture old suggestion'})
    assert result['status'] == 'BLOCKED'
    plan = store.one('SELECT * FROM runs WHERE id=?', (result['result']['run_id'],))
    assert plan['kind'] == 'audit'
    assert plan['status'] == 'blocked'
    assert 'provider_budget=0' in plan['error']
    assert json.loads(plan['payload'])['provider_budget'] == 0
    assert jobs.work_once() is False
    assert not store.rows('SELECT * FROM quota')


def test_cancelled_parent_starts_nothing_and_cancels_own_new_child(monkeypatch):
    store.execute("UPDATE runs SET status='cancelled' WHERE id='run-alpha'")
    result = registry.execute_tool(context(), 'save_artifact', note())
    assert result['code'] == 'cancelled'
    assert not store.rows('SELECT * FROM artifacts')
    store.execute("UPDATE runs SET status='running' WHERE id='run-alpha'")
    original = snapshots.queue_parse

    def cancel_during_queue(*args, **kwargs):
        result = original(*args, **kwargs)
        store.execute("UPDATE runs SET status='cancelled' WHERE id='run-alpha'")
        return result

    monkeypatch.setattr(snapshots, 'queue_parse', cancel_during_queue)
    result = registry.execute_tool(context(), 'parse_document', {'version_id': 'alpha-v1'})
    assert result['status'] == 'BLOCKED'
    assert result['code'] == 'cancelled'
    child = checkpoint()['tool_registry']['child_run_ids'][0]
    assert store.one('SELECT status FROM runs WHERE id=?', (child,))['status'] == 'cancelled'
    assert store.one('SELECT status FROM runs WHERE id=?', ('run-beta',))['status'] == 'running'


def test_csv_stats_dataset_scope_and_fixed_chart_adapter(monkeypatch):
    stats = registry.execute_tool(context(), 'compute_csv_stats', {'csv_text': 'round,value\n1,2\n2,\n3,8\n4,bad\n'})
    assert stats['status'] == 'PASS'
    data = stats['result']
    assert data['statistics']['value'] == {'count': 2, 'sum': 10.0, 'mean': 5.0, 'min': 2.0, 'max': 8.0, 'missing_count': 1, 'invalid_count': 1}
    called = []

    def fixture_chart(workspace, filename, content, spec):
        called.append((workspace, filename, content, spec))
        aid = store.artifact(workspace, None, 'chart', 'Fixture renderer contract', {})
        return {'artifact_id': aid, 'notice': 'Fixture adapter, not a live chart test'}

    monkeypatch.setattr(registry.charts, 'create_chart', fixture_chart)
    result = registry.execute_tool(context(), 'render_chart', {'dataset_artifact_id': data['dataset_artifact_id'], 'spec': {'kind': 'line', 'x': 'round', 'y': ['value']}})
    assert result['status'] == 'PASS'
    assert called[0][0] == 'alpha'
    assert b'3,8' in called[0][2]
    assert store.one('SELECT run_id FROM artifacts WHERE id=?', (result['result']['artifact_id'],))['run_id'] == 'run-alpha'
    bad = registry.execute_tool(context(), 'render_chart', {'dataset_artifact_id': data['dataset_artifact_id'], 'spec': {'shell': 'not allowed'}})
    assert bad['code'] == 'invalid_arguments'


@pytest.mark.parametrize('content', ['a,a\n1,2\n', 'a,b\n1\n', 'a,b\n', 'a,b\n1,2,3\n', 'a,b\n1,\x00\n'])
def test_invalid_csv_is_not_silently_repaired(content):
    result = registry.execute_tool(context(), 'compute_csv_stats', {'csv_text': content})
    assert result['status'] == 'FAIL'
    assert not store.rows("SELECT * FROM artifacts WHERE kind='csv_dataset'")


def test_search_and_fixed_host_fetch_without_caller_urls(monkeypatch):
    paper = {'source': 'arxiv', 'metadata_verified': True, 'arxiv_id': '1234.56789v2', 'identity': 'arxiv:1234.56789', 'pdf_url': 'http://169.254.169.254/evil'}
    monkeypatch.setattr(research, 'search_papers', lambda *args, **kwargs: {'results': [paper], 'cached': False, 'errors': [], 'searched_at': 1})
    result = registry.execute_tool(context(), 'search_papers', {'query': 'Fixture search', 'limit': 1})
    search_aid = result['result']['artifact_id']
    calls = []

    def fixture_fetch(url, max_bytes):
        calls.append((url, max_bytes))
        return {'content': b'%PDF-fixture-only', 'url': url}

    monkeypatch.setattr(research, 'fetch_public', fixture_fetch)
    upload_calls = []

    def fixture_upload(workspace, filename, content, index_dense=True):
        upload_calls.append(index_dense)
        return {'document': {'id': 'alpha-v1'}, 'duplicate': True, 'run_id': 'run-alpha'}

    monkeypatch.setattr(documents, 'upload_document', fixture_upload)
    fetched = registry.execute_tool(context(), 'fetch_document', {'search_artifact_id': search_aid, 'paper_index': 0})
    assert fetched['status'] == 'PASS'
    assert calls == [('https://arxiv.org/pdf/1234.56789v2', 20 * 1024 * 1024)]
    assert upload_calls == [False]
    assert checkpoint()['tool_registry']['child_run_ids'] == []  # never acquire another/shared job
    rejected = registry.execute_tool(context(), 'fetch_document', {'url': 'http://127.0.0.1/'})
    assert rejected['code'] == 'invalid_arguments'


def test_fetch_uses_existing_dns_pinned_ssrf_safe_downloader(monkeypatch):
    # Candidate is valid, but DNS is malicious. Use the real safe fetch function;
    # rejection occurs before any transport request or provider invocation.
    payload = {'results': [{'source': 'arxiv', 'metadata_verified': True, 'arxiv_id': '1234.56789'}]}
    aid = store.artifact('alpha', 'run-alpha', 'paper_search', 'fixture', payload)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('127.0.0.1', 443))])
    # The fixture saved the original implementation before autouse replaced it.
    monkeypatch.setattr(research, 'fetch_public', REAL_FETCH)
    result = registry.execute_tool(context(), 'fetch_document', {'search_artifact_id': aid, 'paper_index': 0})
    assert result['status'] == 'FAIL'
    assert not store.rows("SELECT * FROM runs WHERE kind='parse'")


REAL_FETCH = research.fetch_public


def test_parent_cancel_propagates_to_previously_queued_children():
    queued = registry.execute_tool(context(), 'parse_document', {'version_id': 'alpha-v1'})
    rid = queued['result']['run_id']
    store.execute("UPDATE runs SET status='cancelled' WHERE id='run-alpha'")
    assert registry.execute_tool(context(), 'save_artifact', note())['code'] == 'cancelled'
    assert store.one('SELECT status FROM runs WHERE id=?', (rid,))['status'] == 'cancelled'
    assert store.one('SELECT status FROM runs WHERE id=?', ('run-beta',))['status'] == 'running'


def test_resource_caps_reject_work_before_side_effects():
    invalid = registry.execute_tool(context(), 'search_papers', {'query': 'x', 'limit': 11})
    assert invalid['code'] == 'invalid_arguments'
    csv_result = registry.execute_tool(context(), 'compute_csv_stats', {'csv_text': 'x,y\n' + '1,2\n' * 2001})
    assert csv_result['code'] == 'resource_limit'
    store.execute('UPDATE blocks SET text=? WHERE id=?', ('x' * 500001, 'alpha-v1:0:0'))
    diff = registry.execute_tool(context(), 'compare_versions', {'left': 'alpha-v1', 'right': 'alpha-v2'})
    assert diff['code'] == 'resource_limit'
    assert not store.rows("SELECT * FROM artifacts WHERE kind='csv_dataset'")
