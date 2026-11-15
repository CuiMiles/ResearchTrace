import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium
root=Path(__file__).resolve().parents[3];out=root/'apps/web/validation'
out.mkdir(exist_ok=True)
base=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18980').rstrip('/')
s=json.loads((root/'data/smoke-session.json').read_text());cookie=s['cookie'];cookie=cookie if isinstance(cookie,str) else cookie['rt_session']
if cookie.startswith('rt_session='):cookie=cookie.split('=',1)[1].split(';',1)[0]
with sync_playwright() as p:
 b=launch_chromium(p)
 c=b.new_context(viewport={'width':1440,'height':900});c.add_cookies([{'name':'rt_session','value':cookie,'url':base}]);page=c.new_page();errors=[];responses=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('console',lambda m:errors.append(m.type+': '+m.text) if m.type=='error' else None)
 page.on('requestfailed',lambda r:errors.append('requestfailed '+r.url+' '+str(r.failure)))
 page.on('response',lambda r:responses.append({'path':r.url.removeprefix(base),'status':r.status}) if r.status>=400 else None)
 page.goto(base,wait_until='domcontentloaded');page.wait_for_timeout(5000)
 report={'errors':errors,'responses':responses,'text':page.locator('body').inner_text(),'title':page.title()}
 print(json.dumps(report,ensure_ascii=False,indent=2));(out/'startup-debug.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));page.screenshot(path=str(out/'startup-debug.png'));b.close()
