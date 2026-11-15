"""Inspect actual OCR blocks and PDF source highlight using existing live parser evidence.
No mutating requests and no provider requests are allowed by this browser audit.
"""
import json
import os
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'apps/web/scripts'))
from browser_runtime import launch_chromium
result=json.loads(Path(sys.argv[1]).read_text());base=os.getenv('RT_BROWSER_URL','http://127.0.0.1:18980')
assert result['status']=='PASS'
vid=result['version_id'];cookie=json.loads((ROOT/'data/smoke-session.json').read_text())['cookie'];engine=result['engine']
out=ROOT/'evidence/ubuntu24/browser';out.mkdir(exist_ok=True,parents=True)
report={'engine':engine,'version_id':vid,'parse_id':result['parse_id'],'mutations':[],'errors':[],'status':'NOT RUN'}
try:
 with sync_playwright() as p:
  browser=launch_chromium(p);ctx=browser.new_context(viewport={'width':1440,'height':900})
  ctx.add_cookies([{'name':'rt_session','value':cookie,'url':base,'httpOnly':True,'sameSite':'Strict'}])
  page=ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
  def guard(route):
   if route.request.method not in ('GET','HEAD','OPTIONS'):
    report['mutations'].append(route.request.url.split('/api/v1')[-1]);route.abort()
   else:route.continue_()
  page.route('**/api/v1/**',guard)
  page.add_init_script('localStorage.setItem("rt-version",'+json.dumps(vid)+')')
  page.goto(base,wait_until='networkidle');page.get_by_role('button',name='阅读与问答',exact=True).click()
  page.get_by_label('选择解析快照',exact=True).select_option(result['parse_id'])
  page.get_by_role('button',name='中英对照',exact=True).click()
  page.locator('.parallel-column').first.get_by_text('7189',exact=False).first.wait_for()
  if engine=='paddleocr':page.locator('.parallel-column').first.get_by_text('科研证据链',exact=False).first.wait_for()
  assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
  page.screenshot(path=str(out/f'{engine}-text-layer.png'),full_page=True)
  page.get_by_role('button',name='搜索原文',exact=True).click();page.get_by_label('原文搜索',exact=True).fill('7189')
  page.locator('.text-hit').first.wait_for();page.locator('.text-hit').first.click()
  page.get_by_role('button',name='原版 PDF',exact=True).click()
  page.get_by_test_id('evidence-highlight').wait_for();page.locator('.pdf-loading').wait_for(state='hidden')
  assert page.get_by_role('spinbutton',name='页码').input_value()=='1'
  assert page.locator('canvas').count()==1
  page.screenshot(path=str(out/f'{engine}-source-highlight.png'),full_page=True)
  report['status']='PASS';report['checks']=['real active parser text','CJK text for Paddle','search to exact source page','normalized bbox highlight','one lazily rendered canvas','no browser exceptions','no mutating requests']
  assert not report['errors'] and not report['mutations']
  browser.close()
except Exception as exc:
 report['status']='FAIL';report['error']=str(exc)
finally:(out/f'{engine}-reader.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False));raise SystemExit(0 if report['status']=='PASS' else 1)
