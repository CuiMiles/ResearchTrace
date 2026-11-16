"""Deterministic security/contract fixtures; live evidence comes from the probe."""
import hashlib
import json
import socket
import ssl

import httpx
import pytest

from services.api import research, store

RESOLVER = 'https://dns.google/resolve'
PUBLIC = '93.184.216.34'
PUBLIC6 = '2606:4700:4700::1111'


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.delenv('RT_PUBLIC_DNS_RESOLVER', raising=False)
    monkeypatch.delenv('RT_PUBLIC_PROXY', raising=False)
    monkeypatch.delenv('RT_PROXY', raising=False)
    store.migrate()


def mock_http(monkeypatch, handler):
    original = httpx.Client
    clients = []

    def client(**kwargs):
        clients.append(kwargs)
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        assert kwargs['verify'] is not False
        return original(transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr(research.httpx, 'Client', client)
    return clients


def dns_answer(request, address=PUBLIC):
    kind = int(request.url.params['type'])
    return httpx.Response(200, json={'Status': 0, 'Answer': [{'type': 1, 'data': address}] if kind == 1 else []})


def candidate():
    return {'identity': 'doi:10.1234/fixture', 'title': 'Fixture metadata', 'reason': 'Fixture'}


def test_default_fake_ip_stays_rejected(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('198.18.2.3', 443))])
    mock_http(monkeypatch, lambda r: pytest.fail('default DNS must never silently use DoH'))
    with pytest.raises(ValueError, match='禁止'):
        research.fetch_public('https://export.arxiv.org/api/query')


@pytest.mark.parametrize('url', ['https://@paper.example/', 'https://paper.example:0/'])
def test_empty_credentials_and_zero_port_are_rejected_before_dns(monkeypatch, url):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('unsafe URL reached DNS'))
    with pytest.raises(ValueError):
        research.validate_public_url(url)


@pytest.mark.parametrize('endpoint', [
    'http://dns.google/resolve', 'https://dns.google/resolve?name=evil',
    'https://dns.google/resolve#fragment', 'https://dns.google:443/resolve',
    'https://dns.google.evil.example/resolve', 'https://user:password@dns.google/resolve',
    'https://127.0.0.1/resolve', 'https://dns.google/other',
])
def test_resolver_is_exact_operator_allowlist(monkeypatch, endpoint):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', endpoint)
    mock_http(monkeypatch, lambda r: pytest.fail('invalid resolver must not be contacted'))
    with pytest.raises(ValueError, match='固定 HTTPS'):
        research.validate_public_url('https://paper.example/')


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.0.0.1', '198.18.2.4', '::1', '::ffff:127.0.0.1'])
def test_private_literals_never_pass_through_resolver(monkeypatch, address):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    mock_http(monkeypatch, lambda r: pytest.fail('literal must be checked locally'))
    host = '[' + address + ']' if ':' in address else address
    with pytest.raises(ValueError, match='禁止'):
        research.validate_public_url('https://' + host + '/')


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.1.2.3', '198.18.2.3', '::1', 'fc00::1', 'not-an-ip', None, 'fe80::1%eth0'])
def test_malicious_doh_mixed_or_private_answer_rejected(monkeypatch, address):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)

    def handler(request):
        assert request.url.host == 'dns.google'
        return httpx.Response(200, json={'Status': 0, 'Answer': [
            {'type': 1, 'data': PUBLIC}, {'type': 28 if ':' in str(address) else 1, 'data': address}]})

    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match='禁止'):
        research.fetch_public('https://paper.example/private')


def test_checks_both_dns_families_without_system_fallback(monkeypatch):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: pytest.fail('no system fallback'))
    seen = []

    def handler(request):
        seen.append(int(request.url.params['type']))
        assert request.url.params['name'] == 'paper.example'
        assert request.url.params['cd'] == '0'
        assert request.url.params['edns_client_subnet'] == '0.0.0.0/0'
        return httpx.Response(200, json={'Status': 0, 'Answer': [{'type': seen[-1], 'data': PUBLIC if seen[-1] == 1 else PUBLIC6}]})

    clients = mock_http(monkeypatch, handler)
    assert research.validate_public_url('https://paper.example/')[1] == [PUBLIC, PUBLIC6]
    assert seen == [1, 28]
    assert clients[0]['verify'] is True


