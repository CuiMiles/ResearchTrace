"""Read-only live Reader audit. No parser submission, upload, or model requests.
Usage: python apps/web/scripts/parse-reader-check.py [base_url]
Requires a private data/smoke-session.json and locally installed Playwright/browser.
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium

root = Path(__file__).resolve().parents[3]
out = root / 'apps/web/validation'
out.mkdir(exist_ok=True)
base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:18980').rstrip('/')
report = {'base_url': base, 'checks': [], 'errors': [], 'model_requests': 0}


def check(case, condition):
    report['checks'].append({'case': case, 'status': 'PASS' if condition else 'FAIL'})
    assert condition, case


try:
    session = json.loads((root / 'data/smoke-session.json').read_text())
    cookie = session['cookie']
    if isinstance(cookie, dict):
        cookie = cookie.get('rt_session') or cookie.get('value')
    if cookie.startswith('rt_session='):
        cookie = cookie.split('=', 1)[1].split(';', 1)[0]
    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.add_cookies([{'name': 'rt_session', 'value': cookie, 'url': base,
                             'httpOnly': True, 'sameSite': 'Strict'}])
        documents = context.request.get(base + '/api/v1/documents')
        if not documents.ok:
            raise RuntimeError(f'Authenticated documents endpoint returned {documents.status}')
        versions = documents.json()
        if not versions:
            raise RuntimeError('No document available for read-only Reader audit')
        version = next((v for v in versions if v.get('parsed_pages', 0) > 0), versions[0])
        response = context.request.get(base + f"/api/v1/documents/{version['id']}/parses")
        if not response.ok:
            raise RuntimeError(f'Parses endpoint returned {response.status}')
        snapshots = response.json()
        if not snapshots:
            raise RuntimeError('No snapshot available for read-only Reader audit')
        page = context.new_page()
        page.on('pageerror', lambda e: report['errors'].append(str(e)))
        mutations = []

        def guard(route):
            request = route.request
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                mutations.append(request.url.split('/api/v1')[-1])
                route.abort()
            else:
                route.continue_()

        page.route('**/api/v1/**', guard)
        page.add_init_script('localStorage.setItem("rt-version", ' + json.dumps(version['id']) + ')')
        page.goto(base, wait_until='networkidle')
        page.get_by_role('button', name='阅读与问答', exact=True).click()
        selector = page.get_by_label('选择解析快照', exact=True)
        selector.wait_for()
        selector.locator('option').nth(1).wait_for(state='attached')
        check('snapshot options match authenticated API', selector.locator('option').count() == len(snapshots) + 1)
        check('engine and device controls exist', page.get_by_label('解析引擎', exact=True).count() == 1
              and page.get_by_label('解析设备', exact=True).count() == 1)
        page.get_by_label('解析引擎', exact=True).select_option('mineru')
        page.get_by_label('解析设备', exact=True).select_option('gpu')
        check('GPU requires server resource checks', page.get_by_text('GPU 需服务端配置与资源检查；提交不代表已分配显存。', exact=True).is_visible())
        if snapshots:
            chosen = next((s for s in snapshots if not s.get('active')), snapshots[0])
            if not chosen.get('active'):
                with page.expect_response(lambda r: f"/pages/0?parse_id={chosen['id']}" in r.url):
                    selector.select_option(chosen['id'])
            else:
                selector.select_option(chosen['id'])
            page.get_by_role('button', name='刷新快照', exact=True).click()
            page.wait_for_timeout(700)
            check('explicit snapshot survives refresh', selector.input_value() == chosen['id'])
            if not chosen.get('active'):
                check('historical model submission disabled', page.get_by_role('button', name='发送问题', exact=True).is_disabled())
                check('historical outline editing disabled', page.get_by_role('button', name='编辑目录', exact=True).is_disabled())
            page.get_by_role('button', name='中英对照', exact=True).click()
            with page.expect_response(lambda r: f"/search?q=" in r.url and f"parse_id={chosen['id']}" in r.url):
                page.get_by_role('button', name='搜索原文', exact=True).click()
                page.get_by_label('原文搜索', exact=True).fill('research')
            check('search scopes selected snapshot', True)
        check('desktop has no horizontal overflow', not page.evaluate('() => document.documentElement.scrollWidth > innerWidth'))
        page.screenshot(path=str(out / 'parse-reader-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_role('button', name='展开目录', exact=True).click()
        check('mobile snapshot selector visible', selector.is_visible())
        check('mobile has no horizontal overflow', not page.evaluate('() => document.documentElement.scrollWidth > innerWidth'))
        page.screenshot(path=str(out / 'parse-reader-mobile.png'), full_page=True)
        check('no mutating API requests', not mutations)
        check('no browser exceptions', not report['errors'])
        browser.close()
except Exception as exc:
    report['errors'].append(str(exc))
    report['status'] = 'FAIL' if any(c['status'] == 'FAIL' for c in report['checks']) else 'BLOCKED'
else:
    report['status'] = 'PASS'
finally:
    (out / 'parse-reader-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['status'] == 'PASS' else 1)
