"""Bounded, durable multipart PDF imports; never submit model requests here.

The application owns authentication and route registration. Call upload_batch
from POST /documents; expose get_batch, cancel_batch and resume_batch under
/batches/{id}. Optional item_ids restrict either action to selected files.
"""
import asyncio
import json
import os
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from fastapi import HTTPException

from . import documents
from .store import db, run_execution_lock, uid

MAX_FILES = 50
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_BYTES = 250 * 1024 * 1024
MAX_WORKSPACE_PENDING = 200
MAX_GLOBAL_PENDING = 1000
WORKSPACE_ACTIVE = 6  # Also below the legacy upload cap of ten.
GLOBAL_ACTIVE = 30
PENDING = ('uploading', 'waiting_batch', 'queued', 'running')


def _batch(c, workspace, batch_id):
    row = c.execute('SELECT * FROM import_batches WHERE id=? AND workspace=?',
                    (batch_id, workspace)).fetchone()
    if row is None:
        raise HTTPException(404, '批次不存在或无权限')
    return dict(row)


def _sync(c, workspace=None, batch_id=None):
    """Copy genuine run states, never trust a bare item.run_id for ownership."""
    where = ''
    args = []
    if workspace is not None:
        where += ' AND i.workspace=?'
        args.append(workspace)
    if batch_id is not None:
        where += ' AND i.batch_id=?'
        args.append(batch_id)
    c.execute("""UPDATE batch_items AS i SET
        status=(SELECT r.status FROM runs r WHERE r.id=i.run_id),
        error=(SELECT r.error FROM runs r WHERE r.id=i.run_id),updated=?
        WHERE i.status IN ('waiting_batch','queued','running','failed','partial') AND EXISTS(
          SELECT 1 FROM runs r JOIN versions v ON v.id=i.version_id
          WHERE r.id=i.run_id AND r.workspace=i.workspace AND v.workspace=i.workspace
          AND r.kind='parse' AND json_extract(r.payload,'$.version_id')=i.version_id
          AND (r.status<>i.status OR COALESCE(r.error,'')<>COALESCE(i.error,'')))""" + where,
              [time.time(), *args])


def _snapshot(c, workspace, batch_id):
    batch = _batch(c, workspace, batch_id)
    _sync(c, workspace, batch_id)
    items = [dict(r) for r in c.execute(
        'SELECT * FROM batch_items WHERE batch_id=? AND workspace=? ORDER BY ordinal',
        (batch_id, workspace))]
    docs, runs, errors = [], [], []
    counts = Counter()
    for item in items:
        item.pop('workspace', None)
        item['duplicate'] = bool(item['duplicate'])
        item['owns_run'] = bool(item['owns_run'])
        counts[item['status']] += 1
        if item['version_id']:
            v = c.execute('SELECT * FROM versions WHERE id=? AND workspace=? AND deleted=0',
                          (item['version_id'], workspace)).fetchone()
            if v:
                v = dict(v)
                v.pop('path', None)
                v.pop('workspace', None)
                v['metadata'] = json.loads(v['metadata'])
                active = c.execute('SELECT parse_id FROM active_parses WHERE version_id=?', (v['id'],)).fetchone()
                v['active_parse_id'] = active['parse_id'] if active else v['id']
                v['duplicate'] = item['duplicate']
                docs.append(v)
        if item['run_id']:
            # Foreign or corrupted references must not appear in API responses.
            run = c.execute("SELECT id,status FROM runs WHERE id=? AND workspace=? AND kind='parse' AND json_extract(payload,'$.version_id')=?",
                            (item['run_id'], workspace, item['version_id'])).fetchone()
            if run:
                runs.append({'id': run['id'], 'run_id': run['id'], 'status': run['status']})
            else:
                item['run_id'] = None
        if item['error']:
            errors.append({'item_id': item['id'], 'filename': item['filename'], 'error': item['error']})
    if batch['status'] == 'uploading':
        status = 'uploading'
    elif any(counts[s] for s in PENDING):
        status = 'active'
    elif counts['cancelled'] == len(items):
        status = 'cancelled'
    elif counts['completed'] == len(items):
        status = 'completed'
    elif counts['failed'] == len(items):
        status = 'failed'
    else:
        status = 'partial'
    if status != batch['status']:
        c.execute('UPDATE import_batches SET status=?,updated=? WHERE id=? AND workspace=?',
                  (status, time.time(), batch_id, workspace))
    batch.pop('workspace', None)
    batch.update(status=status, index_dense=bool(batch['index_dense']),
                 batch_id=batch_id, items=items, errors=errors, documents=docs,
                 runs=runs, counts=dict(counts))
    return batch


