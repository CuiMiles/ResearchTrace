"""Read-only/adversarial audit probes; all model endpoints are mocked or unused."""
import os,sys,json,sqlite3
from pathlib import Path
from unittest.mock import patch
import argparse,tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--output',type=Path,default=Path('audit_probes.json'))
args=p.parse_args()
SRC=args.source.resolve()
if not (SRC/'services/api/jobs.py').exists(): raise SystemExit('Source tree not found')
sys.path.insert(0,str(SRC))
os.environ['RT_DATA_DIR']=tempfile.mkdtemp(prefix='researchtrace-audit-')
os.environ['RT_DISABLE_DENSE']='true'
from services.api import jobs, models, retrieval
out={'scope':'isolated deterministic probes, no real model API calls; not an end-to-end accuracy benchmark'}
b={'id':'b1','version_id':'v1','parse_id':'p1','page_index':4,'bbox':[0,0,100,30],'text':'We trained our models on one machine with 8 NVIDIA P100 GPUs.'}
checks=[('contradicted_claim',{'answer':'The experiment used 80 GPUs.','claims':[{'text':'The experiment used 80 GPUs.','type':'source_fact','evidence':[{'block_id':'b1','quote':b['text']}]}]}),('unsupported_answer_prose',{'answer':'The experiment used 80 GPUs and cost 100 million dollars.','claims':[{'text':'The experiment used 8 NVIDIA P100 GPUs.','type':'source_fact','evidence':[{'block_id':'b1','quote':b['text']}]}]}),('whitespace_quote',{'answer':'The experiment used 80 GPUs.','claims':[{'text':'The experiment used 80 GPUs.','type':'source_fact','evidence':[{'block_id':'b1','quote':'   '}]}]})]
out['quote_validator']=[]
for name,payload in checks:
    try:
        value=jobs.validate_answer(payload,[b]);out['quote_validator'].append({'probe':name,'accepted':True,'result':value})
    except Exception as e:out['quote_validator'].append({'probe':name,'accepted':False,'error':str(e)})
attempts=[]
def fake_reserve(project,*args,**kwargs):
    attempts.append(project)
    if project=='full-project':raise models.ModelError('project daily quota exhausted')
    raise RuntimeError('second-project reservation was attempted')
with patch.object(models,'_choose',lambda model: iter([('full-project','fake-key-a'),('available-project','fake-key-b')])),patch.object(models,'reserve',fake_reserve):
    try:models.request('fake-model','generateContent',{},None,10)
    except Exception as e:out['project_routing']={'reservation_projects_attempted':attempts,'exception':type(e).__name__,'message':str(e)}
con=sqlite3.connect(':memory:')
con.execute("CREATE VIRTUAL TABLE docs USING fts5(text,tokenize='unicode61')")
con.execute('INSERT INTO docs VALUES(?)',('\u672c\u6587\u4f7f\u7528\u68c0\u7d22\u589e\u5f3a\u751f\u6210\u65b9\u6cd5\u8fdb\u884c\u95ee\u7b54',))
out['chinese_fts_probe']={'text':'\u672c\u6587\u4f7f\u7528\u68c0\u7d22\u589e\u5f3a\u751f\u6210\u65b9\u6cd5\u8fdb\u884c\u95ee\u7b54','query':'"\u68c0\u7d22" OR "\u7d22\u589e" OR "\u589e\u5f3a"','matches':con.execute('SELECT count(*) FROM docs WHERE docs MATCH ?',( '"\u68c0\u7d22" OR "\u7d22\u589e" OR "\u589e\u5f3a"',)).fetchone()[0]}
ro=sqlite3.connect('file:'+str(SRC/'data/researchtrace.sqlite')+'?mode=ro',uri=True);ro.row_factory=sqlite3.Row
ro.execute('PRAGMA query_only=ON')
def rows(sql,params=()):return [dict(r) for r in ro.execute(sql,params).fetchall()]
def one(sql,params=()):
    r=ro.execute(sql,params).fetchone();return dict(r) if r else None
w='031dcae328aa4df2a24167d69d8f14c6'
v=one("SELECT id,title,label FROM versions WHERE workspace=? AND identity LIKE '%1706.03762%' AND label LIKE '%v7%'",(w,))
if not v:
    candidates=rows("SELECT id,title,label,metadata FROM versions WHERE workspace=? AND title LIKE '%Attention Is All You Need%'",(w,))
    v=next((x for x in candidates if 'v7' in str(x)),candidates[0] if candidates else None)
out['corpus_diagnostic']={'version':v,'queries':[]}
if v:
    qs=['\u7b2c\u516d\u4f5c\u8005\u662f\u8c01\uff1f','\u8bad\u7ec3\u7528\u4e86\u591a\u5c11\u5f20\u663e\u5361\uff1f','Adam beta1 beta2','Transformer big English German BLEU','number NVIDIA P100 GPUs']
    with patch.object(retrieval,'rows',rows),patch.object(retrieval,'one',one):
        for q in qs:
            r=retrieval.retrieve(w,[v['id']],q,limit=10)
            out['corpus_diagnostic']['queries'].append({'question':q,'mode':r['mode'],'blocks':len(r['blocks']),'dense':len(r['dense']),'preview':[{'page_index':x['page_index'],'text':x['text'][:350]} for x in r['blocks'][:3]]})
args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
