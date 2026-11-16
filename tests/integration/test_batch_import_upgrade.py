"""P0-05: synthetic PDFs, real SQLite/files/parser; no live providers or GPU.

An isolated HTTP harness exercises the helpers before main registers its routes.
The test workspace header exists only in this harness, never in the application.
"""
import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import FastAPI, File, Header, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel
from reportlab.pdfgen import canvas

from services.api import batches, documents, jobs, models, store


def pdf(number=0):
    output = io.BytesIO()
    p = canvas.Canvas(output, invariant=True)
    p.setTitle(f'Batch engineering fixture {number}')
    p.drawString(40, 740, f'Unique source evidence BATCH{number:04d} remains immutable.')
    p.save()
    return output.getvalue()


def uploads(count, offset=0):
    return [('files', (f'new-{i}.pdf', pdf(i), 'application/pdf'))
            for i in range(offset, offset + count)]


class Selection(BaseModel):
    item_ids: list[str] | None = None


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(documents, 'DATA', tmp_path)
    monkeypatch.setenv('RT_DISABLE_DENSE', 'true')
    monkeypatch.setenv('ENABLE_DENSE', 'false')
    def forbidden(*args, **kwargs):
        pytest.fail('Batch tests must not invoke a provider')
    monkeypatch.setattr(models, 'embed', forbidden)
    monkeypatch.setattr(models, 'generate', forbidden)
    store.migrate()
    app = FastAPI()

    @app.post('/api/v1/documents')
    async def upload(files: Annotated[list[UploadFile], File()], index_dense: bool = True,
                     x_test_workspace: str = Header(default='alpha')):
        return await batches.upload_batch(x_test_workspace, files, index_dense)

    @app.get('/api/v1/batches/{batch_id}')
    def status(batch_id: str, x_test_workspace: str = Header(default='alpha')):
        return batches.get_batch(x_test_workspace, batch_id)

    @app.post('/api/v1/batches/{batch_id}/cancel')
    def cancel(batch_id: str, body: Selection | None = None,
               x_test_workspace: str = Header(default='alpha')):
        return batches.cancel_batch(x_test_workspace, batch_id, body.item_ids if body else None)

    @app.post('/api/v1/batches/{batch_id}/resume')
    def resume(batch_id: str, body: Selection | None = None,
               x_test_workspace: str = Header(default='alpha')):
        return batches.resume_batch(x_test_workspace, batch_id, body.item_ids if body else None)

    with TestClient(app) as client:
        yield client


def post(api, count=23, offset=0, workspace='alpha'):
    response = api.post('/api/v1/documents?index_dense=false', files=uploads(count, offset),
                        headers={'x-test-workspace': workspace})
    assert response.status_code == 200, response.text
    return response.json()


def pending(workspace=None):
    suffix, args = (' AND workspace=?', (workspace,)) if workspace else ('', ())
    return store.one("SELECT count(*) AS n FROM runs WHERE status IN ('queued','running')" + suffix, args)['n']


def test_23_new_pdfs_in_one_http_request_finish_in_bounded_waves(api):
    batch = post(api)
    assert len(batch['documents']) == len(batch['runs']) == len(batch['items']) == 23
    assert batch['counts'] == {'queued': 6, 'waiting_batch': 17}
    assert batch['errors'] == []
    for run in store.rows('SELECT payload FROM runs'):
        assert json.loads(run['payload'])['index_dense'] is False
    steps = 0
    while jobs.work_once():
        assert pending('alpha') <= 6 and pending() <= 30
        batches.admit_pending()
        steps += 1
        assert steps <= 23
    result = api.get('/api/v1/batches/' + batch['batch_id']).json()
    assert steps == 23
    assert result['status'] == 'completed' and result['counts'] == {'completed': 23}
    assert all(v['parsed_pages'] == v['page_count'] == 1 for v in result['documents'])
    assert store.one('SELECT count(*) AS n FROM block_fts')['n'] >= 23
    assert store.one('SELECT count(*) AS n FROM quota')['n'] == 0
    assert store.one('SELECT count(*) AS n FROM versions')['n'] == 23
    for v in store.rows('SELECT path,sha256 FROM versions'):
        assert hashlib.sha256(Path(v['path']).read_bytes()).hexdigest() == v['sha256']


@pytest.mark.parametrize('count', [1, 10])
def test_old_documents_runs_contract_for_small_uploads(api, count):
    result = post(api, count)
    assert len(result['documents']) == len(result['runs']) == count
    assert all({'id', 'filename', 'metadata', 'active_parse_id', 'duplicate'} <= v.keys() for v in result['documents'])
    assert all(r['id'] == r['run_id'] for r in result['runs'])
    assert all('path' not in d and not d['duplicate'] for d in result['documents'])


