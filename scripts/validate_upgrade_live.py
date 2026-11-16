"""Explicit real HTTP checks. --providers spends the operator-authorized budget.

Access codes/cookies stay in data/. Results never contain authentication values.
Failures are saved and never automatically replayed as new model requests.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from dotenv import dotenv_values
from services.api import store

OUT=ROOT/'evidence/review-upgrade'
BASE='http://127.0.0.1:18980'


def save(path,value,private=False):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    if private:path.chmod(0o600)


def request(client,method,path,**kwargs):
    response=client.request(method,'/api/v1'+path,**kwargs)
    response.raise_for_status()
    return response.json()


def wait(client,rid,timeout=900):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        run=request(client,'GET','/runs/'+rid)
        if run['status'] not in ('queued','running','waiting_batch','waiting_children'):return run
        time.sleep(1)
    raise TimeoutError('Real run did not finish within explicit check bound')


def batch():
    private=ROOT/'data/review-upgrade-batch-session.json'
    if private.exists():raise RuntimeError('A real batch test already exists; inspect its evidence instead of creating another')
    env=dotenv_values(ROOT/'.env')
    with httpx.Client(base_url=BASE,trust_env=False,timeout=120) as admin:
        request(admin,'POST','/auth/login',json={'code':env['RT_ADMIN_CODE']})
        account=request(admin,'POST','/admin/reviewers',json={'label':'20篇原资料真实批量测试','days':7})
    save(private,account,True)
    result={'started':time.time(),'live_http':True,'provider_calls':0,'cases':[],'workspace':account['workspace']}
    with httpx.Client(base_url=BASE,trust_env=False,timeout=120) as client:
        identity=request(client,'POST','/auth/login',json={'code':account['access_code']})
        assert identity['workspace']==account['workspace']
        state={**account,'cookie':client.cookies.get('rt_session')};save(private,state,True)
        with httpx.Client(base_url=BASE,trust_env=False,timeout=30) as fresh:
            again=request(fresh,'POST','/auth/login',json={'code':account['access_code'],'workspace':'must-not-change-scope'})
            assert again['workspace']==identity['workspace']
            assert request(fresh,'GET','/auth/session')['workspace']==identity['workspace']
        result['cases'].append({'name':'new-browser-stable-reviewer-workspace','status':'PASS'})
        manifest=json.loads((ROOT/'evidence/competition-dataset/manifest.json').read_text())
        inputs=[f for f in manifest['files'] if f['role']=='test_input' and '_img' not in f['name'] and 'Understanding' not in f['name'] and f['name']!='1706.03762v1.pdf'][:20]
        assert len(inputs)==20
        with ExitStack() as stack:
            files=[('files',(f['name'],stack.enter_context((ROOT/manifest['extracted_root']/f['relative_path']).open('rb')),'application/pdf')) for f in inputs]
            files.append(('files',('intentionally-broken.pdf',b'%PDF-1.7 invalid input','application/pdf')))
            uploaded=request(client,'POST','/documents?index_dense=false',files=files)
        bid=uploaded['batch_id'];state['batch_id']=bid;save(private,state,True)
        result['upload']={'batch_id':bid,'inputs':inputs,'invalid_file_count':1,'response':uploaded}
        save(OUT/'batch-live.json',result)
        snap=request(client,'GET','/batches/'+bid)
        selected=next((i for i in reversed(snap['items']) if i['status']=='waiting_batch'),None)
        if selected:
            cancelled=request(client,'POST',f'/batches/{bid}/cancel',json={'item_ids':[selected['id']]})
            assert next(i for i in cancelled['items'] if i['id']==selected['id'])['status']=='cancelled'
            request(client,'POST',f'/batches/{bid}/resume',json={'item_ids':[selected['id']]})
            result['cases'].append({'name':'one-item-cancel-resume','status':'PASS','item_id':selected['id']})
        before=store.one('SELECT count(*) n FROM quota')['n']
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline:
            snap=request(client,'GET','/batches/'+bid)
            pending=[i for i in snap['items'] if i['status'] in ('queued','running','waiting_batch','uploading')]
            result['latest']=snap;save(OUT/'batch-live.json',result)
            if not pending:break
            time.sleep(2)
        versions=request(client,'GET','/documents')
        good=[v for v in versions if v['status']=='ready']
        result.update(finished=time.time(),ready_documents=len(good),concurrent_ledger_delta=store.one('SELECT count(*) n FROM quota')['n']-before,
                      status='PASS' if len(good)==20 else 'FAIL',documents=versions)
        # Concurrent authorized model tests may write quota; these parse runs must not.
        ids=[i['run_id'] for i in snap['items'] if i.get('run_id')]
        result['batch_provider_calls']=sum(store.one('SELECT count(*) n FROM quota WHERE run_id=?',(rid,))['n'] for rid in ids)
        result['provider_calls']=result['batch_provider_calls']
        save(OUT/'batch-live.json',result)
        print(json.dumps({'case':'batch','status':result['status'],'ready_documents':len(good),'batch_provider_calls':result['batch_provider_calls']}))


def providers():
    session=json.loads((ROOT/'data/competition-dataset-session.json').read_text())
    path=OUT/'provider-evaluation-live.json'
    if path.exists():raise RuntimeError('Provider evidence exists; inspect it, do not blindly repeat requests')
    result={'started':time.time(),'live_http':True,'cases':[],'budget_authorization':'User: Hydrogen and gemini-3.8-flash each at most40/day, all outcomes counted; old smoke4 retained'}
    save(path,result)
    with httpx.Client(base_url=BASE,cookies={'rt_session':session['cookie']},trust_env=False,timeout=60) as client:
        v='e492d5c15f4444c08e9c335618e32533'
        for name,question in [('training-hardware','论文实际用了多少张什么型号的显卡训练？请说明base和big模型各训练多久。'),
                              ('false-premise-no-answer','为什么作者用了80张GPU？先核对这个前提，再说明论文是否报告训练总费用。不要把没有依据的数字当成事实。')]:
            qids=[r['id'] for r in store.rows('SELECT id FROM quota')]
            queued=request(client,'POST','/qa/runs',json={'question':question,'version_ids':[v],'idempotency_key':'upgrade-'+name+'-'+uuid.uuid4().hex})
            run=wait(client,queued['id'])
            usage=store.rows('SELECT id,project,model,day,status,input_tokens,output_tokens FROM quota WHERE run_id=?',(run['id'],))
            result['cases'].append({'name':name,'question':question,'run':run,'requests':usage,'new_requests':len(usage),'prior_ledger_rows':len(qids)})
            save(path,result)
            print(json.dumps({'case':name,'run_status':run['status'],'requests':len(usage)},ensure_ascii=False),flush=True)
        result['finished']=time.time();save(path,result)


def translations(route='gemini-3.8-flash'):
    """Two actual Flash requests, using original English paper and Chinese task PDF."""
    import re
    label={'gemini-3.8-flash':'flash38','gemini-3.6-flash':'flash36','gemini-3.5-flash-lite':'flashlite'}[route]
    path=OUT/('translation-'+label+'-live.json')
    if path.exists():raise RuntimeError('Translation evidence already exists; do not repeat paid requests blindly')
    session=json.loads((ROOT/'data/competition-dataset-session.json').read_text())
    manifest=json.loads((ROOT/'evidence/competition-dataset/manifest.json').read_text())
    source=next(f for f in manifest['files'] if f['role']=='task_description')
    result={'started':time.time(),'live_http':True,'requested_model':route,'cases':[],
            'chinese_source_role':'用户资料包中的中文赛题要求，用于翻译完整性测试；不是中文科研论文质量样本'}
    save(path,result)
    with httpx.Client(base_url=BASE,cookies={'rt_session':session['cookie']},trust_env=False,timeout=60) as client:
        capabilities=request(client,'GET','/capabilities')
        if capabilities['batch_model']!=route:raise RuntimeError('Running batch route differs from explicitly requested test model; no model call made by this preflight')
        with (ROOT/manifest['extracted_root']/source['relative_path']).open('rb') as f:
            upload=request(client,'POST','/documents?index_dense=false',files={'files':(source['name'],f,'application/pdf')})
        vid=upload['documents'][0]['id']
        if upload['runs']:wait(client,upload['runs'][0]['id'])
        chinese=next(b for b in store.rows('SELECT * FROM current_blocks WHERE workspace=? AND version_id=? ORDER BY page_index,reading_order',(session['workspace'],vid)) if len(re.findall(r'[\u4e00-\u9fff]',b['text']))>30 and len(b['text'])<900)
        english=next(b for b in store.rows('SELECT * FROM current_blocks WHERE workspace=? AND version_id=? ORDER BY page_index,reading_order',(session['workspace'],'95b9e428f36144c7925682db419ded0d')) if '15%' in b['text'] and len(b['text'])<2400)
        for name,block,origin,target in [('zh-to-en',chinese,'zh','en'),('en-to-zh',english,'en','zh-Hans')]:
            queued=request(client,'POST','/translations',json={'version_id':block['version_id'],'block_ids':[block['id']],
                  'source_language':origin,'target_language':target,'idempotency_key':label+'-'+name+'-'+uuid.uuid4().hex})
            run=wait(client,queued['id'])
            translated=request(client,'GET','/translations/'+block['version_id'],params={'source_language':origin,'target_language':target})
            usage=store.rows('SELECT model,status,input_tokens,output_tokens FROM quota WHERE run_id=?',(run['id'],))
            result['cases'].append({'name':name,'source':block,'run':run,'translations':translated,'requests':usage,
                                    'status':'PASS' if run['status']=='completed' and usage and all(x['model']==route for x in usage) else 'FAIL',
                                    'human_quality_review':'NOT RUN'})
            save(path,result);print(json.dumps({'case':name,'status':result['cases'][-1]['status'],'requests':len(usage)}),flush=True)
        result['finished']=time.time();save(path,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',action='store_true');parser.add_argument('--providers',action='store_true');parser.add_argument('--translations',action='store_true')
    parser.add_argument('--translation-model',choices=['gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash-lite'],default='gemini-3.8-flash')
    args=parser.parse_args()
    if args.batch:batch()
    if args.providers:providers()
    if args.translations:translations(args.translation_model)
