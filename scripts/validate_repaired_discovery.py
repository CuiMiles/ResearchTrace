"""Bounded, real public-source discovery/import probe, with no model calls.

Run from the repo root:
  .venv/bin/python scripts/validate_repaired_discovery.py \
    --resolver https://dns.google/resolve

The resolver is explicitly operator-selected. Proxy configuration is read only
from RT_PUBLIC_PROXY/RT_PROXY or the project's existing .env; values are never
logged. Runtime settings and the new SQLite/PDF workspace live in a private /tmp
directory. Only discovery-* evidence is written under the repo; no commit.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import tempfile
import time
from unittest.mock import patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resolver', required=True, choices=['https://dns.google/resolve'])
    parser.add_argument('--proxy', help='Operator-only override; never written to evidence')
    parser.add_argument('--query', action='append', help='Exactly two queries: arXiv first, Crossref second')
    args = parser.parse_args()
    queries = args.query or [
        'arxiv:2303.08774',
        'LoRA Low Rank Adaptation of Large Language Models',
    ]
    if len(queries) != 2 or len(set(queries)) != 2:
        parser.error('Exactly two distinct queries are required')

    from dotenv import dotenv_values
    names = {'RT_PUBLIC_PROXY', 'RT_PROXY', 'RT_PUBLIC_DNS_RESOLVER',
             'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
             'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'}
    existing = dotenv_values(ROOT / '.env') if (ROOT / '.env').is_file() else {}
    process_configuration_names = sorted(names.intersection(os.environ))
    proxy = args.proxy or os.getenv('RT_PUBLIC_PROXY') or os.getenv('RT_PROXY') or existing.get('RT_PUBLIC_PROXY') or existing.get('RT_PROXY')
    if not proxy:
        parser.error('Configure an operator proxy using RT_PUBLIC_PROXY or --proxy')
    parsed_proxy = urllib.parse.urlsplit(proxy)
    loopback_7897 = parsed_proxy.hostname == '127.0.0.1' and parsed_proxy.port == 7897
    private = Path(tempfile.mkdtemp(prefix='researchtrace-discovery-'))
    data = private / 'data'
    data.mkdir(mode=0o700)
    runtime = {'RT_DATA_DIR': str(data), 'RT_PUBLIC_DNS_RESOLVER': args.resolver,
               'RT_PUBLIC_PROXY': proxy, 'RT_ACCESS_CODE': secrets.token_urlsafe(32),
               'RT_SECURE_COOKIE': 'false', 'RT_DISABLE_DENSE': 'true'}
    # This file belongs only to the probe; never edit or source the project .env.
    env_path = private / 'probe.env'
    env_path.touch(mode=0o600)
    env_path.write_text(''.join(f'{k}={json.dumps(v)}\n' for k, v in runtime.items()))
    os.environ.update(runtime)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = ROOT / 'evidence' / 'review-upgrade' / ('discovery-live-' + stamp + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = {
        'started_at': time.time(), 'status': 'FAIL',
        'resolver_option': 'RT_PUBLIC_DNS_RESOLVER', 'resolver': args.resolver,
        'proxy_configuration_names': {'process': process_configuration_names,
                                      'project_env': sorted(names.intersection(existing))},
        'verified_route': {'operator_proxy': True, 'current_loopback_7897': loopback_7897,
                           'tls_certificate_verification': True, 'all_target_addresses_global': True},
        'private_workspace_directory': str(private), 'root_dataset_opened': False,
        'request_budget': {'target_http': 12, 'trusted_doh_http': 48, 'automatic_retries': 0},
        'actual_http_requests': [], 'public_operations': [], 'queries': [],
        'model_requests': 0, 'dense_index': False, 'paid_api_requests': 0,
        'openalex_requests': 0, 'checks': {},
        'official_references': [
            'https://developers.google.com/speed/public-dns/docs/doh/json',
            'https://www.encode.io/httpcore/extensions/',
        ],
    }
    for host in ['export.arxiv.org', 'api.crossref.org', 'arxiv.org', 'dns.google']:
        try:
            report.setdefault('system_dns_readonly', {})[host] = sorted({r[4][0] for r in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        except OSError as exc:
            report.setdefault('system_dns_readonly', {})[host] = {'error_type': type(exc).__name__}

    from fastapi.testclient import TestClient
    from services.api import app as api_module, jobs, models, research, retrieval, store
    import httpx

    http_counts = {'target_http': 0, 'trusted_doh_http': 0}
    real_client, real_fetch = httpx.Client, research.fetch_public

    def request_hook(request):
        is_dns = request.url.host == 'dns.google'
        category = 'trusted_doh_http' if is_dns else 'target_http'
        if http_counts[category] >= report['request_budget'][category]:
            raise ValueError('Probe request budget exhausted; no retry')
        if not is_dns:
            assert ipaddress.ip_address(request.url.host).is_global
            assert request.headers['host'] in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org', 'api.crossref.org')
        http_counts[category] += 1
        report['actual_http_requests'].append({'at': time.time(), 'kind': category,
                                               'url': str(request.url), 'host': request.headers.get('host')})

    def bounded_client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        assert kwargs['verify'] is not False
        return real_client(**kwargs, event_hooks={'request': [request_hook]})

    def observed_fetch(url, *a, **kw):
        operation = {'source_url': url, 'started_at': time.time()}
        report['public_operations'].append(operation)
        try:
            response = real_fetch(url, *a, **kw)
            operation.update(status='PASS', final_url=response['url'], http_status=response['status'],
                             bytes=len(response['content']), sha256=hashlib.sha256(response['content']).hexdigest(),
                             network=response['network'])
            for hop in response['network']['hops']:
                assert all(ipaddress.ip_address(x).is_global for x in hop['resolved_addresses'])
                if hop['url'].startswith('https:'):
                    assert hop['tls_server_name'] == hop['host']
            return response
        except Exception as exc:
            operation.update(status='FAIL', error_type=type(exc).__name__)
            if isinstance(exc, ValueError) and str(exc).startswith(('上游 HTTP ', '上游限流 ', '公开数据源', '可信 DNS', '内网')):
                operation['error'] = str(exc)[:300]
            raise
        finally:
            operation['finished_at'] = time.time()

    def no_model(*a, **kw):
        report['model_requests'] += 1
        raise AssertionError('Model/embedding call forbidden in this probe')

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(research.httpx, 'Client', bounded_client))
            stack.enter_context(patch.object(research, 'fetch_public', observed_fetch))
            for name in ('generate', 'embed', 'request', 'client'):
                stack.enter_context(patch.object(models, name, no_model))
            stack.enter_context(patch.object(retrieval, 'index_dense', no_model))
            api = stack.enter_context(TestClient(api_module.app))
            login = api.post('/api/v1/auth/login', json={'code': runtime['RT_ACCESS_CODE']})
            assert login.status_code == 200
            workspace = login.json()['workspace']
            report['workspace_id'] = workspace
            report['checks']['new_empty_workspace'] = 'PASS' if not store.rows('SELECT id FROM works') else 'FAIL'
            candidates = []
            for query, source in zip(queries, ['arxiv', 'crossref']):
                # New isolated DB starts with no search cache. Both actual API
                # requests must return cached=false, covering both public sources.
                response = api.post('/api/v1/search', json={'query': query, 'sources': [source], 'limit': 5})
                assert response.status_code == 200
                result = response.json()
                report['queries'].append(result)
                assert not result['cached'] and result['status'] == 'success' and result['results']
                assert all(s['status'] == 'success' for s in result['source_status'].values())
                assert all(p['metadata_source_url'] and p['metadata_source_sha256'] and p['metadata_fetched_at'] for p in result['results'])
                candidates.extend(p for p in result['results'] if p['source'] == 'arxiv')
                print(json.dumps({'phase': 'fresh_query', 'status': 'PASS', 'query': query,
                                  'results': len(result['results'])}), flush=True)
            report['checks']['two_fresh_queries_covering_both_sources'] = 'PASS'
            response = api.post('/api/v1/search', json={'query': queries[0], 'sources': ['arxiv'], 'limit': 5})
            cached = response.json()
            assert cached['cached'] and cached['cache_refreshed_at'] == report['queries'][0]['cache_refreshed_at']
            report['cache_check'] = {'cached': True, 'cache_refreshed_at': cached['cache_refreshed_at'],
                                     'searched_at': cached['searched_at'], 'returned_at': cached['returned_at']}
            report['checks']['original_cache_refresh_time'] = 'PASS'
            assert candidates
            paper = candidates[0]
            # Verify the live official distribution page and its actual license
            # link before downloading one PDF. No third-party mirrors or bypass.
            landing_url = 'https://arxiv.org/abs/' + paper['identity'].removeprefix('arxiv:')
            landing = research.fetch_public(landing_url, 3 * 1024 * 1024)
            text = html.unescape(landing['content'].decode('utf-8', errors='replace'))
            links = sorted(set(re.findall(r'https?://(?:arxiv\.org/licenses/|creativecommons\.org/licenses/)[^\s"<>]+', text)))
            links += ['https://arxiv.org' + p for p in re.findall(r'href=["\'](/licenses/[^"\']+)', text)]
            assert links, 'Official arXiv page did not expose a verifiable license link'
            report['oa_distribution'] = {'source': 'official arXiv public distribution', 'landing_url': landing['url'],
                                         'landing_sha256': hashlib.sha256(landing['content']).hexdigest(),
                                         'license_links': links, 'identity': paper['identity']}
            metadata = api.post('/api/v1/search/import', json={'paper': {'identity': paper['identity']},
                                                              'index_dense': False, 'metadata_only': True})
            assert metadata.status_code == 200
            report['metadata_import'] = metadata.json()
            assert metadata.json()['metadata_only'] and not store.rows('SELECT * FROM versions') and not store.rows('SELECT * FROM runs')
            report['checks']['verified_metadata_only_import'] = 'PASS'
            full = api.post('/api/v1/search/import', json={'paper': {'identity': paper['identity']},
                                                          'index_dense': False, 'metadata_only': False})
            assert full.status_code == 200
            result = full.json()
            report['full_import'] = result
            assert not result['metadata_only'], result.get('fulltext_status')
            assert result['work_id'] == metadata.json()['work_id']
            rid, vid = result['run_id'], result['document']['id']
            run = store.one('SELECT * FROM runs WHERE id=?', (rid,))
            assert json.loads(run['payload'])['index_dense'] is False
            assert jobs.work_once()
            run = store.one('SELECT status,result,error FROM runs WHERE id=?', (rid,))
            document = store.one('SELECT id,status,page_count,parsed_pages,dense_pages,sha256,path FROM versions WHERE id=?', (vid,))
            report['parse_run'] = run
            report['document'] = {k: v for k, v in document.items() if k != 'path'}
            report['block_count'] = store.one('SELECT COUNT(*) AS n FROM blocks WHERE version_id=?', (vid,))['n']
            report['reference_count'] = store.one('SELECT COUNT(*) AS n FROM refs WHERE version_id=?', (vid,))['n']
            file_hash = hashlib.sha256(Path(document['path']).read_bytes()).hexdigest()
            assert file_hash == document['sha256'] == result['fulltext_provenance']['sha256']
            assert run['status'] == 'completed' and document['status'] == 'ready'
            assert document['parsed_pages'] == document['page_count'] > 0 and report['block_count'] > 0
            assert document['dense_pages'] == 0 and not store.rows('SELECT * FROM embeddings')
            report['checks']['oa_pdf_full_import_parse_hash'] = 'PASS'
            report['checks']['no_dense_index_or_model_requests'] = 'PASS'
            downloaded = api.get(f'/api/v1/documents/{vid}/file')
            assert downloaded.status_code == 200 and hashlib.sha256(downloaded.content).hexdigest() == file_hash
            # A second actual session cannot access the first session's file/run.
            api.cookies.clear()
            assert api.post('/api/v1/auth/login', json={'code': runtime['RT_ACCESS_CODE']}).status_code == 200
            assert api.get(f'/api/v1/documents/{vid}/file').status_code == 404
            assert api.get(f'/api/v1/runs/{rid}').status_code == 404
            assert len(store.rows('SELECT * FROM works')) == 1
            report['checks']['workspace_file_and_run_isolation'] = 'PASS'
            assert not store.rows('SELECT * FROM quota') and report['model_requests'] == 0
            # Verify start spacing from actual target requests, including PDF.
            for source, gap in [('arxiv', 3.0), ('crossref', 1.0)]:
                times = [r['at'] for r in report['actual_http_requests'] if r['kind'] == 'target_http'
                         and ((source == 'arxiv' and r['host'] in ('arxiv.org', 'export.arxiv.org', 'www.arxiv.org'))
                              or (source == 'crossref' and r['host'] == 'api.crossref.org'))]
                intervals = [b - a for a, b in zip(times, times[1:])]
                assert all(d >= gap for d in intervals)
                report.setdefault('rate_evidence', {})[source] = {'minimum_gap_seconds': gap, 'actual_start_intervals': intervals}
            report['checks']['actual_source_rate_limits'] = 'PASS'
            report['status'] = 'PASS'
    except Exception as exc:
        # Error strings/tracebacks can contain secrets. Retain only a category.
        report['failure_type'] = type(exc).__name__
        report['checks']['probe_completion'] = 'FAIL'
    finally:
        report['finished_at'] = time.time()
        report['http_request_counts'] = http_counts
        report['checks'].setdefault('browser_ui', 'NOT RUN')
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'status': report['status'], 'evidence': str(destination.relative_to(ROOT)),
                          'http_request_counts': http_counts, 'model_requests': report['model_requests']}), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
