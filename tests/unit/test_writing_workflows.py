"""Explicit offline fixtures: no keys, real provider, GPU or main services."""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api import jobs, models, research, store, writing_workflows as writing


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    monkeypatch.setenv('RT_DISABLE_DENSE', 'true')
    # Any accidentally unmocked network is a test failure, never a live request.
    monkeypatch.setattr(models, 'client', lambda: pytest.fail('Unexpected real provider request'))
    monkeypatch.setattr(research, 'fetch_public', lambda *a, **kw: pytest.fail('Unexpected real discovery request'))


def paper(vid='v1', workspace='w', work=None, blocks=4):
    work = work or 'work-' + vid
    store.execute('INSERT OR IGNORE INTO works VALUES(?,?,?,?,?)', (work, workspace, 'Study ' + vid, 'arxiv:2001.00001' if vid == 'v1' else 'arxiv:2001.00002', '{}'))
    store.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (vid, workspace, work, 'Study ' + vid, vid+'.pdf', vid, 'unused.pdf', 'ready', '{}', time.time()))
    store.execute('INSERT INTO parses(id,version_id,workspace,engine,device,status,page_count,created) VALUES(?,?,?,?,?,?,?,?)', (vid, vid, workspace, 'fixture', 'cpu', 'ready', blocks, time.time()))
    store.execute('INSERT INTO active_parses VALUES(?,?)', (vid, vid))
    for i in range(blocks):
        store.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (vid+f'-b{i}', workspace, vid, i, '[0.1,0.1,0.8,0.8]', 'paragraph', i,
             f'The approach uses eight GPUs for training with attention modules. Detail {i}.', 'fixture', 'test', '{}'))
    return vid


def run_for(workflow='survey', ids=None, question='attention architecture'):
    p = writing.WritingRequest(question=question, version_ids=ids or ['v1'], idempotency_key=store.uid())
    queued = writing._queue(p, {'workspace': 'w'}, workflow)
    run = store.one('SELECT * FROM runs WHERE id=?', (queued['id'],))
    run['payload'] = json.loads(run['payload'])
    return run


def manuscript(block, kind='survey', refs=None, bad_number=False):
    claims, sections = [], []
    for i, (key, _) in enumerate(writing.SECTIONS[kind]):
        text = '80 GPUs' if bad_number else 'eight GPUs'
        claims.append({'id': f'c{i}', 'text': text, 'type': 'source_fact', 'evidence': [{'block_id': block['id'], 'quote': 'eight GPUs'}]})
        sections.append({'key': key, 'claim_ids': [f'c{i}']})
    return {'claims': claims, 'sections': sections, 'reference_ids': refs or [],
            'answer_segments': [{'text': c['text'], 'claim_ids': [c['id']]} for c in claims]}


def response(data, model='fixture-Hydrogen'):
    return {'text': json.dumps(data), 'model': model, 'usage': {'input_tokens': 100, 'output_tokens': 100}}


def verified(identity='arxiv:2001.00001'):
    return {'identity': identity, 'source': 'arxiv', 'metadata_verified': True,
            'metadata_source_url': 'https://export.arxiv.org/api/query?id_list=2001.00001',
            'metadata_fetched_at': 1, 'metadata_source_sha256': 'fixture-provenance',
            'title': 'Verified title', 'authors': ['Real Author'], 'year': 2020, 'url': 'https://arxiv.org/abs/2001.00001'}


def test_queue_scope_idempotency_snapshot_pinning():
    paper(); paper('other', workspace='foreign')
    req = writing.WritingRequest(question='topic', version_ids=['v1'], idempotency_key='same')
    first = writing.start_survey(req, {'workspace': 'w'})
    store.execute('UPDATE active_parses SET parse_id=? WHERE version_id=?', ('new-parse', 'v1'))
    assert writing.start_survey(req, {'workspace': 'w'})['id'] == first['id']
    assert json.loads(store.one('SELECT payload FROM runs WHERE id=?', (first['id'],))['payload'])['snapshots'][0]['parse_id'] == 'v1'
    with pytest.raises(Exception, match='文档不存在|422'):
        writing.start_survey(req.model_copy(update={'version_ids': ['other'], 'idempotency_key': 'foreign'}), {'workspace': 'w'})


