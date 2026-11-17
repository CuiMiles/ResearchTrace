"""Real authenticated UI checks. No model calls; codes/cookies stay in data/."""
import json
import re
import os
from pathlib import Path
import sys
import time
import shutil

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright,expect
from services.api import store

OUT=ROOT/'evidence/review-upgrade/browser-live';OUT.mkdir(parents=True,exist_ok=True)
REPORT=OUT/'report.json'
BASE='http://127.0.0.1:18980'
WORKSPACE='031dcae328aa4df2a24167d69d8f14c6'


def main():
    if REPORT.exists():shutil.copy2(REPORT,OUT/('report-attempt-'+str(time.time_ns())+'.json'))
    env=dotenv_values(ROOT/'.env');session=json.loads((ROOT/'data/competition-dataset-session.json').read_text())
    report={'started':time.time(),'data_kind':'REAL project UI, original user corpus','checks':[],
            'provider_calls_by_test':0,'page_errors':[],'failed_requests':[]}
    def save():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    def passed(name,observed=None):
        report['checks'].append({'case':name,'status':'PASS','observed':observed});save()
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.tools/browser-libs/root/usr/lib/x86_64-linux-gnu')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=str(ROOT/'apps/web/.browser-runtime/chrome-linux/chrome'),headless=True,args=['--no-sandbox'])
        admin=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1)
        admin.add_cookies([{'name':'rt_session','value':session['cookie'],'url':BASE}])
        # Preserve the existing corpus scope while authenticating its admin.
        identity=admin.request.post(BASE+'/api/v1/auth/login',data={'code':env['RT_ADMIN_CODE']})
        assert identity.ok and identity.json()['workspace']==WORKSPACE
        page=admin.new_page();page.on('pageerror',lambda error:report['page_errors'].append(str(error)[:300]))
        page.goto(BASE);expect(page.get_by_role('heading',name='你的研究，有证可循。')).to_be_visible()
        expect(page.locator('.document-row').first).to_be_visible()
        passed('admin_corpus_library',{'documents':page.locator('.document-row').count()})
        page.get_by_role('button',name='资源与配额',exact=True).click()
        expect(page.get_by_role('heading',name='评审访问码',exact=True)).to_be_visible()
        private=ROOT/'data/prepared-reviewer-live.json'
        if private.exists():account=json.loads(private.read_text())
        else:
            page.get_by_label('评审名称',exact=True).fill('核心四文档与拓展语料评审')
            page.get_by_label('研究资料空间',exact=True).select_option(WORKSPACE)
            with page.expect_response(lambda r:r.url.endswith('/api/v1/admin/reviewers') and r.request.method=='POST') as response:
                page.get_by_role('button',name='创建独立评审访问码',exact=True).click()
            assert response.value.ok
            account=response.value.json();private.write_text(json.dumps(account,ensure_ascii=False));private.chmod(0o600)
            page.get_by_role('button',name='已保存，隐藏访问码',exact=True).click()
            expect(page.get_by_label('新评审访问码',exact=True)).to_have_count(0)
        passed('admin_ui_binds_prepared_workspace',{'workspace':account['workspace'],'account_id':account['id'],'code_in_public_report':False})
        fresh=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1)
        page=fresh.new_page();page.on('pageerror',lambda error:report['page_errors'].append(str(error)[:300]))
        page.goto(BASE);page.get_by_label('访问码',exact=True).fill(account['access_code'])
        page.get_by_role('button',name='进入工作台',exact=True).click()
        expect(page.locator('.document-row').first).to_be_visible()
        who=fresh.request.get(BASE+'/api/v1/auth/session').json();assert who=={'workspace':WORKSPACE,'role':'reviewer'}
        assert page.locator('.document-row').count()>=39
        page.reload();expect(page.locator('.document-row').first).to_be_visible()
        passed('fresh_browser_stable_login_and_reload',{'workspace':who['workspace'],'documents':page.locator('.document-row').count()})
        account['cookie']=next(c['value'] for c in fresh.cookies() if c['name']=='rt_session');private.write_text(json.dumps(account,ensure_ascii=False));private.chmod(0o600)
        for width in (1280,1440,1920,390):
            page.set_viewport_size({'width':width,'height':1000})
            if width<700:page.get_by_role('button',name='展开主导航',exact=True).click()
            page.get_by_role('button',name='引用图谱',exact=True).click()
            expect(page.locator('.rt-graph-view-status')).to_be_visible(timeout=60000)
            expect(page.locator('.rt-graph-canvas canvas').first).to_be_visible()
            geometry=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
            assert geometry['scroll']<=geometry['width']+2,geometry
            page.screenshot(path=str(OUT/f'graph-{width}.png'),full_page=True)
            passed(f'real_graph_layout_{width}',{'visible_summary':page.locator('.rt-graph-view-status').inner_text(),'geometry':geometry})
        page.set_viewport_size({'width':1440,'height':1000})
        edge=page.locator('.rt-graph-inspector .rt-graph-citation-list button').first
        expect(edge).to_be_visible();edge.click()
        detail=page.get_by_role('region',name='原始引用详情')
        expect(detail).to_be_visible()
        quoted=detail.locator('blockquote').inner_text()
        row=detail.locator('dl').inner_text()
        page.get_by_role('button',name='定位原始条目',exact=False).click()
        expect(page.locator('.located-note')).to_be_visible()
        expect(page.locator('.pdf-sheet canvas').first).to_be_visible(timeout=30000)
        passed('real_graph_edge_opens_reader',{'quote':quoted,'edge_metadata':row,'reader_notice':page.locator('.located-note').inner_text()})
        for vid,label in [('e492d5c15f4444c08e9c335618e32533','v1'),('82451796b5294493b9e58f696fbb8adc','scan'),('4452fbc0c75443578fb2a2987629c19c','book')]:
            page.get_by_label('选择论文版本',exact=True).select_option(vid)
            expect(page.locator('.pdf-sheet canvas').first).to_be_visible(timeout=30000)
            expect(page.locator('details.advanced-parse')).not_to_have_attribute('open','')
            page.get_by_role('button',name='专注阅读',exact=True).click()
            assert page.locator('.app-shell').evaluate("e=>e.classList.contains('focus-reader')")
            page.get_by_role('button',name='折叠或展开目录',exact=True).click()
            assert page.locator('.reader-workspace').evaluate("e=>e.classList.contains('toc-collapsed')")
            page.screenshot(path=str(OUT/f'reader-{label}-focus.png'),full_page=True)
            page.get_by_role('button',name='折叠或展开目录',exact=True).click()
            page.get_by_role('button',name='退出专注',exact=True).click()
            passed('reader_focus_and_snapshot_'+label,{'version_id':vid,'index_progress':page.locator('.index-progress').inner_text()})
        page.get_by_label('页码',exact=True).fill('541');page.get_by_label('页码',exact=True).press('Tab')
        expect(page.locator('.reader-footer')).to_contain_text('第 541 页')
        expect(page.locator('.pdf-page[data-page-index="540"] canvas')).to_be_visible(timeout=30000)
        page.screenshot(path=str(OUT/'book-page541.png'),full_page=True)
        passed('book_physical_page541_renders')
        page.get_by_role('button',name='中英对照',exact=True).click()
        targets=page.get_by_role('group',name='翻译目标语言',exact=True)
        targets.get_by_role('button',name='English',exact=True).click()
        expect(targets.get_by_role('button',name='English',exact=True)).to_have_class(re.compile('active'))
        targets.get_by_role('button',name='中文',exact=True).click()
        passed('translation_direction_select_without_generation')
        assert not report['page_errors'],report['page_errors']
        report.update(status='PASS',finished=time.time());save();browser.close()
    print(json.dumps({'status':report['status'],'checks':len(report['checks']),'provider_calls_by_test':0}))


if __name__=='__main__':
    try:main()
    except Exception as error:
        report=json.loads(REPORT.read_text()) if REPORT.exists() else {'checks':[]}
        report.update(status='FAIL',error_type=type(error).__name__,error=str(error)[:1500],finished=time.time());REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        raise
