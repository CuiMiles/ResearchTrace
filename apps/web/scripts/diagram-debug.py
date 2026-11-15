import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18970'
root=Path(__file__).resolve().parents[3]
s=json.loads((root/'data/smoke-session.json').read_text())
cookie=s['cookie'];cookie=cookie if isinstance(cookie,str) else cookie['rt_session']
if cookie.startswith('rt_session='):cookie=cookie.split('=',1)[1].split(';',1)[0]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/home/CuiMinghao/.cache/ms-playwright/chromium-1091/chrome-linux/chrome',headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
 c=b.new_context(viewport={'width':1440,'height':900});c.add_cookies([{'name':'rt_session','value':cookie,'url':base}]);page=c.new_page()
 errors=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('console',lambda m:errors.append(m.type+': '+m.text) if m.type=='error' else None)
 page.on('requestfailed',lambda r:errors.append('requestfailed '+r.url+' '+str(r.failure)))
 page.goto(base,wait_until='networkidle')
 page.get_by_role('button',name='写作与绘图',exact=True).click();page.get_by_role('button',name='结构图',exact=True).click()
 page.wait_for_timeout(15000)
 print(json.dumps({'errors':errors,'text':page.locator('.writing-page').inner_text(),'svg_count':page.locator('.diagram-preview svg').count(),'svg_text':page.locator('.diagram-preview svg').text_content()},ensure_ascii=False,indent=2))
 page.screenshot(path=str(root/'apps/web/validation/diagram-debug.png'))
 b.close()