def test_twenty_papers_reserve_slots_and_budget():
    ids = [paper('v' + str(i), blocks=12) for i in range(20)]
    run = run_for(ids=ids)
    packed = writing.collect_evidence(run)
    assert len(packed['coverage']) == 20
    assert all(c['candidate_slots'] >= 2 for c in packed['coverage'])
    assert packed['used_context_bytes'] <= 48000
    assert {b['version_id'] for b in packed['blocks']} == set(ids)
    assert all(b['parse_id'] == b['version_id'] for b in packed['blocks'])


def test_reparse_keeps_old_original_blocks():
    paper(); run = run_for()
    store.execute('UPDATE active_parses SET parse_id=? WHERE version_id=?', ('new-snapshot', 'v1'))
    packed = writing.collect_evidence(run)
    assert packed['blocks'] and all(b['parse_id'] == 'v1' for b in packed['blocks'])


@pytest.mark.parametrize('mutation', ['blank', 'numbers', 'unbound', 'fake_ref', 'unknown_section', 'duplicate_claim'])
def test_manuscript_fail_closed_or_rebinds(mutation):
    paper(); run = run_for()
    block = writing.collect_evidence(run)['blocks'][0]
    data = manuscript(block)
    if mutation == 'blank': data['claims'][0]['evidence'][0]['quote'] = '  '
    if mutation == 'numbers': data['claims'][0]['text'] = '80 GPUs'
    if mutation == 'fake_ref': data['reference_ids'] = ['fake']
    if mutation == 'unknown_section': data['sections'][0]['key'] = 'hallucinated'
    if mutation == 'duplicate_claim': data['sections'][1]['claim_ids'] = ['c0']
    if mutation == 'unbound':
        data['answer_segments'][0]['text'] = '80 GPUs and an invented cost'
        result = writing.validate_manuscript(data, [block], 'w', ['v1'], 'survey', [])
        assert '80 GPUs' not in result['answer'] and 'invented cost' not in result['answer']
        return
    with pytest.raises(ValueError):
        writing.validate_manuscript(data, [block], 'w', ['v1'], 'survey', [])


def test_survey_reviewed_sections_bound_after_critic_and_resume(monkeypatch):
    paper(); run = run_for()
    block = writing.collect_evidence(run)['blocks'][0]
    calls = []
    def generate(system, prompt, rid, **kw):
        calls.append(kw['role'])
        return response(manuscript(block))
    monkeypatch.setattr(models, 'generate', generate)
    def critic(run, result, *args):
        from services.api.evidence_validation import apply_semantic_review
        return apply_semantic_review(result, {'reviews': [{'claim_id': c['id'], 'status': 'insufficient', 'reason': 'fixture contradiction'} for c in result['claims']]})
    monkeypatch.setattr(writing, 'review_live', critic)
    result = writing.survey(run)
    assert calls == ['deep']
    assert result['status'] == 'partial'
    assert all(s['text'].startswith('该项主张未获原文支持') for s in result['sections'])
    assert all(c['type'] == 'insufficient' for s in result['sections'] for c in s['source_claims'])
    again = writing.survey(run)
    assert again['artifact_id'] == result['artifact_id']
    assert calls == ['deep']
    assert store.one('SELECT count(*) n FROM artifacts')['n'] == 1
    assert store.one('SELECT count(*) n FROM claims')['n'] == 5


def test_received_invalid_json_checkpoint_prevents_rebill(monkeypatch):
    paper(); run = run_for()
    calls = []
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: (calls.append(1) or {'text': 'invalid JSON', 'model': 'fixture', 'usage': {}}))
    for _ in range(2):
        with pytest.raises(ValueError): writing.survey(run)
    assert calls == [1]
    assert writing._snapshot(run)['writing_response']['text'] == 'invalid JSON'


def test_received_display_titles_are_verified_without_dropping_other_fields():
    paper(); run = run_for(); block = writing.collect_evidence(run)['blocks'][0]
    data = manuscript(block)
    for section in data['sections']:
        section['title'] = dict(writing.SECTIONS['survey'])[section['key']]
    result = writing.validate_manuscript(data, [block], 'w', ['v1'], 'survey', [])
    assert result['sections'][0]['title'] == '研究问题'
    assert data['sections'][0]['title'] == '研究问题'  # retained received receipt
    data['sections'][0]['title'] = '80 GPUs'
    with pytest.raises(ValueError, match='标题'):
        writing.validate_manuscript(data, [block], 'w', ['v1'], 'survey', [])
    data['sections'][0]['title'] = '研究问题'
    data['sections'][0]['extra_fact'] = '80 GPUs'
    with pytest.raises(ValueError):
        writing.validate_manuscript(data, [block], 'w', ['v1'], 'survey', [])


