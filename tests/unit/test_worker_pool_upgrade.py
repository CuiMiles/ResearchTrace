"""Cross-process executor isolation: no upstream models are called."""
import io
import json
import multiprocessing
import time
from pathlib import Path

import pytest
from services.api import jobs,store
from services.worker import main as worker


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    return tmp_path


def _hold_pool(root,pool,ready,release):
    store.DATA=Path(root)
    with worker.worker_lock(pool):ready.set();release.wait(10)


def _hold_execution(root,rid,ready,release):
    store.DATA=Path(root)
    with store.run_execution_lock(rid) as acquired:
        assert acquired
        ready.set();release.wait(10)


def test_split_pools_can_coexist_but_legacy_and_duplicate_cannot(isolated):
    ctx=multiprocessing.get_context('spawn');ready=ctx.Event();release=ctx.Event()
    child=ctx.Process(target=_hold_pool,args=(str(isolated),'documents',ready,release));child.start()
    try:
        assert ready.wait(5)
        with worker.worker_lock('interactive'):pass
        with pytest.raises(RuntimeError):
            with worker.worker_lock('documents'):pass
        with pytest.raises(RuntimeError):
            with worker.worker_lock('all'):pass
    finally:
        release.set();child.join(5)
    assert child.exitcode==0


def test_recovery_skips_live_owner_and_never_resets_other_pool(isolated):
    rid=jobs.queue('w','qa',{},'interactive-running')['id'];doc=jobs.queue('w','parse',{},'doc-running')['id']
    store.execute("UPDATE runs SET status='running'")
    ctx=multiprocessing.get_context('spawn');ready=ctx.Event();release=ctx.Event()
    child=ctx.Process(target=_hold_execution,args=(str(isolated),rid,ready,release));child.start()
    try:
        assert ready.wait(5)
        assert worker.recover('interactive')==[]
        assert store.one('SELECT status FROM runs WHERE id=?',(doc,))['status']=='running'
    finally:
        release.set();child.join(5)
    assert worker.recover('interactive')==[rid]
    assert store.one('SELECT status FROM runs WHERE id=?',(rid,))['status']=='queued'
    assert store.one('SELECT status FROM runs WHERE id=?',(doc,))['status']=='running'


def test_unknown_sent_request_never_automatically_retries(isolated):
    rid=jobs.queue('w','qa',{},'sent-unknown')['id'];store.execute("UPDATE runs SET status='running'")
    store.execute("INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,status) VALUES('q','p','fixture','day',?,?,1,'reserved')",(rid,time.time()))
    assert worker.recover('interactive')==[rid]
    assert store.one('SELECT status FROM runs WHERE id=?',(rid,))['status']=='partial'
    assert store.one("SELECT status FROM quota WHERE id='q'")['status']=='unknown'
    assert not jobs.work_once(pool='interactive')


def test_interaction_claim_does_not_wait_for_earlier_document(isolated,monkeypatch):
    doc=jobs.queue('w','parse',{},'older-document')['id']
    qa=jobs.queue('w','qa',{},'newer-interaction')['id']
    monkeypatch.setattr(jobs,'qa',lambda run:{'answer':'fixture only','status':'ready'})
    assert jobs.work_once(pool='interactive')
    assert store.one('SELECT status FROM runs WHERE id=?',(qa,))['status']=='completed'
    assert store.one('SELECT status FROM runs WHERE id=?',(doc,))['status']=='queued'


def test_fulltext_parse_runs_before_older_index_slice(isolated,monkeypatch):
    from services.api import documents
    index=jobs.queue('w','index',{},'older-index')['id']
    parse=jobs.queue('w','parse',{},'new-fulltext')['id']
    monkeypatch.setattr(documents,'parse_document',lambda run:{'status':'ready','fixture':True})
    assert jobs.work_once(pool='documents')
    assert store.one('SELECT status FROM runs WHERE id=?',(parse,))['status']=='completed'
    assert store.one('SELECT status FROM runs WHERE id=?',(index,))['status']=='queued'


def test_health_does_not_trust_expired_heartbeat(isolated):
    import os
    from services.api.worker_health import read_worker_status
    path=isolated/'worker-status-documents.json'
    path.write_text(json.dumps({'pool':'documents','pid':os.getpid(),'timestamp':time.time()-60,'busy':True}))
    assert not read_worker_status('documents',data_dir=isolated)['healthy']
    data=json.loads(path.read_text());data['timestamp']=time.time();path.write_text(json.dumps(data))
    assert read_worker_status('documents',data_dir=isolated)['healthy']
