"""Version revision summary: grounded in the real diff, idempotent, never re-billed.
Fixture model only; no network."""
import json
import socket
import time

import pytest
from fastapi.testclient import TestClient

from services.api import app as module, documents, models, store
from services.api import version_summary as vs

OLD = ['Attention Is All You Need', 'We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.',
       'On the WMT 2014 English-to-German translation task our model achieves 28.4 BLEU.', 'Page 3']
NEW = ['Attention Is All You Need', 'We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.',
       'On the WMT 2014 English-to-German translation task our big model achieves 28.4 BLEU, and 41.8 BLEU on English-to-French after 3.5 days on eight GPUs.',
       'We also show the Transformer generalizes well to English constituency parsing with both large and limited training data.', 'Page 3']


@pytest.fixture
def api(tmp_path, monkeypatch):
    for target in (store, module, documents):
        monkeypatch.setattr(target, 'DATA', tmp_path)
    monkeypatch.setenv('RT_ACCESS_CODE', 'fixture-reviewer')
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('no network in this test'))
    monkeypatch.setattr(module, 'LOGIN_ATTEMPTS', {})  # the limiter is process-wide across tests
    with TestClient(module.app) as client:
        assert client.post('/api/v1/auth/login', json={'code': 'fixture-reviewer'}).status_code == 200
        yield client


def workspace():
    return store.one('SELECT workspace FROM sessions ORDER BY expires DESC LIMIT 1')['workspace']