def test_unknown_send_resume_does_not_repeat(monkeypatch):
    paper(); run = run_for()
    calls = []
    def fail(*a, **kw):
        calls.append(1)
        raise models.ModelError('fixture transmission unknown')
    monkeypatch.setattr(models, 'generate', fail)
    with pytest.raises(models.ModelError): writing.survey(run)
    with pytest.raises(ValueError, match='不重发'): writing.survey(run)
    assert calls == [1]


def test_one_received_claim_repair_is_strict_and_does_not_regenerate(monkeypatch):
    paper(); run = run_for(); block = writing.collect_evidence(run)['blocks'][0]
    original = manuscript(block); original['claims'][0]['text'] = '80 GPUs'
    original['answer_segments'][0]['text'] = '80 GPUs'
    calls = []
    def generate(system, prompt, rid, **kwargs):
        calls.append(kwargs['role'])
        if kwargs['role'] == 'deep':return response(original)
        assert json.loads(prompt)['rejected'][0]['claim']['id'] == 'c0'
        return response({'claims': [manuscript(block)['claims'][0]]}, 'fixture-lite')
    monkeypatch.setattr(models, 'generate', generate)
    monkeypatch.setattr(writing, 'review_live', lambda run, result, *args: result)
    result = writing.survey(run)
    assert '80 GPUs' not in result['answer']
    assert calls == ['deep', 'light']
    assert writing._snapshot(run)['writing_response']['text'] == json.dumps(original)
    writing.survey(run)
    assert calls == ['deep', 'light']


def test_cancel_during_model_retains_receipt_no_artifact(monkeypatch):
    paper(); run = run_for(); block = writing.collect_evidence(run)['blocks'][0]
    def generate(*a, **kw):
        store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run['id'],))
        return response(manuscript(block))
    monkeypatch.setattr(models, 'generate', generate)
    assert writing.survey(run) == {}
    assert 'writing_response' in writing._snapshot(run)
    assert store.one('SELECT count(*) n FROM artifacts')['n'] == 0


def test_cancel_before_start_no_provider(monkeypatch):
    paper(); run = run_for()
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: pytest.fail('cancelled request called model'))
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (run['id'],))
    assert writing.handle(run) == {}


def test_outline_real_search_interface_bibliography_only_not_evidence(monkeypatch):
    paper(); run = run_for('outline'); block = writing.collect_evidence(run)['blocks'][0]
    calls = []
    def search(workspace, query, **kw):
        calls.append(kw['sources'])
        return {'results': [verified(), verified('arxiv:2002.00002'), {'identity': 'doi:fake', 'title': 'Fabricated'}], 'errors': []}
    monkeypatch.setattr(research, 'search_papers', search)
    prompts = []
    def generate(system, prompt, rid, **kw):
        prompts.append(json.loads(prompt))
        assert kw['role'] == 'deep'
        return response(manuscript(block, 'outline', ['R1', 'R2']))
    monkeypatch.setattr(models, 'generate', generate)
    result = writing.outline(run)
    assert calls == [['arxiv', 'crossref']]
    assert len(result['bibliography']) == 2
    assert result['bibliography'][1]['fulltext_status'] == 'bibliography_only'
    assert 'abstract' not in prompts[0]['verified_reference_records'][1]
    assert all(e['version_id'] == 'v1' for c in result['claims'] for e in c['evidence'])
    writing.outline(run)
    assert len(prompts) == len(calls) == 1


def test_outline_without_selected_papers_searches_local_library(monkeypatch):
    paper()
    req = writing.WritingRequest(question='attention', version_ids=[], idempotency_key='library')
    queued = writing.start_outline(req, {'workspace': 'w'})
    p = json.loads(store.one('SELECT payload FROM runs WHERE id=?', (queued['id'],))['payload'])
    assert p['version_ids'] == [] and [v['id'] for v in p['snapshots']] == ['v1']


