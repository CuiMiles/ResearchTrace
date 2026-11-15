"""Check the published admin processing map, without submitting parser/model jobs."""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from browser_runtime import launch_chromium

root = Path(__file__).resolve().parents[3]
out = root / 'evidence/competition-dataset'
parser = argparse.ArgumentParser()
parser.add_argument('--phase', choices=['before', 'after'], default='before')
args = parser.parse_args()
report = {'status': 'NOT RUN', 'phase': args.phase, 'checks': [], 'errors': [], 'mutations': [], 'provider_calls': 0}
cookie = json.loads((root / 'data/smoke-session.json').read_text())['cookie']
base = 'http://127.0.0.1:18980'


def check(label, condition):
    report['checks'].append({'label': label, 'status': 'PASS' if condition else 'FAIL'})
    assert condition, label


try:
    with sync_playwright() as p:
        browser = launch_chromium(p)
        context = browser.new_context(viewport={'width': 1440, 'height': 1100})
        context.add_cookies([{'name': 'rt_session', 'value': cookie, 'url': base, 'httpOnly': True, 'sameSite': 'Strict'}])
        page = context.new_page()
        page.on('pageerror', lambda err: report['errors'].append(str(err)))

        def guard(route):
            if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                report['mutations'].append(route.request.url.split('/api/v1')[-1])
                route.abort()
            else:
                route.continue_()
        page.route('**/api/v1/**', guard)
        page.goto(base, wait_until='networkidle')
        page.get_by_role('button', name='验收与截图', exact=True).click()
        page.locator('.aw-nodes button').nth(9).wait_for()
        page.wait_for_function("document.querySelector('.aw-overview').innerText.includes('40 个文件')")
        check('40-file manifest visible', '40 个文件' in page.locator('.aw-overview').inner_text())
        payload = context.request.get(base + '/api/v1/admin/workflow').json()
        check('ten real backend step definitions', len(payload['steps']) == 10)
        if args.phase == 'before':
            check('workflow published BEFORE dataset tests', payload['test_execution_started'] is False)
            check('remaining steps honestly not run', all(not x['runs'] for x in payload['steps'][1:]))
        for i, step in enumerate(payload['steps']):
            page.locator('.aw-nodes button').nth(i).click()
            check(f"click step {i+1}: {step['title']}", page.locator('#aw-step-title').inner_text() == step['title'])
            check(f'step {i+1} contains action guidance', page.locator('.aw-explainer').get_by_text('你要做什么', exact=True).is_visible())
            check(f'step {i+1} shows only its runs', page.locator('.aw-run').count() == len(step['runs']))
        page.locator('.aw-nodes button').nth(2).click()
        page.wait_for_timeout(5500)
        check('poll preserves selected step', page.locator('#aw-step-title').inner_text() == payload['steps'][2]['title'])
        check('desktop no horizontal overflow', not page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        page.screenshot(path=str(out / f'workflow-{args.phase}-1440.png'), full_page=True)
        if args.phase=='after':
            page.locator('.aw-run-search input').fill('Understanding')
            page.locator('.aw-run').last.screenshot(path=str(out/'workflow-after-results.png'))
            check('actual textbook retest result visible in selected step', '新快照' in page.locator('.aw-run').last.inner_text() or '5315' in page.locator('.aw-run').last.inner_text())
            page.locator('.aw-run-search input').fill('')
        page.set_viewport_size({'width': 390, 'height': 844})
        check('mobile no horizontal overflow', not page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        page.screenshot(path=str(out / f'workflow-{args.phase}-390.png'), full_page=True)
        check('node clicks never submit tests', not report['mutations'])
        check('no browser exceptions', not report['errors'])
        report.update(status='PASS', observed_at=datetime.now(timezone.utc).isoformat())
        browser.close()
except Exception as exc:
    report.update(status='FAIL', error=str(exc)[:600])
finally:
    (out / f'browser-{args.phase}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['status'] == 'PASS' else 1)
