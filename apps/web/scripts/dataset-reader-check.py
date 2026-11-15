"""Inspect source highlights for the actual corpus, never submit model jobs."""
import json
from pathlib import Path
import re
import sys
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium

root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root))
from services.api import store
out=root/'evidence/competition-dataset'
base='http://127.0.0.1:18980'
cookie=json.loads((root/'data/competition-dataset-session.json').read_text())['cookie']
enhanced=json.loads((out/'enhanced.json').read_text())
locations=json.loads((out/'location-recheck.json').read_text())
report={'status':'NOT RUN','checks':[],'errors':[],'blocked_mutations':[],'screenshots':[],'provider_calls':0}


def check(label, condition):
    report['checks'].append({'label':label,'status':'PASS' if condition else 'FAIL'})
    assert condition,label


def reader(browser, result, tag, target=None):
    vid,pid=result['version_id'],result['parse_id']
    ctx=browser.new_context(viewport={'width':1440,'height':1000})
    ctx.add_cookies([{'name':'rt_session','value':cookie,'url':base,'httpOnly':True,'sameSite':'Strict'}])
    ctx.add_init_script('localStorage.setItem("rt-version",'+json.dumps(vid)+')')
    page=ctx.new_page();page.set_default_timeout(30000)
    page.on('pageerror',lambda err:report['errors'].append(str(err)))
    def guard(route):
        if route.request.method not in ('GET','HEAD','OPTIONS'):
            report['blocked_mutations'].append(route.request.url.split('/api/v1')[-1]);route.abort()
        else:route.continue_()
    page.route('**/api/v1/**',guard)
    page.goto(base,wait_until='networkidle')
    page.get_by_role('button',name='阅读与问答',exact=True).click()
    selector=page.get_by_label('选择解析快照',exact=True)
    selector.locator('option[value="'+pid+'"]').wait_for(state='attached')
    selector.select_option(pid)
    if target is None:
        blocks=store.rows('SELECT b.* FROM blocks b LEFT JOIN block_parses m ON m.block_id=b.id WHERE b.version_id=? AND COALESCE(m.parse_id,b.version_id)=? AND b.page_index=0 AND length(text)>20 ORDER BY reading_order',(vid,pid))
        candidates=[w for b in blocks for w in re.findall(r'[A-Za-z]{5,}',b['text'])]
        assert candidates,'No actual searchable OCR words'
        target={'page_index':0,'query':max(candidates,key=len)}
    page.get_by_role('button',name='搜索原文',exact=True).click()
    page.get_by_label('原文搜索',exact=True).fill(target['query'])
    hit=page.locator('.text-hit').filter(has=page.get_by_text(f'第 {target["page_index"]+1} 页',exact=True)).first
    hit.wait_for();hit.click()
    page.get_by_test_id('evidence-highlight').wait_for()
    page.locator('.pdf-loading').wait_for(state='hidden')
    check(tag+' exact source physical page',page.get_by_role('spinbutton',name='页码',exact=True).input_value()==str(target['page_index']+1))
    check(tag+' lazily renders one PDF canvas',page.locator('canvas').count()==1)
    check(tag+' no horizontal overflow',not page.evaluate('document.documentElement.scrollWidth>innerWidth'))
    path=out/(tag+'-highlight.png');page.screenshot(path=str(path),full_page=True)
    report['screenshots'].append({'path':str(path.relative_to(root)),'label':tag+' · 实际 PDF 证据高亮'})
    report['checks'].append({'label':tag+' snapshot and original location','status':'PASS','version_id':vid,'parse_id':pid,'query':target['query'],'page_index':target['page_index']})
    if result['engine']=='native':
        page.get_by_role('spinbutton',name='页码',exact=True).fill('2')
        page.get_by_role('button',name='中英对照',exact=True).click()
        page.get_by_text('这一页已核验为空白页',exact=True).wait_for()
        check('verified blank is explained as ready rather than pending text',True)
        path=out/'textbook-blank-page.png';page.screenshot(path=str(path),full_page=True)
        report['screenshots'].append({'path':str(path.relative_to(root)),'label':'教材第2物理页 · 已核验空白页'})
    ctx.close()


try:
    with sync_playwright() as p:
        browser=launch_chromium(p)
        book=next(r for r in enhanced if r['engine']=='native' and r['status']=='PASS')
        tail=next(l for d in locations['documents'] if d['version_id']==book['version_id'] for l in d['locations'] if l['page_index']==540 and l['status']=='PASS')
        reader(browser,book,'textbook-page541',tail)
        for result in enhanced:
            if result['status']!='PASS' or result['engine']=='native':continue
            reader(browser,result,result['engine'])
            if result['engine']=='mineru':
                for kind in ('table','formula'):
                    example=result['examples'].get(kind)
                    if example:
                        words=re.findall(r'[A-Za-z]{4,}',example['text'])
                        if words:reader(browser,result,'mineru-'+kind,{'page_index':example['page_index'],'query':max(words,key=len)})
        ctx=browser.new_context(viewport={'width':1440,'height':1000})
        ctx.add_cookies([{'name':'rt_session','value':cookie,'url':base,'httpOnly':True,'sameSite':'Strict'}])
        page=ctx.new_page();page.on('pageerror',lambda err:report['errors'].append(str(err)))
        page.route('**/api/v1/**',lambda route:route.continue_() if route.request.method in ('GET','HEAD','OPTIONS') or route.request.url.endswith('/api/v1/graphs') else (report['blocked_mutations'].append(route.request.url),route.abort()))
        page.goto(base,wait_until='networkidle')
        page.get_by_role('button',name='引用图谱',exact=True).click()
        page.locator('.graph-node').nth(19).wait_for()
        check('20+ real PDF corpus nodes shown',page.locator('.graph-node').count()>=20)
        page.locator('.rank-row').first.click()
        page.locator('.graph-inspector').wait_for()
        check('real graph inspector opens',True)
        path=out/'corpus-graph.png';page.screenshot(path=str(path),full_page=True)
        report['screenshots'].append({'path':str(path.relative_to(root)),'label':'原始 PDF 资料集 · 引用图谱与排名'})
        check('no model, translation, upload or parser requests',not report['blocked_mutations'])
        check('no page exceptions',not report['errors'])
        report['status']='PASS';browser.close()
except Exception as exc:
    report.update(status='FAIL',error=str(exc)[:800])
finally:
    (out/'browser-reader.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
raise SystemExit(0 if report['status']=='PASS' else 1)
