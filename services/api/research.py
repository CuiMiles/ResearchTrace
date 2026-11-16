"""Public scholarly discovery and auditable local citation graphs.

No generated bibliography, no similarity edges masquerading as citations.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

import certifi
import httpx
import networkx as nx

from . import store

MAX_DOWNLOAD = 64 * 1024 * 1024
USER_AGENT = 'ResearchTrace/0.1 (research assistant; bounded scholarly discovery)'
_SOURCE_LOCK = threading.Lock()
_NS = {'a': 'http://www.w3.org/2005/Atom', 'ar': 'http://arxiv.org/schemas/atom'}
# Operator trust boundary, never a request parameter. Exact URLs prevent an
# alternate host, credentials, port, path, query or redirect becoming SSRF.
_TRUSTED_DOH_RESOLVERS = frozenset({'https://dns.google/resolve'})


class _TargetTLSContext(ssl.SSLContext):
    """Authenticate the original hostname even on httpcore's CONNECT path.

    httpcore 1.0.x ignores sni_hostname in TunnelHTTPConnection. Override at the
    actual TLS handshake, while CONNECT and the request URL retain the pinned IP.
    No certificate checks or CA trust are disabled or inherited from proxy env.
    """

    def __new__(cls, hostname):
        return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

    def __init__(self, hostname):
        self._target_hostname = hostname
        self.load_verify_locations(cafile=certifi.where())

    def wrap_socket(self, *args, **kwargs):
        return super().wrap_socket(*args, **{**kwargs, 'server_hostname': self._target_hostname})

    def wrap_bio(self, *args, **kwargs):
        return super().wrap_bio(*args, **{**kwargs, 'server_hostname': self._target_hostname})


def _public_addresses(addresses):
    try:
        valid = bool(addresses) and all(
            '%' not in address and ipaddress.ip_address(address).is_global
            for address in addresses
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('内网、回环、链路本地和云元数据地址被禁止；DNS 必须全部为公网地址')
    return list(dict.fromkeys(addresses))


def _resolve_public(host: str, port: int) -> list[str]:
    # Literal addresses never go through DoH, which must not disguise an unsafe
    # literal as a public hostname. is_global also rejects proxy fake-IP ranges.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return _public_addresses([host])
    resolver = os.getenv('RT_PUBLIC_DNS_RESOLVER', '')
    if not resolver:
        try:
            return _public_addresses([x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)])
        except OSError as exc:
            raise ValueError('目标 DNS 解析失败') from exc
    if resolver not in _TRUSTED_DOH_RESOLVERS:
        raise ValueError('RT_PUBLIC_DNS_RESOLVER 必须为明确允许的固定 HTTPS 解析器')
    # Validate the name as DNS data, never as a URL or resolver selection.
    try:
        name = host.encode('idna').decode('ascii').rstrip('.')
    except UnicodeError as exc:
        raise ValueError('DNS 主机名无效') from exc
    if len(name) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in name.split('.')):
        raise ValueError('DNS 主机名无效')
    proxy = os.getenv('RT_PUBLIC_PROXY') or os.getenv('RT_PROXY') or None
    addresses = []
    try:
        # Only this fixed, operator-selected resolver may bootstrap by hostname
        # via the operator proxy/system DNS. Its certificate and hostname are
        # authenticated with the bundled public CA trust; redirects are refused.
        # Scholarly targets below ALWAYS use validated IP + original Host/SNI.
        with httpx.Client(proxy=proxy, trust_env=False, verify=True,
                          timeout=httpx.Timeout(15, connect=8), follow_redirects=False) as client:
            for record_type in (1, 28):
                with client.stream('GET', resolver, params={'name': name, 'type': record_type, 'cd': '0', 'edns_client_subnet': '0.0.0.0/0'},
                                   headers={'Accept': 'application/dns-json', 'Accept-Encoding': 'identity', 'User-Agent': USER_AGENT}) as response:
                    if response.status_code != 200:
                        raise ValueError('可信 DNS 解析失败或重定向被拒绝')
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 128 * 1024:
                            raise ValueError('可信 DNS 响应超过安全上限')
                data = json.loads(content)
                if not isinstance(data, dict) or type(data.get('Status')) is not int or data['Status'] != 0 or data.get('TC'):
                    raise ValueError('可信 DNS 响应失败或被截断')
                answers = data.get('Answer', [])
                if not isinstance(answers, list) or len(answers) > 128:
                    raise ValueError('可信 DNS 响应记录无效')
                for answer in answers:
                    if not isinstance(answer, dict) or type(answer.get('type')) is not int:
                        raise ValueError('可信 DNS 响应记录无效')
                    if answer.get('type') in (1, 28):
                        # Check ALL address records, including additional family
                        # records and mixed public/private responses.
                        addresses.extend(_public_addresses([answer.get('data')]))
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError('可信 DNS 连接或响应失败；未回退到系统 DNS') from exc
    return _public_addresses(addresses)


def validate_public_url(url: str) -> tuple[urllib.parse.SplitResult, list[str]]:
    """Resolve every address and reject private/mixed DNS; return pinned targets."""
    if not isinstance(url, str) or len(url) > 4000:
        raise ValueError('URL 格式或长度无效')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('仅允许 HTTP(S) 公开地址')
    if '@' in parsed.netloc or '\\' in url or any(ord(x) < 32 for x in url):
        raise ValueError('URL 不允许认证信息、反斜线或控制字符')
    try:
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
    except ValueError as exc:
        raise ValueError('端口无效') from exc
    if port not in (80, 443):
        raise ValueError('下载仅允许标准 HTTP(S) 端口')
    return parsed, _resolve_public(parsed.hostname, port)


def fetch_public(url: str, max_bytes: int = MAX_DOWNLOAD) -> dict:
    """Bounded redirect-safe HTTP, DNS-pinned even through configured proxy.

    The proxy is operator configuration, never request-controlled. Request URL
    uses a validated public IP while Host and TLS SNI retain the original name.
    """
    current = url
    proxy = os.getenv('RT_PUBLIC_PROXY') or os.getenv('RT_PROXY') or None
    hops = []
    for _ in range(5):
        parsed, addresses = validate_public_url(current)
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
        address = addresses[0]
        host_header = host if port in (80, 443) else f'{host}:{port}'
        pinned = httpx.URL(current).copy_with(host=address)
        tls_context = _TargetTLSContext(host)
        source = 'arxiv' if host in ('arxiv.org', 'export.arxiv.org', 'www.arxiv.org') else ('crossref' if host == 'api.crossref.org' else None)
        try:
            with (
                source_window(source) if source else contextlib.nullcontext(),
                httpx.Client(timeout=httpx.Timeout(35, connect=15), proxy=proxy, trust_env=False, verify=tls_context, follow_redirects=False) as client,
                client.stream('GET', pinned, headers={'Host': host_header, 'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}, extensions={'sni_hostname': host}) as response,
            ):
                stream = getattr(response, 'extensions', {}).get('network_stream')
                tls = stream.get_extra_info('ssl_object') if stream else None
                hops.append({'url': current, 'host': host, 'resolved_addresses': addresses,
                             'pinned_address': address, 'status': response.status_code,
                             'tls_server_name': tls.server_hostname if tls else None})
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('location')
                    if not location:
                        raise ValueError('重定向缺少目标')
                    current = urllib.parse.urljoin(current, location)
                    continue
                if response.status_code == 429:
                    raise ValueError(f'上游限流 429；Retry-After={response.headers.get("retry-after", "未知")[:40]}；本次不自动重试')
                if response.status_code >= 400:
                    raise ValueError(f'上游 HTTP {response.status_code}')
                length = response.headers.get('content-length', '')
                if length.isdigit() and int(length) > max_bytes:
                    raise ValueError('下载超过大小上限')
                chunks, total = [], 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError('下载超过大小上限')
                    chunks.append(chunk)
                return {'content': b''.join(chunks), 'content_type': response.headers.get('content-type', ''), 'url': current, 'status': response.status_code,
                        'network': {'resolver': os.getenv('RT_PUBLIC_DNS_RESOLVER') or 'system',
                                    'operator_proxy': bool(proxy), 'tls_verification': True, 'hops': hops}}
        except httpx.TimeoutException as exc:
            raise ValueError('公开数据源超时；未使用离线替代结果') from exc
        except httpx.HTTPError as exc:
            raise ValueError('公开数据源连接失败；未使用离线替代结果') from exc
    raise ValueError('重定向次数超过安全上限')


@contextlib.contextmanager
def source_window(source: str):
    """One arXiv connection at a time across API/worker processes, >=3s gaps."""
    directory = store.DATA / 'source_limits'
    directory.mkdir(exist_ok=True)
    with _SOURCE_LOCK, (directory / f'{source}.lock').open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        stamp = directory / f'{source}.stamp'
        try:
            last = float(stamp.read_text()) if stamp.exists() else 0
            delay = (3.1 if source == 'arxiv' else 1.0) - (time.time() - last)
            if delay > 0:
                time.sleep(delay)
            yield
        finally:
            stamp.write_text(str(time.time()))
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _text(elem, name):
    return ' '.join(elem.findtext(name, default='', namespaces=_NS).split())


def _arxiv(query: str, limit: int) -> list[dict]:
    identifier = re.search(r'(?:arxiv:|arxiv.org/(?:abs|pdf)/)?(\d{4}\.\d{4,5}(?:v\d+)?)', query, re.IGNORECASE)
    params = ({'id_list': identifier.group(1), 'max_results': 1}
              if identifier and len(query.split()) <= 2 else
              {'search_query': 'all:' + query, 'sortBy': 'relevance', 'start': 0, 'max_results': limit})
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)
    fetched = fetch_public(url, 5 * 1024 * 1024)
    provenance = {'metadata_source_sha256': hashlib.sha256(fetched['content']).hexdigest(), 'metadata_fetched_at': time.time(), 'metadata_network': fetched.get('network')}
    root = ET.fromstring(fetched['content'])
    result = []
    for entry in root.findall('a:entry', _NS):
        entry_url = _text(entry, 'a:id')
        aid = entry_url.rsplit('/', 1)[-1]
        if not re.fullmatch(r'(?:[a-z-]+(?:\.[A-Z]{2})?/)?\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?', aid):
            continue
        license_url = entry.find('ar:license', _NS)
        doi = _text(entry, 'ar:doi')
        result.append({'identity': 'arxiv:' + re.sub(r'v\d+$', '', aid), 'title': _text(entry, 'a:title'), 'authors': [_text(a, 'a:name') for a in entry.findall('a:author', _NS)], 'year': int(_text(entry, 'a:published')[:4] or 0), 'published': _text(entry, 'a:published'), 'updated': _text(entry, 'a:updated'), 'arxiv_id': aid, 'doi': doi or None, 'url': 'https://arxiv.org/abs/' + aid, 'pdf_url': 'https://arxiv.org/pdf/' + aid, 'source': 'arxiv', 'abstract': _text(entry, 'a:summary'), 'license': license_url.text if license_url is not None else '许可需在来源页面核对', 'metadata_verified': True, 'metadata_source_url': url, 'reason': 'arXiv 实时元数据候选；标题相近不等于同一研究问题'})
    for item in result:
        item.update(provenance)
    return result


def _crossref(query: str, limit: int) -> list[dict]:
    doi = re.fullmatch(r'(?:https?://(?:dx\.)?doi.org/)?(10\.\d{4,9}/\S+)', query.strip(), re.IGNORECASE)
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi.group(1), safe='') if doi else 'https://api.crossref.org/works?' + urllib.parse.urlencode({'query.bibliographic': query, 'rows': min(60, limit * 3)})
    fetched = fetch_public(url, 8 * 1024 * 1024)
    provenance = {'metadata_source_sha256': hashlib.sha256(fetched['content']).hexdigest(), 'metadata_fetched_at': time.time(), 'metadata_network': fetched.get('network')}
    data = json.loads(fetched['content'])['message']
    entries = data.get('items', []) if not doi else [data]
    result = []
    for item in entries:
        if item.get('type') in {'component', 'peer-review', 'dataset', 'journal', 'book-series'}:
            continue
        ident = item.get('DOI')
        if not ident:
            continue
        date = item.get('published', item.get('issued', {})).get('date-parts', [[0]])[0]
        links = [x.get('URL', '') for x in item.get('link', []) if x.get('content-type') == 'application/pdf']
        refs = item.get('reference', [])
        result.append({'identity': 'doi:' + ident.lower(), 'title': ' '.join(item.get('title', ['无标题'])), 'authors': [' '.join(filter(None, [a.get('given'), a.get('family')])) for a in item.get('author', [])], 'year': date[0] if date else 0, 'doi': ident, 'url': item.get('URL', 'https://doi.org/' + ident), 'pdf_url': links[0] if links else None, 'source': 'crossref', 'abstract': re.sub('<[^>]+>', '', item.get('abstract', '')), 'license': [x.get('URL') for x in item.get('license', [])], 'references': refs, 'metadata_verified': True, 'metadata_source_url': url, 'reason': 'Crossref 已登记元数据；候选需核对标题、作者和年份；PDF 可得性未验证'})
    for item in result:
        item.update(provenance)
    return result[:limit]


def _rank(workspace: str, query: str, result: list[dict]) -> list[dict]:
    feedback = {x['identity']: x['value'] for x in store.rows('SELECT identity,value FROM feedback WHERE workspace=?', (workspace,))}
    library = store.rows('SELECT title FROM works WHERE workspace=?', (workspace,))
    library_terms = set(re.findall(r'\w{3,}', ' '.join(x['title'].lower() for x in library)))
    query_terms = set(re.findall(r'\w{3,}', query.lower()))
    ranked = []
    for position, original in enumerate(result):
        item = dict(original)
        value = feedback.get(item['identity'], 0)
        if value == -1:
            continue
        terms = set(re.findall(r'\w{3,}', (item['title'] + ' ' + item.get('abstract', '')).lower()))
        relevance = len(terms & query_terms) + min(3, len(terms & library_terms))
        score = 1 / (position + 1) + relevance / 10 + value * 2
        item['recommendation_score'] = score
        item['feedback'] = value
        item['reason'] += f'；检索词重合 {len(terms & query_terms)}，库标题词重合 {len(terms & library_terms)}，反馈加权 {value * 2:+d}；方法差异与证据充分程度尚需全文核查'
        if re.search(r'https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+', item.get('abstract', '')):
            item['code_clues'] = re.findall(r'https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+', item['abstract'])
        ranked.append(item)
    return sorted(ranked, key=lambda x: x['recommendation_score'], reverse=True)


def search_papers(workspace: str, query: str, sources=None, limit=10, *, fresh=False, cancel_check=None) -> dict:
    query = query.strip()
    if not query or len(query) > 1000:
        raise ValueError('查询长度应为 1–1000 字符')
    limit = max(1, min(int(limit), 20))
    sources = list(dict.fromkeys(sources or ['arxiv', 'crossref']))
    if not sources or any(x not in ('arxiv', 'crossref') for x in sources):
        raise ValueError('不支持的数据源')
    key = hashlib.sha256(json.dumps(['scholarly-v3', query, sorted(sources), limit], ensure_ascii=False).encode()).hexdigest()
    cached = store.one('SELECT * FROM search_cache WHERE key=?', (key,))
    if not fresh and cached and time.time() - cached['created'] < 1800:
        payload = json.loads(cached['payload'])
        payload['cached'] = True
    else:
        payload = {'results': [], 'errors': [], 'cached': False, 'searched_at': time.time(), 'query': query, 'sources': sources, 'source_status': {}}
        for source in sources:
            if cancel_check and cancel_check():
                payload['errors'].append({'source': source, 'error': '检查已取消；未请求此来源'})
                payload['source_status'][source] = {'status': 'failed', 'requested': False}
                break
            try:
                found = (_arxiv if source == 'arxiv' else _crossref)(query, limit)
                payload['results'].extend(found)
                payload['source_status'][source] = {'status': 'success', 'result_count': len(found), 'fetched_at': time.time()}
            except (ValueError, OSError, ET.ParseError, KeyError, TypeError, json.JSONDecodeError) as exc:
                payload['errors'].append({'source': source, 'error': str(exc)[:300]})
                payload['source_status'][source] = {'status': 'failed', 'checked_at': time.time()}
        successful = sum(x['status'] == 'success' for x in payload['source_status'].values())
        payload['status'] = 'success' if not payload['errors'] else ('partial' if successful else 'failed')
        seen, unique = set(), []
        for item in payload['results']:
            identity = ('doi:' + item['doi'].lower()) if item.get('doi') else item['identity']
            if identity not in seen:
                seen.add(identity)
                unique.append(item)
        payload['results'] = unique
        payload['cache_refreshed_at'] = None
        payload['cache_expires_at'] = None
        # Failed-only searches are not cached as successful empty results.
        if unique or not payload['errors']:
            payload['cache_refreshed_at'] = time.time()
            payload['cache_expires_at'] = payload['cache_refreshed_at'] + 1800
            store.execute('INSERT OR REPLACE INTO search_cache VALUES(?,?,?)', (key, json.dumps(payload, ensure_ascii=False), payload['cache_refreshed_at']))
    payload['results'] = _rank(workspace, query, payload['results'])[:limit]
    payload['rank_scope'] = '候选集内启发式排序；时间显示为元数据年份，无全领域质量结论'
    payload['returned_at'] = time.time()
    return payload


def _verified_paper(paper: dict) -> dict:
    """Do not accept caller-supplied metadata as verified scholarly records."""
    if not isinstance(paper, dict):
        raise TypeError('论文候选无效')
    identity = str(paper.get('identity', ''))
    if identity.startswith('arxiv:'):
        candidates = _arxiv(identity[6:], 1)
    elif identity.startswith('doi:'):
        candidates = _crossref(identity[4:], 1)
    else:
        raise ValueError('只允许通过 arXiv/DOI 身份重新核验后入库')
    match = next((x for x in candidates if x['identity'].lower() == identity.lower()), None)
    if not match:
        raise ValueError('来源未确认该论文身份；未导入未经核验的记录')
    return match


def import_paper(workspace: str, paper: dict, *, index_dense=True, metadata_only=False) -> dict:
    paper = _verified_paper(paper)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing = c.execute('SELECT * FROM works WHERE workspace=? AND identity=?', (workspace, paper['identity'])).fetchone()
        work_id = existing['id'] if existing else store.uid()
        if not existing:
            c.execute('INSERT INTO works VALUES(?,?,?,?,?)', (work_id, workspace, paper['title'], paper['identity'], json.dumps(paper, ensure_ascii=False)))
    result = {'work_id': work_id, 'paper': paper, 'metadata_only': True, 'fulltext_status': '未提供可访问全文链接'}
    if metadata_only:
        result['fulltext_status'] = '已按请求仅导入来源核验元数据；未下载 PDF、未提交解析或密集索引'
    elif paper.get('pdf_url'):
        try:
            response = fetch_public(paper['pdf_url'])
            if not response['content'].lstrip().startswith(b'%PDF-'):
                raise ValueError('来源未返回 PDF；仅保留已核验元数据')
            from .documents import upload_document
            uploaded = upload_document(workspace, (paper.get('arxiv_id') or 'paper') + '.pdf', response['content'], index_dense=index_dense)
            version_id = uploaded['document']['id']
            previous = uploaded['document'].get('work_id')
            store.execute('UPDATE versions SET work_id=? WHERE id=? AND workspace=?', (work_id, version_id, workspace))
            if previous and previous != work_id:
                store.execute('DELETE FROM works WHERE id=? AND workspace=? AND NOT EXISTS(SELECT 1 FROM versions WHERE work_id=?)', (previous, workspace, previous))
            uploaded['document']['work_id'] = work_id
            result.update(uploaded)
            result.update({'metadata_only': False, 'fulltext_status': '真实 PDF 已提交逐页处理；不代表全文已解析',
                           'fulltext_provenance': {'source_url': paper['pdf_url'], 'final_url': response.get('url', paper['pdf_url']),
                                                   'sha256': hashlib.sha256(response['content']).hexdigest(),
                                                   'fetched_at': time.time(), 'network': response.get('network')}})
        except ValueError as exc:
            result['fulltext_status'] = str(exc)
    return result


def normalize_identity(value):
    value = str(value or '').strip().lower()
    value = re.sub(r'^https?://(?:dx\.)?doi.org/', 'doi:', value)
    value = re.sub(r'^https?://(?:www\.)?arxiv.org/(?:abs|pdf)/', 'arxiv:', value)
    if re.match(r'^10\.\d{4,9}/', value):
        value = 'doi:' + value
    if value.startswith('arxiv:'):
        value = re.sub(r'v\d+(?:\.pdf)?$', '', value)
    return value.rstrip('.,;')


def build_graph(workspace: str) -> dict:
    works = store.rows('SELECT * FROM works WHERE workspace=?', (workspace,))
    # A work containing only deleted local documents must not remain graph-searchable.
    works = [w for w in works if store.one('SELECT id FROM versions WHERE workspace=? AND work_id=? AND deleted=0', (workspace, w['id'])) or json.loads(w['metadata']).get('metadata_verified')]
    by_identity = {}
    for work in works:
        metadata = json.loads(work['metadata'])
        for identity in (work['identity'], metadata.get('doi'), ('arxiv:' + metadata['arxiv_id']) if metadata.get('arxiv_id') else None):
            if identity:
                by_identity[normalize_identity(identity)] = work['id']
    edges = []
    refs = store.rows("SELECT r.*,v.work_id FROM refs r JOIN versions v ON v.id=r.version_id LEFT JOIN active_parses a ON a.version_id=v.id WHERE r.workspace=? AND v.deleted=0 AND COALESCE(json_extract(r.metadata,'$.parse_id'),r.version_id)=COALESCE(a.parse_id,r.version_id)", (workspace,))
    known_sources = {w['id'] for w in works}
    for ref in refs:
        if ref['work_id'] not in known_sources:
            continue
        text = ref['text']
        candidates = [ref.get('target_identity')]
        candidates.extend('doi:' + x for x in re.findall(r'10\.\d{4,9}/[^\s<>"\]]+', text, flags=re.IGNORECASE))
        candidates.extend('arxiv:' + x for x in re.findall(r'(?:arxiv:|arxiv.org/(?:abs|pdf)/)\s*(\d{4}\.\d{4,5}(?:v\d+)?)', text, flags=re.IGNORECASE))
        target = next((by_identity[normalize_identity(x)] for x in candidates if normalize_identity(x) in by_identity), None)
        method = 'reference_identifier_exact'
        if target is None:
            norm = re.sub(r'[^\w]', '', text.lower())
            matches = [w['id'] for w in works if len(re.sub(r'[^\w]', '', w['title'])) >= 24 and re.sub(r'[^\w]', '', w['title'].lower()) in norm]
            if len(matches) == 1:
                target, method = matches[0], 'reference_unique_full_title'
        if target and target != ref['work_id']:
            edges.append({'source': ref['work_id'], 'target': target, 'ref_id': ref['id'], 'text': text, 'version_id': ref['version_id'], 'page_index': ref['page_index'], 'block_id': ref['block_id'], 'method': method, 'status': '参考文献条目已定位，匹配需人工抽查'})
    # Verified Crossref reference metadata provides real edges when fulltext is unavailable.
    for work in works:
        meta = json.loads(work['metadata'])
        for ref_no, ref in enumerate(meta.get('references', []) if meta.get('metadata_verified') else []):
            target = by_identity.get(normalize_identity(ref.get('DOI')))
            if target and target != work['id']:
                rid = 'metadata:' + work['id'] + ':' + str(ref_no)
                edges.append({'source': work['id'], 'target': target, 'ref_id': rid, 'text': json.dumps(ref, ensure_ascii=False), 'version_id': None, 'page_index': None, 'block_id': None, 'metadata_source_url': meta.get('metadata_source_url'), 'method': 'crossref_deposited_reference_doi', 'status': 'Crossref 登记引用条目；未声称页内全文证据'})
    graph = nx.DiGraph()
    graph.add_nodes_from(w['id'] for w in works)
    graph.add_edges_from((e['source'], e['target']) for e in edges)
    # Pure Python power iteration avoids scipy dependency for a 20-paper graph.
    ranks = {node: 1 / max(1, len(graph)) for node in graph}
    for _ in range(150):
        if not graph:
            break
        dangling = sum(ranks[n] for n in graph if graph.out_degree(n) == 0) / len(graph)
        updated = {n: (1 - .85) / len(graph) + .85 * (dangling + sum(ranks[p] / graph.out_degree(p) for p in graph.predecessors(n))) for n in graph}
        if sum(abs(updated[n] - ranks[n]) for n in graph) < 1e-12:
            ranks = updated
            break
        ranks = updated
    with store.db() as c:
        c.execute('DELETE FROM citation_edges WHERE workspace=?', (workspace,))
        for edge in edges:
            c.execute('INSERT OR IGNORE INTO citation_edges VALUES(?,?,?,?,?,?)', (hashlib.sha256((workspace + edge['ref_id'] + edge['target']).encode()).hexdigest(), workspace, edge['source'], edge['target'], edge['ref_id'], edge['method']))
    return {'nodes': [{'id': w['id'], 'title': w['title'], 'identity': w['identity'], 'rank': ranks.get(w['id'], 0), 'indegree': graph.in_degree(w['id']), 'versions': [v['id'] for v in store.rows('SELECT id FROM versions WHERE workspace=? AND work_id=? AND deleted=0', (workspace, w['id']))]} for w in works], 'edges': edges, 'scope': '当前工作区已导入作品的局部引用图；仅使用真实参考文献/已核验 Crossref 引用条目。PageRank 是当前集合相对中心性，断连节点不代表论文质量低。', 'computed_at': time.time(), 'algorithm': {'name': 'PageRank', 'damping': .85, 'iterations_max': 150}}


@contextlib.contextmanager
def _watch_lock(workspace, watch_id):
    # OS releases this lock on crash; no expiring lease can overlap a slow fetch.
    directory = store.DATA / 'watch_locks'
    directory.mkdir(exist_ok=True)
    name = hashlib.sha256((workspace + ':' + watch_id).encode()).hexdigest()
    with (directory / (name + '.lock')).open('a+') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _recover_watch(workspace, watch_id):
    """Caller holds the watch lock: any running record is an abandoned attempt."""
    now = time.time()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        abandoned = c.execute("SELECT id FROM runs WHERE workspace=? AND kind='watch' AND status='running' AND json_extract(payload,'$.watch_id')=?", (workspace, watch_id)).fetchall()
        for run in abandoned:
            detail = '追踪检查进程中断；未提交不完整结果，按下次计划或手动重试'
            c.execute("UPDATE runs SET status='failed',error=?,updated=? WHERE id=?", (detail, now, run['id']))
            c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (run['id'], 'recovered', json.dumps({'error': detail}), now))
    return len(abandoned)


def recover_watch_checks():
    """Recover dead API/worker attempts without interfering with active checks."""
    recovered = 0
    for run in store.rows("SELECT DISTINCT workspace,json_extract(payload,'$.watch_id') AS watch_id FROM runs WHERE kind='watch' AND status='running'"):
        if run['watch_id']:
            with _watch_lock(run['workspace'], run['watch_id']) as acquired:
                if acquired:
                    recovered += _recover_watch(run['workspace'], run['watch_id'])
    return recovered


def check_watch(workspace: str, watch_id: str, *, scheduled=False) -> dict:
    if not store.one('SELECT id FROM watches WHERE id=? AND workspace=?', (watch_id, workspace)):
        raise ValueError('追踪查询不存在或无权限')
    with _watch_lock(workspace, watch_id) as acquired, contextlib.ExitStack() as execution:
        if not acquired:
            running = store.one("SELECT id FROM runs WHERE workspace=? AND kind='watch' AND status='running' AND json_extract(payload,'$.watch_id')=? ORDER BY created DESC LIMIT 1", (workspace, watch_id))
            return {'status': 'running', 'overlap': True, 'run_id': running['id'] if running else None, 'results': [], 'errors': []}
        _recover_watch(workspace, watch_id)
        run_id, now = store.uid(), time.time()
        # Coordinate with the API resume guard as well as the per-watch lock.
        # Acquire before publishing the run ID, and retain through cancellation.
        if not execution.enter_context(store.run_execution_lock(run_id)):
            raise RuntimeError('追踪运行锁不可用')
        # Claim and advance the schedule in one transaction before external I/O.
        # Even a crash or network failure cannot cause a tight automatic retry loop.
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM watches WHERE id=? AND workspace=?', (watch_id, workspace)).fetchone()
            if not row:
                raise ValueError('追踪查询不存在或无权限')
            watch = dict(row)
            if scheduled and (not watch['enabled'] or watch['next_check'] is None or watch['next_check'] > now):
                return {'status': 'skipped', 'reason': 'disabled_or_not_due', 'results': [], 'errors': []}
            next_check = now + max(1, watch['interval_hours']) * 3600
            c.execute('UPDATE watches SET next_check=? WHERE id=? AND workspace=?', (next_check, watch_id, workspace))
            c.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)', (run_id, workspace, 'watch', 'running', json.dumps({'watch_id': watch_id, 'query': watch['query'], 'trigger': 'scheduled' if scheduled else 'manual'}), now, now))
            c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (run_id, 'search_papers', json.dumps({'query': watch['query'], 'sources': ['arxiv', 'crossref'], 'triggered_at': now, 'trigger': 'scheduled' if scheduled else 'manual'}), now))
        try:
            # Scheduled/manual checks must observe current sources, not a cached search.
            result = search_papers(workspace, watch['query'], fresh=True, cancel_check=lambda: store.cancelled(run_id))
        except Exception as exc:
            # Do not expose upstream exception strings which might contain credentials.
            result = {'results': [], 'errors': [{'source': 'discovery', 'error': '追踪检查异常：' + type(exc).__name__}], 'cached': False, 'searched_at': now}
        previous = json.loads(watch['result'] or '[]')
        old_ids = set(previous.get('seen_identities', [x['identity'] for x in previous.get('results', [])])) if isinstance(previous, dict) else {x['identity'] for x in previous}
        result['new_identities'] = [x['identity'] for x in result['results'] if x['identity'] not in old_ids]
        result['seen_identities'] = sorted(old_ids | {x['identity'] for x in result['results']})
        result.update(run_id=run_id, trigger='scheduled' if scheduled else 'manual', last_attempt=now)
        success = bool(result['results']) or not result['errors']
        status = 'partial' if result['errors'] and result['results'] else 'failed' if result['errors'] else 'completed'
        result['status'] = status
        finished = time.time()
        encoded = json.dumps(result, ensure_ascii=False)
        # Publish the baseline, terminal run, and terminal event atomically.
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current = c.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
            if current['status'] == 'cancelled':
                c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (run_id, 'cancelled', json.dumps({'discarded_results': True}), finished))
                return {'run_id': run_id, 'status': 'cancelled', 'results': [], 'errors': [], 'new_identities': []}
            c.execute('UPDATE watches SET last_checked=?,result=? WHERE id=? AND workspace=?', (finished if success else watch['last_checked'], encoded, watch_id, workspace))
            c.execute('UPDATE runs SET status=?,result=?,error=?,updated=? WHERE id=?', (status, encoded, '公开来源未全部成功；见结果 errors' if result['errors'] else None, finished, run_id))
            c.execute('INSERT INTO steps(run_id,event,data,created) VALUES(?,?,?,?)', (run_id, status, json.dumps({'new_count': len(result['new_identities']), 'errors': result['errors']}), finished))
        return result


def check_due_watches(*, limit=1):
    """One bounded fair batch per scheduler tick; disabled watches never fetch."""
    recover_watch_checks()
    results = []
    for watch in store.rows('SELECT id,workspace FROM watches WHERE enabled=1 AND next_check<=? ORDER BY next_check,id LIMIT ?', (time.time(), max(1, min(int(limit), 10)))):
        results.append(check_watch(watch['workspace'], watch['id'], scheduled=True))
    return results