def test_diagram_compiles_four_actual_sources_no_execution(monkeypatch):
    paper(); run = run_for('diagram')
    graph = {'nodes': [{'id': 'Input', 'label': '输入数据'}, {'id': 'Encoder', 'label': 'Attention 编码器'}],
             'edges': [{'source': 'Input', 'target': 'Encoder', 'label': '特征'}]}
    roles = []
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: (roles.append(kw['role']) or response(graph, 'fixture-Flash36')))
    result = writing.diagram(run)
    assert roles == ['answer']
    assert set(result['sources']) == {'mermaid', 'dot', 'tikz', 'matplotlib'}
    assert all('Attention' in source for source in result['sources'].values())
    compile(result['sources']['matplotlib'], 'generated.py', 'exec')  # compile only, no execution
    assert 'Input -> Encoder' in result['sources']['dot']
    assert '\\draw[->] (Input) --' in result['sources']['tikz']
    assert writing.diagram(run)['artifact_id'] == result['artifact_id']
    assert roles == ['answer']


@pytest.mark.parametrize('label', ['<img src=x>', '\\input{secret}', 'https://example.com', '%%{init}', 'click A', 'bad\nline'])
def test_diagram_rejects_executable_or_external_labels(label):
    with pytest.raises(ValueError):
        writing.diagram_sources({'nodes': [{'id': 'A', 'label': label}, {'id': 'B', 'label': 'safe'}], 'edges': [{'source': 'A', 'target': 'B'}]})


def test_router_schema_scope_export_and_conflict():
    paper()
    app = FastAPI(); app.include_router(writing.router)
    app.dependency_overrides[writing.writing_session] = lambda: {'workspace': 'w', 'role': 'reviewer'}
    with TestClient(app) as client:
        body = {'question': 'topic', 'version_ids': ['v1'], 'idempotency_key': 'api'}
        first = client.post('/api/v1/writing/surveys', json=body)
        assert first.status_code == 200
        assert client.post('/api/v1/writing/surveys', json=body).json()['id'] == first.json()['id']
        assert client.post('/api/v1/writing/surveys', json={**body, 'question': 'changed'}).status_code == 422
        assert client.post('/api/v1/writing/outlines', json={**body, 'extra': True}).status_code == 422
        assert client.get('/api/v1/writing/artifacts/missing/export').status_code == 404
        aid = store.artifact('foreign', None, 'outline', 'private', {'answer': 'secret'})
        assert client.get('/api/v1/writing/artifacts/' + aid + '/export').status_code == 404


def test_local_graph_roles_no_fake_edges_or_quality_inference():
    for name in ['a', 'b', 'c', 'd', 'e', 'alone']:
        paper(name, blocks=0)
    def cite(source, target, no):
        store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)', (no, 'w', source, None, 0, '1', 'Citation', 'doi:10.1234/' + target, '{}'))
    for name in ['a', 'b', 'c', 'd', 'e', 'alone']:
        store.execute('UPDATE works SET identity=? WHERE id=?', ('doi:10.1234/' + name, 'work-' + name))
    for i, (source, target) in enumerate([('a', 'b'), ('b', 'c'), ('d', 'c'), ('e', 'c'), ('a', 'b')]): cite(source, target, str(i))
    graph = research.build_graph('w')
    nodes = {n['id'][5:]: n for n in graph['nodes']}
    assert nodes['c']['role'] == 'cornerstone'
    assert nodes['b']['role'] == 'bridge'
    assert nodes['a']['role'] == 'peripheral'
    assert nodes['alone']['role'] == 'isolated'
    assert nodes['a']['outdegree'] == 1  # duplicate provenance not a doubled graph edge
    assert nodes['b']['betweenness'] > 0
    assert '当前工作区' in graph['role_rules']['scope']
    assert len(graph['edges']) == 5  # original citation provenance retained


def test_review_unknown_does_not_repeat_on_resume(monkeypatch):
    paper(); run = run_for(); block = writing.collect_evidence(run)['blocks'][0]
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: response(manuscript(block)))
    calls = []
    def review(*a, **kw):
        calls.append(1)
        raise models.ModelError('fixture review interrupted')
    monkeypatch.setattr(writing, 'review_live', review)
    with pytest.raises(models.ModelError): writing.survey(run)
    result = writing.survey(run)
    assert result['status'] == 'partial' and calls == [1]
    assert '不重发' in result['publication_notice']


