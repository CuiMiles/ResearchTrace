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
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET

import httpx
import networkx as nx

from . import store

MAX_DOWNLOAD = 64 * 1024 * 1024
USER_AGENT = 'ResearchTrace/0.1 (research assistant; bounded scholarly discovery)'
_SOURCE_LOCK = threading.Lock()
_NS = {'a': 'http://www.w3.org/2005/Atom', 'ar': 'http://arxiv.org/schemas/atom'}


def validate_public_url(url: str) -> tuple[urllib.parse.SplitResult, list[str]]:
    """Resolve every address and reject private/mixed DNS; return pinned targets."""
    if not isinstance(url, str) or len(url) > 4000:
        raise ValueError('URL 格式或长度无效')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('仅允许 HTTP(S) 公开地址')
    if parsed.username or parsed.password or '\\' in url or any(ord(x) < 32 for x in url):
        raise ValueError('URL 不允许认证信息、反斜线或控制字符')
    try:
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError as exc:
        raise ValueError('端口无效') from exc
    if port not in (80, 443):
        raise ValueError('下载仅允许标准 HTTP(S) 端口')
    try:
        addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise ValueError('目标 DNS 解析失败') from exc
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise ValueError('内网、回环、链路本地和云元数据地址被禁止')
    return parsed, addresses


def fetch_public(url: str, max_bytes: int = MAX_DOWNLOAD) -> dict:
    """Bounded redirect-safe HTTP, DNS-pinned even through configured proxy.

    The proxy is operator configuration, never request-controlled. Request URL
    uses a validated public IP while Host and TLS SNI retain the original name.
    """
    current = url
    proxy = os.getenv('RT_PUBLIC_PROXY') or os.getenv('RT_PROXY') or None
    for _ in range(5):
        parsed, addresses = validate_public_url(current)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        address = addresses[0]
        host_header = host if port in (80, 443) else f'{host}:{port}'
        pinned = httpx.URL(current).copy_with(host=address)
        try:
            with (
                httpx.Client(timeout=httpx.Timeout(35, connect=15), proxy=proxy, trust_env=False, follow_redirects=False) as client,
                client.stream('GET', pinned, headers={'Host': host_header, 'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'}, extensions={'sni_hostname': host}) as response,
            ):
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
                return {'content': b''.join(chunks), 'content_type': response.headers.get('content-type', ''), 'url': current, 'status': response.status_code}
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
    params = {'id_list': identifier.group(1)} if identifier and len(query.split()) <= 2 else {'search_query': 'all:' + query, 'sortBy': 'relevance'}
    params.update({'start': 0, 'max_results': limit})
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)
    with source_window('arxiv'):
        fetched = fetch_public(url, 5 * 1024 * 1024)
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
    return result


def _crossref(query: str, limit: int) -> list[dict]:
    doi = re.fullmatch(r'(?:https?://(?:dx\.)?doi.org/)?(10\.\d{4,9}/\S+)', query.strip(), re.IGNORECASE)
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi.group(1), safe='') if doi else 'https://api.crossref.org/works?' + urllib.parse.urlencode({'query.bibliographic': query, 'rows': min(60, limit * 3), 'filter': 'has-references:true'})
    with source_window('crossref'):
        fetched = fetch_public(url, 8 * 1024 * 1024)
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


