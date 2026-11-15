"""Real local thread/file-lock lifecycle with fixture parser, no model inference."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from services.api import app,documents,jobs,store


def test_resume_waits_for_old_execution_to_release_resources(tmp_path,monkeypatch):
    for mod in (app,documents,store):monkeypatch.setattr(mod,'DATA',tmp_path)
    monkeypatch.setattr(app,'LOGIN_ATTEMPTS',{})
    monkeypatch.setenv('RT_ACCESS_CODE','ownership-fixture')
    entered=threading.Event();released=threading.Event()
    calls=[]
    def slow(run):
        calls.append(run['id']);entered.set()
        assert released.wait(5)
        return {'status':'ready','parsed_pages':1}
    monkeypatch.setattr(documents,'parse_document',slow)
    with TestClient(app.app) as c:
        c.post('/api/v1/auth/login',json={'code':'ownership-fixture'}).raise_for_status()
        w=c.get('/api/v1/auth/session').json()['workspace']
        r=jobs.queue(w,'parse',{'version_id':'fixture'},'owned-execution')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(jobs.work_once)
            try:
                assert entered.wait(5)
                assert c.post('/api/v1/runs/'+r['id']+'/cancel').status_code==200
                resume=c.post('/api/v1/runs/'+r['id']+'/resume')
                assert resume.status_code==409
                assert store.one('SELECT status FROM runs WHERE id=?',(r['id'],))['status']=='cancelled'
                assert calls==[r['id']]
            finally:
                released.set()
                future.result(timeout=5)
        assert c.post('/api/v1/runs/'+r['id']+'/resume').status_code==200
        assert jobs.work_once()
        assert calls==[r['id'],r['id']]
        assert store.one('SELECT status FROM runs WHERE id=?',(r['id'],))['status']=='completed'
        assert store.one('SELECT count(*) n FROM quota')['n']==0
        watch=jobs.queue(w,'watch',{'watch_id':'fixture-watch'},'watch-not-a-worker-job')
        store.execute("UPDATE runs SET status='failed' WHERE id=?",(watch['id'],))
        assert c.post('/api/v1/runs/'+watch['id']+'/resume').status_code==409
        assert store.one('SELECT status FROM runs WHERE id=?',(watch['id'],))['status']=='failed'