def get_batch(workspace, batch_id):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return _snapshot(c, workspace, batch_id)


def _sizes(files):
    total = 0
    for upload in files:
        # A multipart UploadFile is already a disk-spooled, seekable file.
        upload.file.seek(0, os.SEEK_END)
        total += upload.file.tell()
        upload.file.seek(0)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(413, '单次批量上传总大小上限250 MiB')


def _reserve(workspace, files, index_dense):
    now, batch_id = time.time(), uid()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        _sync(c)
        for scope, args, cap in (
            (' AND workspace=?', (workspace,), MAX_WORKSPACE_PENDING),
            ('', (), MAX_GLOBAL_PENDING),
        ):
            count = c.execute("SELECT count(*) FROM batch_items WHERE status IN ('uploading','waiting_batch','queued','running')" + scope, args).fetchone()[0]
            if count + len(files) > cap:
                raise HTTPException(429, '批量导入等待区已满；请等待或取消已有批次')
        c.execute('INSERT INTO import_batches(id,workspace,status,index_dense,created,updated) VALUES(?,?,?,?,?,?)',
                  (batch_id, workspace, 'uploading', int(index_dense), now, now))
        ids = []
        for ordinal, upload in enumerate(files):
            item_id = uid()
            ids.append(item_id)
            filename = Path((upload.filename or 'upload.pdf').replace('\\', '/')).name[:240]
            c.execute('INSERT INTO batch_items(id,batch_id,workspace,ordinal,filename,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                      (item_id, batch_id, workspace, ordinal, filename, 'uploading', now, now))
    return batch_id, ids


async def upload_batch(workspace, files, index_dense=True):
    """One request, up to fifty independent imports, with bounded disk backlog."""
    if not 1 <= len(files) <= MAX_FILES:
        raise HTTPException(413, '单次请选择1至50个PDF文件')
    await asyncio.to_thread(_sizes, files)
    batch_id, ids = await asyncio.to_thread(_reserve, workspace, files, index_dense)
    try:
        for upload, item_id in zip(files, ids):
            try:
                await asyncio.to_thread(
                    documents.upload_document_file, workspace, upload.filename or 'upload.pdf',
                    upload.file, index_dense, batch_item_id=item_id, max_bytes=MAX_FILE_BYTES)
            except (ValueError, OSError) as exc:
                # Controlled validation messages are safe; OS errors may contain paths.
                message = str(exc)[:250] if isinstance(exc, ValueError) else '文件落盘失败；请检查存储后重新上传'
                with db() as c:
                    c.execute("UPDATE batch_items SET status='failed',error=?,updated=? WHERE id=? AND workspace=? AND status='uploading'",
                              (message, time.time(), item_id, workspace))
    finally:
        with db() as c:
            # Unaccepted files have no source bytes after an interrupted request.
            c.execute("UPDATE batch_items SET status='failed',error='上传中断；此文件需重新上传',updated=? WHERE batch_id=? AND workspace=? AND status='uploading'",
                      (time.time(), batch_id, workspace))
            c.execute("UPDATE import_batches SET status='active',updated=? WHERE id=? AND workspace=? AND status='uploading'",
                      (time.time(), batch_id, workspace))
    await asyncio.to_thread(admit_pending, workspace)
    result = await asyncio.to_thread(get_batch, workspace, batch_id)
    if not result['documents'] and result['counts'].get('failed') == len(files):
        raise HTTPException(422, {'message': '没有文件通过PDF校验', 'batch_id': batch_id,
                                  'items': result['items'], 'errors': result['errors']})
    return result


def _owned_run(c, item):
    if not item['owns_run'] or not item['run_id']:
        return None
    return c.execute("""SELECT r.* FROM runs r JOIN versions v ON v.id=?
        WHERE r.id=? AND r.workspace=? AND v.workspace=r.workspace AND r.kind='parse'
        AND json_extract(r.payload,'$.version_id')=v.id
        AND json_extract(r.payload,'$.batch_id')=?
        AND json_extract(r.payload,'$.batch_item_id')=?""",
                     (item['version_id'], item['run_id'], item['workspace'], item['batch_id'], item['id'])).fetchone()


def admit_pending(workspace=None, limit=WORKSPACE_ACTIVE):
    """Atomically move bounded waiting imports into the ordinary worker queue."""
    admitted = 0
    now = time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        _sync(c, workspace)
        total = c.execute("SELECT count(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0]
        if total >= GLOBAL_ACTIVE:
            return 0
        query = """SELECT i.* FROM batch_items i JOIN import_batches b
            ON b.id=i.batch_id AND b.workspace=i.workspace
            WHERE b.status='active' AND i.status='waiting_batch' AND i.owns_run=1"""
        args = []
        if workspace is not None:
            query += ' AND i.workspace=?'
            args.append(workspace)
        # The durable waiting area is bounded independently of queued/running.
        query += ' ORDER BY i.created,i.ordinal LIMIT ?'
        args.append(MAX_GLOBAL_PENDING)
        pending_by_workspace = {}
        for item in c.execute(query, args).fetchall():
            if admitted >= max(0, min(limit, GLOBAL_ACTIVE - total)):
                break
            w = item['workspace']
            if w not in pending_by_workspace:
                pending_by_workspace[w] = c.execute("SELECT count(*) FROM runs WHERE workspace=? AND status IN ('queued','running')", (w,)).fetchone()[0]
            if pending_by_workspace[w] >= WORKSPACE_ACTIVE:
                continue
            run = _owned_run(c, item)
            if not run or run['status'] != 'waiting_batch':
                continue
            version = c.execute('SELECT deleted FROM versions WHERE id=? AND workspace=?', (item['version_id'], w)).fetchone()
            if version['deleted']:
                c.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=? AND workspace=?", (now, run['id'], w))
                c.execute("UPDATE batch_items SET status='cancelled',error='文档已删除',updated=? WHERE id=? AND workspace=?", (now, item['id'], w))
                continue
            c.execute("UPDATE runs SET status='queued',updated=? WHERE id=? AND workspace=?", (now, run['id'], w))
            c.execute("UPDATE batch_items SET status='queued',updated=? WHERE id=? AND workspace=?", (now, item['id'], w))
            c.execute("UPDATE versions SET status='queued' WHERE id=? AND workspace=? AND status='waiting_batch'", (item['version_id'], w))
            c.execute("INSERT INTO steps(run_id,event,data,created) VALUES(?,'queued',?,?)", (run['id'], json.dumps({'batch_id': item['batch_id'], 'tool': 'parse_document'}), now))
            pending_by_workspace[w] += 1
            admitted += 1
    return admitted


def recover_pending_uploads():
    """Worker startup: keep accepted sources; fail only interrupted file uploads.

    A live API upload must not be interrupted when a worker happens to restart.
    Only stale requests (one hour) are recovered; normally finally closes them.
    """
    cutoff = time.time() - 3600
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE batch_items SET status='failed',error='上传中断；此文件需重新上传',updated=? WHERE status='uploading' AND batch_id IN (SELECT id FROM import_batches WHERE status IN ('uploading','active') AND updated<?)", (time.time(), cutoff))
        c.execute("UPDATE import_batches SET status='active',updated=? WHERE status='uploading' AND updated<?", (time.time(), cutoff))


def _selection(c, workspace, batch_id, item_ids):
    _batch(c, workspace, batch_id)
    items = c.execute('SELECT * FROM batch_items WHERE batch_id=? AND workspace=? ORDER BY ordinal', (batch_id, workspace)).fetchall()
    if item_ids is None:
        return items
    if not isinstance(item_ids, list) or len(item_ids) > MAX_FILES or any(not isinstance(i, str) for i in item_ids):
        raise HTTPException(422, 'item_ids须为最多50个文件ID的列表')
    wanted = set(item_ids)
    if wanted - {i['id'] for i in items}:
        raise HTTPException(404, '批次文件不存在或无权限')
    return [i for i in items if i['id'] in wanted]


def cancel_batch(workspace, batch_id, item_ids=None):
    now = time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        _sync(c, workspace, batch_id)
        for item in _selection(c, workspace, batch_id, item_ids):
            if item['status'] == 'completed':
                continue
            run = _owned_run(c, item)
            if run and run['status'] != 'completed':
                c.execute("UPDATE runs SET status='cancelled',updated=? WHERE id=? AND workspace=?", (now, run['id'], workspace))
                c.execute("UPDATE parses SET status='cancelled' WHERE id=? AND workspace=? AND status NOT IN ('ready','completed')", (item['version_id'], workspace))
                c.execute("INSERT INTO steps(run_id,event,data,created) VALUES(?,'cancelled',?,?)", (run['id'], json.dumps({'batch_id': batch_id}), now))
            c.execute("UPDATE batch_items SET status='cancelled',updated=? WHERE id=? AND workspace=?", (now, item['id'], workspace))
        if item_ids is None:
            c.execute("UPDATE import_batches SET status='cancelled',updated=? WHERE id=? AND workspace=?", (now, batch_id, workspace))
        return _snapshot(c, workspace, batch_id)


def resume_batch(workspace, batch_id, item_ids=None):
    now = time.time()
    with ExitStack() as locks, db() as c:
        c.execute('BEGIN IMMEDIATE')
        _sync(c)
        items = _selection(c, workspace, batch_id, item_ids)
        workspace_pending = c.execute("SELECT count(*) FROM batch_items WHERE workspace=? AND status IN ('uploading','waiting_batch','queued','running')", (workspace,)).fetchone()[0]
        global_pending = c.execute("SELECT count(*) FROM batch_items WHERE status IN ('uploading','waiting_batch','queued','running')").fetchone()[0]
        for item in items:
            run = _owned_run(c, item)
            # Cancelling a duplicate pauses only that reference. Resuming it may
            # observe its existing task, but never reactivate another batch's job.
            if not run and item['duplicate'] and item['status'] == 'cancelled':
                reference = c.execute("SELECT r.status,r.error FROM runs r JOIN versions v ON v.id=? WHERE r.id=? AND r.workspace=? AND v.workspace=r.workspace AND v.deleted=0 AND r.kind='parse' AND json_extract(r.payload,'$.version_id')=v.id", (item['version_id'], item['run_id'], workspace)).fetchone()
                if reference:
                    if reference['status'] in PENDING:
                        if workspace_pending >= MAX_WORKSPACE_PENDING or global_pending >= MAX_GLOBAL_PENDING:
                            raise HTTPException(429, '批量导入等待区已满；请等待或取消已有批次')
                        workspace_pending += 1
                        global_pending += 1
                    c.execute('UPDATE batch_items SET status=?,error=?,updated=? WHERE id=? AND workspace=?', (reference['status'], reference['error'], now, item['id'], workspace))
                continue
            if not run or run['status'] not in ('cancelled', 'failed', 'partial'):
                continue
            v = c.execute('SELECT deleted FROM versions WHERE id=? AND workspace=?', (item['version_id'], workspace)).fetchone()
            if v['deleted']:
                continue
            if workspace_pending >= MAX_WORKSPACE_PENDING or global_pending >= MAX_GLOBAL_PENDING:
                raise HTTPException(429, '批量导入等待区已满；请等待或取消已有批次')
            if not locks.enter_context(run_execution_lock(run['id'])):
                raise HTTPException(409, '任务正在释放资源，请稍后恢复')
            c.execute("UPDATE runs SET status='waiting_batch',error=NULL,updated=? WHERE id=? AND workspace=?", (now, run['id'], workspace))
            c.execute("UPDATE batch_items SET status='waiting_batch',error=NULL,updated=? WHERE id=? AND workspace=?", (now, item['id'], workspace))
            c.execute("UPDATE parses SET status='queued',error=NULL WHERE id=? AND workspace=? AND status NOT IN ('ready','completed')", (item['version_id'], workspace))
            c.execute("INSERT INTO steps(run_id,event,data,created) VALUES(?,'waiting_batch',?,?)", (run['id'], json.dumps({'batch_id': batch_id, 'resumed': True}), now))
            workspace_pending += 1
            global_pending += 1
        c.execute("UPDATE import_batches SET status='active',updated=? WHERE id=? AND workspace=?", (now, batch_id, workspace))
    admit_pending(workspace)
    return get_batch(workspace, batch_id)
