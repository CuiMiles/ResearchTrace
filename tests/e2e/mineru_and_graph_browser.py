"""Browser verification for MinerU formula/table highlights, 20-node graph interaction (E06), and stored note export (E08).
No model/provider calls are made.
"""
import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/web/scripts'))
from browser_runtime import launch_chromium

BASE = os.getenv('RT_BROWSER_URL', 'http://127.0.0.1:18980').rstrip('/')
OUT = ROOT / 'evidence/ubuntu24/browser'
OUT.mkdir(parents=True, exist_ok=True)
COOKIE = json.loads((ROOT / 'data/smoke-session.json').read_text())['cookie']

report = {'base_url': BASE, 'provider_requests': 0, 'cases': [], 'errors': [], 'status': 'NOT RUN'}


def check_mineru_doc(browser, label, result_path, block_text, search_term):
    data = json.loads((ROOT / result_path).read_text())
    assert data['status'] == 'PASS', f'{result_path} did not pass'
    vid = data['version_id']
    pid = data['parse_id']
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    ctx.add_cookies([{'name': 'rt_session', 'value': COOKIE, 'url': BASE, 'httpOnly': True, 'sameSite': 'Strict'}])
    ctx.add_init_script('localStorage.setItem("rt-version",' + json.dumps(vid) + ')')
    page = ctx.new_page()
    page.set_default_timeout(15000)
    page.on('pageerror', lambda e: report['errors'].append(f'{label}: {e}'))
    mutations = []
    page.route('**/api/v1/**', lambda r: (mutations.append(r.request.url), r.abort()) if r.request.method not in ('GET', 'HEAD', 'OPTIONS') else r.continue_())
    try:
        page.goto(BASE, wait_until='networkidle')
        page.get_by_role('button', name='阅读与问答', exact=True).click()
        page.get_by_label('选择解析快照', exact=True).select_option(pid)
        page.get_by_role('button', name='中英对照', exact=True).click()
        page.locator('.parallel-column').first.get_by_text(block_text, exact=False).first.wait_for()
        page.screenshot(path=str(OUT / f'mineru-{label}-text.png'), full_page=True)
        page.get_by_role('button', name='搜索原文', exact=True).click()
        page.get_by_label('原文搜索', exact=True).fill(search_term)
        page.locator('.text-hit').first.wait_for()
        page.locator('.text-hit').first.click()
        page.get_by_role('button', name='原版 PDF', exact=True).click()
        page.get_by_test_id('evidence-highlight').wait_for()
        page.locator('.pdf-loading').wait_for(state='hidden')
        assert page.locator('canvas').count() == 1
        assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        page.screenshot(path=str(OUT / f'mineru-{label}-highlight.png'), full_page=True)
        assert not mutations, f'Unexpected mutations: {mutations}'
        report['cases'].append({'id': f'B02-mineru-{label}', 'version_id': vid, 'parse_id': pid, 'status': 'PASS'})
    finally:
        ctx.close()


with sync_playwright() as p:
    browser = launch_chromium(p)
    try:
        check_mineru_doc(browser, 'formula', 'evidence/ubuntu24/mineru-cpu-formula.json', 'softmax', 'softmax')
        check_mineru_doc(browser, 'table', 'evidence/ubuntu24/mineru-cpu-table.json', 'Transformer (big)', 'BLEU')

        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        ctx.add_cookies([{'name': 'rt_session', 'value': COOKIE, 'url': BASE, 'httpOnly': True, 'sameSite': 'Strict'}])
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda e: report['errors'].append(f'graph_writing: {e}'))
        try:
            page.goto(BASE, wait_until='networkidle')
            page.get_by_role('button', name='引用图谱', exact=True).click()
            page.locator('.graph-node').first.wait_for()
            nodes_count = page.locator('.graph-node').count()
            edges_count = page.locator('.graph-canvas svg line').count()
            assert nodes_count >= 20, f'Expected >=20 nodes, got {nodes_count}'
            assert edges_count >= 20, f'Expected >=20 edges, got {edges_count}'
            page.get_by_text('局部 PageRank · 断连不代表低质量', exact=True).wait_for()
            with page.expect_response(lambda r: r.url.endswith('/api/v1/graphs') and r.request.method == 'POST') as resp_info:
                page.get_by_role('button', name='重建与重算', exact=True).click()
            assert resp_info.value.status == 200
            recomputed = resp_info.value.json()
            assert len(recomputed['nodes']) >= 20 and len(recomputed['edges']) >= 20
            page.locator('.rank-row').first.click()
            page.locator('.graph-inspector').get_by_text('PageRank', exact=False).wait_for()
            page.get_by_role('button', name='返回排名', exact=True).click()
            page.get_by_text('语料范围', exact=True).click()
            assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            page.screenshot(path=str(OUT / 'graph-20-nodes-1440.png'), full_page=True)
            page.set_viewport_size({'width': 1280, 'height': 800})
            assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            report['cases'].append({'id': 'E06-graph-20-nodes', 'nodes': nodes_count, 'edges': edges_count, 'recomputed_nodes': len(recomputed['nodes']), 'status': 'PASS'})

            # E08 deterministic artifact export check (stored verified research_note, 0 model calls)
            page.get_by_role('link', name='写作工坊', exact=True).click()
            page.get_by_role('button', name='产物', exact=True).click()
            note_btn = page.locator('.artifact-row').filter(has_text='research_note').first
            note_btn.wait_for()
            note_btn.click()
            exports = {}
            for fmt in ('md', 'html', 'bib'):
                href = page.locator('.artifact-preview .export-row a').filter(has_text=fmt).first.get_attribute('href')
                assert href
                resp = ctx.request.get(BASE + href)
                assert resp.status == 200, f'Export {fmt} returned {resp.status}'
                body = resp.text()
                assert len(body.strip()) > 20
                if fmt == 'bib':
                    assert '@article{' in body
                exports[fmt] = len(body)
            report['cases'].append({'id': 'E08-stored-note-export', 'exports': exports, 'status': 'PASS'})
        finally:
            ctx.close()
    finally:
        browser.close()

report['status'] = 'PASS' if not report['errors'] and all(c['status'] == 'PASS' for c in report['cases']) else 'FAIL'
(ROOT / 'evidence/ubuntu24/mineru-graph-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(0 if report['status'] == 'PASS' else 1)
