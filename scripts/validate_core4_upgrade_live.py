"""Real core-four HTTP tasks. Durable case IDs prevent accidental sent retries."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.api import store
import httpx

OUT=ROOT/'evidence/review-upgrade/core4-qa-after-index.json'
CASES=[
 ('v1-author','e492d5c15f4444c08e9c335618e32533','这篇论文按署名顺序的第六作者是谁？作者栏列的机构是什么？请区分作者栏机构与论文关于工作完成地点的脚注，只回答这三个问题。'),
 ('v7-optimizer','dceae303ec2f41cbbc4d88f047db9424','论文训练时 Adam 的 beta1、beta2 和 epsilon 分别是什么？只报告原文支持的超参数。'),
 ('scan-table','82451796b5294493b9e58f696fbb8adc','扫描版论文表格中 Transformer (big) 在 English-to-German 上的 BLEU 是多少？请给出可核对的表格证据，不把精排相关性分数当实验结果。'),
 ('book-tail','4452fbc0c75443578fb2a2987629c19c','请查看本书末尾索引，reparameterization trick 指向哪些印刷页码？只回答索引明确列出的页码，引用索引原文。'),
 ('false-premise','e492d5c15f4444c08e9c335618e32533','为什么作者用了80张GPU？请先核对这个数字前提，再说明这篇论文是否报告了训练总费用；没有证据就明确写缺证据。'),
 ('v7-hardware','dceae303ec2f41cbbc4d88f047db9424','请依据原文说明训练用了多少张什么型号的GPU，Base模型的训练时长是多少。')]


def save(report):OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2))


def main(refresh_only=False):
    session=json.loads((ROOT/'data/competition-dataset-session.json').read_text())
    report=json.loads(OUT.read_text()) if OUT.exists() else {'started':time.time(),'scope':'core4 only','live_http':True,
         'authorization':'User authorizes Hydrogen and Flash at most40/day each, all outcomes counted; no smoke reset',
         'independent_human_quality_review':'NOT RUN','cases':[]}
    with httpx.Client(base_url='http://127.0.0.1:18980',cookies={'rt_session':session['cookie']},trust_env=False,timeout=60) as client:
        for name,vid,question in CASES:
            item=next((c for c in report['cases'] if c['name']==name),None)
            if item is None:
                if refresh_only:continue
                item={'name':name,'version_id':vid,'question':question,'created':time.time(),'status':'NOT RUN'}
                response=client.post('/api/v1/qa/runs',json={'question':question,'version_ids':[vid],
                                       'idempotency_key':'core4-after-local-index-v2-'+name})
                response.raise_for_status();item['run_id']=response.json()['id'];report['cases'].append(item);save(report)
            deadline=time.monotonic()+(1 if refresh_only else 1800)
            while True:
                try:
                    response=client.get('/api/v1/runs/'+item['run_id']);response.raise_for_status();run=response.json()
                except httpx.HTTPError as error:
                    item.setdefault('polling_interruptions',[]).append({'time':time.time(),'error_type':type(error).__name__,
                           'action':'Retry read of the same run ID only; no model request replay'})
                    save(report)
                    if refresh_only or time.monotonic()>deadline:raise
                    time.sleep(2);continue
                item['run']=run;item['updated']=time.time()
                item['requests']=store.rows('SELECT id,model,status,project,input_tokens,output_tokens FROM quota WHERE run_id=? ORDER BY started',(item['run_id'],))
                item['status']='NOT RUN' if run['status'] in ('queued','running','waiting_children') else 'PASS' if run['status']=='completed' else 'FAIL'
                item['status_meaning']='Execution and support checks only; no claimed human QA accuracy'
                result=run.get('result') or {}
                saved=store.one('SELECT checkpoint FROM runs WHERE id=? AND workspace=?',(item['run_id'],session['workspace']))
                checkpoint=json.loads(saved['checkpoint'] or '{}')
                ret=result.get('retrieval') or checkpoint.get('retrieval') or {}
                item['retrieval_mode']=ret.get('mode')
                item['dense_index']=ret.get('dense_index')
                item['rerank']=ret.get('rerank')
                item['retrieval_snapshot']=ret
                save(report)
                if run['status'] not in ('queued','running','waiting_children') or time.monotonic()>deadline:break
                time.sleep(2)
            print(json.dumps({'case':name,'run':item['run_id'],'status':run['status'],'calls':len(item['requests']),
                              'retrieval':item['retrieval_mode'],'error':run.get('error')},ensure_ascii=False),flush=True)
            if run['status'] in ('queued','running','waiting_children'):break
    report['updated']=time.time();save(report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--refresh-only',action='store_true')
    main(parser.parse_args().refresh_only)