def search_papers(workspace: str, query: str, sources=None, limit=10) -> dict:
    query = query.strip()
    if not query or len(query) > 1000:
        raise ValueError('查询长度应为 1–1000 字符')
    limit = max(1, min(int(limit), 20))
    sources = list(dict.fromkeys(sources or ['arxiv', 'crossref']))
    if not sources or any(x not in ('arxiv', 'crossref') for x in sources):
        raise ValueError('不支持的数据源')
    key = hashlib.sha256(json.dumps(['scholarly-v2', query, sorted(sources), limit], ensure_ascii=False).encode()).hexdigest()
    cached = store.one('SELECT * FROM search_cache WHERE key=?', (key,))
    if cached and time.time() - cached['created'] < 1800:
        payload = json.loads(cached['payload'])
        payload['cached'] = True
    else:
        payload = {'results': [], 'errors': [], 'cached': False, 'searched_at': time.time(), 'query': query, 'sources': sources}
        for source in sources:
            try:
                payload['results'].extend((_arxiv if source == 'arxiv' else _crossref)(query, limit))
            except (ValueError, OSError, ET.ParseError, KeyError, TypeError, json.JSONDecodeError) as exc:
                payload['errors'].append({'source': source, 'error': str(exc)[:300]})
        seen, unique = set(), []
        for item in payload['results']:
            identity = ('doi:' + item['doi'].lower()) if item.get('doi') else item['identity']
            if identity not in seen:
                seen.add(identity)
                unique.append(item)
        payload['results'] = unique
        # Failed-only searches are not cached as successful empty results.
        if unique or not payload['errors']:
            store.execute('INSERT OR REPLACE INTO search_cache VALUES(?,?,?)', (key, json.dumps(payload, ensure_ascii=False), time.time()))
    payload['results'] = _rank(workspace, query, payload['results'])[:limit]
    payload['rank_scope'] = '候选集内启发式排序；时间显示为元数据年份，无全领域质量结论'
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


def import_paper(workspace: str, paper: dict) -> dict:
    paper = _verified_paper(paper)
    existing = store.one('SELECT * FROM works WHERE workspace=? AND identity=?', (workspace, paper['identity']))
    work_id = existing['id'] if existing else store.uid()
    if not existing:
        store.execute('INSERT INTO works VALUES(?,?,?,?,?)', (work_id, workspace, paper['title'], paper['identity'], json.dumps(paper, ensure_ascii=False)))
    result = {'work_id': work_id, 'paper': paper, 'metadata_only': True, 'fulltext_status': '未提供可访问全文链接'}
    if paper.get('pdf_url'):
        try:
            response = fetch_public(paper['pdf_url'])
            if not response['content'].lstrip().startswith(b'%PDF-'):
                raise ValueError('来源未返回 PDF；仅保留已核验元数据')
            from .documents import upload_document
            uploaded = upload_document(workspace, (paper.get('arxiv_id') or 'paper') + '.pdf', response['content'])
            version_id = uploaded['document']['id']
            previous = uploaded['document'].get('work_id')
            store.execute('UPDATE versions SET work_id=? WHERE id=? AND workspace=?', (work_id, version_id, workspace))
            if previous and previous != work_id:
                store.execute('DELETE FROM works WHERE id=? AND workspace=? AND NOT EXISTS(SELECT 1 FROM versions WHERE work_id=?)', (previous, workspace, previous))
            result.update(uploaded)
            result.update({'metadata_only': False, 'fulltext_status': '真实 PDF 已提交逐页处理；不代表全文已解析'})
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


def check_watch(workspace: str, watch_id: str) -> dict:
    watch = store.one('SELECT * FROM watches WHERE id=? AND workspace=?', (watch_id, workspace))
    if not watch:
        raise ValueError('追踪查询不存在或无权限')
    run_id, now = store.uid(), time.time()
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)', (run_id, workspace, 'watch', 'running', json.dumps({'watch_id': watch_id, 'query': watch['query']}), now, now))
    store.event(run_id, 'search_papers', {'query': watch['query'], 'sources': ['arxiv', 'crossref'], 'triggered_at': now})
    result = search_papers(workspace, watch['query'])
    previous = json.loads(watch['result'])
    old_ids = {x['identity'] for x in (previous.get('results', []) if isinstance(previous, dict) else previous)}
    result['new_identities'] = [x['identity'] for x in result['results'] if x['identity'] not in old_ids]
    result['run_id'] = run_id
    # No duplicate automatic imports: discovery stays metadata until explicitly selected.
    success = bool(result['results']) or not result['errors']
    store.execute('UPDATE watches SET last_checked=?,next_check=?,result=? WHERE id=? AND workspace=?', (now if success else watch['last_checked'], now + max(1, watch['interval_hours']) * 3600, json.dumps(result, ensure_ascii=False), watch_id, workspace))
    status = 'partial' if result['errors'] and result['results'] else 'failed' if result['errors'] else 'completed'
    store.execute('UPDATE runs SET status=?,result=?,updated=? WHERE id=?', (status, json.dumps(result, ensure_ascii=False), time.time(), run_id))
    store.event(run_id, status, {'new_count': len(result['new_identities']), 'errors': result['errors']})
    return result
