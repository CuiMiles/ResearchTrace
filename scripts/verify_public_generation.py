"""Real ECS generation and a self-authored Chinese full-PDF translation."""
from pathlib import Path
import json,time,io
import httpx
from dotenv import dotenv_values
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/completion-20261116';base='https://researchtrace.sluna.xyz/api/v1'
s=json.loads((ROOT/'data/competition-dataset-session.json').read_text());private=ROOT/'data/completion-deployment'
report={'status':'NOT RUN','cases':[],'source':'actual ECS, native APIs, no fixture provider'}
record=OUT/'public-generation-live.json'
def save():record.write_text(json.dumps(report,ensure_ascii=False,indent=2))
if record.exists():raise SystemExit('Existing live execution; inspect receipts, do not repeat')
def wait(c,rid):
 while True:
  r=c.get('/runs/'+rid);r.raise_for_status();d=r.json()
  if d['status'] not in ('queued','running','waiting_children'):return d
  time.sleep(5)
with httpx.Client(base_url=base,proxy='http://127.0.0.1:18987',cookies={'rt_session':s['cookie']},timeout=90) as c:
 caps=c.get('/capabilities');caps.raise_for_status();report['capabilities']=caps.json();assert caps.json()['model_configured']
 p={'version_ids':['e492d5c15f4444c08e9c335618e32533'],'question':'请依据首页和已核验作者顺序，给出这篇论文第六位作者的姓名与机构；只写一条可核对事实。','idempotency_key':'public-author-verified-order-20261117'}
 r=c.post('/qa/runs',json=p);r.raise_for_status();case={'name':'public-author','run_id':r.json()['id'],'status':'NOT RUN'};report['cases'].append(case);save()
 result=wait(c,case['run_id']);case.update(run=result,status='PASS' if result['status']=='completed' and result.get('result',{}).get('status')=='ready' else 'FAIL' if result['status']=='failed' else 'BLOCKED');save();print({'case':case['name'],'status':case['status']},flush=True)
# A separate fresh workspace tests an actual new upload, not the prepared corpus.
values=dotenv_values(ROOT/'.env')
with httpx.Client(base_url=base,proxy='http://127.0.0.1:18987',timeout=90) as c:
 login=c.post('/auth/login',json={'code':values['RT_ACCESS_CODE']});login.raise_for_status()
 (private/'public-translation-session.json').write_text(json.dumps({'workspace':login.json()['workspace'],'cookie':c.cookies.get('rt_session')}));(private/'public-translation-session.json').chmod(0o600)
 pdfmetrics.registerFont(TTFont('ChineseFixture',str(ROOT/'.tools/mineru-env/lib/python3.12/site-packages/docvortex/resources/fonts/DroidSansFallbackFull.ttf')))
 data=io.BytesIO();pdf=canvas.Canvas(data);pdf.setFont('ChineseFixture',13)
 for y,text in [(760,'证据追踪科研助手：中文全文翻译测试'),(720,'本文提出一个面向科研阅读的证据追踪助手。'),(690,'系统保留论文版本，将事实绑定到原文位置，并标记证据不足。'),(660,'实验结果尚待完成，本文不宣称已经证明性能提升。'),(630,'示例公式：$a+b=c$'),(600,'This is a self-authored input, not an official evaluation paper.')]:pdf.drawString(40,y,text)
 pdf.save();raw=data.getvalue();up=c.post('/documents?index_dense=false',files={'files':('Chinese-self-authored.pdf',raw,'application/pdf')});up.raise_for_status();d=up.json();vid=d['documents'][0]['id'];prid=d['items'][0]['run_id'];parse=wait(c,prid);assert parse['status']=='completed'
 r=c.post('/translations',json={'version_id':vid,'source_language':'zh','target_language':'en','idempotency_key':'public-full-chinese-to-english-20261117'});r.raise_for_status();case={'name':'new-chinese-full-pdf','run_id':r.json()['id'],'version_id':vid,'parse_run_id':prid,'input_source':'self-authored Chinese PDF, not core4 corpus','status':'NOT RUN'};report['cases'].append(case);save()
 result=wait(c,case['run_id']);case.update(run=result,status='PASS' if result['status']=='completed' else 'FAIL' if result['status']=='failed' else 'BLOCKED')
 if case['status']=='PASS':
  exported=c.get('/translations/'+vid+'/export',params={'target_language':'en','source_language':'zh','format':'html'});exported.raise_for_status();(OUT/'public-chinese-translation.html').write_text(exported.text)
 save();print({'case':case['name'],'status':case['status']},flush=True)
report['status']='PASS' if all(c['status']=='PASS' for c in report['cases']) else 'BLOCKED';save()
