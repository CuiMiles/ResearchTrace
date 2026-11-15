"""Attach real completed observations to the admin workflow; no provider calls."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from validate_competition_dataset import OUT, BASE, cookie, record, save_json, now
sys.path.insert(0,str(ROOT))
from services.api import store
import httpx


def prepare():
    enhanced=json.loads((OUT/'enhanced.json').read_text())
    for result in enhanced:
        vid,pid=result['version_id'],result['parse_id']
        formula=store.one("SELECT b.* FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? AND b.type IN ('equation','formula') ORDER BY page_index,reading_order LIMIT 1",(vid,pid))
        if formula:
            example={k:formula[k] for k in ('page_index','id','text')}
            example['text']=example['text'][:3000];example['bbox']=json.loads(formula['bbox'])
            result['examples']['formula']=example
        start=datetime.fromisoformat(result['started']).timestamp()
        finish=datetime.fromisoformat(result['finished']).timestamp()
        resources=[]
        for p in (ROOT/'data/parsing').glob('*/result.json'):
            if start<=p.stat().st_mtime<=finish:
                observation=json.loads(p.read_text())
                if observation.get('engine')==result['engine'] and observation.get('device')==result['device']:
                    resources.append({k:observation.get(k) for k in ('engine','device','elapsed_seconds','peak_rss_kib','cuda_peak_allocated_mib','cuda_peak_reserved_mib')})
        result['resource_observations']=resources
        result['runner_peak_rss_kib']=max((r.get('peak_rss_kib') or 0 for r in resources),default=None)
        path=OUT/next(r['id']+'.json' for s in json.loads((OUT/'workflow.json').read_text())['steps'] for r in s['runs'] if result['run_id'] in r.get('run_ids',[]) and s['id']=='parse')
        save_json(path,result)
    save_json(OUT/'enhanced.json',enhanced)
    print('Enriched actual formula examples and bounded CPU resource observations',flush=True)


def finalize():
    safety=json.loads((OUT/'safety-and-quota.json').read_text());assert safety['status']=='PASS' and safety['quota_unchanged']
    browser=json.loads((OUT/'browser-reader.json').read_text());assert browser['status']=='PASS'
    enhanced=json.loads((OUT/'enhanced.json').read_text())
    locations=json.loads((OUT/'location-recheck.json').read_text());assert locations['status']=='PASS'
    ingestion=json.loads((OUT/'ingestion.json').read_text());assert len(ingestion['documents'])==39
    for doc in locations['documents']:
        vid=doc['version_id'];bad=any(l['status']=='FAIL' for l in doc['locations'])
        record('snapshots','location-recheck-'+vid,doc['file']['name']+' · 正文定位复查', 'FAIL' if bad else 'PASS',
               '排除重复页眉后，从实际正文选择稀有词，经 FTS → 指定解析快照 → 页 API 核对原块和 bbox。不是语义问答质量评测。',
               files=[doc['file']],results=doc['locations'],evidence=[OUT/'location-recheck.json'],
               command='.venv/bin/python scripts/validate_competition_locations.py')
    reader_files=[d['file'] for d in ingestion['documents'] if d['file']['name'] in ('UnderstandingDeepLearning_02_09_26_C.pdf','1706.03762v1_img.pdf')]
    record('reader','actual-corpus-reader','原教材末页 / 扫描原件 / 结构化公式表格 · 浏览器检查','PASS',
           '真实浏览器打开正确解析快照，搜索实际词句并点击到原版 PDF，核对页码、黄色 bbox 和单页懒加载；空白页显示已核验状态。',
           files=reader_files,results=browser['checks'],evidence=[OUT/'browser-reader.json'],screenshots=browser['screenshots'],
           command='.venv/bin/python apps/web/scripts/dataset-reader-check.py')
    graph=json.loads((OUT/'graph.json').read_text())
    record('graph','actual-corpus-graph-browser','全文资料引用图 · 浏览器交互','PASS','实际打开本批全文生成的图谱与节点检查器，未调用综述模型。',
           counts={'nodes':len(graph['nodes']),'located_reference_edges':len(graph['edges'])},evidence=[OUT/'browser-reader.json',OUT/'graph.json'],
           screenshots=[s for s in browser['screenshots'] if 'graph' in s['path']])
    chart=json.loads((OUT/'csv-chart.json').read_text())
    files={}
    with httpx.Client(base_url=BASE,cookies={'rt_session':cookie()},trust_env=False,timeout=60) as client:
        for name,url in chart['files'].items():
            response=client.get(url);response.raise_for_status()
            files[name]={'bytes':len(response.content),'sha256':hashlib.sha256(response.content).hexdigest()}
            if name in ('png','svg'):
                (OUT/('corpus-page-counts.'+name)).write_bytes(response.content)
            elif name=='spec':
                (OUT/'corpus-chart-spec.json').write_bytes(response.content)
            if name=='png':assert response.content.startswith(b'\x89PNG')
            if name=='spec':assert json.loads(response.content)['input_sha256']
        rid=enhanced[0]['run_id']
        events=client.get('/api/v1/runs/'+rid+'/events');events.raise_for_status()
        ids=[int(x) for x in re.findall(r'^id: (\d+)$',events.text,re.M)]
        assert ids and ids==sorted(set(ids)) and 'event: done' in events.text
        save_json(OUT/'exports-and-events.json',{'status':'PASS','downloaded_files':files,'terminal_run':rid,'event_count':len(ids),'first_event':ids[0],'last_event':ids[-1]})
    record('export','actual-chart-downloads','实际下载 PNG / SVG / 脚本 / PlotSpec / CSV','PASS','通过带鉴权的真实产物接口逐个下载，登记字节与哈希。',results=files,
           evidence=[OUT/'exports-and-events.json',OUT/'corpus-chart-spec.json'],
           screenshots=[{'path':'evidence/competition-dataset/corpus-page-counts.png','label':'本批39份原始PDF实测页数 · 真实CSV绘图产物'}])
    record('recovery','actual-persistent-events','完成任务持久化事件与终止事件','PASS','读取真实教材任务 SSE，事件序号有序且不重复，收到 done；不是模型 token streaming 验收。',
           results={'run_id':rid,'events':len(ids)},evidence=[OUT/'exports-and-events.json'])

    state=json.loads((OUT/'workflow.json').read_text())
    by_vid={r['version_id']:r for r in enhanced if r['engine']=='native' and r['status']=='PASS'}
    for step in state['steps']:
        for run in step['runs']:
            if step['id']=='parse' and run['id'].startswith('native-') and run['id'][7:] in by_vid:
                run['resolved_by']='textbook-native-v2'
            if step['id']=='snapshots' and run['id'].startswith('fts-') and run['status']=='FAIL':
                run['resolved_by']='location-recheck-'+run['id'][4:]
            if run['id']=='native-'+ingestion['documents'][0]['version_id']:
                run['duration_seconds']=ingestion['documents'][0]['duration_seconds']
            if not run.get('command'):
                run['command']='.venv/bin/python scripts/validate_competition_followup.py' if step['id'] in ('analysis','graph','discovery','export') or 'cpu-' in run['id'] or 'gpu' in run['id'] or run['id']=='textbook-native-v2' else '.venv/bin/python scripts/validate_competition_dataset.py --resume'
            for result in enhanced:
                if step['id']=='parse' and result['run_id'] in run.get('run_ids',[]):
                    run['results'].update(examples=result['examples'],runner_peak_rss_kib=result['runner_peak_rss_kib'])
    before=json.loads((OUT/'browser-before.json').read_text())
    assert datetime.fromisoformat(before['observed_at']) < datetime.fromisoformat(state['testing_started_at'])
    archive_hash=hashlib.sha256((ROOT/state['dataset']['source_name']).read_bytes()).hexdigest()
    assert archive_hash==state['dataset']['archive_sha256']
    state.update(ledger=safety['ledger'],completed_at=now(),updated_at=now())
    save_json(OUT/'workflow.json',state)
    ready=[store.one('SELECT id,status,page_count,parsed_pages,active_parses.parse_id FROM versions JOIN active_parses ON active_parses.version_id=versions.id WHERE versions.id=?',(d['version_id'],)) for d in ingestion['documents']]
    assert all(v['status']=='ready' and v['parsed_pages']==v['page_count'] for v in ready)
    from services.api.workflow_report import build_workflow_report
    workflow=build_workflow_report()
    summary={'overall_status':'BLOCKED','local_document_pipeline_status':'PASS','source_archive_unchanged':True,
             'workflow_published_before_tests':True,'original_input_documents':39,'original_input_pages':1986,
             'original_file_manifest_count':40,'final_ready_documents':len(ready),'location_checks':locations['counts'],
             'enhanced_runs':[{'engine':r['engine'],'device':r['device'],'status':r['status'],'duration_seconds':r['duration_seconds'],
                               'blocks':r['counts']['blocks'],'types':r['counts']['types'],'scope':r.get('source') or r['input_file'],
                               'runner_peak_rss_kib':r['runner_peak_rss_kib']} for r in enhanced],
             'graph_nodes':len(graph['nodes']),'graph_reference_entries':len(graph['edges']),
             'workflow_step_statuses':{s['id']:s['status'] for s in workflow['steps']},'provider_calls_this_batch':0,
             'quota_unchanged':True,'ledger':safety['ledger'],'finished':now(),
             'remaining':['GPU WSL/NVML process memory accounting','exhausted Hydrogen smoke budget; no new model-quality assessment',
                          'public scholarly source DNS route','public HTTPS and final contest deliverables'],
             'quality_scope':'Execution, snapshot preservation, indexing and browser location checks; not an independently labelled OCR/QA quality benchmark.'}
    save_json(OUT/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    prepare() if '--prepare' in sys.argv else finalize()
