"""Browser fixtures for real components; all HTTP responses explicitly synthetic.

Run with the parent venv, private Node on PATH, RT_BROWSER_EXECUTABLE and
LD_LIBRARY_PATH set. Only this script's Vite child is stopped, never services.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path('/tmp/rt-complete-documents-browser')
OUT.mkdir(exist_ok=True)

ENTRY = '''import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {VersionChoice} from '../src/components/VersionChoice';
import {ReferenceTools} from '../src/components/ReferenceTools';
const versions=[{id:'old',work_id:'work',title:'Fixture title',filename:'renamed.pdf',label:'v1',status:'ready',metadata:{}}];
function Harness(){const [pending,setPending]=useState(['old']);const [notice,setNotice]=useState('');return <>
<h1>明确标记的组件浏览器夹具</h1><output data-testid="notice">{notice}</output>
<VersionChoice pendingIds={pending} versions={versions} onDismiss={id=>setPending(x=>x.filter(v=>v!==id))} onResolved={async()=>setNotice('版本选择已保存')}/>
<ReferenceTools versionId="old" onEvidence={e=>setNotice(e.block_id+' '+e.parse_id)}/></>}
createRoot(document.getElementById('root')).render(<Harness/>);'''
HTML = '<!doctype html><html><meta charset="utf-8"><style>body{font:16px sans-serif;margin:0}button,input,select{font:inherit}button{padding:8px}summary{cursor:pointer}blockquote{overflow-wrap:anywhere}</style><div id="root"></div><script type="module" src="./entry.tsx"></script></html>'


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='workflow-fixture-', dir=ROOT / 'apps/web') as folder:
        folder = Path(folder)
        (folder / 'index.html').write_text(HTML)
        (folder / 'entry.tsx').write_text(ENTRY)
        log = (OUT / 'vite.log').open('w')
        proc = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'],
                                cwd=ROOT / 'apps/web', stdout=log, stderr=subprocess.STDOUT)
        results = []
        try:
            url = f'http://127.0.0.1:{port}/{folder.name}/index.html'
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError('Fixture Vite did not start')
                try:
                    with urllib.request.urlopen(url, timeout=.5): break
                except OSError: time.sleep(.1)
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=os.environ['RT_BROWSER_EXECUTABLE'], headless=True, args=['--no-sandbox'])
                for width, height in [(1280, 800), (1440, 900), (1920, 1080), (390, 844)]:
                    page = browser.new_page(viewport={'width': width, 'height': height})
                    errors, calls = [], []
                    page.on('pageerror', lambda exc: errors.append(str(exc)))
                    report = {'id': 'analysis', 'version_id': 'old', 'parse_id': 'old-snapshot', 'status': 'ready', 'active_snapshot': True,
                        'reference_count': 1, 'scope': 'Fixture 正文引用统计', 'ranking_rule': 'Fixture 次数降序', 'references': [
                        {'id': 'r1', 'text': '[1] Fixture bibliography.', 'marker': '1', 'citation_count': 3, 'sections': {'1 Methods': 3},
                         'classification': {'status': 'not_run', 'label': 'uncertain'}, 'contexts': [
                         {'block_id': 'body1', 'version_id': 'old', 'parse_id': 'old-snapshot', 'page_index': 0, 'bbox': [0,0,1,1],
                          'quote': 'Fixture body evidence [1].', 'section': '1 Methods', 'count': 3}]}]}
                    batch = {'id': 'batch', 'status': 'queued', 'items': [{'ref_id': 'r1', 'status': 'pending', 'parse_status': None, 'result': {}}],
                             'counts': {'pending': 1}, 'notice': 'Fixture：尚未真实联网。'}
                    def route(request):
                        path = request.request.url.split('/api/v1', 1)[1]
                        method = request.request.method
                        body = request.request.post_data_json if method == 'POST' else None
                        calls.append({'path': path, 'method': method, 'body': body})
                        if path == '/versions/old/choices':
                            version = {'id': 'old', 'title': 'Fixture title', 'label': 'v1', 'filename': 'renamed.pdf', 'status': 'ready'}
                            payload = {'incoming': version, 'versions': [version, {**version, 'id': 'new', 'label': 'v7', 'is_current': True}],
                                       'work_id': 'work', 'newer_version_id': 'new', 'requires_choice': True, 'notice': 'Fixture 选择', 'version_notice': 'Fixture 库中较新版本'}
                        elif path == '/versions/compare':
                            payload = {'counts': {'modified': 1, 'unchanged': 2}, 'changes': [{'kind': 'modified',
                                'before': {'text': 'Fixture previous text.', 'page_index': 0}, 'after': {'text': 'Fixture changed text.', 'page_index': 1}}], 'notice': 'Fixture 确定性版本差异'}
                        elif path == '/versions/resolve': payload = {'status': 'completed'}
                        elif path == '/documents/old/reference-analysis':
                            payload = report if method == 'POST' or any(c['method'] == 'POST' and c['path'] == path for c in calls) else {'status': 'not_run', 'references': [], 'version_id': 'old', 'parse_id': 'old-snapshot'}
                        elif path == '/reference-analyses/analysis/classify':
                            report['references'][0]['classification'] = {'status': 'model_assisted', 'label': 'background'}
                            payload = {'id': 'classify', 'status': 'queued'}
                        elif path == '/runs/classify': payload = {'id': 'classify', 'status': 'completed', 'error': None, 'result': {}}
                        elif path == '/reference-analyses/analysis/downloads': payload = {'id': 'batch', 'status': batch['status']}
                        elif path == '/reference-downloads/batch/cancel':
                            batch['status'] = 'cancelled'; payload = batch
                        elif path == '/reference-downloads/batch/resume':
                            batch['status'] = 'queued'; payload = batch
                        elif path == '/reference-downloads/batch': payload = batch
                        else: raise AssertionError('Unmocked fixture API: ' + path)
                        request.fulfill(status=200, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))
                    page.route('**/api/v1/**', route)
                    page.goto(url)
                    page.get_by_role('dialog').wait_for()
                    page.get_by_role('button', name='查看差异', exact=True).click()
                    page.get_by_text('modified: 1', exact=False).wait_for()
                    page.get_by_text('modified ·', exact=False).click()
                    page.get_by_text('Fixture changed text.', exact=True).wait_for()
                    assert page.get_by_role('button', name='保留较新版本 v7（推荐）').is_enabled()
                    page.get_by_role('button', name='两个都保留', exact=True).click()
                    page.get_by_test_id('notice').filter(has_text='版本选择已保存').wait_for()
                    page.get_by_text('参考文献重要性与批量下载', exact=True).click()
                    page.get_by_role('button', name='分析正文引用', exact=True).click()
                    page.get_by_text('正文引用 3 次', exact=False).wait_for()
                    page.get_by_text('正文引用 3 次', exact=False).click()
                    page.get_by_role('button', name='查看正文原文', exact=True).click()
                    page.get_by_test_id('notice').filter(has_text='body1 old-snapshot').wait_for()
                    page.get_by_role('button', name='Lite 分类（消耗轻量调用）', exact=True).click()
                    page.get_by_text('背景（模型辅助，待核验）', exact=False).wait_for()
                    page.get_by_role('spinbutton').fill('2')
                    page.get_by_role('button', name='下载最常引用的 2 篇', exact=True).click()
                    page.get_by_role('button', name='取消下载', exact=True).click()
                    page.get_by_role('button', name='恢复尚未发送的项目', exact=True).click()
                    page.get_by_role('button', name='取消下载', exact=True).wait_for()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    assert next(c['body'] for c in calls if c['path'] == '/versions/resolve')['action'] == 'both'
                    assert next(c['body'] for c in calls if c['path'].endswith('/downloads'))['top_n'] == 2
                    page.screenshot(path=str(OUT / f'fixture-{width}.png'), full_page=True)
                    results.append({'viewport': [width, height], 'status': 'PASS', 'assertions': 12, 'fixture_api_requests': len(calls), 'page_errors': errors})
                    page.close()
                browser.close()
            (OUT / 'report.json').write_text(json.dumps({'type': 'explicit_browser_fixture', 'live_api_calls': 0, 'results': results}, indent=2))
            print(json.dumps({'status': 'PASS', 'viewports': len(results), 'assertions': sum(r['assertions'] for r in results), 'report': str(OUT / 'report.json')}))
        finally:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
            log.close()


if __name__ == '__main__': main()
