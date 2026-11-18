"""Click genuine saved model citations and exercise real user tools; no model spend."""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.getenv('RT_BROWSER_OUT',str(ROOT/'evidence/browser')))
OUT.mkdir(exist_ok=True,parents=True)
base=os.getenv('RT_BROWSER_URL','http://127.0.0.1:18970')
s=json.loads((ROOT/'data/smoke-session.json').read_text())
report=[];errors=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.getenv('RT_CHROMIUM','/home/CuiMinghao/.cache/ms-playwright/chromium-1091/chrome-linux/chrome'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    context=browser.new_context(viewport={'width':1440,'height':900},accept_downloads=True)
    context.add_cookies([{'name':'rt_session','value':s['cookie'],'url':base,'httpOnly':True,'sameSite':'Strict'}])
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(base,wait_until='networkidle',timeout=120000)
    page.get_by_role('button',name='任务',exact=True).click()
    page.locator('.run-row').filter(has_text='What beta1 and beta2').first.click()
    page.locator('.evidence-chip').first.wait_for(timeout=60000)
    page.locator('.evidence-chip').first.click()
    page.get_by_test_id('evidence-highlight').wait_for(timeout=30000)
    page.locator('.pdf-loading').wait_for(state='hidden',timeout=60000)
    assert page.get_by_role('spinbutton',name='页码').input_value()=='7'
    # Continuous reader: the evidence page is rendered; only nearby pages hold canvases.
    assert page.locator('.pdf-page[data-page-index="6"] canvas').count()==1 and page.locator('canvas').count()<=4
    assert not page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
    page.screenshot(path=OUT/'citation-1440.png',full_page=True)
    before=page.get_by_test_id('evidence-highlight').bounding_box()
    page.get_by_role('button',name='旋转页面',exact=True).click()
    page.locator('.pdf-loading').wait_for(state='hidden',timeout=60000)
    after=page.get_by_test_id('evidence-highlight').bounding_box()
    assert before!=after
    page.get_by_role('button',name='放大',exact=True).click()
    page.locator('.pdf-loading').wait_for(state='hidden',timeout=60000)
    assert page.get_by_test_id('evidence-highlight').is_visible()
    page.screenshot(path=OUT/'citation-rotated-zoomed.png',full_page=True)
    page.set_viewport_size({'width':1280,'height':800})
    page.screenshot(path=OUT/'reader-1280.png',full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
    report.append({'case':'C03,D06','status':'PASS','version':'Transformer v7','physical_page':7,'canvas_count':'<=4 (continuous, lazily rendered)','rotation':90,'zoom':110,'bbox_before':before,'bbox_after':after})
    page.get_by_role('link',name='写作工坊',exact=True).click()
    page.get_by_label('上传 CSV').set_input_files(ROOT/'evals/files/metrics_a.csv')
    button=page.get_by_role('button',name=re.compile('生成.*图|绘制'))
    if button.count():
        button.first.click()
        page.locator('.chart-preview img,.chart-output img').first.wait_for(timeout=120000)
        page.screenshot(path=OUT/'csv-chart-1280.png',full_page=True)
        report.append({'case':'E10','status':'PASS','input':'metrics_a.csv','text':page.locator('main').inner_text()[-1800:]})
    page.get_by_role('button',name='结构图',exact=True).click()
    page.locator('.diagram-preview svg').wait_for(timeout=90000)
    page.get_by_label('Mermaid 源码').fill('flowchart LR\n A[原文证据] --> B[核查条件]\n B --> C[结论]')
    page.get_by_role('button',name='更新预览',exact=True).click()
    page.get_by_text('核查条件',exact=True).last.wait_for(timeout=30000)
    with page.expect_download() as d:
        page.get_by_role('button',name='导出 SVG',exact=True).click()
    d.value.save_as(OUT/'edited-diagram.svg')
    page.get_by_label('Mermaid 源码').fill('flowchart LR\n A --> B\n click A "javascript:alert(1)"')
    page.get_by_role('button',name='更新预览',exact=True).click()
    page.get_by_text('结构图不允许',exact=False).wait_for(timeout=10000)
    report.append({'case':'E09','status':'PASS','edited_svg_export':True,'malicious_click_rejected':True})
    (OUT/'acceptance.json').write_text(json.dumps({'report':report,'page_errors':errors},ensure_ascii=False,indent=2))
    assert not errors,errors
    browser.close()
print(json.dumps({'report':report,'page_errors':errors},ensure_ascii=False))
