"""Deterministic fixture tests; these do not claim upstream live availability."""
import json
import socket
import subprocess
import sys

import pytest

from services.api import store
from services.api.charts import PLOT_SCRIPT, artifact_file, create_chart
from services.api.research import build_graph, search_papers, validate_public_url


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()
    return tmp_path


@pytest.mark.parametrize('url', ['http://127.0.0.1/', 'http://169.254.169.254/latest/meta-data', 'http://[::1]/', 'file:///etc/passwd', 'http://user:pass@example.com/', 'https://example.com:8080/', 'http://10.0.0.1'])
def test_ssrf_private_and_unsafe(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_ssrf_mixed_public_private_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443)), (2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='禁止'):
        validate_public_url('https://public-name.example/')


def test_plot_template_compiles():
    compile(PLOT_SCRIPT, 'plot.py', 'exec')


def test_two_csvs_are_real_distinct_figures_and_reproduce(tmp_path):
    first = create_chart('alpha', 'new1.csv', b'epoch,score\n1,2\n2,5\n3,3\n', {'kind': 'line', 'x': 'epoch', 'y': ['score'], 'title': 'First'})
    second = create_chart('alpha', 'new2.csv', b'batch,value\nA,7\nB,8\nC,1\n', {'kind': 'bar', 'x': 'batch', 'y': ['value'], 'title': 'Second'})
    assert first['spec']['x_scale'] == 'numeric'
    assert second['spec']['x_scale'] == 'categorical'
    assert first['statistics']['score']['max'] == 5
    assert first['statistics']['score']['delta'] == 1
    assert second['statistics']['value']['max'] == 8
    first_png = artifact_file('alpha', first['artifact_id'], 'chart.png')
    second_png = artifact_file('alpha', second['artifact_id'], 'chart.png')
    assert first_png.read_bytes() != second_png.read_bytes()
    directory = first_png.parent
    repro = tmp_path / 'reproduced'
    subprocess.run([sys.executable, str(directory / 'plot.py'), str(directory / 'input.csv'), str(directory / 'spec.json'), str(repro)], check=True, timeout=40)
    assert (repro / 'chart.svg').is_file()
    with pytest.raises(ValueError, match='权限'):
        artifact_file('beta', first['artifact_id'], 'chart.png')
    with pytest.raises(ValueError):
        artifact_file('alpha', first['artifact_id'], '../input.csv')


def test_missing_gb18030_and_numeric_diagnostics():
    raw = '轮次,数值\n一,2\n二,\n三,异常\n四,8\n'.encode('gb18030')
    result = create_chart('alpha', '中文.csv', raw, {'kind': 'line', 'x': '轮次', 'y': ['数值']})
    assert result['encoding'] == 'gb18030'
    assert result['statistics']['数值']['missing_count'] == 1
    assert result['statistics']['数值']['invalid_count'] == 1
    assert result['statistics']['数值']['max'] == 8
    assert result['warnings']


def test_no_eval_or_shell_from_csv(tmp_path):
    marker = tmp_path / 'ATTACK_SUCCEEDED'
    content = f'label,value\n"__import__(\'pathlib\').Path(\'{marker}\').touch()",4\nnormal,8\n'.encode()
    result = create_chart('alpha', 'malicious.csv', content, {'kind': 'bar', 'x': 'label', 'y': ['value']})
    assert not marker.exists()
    assert result['statistics']['value']['max'] == 8
    with pytest.raises(ValueError):
        create_chart('alpha', '../attack.csv', content, {'kind': 'bar'})
    with pytest.raises(ValueError):
        create_chart('alpha', 'attack.csv', content, {'kind': 'shell'})


def test_radar_and_three_d():
    radar = create_chart('alpha', 'radar.csv', b'method,p,r,s\nA,.8,.6,12\nB,.7,.9,9\n', {'kind': 'radar', 'x': 'method', 'y': ['p', 'r', 's']})
    assert radar['warnings']
    three_d = create_chart('alpha', 'three.csv', b'x,y,z\n1,2,3\n2,4,6\n', {'kind': '3d', 'x': 'x', 'y': ['y'], 'z': 'z'})
    assert artifact_file('alpha', three_d['artifact_id'], 'chart.png').is_file()
    with pytest.raises(ValueError, match='三维图'):
        create_chart('alpha', 'bad.csv', b'x,y\nA,3\nB,4\n', {'kind': '3d', 'x': 'x', 'y': ['y'], 'z': 'x'})