def test_private_aaaa_after_public_a_also_fails_closed(monkeypatch):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    seen = []

    def handler(request):
        kind = int(request.url.params['type'])
        seen.append(kind)
        return httpx.Response(200, json={'Status': 0, 'Answer': [{'type': kind, 'data': PUBLIC if kind == 1 else 'fd00::1'}]})

    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match='禁止'):
        research.fetch_public('https://paper.example/')
    assert seen == [1, 28]


@pytest.mark.parametrize('body', [{'Status': 2}, {'Status': 0, 'TC': True}, [], {'Status': 0, 'Answer': 'bad'}, {'Status': 0, 'Answer': [None]}, {'Status': 0, 'Answer': []}])
def test_bad_dns_payload_fails_closed(monkeypatch, body):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    mock_http(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        research.validate_public_url('https://paper.example/')


def test_resolver_redirect_is_never_followed(monkeypatch):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={'location': 'http://169.254.169.254/'})

    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match='重定向'):
        research.fetch_public('https://paper.example/')
    assert len(seen) == 1


def test_resolver_response_size_is_bounded(monkeypatch):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    mock_http(monkeypatch, lambda r: httpx.Response(200, content=b' ' * (128 * 1024 + 1)))
    with pytest.raises(ValueError, match='上限'):
        research.validate_public_url('https://paper.example/')


@pytest.mark.parametrize('location', ['http://169.254.169.254/latest', 'https://next.example/private', '/rebound'])
def test_redirects_revalidate_dns_and_reject_private(monkeypatch, location):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    targets, dns = [], []

    def handler(request):
        if request.url.host == 'dns.google':
            dns.append(request.url.params['name'])
            # First request's A + AAAA are public; later hop becomes private.
            return dns_answer(request, PUBLIC if len(dns) <= 2 else '10.0.0.9')
        targets.append(request)
        return httpx.Response(302, headers={'location': location})

    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError, match='禁止'):
        research.fetch_public('https://paper.example/')
    assert len(targets) == 1
    assert targets[0].url.host == PUBLIC
    assert targets[0].headers['host'] == 'paper.example'


def test_every_public_redirect_is_pinned_with_original_host_tls(monkeypatch):
    monkeypatch.setenv('RT_PUBLIC_DNS_RESOLVER', RESOLVER)
    monkeypatch.setenv('RT_PUBLIC_PROXY', 'http://operator-proxy.invalid:7897')
    targets = []

    def handler(request):
        if request.url.host == 'dns.google':
            return dns_answer(request, PUBLIC if request.url.params['name'] == 'first.example' else '1.1.1.1')
        targets.append(request)
        if len(targets) == 1:
            return httpx.Response(302, headers={'location': 'https://next.example/paper.pdf'})
        return httpx.Response(200, content=b'%PDF-fixture')

    clients = mock_http(monkeypatch, handler)
    result = research.fetch_public('https://first.example/')
    assert [r.url.host for r in targets] == [PUBLIC, '1.1.1.1']
    assert [r.headers['host'] for r in targets] == ['first.example', 'next.example']
    assert [r.extensions['sni_hostname'] for r in targets] == ['first.example', 'next.example']
    contexts = [c['verify'] for c in clients if isinstance(c['verify'], ssl.SSLContext)]
    assert [c._target_hostname for c in contexts] == ['first.example', 'next.example']
    assert len(result['network']['hops']) == 2
    assert all(c['proxy'] == 'http://operator-proxy.invalid:7897' for c in clients)


def test_connect_tls_uses_hostname_and_keeps_certificate_authentication(monkeypatch):
    context = research._TargetTLSContext('paper.example')
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()['x509_ca'] > 0
    # httpcore's proxy supplies the IP here. Check the actual SSLObject SNI.
    obj = context.wrap_bio(ssl.MemoryBIO(), ssl.MemoryBIO(), server_hostname=PUBLIC)
    assert obj.server_hostname == 'paper.example'
    seen = []
    monkeypatch.setattr(ssl.SSLContext, 'wrap_socket', lambda self, *a, **kw: seen.append(kw['server_hostname']))
    context.wrap_socket(object(), server_hostname=PUBLIC)
    assert seen == ['paper.example']


