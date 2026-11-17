"""Explicit planner fixtures verify feedback and durable child waits, no LLM calls."""
import io
import json
from reportlab.pdfgen import canvas
from services.api import documents,jobs,models,store


def test_observation_changes_second_plan_and_reaches_answer(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    monkeypatch.setenv('RT_AGENT_PLANNING','true');monkeypatch.setenv('RT_DISABLE_DENSE','true')
    pdf=io.BytesIO();c=canvas.Canvas(pdf);c.drawString(40,700,'The experiment trained using eight GPUs with gradient clipping.');c.save()
    uploaded=documents.upload_document('agent','new.pdf',pdf.getvalue(),index_dense=False)
    jobs.work_once(pool='documents');vid=uploaded['document']['id']
    calls=[]
    def generate(system,prompt,rid,core=True, role=None, **_):
        core = core if role is None else role != 'light'  # role-based routing
        data=json.loads(prompt);calls.append((core,data))
        if not core:
            if data['round_index']==0:
                plan={'phase':'execute','summary':'先查训练设备','actions':[{'id':'hardware','tool':'retrieve_evidence','arguments':{'version_ids':[vid],'question':'eight GPUs','limit':3}}]}
            else:
                observed=data['observations'][0]['result']['blocks']
                assert 'gradient clipping' in observed[0]['text']
                plan={'phase':'execute','summary':'根据观察到的训练条件补查梯度裁剪','actions':[{'id':'condition','tool':'retrieve_evidence','arguments':{'version_ids':[vid],'question':'gradient clipping','limit':3}}]}
            return {'text':json.dumps(plan),'model':'FIXTURE_PLANNER','usage':{}}
        assert len(data['tool_observations'])==2
        assert data['tool_observations'][1]['id']=='condition'
        block=data['evidence'][0]
        return {'text':json.dumps({'claims':[{'id':'fact','text':'The experiment trained using eight GPUs with gradient clipping.','type':'source_fact','evidence':[{'block_id':block['id'],'quote':block['text']}]}]}),'model':'FIXTURE_ANSWER','usage':{}}
    monkeypatch.setattr(models,'generate',generate)
    run=jobs.queue('agent','agent',{'version_ids':[vid],'question':'Explain the training configuration'},'adaptive-feedback')
    jobs.work_once(pool='interactive')
    result=store.one('SELECT * FROM runs WHERE id=?',(run['id'],))
    assert result['status'] in ('partial','completed'),result['error']
    assert [core for core,_ in calls]==[False,False,True]
    snap=json.loads(result['checkpoint'])
    assert len(snap['tool_registry']['calls'])==2
    assert store.one('SELECT count(*) n FROM quota')['n']==0


def test_parent_waits_for_scoped_child_without_blocking_worker(tmp_path,monkeypatch):
    from services.api.dependencies import wake_dependencies
    monkeypatch.setattr(store,'DATA',tmp_path);store.migrate()
    child=jobs.queue('mine','parse',{},'dependency-child')['id']
    parent=jobs.queue('mine','agent',{},'dependency-parent')['id']
    store.execute("UPDATE runs SET status='waiting_children',checkpoint=? WHERE id=?",(json.dumps({'waiting_children':[child]}),parent))
    other=jobs.queue('other','agent',{},'foreign-parent')['id']
    store.execute("UPDATE runs SET status='waiting_children',checkpoint=? WHERE id=?",(json.dumps({'waiting_children':[child]}),other))
    assert parent not in wake_dependencies()
    # A foreign ID cannot reveal its status or force another workspace to wait.
    assert store.one('SELECT status FROM runs WHERE id=?',(other,))['status']=='queued'
    store.execute("UPDATE runs SET status='completed' WHERE id=?",(child,))
    assert wake_dependencies()==[parent]
    assert store.one('SELECT status FROM runs WHERE id=?',(parent,))['status']=='queued'
