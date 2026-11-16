"""Date uncertainty and automatic fulltext state transitions, explicit fixtures."""
import json
import pytest
from services.api import store,jobs,future_work,research
from services.api.temporal import publication_window,compare_time


def test_same_year_later_month_is_included_but_overlapping_year_is_not():
    old={'identity':'arxiv:2402.00001'}
    assert compare_time(old,{'published':'2024-08-12T10:00:00Z'})['status']=='later'
    assert compare_time(old,{'year':2024})['status']=='overlap'
    assert compare_time(old,{'identity':'arxiv:2401.00002'})['status']=='earlier'
    assert compare_time({}, {'published':'2025-01-01'})['status']=='unknown'
    assert publication_window({'year':2024})['latest']=='2024-12-31'


def test_chinese_query_plan_is_received_once_and_preserves_original_request(tmp_path,monkeypatch):
    from services.api import models
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    payload={'question':'局部注意力是否支持更长序列？'}
    rid=jobs.queue('w','audit',payload,'query-plan')['id']
    run={'id':rid,'workspace':'w','payload':payload}
    calls=[]
    def generate(system,prompt,run_id,core=True):
        calls.append(core);assert json.loads(prompt)['question']==payload['question']
        return {'text':json.dumps({'query':'local attention long sequences'}),'model':'FIXTURE_PLANNER','usage':{}}
    monkeypatch.setattr(models,'generate',generate)
    for _ in range(2):
        snap=json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?',(rid,))['checkpoint'])
        assert future_work.planned_query(run,{'text':'restricted local attention'},snap)=='local attention long sequences'
    assert calls==[False]
    assert run['payload']==payload
    assert not store.rows('SELECT * FROM quota')


def test_fulltext_download_waits_for_own_parser_then_wakes(tmp_path,monkeypatch):
    from services.api.dependencies import wake_dependencies,cancel_owned_children
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_FUTURE_FULLTEXT','true')
    with store.db() as c:
        c.execute("INSERT INTO works VALUES('old','w','Old paper','arxiv:2402.00001','{}')")
        c.execute("INSERT INTO versions(id,workspace,work_id,title,filename,sha256,path,identity,created) VALUES('v','w','old','Old paper','old.pdf','hash','unused','arxiv:2402.00001',1)")
        c.execute("INSERT INTO blocks VALUES('b','w','v',0,'[0,0,1,1]','text',0,'Future work: longer sequences.','fixture','native','{}')")
    paper={'identity':'arxiv:2408.00002','published':'2024-08-12','source':'arxiv','title':'Later paper'}
    monkeypatch.setattr(research,'search_papers',lambda *a,**kw:{'results':[paper],'searched_at':1,'status':'success'})
    called=[]
    def import_fixture(workspace,paper,**kwargs):
        called.append(kwargs)
        child=jobs.queue(workspace,'parse',{'version_id':'child-version'},'download-fixture')
        return {'metadata_only':False,'document':{'id':'child-version'},'run_id':child['id'],'duplicate':False}
    monkeypatch.setattr(research,'import_paper',import_fixture)
    parent=jobs.queue('w','audit',{'version_id':'v','block_id':'b','question':'longer sequences'},'audit-fixture')
    run={**store.one('SELECT * FROM runs WHERE id=?',(parent['id'],)),'payload':{'version_id':'v','block_id':'b','question':'longer sequences'}}
    result=future_work.audit(run)
    assert result['status']=='waiting_children'
    assert called==[{'index_dense':False,'metadata_only':False}]
    assert not store.rows('SELECT * FROM quota')
    store.execute("UPDATE runs SET status='waiting_children' WHERE id=?",(parent['id'],))
    assert wake_dependencies()==[]
    # Parent cancellation only stops its own newly downloaded parse, not others.
    child=result['downloads'][0]['run_id']
    foreign=jobs.queue('other','parse',{'parent_run_id':parent['id']},'other-child')['id']
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?",(parent['id'],))
    cancel_owned_children('w',parent['id'])
    assert store.one('SELECT status FROM runs WHERE id=?',(child,))['status']=='cancelled'
    assert store.one('SELECT status FROM runs WHERE id=?',(foreign,))['status']=='queued'