def test_general_crossref_query_includes_papers_without_references(monkeypatch):
    calls = []

    def fetched(url, *a):
        calls.append(httpx.URL(url))
        return {'content': json.dumps({'message': {'items': [{'DOI': '10.1234/fixture', 'title': ['New paper']}]}}).encode()}

    monkeypatch.setattr(research, 'fetch_public', fetched)
    assert research._crossref('new literature discovery', 2)[0]['references'] == []
    assert 'filter' not in calls[0].params
    assert calls[0].params['query.bibliographic'] == 'new literature discovery'


def test_single_arxiv_identifier_uses_only_exact_lookup_parameters(monkeypatch):
    calls = []

    def fetched(url, *a):
        calls.append(httpx.URL(url))
        return {'content': b'<feed xmlns="http://www.w3.org/2005/Atom"/>'}

    monkeypatch.setattr(research, 'fetch_public', fetched)
    research._arxiv('arxiv:2106.09685v2', 10)
    assert dict(calls[0].params) == {'id_list': '2106.09685v2', 'max_results': '1'}


@pytest.mark.parametrize('a_ok,c_ok,expected', [(True, True, 'success'), (True, False, 'partial'), (False, True, 'partial'), (False, False, 'failed')])
def test_search_status_including_successful_empty_source(monkeypatch, a_ok, c_ok, expected):
    def source(ok):
        def fetch(*a):
            if not ok:
                raise ValueError('Fixture upstream failure')
            return []
        return fetch

    monkeypatch.setattr(research, '_arxiv', source(a_ok))
    monkeypatch.setattr(research, '_crossref', source(c_ok))
    result = research.search_papers('new-workspace', 'fresh fixture query', fresh=True)
    assert result['status'] == expected
    assert result['results'] == []
    if expected == 'success':
        assert result['cache_expires_at'] - result['cache_refreshed_at'] == 1800
    else:
        assert result['cache_refreshed_at'] is None and result['cache_expires_at'] is None
    if expected == 'failed':
        assert not store.rows('SELECT * FROM search_cache')


def test_cache_preserves_original_refresh_time_and_fresh_replaces_it(monkeypatch):
    calls = []

    def source(*a):
        calls.append(1)
        return [candidate()]

    monkeypatch.setattr(research, '_crossref', source)
    first = research.search_papers('a', 'fixture', ['crossref'])
    cached = research.search_papers('b', 'fixture', ['crossref'])
    assert cached['cached'] and len(calls) == 1
    assert cached['cache_refreshed_at'] == first['cache_refreshed_at']
    assert cached['searched_at'] == first['searched_at']
    assert cached['returned_at'] >= first['returned_at']
    fresh = research.search_papers('a', 'fixture', ['crossref'], fresh=True)
    assert not fresh['cached'] and len(calls) == 2
    assert fresh['cache_refreshed_at'] > first['cache_refreshed_at']


def test_import_records_pdf_provenance_without_embedding(monkeypatch):
    from services.api import documents
    paper = {**candidate(), 'pdf_url': 'https://paper.example/paper.pdf'}
    content = b'%PDF-fixture'
    monkeypatch.setattr(research, '_verified_paper', lambda p: paper)
    monkeypatch.setattr(research, 'fetch_public', lambda *a: {'content': content, 'url': paper['pdf_url']})

    def upload(*args, **kwargs):
        assert kwargs['index_dense'] is False
        return {'document': {'id': 'fixture-version'}}

    monkeypatch.setattr(documents, 'upload_document', upload)
    result = research.import_paper('new-workspace', paper, index_dense=False)
    assert result['metadata_only'] is False
    assert result['document']['work_id'] == result['work_id']
    assert result['fulltext_provenance']['sha256'] == hashlib.sha256(content).hexdigest()
    assert result['fulltext_provenance']['source_url'] == paper['pdf_url']
    assert not store.rows('SELECT * FROM quota')
