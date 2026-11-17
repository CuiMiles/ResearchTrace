"""Independent condition classifier fixtures; never use a provider or key."""
import json
import time

import pytest

from services.api import coverage_review, decision_service, jobs, models, store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path);store.migrate()
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                  ('audit', 'ws', 'audit', 'running', '{"question":"Are all task conditions covered?"}', time.time(), time.time()))
    monkeypatch.setattr(models, 'client', lambda: pytest.fail('Unexpected provider call'))


def run():
    return {'id': 'audit', 'workspace': 'ws', 'payload': {'question': 'Are all task conditions covered?'}}


def row(category='direct'):
    return {'version_id': 'later', 'category': category,
            'statements': ['The later method reduces memory reads.'],
            'evidence': [{'version_id': 'later', 'quote': 'reduces memory reads'}],
            'time_comparison': {'status': 'later'}}


def native(monkeypatch, selected='partial', confidence=.97, probability=.96):
    calls = []
    def create(shared, questions, run_id, response_key=None):
        calls.append(shared)
        probabilities = {key: (probability if key == selected else (1-probability)/2) for key in coverage_review.CRITERIA}
        result = {'model': 'gemini-decision-1', 'answers': {key: {'type': 'choice', 'choice': selected,
                  'probabilities': probabilities, 'confidence': confidence} for key in questions}}
        jobs.checkpoint({'id': run_id}, {response_key: result})
        return result
    monkeypatch.setattr(decision_service, 'create', create)
    return calls


def test_supported_fact_does_not_prove_all_research_conditions(monkeypatch):
    calls = native(monkeypatch)
    result = coverage_review.review(run(), [row()], {'text': 'Study restricted attention.'})[0]
    assert result['category'] == 'partial'
    assert result['factual_gate_category'] == 'direct'
    assert result['coverage_review']['human_status'] == 'unreviewed'
    assert len(calls) == 1


@pytest.mark.parametrize('category,selected,expected', [
    ('partial', 'direct', 'partial'), ('direct', 'direct', 'direct'),
    ('direct', 'insufficient', 'insufficient'), ('insufficient', 'direct', 'insufficient')])
def test_independent_review_cannot_promote_insufficient_source_gate(monkeypatch, category, selected, expected):
    calls = native(monkeypatch, selected)
    result = coverage_review.review(run(), [row(category)], {'text': 'Original condition'})[0]
    assert result['category'] == expected
    assert len(calls) == (0 if category == 'insufficient' else 1)


def test_low_confidence_does_not_release_positive_coverage(monkeypatch):
    native(monkeypatch, 'direct', confidence=.6)
    result = coverage_review.review(run(), [row()], {'text': 'Original condition'})[0]
    assert result['category'] == 'insufficient' and result['coverage_review']['status'] == 'not_checked'


def test_received_review_is_reused_and_changed_scope_cannot_reuse_it(monkeypatch):
    calls = native(monkeypatch)
    source = {'text': 'Original condition'}
    coverage_review.review(run(), [row()], source)
    assert coverage_review.review(run(), [row()], source)[0]['category'] == 'partial'
    changed = row();changed['statements'] = ['A different new condition.']
    assert coverage_review.review(run(), [changed], source)[0]['category'] == 'insufficient'
    assert len(calls) == 1


def test_interrupted_review_is_never_repeated(monkeypatch):
    calls = []
    def failed(*a, **kwargs):
        calls.append(1);raise models.ModelError('fixture unknown send')
    monkeypatch.setattr(decision_service, 'create', failed)
    for _ in range(2):
        assert coverage_review.review(run(), [row()], {'text': 'Original condition'})[0]['category'] == 'insufficient'
    assert len(calls) == 1
    assert json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?', ('audit',))['checkpoint'])['coverage_review_attempted']


def test_revalidation_copies_received_analysis_without_old_tool_or_coverage_state():
    from services.api.future_work import reuse_analysis
    payload={'version_id':'v','block_id':'b','question':'Original question'}
    original={'model_response':{'text':'received','model':'fixture'},'audit_evidence':[{'id':'b'}],
              'search':{'results':[]},'decision_review_response_fixture':{'answers':{}},
              'tool_registry':{'budget':'must not copy'},'coverage_review_response':{'old':'must recheck'}}
    store.execute("UPDATE runs SET status='completed',payload=?,checkpoint=? WHERE id=?",
                  (json.dumps(payload),json.dumps(original),'audit'))
    child={'id':'recheck','workspace':'ws','payload':{**payload,'analysis_source_run_id':'audit'}}
    store.execute('INSERT INTO runs(id,workspace,kind,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)',
                  ('recheck','ws','audit','running',json.dumps(child['payload']),time.time(),time.time()))
    copied=reuse_analysis(child,{})
    assert copied['model_response']==original['model_response']
    assert copied['analysis_receipt_reused_from']=='audit'
    assert copied['decision_review_response_fixture']==original['decision_review_response_fixture']
    assert 'tool_registry' not in copied and 'coverage_review_response' not in copied
    child['payload']['question']='Changed question'
    with pytest.raises(ValueError,match='范围已变化'):reuse_analysis(child,{})
    child['workspace']='another'
    with pytest.raises(ValueError,match='越权'):reuse_analysis(child,{})
    child['workspace']='ws';child['payload']['question']='Original question'
    store.execute('INSERT INTO quota(id,project,model,day,run_id,started,input_tokens,status) VALUES(?,?,?,?,?,?,?,?)',
                  ('unknown-review','fixture','gemini-decision-1','fixture-day','audit',time.time(),1,'unknown'))
    with pytest.raises(ValueError,match='结果未知'):reuse_analysis(child,{})
