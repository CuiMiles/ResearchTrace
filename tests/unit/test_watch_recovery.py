"""Isolated fault/concurrency tests; source responses here are explicitly fixtures."""
import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.api import research, store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.migrate()


def watch(wid='w', enabled=1):
    store.execute('INSERT INTO watches VALUES(?,?,?,?,?,?,?,?)', (wid, 'alpha', 'fixture query', enabled, 1, None, 0, '[]'))


def response(*args, **kwargs):
    return {'results': [{'identity': 'doi:10.1234/unit', 'title': 'Fixture'}], 'errors': [], 'cached': False}


def test_overlapping_manual_and_scheduler_share_one_attempt(monkeypatch):
    watch()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def slow(*a, **kw):
        calls.append(kw)
        entered.set()
        assert release.wait(5)
        return response()
    monkeypatch.setattr(research, 'search_papers', slow)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(research.check_watch, 'alpha', 'w')
        try:
            assert entered.wait(5)
            overlap = research.check_watch('alpha', 'w')
            assert overlap['overlap'] and overlap['run_id']
            assert research.recover_watch_checks() == 0
            assert research.check_due_watches() == []  # claim already advanced schedule
        finally:
            release.set()
        assert first.result()['run_id'] == overlap['run_id']
    assert len(calls) == 1 and calls[0]['fresh'] is True
    assert len(store.rows('SELECT * FROM runs')) == 1


def test_crash_recovery_uses_os_lock_and_preserves_schedule(monkeypatch):
    watch()
    def crash():
        research.search_papers = lambda *a, **kw: os._exit(23)
        research.check_watch('alpha', 'w', scheduled=True)
    proc = multiprocessing.get_context('fork').Process(target=crash)
    proc.start()
    proc.join(5)
    try:
        assert proc.exitcode == 23
        assert store.one('SELECT status FROM runs')['status'] == 'running'
        assert research.recover_watch_checks() == 1
        assert research.recover_watch_checks() == 0
        assert store.one('SELECT status FROM runs')['status'] == 'failed'
        assert store.one("SELECT event FROM steps WHERE event='recovered'")
        monkeypatch.setattr(research, 'search_papers', response)
        assert research.check_due_watches() == []
        assert research.check_watch('alpha', 'w')['status'] == 'completed'
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join()


def test_disabled_schedule_and_workspace_cannot_fetch(monkeypatch):
    watch(enabled=0)
    monkeypatch.setattr(research, 'search_papers', lambda *a, **kw: pytest.fail('unexpected source call'))
    assert research.check_due_watches() == []
    assert research.check_watch('alpha', 'w', scheduled=True)['status'] == 'skipped'
    with pytest.raises(ValueError, match='无权限'):
        research.check_watch('beta', 'w')
    assert not store.rows('SELECT * FROM runs')


def test_failures_are_terminal_bounded_and_keep_seen_baseline(monkeypatch):
    watch()
    monkeypatch.setattr(research, 'search_papers', response)
    first = research.check_watch('alpha', 'w')
    checked = store.one('SELECT last_checked FROM watches')['last_checked']
    def fail(*a, **kw):
        raise OSError('not returned to browser')
    monkeypatch.setattr(research, 'search_papers', fail)
    store.execute('UPDATE watches SET next_check=0')
    failed = research.check_due_watches()[0]
    assert failed['status'] == 'failed' and not failed['results']
    assert 'not returned' not in json.dumps(failed)
    assert store.one('SELECT last_checked FROM watches')['last_checked'] == checked
    assert store.one('SELECT next_check FROM watches')['next_check'] > time.time() + 3500
    assert research.check_due_watches() == []
    monkeypatch.setattr(research, 'search_papers', response)
    assert research.check_watch('alpha', 'w')['new_identities'] == []
    assert first['new_identities']
    assert not store.rows('SELECT * FROM works')


def test_disable_during_fetch_is_not_overwritten(monkeypatch):
    watch()
    def disable(*a, **kw):
        store.execute('UPDATE watches SET enabled=0 WHERE id=?', ('w',))
        return response()
    monkeypatch.setattr(research, 'search_papers', disable)
    assert research.check_watch('alpha', 'w', scheduled=True)['status'] == 'completed'
    assert store.one('SELECT enabled FROM watches')['enabled'] == 0
    store.execute('UPDATE watches SET next_check=0')
    assert research.check_due_watches() == []


