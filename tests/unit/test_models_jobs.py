"""Quota, grounding and idempotency tests. All upstream responses are explicit fixtures."""
import concurrent.futures
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from services.api import store, models, jobs

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    store.migrate()
    monkeypatch.setenv('HYDROGEN_SMOKE_LIMIT','4')
    monkeypatch.setenv('HYDROGEN_SESSION_LIMIT','2')
    monkeypatch.setenv('RT_SMOKE_MODE','true')

def test_project_aliases_share_daily_budget():
    now=1780000000
    for i in range(20):
        qid=models.reserve('same-project',models.CORE,100,None,now+i*61)
        store.execute("UPDATE quota SET status='ok' WHERE id=?",(qid,))
        if i==3:
            break
    with pytest.raises(models.ModelError,match='冒烟预算'):
        models.reserve('second-key-same-project',models.CORE,100,None,now+300)
    # Smoke guard is GLOBAL and cannot be multiplied by key/project count.
    assert store.one('SELECT count(*) n FROM quota')['n']==4

def test_rpm_tpm_atomic_concurrency():
    def claim(_):
        try:
            return models.reserve('same',models.BATCH,200000,None,1780000000)
        except models.ModelError:
            return None
    # Each context is capped at96K, no oversized reservation can pass.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(claim,range(3)))==[None,None,None]
    def bounded(_):
        try:
            return models.reserve('same',models.BATCH,90000,None,1780000000)
        except models.ModelError:
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(bool(x) for x in pool.map(bounded,range(3)))==1

def test_pacific_day_and_dst():
    tz=ZoneInfo('America/Los_Angeles')
    before=datetime(2026,3,8,0,1,tzinfo=tz).timestamp()
    after=models.reset_at(before)
    # Spring forward: this local quota day is23hours.
    assert after-before==23*3600-60
    fall=datetime(2026,11,1,0,1,tzinfo=tz).timestamp()
    assert models.reset_at(fall)-fall==25*3600-60
    assert models.quota_day(before)=='2026-03-08'

def test_rpd_persists_between_reservations():
    model='fixture-batch'
    for i in range(500):
        store.execute('INSERT INTO quota(id,project,model,day,started,input_tokens,status) VALUES(?,?,?,?,?,?,?)',(str(i),'p',model,models.quota_day(1780000000),1780000000-5000,1,'failed'))
    with pytest.raises(models.ModelError,match='日额度'):
        models.reserve('p',model,10,None,1780000000)

def test_invalid_reference_and_mismatching_quote_rejected():
    blocks=[{'id':'block','version_id':'v1','page_index':4,'bbox':[.1,.2,.3,.4],'text':'Eight GPUs were used.'}]
    data={'answer':'8 GPUs','claims':[{'text':'8 GPUs','type':'source_fact','evidence':[{'block_id':'nonexistent','quote':'Eight GPUs'}]}]}
    with pytest.raises(ValueError,match='引用'):
        jobs.validate_answer(data,blocks)
    data['claims'][0]['evidence'][0]={'block_id':'block','quote':'Sixty GPUs'}
    with pytest.raises(ValueError):
        jobs.validate_answer(data,blocks)
    data['claims'][0]['evidence'][0]['quote']='Eight GPUs'
    result=jobs.validate_answer(data,blocks)
    assert result['claims'][0]['evidence'][0]['version_id']=='v1'
    assert result['claims'][0]['evidence'][0]['status']=='located_semantics_pending'

def test_idempotency_payload_conflict_and_cancel_before_request():
    a=jobs.queue('w','qa',{'question':'first'},'same-key')
    b=jobs.queue('w','qa',{'question':'first'},'same-key')
    assert a['id']==b['id']
    assert b['reused']
    with pytest.raises(ValueError,match='幂等'):
        jobs.queue('w','qa',{'question':'different'},'same-key')
    store.execute("UPDATE runs SET status='cancelled' WHERE id=?",(a['id'],))
    with pytest.raises(models.ModelError,match='取消'):
        models.reserve('p',models.BATCH,10,a['id'])
    assert store.one('SELECT count(*) n FROM quota')['n']==0

def test_no_paid_route_and_no_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    monkeypatch.setenv('ALLOW_PAID_FALLBACK','true')
    with pytest.raises(models.ModelError,match='无可用免费路由'):
        models.generate('test','no api','none')
    assert models.provider_report()['paid_fallback'] is False

def test_three_workspaces_get_independent_runs():
    rs=[jobs.queue(w,'qa',{'q':w},'same-idem') for w in ['reviewer1','reviewer2','reviewer3']]
    assert len({r['id'] for r in rs})==3
    assert store.one("SELECT count(*) n FROM runs WHERE status='queued'")['n']==3

