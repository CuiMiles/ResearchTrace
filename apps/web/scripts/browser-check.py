"""Read-only browser checks; uses the existing local smoke session, no model requests."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium
root=Path(__file__).resolve().parents[3]
out=Path(__file__).resolve().parents[1]/'validation/ubuntu24-browser'
out.mkdir(parents=True,exist_ok=True)
session=json.loads((root/'data/smoke-session.json').read_text())
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18980'
cookie=session['cookie']
if isinstance(cookie,dict):cookie=cookie.get('rt_session') or cookie.get('value')
if cookie.startswith('rt_session='):cookie=cookie.split('=',1)[1].split(';',1)[0]
report={'base_url':base,'checks':[],'errors':[]}
with sync_playwright() as p:
 browser=launch_chromium(p)
 context=browser.new_context(viewport={'width':1440,'height':900},device_scale_factor=1)
 context.add_cookies([{'name':'rt_session','value':cookie,'url':base,'httpOnly':True,'sameSite':'Strict'}])
 page=context.new_page()
 page.set_default_timeout(15000)
 page.on('pageerror',lambda e:report['errors'].append(str(e)))
 page.goto(base,wait_until='networkidle',timeout=120000)
 page.get_by_role('heading',name='你的研究，有证可循。').wait_for(timeout=120000)
 page.screenshot(path=str(out/'library-1440.png'),full_page=True)
 report['checks'].append({'case':'library_1440','horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth')})
 for label,heading in [('版本与比较','版本与跨文比较'),('检索与追踪','检索与追踪'),('研究建议核查','研究建议核查'),('写作与绘图','写作与绘图')]:
  print('Checking navigation: '+label,flush=True)
  page.get_by_role('button',name=label,exact=True).click()
  page.get_by_role('heading',name=heading,exact=True).wait_for()
  report['checks'].append({'case':label,'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth')})
 page.get_by_role('button',name='结构图',exact=True).click()
 page.locator('.diagram-preview svg .node text').first.wait_for(timeout=120000)
 report['checks'].append({'case':'mermaid_default','labels':page.locator('.diagram-preview').inner_text()})
 page.screenshot(path=str(out/'diagram-1440.png'),full_page=True)
 source=page.get_by_label('Mermaid 源码')
 source.fill('flowchart LR\n  A[原文证据] --> B[核对后的结论]')
 page.get_by_role('button',name='更新预览').click()
 page.get_by_text('核对后的结论',exact=True).wait_for()
 report['checks'].append({'case':'mermaid_edit','visible':True})
 source.fill('flowchart LR\n  A --> B\n  click A "javascript:alert(1)"')
 page.get_by_role('button',name='更新预览').click()
 page.get_by_role('alert').wait_for()
 report['checks'].append({'case':'mermaid_script_rejection','message':page.get_by_role('alert').inner_text()})
 page.set_viewport_size({'width':1280,'height':800})
 page.get_by_role('button',name='文献库',exact=True).click()
 page.screenshot(path=str(out/'library-1280.png'),full_page=True)
 report['checks'].append({'case':'library_1280','horizontal_overflow':page.evaluate('document.documentElement.scrollWidth>innerWidth')})
 browser.close()
(out/'browser-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'checks':len(report['checks']),'browser_errors':len(report['errors']),'report':str(out/'browser-check.json')}))