def test_graph_has_only_actual_reference_edges():
    for wid, title, identity in [('a', 'A reliable long research paper', 'doi:10.1234/a'), ('b', 'An unrelated different research paper', 'doi:10.1234/b'), ('c', 'Disconnected useful research paper', 'doi:10.1234/c')]:
        store.execute('INSERT INTO works VALUES(?,?,?,?,?)', (wid, 'alpha', title, identity, json.dumps({'metadata_verified': True})))
    store.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,created) VALUES(?,?,?,?,?,?,?,?,?)', ('av', 'alpha', 'a', 'A', 'a.pdf', 'sha', '/unused', 'ready', 1))
    store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)', ('ref1', 'alpha', 'av', 'block1', 3, '[1]', 'B. An unrelated different research paper. doi:10.1234/b', 'doi:10.1234/b', '{}'))
    graph = build_graph('alpha')
    assert len(graph['nodes']) == 3
    assert len(graph['edges']) == 1
    assert graph['edges'][0]['ref_id'] == 'ref1'
    assert graph['edges'][0]['source'] == 'a'
    assert graph['edges'][0]['target'] == 'b'
    assert abs(sum(n['rank'] for n in graph['nodes']) - 1) < 1e-8
    assert build_graph('beta')['nodes'] == []


def test_short_title_needs_first_author_and_year_to_become_an_edge():
    # "Attention Is All You Need" is too short to be distinctive on its own.
    for wid, title in [('t', 'Attention Is All You Need'), ('s', 'Bidirectional encoder pretraining study')]:
        store.execute('INSERT INTO works VALUES(?,?,?,?,?)', (wid, 'gamma', title, 'local:' + wid, '{}'))
        store.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,created) VALUES(?,?,?,?,?,?,?,?,?)', (wid + 'v', 'gamma', wid, title, wid + '.pdf', 'sha' + wid, '/unused', 'ready', 1))
    card = {'authors': [{'name': 'Ashish Vaswani'}], 'year': {'value': 2017}}
    store.execute('INSERT INTO document_cards VALUES(?,?,?,?,?,?)', ('tv', 'p', 'gamma', json.dumps(card), 1, 1))
    refs = [('good', 'Ashish Vaswani, Noam Shazeer, et al. 2017. Attention is all you need. In NIPS.'),
            ('wrong-year', 'J. Doe and A. Vaswani. 2019. Attention is all you need for tables.'),
            ('no-author', 'A. Writer. 2017. Why attention is all you need, revisited.')]
    for ref_id, text in refs:
        store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)', (ref_id, 'gamma', 'sv', 'b-' + ref_id, 9, '[1]', text, None, '{}'))
    graph = build_graph('gamma')
    assert [(e['ref_id'], e['target'], e['method']) for e in graph['edges']] == [('good', 't', 'reference_title_first_author_year')]


def test_feedback_reorders_cached_candidates(monkeypatch):
    from services.api import research
    candidates = [{'identity': 'doi:10.1234/a', 'title': 'A paper about research', 'abstract': '', 'reason': 'fixture'}, {'identity': 'doi:10.1234/b', 'title': 'A second paper about research', 'abstract': '', 'reason': 'fixture'}]
    monkeypatch.setattr(research, '_crossref', lambda *a: candidates)
    before = search_papers('alpha', 'research', ['crossref'])
    assert before['results'][0]['identity'].endswith('/a')
    store.execute('INSERT INTO feedback VALUES(?,?,?)', ('alpha', 'doi:10.1234/b', 1))
    after = search_papers('alpha', 'research', ['crossref'])
    assert after['cached']
    assert after['results'][0]['identity'].endswith('/b')
    store.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?)', ('alpha', 'doi:10.1234/a', -1))
    assert len(search_papers('alpha', 'research', ['crossref'])['results']) == 1


