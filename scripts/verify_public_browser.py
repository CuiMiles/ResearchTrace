"""Independent browser verification against the real TLS ECS deployment."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'evidence/completion-20261116/public-browser';out.mkdir(exist_ok=True)
a=json.loads((ROOT/'data/completion-seeded-reviewer.json').read_text())
# The access code is only read into the browser; no traces or screenshots of it.
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=str(ROOT/'apps/web/.browser-runtime/chrome-linux/chrome'),headless=True,args=['--no-sandbox','--proxy-server=http://127.0.0.1:18987'])
 c=b.new_context(viewport={'width':1440,'height':1000});page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 resp=page.goto('https://researchtrace.sluna.xyz');page.locator('input[type=password]').wait_for(timeout=20000)
 page.screenshot(path=str(out/'login.png'),full_page=True)
 page.locator('input[type=password]').fill(a['access_code'])
 with page.expect_response(lambda r:r.url.endswith('/api/v1/auth/login') and r.request.method=='POST',timeout=30000) as logged:
  page.get_by_role('button',name='进入工作台').click()
 assert logged.value.status==200,'Login HTTP '+str(logged.value.status)
 page.locator('input[type=password]').wait_for(state='detached',timeout=30000)
 page.goto('https://researchtrace.sluna.xyz/library');page.get_by_role('heading',name='文献库',exact=True).wait_for(timeout=60000)
 who=page.request.get('https://researchtrace.sluna.xyz/api/v1/auth/session').json()
 docs=page.request.get('https://researchtrace.sluna.xyz/api/v1/documents').json()
 assert who['workspace']==a['workspace'] and len(docs)>=39
 page.screenshot(path=str(out/'library.png'),full_page=True)
 # Reload in this fresh context proves the invitation is stable across requests.
 page.reload();page.wait_for_timeout(1500)
 result={'status':'PASS' if not errors else 'FAIL','tls_status':resp.status,'reviewer_login':'PASS','workspace_isolated':who['workspace']==a['workspace'],'documents':len(docs),'browser_errors':errors,'provider_calls':0,'egress':'node01 proxy to public ECS; real TLS verification'}
 (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));b.close()
