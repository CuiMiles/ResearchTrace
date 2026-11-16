"""Rejected claims require new evidence and review; received calls never replay."""
import io
import json

import pytest
from reportlab.pdfgen import canvas

from services.api import answer_cycle,documents,evidence_validation,jobs,models,retrieval,store


@pytest.fixture
def example(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    pdf=io.BytesIO();c=canvas.Canvas(pdf);c.drawString(30,700,'The experiment used 8 NVIDIA P100 GPUs.');c.save()
    uploaded=documents.upload_document('cycle','new.pdf',pdf.getvalue(),index_dense=False)
    jobs.work_once(pool='documents');vid=uploaded['document']['id']
    block=retrieval._decode(store.one('SELECT * FROM current_blocks WHERE version_id=?',(vid,)))
    run=jobs.queue('cycle','qa',{'version_ids':[vid],'question':'Which GPUs?'},'revision-example')
    run=store.one('SELECT * FROM runs WHERE id=?',(run['id'],))
    run['payload']=json.loads(run['payload'])
    original={'text':json.dumps({'claims':[{'id':'c1','text':'80 NVIDIA P100 GPUs','type':'source_fact','evidence':[{'block_id':block['id'],'quote':block['text']}]}]}),
              'model':'FIXTURE','usage':{}}
    jobs.checkpoint(run,{'model_response':original})
    monkeypatch.setattr(retrieval,'retrieve',lambda *a,**kw:{'blocks':[block],'mode':'FIXTURE_REAL_PDF_SOURCE'})
    return run,vid,block,original


def test_rejected_number_is_revised_reviewed_and_receipt_reused(example,monkeypatch):
    run,vid,block,original=example;calls=[]
    def generate(system,prompt,rid,core=True):
        data=json.loads(prompt);assert data['validation_failure']
        assert data['evidence'][0]['id']==block['id']
        calls.append(data)
        return {'text':json.dumps({'claims':[{'id':'correct','text':block['text'],'type':'source_fact','evidence':[{'block_id':block['id'],'quote':block['text']}]}]}),'model':'FIXTURE_REVISION','usage':{}}
    monkeypatch.setattr(models,'generate',generate)
    result,*_=answer_cycle.complete(run,original,[block],[vid],'Which GPUs?',{'blocks':[block]})
    assert result['status']=='ready' and '80' not in result['answer']
    assert result['revision']['attempts']==1
    assert len(calls)==1
    snap=json.loads(store.one('SELECT checkpoint FROM runs WHERE id=?',(run['id'],))['checkpoint'])
    assert snap['model_response']==original and snap['answer_first_review']['validation_failure']
    again,*_=answer_cycle.complete(run,original,[block],[vid],'Which GPUs?',{'blocks':[block]})
    assert again==result and len(calls)==1


def test_failed_revision_never_publishes_bad_number_or_replays(example,monkeypatch):
    run,vid,block,original=example;calls=[]
    def generate(*a,**kw):
        calls.append(True);raise models.ModelError('FIXTURE sent outcome unknown')
    monkeypatch.setattr(models,'generate',generate)
    for _ in range(2):
        result,*_=answer_cycle.complete(run,original,[block],[vid],'Which GPUs?',{'blocks':[block]})
        assert result['status']=='partial' and result['claims'][0]['type']=='insufficient'
        assert '80' not in result['answer'] and result['revision']['status']=='BLOCKED'
    assert len(calls)==1


def test_exhausted_budget_keeps_rejected_draft_private(example,monkeypatch):
    run,vid,block,original=example
    monkeypatch.setattr(models,'workflow_budget',lambda rid:{'remaining':0})
    monkeypatch.setattr(models,'generate',lambda *a,**kw:pytest.fail('Exhausted budget cannot send'))
    result,*_=answer_cycle.complete(run,original,[block],[vid],'Which GPUs?',{'blocks':[block]})
    assert result['revision']['status']=='BLOCKED' and result['status']=='partial'
    assert all(c['type']=='insufficient' for c in result['claims'])


def test_unavailable_critic_does_not_cause_generation_retry(example,monkeypatch):
    run,vid,block,original=example
    original['text']=json.dumps({'claims':[{'id':'c1','text':'The GPUs were NVIDIA P100.','type':'source_fact','evidence':[{'block_id':block['id'],'quote':block['text']}]}]})
    monkeypatch.setattr(evidence_validation,'review_live',lambda r,v,*a:{**v,'evidence_review':'not_checked','status':'partial'})
    monkeypatch.setattr(models,'generate',lambda *a,**kw:pytest.fail('Unavailable critic is not a repair signal'))
    result,*_=answer_cycle.complete(run,original,[block],[vid],'Which GPUs?',{'blocks':[block]})
    assert result['status']=='partial' and 'revision' not in result
