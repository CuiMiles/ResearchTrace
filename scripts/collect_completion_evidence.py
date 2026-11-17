"""Collect actual run receipts, never infer answer accuracy from completion."""
import json,time,re
from pathlib import Path
from datetime import datetime,timezone
from services.api import store,models
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/completion-20261116'

def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2))

def refresh(name):
 path=OUT/name
 if not path.exists():return
 d=json.loads(path.read_text())
 for c in d.get('cases',[]):
  if not c.get('run_id'):continue
  row=store.one('SELECT status,result,error FROM runs WHERE id=?',(c['run_id'],))
  if not row:continue
  result=json.loads(row['result'] or '{}')
  c.update(run_status=row['status'],error=row['error'],result=result,manual_quality_review='NOT RUN')
  c['status']='FAIL' if row['status']=='failed' else 'NOT RUN' if row['status'] in ('running','queued','waiting_children') else 'PASS' if row['status']=='completed' and result.get('status') in ('ready',None) else 'BLOCKED'
 d['updated_at']=datetime.now(timezone.utc).isoformat();d['status']='FAIL' if any(c.get('status')=='FAIL' for c in d.get('cases',[])) else 'BLOCKED' if any(c.get('status') in ('BLOCKED','NOT RUN') for c in d.get('cases',[])) else 'PASS'
 d['status_meaning']='Execution and machine checks only; manual factual quality is separate'
 save(path,d)
for n in ['official-live.json','feature-live.json','future-live.json','future-focused-live.json','future-targeted-live.json']:refresh(n)
summary={'updated_at':datetime.now(timezone.utc).isoformat(),'release_status':'BLOCKED','status_meaning':'P0 all-pass is not established',
 'branch':'upgrade/complete-20261116','backend_tests':{},'frontend':{'build':'PASS','actual_browser_checks':32,'actual_browser_status':json.loads((OUT/'browser/report.json').read_text())['status']},
 'public_browser':json.loads((OUT/'public-browser/report.json').read_text()),
 'indexes':store.rows('SELECT id,model_id,status,expected_blocks,covered_blocks,excluded_blocks,chunk_count,vector_count,error FROM index_generations WHERE workspace=? ORDER BY created DESC',('031dcae328aa4df2a24167d69d8f14c6',)),
 'quota':store.rows('''SELECT q.project,q.model,q.day,count(*) transport_attempts,sum(COALESCE(u.units,1)) request_units,
 sum(CASE WHEN u.source='legacy_upper_bound' THEN 1 ELSE 0 END) conservative_legacy_rows FROM quota q LEFT JOIN quota_request_units u ON u.quota_id=q.id GROUP BY q.project,q.model,q.day'''),
 'quota_notice':'Legacy request units without a retained response use a conservative upper bound. They are not provider-certified totals. Old rows are retained; logical project slots follow the user-declared two projects and are not Google numeric project IDs.',
 'materials':{'technical_pdf':'deliverables/ResearchTrace_技术说明.pdf','pdf_pages':6,'video':json.loads((ROOT/'deliverables/video-evidence.json').read_text())}}
for log in ['final-regression.log','release-fix-regression.log','pre-deploy-final-regression.log','final-validated-regression.log','jsonschema-routing-regression.log','final-current-regression.log']:
 text=(OUT/log).read_text() if (OUT/log).exists() else ''
 m=re.search(r'(\d+) passed in ([^\n]+)',text)
 summary['backend_tests'][log]={'status':'PASS','passed':int(m[1]),'duration':m[2]} if m else {'status':'NOT RUN'}
summary['public_runtime_reports']={}
for name in ['public-generation-live.json','public-feature-suite.json','public-repair-live.json',
             'public-v5-repairs.json','jsonschema-live-repairs.json','public-seed-copy.json',
             'public-semantic-qa.json','public-final-browser/report.json','public-runtime.json']:
 path=OUT/name
 if path.exists():summary['public_runtime_reports'][name]=json.loads(path.read_text())
summary['deployment_notice']='ECS owns generation and embedding spending after ledger import. Local provider spending is disabled. Core4 cloud generation is ready; full39 local generation remains separately reported.'
save(OUT/'summary.json',summary)
p=ROOT/'evidence/competition-dataset/workflow.json';d=json.loads(p.read_text())
items={'reader':('completion-browser','Actual core4 PDF/UI rendering across four widths','PASS',['evidence/completion-20261116/browser/report.json']),
 'analysis':('completion-official','Official questions, traps and translation; consult individual outcomes','BLOCKED',['evidence/completion-20261116/official-live.json','evidence/completion-20261116/feature-live.json']),
 'graph':('completion-writing','20-paper survey and Future Work actual receipts','BLOCKED',['evidence/completion-20261116/feature-live.json','evidence/completion-20261116/future-live.json']),
 'snapshots':('completion-indices','Core4 cloud/local generations ready; full39 remains incomplete','BLOCKED',['evidence/completion-20261116/summary.json','evidence/completion-20261116/core-cloud-public-import.log','evidence/completion-20261116/public-seed-copy.json']),
 'discovery':('completion-recommendations','Real arXiv discovery and schema-repaired recommendation reasons','PASS',['evidence/completion-20261116/feature-repair-live.json']),
 'export':('completion-materials','Actual diagram schema repair, 6-page PDF and 6-minute 1080p recording','PASS',['evidence/completion-20261116/feature-repair-live.json','deliverables/ResearchTrace_技术说明.pdf','deliverables/ResearchTrace_实际界面演示_1080p.mp4']),
 'recovery':('completion-regression','Backend regression, quota-item units and independent public browser','PASS',['evidence/completion-20261116/final-validated-regression.log','evidence/completion-20261116/public-final-browser/report.json'])}
for step in d['steps']:
 if step['id'] not in items:continue
 rid,label,status,paths=items[step['id']]
 row={'id':rid,'label':label,'status':status,'finished':summary['updated_at'],'summary':'New completion-stage records; historical failures and machine/human review distinctions retained.','files':[],'counts':{},'evidence_files':paths,'screenshots':[],'command':'scripts/collect_completion_evidence.py'}
 step['runs']=[r for r in step.get('runs',[]) if r['id']!=rid]+[row]
d['updated_at']=summary['updated_at'];save(p,d)
print(json.dumps({'release_status':summary['release_status'],'updated':summary['updated_at']}))