def test_validation_errors_are_per_file_and_later_files_still_import(api):
    files = [('files', ('header.txt', b'not a PDF', 'text/plain')),
             *uploads(1), ('files', ('corrupt.pdf', b'%PDF-invalid', 'application/pdf')),
             *uploads(1, 1)]
    response = api.post('/api/v1/documents?index_dense=false', files=files)
    assert response.status_code == 200
    result = response.json()
    assert len(result['items']) == 4 and len(result['errors']) == 2
    assert len(result['documents']) == 2 and result['counts'] == {'failed': 2, 'queued': 2}
    assert not list(store.DATA.rglob('*.tmp'))


def test_single_invalid_file_preserves_422_and_durable_error(api):
    response = api.post('/api/v1/documents', files={'files': ('invalid.pdf', b'not PDF')})
    assert response.status_code == 422
    detail = response.json()['detail']
    result = api.get('/api/v1/batches/' + detail['batch_id']).json()
    assert result['status'] == 'failed' and len(result['errors']) == 1
    assert store.one('SELECT count(*) n FROM versions')['n'] == 0


class BoundedRead(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        assert 0 < size <= 1024 * 1024, 'An import attempted an unbounded read'
        self.read_sizes.append(size)
        return super().read(size)


def test_streamed_file_ingestion_uses_only_bounded_reads(api):
    data = pdf() + b'\n%' + b'x' * (3 * 1024 * 1024)
    source = BoundedRead(data)
    result = asyncio.run(batches.upload_batch('alpha', [UploadFile(source, filename='large.pdf')], False))
    assert len(source.read_sizes) >= 4
    assert result['items'][0]['sha256'] == hashlib.sha256(data).hexdigest()
    assert not list(store.DATA.rglob('*.tmp'))


def test_fifty_mib_file_limit_is_independent_and_aggregate_is_bounded(api, tmp_path):
    large = tmp_path / 'oversize.pdf'
    with large.open('wb') as f:
        f.write(pdf())
        f.truncate(batches.MAX_FILE_BYTES + 1)
    with large.open('rb') as f:
        result = asyncio.run(batches.upload_batch('alpha', [
            UploadFile(f, filename='oversize.pdf'), UploadFile(io.BytesIO(pdf(2)), filename='valid.pdf')], False))
    assert result['counts'] == {'failed': 1, 'queued': 1}
    assert '50 MiB' in result['errors'][0]['error']
    before = store.one('SELECT count(*) n FROM import_batches')['n']
    with large.open('r+b') as f:
        f.truncate(batches.MAX_BATCH_BYTES + 1)
        with pytest.raises(batches.HTTPException) as exc:
            asyncio.run(batches.upload_batch('alpha', [UploadFile(f, filename='too-big.pdf')], False))
    assert exc.value.status_code == 413
    assert store.one('SELECT count(*) n FROM import_batches')['n'] == before


def test_maximum_fifty_files_and_reject_fifty_one_before_persistence(api):
    fifty = post(api, 50)
    assert len(fifty['items']) == 50 and pending() == 6
    response = api.post('/api/v1/documents?index_dense=false', files=uploads(51, 100))
    assert response.status_code == 413
    assert store.one('SELECT count(*) n FROM import_batches')['n'] == 1


def test_duplicate_bytes_are_idempotent_and_do_not_overwrite_snapshots(api):
    initial = post(api, 1)
    original = store.one('SELECT * FROM versions')
    original_stat = Path(original['path']).stat()
    assert jobs.work_once()
    blocks = store.rows('SELECT * FROM blocks ORDER BY id')
    active = store.rows('SELECT * FROM active_parses')
    duplicates = api.post('/api/v1/documents?index_dense=false', files=uploads(1) + uploads(1)).json()
    assert len(duplicates['items']) == 2
    assert all(v['duplicate'] for v in duplicates['documents'])
    assert all(not item['owns_run'] for item in duplicates['items'])
    assert store.one('SELECT count(*) n FROM runs')['n'] == 1
    assert duplicates['runs'][0]['id'] == initial['runs'][0]['id']
    assert store.rows('SELECT * FROM blocks ORDER BY id') == blocks
    store.execute('UPDATE versions SET deleted=1 WHERE id=?', (original['id'],))
    restored = post(api, 1)
    assert restored['documents'][0]['id'] == original['id']
    assert jobs.work_once()
    assert store.rows('SELECT * FROM blocks ORDER BY id') == blocks
    assert store.rows('SELECT * FROM active_parses') == active
    final_stat = Path(original['path']).stat()
    assert final_stat.st_ino == original_stat.st_ino and final_stat.st_mtime_ns == original_stat.st_mtime_ns


def test_cancel_all_and_resume_keep_same_runs_with_bounded_readmission(api):
    initial = post(api)
    base = '/api/v1/batches/' + initial['batch_id']
    cancelled = api.post(base + '/cancel').json()
    assert cancelled['status'] == 'cancelled' and cancelled['counts'] == {'cancelled': 23}
    assert pending() == 0 and batches.admit_pending() == 0
    resumed = api.post(base + '/resume').json()
    assert resumed['counts'] == {'queued': 6, 'waiting_batch': 17}
    assert {r['id'] for r in resumed['runs']} == {r['id'] for r in initial['runs']}
    assert store.one('SELECT count(*) n FROM runs')['n'] == 23


def test_selected_cancel_resume_and_execution_ownership(api):
    initial = post(api)
    base = '/api/v1/batches/' + initial['batch_id']
    item = initial['items'][0]
    selection = {'item_ids': [item['id']]}
    assert api.post(base + '/cancel', json=selection).json()['counts']['cancelled'] == 1
    with store.run_execution_lock(item['run_id']) as acquired:
        assert acquired
        response = api.post(base + '/resume', json=selection)
        assert response.status_code == 409
        assert store.one('SELECT status FROM runs WHERE id=?', (item['run_id'],))['status'] == 'cancelled'
    assert api.post(base + '/resume', json=selection).status_code == 200
    assert pending('alpha') == 6


def test_duplicate_batch_cannot_cancel_or_resume_preexisting_job(api):
    original = post(api, 1)
    duplicate = post(api, 1)
    base = '/api/v1/batches/' + duplicate['batch_id']
    api.post(base + '/cancel')
    rid = original['runs'][0]['id']
    assert store.one('SELECT status FROM runs WHERE id=?', (rid,))['status'] == 'queued'
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?", (rid,))
    api.post(base + '/resume')
    assert store.one('SELECT status FROM runs WHERE id=?', (rid,))['status'] == 'cancelled'


def test_workspace_isolation_and_no_foreign_job_activation(api):
    alpha = post(api, 7)
    beta = post(api, 1, 100, 'beta')
    base = '/api/v1/batches/' + alpha['batch_id']
    for suffix in ('', '/cancel', '/resume'):
        response = (api.get(base, headers={'x-test-workspace': 'beta'}) if not suffix
                    else api.post(base + suffix, headers={'x-test-workspace': 'beta'}))
        assert response.status_code == 404
    assert api.post(base + '/cancel', json={'item_ids': [beta['items'][0]['id']]}).status_code == 404
    foreign = beta['items'][0]['run_id']
    store.execute("UPDATE runs SET status='waiting_batch' WHERE id=?", (foreign,))
    # Corrupted/stale references are not authority to activate another workspace.
    item = alpha['items'][-1]
    store.execute('UPDATE batch_items SET run_id=? WHERE id=?', (foreign, item['id']))
    batches.admit_pending('alpha')
    api.post(base + '/cancel')
    api.post(base + '/resume')
    assert store.one('SELECT status FROM runs WHERE id=?', (foreign,))['status'] == 'waiting_batch'
    view = api.get(base).json()
    assert foreign not in json.dumps(view)


def seed_runs(workspace, count):
    now = time.time()
    with store.db() as c:
        for _ in range(count):
            c.execute("INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,'parse','queued','{}',?,?)",
                      (store.uid(), workspace, now, now))


def test_existing_upload_ten_cap_and_global_thirty_cap_hold_excess(api):
    seed_runs('alpha', 10)
    seed_runs('other', 20)
    result = post(api, 23)
    assert result['counts'] == {'waiting_batch': 23} and pending() == 30
    store.execute("DELETE FROM runs WHERE workspace='other'")
    assert batches.admit_pending('alpha') == 0 and pending('alpha') == 10
    store.execute("DELETE FROM runs WHERE workspace='alpha' AND payload='{}'")
    seed_runs('other', 29)
    assert batches.admit_pending() == 1 and pending() == 30


def test_waiting_area_bounded_on_new_upload_and_resume(api, monkeypatch):
    monkeypatch.setattr(batches, 'MAX_WORKSPACE_PENDING', 24)
    first = post(api, 23)
    rejected = api.post('/api/v1/documents?index_dense=false', files=uploads(2, 100))
    assert rejected.status_code == 429
    base = '/api/v1/batches/' + first['batch_id']
    api.post(base + '/cancel')
    post(api, 23, 100)
    assert api.post(base + '/resume').status_code == 429
    assert store.one("SELECT count(*) n FROM batch_items WHERE status='cancelled'")['n'] == 23
    assert store.one("SELECT count(*) n FROM batch_items WHERE status IN ('queued','waiting_batch')")['n'] == 23


def test_worker_process_restart_reads_durable_waiting_items(api):
    initial = post(api, 23)
    code = f"""from services.api import batches,jobs
import json
batches.recover_pending_uploads()
assert jobs.work_once()
batches.admit_pending()
print(json.dumps(batches.get_batch('alpha', {initial['batch_id']!r})['counts']))
"""
    env = {**os.environ, 'RT_DATA_DIR': str(store.DATA), 'RT_DISABLE_DENSE': 'true', 'ENABLE_DENSE': 'false'}
    child = subprocess.run([sys.executable, '-c', code], cwd=store.ROOT,
                           env=env, capture_output=True, text=True, timeout=45, check=False)
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == {'completed': 1, 'queued': 6, 'waiting_batch': 16}
    assert store.one('SELECT count(*) n FROM versions')['n'] == 23


def test_interrupted_request_does_not_block_already_accepted_sources(api):
    files = [UploadFile(io.BytesIO(pdf(i)), filename=f'new-{i}.pdf') for i in range(2)]
    batch_id, ids = batches._reserve('alpha', files, False)
    documents.upload_document_file('alpha', files[0].filename, files[0].file,
                                   False, batch_item_id=ids[0], max_bytes=batches.MAX_FILE_BYTES)
    # The API dies before reaching file two or its finally block. A worker may
    # immediately process committed sources but cannot admit the missing source.
    assert batches.admit_pending() == 1
    assert jobs.work_once()
    result = batches.get_batch('alpha', batch_id)
    assert result['counts'] == {'completed': 1, 'uploading': 1}
    store.execute('UPDATE import_batches SET updated=? WHERE id=?', (time.time() - 3601, batch_id))
    batches.recover_pending_uploads()
    result = batches.get_batch('alpha', batch_id)
    assert result['status'] == 'partial' and result['counts'] == {'completed': 1, 'failed': 1}
    assert '重新上传' in result['errors'][0]['error']


def test_partial_parse_resume_keeps_existing_immutable_blocks(api):
    initial = post(api, 1)
    assert jobs.work_once()
    before = store.rows('SELECT * FROM blocks ORDER BY id')
    active = store.rows('SELECT * FROM active_parses')
    item = initial['items'][0]
    store.execute("UPDATE runs SET status='partial',error='Synthetic interrupted indexing' WHERE id=?", (item['run_id'],))
    status = batches.get_batch('alpha', initial['batch_id'])
    assert status['status'] == 'partial' and status['items'][0]['status'] == 'partial'
    batches.resume_batch('alpha', initial['batch_id'], [item['id']])
    assert jobs.work_once()
    assert store.rows('SELECT * FROM blocks ORDER BY id') == before
    assert store.rows('SELECT * FROM active_parses') == active
    assert batches.get_batch('alpha', initial['batch_id'])['status'] == 'completed'


def test_main_registered_routes_use_real_auth_and_bounded_run_resume(api, monkeypatch):
    from services.api import app as application
    monkeypatch.setattr(application, 'DATA', store.DATA)
    monkeypatch.setenv('RT_ACCESS_CODE', 'batch-test-access-only')
    with TestClient(application.app) as client:
        login = client.post('/api/v1/auth/login', json={'code': 'batch-test-access-only'})
        assert login.status_code == 200
        response = client.post('/api/v1/documents?index_dense=false', files=uploads(23))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['counts'] == {'queued': 6, 'waiting_batch': 17}
        base = '/api/v1/batches/' + result['batch_id']
        item = result['items'][0]
        assert client.post(base + '/cancel', json={'item_ids': [item['id']]}).status_code == 200
        resumed = client.post('/api/v1/runs/' + item['run_id'] + '/resume')
        assert resumed.status_code == 200 and resumed.json()['status'] in ('queued', 'waiting_batch')
        assert pending() == 6
        client.cookies.clear()
        assert client.get(base).status_code == 401
        client.post('/api/v1/auth/login', json={'code': 'batch-test-access-only'})
        assert client.get(base).status_code == 404


def test_deleted_waiting_document_cannot_be_admitted_or_resumed(api):
    initial = post(api, 7)
    item = initial['items'][-1]
    store.execute('UPDATE versions SET deleted=1 WHERE id=?', (item['version_id'],))
    store.execute("UPDATE runs SET status='completed' WHERE id=?", (initial['items'][0]['run_id'],))
    batches.admit_pending()
    assert store.one('SELECT status FROM runs WHERE id=?', (item['run_id'],))['status'] == 'cancelled'
    batches.resume_batch('alpha', initial['batch_id'], [item['id']])
    assert store.one('SELECT status FROM runs WHERE id=?', (item['run_id'],))['status'] == 'cancelled'