def test_redirect_revalidates_and_dns_is_pinned(monkeypatch):
    from services.api import research
    calls = []
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **k: [(2, 1, 6, '', ('127.0.0.1' if host == '127.0.0.1' else '93.184.216.34', 443))])

    class Response:
        status_code = 302
        def __init__(self):
            self.headers = {'location': 'http://127.0.0.1/private'}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def stream(self, method, url, **kwargs):
            calls.append((url, kwargs))
            return Response()
    monkeypatch.setattr(research.httpx, 'Client', Client)
    with pytest.raises(ValueError, match='禁止'):
        research.fetch_public('https://safe.example/paper.pdf')
    assert len(calls) == 1
    assert calls[0][0].host == '93.184.216.34'
    assert calls[0][1]['headers']['Host'] == 'safe.example'
    assert calls[0][1]['extensions']['sni_hostname'] == 'safe.example'


def test_watch_check_persists_and_deduplicates(monkeypatch):
    from services.api import research
    now = 12345
    store.execute('INSERT INTO watches VALUES(?,?,?,?,?,?,?,?)', ('watch1', 'alpha', 'research', 0, 24, None, now, '[]'))
    monkeypatch.setattr(research, 'search_papers', lambda *a, **k: {'results': [{'identity': 'doi:10.1234/a', 'title': 'A'}], 'errors': [], 'cached': False})
    first = research.check_watch('alpha', 'watch1')
    second = research.check_watch('alpha', 'watch1')
    assert first['new_identities'] == ['doi:10.1234/a']
    assert second['new_identities'] == []
    watch = store.one('SELECT * FROM watches WHERE id=?', ('watch1',))
    assert watch['enabled'] == 0  # manual immediate check does not turn on scheduling
    assert watch['last_checked']
    assert len(store.rows('SELECT * FROM runs WHERE workspace=?', ('alpha',))) == 2
    with pytest.raises(ValueError):
        research.check_watch('beta', 'watch1')


def test_short_title_without_a_card_uses_the_papers_first_page_and_arxiv_year():
    store.execute('INSERT INTO works VALUES(?,?,?,?,?)', ('t2', 'delta', 'Attention Is All You Need', 'arxiv:1706.03762', json.dumps({'arxiv_id': '1706.03762'})))
    store.execute('INSERT INTO works VALUES(?,?,?,?,?)', ('s2', 'delta', 'A citing paper with a long enough title', 'local:s2', '{}'))
    for wid in ('t2', 's2'):
        store.execute('INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,status,created) VALUES(?,?,?,?,?,?,?,?,?)', (wid + 'v', 'delta', wid, wid, wid + '.pdf', 'sha-' + wid, '/unused', 'ready', 1))
    store.execute('INSERT INTO blocks VALUES(?,?,?,?,?,?,?,?,?,?,?)', ('fp', 'delta', 't2v', 0, '[0,0,1,1]', 'paragraph', 1, 'Ashish Vaswani∗ Google Brain avaswani@google.com', 'native', 'ok', '{}'))
    refs = [('good', '[VSP + 17] Ashish Vaswani, Noam Shazeer, and Niki Parmar. Attention is all you need. In NIPS, 2017.'),
            ('initials', '[62] A. Vaswani, N. Shazeer, and N. Parmar. Attention is all you need. In NIPS, 2017.'),
            ('other-author', 'J. Doe, A. Vaswani. Attention is all you need, again. 2017.'),
            ('other-year', 'Ashish Vaswani. Attention is all you need. Talk, 2020.')]
    for ref_id, text in refs:
        store.execute('INSERT INTO refs VALUES(?,?,?,?,?,?,?,?,?)', (ref_id, 'delta', 's2v', 'b-' + ref_id, 5, '[1]', text, None, '{}'))
    edges = build_graph('delta')['edges']
    assert sorted((e['ref_id'], e['target'], e['method']) for e in edges) == [('good', 't2', 'reference_title_first_author_year'), ('initials', 't2', 'reference_title_first_author_year')]
