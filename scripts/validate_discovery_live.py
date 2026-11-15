"""Bounded public-HTTP discovery acceptance; never calls a model or changes env.

Run: .venv/bin/python scripts/validate_discovery_live.py
Only a new authenticated workspace is changed. All created watches are disabled
in finally. A source operation budget is conservative (cache hits count too).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(database):
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        quota = [dict(r) for r in conn.execute('SELECT * FROM quota ORDER BY id')]
        watches = [dict(r) for r in conn.execute('SELECT * FROM watches ORDER BY id')]
    counts = {}
    for row in quota:
        counts[row['model']] = counts.get(row['model'], 0) + 1
    return {'quota_sha256': digest(quota), 'quota_counts': counts, 'watches': watches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:18980')
    parser.add_argument('--private-env', type=Path)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/researchtrace.sqlite')
    parser.add_argument('--max-source-requests', type=int, default=2,
                        help='Conservative per-source operation ceiling; no retries')
    parser.add_argument('--scheduler-timeout', type=float, default=110)
    args = parser.parse_args()
    # Credentials stay in memory; neither values nor cookies enter evidence.
    private = args.private_env or next((p for p in [ROOT / 'private.env', ROOT / '.env'] if p.is_file()), ROOT / 'private.env')
    config = dotenv_values(private) if private.is_file() else {}
    code = os.environ.get('RT_ACCESS_CODE') or config.get('RT_ACCESS_CODE')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ROOT / 'evidence/ubuntu24' / ('discovery-20261116-' + stamp)
    directory.mkdir(parents=True, mode=0o700)
    report = {'started_at': time.time(), 'base_url': args.base_url, 'transport': 'public HTTP',
              'E01': {'status': 'NOT RUN'}, 'E03': {'status': 'NOT RUN'},
              'source_operation_ceiling': args.max_source_requests, 'source_operations': {'arxiv': 0, 'crossref': 0},
              'provider_calls': 0, 'command': '.venv/bin/python scripts/validate_discovery_live.py',
              'operations': [], 'created_watches': [], 'scope': 'new authenticated workspace only'}
    before = snapshot(args.database)
    report['quota_before'] = {k: v for k, v in before.items() if k != 'watches'}
    workspace = None
    counter = 0
    def save(name, value):
        path = directory / (name + '.json')
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        return str(path.relative_to(ROOT))
    def request(client, method, path, **kwargs):
        nonlocal counter
        started = time.time()
        response = client.request(method, path, **kwargs)
        counter += 1
        # Store response bytes, never request headers/cookies or the login response.
        raw_path = directory / (f'{counter:02d}-http-response.json')
        raw_path.write_bytes(response.content)
        report['operations'].append({'method': method, 'path': path, 'started_at': started,
                                     'finished_at': time.time(), 'http_status': response.status_code,
                                     'response_sha256': hashlib.sha256(response.content).hexdigest(),
                                     'raw_response': str(raw_path.relative_to(ROOT))})
        response.raise_for_status()
        return response.json()
    def consume(sources):
        if any(report['source_operations'][source] >= args.max_source_requests for source in sources):
            return False
        for source in sources:
            report['source_operations'][source] += 1
        return True
    with httpx.Client(base_url=args.base_url, trust_env=False, timeout=190) as client:
        try:
            request(client, 'GET', '/healthz')
            if not code:
                raise RuntimeError('local access code unavailable')
            login = client.post('/api/v1/auth/login', json={'code': code})
            login.raise_for_status()
            workspace = login.json()['workspace']
            report['workspace'] = workspace
            schema = client.get('/openapi.json').json()
            fields = schema.get('components', {}).get('schemas', {}).get('Import', {}).get('properties', {})
            report['http_import_flags'] = all(k in fields for k in ('metadata_only', 'index_dense'))
            paths = [('arxiv', '1512.03385'), ('crossref', 'Deep Residual Learning for Image Recognition')]
            source_results = []
            for source, query in paths:
                if not consume([source]):
                    break
                found = request(client, 'POST', '/api/v1/search', json={'query': query, 'sources': [source], 'limit': 3})
                item = {'source': source, 'query': query, 'cached': found.get('cached'), 'errors': found.get('errors', []),
                        'candidate_count': len(found.get('results', [])), 'status': 'BLOCKED'}
                if found.get('results') and report['http_import_flags'] and consume([source]):
                    candidate = found['results'][0]
                    started = time.time()
                    imported = request(client, 'POST', '/api/v1/search/import', json={
                        'paper': {'identity': candidate['identity'], 'title': 'UNTRUSTED TITLE MUST NOT BE IMPORTED', 'metadata_verified': True},
                        'metadata_only': True, 'index_dense': False})
                    verified = imported['paper']
                    assert imported['metadata_only'] and 'document' not in imported
                    assert verified['identity'] == candidate['identity']
                    assert verified['title'] != 'UNTRUSTED TITLE MUST NOT BE IMPORTED'
                    assert len(verified.get('metadata_source_sha256', '')) == 64
                    assert verified.get('metadata_fetched_at', 0) >= started
                    item.update(status='PASS', work_id=imported['work_id'], identity=verified['identity'],
                                raw_source_sha256=verified['metadata_source_sha256'],
                                fetched_at=verified['metadata_fetched_at'], source_url=verified['metadata_source_url'],
                                reverified_caller_metadata=True)
                elif found.get('results'):
                    item['reason'] = 'HTTP import flags unavailable or explicit source operation ceiling reached'
                source_results.append(item)
                print(source + ': ' + item['status'], flush=True)
            report['E01'] = {'status': 'PASS' if len(source_results) == 2 and all(x['status'] == 'PASS' for x in source_results) else 'BLOCKED', 'sources': source_results}
            # Manual and scheduler share production code. Never exceed the explicit
            # source budget merely to turn a blocked acceptance case green.
            w = request(client, 'POST', '/api/v1/watch-queries', json={'query': paths[1][1], 'enabled': False, 'interval_hours': 1})
            wid = w['id']
            report['created_watches'].append(wid)
            if consume(['arxiv', 'crossref']):
                immediate = request(client, 'POST', '/api/v1/watch-queries/' + wid + '/check')
                report['E03']['immediate'] = immediate
            else:
                immediate = None
            if consume(['arxiv', 'crossref']):
                request(client, 'PATCH', '/api/v1/watch-queries/' + wid, json={'enabled': True})
                # Controlled due time, scoped to this new watch/workspace. No
                # interval/global setting or pre-existing watch is changed.
                with sqlite3.connect(args.database, timeout=30) as conn:
                    assert conn.execute('UPDATE watches SET next_check=? WHERE id=? AND workspace=?', (time.time() - 1, wid, workspace)).rowcount == 1
                deadline = time.monotonic() + args.scheduler_timeout
                scheduled = None
                while time.monotonic() < deadline:
                    with sqlite3.connect('file:' + str(args.database) + '?mode=ro', uri=True) as conn:
                        conn.row_factory = sqlite3.Row
                        row = conn.execute("SELECT * FROM runs WHERE workspace=? AND kind='watch' AND json_extract(payload,'$.watch_id')=? AND json_extract(payload,'$.trigger')='scheduled' ORDER BY created DESC LIMIT 1", (workspace, wid)).fetchone()
                        if row and row['status'] not in ('queued', 'running'):
                            scheduled = dict(row)
                            break
                    time.sleep(.5)
                report['E03']['scheduled'] = scheduled
                request(client, 'PATCH', '/api/v1/watch-queries/' + wid, json={'enabled': False})
                with sqlite3.connect(args.database, timeout=30) as conn:
                    conn.execute('UPDATE watches SET next_check=0 WHERE id=? AND workspace=?', (wid, workspace))
                    count = conn.execute("SELECT count(*) FROM runs WHERE workspace=? AND kind='watch'", (workspace,)).fetchone()[0]
                # At least one complete 30-second scheduler tick while disabled.
                time.sleep(32)
                with sqlite3.connect('file:' + str(args.database) + '?mode=ro', uri=True) as conn:
                    after_count = conn.execute("SELECT count(*) FROM runs WHERE workspace=? AND kind='watch'", (workspace,)).fetchone()[0]
                report['E03']['disabled_no_new_run'] = after_count == count
                report['E03']['status'] = 'PASS' if immediate and immediate.get('status') == 'completed' and scheduled and scheduled['status'] == 'completed' and count == after_count and not json.loads(scheduled['result']).get('new_identities') else 'BLOCKED'
            else:
                report['E03'].update(status='BLOCKED', reason='External failure and/or explicit per-source operation ceiling; controlled scheduler live check NOT RUN')
            with sqlite3.connect('file:' + str(args.database) + '?mode=ro', uri=True) as conn:
                counts = {table: conn.execute('SELECT count(*) FROM ' + table + ' WHERE workspace=?', (workspace,)).fetchone()[0] for table in ['works', 'versions', 'embeddings']}
                steps = conn.execute("SELECT s.run_id,s.event,s.data,s.created FROM steps s JOIN runs r ON r.id=s.run_id WHERE r.workspace=? ORDER BY s.id", (workspace,)).fetchall()
            report['workspace_counts'] = counts
            report['watch_steps'] = save('watch-steps', steps)
            assert counts['versions'] == 0 and counts['embeddings'] == 0
        except Exception as exc:
            report['error_type'] = type(exc).__name__
            # HTTP errors can embed URLs; no exception strings are persisted.
            for case in ['E01', 'E03']:
                if report[case]['status'] == 'NOT RUN':
                    report[case] = {'status': 'BLOCKED', 'reason': type(exc).__name__}
        finally:
            disabled = []
            for wid in report['created_watches']:
                try:
                    request(client, 'PATCH', '/api/v1/watch-queries/' + wid, json={'enabled': False})
                    disabled.append(wid)
                except Exception:
                    # Local fail-safe changes only the exact newly-created watch.
                    with sqlite3.connect(args.database, timeout=30) as conn:
                        conn.execute('UPDATE watches SET enabled=0 WHERE id=? AND workspace=?', (wid, workspace))
                    disabled.append(wid)
            report['disabled_watches'] = disabled
            after = snapshot(args.database)
            report['quota_after'] = {k: v for k, v in after.items() if k != 'watches'}
            report['quota_unchanged'] = before['quota_sha256'] == after['quota_sha256']
            original_ids = {w['id'] for w in before['watches']}
            report['preexisting_watches_unchanged'] = before['watches'] == [w for w in after['watches'] if w['id'] in original_ids]
            report['all_created_watches_disabled'] = all(not w['enabled'] for w in after['watches'] if w['id'] in report['created_watches'])
            report['finished_at'] = time.time()
            save('result', report)
    print(json.dumps({'evidence': str(directory.relative_to(ROOT)), 'E01': report['E01']['status'], 'E03': report['E03']['status'], 'quota_unchanged': report.get('quota_unchanged')}))
    return 0 if report['E01']['status'] == report['E03']['status'] == 'PASS' and report.get('quota_unchanged') else 2


if __name__ == '__main__':
    raise SystemExit(main())
