"""Continue remaining explicitly authorised live checks; never repeat old cases."""
import json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from services.api import store,jobs
s=json.loads((ROOT/'evals/review_upgrade_scopes.json').read_text());names={v['name']:v['version_id'] for v in s['core']+s['expansion']};w=s['workspace'];v7=names['1706.03762v7.pdf']
file=ROOT/'evidence/completion-20261116/official-live.json'
report=json.loads(file.read_text())
extra=[('ln-reference',[v7],'请给出此论文引用的Layer Normalization文献的完整作者及年份，引用References原文。'),('bert',[v7,names['N19-1423.pdf']],'BERT架构承袭原Transformer的哪一部分，又丢弃哪一部分？分别给出两篇全文证据。')]
gpt=ROOT/'evidence/completion-20261116/gpt2-import.json'
if gpt.exists():
 try:
  two=json.loads(gpt.read_text())['version_id'];three=names['2005.14165v4.pdf'];one=names['language_understanding_paper.pdf']
  extra.extend([('gpt-parameters',[one,two,three],'对比三篇论文中最大GPT-1、GPT-2、GPT-3的参数量，保留单位，逐篇引用。'),('gpt-layernorm',[one,two],'GPT-2相比GPT-1在Layer Normalization位置做了什么关键调整？请给出两篇原文，未报告的写缺证据。'),('gpt-context',[one,two,three],'GPT-1到GPT-3最大上下文长度分别是多少token？逐篇引用原文并区分最大模型与训练设置。')])
 except (KeyError,ValueError):print('GPT2 import not ready; do not substitute another paper',flush=True)
extra.extend([('false-premise',[v7],'为什么Transformer训练用了80张GPU？若问题前提不符，请以原文纠正。'),('unreported-cost',[v7],'该论文训练Base模型的美元费用是多少？只根据所选论文，未提供的数据明确说缺证据。')])
for name,vids,q in extra:
 if any(c['name']==name for c in report['cases']):continue
 # Preserve at least ten of the authorised forty core/Flash calls for judging.
 from services.api import models
 used=store.rows("SELECT model,count(*) n FROM quota WHERE day=? AND model IN ('gemini-4-hydrogen','gemini-3.6-flash') GROUP BY model",(models.quota_day(),))
 if any(c['n']>=30 for c in used):print('Thirty-call test ceiling reached; ten per model reserved for judging',flush=True);break
 while store.one("SELECT count(*) n FROM runs WHERE workspace=? AND status IN ('queued','running')",(w,))['n']>=4:time.sleep(10)
 if any(not store.one("SELECT 1 FROM versions WHERE id=? AND status='ready'",(v,)) for v in vids):
  print('Waiting for parse for',name,flush=True)
  while any(not store.one("SELECT 1 FROM versions WHERE id=? AND status='ready'",(v,)) for v in vids):time.sleep(10)
 task=jobs.queue(w,'qa',{'question':q,'version_ids':vids},'completion-official-'+name)
 report['cases'].append({'name':name,'question':q,'versions':vids,'run_id':task['id'],'status':'NOT RUN'})
 file.write_text(json.dumps(report,ensure_ascii=False,indent=2));print({'case':name,'run':task['id']},flush=True)
 while store.one('SELECT status FROM runs WHERE id=?',(task['id'],))['status'] in ('queued','running','waiting_children'):time.sleep(10)
 for c in report['cases']:
  r=store.one('SELECT status,error,result FROM runs WHERE id=?',(c['run_id'],));result=json.loads(r['result'] or '{}')
  c.update(run_status=r['status'],error=r['error'],answer=result.get('answer'),result_status=result.get('status'),claims=result.get('claims',[]),model=result.get('model'),manual_quality_review='NOT RUN',status='PASS' if r['status']=='completed' and result.get('status')=='ready' else 'FAIL' if r['status']=='failed' else 'NOT RUN')
 file.write_text(json.dumps(report,ensure_ascii=False,indent=2))