def seed(ws, vid, label, number, texts):
    store.execute('INSERT INTO versions(id,workspace,title,filename,sha256,path,status,page_count,parsed_pages,label,metadata,created) '
                  'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (vid, ws, 'Attention Is All You Need', vid + '.pdf', vid, 'none.pdf', 'ready', 3, 3, label,
                   json.dumps({'arxiv_id': '1706.03762', 'arxiv_version': number}), time.time()))
    store.execute("INSERT OR IGNORE INTO parses(id,version_id,workspace,engine,device,status,page_count,created) VALUES(?,?,?,'native','cpu','ready',3,?)",
                  (vid, vid, ws, time.time()))
    store.execute('INSERT OR REPLACE INTO active_parses VALUES(?,?)', (vid, vid))
    for i, text in enumerate(texts):
        store.execute('INSERT INTO blocks(id,workspace,version_id,page_index,bbox,type,reading_order,text,source,quality) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (f'{vid}-{i}', ws, vid, min(i, 2), '[0,0,1,1]', 'paragraph', i, text, 'fixture', 'fixture'))


def test_selection_skips_trivial_changes_and_keeps_document_order():
    diff = {'changes': [
        {'kind': 'modified', 'before': {'text': 'Results are reported in Table 2 [12].', 'page_index': 1},
         'after': {'text': 'Results are reported in Table 2 [13].', 'page_index': 1}},
        {'kind': 'deleted', 'before': {'text': '3', 'page_index': 2}, 'after': None},
        {'kind': 'added', 'before': None, 'after': {'text': 'A new section on parsing experiments with substantial results.', 'page_index': 8}},
    ]}
    chosen = vs.select_changes(diff)
    assert [c['id'] for c in chosen] == ['c2'] and chosen[0]['new_page'] == 9


def test_uncited_or_foreign_points_are_dropped():
    supplied = [{'id': 'c1', 'kind': 'added', 'new_page': 4}]
    raw = json.dumps({'overall': '新增了实验。', 'points': [
        {'title': '新增句法分析实验', 'detail': '第 4 页新增。', 'change_ids': ['c1']},
        {'title': '编造', 'detail': '没有依据', 'change_ids': ['c99']},
        {'title': '无引用', 'detail': '没有依据', 'change_ids': []}]})
    overall, points = vs.validate(raw, supplied)
    assert overall == '新增了实验。' and [p['title'] for p in points] == ['新增句法分析实验']
    assert points[0]['refs'] == [{'id': 'c1', 'kind': 'added', 'new_page': 4}]
    assert vs.validate('{not json', supplied) == ('', [])


def test_summary_is_chronological_grounded_idempotent_and_not_rebilled(api, monkeypatch):
    ws = workspace()
    seed(ws, 'v7', 'v7', 7, NEW)
    seed(ws, 'v1', 'v1', 1, OLD)
    calls = []

    def generate(system, prompt, rid, core=True, role=None, **_):
        calls.append({'role': role, 'prompt': prompt})
        changes = json.loads(prompt.split('Changes:\n', 1)[1])
        return {'model': 'FIXTURE_NOT_LIVE', 'text': json.dumps({'overall': 'v7 补充了实验结果。', 'points': [
            {'title': '补充英法翻译结果', 'detail': '新增 41.8 BLEU。', 'change_ids': [changes[0]['id']]}]})}

    monkeypatch.setattr(models, 'generate', generate)
    # The dialog passes (existing v7, uploaded v1); the summary still reads v1 -> v7.
    first = api.post('/api/v1/versions/summary', json={'left': 'v7', 'right': 'v1'}).json()
    again = api.post('/api/v1/versions/summary', json={'left': 'v1', 'right': 'v7'}).json()
    assert again['id'] == first['id'] and again.get('reused')
    run = store.one('SELECT * FROM runs WHERE id=?', (first['id'],))
    assert json.loads(run['payload']) == {'older': 'v1', 'newer': 'v7', 'order_known': True}
    result = vs.handle({**run, 'payload': json.loads(run['payload'])})
    assert calls and calls[0]['role'] == 'deep' and 'Older version: v1. Newer version: v7.' in calls[0]['prompt']
    assert result['labels'] == {'older': 'v1', 'newer': 'v7'} and result['points'][0]['refs'][0]['new_page'] >= 1
    assert result['model'] == 'FIXTURE_NOT_LIVE' and 'status' not in result


def test_identical_versions_need_no_model_call(api, monkeypatch):
    ws = workspace()
    seed(ws, 'a', 'v2', 2, OLD)
    seed(ws, 'b', 'v3', 3, OLD)
    monkeypatch.setattr(models, 'generate', lambda *a, **k: pytest.fail('nothing to summarize'))
    run = store.one('SELECT * FROM runs WHERE id=?', (api.post('/api/v1/versions/summary', json={'left': 'a', 'right': 'b'}).json()['id'],))
    result = vs.handle({**run, 'payload': json.loads(run['payload'])})
    assert result['status'] == 'partial' and result['points'] == [] and '无需总结' in result['reason']


def test_other_workspace_versions_are_not_found(api):
    store.execute("INSERT INTO versions(id,workspace,title,filename,sha256,path,status,created) VALUES('x','other','t','x.pdf','x','none.pdf','ready',0)")
    seed(workspace(), 'mine', 'v1', 1, OLD)
    assert api.post('/api/v1/versions/summary', json={'left': 'mine', 'right': 'x'}).status_code == 404


def test_a_successful_retry_is_what_the_next_request_shows(api):
    ws = workspace()
    seed(ws, 'v7', 'v7', 7, NEW)
    seed(ws, 'v1', 'v1', 1, OLD)
    first = api.post('/api/v1/versions/summary', json={'left': 'v1', 'right': 'v7'}).json()
    store.execute("UPDATE runs SET status='failed' WHERE id=?", (first['id'],))  # provider 503
    retry = api.post('/api/v1/versions/summary', json={'left': 'v1', 'right': 'v7', 'retry': 1}).json()
    assert retry['id'] != first['id']
    # Still running: a plain request returns the failed original (the UI offers retry).
    assert api.post('/api/v1/versions/summary', json={'left': 'v1', 'right': 'v7'}).json()['id'] == first['id']
    store.execute("UPDATE runs SET status='completed' WHERE id=?", (retry['id'],))
    shown = api.post('/api/v1/versions/summary', json={'left': 'v7', 'right': 'v1'}).json()
    assert shown['id'] == retry['id'] and shown['reused']
