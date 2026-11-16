"""Native endpoint/usage and typed judgments, no real API calls."""
import json
import pytest
import httpx
from services.api import decision_service as decision,models,store,jobs


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_DECISION_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','fixture-not-real')
    monkeypatch.setenv('RT_MODEL_DAILY_LIMITS',json.dumps({decision.MODEL:100}))


def test_native_endpoint_keeps_zero_output_usage_and_received_record(isolated,monkeypatch):
    called=[]
    def upstream(request):
        called.append(request)
        assert request.url.path=='/v1beta/decisions'
        body=json.loads(request.content);assert body['model']==decision.MODEL
        return httpx.Response(200,json={'answers':{'route':{'type':'choice','choice':'qa','probabilities':{'qa':.99,'other':.01},'confidence':.99}},'usage':{'total_input_tokens':71,'total_output_tokens':0,'total_tokens':71}})
    monkeypatch.setattr(models,'client',lambda:httpx.Client(transport=httpx.MockTransport(upstream)))
    response=decision.create({'request':'find evidence'},{'route':{'type':'choice','instructions':'fixture','criteria':{'qa':'research','other':'other'}}})
    assert response['usage']['total_output_tokens']==0 and len(called)==1
    quota=store.one('SELECT * FROM quota')
    assert quota['input_tokens']==71 and quota['output_tokens']==0 and quota['status']=='ok'


@pytest.mark.parametrize('answer',[
    {'type':'choice','choice':'supported','probabilities':{'supported':1.2,'other':-.2},'confidence':1},
    {'type':'choice','choice':'supported','probabilities':{'supported':.1,'other':.9},'confidence':.9},
    {'type':'choice','choice':'supported','probabilities':{'supported':.1,'other':.1},'confidence':.9},
    {'type':'choice','choice':'supported','probabilities':{'supported':.9,'other':.1},'confidence':float('nan')},
])
def test_malformed_or_inconsistent_probabilities_cannot_authorize_publish(answer):
    with pytest.raises(ValueError):decision.choice(answer,('supported','other'))


def test_uncertain_routing_is_other_and_cached_without_reissuing(isolated,monkeypatch):
    rid=jobs.queue('w','agent',{'question':'unclear','version_ids':['v']},'decision-routing')['id']
    run={'id':rid,'workspace':'w','payload':{'question':'unclear','version_ids':['v']}}
    calls=[]
    def native(*a,**kwargs):
        calls.append(1)
        return {'answers':{'route':{'type':'choice','choice':'qa','probabilities':{'qa':.55,'other':.2,'translation':.1,'retrieval':.05,'comparison':.05,'future_work':.05},'confidence':.55}}}
    monkeypatch.setattr(decision,'create',native)
    assert decision.route(run)['route']=='other'
    assert decision.route(run)['route']=='other' and len(calls)==1


def test_inference_label_does_not_masquerade_as_reviewed_source_truth():
    data={'claims':[{'id':'i','text':'The training cost is unknown.','type':'inference','evidence':[]}]}
    result=jobs.validate_answer(data,[])
    assert result['status']=='partial' and result['evidence_review']=='not_checked'