def test_outline_empty_library_is_only_proposal_no_fabricated_results(monkeypatch):
    queued = writing.start_outline(writing.WritingRequest(question='Research idea', idempotency_key='empty'), {'workspace': 'w'})
    run = store.one('SELECT * FROM runs WHERE id=?', (queued['id'],)); run['payload'] = json.loads(run['payload'])
    monkeypatch.setattr(research, 'search_papers', lambda *a, **kw: {'results': [verified()], 'errors': []})
    data = {'claims': [{'id': f'c{i}', 'text': '待验证研究计划，不包含已完成的实验结果', 'type': 'suggestion', 'evidence': []} for i in range(4)],
            'sections': [{'key': key, 'claim_ids': [f'c{i}']} for i, (key, _) in enumerate(writing.SECTIONS['outline'])], 'reference_ids': ['R1']}
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: response(data))
    result = writing.outline(run)
    assert result['status'] == 'partial' and len(result['sections']) == 4
    assert result['bibliography'][0]['fulltext_status'] == 'bibliography_only'
    assert all(c['type'] == 'suggestion' for c in result['claims'])


def test_scope_checked_again_after_document_deleted(monkeypatch):
    paper(); run = run_for(); writing.collect_evidence(run)
    store.execute('UPDATE versions SET deleted=1 WHERE id=?', ('v1',))
    with pytest.raises(ValueError, match='无权限'): writing.survey(run)


def test_manuscript_export_keeps_verified_record_and_quote(monkeypatch):
    paper(); run = run_for('outline'); block = writing.collect_evidence(run)['blocks'][0]
    monkeypatch.setattr(research, 'search_papers', lambda *a, **kw: {'results': [verified()], 'errors': []})
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: response(manuscript(block, 'outline', ['R1'])))
    result = writing.outline(run)
    exported = writing.export_writing(result['artifact_id'], 'md', {'workspace': 'w'}).body.decode()
    assert '## Abstract' in exported and 'eight GPUs' in exported and 'parse=v1' in exported
    assert 'Verified title' in exported and 'arxiv:2001.00001' in exported
    bib = writing.export_writing(result['artifact_id'], 'bib', {'workspace': 'w'}).body.decode()
    assert '@article{R1' in bib and 'Real Author' in bib


@pytest.mark.parametrize('field,value', [('authors', {'name': 'bad'}), ('year', 'not-a-year'), ('identity', 'arxiv:invented'), ('metadata_source_url', 'https://api.crossref.org.evil/works')])
def test_reference_record_schema_rejects_each_invalid_field(field, value):
    assert writing._verified_record({**verified(), field: value}) is None


def test_chinese_idea_english_search_plan_is_checkpointed(monkeypatch):
    paper(); run = run_for('outline', question='研究注意力证据检索')
    calls = []
    def generate(system, prompt, rid, **kw):
        calls.append(kw['role'])
        return response({'query': 'attention evidence retrieval'})
    monkeypatch.setattr(models, 'generate', generate)
    assert writing.planned_search_query(run) == 'attention evidence retrieval'
    assert writing.planned_search_query(run) == 'attention evidence retrieval'
    assert calls == ['light']


def test_outline_discovery_failure_is_visible_and_partial(monkeypatch):
    paper(); run = run_for('outline'); block = writing.collect_evidence(run)['blocks'][0]
    monkeypatch.setattr(research, 'search_papers', lambda *a, **kw: {'results': [], 'errors': [{'source': 'arxiv', 'error': 'fixture timeout'}]})
    monkeypatch.setattr(models, 'generate', lambda *a, **kw: response(manuscript(block, 'outline')))
    result = writing.outline(run)
    assert result['status'] == 'partial' and result['search']['errors']
    assert '检索未全部成功' in result['publication_notice']


def test_references_cannot_omit_known_cited_fulltext_record():
    paper(); run = run_for('outline'); block = writing.collect_evidence(run)['blocks'][0]
    reference = {**verified(), 'id': 'R1', 'version_id': 'v1'}
    with pytest.raises(ValueError, match='遗漏'):
        writing.validate_manuscript(manuscript(block, 'outline'), [block], 'w', ['v1'], 'outline', [reference])