def test_cancellation_during_fetch_discards_result_and_preserves_baseline(monkeypatch):
    watch()
    def cancel(*a, **kw):
        store.execute("UPDATE runs SET status='cancelled' WHERE kind='watch' AND status='running'")
        rid = store.one('SELECT id FROM runs')['id']
        with store.run_execution_lock(rid) as acquired:
            assert not acquired  # API resume must return 409 during cleanup.
        return response()
    monkeypatch.setattr(research, 'search_papers', cancel)
    result = research.check_watch('alpha', 'w')
    assert result['status'] == 'cancelled' and not result['results']
    assert store.one('SELECT status FROM runs')['status'] == 'cancelled'
    baseline = store.one('SELECT result,last_checked FROM watches')
    assert baseline == {'result': '[]', 'last_checked': None}
    with store.run_execution_lock(result['run_id']) as acquired:
        assert acquired


def test_cancellation_stops_next_source(monkeypatch):
    stopped = []
    def first(*a):
        stopped.append(True)
        return []
    monkeypatch.setattr(research, '_arxiv', first)
    monkeypatch.setattr(research, '_crossref', lambda *a: pytest.fail('cancelled check requested next source'))
    result = research.search_papers('alpha', 'fixture', fresh=True, cancel_check=lambda: bool(stopped))
    assert result['errors'] and result['errors'][0]['source'] == 'crossref'


def test_fresh_search_bypasses_shared_cache(monkeypatch):
    calls = []
    def source(*a):
        calls.append(a)
        return [dict(response()['results'][0], reason='fixture')]
    monkeypatch.setattr(research, '_crossref', source)
    assert not research.search_papers('alpha', 'fixture', ['crossref'])['cached']
    assert research.search_papers('alpha', 'fixture', ['crossref'])['cached']
    assert not research.search_papers('alpha', 'fixture', ['crossref'], fresh=True)['cached']
    assert len(calls) == 2


def test_metadata_only_reverifies_without_pdf_or_runs(monkeypatch):
    verified = dict(response()['results'][0], pdf_url='https://example.org/paper.pdf', metadata_verified=True)
    calls = []
    def verify(paper):
        calls.append(paper)
        return verified
    monkeypatch.setattr(research, '_verified_paper', verify)
    monkeypatch.setattr(research, 'fetch_public', lambda *a: pytest.fail('metadata only downloaded PDF'))
    first = research.import_paper('alpha', {'identity': verified['identity'], 'title': 'untrusted'}, metadata_only=True, index_dense=False)
    second = research.import_paper('alpha', verified, metadata_only=True, index_dense=False)
    assert first['work_id'] == second['work_id'] and first['paper']['title'] == 'Fixture'
    assert len(calls) == 2
    assert len(store.rows('SELECT * FROM works')) == 1
    assert not store.rows('SELECT * FROM versions')
    assert not store.rows('SELECT * FROM runs')
    assert not store.rows('SELECT * FROM quota')


def test_dense_flag_is_forwarded_to_pdf_upload(monkeypatch):
    from services.api import documents
    verified = dict(response()['results'][0], pdf_url='https://example.org/paper.pdf')
    monkeypatch.setattr(research, '_verified_paper', lambda p: verified)
    monkeypatch.setattr(research, 'fetch_public', lambda *a: {'content': b'%PDF-fixture'})
    calls = []
    def upload(*a, **kw):
        calls.append(kw['index_dense'])
        return {'document': {'id': 'fixture-version'}}
    monkeypatch.setattr(documents, 'upload_document', upload)
    research.import_paper('alpha', verified, index_dense=False)
    research.import_paper('alpha', verified)
    assert calls == [False, True]


def test_worker_checks_schedule_even_when_queue_is_busy(monkeypatch):
    import resource
    from services.worker import main as worker
    calls = []
    monkeypatch.setattr(resource, 'setrlimit', lambda *a: None)
    monkeypatch.setattr(worker.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(research, 'check_due_watches', lambda **kw: calls.append(kw))
    monkeypatch.setattr(worker.time, 'monotonic', lambda: 100)
    monkeypatch.setattr(worker, 'stopping', False)
    def busy(pool='all'):
        assert pool=='all'
        worker.stopping = True
        return True
    monkeypatch.setattr(worker, 'work_once', busy)
    worker.main()
    assert calls == [{'limit': 1}]