def test_two_keys_same_project_are_not_two_quota_groups(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','unit-key-one')
    monkeypatch.setenv('GEMINI_API_KEY2','unit-key-two')
    monkeypatch.setenv('GEMINI_PROJECT_1','p1')
    monkeypatch.setenv('GEMINI_PROJECT_2','p1')
    assert len(list(models._choose(models.BATCH)))==1
    monkeypatch.setenv('GEMINI_PROJECT_2','p2')
    assert len(list(models._choose(models.BATCH)))==2

@pytest.mark.parametrize('status,category,disabled',[(401,'UNAUTHENTICATED',True),(403,'PERMISSION_DENIED',True),(404,'NOT_FOUND',True),(429,'RESOURCE_EXHAUSTED',False),(500,'INTERNAL',False)])
def test_http_failures_are_bounded_counted_and_redacted(monkeypatch,status,category,disabled):
    import httpx
    monkeypatch.setenv('GEMINI_API_KEY','private-fixture-key')
    monkeypatch.setenv('GEMINI_PROJECT_1','fixture-project')
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    calls=[]
    def upstream(req):
        calls.append(req)
        return httpx.Response(status,json={'error':{'status':category,'message':'sensitive upstream text private-fixture-key'}})
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(upstream)))
    with pytest.raises(models.ModelError) as caught:
        models.generate('fixture system','fixture prompt',None,core=False)
    assert 'private-fixture-key' not in str(caught.value)
    assert len(calls)==1
    q=store.one('select * from quota')
    assert q['status']==('disabled' if disabled else 'failed')
    assert q['input_tokens']>0

def test_timeout_bad_json_and_truncation_count_without_fake_success(monkeypatch):
    import httpx
    monkeypatch.setenv('GEMINI_API_KEY','unit-key')
    monkeypatch.setenv('GEMINI_PROJECT_1','p')
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    def timeout(req):
        raise httpx.ReadTimeout('fixture timeout')
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(timeout)))
    with pytest.raises(models.ModelError,match='未知'):
        models.generate('s','p',None,False)
    assert store.one('select status from quota')['status']=='unknown'
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,text='{bad'))))
    with pytest.raises(models.ModelError,match='JSON'):
        models.generate('s','p',None,False)
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}))))
    with pytest.raises(models.ModelError,match='完整'):
        models.generate('s','p',None,False)
    assert store.one('select count(*) n from quota')['n']==3

def test_actual_model_version_and_reasoning_usage(monkeypatch):
    import httpx
    monkeypatch.setenv('GEMINI_API_KEY','unit-key')
    monkeypatch.setenv('GEMINI_PROJECT_1','p')
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    payload={'modelVersion':'actual-upstream-version','candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'{"ok":true}'}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':3,'thoughtsTokenCount':2,'totalTokenCount':15}}
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))))
    result=models.generate('s','p',None,False)
    assert result['model']=='actual-upstream-version'
    assert store.one('select output_tokens from quota')['output_tokens']==5

def test_free_tier_exhaustion_disables_route(monkeypatch):
    import httpx
    monkeypatch.setenv('GEMINI_API_KEY','unit-key')
    monkeypatch.setenv('GEMINI_PROJECT_1','p')
    monkeypatch.delenv('GEMINI_API_KEY2',raising=False)
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(400,json={'error':{'status':'BAD_REQUEST','message':'AllocationQuota.FreeTierOnly'}}))))
    with pytest.raises(models.ModelError):
        models.generate('s','p',None,False)
    assert store.one('select status from provider_state')['status']=='disabled'
    assert list(models._choose(models.BATCH))==[]

def test_bounded_pdf_line_hyphen_repair_preserves_raw_source():
    raw='It combines a local windowed attention with a task moti- vated global attention.'
    block={'id':'b','version_id':'v','page_index':3,'bbox':[0,0,1,1],'text':raw}
    data={'answer':'有证据','claims':[{'text':'局部与全局注意力结合','type':'source_fact','evidence':[{'block_id':'b','quote':'It combines a local windowed attention with a task motivated global attention.'}]}]}
    result=jobs.validate_answer(data,[block])
    evidence=result['claims'][0]['evidence'][0]
    assert evidence['quote']==raw
    assert evidence['repair']=='pdf_layout_normalization'
    data['claims'][0]['evidence'][0]['quote']='It combines a completely different mechanism with 999 global attention.'
    with pytest.raises(ValueError):
        jobs.validate_answer(data,[block])
