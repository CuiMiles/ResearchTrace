"""Actual running UI and corpus checks. No fixture responses or model calls."""
import json,os,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];base=os.getenv('RT_VERIFY_URL','http://127.0.0.1:18980');out=ROOT/'evidence/completion-20261116/browser';out.mkdir(exist_ok=True,parents=True)
s=json.loads((ROOT/'data/competition-dataset-session.json').read_text());core=json.loads((ROOT/'evals/review_upgrade_scopes.json').read_text())['core']
report={'status':'NOT RUN','source':'actual runtime, no mocked API','model_calls':0,'checks':[],'errors':[]}
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=str(ROOT/'apps/web/.browser-runtime/chrome-linux/chrome'),headless=True,args=['--no-sandbox'])
 context=browser.new_context(viewport={'width':1440,'height':1000});context.add_cookies([{'name':'rt_session','value':s['cookie'],'url':base}])
 page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
 for width in [1280,1440,1920,390]:
  page.set_viewport_size({'width':width,'height':1000})
  for path in ['/library','/chat','/compare','/discover','/insights','/studio','/settings']:
   with page.expect_response(lambda r:r.url.endswith('/api/v1/documents'),timeout=45000):
    response=page.goto(base+path)
   page.wait_for_timeout(900)
   overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth+2')
   text=page.locator('body').inner_text()
   ok=response.status==200 and '应用出现问题' not in text and not overflow
   report['checks'].append({'route':path,'width':width,'status':'PASS' if ok else 'FAIL','horizontal_overflow':overflow})
   page.screenshot(path=str(out/(str(width)+'-'+path.strip('/')+'.png')),full_page=True)
 for paper in core:
  page.set_viewport_size({'width':1440,'height':1000});page.goto(base+'/read/'+paper['version_id']);page.wait_for_selector('canvas',timeout=45000);page.wait_for_timeout(600)
  canvas=page.locator('canvas').count();textlayer=page.locator('.textLayer').count()
  report['checks'].append({'file':paper['name'],'pdf_canvas':canvas,'pdf_text_layer':textlayer,'status':'PASS' if canvas else 'FAIL'})
  page.screenshot(path=str(out/(paper['name']+'.png')),full_page=True)
 browser.close()
report['status']='PASS' if not report['errors'] and all(c['status']=='PASS' for c in report['checks']) else 'FAIL'
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'status':report['status'],'checks':len(report['checks']),'errors':report['errors']},ensure_ascii=False))
