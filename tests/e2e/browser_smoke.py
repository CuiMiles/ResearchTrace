"""Real browser acceptance on running app; does not make new model requests."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.getenv('RT_BROWSER_OUT',str(ROOT/'evidence/browser')))
OUT.mkdir(parents=True,exist_ok=True)
base=os.getenv('RT_BROWSER_URL','http://127.0.0.1:18970')
s=json.loads((ROOT/'data/smoke-session.json').read_text())
errors=[];console=[];report=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('RT_CHROMIUM','/home/CuiMinghao/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_cookies([{'name':'rt_session','value':s['cookie'],'url':base,'httpOnly':True,'sameSite':'Strict'}])
    page=context.new_page()
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('console',lambda e:console.append(e.text) if e.type=='error' else None)
    page.goto(base,wait_until='domcontentloaded',timeout=180000)
    page.get_by_text('文献库',exact=True).first.wait_for(timeout=180000)
    page.screenshot(path=OUT/'library-1440.png',full_page=True)
    report.append({'step':'library1440','status':'PASS','title':page.title(),'body_text':page.locator('body').inner_text()[:1800]})
    # Traverse actual UI via user-visible navigation.
    for label in ['阅读工作台','文献阅读','阅读器','证据阅读']:
        locator=page.get_by_text(label,exact=True)
        if locator.count():
            locator.first.click();break
    page.wait_for_timeout(2000)
    page.screenshot(path=OUT/'workspace-1440.png',full_page=True)
    page.set_viewport_size({'width':1280,'height':800})
    page.screenshot(path=OUT/'workspace-1280.png',full_page=True)
    report.append({'step':'workspace1280','overflow':page.evaluate('document.documentElement.scrollWidth>window.innerWidth'),'body_text':page.locator('body').inner_text()[:1800]})
    (OUT/'initial.json').write_text(json.dumps({'report':report,'page_errors':errors,'console_errors':console},ensure_ascii=False,indent=2))
    browser.close()
print(json.dumps({'report':report,'page_errors':errors,'console_errors':console},ensure_ascii=False))
